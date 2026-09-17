"""Build the engineer's shelf (#58): fetch -> one Markdown file per work -> pins.

The second demo corpus is a shelf of openly licensed engineering books, guides
and papers. Unlike the classics, none of its text is committed: every work is
fetched from its publisher at build time, converted to a single Markdown file
under `corpus-tech/prepared/`, and indexed into an index of its own with the
generic folder ingest:

    LIBRARY_DB_PATH=~/ayl-tech uv run ayl-add corpus-tech/prepared

corpus-tech/manifest.yaml is the single source of truth for what the shelf
holds, where each work comes from, under which licence, and the sha256 of every
file that was fetched to build it. Three of the works are CC BY-NC-ND: they are
fetched as text and never get a generated book card, because a card is a
derivative work and ND forbids distributing one (`cards: false` in the manifest,
and `card_targets` below is the only list a card-generating stage may read).

Stages (all cached in corpus-tech/raw/, safe to re-run):
  uv run scripts/fetch_tech_shelf.py --stage fetch      # download, nothing else
  uv run scripts/fetch_tech_shelf.py --stage prepare    # raw -> prepared/<id>.md
  uv run scripts/fetch_tech_shelf.py --stage toc        # prepared -> toc/<id>.json
  uv run scripts/fetch_tech_shelf.py --stage checksums  # pin the fetched files
  uv run scripts/fetch_tech_shelf.py --stage verify     # re-hash them against the pins
  uv run scripts/fetch_tech_shelf.py --work sre         # substring filter on the title

The stages are deliberately separate from `scripts/ingest_demo_corpus.py`: that
script owns the classics index and embeds; this one writes files and nothing
else, so it needs no model, no database and no embedding backend.

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


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def works(manifest: dict) -> list[dict]:
    return manifest["works"]


def card_targets(manifest: dict) -> list[dict]:
    """The works a card MAY be generated for, and the only list a card stage is
    allowed to read.

    A book card is a summary written from the work — a derivative — so for a
    CC BY-NC-ND work distributing one is exactly what the licence withholds.
    Those works are indexed as text and answer quote questions; they are absent
    from the catalogue's card side, which is the price the shelf pays for
    carrying the titles its audience knows (#58)."""
    return [work for work in works(manifest) if work.get("cards") is True]


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
             "svg", "noscript", "sup", "figure", "iframe", "button", "select"}
VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "col", "source"}
BLOCK_TAGS = {"p", "div", "section", "article", "ul", "ol", "dl", "table",
              "tr", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6",
              "li", "dt", "dd", "pre", "td", "th", "figcaption", "main"}
HEADINGS = {f"h{level}": level for level in range(1, 7)}


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
            self.blocks.append(("text", f"```\n{text}\n```"))
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
        return re.sub(r"^(?:chapter|part|appendix)?\s*[0-9IVXA-F]*[.\-)]?\s*", "",
                      text.strip().lower())
    return bare(one) == bare(other)


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
            pieces.append(block[1])
    return "\n\n".join(pieces).strip()


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
            "the shelf (OWASP, ReAct, Chain-of-Thought). `brew install poppler` on "
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
        except FileNotFoundError as error:
            # A missing pdftotext is the one failure that is about the machine
            # and not about the shelf: the other works still prepare, and this
            # one is named rather than left as a file nobody notices is absent.
            unprepared.append(f"  {work['id']}: {error}")
            continue
        card = "card allowed" if work.get("cards") else f"no card ({work['licence']})"
        print(f"  {work['id']}: {chapters} chapters, {size:,} characters, {card}")
    if unprepared:
        print("\nnot prepared:\n" + "\n".join(unprepared))
        sys.exit(1)


# --- table of contents -------------------------------------------------------

def write_toc(entries: list[dict]) -> None:
    """The chapter titles of each prepared work, committed under corpus-tech/toc/.

    Same file shape as the classics' corpus/toc/, and the same purpose: the text
    is not in the repository, so this is what a reviewer reads to see which
    chapters a golden question was written against, and what the weekly job
    diffs when a publisher changes a book under its own URL."""
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


# --- pins --------------------------------------------------------------------

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
            f"      {path.name}: {sha256_of(path)}\n" for path in files) + "\n"
        print(f"  {work['id']}: {len(files)} files pinned")
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
            actual = sha256_of(present[name])
            checked += 1
            if actual != digest:
                problems.append(f"  {work['id']}/{name}: manifest {digest[:12]}..., "
                                f"got {actual[:12]}... — the source changed upstream")
        for name in sorted(set(present) - set(pins)):
            problems.append(f"  {work['id']}/{name}: fetched but not pinned")
        print(f"  {work['id']}: {len(pins)} pins")
    if problems:
        sys.exit("checksum verification failed:\n" + "\n".join(problems)
                 + "\n\nre-pin with --stage checksums once the change is understood; "
                   "a changed chapter is a different edition, and the golden questions "
                   "and the tables of contents have to be re-read against it.")
    print(f"\n{checked} files verified against corpus-tech/manifest.yaml")


# --- main --------------------------------------------------------------------

STAGES = ("fetch", "prepare", "toc", "checksums", "verify")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=("all",) + STAGES, default="all")
    ap.add_argument("--work", help="substring filter: of the work's title or id")
    ap.add_argument("--refetch", action="store_true",
                    help="download again even when the file is cached")
    args = ap.parse_args()

    manifest = load_manifest()
    entries = works(manifest)
    if args.work:
        needle = args.work.lower()
        entries = [work for work in entries
                   if needle in work["title"].lower() or needle in work["id"]]
        if not entries:
            sys.exit(f"no work of corpus-tech/manifest.yaml matches {args.work!r}")

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
    if args.stage == "checksums":
        print("== pin the fetched sources into the manifest ==")
        write_checksums(entries)
    if args.stage in ("all", "verify"):
        print("== verify ==")
        verify(entries)


if __name__ == "__main__":
    main()
