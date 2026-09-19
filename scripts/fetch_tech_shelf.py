"""Build the engineer's shelf (#58): fetch -> one Markdown file per work -> pins.

The second demo corpus is a shelf of openly licensed engineering books, guides
and papers. Unlike the classics, none of its text is committed: every work is
fetched from its publisher at build time, converted to a single Markdown file
under `corpus-tech/prepared/`, and indexed into an index of its own with the
generic folder ingest:

    LIBRARY_DB_PATH=~/ayl-tech uv run ayl-add corpus-tech/prepared

corpus-tech/manifest.yaml is the single source of truth for what the shelf
holds, where each work comes from, under which licence, and the sha256 of every
file that was fetched to build it — taken per the work's `pin:`, which is
`bytes` for a PDF or a file out of a git repository and `text` for a page read
off the web, because two of these publishers do not serve the same bytes twice
(see `digest_of`). Three of the works are CC BY-NC-ND: they are
fetched as text, and their committed card is a structure card — title, chapter
list and the publisher's own description, reproduced verbatim and built by code
(`cards: structure` in the manifest) — because a model-written card is a
derivative and ND forbids distributing one. The licence does let a reader make
one for themself (section 2(a)(1)(B)), so they also get a model-written card
(`local_card: true`) that is written only under AYL_HOME, outside any checkout:
`card_dir` sends every model-written card of a NoDerivatives work there, and
`ask_your_library.home.private_dir` refuses a folder inside a git work tree.

Stages (all cached in corpus-tech/raw/, safe to re-run):
  uv run scripts/fetch_tech_shelf.py --stage fetch      # download, nothing else
  uv run scripts/fetch_tech_shelf.py --stage prepare    # raw -> prepared/<id>.md
  uv run scripts/fetch_tech_shelf.py --stage toc        # prepared -> toc/<id>.json
  uv run scripts/fetch_tech_shelf.py --stage structure-cards  # manifest + toc -> cards/<id>.md, no model
  uv run scripts/fetch_tech_shelf.py --stage checksums  # pin the fetched files
  uv run scripts/fetch_tech_shelf.py --stage verify     # re-hash them against the pins
  uv run scripts/fetch_tech_shelf.py --work sre         # substring filter on the title

`--stage cards` is the one stage that calls a model, so it is asked for by name
and never runs as part of `--stage all`:

  uv run scripts/fetch_tech_shelf.py --stage cards                 # every work that may have one
  uv run scripts/fetch_tech_shelf.py --stage cards --work twelve   # one of them
  uv run scripts/fetch_tech_shelf.py --stage cards --force         # rebuild cards already written

It writes corpus-tech/cards/<id>.md for a `shared` work and
$AYL_HOME/cards/tech/<id>.md for a local one (a `cards: local` work, and a
`structure` work with `local_card: true`), through the repository's own client
(`ask_your_library.llm.llm_invoke`), so LLM_BACKEND=ollama|openrouter picks the
backend and the egress and observer rules of ADR-017 apply unchanged, and it
records in each card which backend and model wrote it. The cards are indexed
into the shelf's own index with
`scripts/ingest_demo_corpus.py --stage cards --cards-dir corpus-tech/cards
--cards-dir ~/AskYourLibrary/cards/tech`.

Every other stage is deliberately separate from `scripts/ingest_demo_corpus.py`:
that script owns the classics index and embeds; these ones write files and
nothing else, so they need no model, no database and no embedding backend.

Fetch kinds, one per shape of source (`fetch:` in the manifest):
  html-chapters  one HTML page per chapter, listed by the site's own table of
                 contents (sre.google, abseil.io) — or a single long page whose
                 own `<h2>`s are the chapters (developers.google.com)
  git-markdown   Markdown files in a git repository, in the order the manifest
                 lists them (heroku/12factor)
  git-html       HTML files in a git repository, in the order the repository's
                 own build manifest lists them (google/building-secure-and-
                 reliable-systems ships the book's HTML, not Markdown)
  pdf            a published PDF, split into chapters by `chapter_regex`
  arxiv-html     arXiv's own HTML rendering, https://arxiv.org/html/<id>
  arxiv-pdf      the paper's PDF, https://arxiv.org/pdf/<id>. No work on the
                 shelf uses it: #58 planned it for ReAct and Chain-of-Thought,
                 on the rule that arXiv renders HTML only for submissions from
                 December 2023 on, and arXiv has since rendered both. The kind
                 stays because the next paper added may be one it has not.

Nothing here needs a dependency the lockfile does not already have: `requests`
and `pyyaml` are the project's, the HTML is converted by a small reader built on
`html.parser` from the standard library, and a PDF is read through `pdftotext`
(poppler) as a subprocess — the one external tool, and a work whose PDF cannot
be read is reported and left unprepared rather than silently skipped.
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

import requests
import yaml

REPO = Path(__file__).resolve().parents[1]
SHELF = REPO / "corpus-tech"
MANIFEST = SHELF / "manifest.yaml"
RAW_DIR = SHELF / "raw"            # fetched sources, gitignored
PREPARED_DIR = SHELF / "prepared"  # one .md per work, gitignored
# Chapter titles per work, committed: the shelf's text is not in this repository,
# so the table of contents is the only reviewable record of what a work's
# chapters are and which edition the golden questions were written against.
TOC_DIR = SHELF / "toc"

# The page order a fetch worked out, written next to the pages it fetched. It is
# pinned like a fetched file on purpose: a publisher that re-orders or renames a
# chapter changes this file, and the weekly job then says so.
PAGES_INDEX = "_pages.json"

# One request at a time, named, with a pause between them: a full fetch is ~170
# requests to four hosts, and from CI they all leave one shared runner IP.
USER_AGENT = ("ask-your-library-corpus-ingest/1.0 "
              "(+https://github.com/ievgen-borysenko/ask-your-library)")
HEADERS = {"User-Agent": USER_AGENT}
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_S = 5   # then doubled: 5s, 10s
DOWNLOAD_PAUSE_S = 1     # between two requests, so a work is not a burst


# The fetch kinds whose text comes out of `pdftotext` (poppler), the one
# external tool: a machine without it leaves these out with --skip-pdf.
PDF_FETCH_KINDS = ("pdf", "arxiv-pdf")


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def works(manifest: dict) -> list[dict]:
    return manifest["works"]


# What `cards:` in the manifest may say, and nothing else (see its header). It
# names the card the REPOSITORY carries for a work, if any.
CARD_POLICIES = ("shared", "structure", "local")
# The policies whose card a model writes. `structure` is not one of them: a
# structure work's model-written card, if it has one, is `local_card: true`.
MODEL_CARD_POLICIES = ("shared", "local")
# Where a local card of this shelf goes under AYL_HOME: $AYL_HOME/cards/tech/.
SHELF_NAME = "tech"


def card_policy(work: dict) -> str:
    """The work's `cards:` value. A work that names none is `local`: a card
    nobody decided may be shared is built where it is read and never committed.
    A value that is not one of the three is a mistake in the manifest, not a
    fourth kind of card, and is refused rather than guessed at."""
    policy = work.get("cards", "local")
    if policy not in CARD_POLICIES:
        raise ValueError(f"{work['id']}: cards is {policy!r}, not one of "
                         f"{', '.join(CARD_POLICIES)}")
    return policy


def local_card(work: dict) -> bool:
    """`local_card: true`: a `structure` work that ALSO gets a model-written card,
    built on the reader's machine for the reader and never committed.

    A second field rather than a fourth `cards:` value, because it answers a
    second question. `cards:` is what the repository ships for the work (plan
    of 2026-09-18, section 3.1: shared, structure or local); this is whether the
    reader's machine builds a model card besides it (section 2's "built" tier).
    It is only meaningful beside `structure`: a `shared` work's model card is the
    committed one, and a `local` work's model card is local already."""
    value = work.get("local_card", False)
    if not isinstance(value, bool):
        raise ValueError(f"{work['id']}: local_card is {value!r}, not true or false")
    if value and card_policy(work) != "structure":
        raise ValueError(f"{work['id']}: local_card belongs beside cards: structure, "
                         f"not cards: {card_policy(work)}")
    return value


# The shape of a licence identifier in the manifest: SPDX-style, one token, no
# spaces ("CC-BY-NC-ND-4.0", not "CC BY-NC-ND 4.0"). The manifest test refuses
# anything else, so the checks below never meet a form they were not written for.
LICENCE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+-]*")


def licence_terms(work: dict) -> list[str]:
    """The licence identifier cut into its terms, on hyphens AND whitespace, so a
    spaced form still yields its "ND" or "SA" rather than failing open."""
    return [term for term in re.split(r"[-\s_]+", str(work.get("licence", "")).upper()) if term]


def no_derivatives(work: dict) -> bool:
    """Whether the work's licence withholds adaptations (CC ...-ND-...). A work
    with no licence at all counts as one: nobody may adapt what nobody licensed."""
    terms = licence_terms(work)
    return not terms or "ND" in terms


def share_alike(work: dict) -> bool:
    """Whether an adaptation of the work must carry the work's own licence."""
    return "SA" in licence_terms(work)


def wants_model_card(work: dict) -> bool:
    """Whether the manifest asks for a model-written card of this work at all."""
    return card_policy(work) in MODEL_CARD_POLICIES or local_card(work)


def model_card_is_local(work: dict) -> bool:
    """Whether this work's model-written card is local — written under AYL_HOME
    and never into the repository tree. Always, for a NoDerivatives work, read
    off its licence whatever `cards:` says: CC BY-NC-ND lets the reader make an
    adaptation for themself and withholds sharing one (section 2(a)(1)(B))."""
    return card_policy(work) != "shared" or no_derivatives(work)


def card_targets(manifest: dict) -> list[dict]:
    """The works a MODEL may write a card for, and the only list the model-card
    stage is allowed to read.

    A book card is a summary written from the work — a derivative — so for a
    CC BY-NC-ND work distributing one is exactly what the licence withholds,
    while making one for the reader is what it grants. The licence is read here
    as well as the manifest: a NoDerivatives work is offered only when the
    manifest itself asks for a LOCAL model card (`cards: local`, or `structure`
    with `local_card: true`), so a work mislabelled `shared` is skipped before
    its text is read — and `card_dir` sends every card of an ND work to AYL_HOME
    regardless (#58)."""
    return [work for work in works(manifest)
            if wants_model_card(work)
            and not (no_derivatives(work) and card_policy(work) == "shared")]


def structure_targets(manifest: dict) -> list[dict]:
    """The works whose card is built by code from the manifest and the chapter
    list: `cards: structure`."""
    return [work for work in works(manifest) if card_policy(work) == "structure"]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --- fetching ----------------------------------------------------------------

def fetch(url: str, attempts: int = DOWNLOAD_ATTEMPTS) -> bytes:
    """GET `url`, retrying only what is worth retrying.

    429 and 5xx are the host saying "later", and a connection error or a read
    timeout is usually the same answer seen from this end; everything else — a
    404 on a URL this repository got wrong — is a fact about the request and
    fails on the first attempt rather than three times slowly. The bytes are
    returned undecoded because the same path fetches HTML, Markdown and PDFs,
    and only the caller knows which."""
    delay = DOWNLOAD_BACKOFF_S
    for attempt in range(1, attempts + 1):
        try:
            response = requests.get(url, timeout=120, headers=HEADERS)
        except (requests.ConnectionError, requests.Timeout) as exc:
            problem = f"{type(exc).__name__}: {exc}"
        else:
            if response.status_code < 400:
                return response.content
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()   # ours to fix, not the host's
            problem = f"HTTP {response.status_code}"
        if attempt == attempts:
            sys.exit(f"giving up on {url} after {attempts} attempts — {problem}")
        print(f"    {problem}; retrying in {delay}s ({attempt}/{attempts - 1})", flush=True)
        time.sleep(delay)
        delay *= 2
    raise AssertionError("unreachable")   # pragma: no cover


def fetch_to(url: str, path: Path, refetch: bool = False) -> bool:
    """Download `url` to `path` unless it is already there. Returns True when a
    request was actually made, so the caller can pause only between requests and
    a re-run of a finished fetch costs the hosts nothing."""
    if path.exists() and not refetch:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(fetch(url))
    return True


def raw_dir(work: dict) -> Path:
    return RAW_DIR / work["id"]


# --- a very small HTML reader ------------------------------------------------
# Enough of HTML to turn a published chapter into Markdown, and no more: the
# lockfile has no HTML library and this needs neither a DOM nor CSS selectors.
# What it keeps is what a reader would read aloud — headings, paragraphs, lists,
# quotes, code, definition lists and table cells — and what it drops is the page
# around them.

# Dropped with everything inside them. `sup` is in the list because a footnote
# marker renders as a digit glued to the last word of a sentence ("goals,19"),
# which is a word the full-text index would then hold and nobody would search.
SKIP_TAGS = {"script", "style", "nav", "footer", "header", "aside", "form",
             "svg", "noscript", "sup", "iframe", "button", "select",
             # An image, however it is embedded. `object` is here and `figure`
             # is NOT: a figure is dropped in the shape that holds a picture and
             # kept in the shape that holds text. On arXiv that distinction is
             # the whole appendix of a paper — ReAct's prompt trajectories and
             # Chain-of-Thought's exemplars are `<figure>`s of text, and they are
             # what a reader of those papers quotes. A figure that really is only
             # a picture leaves nothing behind to flush and disappears by itself.
             "object", "picture", "video", "audio"}
VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "col", "source"}
BLOCK_TAGS = {"p", "div", "section", "article", "ul", "ol", "dl", "table",
              "tr", "figure", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
              "li", "dt", "dd", "pre", "td", "th", "figcaption", "main"}
HEADINGS = {f"h{level}": level for level in range(1, 7)}
CODE_INDENT = "    "

# What a prepared file's body may never contain: a line that a chapter splitter
# reads as a heading. `#` and `##` at column zero are the file's own structure —
# the work's title and its chapters — and a body line that looks like one is a
# chapter cut in the wrong place, in this repository's `write_toc` and in
# `ayl-add` alike.
BODY_HEADING = re.compile(r"(?m)^#{1,2}[ \t]")


def _matches(tag: str, attrs: dict, spec: str) -> bool:
    """Whether an element matches a container spec from the manifest: `tag`,
    `tag#id` or `tag.class`. Three shapes, because that is all four publishers
    need and a CSS engine to read four selectors would be the larger risk."""
    want_tag, _, rest = spec.partition("#") if "#" in spec else spec.partition(".")
    if want_tag and tag != want_tag:
        return False
    if "#" in spec:
        return attrs.get("id") == rest
    if "." in spec:
        return rest in (attrs.get("class") or "").split()
    return True


class MarkdownReader(HTMLParser):
    """HTML -> a list of blocks: ("heading", level, text) or ("text", text).

    `container` limits the reading to one element of the page (the manifest's
    `container:`, e.g. "div#content"), which is how the site's navigation,
    banner and footer are left out without a list of class names per publisher.
    Blocks, not a string, because the caller decides at which level a heading
    sits once it knows whether the page is a chapter or a whole book."""

    def __init__(self, container: str | None = None):
        super().__init__(convert_charrefs=True)
        self.container = container
        self.blocks: list[tuple] = []
        self._collecting = container is None
        self._container_depth = 0
        self._skip_depth = 0
        self._open: list[str] = []
        self._buf: list[str] = []
        self._pending: tuple | None = None   # the block the buffer belongs to
        self._row: list[str] = []
        self._pre = False
        self._quote = 0

    # -- block bookkeeping
    def _flush(self) -> None:
        text = re.sub(r"[ \t]+\n", "\n", "".join(self._buf))
        text = text.strip() if not self._pre else text.strip("\n")
        self._buf = []
        if not text:
            self._pending = None
            return
        if self._pending and self._pending[0] == "heading":
            self.blocks.append(("heading", self._pending[1], " ".join(text.split())))
        elif self._quote:
            # Everything inside a blockquote is quoted, including the separate
            # paragraphs a published pull quote is built from.
            self.blocks.append(("text", "> " + text.replace("\n", "\n> ")))
        elif self._pending and self._pending[0] == "item":
            self.blocks.append(("text", "- " + " ".join(text.split())))
        elif self._pending and self._pending[0] == "term":
            self.blocks.append(("text", f"**{' '.join(text.split())}**"))
        elif self._pending and self._pending[0] == "pre":
            # An INDENTED code block, never a fenced one. A fence is invisible
            # to a line-based reader, and every reader of a prepared file is
            # line-based: `ayl-add` cuts a Markdown book on `#`/`##` at column
            # zero with one regex over the whole file, and so does `write_toc`
            # below. Inside a fence that regex still matches, so a shell or
            # Python comment in a code sample — "# Get all active machines in
            # satellite" — opens a section of its own, cuts the chapter it sits
            # in half, and puts a comment line into the index as the section
            # title the agent then cites. Eighteen of those across this shelf.
            # Four leading spaces are what Markdown means by preformatted text,
            # they keep every character of the line, and nothing can read them
            # as a heading (#58).
            self.blocks.append(("text", "\n".join(
                CODE_INDENT + line if line.strip() else line
                for line in text.split("\n"))))
        else:
            self.blocks.append(("text", text))
        self._pending = None

    def handle_starttag(self, tag, attrs):
        attrs = {name: value or "" for name, value in attrs}
        if tag in VOID_TAGS:
            if self._collecting and self._skip_depth == 0 and tag == "br":
                self._buf.append("\n")
            return
        self._open.append(tag)
        if self._skip_depth:
            self._skip_depth += 1
            return
        if not self._collecting:
            if self.container and _matches(tag, attrs, self.container):
                self._collecting = True
                self._container_depth = len(self._open)
            return
        if tag in SKIP_TAGS:
            self._flush()
            self._skip_depth = 1
            return
        if tag in BLOCK_TAGS:
            self._flush()
        if tag in HEADINGS:
            self._pending = ("heading", HEADINGS[tag])
        elif tag == "blockquote":
            self._quote += 1
        elif tag == "li":
            self._pending = ("item",)
        elif tag == "dt":
            self._pending = ("term",)
        elif tag == "pre":
            self._pending = ("pre",)
            self._pre = True

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if tag in self._open:
            # Unclosed inline tags are common in published HTML; drop back to
            # the matching open tag rather than trusting the document.
            while self._open and self._open.pop() != tag:
                pass
        if self._skip_depth:
            self._skip_depth -= 1
            return
        if not self._collecting:
            return
        if tag in ("td", "th"):
            self._row.append(" ".join("".join(self._buf).split()))
            self._buf = []
            self._pending = None
            return
        if tag == "tr":
            if any(self._row):
                self.blocks.append(("text", "| " + " | ".join(self._row) + " |"))
            self._row = []
            return
        if tag in BLOCK_TAGS:
            self._flush()
        if tag == "pre":
            self._pre = False
        if tag == "blockquote":
            self._quote = max(0, self._quote - 1)
        if self.container and self._collecting and len(self._open) < self._container_depth:
            self._collecting = False

    def handle_data(self, data):
        if self._collecting and not self._skip_depth:
            self._buf.append(data if self._pre else re.sub(r"\s+", " ", data))

    def close(self):
        super().close()
        self._flush()


def read_html(html: str, container: str | None = None) -> list[tuple]:
    reader = MarkdownReader(container)
    reader.feed(html)
    reader.close()
    return reader.blocks


def same_heading(one: str, other: str) -> bool:
    """Whether two headings name the same chapter, ignoring the numbering the
    table of contents adds ("5. Eliminating Toil" is "Eliminating Toil")."""
    def bare(text: str) -> str:
        # The number is matched before anything is lowercased: a roman numeral
        # or an appendix letter is a capital, and one followed by punctuation,
        # so "III. Config" loses "III. " while "A Collection" keeps its "A".
        return re.sub(r"^(?:(?i:chapter|part|appendix)\s+)?"
                      r"(?:\d+(?:\.\d+)*[.\-):]?\s+|[IVXLC]+[.\-):]\s*|[A-F][.\-):]\s*)?",
                      "", text.strip()).lower()
    return bare(one) == bare(other)


def as_body_line(text: str) -> str:
    """A text block none of whose lines can be read as a chapter heading.

    A `<pre>` is indented whole, above, and that covers most code. What it does
    not cover is a publisher who renders a code listing as one element per LINE:
    arXiv wraps each line of a Python listing in its own `<div>`, so a comment
    line arrives here as a block of its own with `#` at column zero — four of
    them in the bge-m3 appendix, each of which would cut that appendix into
    pieces named after a comment. Only the offending line is indented, and only
    by the four spaces Markdown reads as preformatted text: the line keeps every
    character it had, and it keeps its place in the chapter (#58)."""
    if not BODY_HEADING.search(text):
        return text
    return "\n".join(CODE_INDENT + line if BODY_HEADING.match(line) else line
                     for line in text.split("\n"))


def render(blocks: list[tuple], demote: int = 0, skip_title: str | None = None) -> str:
    """Blocks -> Markdown, inside one chapter.

    No heading rendered here may reach level 2: `##` is what the ingest cuts
    chapters on, and the chapter's own heading is written by the caller. The
    publishers disagree about which level a section is — sre.google gives the
    chapter title an `<h2>` and its sections `<h1>` — so the levels are clamped
    rather than trusted, and a first heading that merely repeats the chapter
    title is dropped instead of printed twice."""
    pieces = []
    for index, block in enumerate(blocks):
        if block[0] == "heading":
            if skip_title and index == 0 and same_heading(block[2], skip_title):
                continue
            level = min(6, max(block[1] + demote, demote + 2))
            pieces.append("#" * level + " " + block[2])
        else:
            pieces.append(as_body_line(block[1]))
    # Newlines only: a chapter that opens with a code sample opens with four
    # spaces of indentation, and that indentation is what keeps the sample from
    # being read as a heading.
    return "\n\n".join(pieces).strip("\n")


def first_heading(blocks: list[tuple], level: int = 1) -> str | None:
    for block in blocks:
        if block[0] == "heading" and block[1] == level:
            return block[2]
    return None


def links_in(html: str) -> list[tuple[str, str]]:
    """(href, text) for every link, in document order, entities resolved. A
    table of contents is read with this and nothing else: the page's own order
    is the book's order."""
    found = []
    for match in re.finditer(r"<a\b[^>]*\bhref=\"([^\"]*)\"[^>]*>(.*?)</a>", html,
                             re.S | re.I):
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", match.group(2))).split())
        found.append((unescape(match.group(1)), text))
    return found


# --- PDF text ----------------------------------------------------------------

# A small-caps section heading comes out of a PDF letter by letter
# ("I NTRODUCTION", "R ELATED W ORK"): the glyphs are separate in the file and
# nothing in the text layer says they are one word. Repaired on short lines
# only, where a run of a single capital followed by capitals is a heading and
# never a sentence.
SPACED_CAPS = re.compile(r"\b([A-Z])[ ]([A-Z]{2,})\b")
SINGLE_CAPS = re.compile(r"\b(?:[A-Z][ ]){2,}[A-Z]\b")
# The dots that lead the eye to a page number in a printed table of contents.
DOT_LEADER = re.compile(r"\.\s*\.\s*\.")
# A number with a decimal point anywhere after the section number: a measured
# value, and so a table row rather than a heading.
MEASUREMENT = re.compile(r"\s\d+\.\d")


def pdf_text(path: Path) -> str:
    """The text layer of a PDF, through `pdftotext` (poppler).

    Not a Python dependency: the lockfile has no PDF reader, and adding one for
    three files of the shelf would be a dependency on every install of this
    project. A missing `pdftotext` is reported by the caller and leaves the work
    unprepared — never silently empty."""
    if shutil.which("pdftotext") is None:
        raise FileNotFoundError(
            "pdftotext (poppler) is not installed — it is what reads the PDF works of "
            "the shelf (today only OWASP; `arxiv-pdf` would be the other). `brew install poppler` on "
            "macOS, `apt-get install poppler-utils` on Debian/Ubuntu.")
    done = subprocess.run(["pdftotext", "-q", str(path), "-"],
                          capture_output=True, text=True, check=True)
    return done.stdout


def strip_page_furniture(text: str) -> list[str]:
    """PDF text -> lines with the page numbers and the running header removed.

    Both are printed on every page and both look exactly like the thing this
    module is trying to find: a page number is a line holding one number, and a
    running header ("Published as a conference paper at ICLR 2023") is a short
    line of title case right under it. Left in, they turn every page break into
    a numbered section and a paper gains thirty chapters that are all called the
    same thing.

    Two facts separate them from the text. A page number sits immediately before
    the page break — pdftotext writes a form feed at the start of the next page,
    which is what identifies it. And a running header is repeated: a line of
    three words or more that appears four times or more in a document is the
    page's furniture, not a sentence of the book."""
    lines = text.split("\n")
    repeated = {}
    for line in lines:
        stripped = line.replace("\x0c", "").strip()
        if len(stripped.split()) >= 3 and len(stripped) <= 90:
            repeated[stripped] = repeated.get(stripped, 0) + 1

    kept = []
    for index, line in enumerate(lines):
        stripped = line.replace("\x0c", "").strip()
        if repeated.get(stripped, 0) >= 4:
            continue
        if re.fullmatch(r"\d{1,3}", stripped):
            ahead = index + 1
            while ahead < len(lines) and not lines[ahead].strip():
                ahead += 1
            if ahead < len(lines) and "\x0c" in lines[ahead]:
                continue      # the number printed at the foot of the page
        kept.append(stripped if "\x0c" in line else line)
    return kept


def normalise_pdf_lines(text: str) -> list[str]:
    """PDF text -> lines a chapter regex can match.

    Page furniture is removed, the letter-by-letter small caps above are joined,
    and a section number that the layout put on a line of its own is put back in
    front of its heading ("1" + "I NTRODUCTION" -> "1 Introduction"). Body text
    is left exactly as it is: only short lines are touched."""
    lines = [line.replace("\x0c", "") for line in strip_page_furniture(text)]
    out: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if re.fullmatch(r"\d+(?:\.\d+)*", line):
            # The heading this number belongs to is the next non-empty line.
            ahead = index + 1
            while ahead < len(lines) and not lines[ahead].strip():
                ahead += 1
            if ahead < len(lines) and 0 < len(lines[ahead].strip()) <= 70:
                out.append(f"{line} {tidy_heading(lines[ahead].strip())}")
                index = ahead + 1
                continue
        out.append(tidy_heading(line) if len(line) <= 70 else line)
        index += 1
    return out


def tidy_heading(line: str) -> str:
    """One short line with its small caps joined back into words."""
    if not SINGLE_CAPS.search(line) and not SPACED_CAPS.search(line):
        return line
    joined = line
    for _ in range(4):   # "R E A C T" needs several passes, one pair at a time
        joined = SPACED_CAPS.sub(r"\1\2", joined)
        joined = re.sub(r"\b([A-Z])[ ]([A-Z])\b", r"\1\2", joined)
    return " ".join(
        word if not word.isupper() or len(word) <= 3 else word.title()
        for word in joined.split())


def follows(previous: tuple, number: tuple) -> bool:
    """Whether `number` can be the next section number after `previous`.

    Sections count up by one and sub-sections belong to the section they
    follow. The tolerated step of two is for a heading the page layout swallowed
    — Chain-of-Thought loses both its "1 Introduction" and its "5 Symbolic
    Reasoning" to a column break, and a run that stops at the first missing
    heading would end that paper after four sections."""
    if len(number) == 1:
        return number[0] in (previous[0] + 1, previous[0] + 2)
    if len(number) == 2 and number[0] == previous[0]:
        return number[1] == (previous[1] + 1 if len(previous) == 2 else 1)
    return False


def numbered_chain(headings: list[tuple[int, str, tuple]]) -> list[tuple[int, str]]:
    """The longest run of candidate headings whose numbers actually run in
    sequence, starting at section 1 or 2.

    A two-column paper's tables are full of lines that look exactly like a
    numbered heading ("60.4 Act", "20 Method"), and a regex alone cannot tell
    them from "4 Decision Making Tasks". Section numbers can: they run in order.
    The longest such run is taken rather than the first, because a table that
    happens to start with a plausible "1" would otherwise capture the whole
    paper — so this is a longest-chain search, not a greedy walk."""
    longest = [0] * len(headings)      # chain length ending at this candidate
    came_from = [-1] * len(headings)
    for index, (_, _, number) in enumerate(headings):
        if len(number) == 1 and number[0] in (1, 2):
            longest[index] = 1
        for earlier in range(index):
            if longest[earlier] and follows(headings[earlier][2], number) \
                    and longest[earlier] + 1 > longest[index]:
                longest[index] = longest[earlier] + 1
                came_from[index] = earlier
    if not any(longest):
        return []
    end = max(range(len(headings)), key=lambda index: longest[index])
    chain = []
    while end != -1:
        chain.append(headings[end])
        end = came_from[end]
    return [(line, title) for line, title, _ in reversed(chain)]


def split_pdf_chapters(text: str, chapter_regex: str, lead: str) -> list[tuple[str, str]]:
    """[(title, body)] for a PDF, cut at the lines `chapter_regex` matches.

    Everything before the first heading is one chapter under `lead` (a paper's
    title, authors and abstract; OWASP's licence page and table of contents) —
    nothing of the file is dropped."""
    lines = normalise_pdf_lines(text)
    pattern = re.compile(chapter_regex)
    candidates = []
    for number, line in enumerate(lines):
        if DOT_LEADER.search(line):
            # A line of the document's own table of contents ("LLM01:2025 Prompt
            # Injection . . . 3") matches every heading pattern its headings do.
            continue
        if pattern.match(line):
            if MEASUREMENT.search(line):
                # A row of a results table reads as a numbered heading ("4.1
                # Chain of thought 4.4 (+0.3)"); a section title does not carry
                # a decimal number.
                continue
            digits = re.match(r"(\d+(?:\.\d+)*)\s", line)
            order = tuple(int(part) for part in digits.group(1).split(".")) if digits else ()
            candidates.append((number, line.strip(), order))
    if candidates and all(candidate[2] for candidate in candidates):
        starts = numbered_chain(candidates)
    else:
        starts = [(number, title) for number, title, _ in candidates]

    chapters = []
    first = starts[0][0] if starts else len(lines)
    head = "\n".join(lines[:first]).strip()
    if head:
        chapters.append((lead, head))
    for index, (line, title) in enumerate(starts):
        end = starts[index + 1][0] if index + 1 < len(starts) else len(lines)
        body = "\n".join(lines[line + 1:end]).strip()
        chapters.append((title, body or title))
    return chapters


# --- fetch, per kind ---------------------------------------------------------

def page_list(work: dict) -> list[dict]:
    """[{url, file, title}] for a work made of HTML pages, from the publisher's
    own table of contents. Written to `_pages.json` beside the pages so that
    `prepare` needs no network and so that a re-ordered or renamed chapter shows
    up as a changed pin."""
    source = work["source"]
    if not work.get("page_pattern"):
        # One long page: its own headings are the chapters (Rules of ML).
        return [{"url": source, "file": "index.html", "title": work["title"]}]
    html = fetch(source).decode("utf-8", "replace")
    time.sleep(DOWNLOAD_PAUSE_S)
    pattern = re.compile(work["page_pattern"])
    pages, seen = [], set()
    for href, text in links_in(html):
        href = href.split("#")[0]
        if not pattern.match(href) or href in seen:
            continue
        seen.add(href)
        pages.append({"url": requests.compat.urljoin(source, href),
                      "file": Path(href.rstrip("/")).name + ".html"
                              if not href.endswith(".html") else Path(href).name,
                      "title": text})
    if not pages:
        sys.exit(f"{work['id']}: the table of contents at {source} matched no page — "
                 f"page_pattern {work['page_pattern']!r} no longer fits the site")
    return pages


def git_page_list(work: dict) -> list[dict]:
    """[{url, file, title}] for a work held in a git repository.

    `paths:` lists the files in reading order; `order_file:` names a file in the
    repository that lists them itself (Building Secure and Reliable Systems
    ships the book's build manifest, which is the publisher's own order and
    stays right when a chapter is added)."""
    base = f"https://raw.githubusercontent.com/{work['repo']}/{work['ref']}/"
    if work.get("order_file"):
        listed = json.loads(fetch(base + work["order_file"]).decode("utf-8"))["files"]
        time.sleep(DOWNLOAD_PAUSE_S)
        skip = set(work.get("skip_files") or [])
        directory = work["order_file"].rsplit("/", 1)[0]
        paths = [f"{directory}/{name}" for name in listed if name not in skip]
    else:
        paths = work["paths"]
    return [{"url": base + path, "file": Path(path).name, "title": ""} for path in paths]


def single_file_name(work: dict) -> str:
    """The raw file of a work that is one document: the arXiv identifier for a
    paper (so the file says which paper it is), the work's id otherwise."""
    if work["fetch"] == "pdf":
        return f"{work['id']}.pdf"
    suffix = "pdf" if work["fetch"] == "arxiv-pdf" else "html"
    return f"{work['arxiv_id']}.{suffix}"


def fetch_work(work: dict, refetch: bool = False) -> None:
    """Download everything one work is built from into corpus-tech/raw/<id>/."""
    target = raw_dir(work)
    kind = work["fetch"]
    if kind in ("pdf", "arxiv-pdf", "arxiv-html"):
        url = work["source"]
        name = single_file_name(work)
        if fetch_to(url, target / name, refetch):
            time.sleep(DOWNLOAD_PAUSE_S)
        print(f"  {work['id']}: {name}")
        return

    pages = (git_page_list(work) if kind.startswith("git-") else page_list(work))
    fetched = 0
    for page in pages:
        if fetch_to(page["url"], target / page["file"], refetch):
            fetched += 1
            time.sleep(DOWNLOAD_PAUSE_S)
    (target / PAGES_INDEX).write_text(
        json.dumps(pages, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"  {work['id']}: {len(pages)} pages ({fetched} downloaded, "
          f"{len(pages) - fetched} cached)")


# --- prepare -----------------------------------------------------------------

def read_pages(work: dict) -> list[dict]:
    index = raw_dir(work) / PAGES_INDEX
    if not index.exists():
        sys.exit(f"{work['id']}: nothing fetched yet ({index} is missing) — "
                 f"run --stage fetch first")
    return json.loads(index.read_text(encoding="utf-8"))


# A link written as HTML inside a Markdown file (heroku/12factor is full of
# them): the text is what a reader reads and what a search should find, the
# markup is not.
INLINE_ANCHOR = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)


def markdown_chapter(text: str) -> tuple[str | None, str]:
    """(title, body) for one Markdown file of a work: its own first heading is
    the chapter title and is not repeated in the body.

    Both heading styles, because one repository uses both: the twelve factors
    open with "## III. Config", the introduction and the background with the
    underlined form ("Introduction" over a row of "=")."""
    text = INLINE_ANCHOR.sub(r"\1", text).strip()
    atx = re.match(r"^#{1,2}\s+(.*)$", text, re.M)
    if atx and atx.start() == 0:
        return atx.group(1).strip(), text[atx.end():].strip()
    setext = re.match(r"^(\S[^\n]*)\n[=-]{3,}\s*$", text, re.M)
    if setext and setext.start() == 0:
        return setext.group(1).strip(), text[setext.end():].strip()
    return None, text


def chapters_of(work: dict) -> list[tuple[str, str]]:
    """[(title, body)] for one work, whatever it was fetched from."""
    kind = work["fetch"]
    directory = raw_dir(work)

    if kind in ("pdf", "arxiv-pdf"):
        return split_pdf_chapters(pdf_text(directory / single_file_name(work)),
                                  work["chapter_regex"],
                                  work.get("lead_section", "Front matter"))

    if kind == "arxiv-html":
        html = (directory / single_file_name(work)).read_text(encoding="utf-8",
                                                              errors="replace")
        return single_page_chapters(html, work)

    if kind == "git-markdown":
        chapters = []
        for page in read_pages(work):
            # The source files are already Markdown with the subheadings the
            # ingest splits on, so the text is carried across as it is; only the
            # chapter's own heading is lifted out, to be written once above.
            title, body = markdown_chapter(
                (directory / page["file"]).read_text(encoding="utf-8"))
            chapters.append((title or Path(page["file"]).stem, body))
        return chapters

    pages = read_pages(work)
    if len(pages) == 1 and not work.get("page_pattern"):
        html = (directory / pages[0]["file"]).read_text(encoding="utf-8", errors="replace")
        return single_page_chapters(html, work)

    chapters = []
    for page in pages:
        html = (directory / page["file"]).read_text(encoding="utf-8", errors="replace")
        blocks = read_html(html, work.get("container"))
        # The publisher's own table of contents names the chapter; the page's
        # first heading is the fallback, for a work fetched from a repository
        # where there is no table of contents to read a title from.
        title = page["title"] or first_heading(blocks) or Path(page["file"]).stem
        chapters.append((title, render(blocks, demote=1, skip_title=title)))
    return chapters


def single_page_chapters(html: str, work: dict) -> list[tuple[str, str]]:
    """One long page -> chapters at its own `<h2>`s (Rules of ML, an arXiv HTML
    paper). What stands before the first one — a paper's abstract, a guide's
    introduction — is kept as the first chapter rather than dropped."""
    blocks = read_html(html, work.get("container"))
    chapters: list[tuple[str, str]] = []
    current: list[tuple] = []
    title = work.get("lead_section", "Front matter")
    for block in blocks:
        if block[0] == "heading" and block[1] == 1:
            continue          # the document title; the file carries it once
        if block[0] == "heading" and block[1] == 2:
            body = render(current, demote=1)
            if body or chapters:
                chapters.append((title, body or title))
            title, current = block[2], []
            continue
        current.append(block)
    body = render(current, demote=1)
    if body or not chapters:
        chapters.append((title, body or title))
    return chapters


def prepare_work(work: dict) -> tuple[int, int]:
    """Write corpus-tech/prepared/<id>.md and return (chapters, characters).

    The shape is the one `ayl-add` reads without being told anything: YAML front
    matter with `title:` and `author:` (the book key the agent cites), the work's
    title as the single `#`, and one `##` per chapter — the headings
    `ingest/chapters.py` splits sections on."""
    chapters = [(title, body) for title, body in chapters_of(work) if body.strip()]
    # The shape is a promise about where the chapters are, so it is checked here
    # rather than discovered later as a section named after a line of somebody's
    # shell script. A body line that reads as `#` or `##` means this work cannot
    # be cut correctly by anything, and the work is named instead of written.
    strays = [(title, line) for title, body in chapters
              for line in body.split("\n") if BODY_HEADING.match(line)]
    if strays:
        raise ValueError(
            f"{len(strays)} body line(s) would be read as a chapter heading, e.g. "
            + "; ".join(f"{title!r}: {line[:60]!r}" for title, line in strays[:3]))
    lines = ["---", f"title: \"{work['title']}\"", f"author: \"{work['author']}\"", "---", "",
             f"# {work['title']}", ""]
    for title, body in chapters:
        lines.append(f"## {title}")
        lines.append("")
        lines.append(body)
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    (PREPARED_DIR / f"{work['id']}.md").write_text(text, encoding="utf-8")
    return len(chapters), len(text)


def prepare(entries: list[dict]) -> None:
    unprepared = []
    for work in entries:
        try:
            chapters, size = prepare_work(work)
        except (FileNotFoundError, ValueError) as error:
            # Two failures that leave the other works preparable: a missing
            # pdftotext, which is about the machine and not about the shelf, and
            # text that cannot be cut into chapters unambiguously. Both name the
            # work rather than leave a file nobody notices is absent or wrong.
            unprepared.append(f"  {work['id']}: {error}")
            continue
        card = f"{card_policy(work)} card"
        print(f"  {work['id']}: {chapters} chapters, {size:,} characters, {card}")
    if unprepared:
        print("\nnot prepared:\n" + "\n".join(unprepared))
        sys.exit(1)


# --- table of contents -------------------------------------------------------

def write_toc(entries: list[dict]) -> None:
    """The chapter titles of each prepared work, committed under corpus-tech/toc/.

    Same file shape as the classics' corpus/toc/, and the same purpose: the text
    is not in the repository, so this is what a reviewer reads to see which
    chapters a golden question was written against, and what a reviewer diffs
    after re-fetching a work whose pins went red (corpus-tech/README.md). The
    weekly job regenerates them too, for every work but the PDF ones
    (`--skip-pdf`), and fails when the result differs from what is committed:
    a change to the reader or the splitter that moves a title shows up there."""
    TOC_DIR.mkdir(parents=True, exist_ok=True)
    for work in entries:
        prepared = PREPARED_DIR / f"{work['id']}.md"
        if not prepared.exists():
            print(f"  {work['id']}: not prepared, skipped")
            continue
        titles = re.findall(r"^##\s+(.*)$", prepared.read_text(encoding="utf-8"), re.M)
        (TOC_DIR / f"{work['id']}.json").write_text(
            json.dumps(titles, indent=0, ensure_ascii=False), encoding="utf-8")
        print(f"  {work['id']}: {len(titles)} chapters")


# --- book cards --------------------------------------------------------------

# Three kinds of card, by the work's `cards:` value (see the manifest header):
# a `shared` card, written by a model and committed here; a `structure` card,
# built by code from the manifest and the chapter list and committed here; and a
# local card, written by a model under AYL_HOME ($AYL_HOME/cards/tech/), outside
# any checkout — the reader may build a card for themself that the repository
# may not share. A `structure` work with `local_card: true` has both. `card_dir`
# is the one place that decides which folder a model-written card is written to,
# and it cannot send a local card, or any card of a NoDerivatives work, here.
CARDS_DIR = SHELF / "cards"


def local_cards_dir() -> Path:
    """$AYL_HOME/cards/tech, refused when AYL_HOME resolves inside a git work
    tree (`ask_your_library.home.private_dir`). Imported here, not at the top,
    so the stages that need no configuration keep importing none."""
    from ask_your_library.home import private_dir

    return private_dir("cards", SHELF_NAME)

# How much of a work the model is shown. Never the whole book: the shelf is 5 MB
# of prepared text and the largest single work is over a megabyte, which no
# context this project runs on holds and no card needs. What a card is written
# from is the work's own skeleton — the full chapter list, so every chapter can
# be named — plus the opening of each chapter, which in an engineering text is
# where the chapter says what it is about before it argues it. 1,500 characters
# is about two paragraphs, enough for that thesis; the 60,000-character cap is
# what keeps a 48-chapter book inside a local 14b model's window together with
# the prompt, and it is spent on the earliest chapters, so a work that hits it
# is summarised from its first half and still lists all of its chapters (#58).
CARD_CHAPTER_CHARS = 1_500
CARD_TOTAL_CHARS = 60_000

# The sections the model writes. `## Structure` is not among them: it is the
# work's chapter list, which this script already holds exactly, and asking a
# model to copy forty titles is asking it to get one of them wrong. The card's
# promise that it can answer "which chapter covers X" rests on those titles
# being the prepared text's own, so they are written here and not generated.
CARD_MODEL_SECTIONS = ("Summary", "Key ideas", "Terms", "Themes")

# What the card prompt says about the work's own words, by where the card may
# go. A shared card is an adaptation this repository distributes: it may carry a
# short quotation the way any review does, marked and attributed, and the rest is
# paraphrase. A card of a NoDerivatives work is never shared, and is paraphrase
# only, so nothing of the work's text is copied into a card at all.
CARD_QUOTES = """Write every sentence in your own words. You may quote the text sparingly: a quotation is at most one sentence of under 25 words, stands inside double quotation marks, and is followed at once by the chapter it comes from in parentheses, spelled exactly as in the chapter list — "a quoted sentence" (III. Config). Never copy a sentence, a definition or any run of more than a few words without marking it that way. Names, titles, chapter titles and the work's own coined terms may be used as they are."""

CARD_PARAPHRASE_ONLY = """Write every sentence in your own words. Never copy a sentence, a definition or any run of more than a few words from the text you are given, and do not quote it: this card is a paraphrase of the work, never an excerpt of it. Names, titles, chapter titles and the work's own coined terms are the only things you copy."""

CARD_SYSTEM = """You write a reference card for one technical work: the page a reader consults to decide whether this work answers their question, and which of its chapters to open.

Write ONLY from the text you are given. Add nothing you know about this work from anywhere else. Do not invent chapters, numbers, figures or quotations, and claim nothing the given text does not support.

{words} Where you name a chapter, spell it EXACTLY as it stands in the chapter list you are given.

Reply with exactly these sections, in this order, and with nothing else — no preamble, no closing remark, no code fence, no title line above them:

## Summary
One paragraph of 120-200 words: what the work is, who wrote it and for whom, what it argues, and how it is organised.

## Key ideas
Six to twelve bullets — never more than twelve — one idea per line and one line per idea, each in the form
- **<the idea>** — <one sentence saying what the work claims about it> (<chapter name>)
The chapter name is the chapter that idea lives in, copied from the chapter list character for character, INCLUDING the number, numeral or code it begins with: "III. Config", not "Config"; "LLM01:2025 Prompt Injection", not "Prompt Injection".

## Terms
Five to twelve bullets, the vocabulary this work uses in its own way — words it coins or gives a meaning of its own, not general English — each in the form
- **<term>** — <what it means in this work, one sentence>

## Themes
Four to eight bullets, the concerns that run across chapters rather than sitting in one, each in the form
- **<theme>** — <one sentence>"""


def card_system(work: dict) -> str:
    """The card prompt for this work: short attributed quotes allowed, except
    for a NoDerivatives work, whose (local) card is paraphrase only."""
    words = CARD_PARAPHRASE_ONLY if no_derivatives(work) else CARD_QUOTES
    return CARD_SYSTEM.format(words=words)


def prepared_chapters(work: dict) -> list[tuple[str, str]]:
    """The chapters of corpus-tech/prepared/<id>.md as (title, body).

    Read back from the prepared file rather than re-derived from raw/, so a card
    is written from exactly the text that was indexed — the same file `ayl-add`
    read, cut on the same `##` headings."""
    path = PREPARED_DIR / f"{work['id']}.md"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing — run --stage prepare first")
    pieces = re.split(r"(?m)^## ", path.read_text(encoding="utf-8"))[1:]
    chapters = []
    for piece in pieces:
        title, _, body = piece.partition("\n")
        chapters.append((title.strip(), body.strip()))
    return chapters


def card_excerpts(chapters: list[tuple[str, str]]) -> tuple[str, int]:
    """The openings of the chapters, within the budget; also how many were read.

    A chapter whose opening does not fit the total budget is left out of the
    excerpts and stays in the chapter list, which is why the two are built
    separately."""
    parts, spent, read = [], 0, 0
    for title, body in chapters:
        opening = body[:CARD_CHAPTER_CHARS].strip()
        if not opening or spent + len(opening) > CARD_TOTAL_CHARS:
            continue
        parts.append(f"### {title}\n{opening}")
        spent += len(opening)
        read += 1
    return "\n\n".join(parts), read


def card_user(work: dict, chapters: list[tuple[str, str]]) -> str:
    """The user message: the work's front matter, its chapter list, the chapter
    openings — all of it as DATA.

    Every character of this comes from a publisher's web page, so it is wrapped
    untrusted (`data_block`, the DATA_RULE that `llm_invoke` appends): text
    fetched from the internet that reaches a model is content and never an
    instruction, whatever it says about itself (ADR-017)."""
    from ask_your_library.llm import data_block

    listing = "\n".join(f"- {title}" for title, _ in chapters)
    excerpts, read = card_excerpts(chapters)
    return "\n".join([
        data_block("work", "\n".join([f"title: {work['title']}",
                                      f"author: {work['author']}",
                                      f"year: {work['year']}",
                                      f"kind: {work['kind']}"])),
        data_block("chapter_list", listing, chapters=str(len(chapters))),
        data_block("chapter_openings", excerpts,
                   chapters_read=str(read), characters_each=str(CARD_CHAPTER_CHARS)),
    ])


def card_sections(reply: str) -> dict[str, str]:
    """The `## section` bodies of a model's reply, by heading."""
    body = re.sub(r"^\s*```[a-z]*\n|\n```\s*$", "", reply.strip())
    sections = {}
    for piece in re.split(r"(?m)^## ", body)[1:]:
        header, _, text = piece.partition("\n")
        sections[header.strip()] = text.strip()
    return sections


def structure_section(titles: list[str]) -> str:
    """The chapter list as a card's `## Structure`, in the work's own order and
    the work's own spelling — one plain bullet per chapter and no number of our
    own, because most titles carry the book's number already ("5. Eliminating
    Toil") and a list position beside it would contradict it wherever the book
    has front matter or parts."""
    return "\n".join(f"- {title}" for title in titles)


def model_card_front_matter(work: dict, model: str, built: str,
                            edited: str | None = None) -> list[str]:
    """The front matter of a model-written card, and the H1 below it.

    The licence lines are what CC BY 4.0 section 3(a) asks of a shared
    adaptation: the licence and a link to it, where the work is, and that the
    card is an adaptation. For a ShareAlike work the card itself is under the
    work's licence (BY-SA section 3(b)), and says so.

    `edited` is the record of a hand edit to a model-written section, kept so
    that `card_model` stays a truthful account of who wrote the rest."""
    lines = ["---",
             f"date: {built}",
             "tags: [book, tech-shelf]",
             "type: book-card",
             f"source: \"{work['author']} — {work['title']}\"",
             f"card_kind: {'local' if model_card_is_local(work) else 'shared'}",
             f"card_model: {model}",
             f"card_built: {built}",
             f"licence: {work['licence']}",
             f"licence_url: {work['licence_url']}",
             f"work_url: {work['source']}",
             "adapted: \"a model-written summary of the work, not the work itself\""]
    if share_alike(work):
        lines += [f"card_licence: {work['licence']}",
                  f"card_licence_url: {work['licence_url']}"]
    if edited:
        lines.append(f"edited: {edited}")
    return lines + ["---", f"# {work['title']} — {work['author']}", ""]


def card_text(work: dict, sections: dict[str, str], chapters: list[tuple[str, str]],
              model: str, built: str) -> str:
    """The card file: the front matter and H1 shape corpus/cards/*.md already has.

    `source` is "Author — Title" and the H1 is "Title — Author" because that is
    how the classics' cards are written, and `ingest.chunking.chunk_card` reads
    the book key off the H1 — so a tech card ingests through the same code path
    and lands in the catalogue under the same key `ayl-add` minted for the text.

    `card_model` and `card_built` are the two fields the classics' cards do not
    have: this shelf's cards are generated rather than written, and a card built
    on the local 14b model and one built on the hosted model are otherwise
    indistinguishable on disk (#58)."""
    lines = model_card_front_matter(work, model, built)
    for name in ("Summary", "Key ideas"):
        lines += [f"## {name}", "", sections[name], ""]
    lines += ["## Structure", "", structure_section([title for title, _ in chapters]), ""]
    for name in ("Terms", "Themes"):
        lines += [f"## {name}", "", sections[name], ""]
    return "\n".join(lines).rstrip() + "\n"


def restamp_card(text: str, work: dict, titles: list[str]) -> str:
    """A model-written card with its front matter and `## Structure` rebuilt by
    code, and every model-written section left exactly as it was.

    Both parts are derived, never generated: the front matter from the manifest
    plus the card's own `card_model` and `card_built`, the Structure from the
    committed chapter list. So a change to how either is written — a licence
    line, the shape of the chapter list — is applied to cards already built
    without calling a model again, and a test can hold every committed card to
    `restamp_card(card) == card`."""
    if not text.startswith("---\n"):
        raise ValueError(f"{work['id']}: the card has no front matter")
    front, _, body = text[4:].partition("\n---\n")
    fields = dict(line.split(": ", 1) for line in front.splitlines() if ": " in line)
    for field in ("card_model", "card_built"):
        if not fields.get(field):
            raise ValueError(f"{work['id']}: the card has no {field}")
    heading, _, rest = body.partition("\n")
    if not heading.startswith("# "):
        raise ValueError(f"{work['id']}: the card's first line after the front matter is not its H1")
    new_rest, replaced = re.subn(r"(?ms)^## Structure\n.*?(?=^## |\Z)",
                                 lambda _: f"## Structure\n\n{structure_section(titles)}\n\n",
                                 rest)
    if replaced != 1:
        raise ValueError(f"{work['id']}: the card has {replaced} Structure sections, not one")
    lines = model_card_front_matter(work, fields["card_model"], fields["card_built"],
                                    fields.get("edited"))
    return ("\n".join(lines) + new_rest).rstrip() + "\n"


def restamp_cards(entries: list[dict], manifest: dict) -> None:
    """Rebuild the front matter and Structure of every model-written card already
    on disk (see `restamp_card`). No model is called and a card not yet written
    stays unwritten."""
    allowed = {work["id"] for work in card_targets(manifest)}
    for work in entries:
        if work["id"] not in allowed:
            continue
        path = card_dir(work) / f"{work['id']}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        new = restamp_card(text, work, committed_chapters(work))
        path.write_text(new, encoding="utf-8")
        print(f"  {work['id']}: {'restamped' if new != text else 'unchanged'}")


def card_dir(work: dict) -> Path:
    """The folder a model-written card of this work goes to: the committed one
    for a `shared` work, $AYL_HOME/cards/tech for every other — and for every
    NoDerivatives work whatever its `cards:` says (`model_card_is_local`). A
    work the manifest gives no model card has none, and asking is a bug in the
    caller."""
    if not wants_model_card(work):
        raise ValueError(f"{work['id']}: a {card_policy(work)} card is not written by a model")
    if model_card_is_local(work):
        return local_cards_dir()
    return CARDS_DIR


def build_cards(entries: list[dict], manifest: dict, force: bool = False) -> None:
    """Write the model-written cards: corpus-tech/cards/<id>.md for a `shared`
    work, $AYL_HOME/cards/tech/<id>.md for a local one.

    The NoDerivatives rule is enforced here and not only documented: the list
    this loop runs over is `card_targets`, intersected with whatever `--work`
    selected, and a work that is not in it is reported and skipped; the folder
    is `card_dir`'s, which sends every card of a CC BY-NC-ND work under
    AYL_HOME, and `local_cards_dir` refuses an AYL_HOME inside a git work tree.
    A card of such a work is a derivative the reader may make and this project
    may not distribute, so no model-written card of one is ever written inside
    the repository tree — an assertion in the code and a test, not a convention
    (`tests/test_tech_shelf.py`). Their committed structure cards are built by
    `build_structure_cards`, which calls no model."""
    # Imported here rather than at the top of the file so that `fetch`,
    # `prepare`, `toc`, `checksums` and `verify` keep needing no model, no key
    # and no database — which is what lets the weekly CI job run this script at
    # all, and what lets the tests exec the module offline.
    from ask_your_library import config
    from ask_your_library.llm import llm_invoke

    allowed = {work["id"] for work in card_targets(manifest)}
    model = f"{config.LLM_BACKEND}/{config.ORCHESTRATOR_MODEL}"
    built = date.today().isoformat()
    problems = []
    for work in entries:
        if work["id"] not in allowed:
            print(f"  {work['id']}: no model-written card ({work['licence']}, "
                  f"cards: {card_policy(work)}), skipped")
            continue
        folder = card_dir(work)
        if model_card_is_local(work) and folder.resolve().is_relative_to(REPO.resolve()):
            # `private_dir` has refused this already; the second check costs
            # nothing and names the rule the code exists for.
            raise RuntimeError(f"{work['id']}: a local card may not be written inside "
                               f"the repository ({folder})")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{work['id']}.md"
        if path.exists() and not force:
            print(f"  {work['id']}: card already written, kept (--force to rebuild)")
            continue
        chapters = prepared_chapters(work)
        started = time.monotonic()
        reply = llm_invoke(card_system(work), card_user(work, chapters), role="card").content
        sections = card_sections(reply)
        missing = [name for name in CARD_MODEL_SECTIONS if not sections.get(name)]
        if missing:
            # Half a card is worse than none: it would be indexed, retrieved and
            # quoted as if it were whole. The reply is not written, and the run
            # says which work to re-run once the prompt or the model is changed.
            problems.append(f"  {work['id']}: the reply has no {', '.join(missing)}")
            continue
        path.write_text(card_text(work, sections, chapters, model, built), encoding="utf-8")
        where = path.relative_to(REPO) if path.is_relative_to(REPO) else path
        print(f"  {work['id']}: {len(chapters)} chapters -> {where}, "
              f"{len(reply):,} characters from {model} in "
              f"{(time.monotonic() - started) / 60:.1f} min")
    if problems:
        sys.exit("cards not written:\n" + "\n".join(problems))


# --- structure cards ---------------------------------------------------------

# The sections of a structure card, in order. None of them is written by a
# model, and none of them says anything about the work in this project's words:
# `About` is the publisher's own description, quoted; `Structure` is the chapter
# list; `Facts` is the manifest. What makes the card shareable under CC BY-NC-ND
# is exactly that — it reproduces parts of the work and its publisher's page
# verbatim and attributed, which the licence grants, and adapts nothing, which
# it withholds. A summary, a paraphrase or a list of key ideas is an adaptation
# and belongs in a `local` card, never in this one.
STRUCTURE_SECTIONS = ("About", "Structure", "Facts")
STRUCTURE_FIELDS = ("about", "about_source", "about_checked")


def committed_chapters(work: dict) -> list[str]:
    """The work's chapter titles from the committed corpus-tech/toc/<id>.json —
    the same list the prepared text is cut on, readable without fetching."""
    path = TOC_DIR / f"{work['id']}.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} is missing — run --stage toc first")
    return json.loads(path.read_text(encoding="utf-8"))


def structure_card_text(work: dict, titles: list[str]) -> str:
    """A structure card: front matter and H1 as every other card (so
    `chunk_card` keys it to the same book), then About, Structure and Facts.

    Deterministic by construction — no build date, nothing from the clock — so
    a committed structure card can be compared byte for byte with what this
    function builds, which is how a test proves nobody edited one by hand."""
    missing = [field for field in STRUCTURE_FIELDS if not work.get(field)]
    if missing:
        raise ValueError(f"{work['id']}: a structure card needs {', '.join(missing)} "
                         f"in the manifest")
    about = " ".join(str(work["about"]).split())
    checked = str(work["about_checked"])
    lines = ["---",
             f"date: {checked}",
             "tags: [book, tech-shelf]",
             "type: book-card",
             f"source: \"{work['author']} — {work['title']}\"",
             "card_kind: structure",
             "card_model: none",
             "---",
             f"# {work['title']} — {work['author']}",
             "",
             "## About",
             "",
             f"> {about}",
             "",
             f"The description of the work on the site that publishes it online, "
             f"quoted verbatim from <{work['about_source']}> (read {checked}).",
             "",
             "## Structure",
             "",
             structure_section(titles),
             "",
             "## Facts",
             "",
             f"- Title: {work['title']}",
             f"- Authors: {work['author']}",
             f"- Year: {work['year']}",
             f"- Kind: {work['kind']}",
             f"- Edition: the online edition at <{work['source']}>, as pinned in "
             f"corpus-tech/manifest.yaml",
             f"- Licence: {work['licence']} <{work['licence_url']}>, as stated at "
             f"<{work['licence_statement']}>",
             f"- Chapters: {len(titles)}",
             "- This card: the title, the chapter list and the publishing site's description, "
             "reproduced verbatim and attributed; no summary of the work, because its "
             "licence withholds the right to share one",
             ]
    return "\n".join(lines).rstrip() + "\n"


def build_structure_cards(entries: list[dict], manifest: dict) -> None:
    """Write corpus-tech/cards/<id>.md for every selected `structure` work.

    No model, no key, no fetch: the card is the manifest and the committed
    chapter list, so this stage is part of `--stage all` and a rebuild that
    changes a committed card means the manifest or the chapter list changed."""
    allowed = {work["id"] for work in structure_targets(manifest)}
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    for work in entries:
        if work["id"] not in allowed:
            continue
        titles = committed_chapters(work)
        path = CARDS_DIR / f"{work['id']}.md"
        path.write_text(structure_card_text(work, titles), encoding="utf-8")
        print(f"  {work['id']}: {len(titles)} chapters -> {path.name} (structure card)")


# --- pins --------------------------------------------------------------------

PIN_KINDS = ("text", "bytes")


def pin_kind(work: dict) -> str:
    """Whether this work's files are pinned by their bytes or by the text the
    reader extracts from them (`pin:` in the manifest).

    There is no default. A work added without deciding this would be pinned by
    whichever rule happened to be the fallback, and the two rules answer
    different questions — so the person adding a work says which one, and a work
    that does not is a failure rather than a guess."""
    kind = work.get("pin")
    if kind not in PIN_KINDS:
        sys.exit(f"{work['id']}: pin: is {kind!r}, not one of {PIN_KINDS} — say in "
                 f"corpus-tech/manifest.yaml whether this work's files are pinned by "
                 f"their bytes or by the text read out of them")
    return kind


def page_text(work: dict, path: Path) -> str:
    """The reader's output for one fetched page: the chapter body the prepare
    stage builds out of that file, and nothing else the page carries."""
    html = path.read_text(encoding="utf-8", errors="replace")
    return render(read_html(html, work.get("container")), demote=1)


def digest_of(work: dict, path: Path) -> str:
    """The digest this work's pins are made of.

    `pin: bytes` hashes the file. `pin: text` hashes what the reader extracts
    from it, because two of these publishers do not serve the same bytes twice:
    developers.google.com stamps every response with a CSP `nonce` and an
    analytics JSON blob whose keys come out in a different order each time, and
    abseil.io is behind Cloudflare's email obfuscation, which rewrites the
    book's "Email ... to comment" link with a fresh key per response. Three
    fetches of an unchanged page gave three digests, so the weekly job was red
    by construction on those two files — and a job that is always red cannot
    report the edit it exists to catch in the other 174 (#58).

    None of that noise is text of the book: `<script>` is dropped by the reader
    and an attribute never reaches it, while the link's visible text is stable.
    Hashing the reader's output pins exactly what the shelf is built from, and a
    changed paragraph still changes the digest.

    The pages index is always hashed as bytes, whatever the work's rule: it is
    this script's own record of which pages the publisher's table of contents
    listed and in which order, not a page to read, and a chapter that appears,
    vanishes or moves has to be a failure."""
    if path.name == PAGES_INDEX or pin_kind(work) == "bytes":
        return sha256_of(path)
    return hashlib.sha256(page_text(work, path).encode("utf-8")).hexdigest()


def fetched_files(work: dict) -> list[Path]:
    directory = raw_dir(work)
    if not directory.exists():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file())


def pins_of(work: dict) -> dict:
    return work.get("sources") or {}


def write_checksums(entries: list[dict]) -> None:
    """Pin the sha256 of every fetched file into the manifest, under the work's
    `sources:` block: file name -> digest, sorted by name.

    Per file rather than one digest per work, because these works are dozens of
    separately published pages and the answer a red weekly job has to give is
    *which chapter changed*, not *something did*."""
    # The file is edited as text, not re-serialised from the parsed YAML: the
    # comments above each entry are half of what this manifest says, and a dump
    # would drop every one of them. Split on the `- id:` lines and every entry
    # keeps its own comments, ordering and quoting.
    wanted = {work["id"] for work in entries}
    pieces = re.split(r"(?m)^(?=  - id: )", MANIFEST.read_text(encoding="utf-8"))
    for index, piece in enumerate(pieces):
        named = re.match(r"  - id: (\S+)", piece)
        if not named or named.group(1) not in wanted:
            continue
        work = next(entry for entry in entries if entry["id"] == named.group(1))
        files = fetched_files(work)
        if not files:
            print(f"  {work['id']}: nothing fetched, skipped")
            continue
        body = re.sub(r"\n?    sources:\n(?:      [^\n]*\n)*", "\n", piece).rstrip("\n")
        pieces[index] = body + "\n    sources:\n" + "".join(
            f"      {path.name}: {digest_of(work, path)}\n" for path in files) + "\n"
        print(f"  {work['id']}: {len(files)} files pinned by {pin_kind(work)}")
    MANIFEST.write_text("".join(pieces).rstrip("\n") + "\n", encoding="utf-8")


def verify(entries: list[dict]) -> None:
    """Re-hash every fetched file against its pin. A file with no pin is a
    failure, not a skip: an unpinned source is verified against nothing, and the
    eval numbers name the manifest they were measured from."""
    problems = []
    checked = 0
    for work in entries:
        pins = pins_of(work)
        if not pins:
            problems.append(f"  {work['id']}: no sources pinned — run --stage checksums")
            continue
        present = {path.name: path for path in fetched_files(work)}
        for name, digest in pins.items():
            if name not in present:
                problems.append(f"  {work['id']}/{name}: pinned but not fetched")
                continue
            actual = digest_of(work, present[name])
            checked += 1
            if actual != digest:
                problems.append(f"  {work['id']}/{name}: manifest {digest[:12]}..., "
                                f"got {actual[:12]}... ({pin_kind(work)} pin) — "
                                f"the source changed upstream")
        for name in sorted(set(present) - set(pins)):
            problems.append(f"  {work['id']}/{name}: fetched but not pinned")
        print(f"  {work['id']}: {len(pins)} pins ({pin_kind(work)})")
    if problems:
        sys.exit("checksum verification failed:\n" + "\n".join(problems)
                 + "\n\nre-pin with --stage checksums once the change is understood; "
                   "a changed chapter is a different edition, and the golden questions "
                   "and the tables of contents have to be re-read against it.")
    print(f"\n{checked} files verified against corpus-tech/manifest.yaml")


# --- main --------------------------------------------------------------------

# `cards` is asked for by name and is not part of `--stage all`, like
# `checksums`: it is the only stage that calls a model, and a plain run of this
# script — which is what a machine does to check its pins — must not quietly
# spend ten model calls.
# `structure-cards` IS part of it: it calls no model and reads only committed
# files, like `toc`, and what it writes is committed.
# `restamp-cards` is by name too: it rewrites files a model wrote (their front
# matter and chapter list only), which a plain run should not touch.
STAGES = ("fetch", "prepare", "toc", "structure-cards", "cards", "restamp-cards",
          "checksums", "verify")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=("all",) + STAGES, default="all")
    ap.add_argument("--work", help="substring filter: of the work's title or id")
    ap.add_argument("--refetch", action="store_true",
                    help="download again even when the file is cached")
    ap.add_argument("--force", action="store_true",
                    help="--stage cards only: rebuild a card that is already written")
    ap.add_argument("--skip-pdf", action="store_true",
                    help="leave out the works read through pdftotext (fetch: pdf, arxiv-pdf) — "
                         "for a machine without poppler, such as the weekly CI job")
    args = ap.parse_args()
    if args.force and args.stage != "cards":
        ap.error("--force belongs to --stage cards; no other stage overwrites anything "
                 "it would need forcing past")

    manifest = load_manifest()
    entries = works(manifest)
    if args.work:
        needle = args.work.lower()
        entries = [work for work in entries
                   if needle in work["title"].lower() or needle in work["id"]]
        if not entries:
            sys.exit(f"no work of corpus-tech/manifest.yaml matches {args.work!r}")
    if args.skip_pdf:
        entries = [work for work in entries if work["fetch"] not in PDF_FETCH_KINDS]

    if args.stage in ("all", "fetch"):
        print("== fetch ==")
        for work in entries:
            fetch_work(work, refetch=args.refetch)
    if args.stage in ("all", "prepare"):
        print("== prepare ==")
        prepare(entries)
    if args.stage in ("all", "toc"):
        print("== table of contents ==")
        write_toc(entries)
    if args.stage in ("all", "structure-cards"):
        print("== structure cards ==")
        build_structure_cards(entries, manifest)
    if args.stage == "cards":
        print("== book cards ==")
        build_cards(entries, manifest, force=args.force)
    if args.stage == "restamp-cards":
        print("== restamp model-written cards (no model) ==")
        restamp_cards(entries, manifest)
    if args.stage == "checksums":
        print("== pin the fetched sources into the manifest ==")
        write_checksums(entries)
    if args.stage in ("all", "verify"):
        print("== verify ==")
        verify(entries)


if __name__ == "__main__":
    main()
