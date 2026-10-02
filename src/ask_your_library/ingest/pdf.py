"""One `.pdf` -> the title, the author and the sections `ayl add` indexes.

A PDF is read through its text layer: the characters a page draws, as the
`pypdf` library (BSD-3-Clause, pure Python, ADR-030) extracts them. Nothing is
rendered and nothing is recognised from images, so a scanned book with no text
layer is refused rather than indexed as empty. This module hands `add_folder`
the same three things a text or EPUB book gives it: a title and author (or
none, for the file-name rule to fill in), and `[(section title, text)]`.

Sections come from structure, never from heuristics over the text:

- with an outline (the bookmarks a viewer shows in its side panel), each
  top-level entry opens a section at the page it points to, and the section
  runs to the page before the next entry's; when the top level is a single
  entry with entries under it (a book whose one bookmark is its own title),
  the level under it is used instead. Pages before the first entry are
  `Front matter`. A page is the smallest unit: a chapter that starts halfway
  down a page starts, here, on the next one, and when two entries point at the
  same page the first one names it;
- an entry that points at no page of this document (past the last page, at an
  object that is not a page, at another file) is ignored, and so is one with
  no title; an outline left with no usable entry, or one that cannot be read,
  is not used, and the caller is told so;
- without an outline, every page with text is a section of its own,
  `Page N`, N counted from the first page of the file (the number a viewer's
  page box shows, not the number printed on the page). A page without text is
  no section, so the numbering keeps its gaps.

Reading order is page order. The text of a page is what `pypdf` extracts in its
plain mode: every run of whitespace other than a line break becomes one space,
lines are trimmed and empty ones dropped, and control and invisible characters
are stripped (`sanitize.strip_control_chars`). A word hyphenated at the end of a
line stays hyphenated (`infor- mation` once the chunker joins the lines): the
hyphen of a broken word and the hyphen of a compound look the same in the text
layer. Running headers, footers and page numbers are not detected and are read
as text; two-column layouts come out in whatever order the producer drew them.

The title is the document information dictionary's `/Title`, else the XMP
`dc:title`; the author `/Author`, else the XMP `dc:creator` names, joined.
Metadata that cannot be read is treated as absent, and the caller falls back to
the file-name rule of a text book.

A PDF is untrusted input. What the library bounds, what this module bounds,
and what is never done:

- **never done**: no JavaScript is evaluated and no action (launch, URI,
  submit, GoTo another file) is followed — `pypdf` implements none of them, and
  an outline entry is used only for the page number of this document it names;
  embedded files and attachments are never read; pages are not rendered, images
  are never decoded, and no font is loaded to draw a glyph (a Type 1 font
  program embedded without a `/ToUnicode` map is read by `pypdf` for its
  encoding table only); `pypdf`'s one external program, `jbig2dec` for JBIG2
  images, is switched off in its configuration; an encrypted file is refused
  before any password, the empty one included, is tried;
- **the library bounds**: object-reference loops in the page tree, the outline,
  forms drawn inside forms and inherited attributes are detected and stop;
  every decoded stream is capped (`MAX_STREAM_BYTES`, set through `pypdf`'s
  configuration for every filter it inflates: Flate, LZW, run-length, JBIG2);
  the page-tree walk stops past `2 * MAX_PAGES` entries and the outline walk
  past `MAX_OUTLINE_ENTRIES`, so neither is materialised past the cap; XMP
  metadata is parsed with entity declarations forbidden and an element cap; a
  damaged cross-reference table is rebuilt by scanning the file once;
- **this module bounds**, before the work is done rather than after: the file
  size (`MAX_FILE_BYTES`, checked on the open file before the library reads
  it); every byte `pypdf` inflates in this file, all streams together
  (`MAX_DECODED_BYTES`), counted at its one decoding function and refused
  before the next stream is inflated, which is what bounds memory: the library
  keeps what it inflated for as long as the file is open; every byte of
  drawing instructions parsed for a page, the page's own and each form it draws
  every time it draws it (`MAX_PAGE_CONTENT_BYTES`), and for the whole file
  (`MAX_CONTENT_BYTES`), counted when the content is handed to the parser and
  before it is parsed, which is what bounds time: parsing and interpreting the
  instructions is the slow part; the bytes a page shows as text, counted per
  instruction while the page is interpreted, and the characters it yields
  (`MAX_PAGE_CHARS`); the characters of the whole book (`MAX_TOTAL_CHARS`); the
  number of pages (`MAX_PAGES`);
- **time**: `pypdf` has no timeout, and none is added (no thread, no signal).
  The bound is the content caps above. Measured on an Apple M-series
  machine, the slowest instructions to parse and interpret (runs of numbers,
  of path operators) go at about 2 MB a second: the worst page the caps admit
  takes under 2 s, the worst file about a minute (52 s for 128 MiB of `q Q`),
  and a 400-page book of plain text under 3 s.

Every refusal is a `PdfRefused` carrying a reason written here: it names no
part of the document and quotes no text of it, so the caller's one line about
the file says which file and why, and nothing of what is in it. `pypdf`'s own
log lines and warnings are silenced while it reads, for the same reason: they
can quote bytes of the document (a font name, an object's content).
"""
import logging
import os
import re
import warnings
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

import pypdf
import pypdf._page
import pypdf.filters
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError

from ..sanitize import LINE_BREAK_RE, strip_control_chars
from .chapters import FRONT_MATTER_SECTION, unique_titles

# --- bounds -------------------------------------------------------------------
# A long novel is 300-600 pages and under 2 MB of text; a dense page is 3,000 to
# 5,000 characters, drawn by 10 to 100 KB of content. Every cap is far past
# that, and far short of what would take minutes or gigabytes.
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PAGES = 5_000
MAX_STREAM_BYTES = 16 * 1024 * 1024          # one inflated stream (pypdf's own cap)
MAX_DECODED_BYTES = 256 * 1024 * 1024        # everything inflated in one file
MAX_PAGE_CONTENT_BYTES = 4 * 1024 * 1024     # drawing instructions parsed for one page
MAX_CONTENT_BYTES = 128 * 1024 * 1024        # ... and for the whole file
MAX_PAGE_CHARS = 100_000
MAX_TOTAL_CHARS = 20_000_000
MAX_OUTLINE_ENTRIES = 10_000

# The scanned-PDF rule: fewer than SCAN_MIN_CHARS characters (whitespace not
# counted) on the first SCAN_PAGES pages, or on all of them when there are fewer,
# means there is no text layer to read. A real book's cover, half-title and
# title pages can be nearly empty, so the window is ten pages, not one; a scan
# whose only text is a page number or a scanner's stamp stays under 200.
SCAN_PAGES = 10
SCAN_MIN_CHARS = 200

PAGE_SECTION = "Page {n}"

# The operators that show text, whose string operands are counted against
# MAX_PAGE_CHARS while the page is interpreted (TJ's are inside its array).
SHOW_TEXT = frozenset({b"Tj", b"TJ", b"'", b'"'})


class PdfRefused(Exception):
    """The file is not indexed. The message is a reason, never a quote."""


@dataclass
class PdfBook:
    title: str                          # "" when the metadata names none
    author: str                         # "" when the metadata names none
    sections: list[tuple[str, str]]
    # Why the outline was not used, when the file has one that was not; the
    # caller reports it, since the sections are then pages, not chapters.
    outline_note: str = ""


def mib(n: int) -> str:
    return f"{n // (1024 * 1024)} MiB"


ENCRYPTED = ("encrypted (password-protected or restricted; no password was tried and "
             "nothing was decrypted)")


# --- the budget -----------------------------------------------------------------

class _Budget:
    """What one file has cost so far, and the refusal once it costs too much.

    The refusal is sticky. `pypdf` catches broad exceptions in a few places
    while it interprets a page (a form it cannot draw is skipped, not fatal),
    so a refusal raised inside one of them can be swallowed; once `over` is
    set, every later decode, parse or instruction raises it again, and the
    caller checks it after every page, so it always surfaces."""

    def __init__(self):
        self.decoded = 0
        self.content = 0
        self.page_content = 0
        self.page_shown = 0
        self.over: str | None = None

    def refuse(self, reason: str) -> None:
        if self.over is None:
            self.over = reason
        raise PdfRefused(self.over)

    def check(self) -> None:
        if self.over is not None:
            raise PdfRefused(self.over)

    def new_page(self) -> None:
        self.page_content = 0
        self.page_shown = 0

    def inflated(self, n: int) -> None:
        self.decoded += n
        if self.decoded > MAX_DECODED_BYTES:
            self.refuse(f"its compressed streams inflate past {mib(MAX_DECODED_BYTES)} "
                        "in all")

    def parsed(self, n: int) -> None:
        self.page_content += n
        self.content += n
        if self.page_content > MAX_PAGE_CONTENT_BYTES:
            self.refuse(f"a page in it has more than {mib(MAX_PAGE_CONTENT_BYTES)} of "
                        "drawing instructions")
        if self.content > MAX_CONTENT_BYTES:
            self.refuse(f"it has more than {mib(MAX_CONTENT_BYTES)} of drawing "
                        "instructions in all")

    def shown(self, n: int) -> None:
        self.page_shown += n
        if self.page_shown > MAX_PAGE_CHARS:
            self.refuse(page_chars_reason())

    def visit(self, operator, operands, *_matrices) -> None:
        """`pypdf`'s per-instruction callback (a public extraction hook)."""
        self.check()
        if operator in SHOW_TEXT:
            self.shown(sum(shown_length(operand) for operand in operands))


def shown_length(operand) -> int:
    if isinstance(operand, (str, bytes)):
        return len(operand)
    if isinstance(operand, list):                    # TJ: strings and kerning numbers
        return sum(len(item) for item in operand if isinstance(item, (str, bytes)))
    return 0


def page_chars_reason() -> str:
    return f"a page in it holds more than {MAX_PAGE_CHARS:,} characters of text"


@contextmanager
def _bounded(budget: _Budget):
    """`pypdf` with this module's caps, for the length of one read.

    Two of the caps have no setting in the library, so they are counted at the
    two places every stream passes through: `pypdf.filters.decode_stream_data`,
    the one function that inflates a stream, and the `ContentStream` that
    `pypdf._page` builds for every page and every form before it parses one.
    Both are put back when the read ends, however it ends, and a test pins
    that each is still where the library looks for it."""
    decode = pypdf.filters.decode_stream_data
    content_stream = pypdf._page.ContentStream

    def counted_decode(stream):
        budget.check()                               # refuse before inflating more
        data = decode(stream)
        budget.inflated(len(data))
        return data

    class CountedContentStream(content_stream):
        def __init__(self, stream, pdf, forced_encoding=None):
            budget.check()
            super().__init__(stream, pdf, forced_encoding)
            # Counted after the bytes are joined and before they are parsed:
            # parsing is lazy, and `operations` is what costs the time.
            budget.parsed(len(self.get_data()))

    configuration = dict(
        maximum_declared_stream_length=MAX_FILE_BYTES,
        zlib_maximum_output_length=MAX_STREAM_BYTES,
        lzw_maximum_output_length=MAX_STREAM_BYTES,
        run_length_maximum_output_length=MAX_STREAM_BYTES,
        jbig2_maximum_output_length=MAX_STREAM_BYTES,
        image_maximum_buffer_size=MAX_STREAM_BYTES,
        array_based_stream_maximum_output_length=MAX_PAGE_CONTENT_BYTES,
        page_tree_maximum_entries=2 * MAX_PAGES,
        outline_maximum_entries=MAX_OUTLINE_ENTRIES,
        jbig2dec_binary=None,
    )
    quiet = logging.getLogger("pypdf")
    propagate = quiet.propagate
    silent = logging.NullHandler()
    with ExitStack() as stack:
        stack.enter_context(apply_configuration(**configuration))
        stack.enter_context(warnings.catch_warnings())
        warnings.simplefilter("ignore")
        # Not propagated, and handled by a handler that drops them: without a
        # handler of its own the logger would fall back to `logging.lastResort`
        # and print to stderr anyway.
        quiet.addHandler(silent)
        quiet.propagate = False
        pypdf.filters.decode_stream_data = counted_decode
        pypdf._page.ContentStream = CountedContentStream
        try:
            yield
        finally:
            pypdf.filters.decode_stream_data = decode
            pypdf._page.ContentStream = content_stream
            quiet.propagate = propagate
            quiet.removeHandler(silent)


class _Reader(PdfReader):
    """`PdfReader` that refuses an encrypted file instead of trying a password.

    `PdfReader` tries the empty password on any encrypted file as it opens it
    (an owner-password-only file opens that way). This project does not work
    around a protection, whichever kind, so the attempt is replaced by the
    refusal; `read_pdf` checks `is_encrypted` afterwards as well, in case a
    later version of the library stops calling this method."""

    def _handle_encryption(self, password) -> None:
        raise PdfRefused(ENCRYPTED)


# --- text -----------------------------------------------------------------------

_SPACES = re.compile(r"[^\S\n]+")


def clean_text(text: str) -> str:
    """A page's extracted text, normalised: see the module docstring."""
    text = strip_control_chars(LINE_BREAK_RE.sub("\n", text))
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def clean_label(label) -> str:
    """A title, author or outline label as one clean line; "" for anything that
    is not text (the library hands undecodable strings over as bytes)."""
    if not isinstance(label, str):
        return ""
    return _SPACES.sub(" ", LINE_BREAK_RE.sub(" ", strip_control_chars(label))).strip()


def visible_chars(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def page_text(page, budget: _Budget) -> str:
    budget.new_page()
    raw = page.extract_text(visitor_operand_before=budget.visit)
    budget.check()                                   # a refusal pypdf swallowed
    if len(raw) > MAX_PAGE_CHARS:
        budget.refuse(page_chars_reason())
    return clean_text(raw)


def read_pages(reader: PdfReader, budget: _Budget) -> list[str]:
    try:
        count = len(reader.pages)
    except LimitReachedError as error:
        budget.check()
        raise PdfRefused(f"its page tree is larger than the limit of {MAX_PAGES:,} "
                         "pages") from error
    if count > MAX_PAGES:
        raise PdfRefused(f"it has {count:,} pages, and the limit is {MAX_PAGES:,}")
    if count == 0:
        raise PdfRefused("it has no pages")
    texts: list[str] = []
    total = 0
    for index in range(count):
        text = page_text(reader.pages[index], budget)
        total += len(text)
        if total > MAX_TOTAL_CHARS:
            raise PdfRefused(f"it holds more than {MAX_TOTAL_CHARS:,} characters of text")
        texts.append(text)
        if index + 1 == min(SCAN_PAGES, count):
            if sum(visible_chars(t) for t in texts) < SCAN_MIN_CHARS:
                raise PdfRefused(
                    f"no text layer (fewer than {SCAN_MIN_CHARS} characters of text on its "
                    f"first {index + 1} page{'' if index == 0 else 's'}): a scanned PDF "
                    "needs OCR, which ayl does not do")
    return texts


# --- metadata -------------------------------------------------------------------

def metadata(reader: PdfReader, budget: _Budget) -> tuple[str, str]:
    """(title, author) from the information dictionary, else from XMP."""
    title = author = ""
    try:
        info = reader.metadata
        if info is not None:
            title, author = clean_label(info.title), clean_label(info.author)
    except PdfRefused:
        raise
    except Exception:
        pass                                         # absent, for the file-name rule
    budget.check()
    if title and author:
        return title, author
    try:
        xmp = reader.xmp_metadata
        if xmp is not None:
            titles = xmp.dc_title or {}
            title = title or clean_label(titles.get("x-default")
                                         or next(iter(titles.values()), ""))
            names = [clean_label(name) for name in xmp.dc_creator or []]
            author = author or ", ".join(name for name in names if name)
    except PdfRefused:
        raise
    except Exception:
        pass
    budget.check()
    return title, author


# --- sections -------------------------------------------------------------------

def outline_level(outline: list) -> list:
    """The outline's top level, or the level under it while the top level is
    one entry with entries under it (`pypdf` puts an entry's children in a
    list right after it)."""
    level = outline
    while (len(level) == 2 and not isinstance(level[0], list)
           and isinstance(level[1], list)):
        level = level[1]
    return [entry for entry in level if not isinstance(entry, list)]


def outline_starts(reader: PdfReader, budget: _Budget, count: int
                   ) -> tuple[list[tuple[int, str]], str]:
    """[(first page index, title)] in page order, one per page, and the reason
    the outline was not used when it was not ("" when there is none)."""
    try:
        outline = reader.outline
    except PdfRefused:
        raise
    except LimitReachedError:
        budget.check()
        return [], f"its outline has more than {MAX_OUTLINE_ENTRIES:,} entries"
    except Exception as error:
        budget.check()
        return [], f"its outline could not be read ({type(error).__name__})"
    budget.check()
    if not outline:
        return [], ""
    starts: dict[int, str] = {}
    for entry in outline_level(outline):
        title = clean_label(getattr(entry, "title", None))
        try:
            page = reader.get_destination_page_number(entry)
        except PdfRefused:
            raise
        except Exception:
            page = None
        budget.check()
        if not title or not isinstance(page, int) or not 0 <= page < count:
            continue                                 # points at no page of this file
        starts.setdefault(page, title)
    if not starts:
        return [], "no entry of its outline points at a page of the document"
    return sorted(starts.items()), ""


def build_sections(texts: list[str], starts: list[tuple[int, str]]) -> list[tuple[str, str]]:
    """Page texts -> [(section title, text)]: one section per outline start,
    running to the page before the next one; one per page without starts."""
    if not starts:
        return [(PAGE_SECTION.format(n=n), text) for n, text in enumerate(texts, 1) if text]
    bounds = list(starts)
    if bounds[0][0] > 0:
        bounds.insert(0, (0, FRONT_MATTER_SECTION))
    sections = []
    for i, (first, title) in enumerate(bounds):
        last = bounds[i + 1][0] if i + 1 < len(bounds) else len(texts)
        text = "\n\n".join(t for t in texts[first:last] if t)
        if text:
            sections.append((title, text))
    return unique_titles(sections)


# --- the whole read -------------------------------------------------------------

def read_pdf(path: Path) -> PdfBook:
    """The whole read. Raises `PdfRefused` for anything that is not indexed.

    Any exception the library raises on a damaged file is a refusal naming its
    class only: its message can quote bytes of the document."""
    budget = _Budget()
    try:
        with open(path, "rb") as fp:
            size = os.fstat(fp.fileno()).st_size
            if size > MAX_FILE_BYTES:
                raise PdfRefused(f"the file is larger than {mib(MAX_FILE_BYTES)}")
            with _bounded(budget):
                reader = _Reader(fp, strict=False)
                if reader.is_encrypted:
                    raise PdfRefused(ENCRYPTED)
                texts = read_pages(reader, budget)
                title, author = metadata(reader, budget)
                starts, note = outline_starts(reader, budget, len(texts))
    except PdfRefused:
        raise
    except OSError as error:
        raise PdfRefused("the file cannot be read") from error
    except Exception as error:
        if budget.over is not None:                  # the library re-raised it as its own
            raise PdfRefused(budget.over) from error
        raise PdfRefused(f"could not be read ({type(error).__name__})") from error
    sections = build_sections(texts, starts)
    if not sections:                                 # the scan rule makes this rare
        raise PdfRefused("no text in it")
    return PdfBook(title=title, author=author, sections=sections, outline_note=note)
