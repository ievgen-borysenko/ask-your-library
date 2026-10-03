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
  the page-tree walk stops past `2 * MAX_PAGES` entries or `MAX_PAGE_TREE_DEPTH`
  levels and the outline walk past `MAX_OUTLINE_ENTRIES` entries or
  `MAX_OUTLINE_DEPTH` levels, so neither is materialised past the cap; a page
  draws at most `MAX_FORM_DRAWS` forms (the library skips the rest); XMP
  metadata is parsed with entity declarations forbidden and an element cap; a
  damaged cross-reference table is rebuilt by scanning the file once. Every
  one of these is set explicitly in `_bounded`, not left at the library's
  default. Its fixed limits (a `/ToUnicode` map of at most 100,000 entries,
  a width table of at most 65,536 CIDs) apply as well;
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
  instruction while the page is interpreted and multiplied by the longest
  string one code of the page's fonts maps to, and the characters it yields
  (`MAX_PAGE_CHARS`); the characters of the whole book (`MAX_TOTAL_CHARS`); the
  number of pages (`MAX_PAGES`); the fonts: the library builds a font's
  character map and widths again for every page and every form draw that uses
  it, so each font dictionary is built once per file and kept, and the entries
  of every one built are counted (`MAX_FONT_ENTRIES`), which bounds the memory
  the kept fonts hold and the time spent building them;
- **time**: `pypdf` has no timeout. None is added by a thread or a signal; a
  deadline per file (`MAX_SECONDS_PER_FILE`) is checked at every counting point
  above and at every drawing instruction, so whatever no cap names (the next
  table a hostile font could make large) still ends in a refusal. The caps are
  set so that it should not be what stops a file: measured on an Apple
  M-series machine, the slowest instructions to parse and interpret (runs of
  numbers, of path operators) go at about 2 MB a second, the worst page the
  content caps admit takes under 2 s, the worst file about a minute (52 s for
  128 MiB of `q Q`), and a 400-page book of plain text under 3 s.

Every refusal is a `PdfRefused` carrying a reason written here: it names no
part of the document and quotes no text of it, so the caller's one line about
the file says which file and why, and nothing of what is in it. `pypdf`'s own
log lines and warnings are silenced while it reads, for the same reason: they
can quote bytes of the document (a font name, an object's content).

**One read at a time.** The counting points replace three names inside
`pypdf` (`filters.decode_stream_data`, `_page.ContentStream`,
`Font.from_font_resource`), the `pypdf` logger is detached and warnings are
filtered, all of it process-wide, for the length of one `read_pdf` and put back
afterwards. The reader assumes it is the only code using `pypdf` while it runs,
which is true of `ayl add`, a single-threaded command; it is not thread-safe,
and two reads in parallel threads would count each other's work.
"""
import logging
import os
import re
import time
import warnings
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import pypdf
import pypdf._font
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
# A real outline is a few levels deep and a real page tree four or five; the
# library walks both recursively.
MAX_OUTLINE_DEPTH = 32
MAX_PAGE_TREE_DEPTH = 64
# Forms one page may draw: a running head, a watermark, a figure built of
# parts is a handful to a few dozen; past this the library skips the rest.
MAX_FORM_DRAWS = 200
# Entries in the character maps and width tables of every font built for one
# file. A book's fonts hold a few hundred entries each, a CJK font tens of
# thousands; a one-line `/ToUnicode` range can make 65,536, and each costs
# memory (about 160 bytes) and time to build.
MAX_FONT_ENTRIES = 1_000_000
MAX_SECONDS_PER_FILE = 60
# Recovering a damaged compressed stream is a byte-at-a-time loop in the
# library; a real damaged stream is a page's worth.
MAX_RECOVERY_BYTES = 1024 * 1024
MAX_XMP_BYTES = 1024 * 1024
MAX_XMP_ELEMENTS = 10_000
# Objects the library may visit to find a document catalogue that is missing.
MAX_ROOT_RECOVERY = 10_000

# The scanned-PDF rule: fewer than SCAN_MIN_CHARS characters (whitespace not
# counted) on the first SCAN_PAGES pages, or on all of them when there are fewer,
# means there is no text layer to read. A real book's cover, half-title and
# title pages can be nearly empty, so the window is ten pages, not one; a scan
# whose only text is a page number or a scanner's stamp stays under 200.
SCAN_PAGES = 10
SCAN_MIN_CHARS = 200
# Past the first ten pages a book is read whatever it holds; when fewer than
# this share of all its pages have text, the caller is told the rest may be
# scanned, since text-layer front matter over a scanned body passes the rule.
SPARSE_TEXT_SHARE = 0.5

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
    # What the caller should say about a book it indexes anyway: an outline
    # that was not used (the sections are then pages), pages without text.
    notes: list[str] = field(default_factory=list)


def mib(n: int) -> str:
    return f"{n // (1024 * 1024)} MiB"


ENCRYPTED = ("encrypted (password-protected or restricted; no password was tried and "
             "nothing was decrypted)")
NOT_ENGAGED = "the reader's limits did not engage (library version?)"


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
        self.font_entries = 0
        self.font_calls = 0
        # The longest string one code maps to, over the fonts this page uses.
        self.page_expansion = 1
        self.deadline = time.monotonic() + MAX_SECONDS_PER_FILE
        self.over: str | None = None

    def refuse(self, reason: str) -> None:
        if self.over is None:
            self.over = reason
        raise PdfRefused(self.over)

    def check(self) -> None:
        if self.over is None and time.monotonic() > self.deadline:
            self.over = f"it took longer than {MAX_SECONDS_PER_FILE} s to read"
        if self.over is not None:
            raise PdfRefused(self.over)

    def new_page(self) -> None:
        self.page_content = 0
        self.page_shown = 0
        self.page_expansion = 1

    def font(self, entries: int, expansion: int) -> None:
        """A font the page (or a form it draws) uses; `entries` is 0 when it
        was built earlier in this file and is handed back, not rebuilt."""
        self.font_calls += 1
        self.page_expansion = max(self.page_expansion, expansion)
        self.font_entries += entries
        if self.font_entries > MAX_FONT_ENTRIES:
            self.refuse(f"its fonts' character maps and widths hold more than "
                        f"{MAX_FONT_ENTRIES:,} entries")

    def inflated(self, n: int) -> None:
        self.decoded += n
        if self.decoded > MAX_DECODED_BYTES:
            self.refuse(f"its compressed streams inflate past {mib(MAX_DECODED_BYTES)} "
                        "in all")

    def parsed(self, n: int) -> None:
        self.page_content += n
        self.content += n
        if self.page_content > MAX_PAGE_CONTENT_BYTES:
            self.refuse_page_content()
        if self.content > MAX_CONTENT_BYTES:
            self.refuse(f"it has more than {mib(MAX_CONTENT_BYTES)} of drawing "
                        "instructions in all")

    def refuse_page_content(self) -> None:
        self.refuse(f"a page in it has more than {mib(MAX_PAGE_CONTENT_BYTES)} of drawing "
                    "instructions")

    def shown(self, n: int) -> None:
        self.page_shown += n
        if self.page_shown > MAX_PAGE_CHARS:
            self.refuse(page_chars_reason())

    def visit(self, operator, operands, *_matrices) -> None:
        """`pypdf`'s per-instruction callback (a public extraction hook). A
        shown byte is charged as the longest string a code of the page's fonts
        maps to: a `/ToUnicode` map can turn one byte into 256 characters, and
        what the cap bounds is the text the library builds, not the bytes."""
        self.check()
        if operator in SHOW_TEXT:
            self.shown(self.page_expansion
                       * sum(shown_length(operand) for operand in operands))


def shown_length(operand) -> int:
    if isinstance(operand, (str, bytes)):
        return len(operand)
    if isinstance(operand, list):                    # TJ: strings and kerning numbers
        return sum(len(item) for item in operand if isinstance(item, (str, bytes)))
    return 0


def page_chars_reason() -> str:
    return f"a page in it holds more than {MAX_PAGE_CHARS:,} characters of text"


def font_size(font) -> tuple[int, int]:
    """(entries, expansion) of a font the library built: the entries of its
    character map, encoding and width table, and the longest string one code
    maps to."""
    character_map = font.character_map or {}
    encoding = font.encoding if isinstance(font.encoding, dict) else {}
    entries = len(character_map) + len(encoding) + len(font.character_widths or {})
    expansion = max((len(value) for value in character_map.values()
                     if isinstance(value, str)), default=1)
    return entries, max(expansion, 1)


@contextmanager
def _bounded(budget: _Budget):
    """`pypdf` with this module's caps, for the length of one read.

    Three of the caps have no setting in the library, so they are counted at
    the three places the work passes through: `pypdf.filters.decode_stream_data`,
    the one function that inflates a stream; the `ContentStream` that
    `pypdf._page` builds for every page and every form before it parses one;
    and `Font.from_font_resource`, which builds a font's maps for every page
    and every form draw that uses it. All three are put back when the read
    ends, however it ends, and a test pins that each is still where the
    library looks for it; `page_text` refuses a page whose text came out with
    nothing counted, should a later version look elsewhere."""
    decode = pypdf.filters.decode_stream_data
    content_stream = pypdf._page.ContentStream
    font_class = pypdf._font.Font
    from_font_resource = font_class.__dict__["from_font_resource"]   # the classmethod
    built: dict[int, tuple] = {}

    def counted_font(cls, font_dict):
        """Each font dictionary is built once per file: the library would build
        it again for every page and every form draw, and an empty form drawn
        200 times would rebuild every font it names 200 times. The entry keeps
        the dictionary alive, so its `id` cannot be reused for another."""
        budget.check()
        known = built.get(id(font_dict))
        if known is None or known[0] is not font_dict:
            try:
                font = from_font_resource.__func__(cls, font_dict)
            except Exception as error:
                built[id(font_dict)] = (font_dict, error, 1)
                raise
            entries, expansion = font_size(font)
            built[id(font_dict)] = (font_dict, font, expansion)
            budget.font(entries, expansion)
            return font
        _, font, expansion = known
        if isinstance(font, Exception):
            raise font                               # failed once: not retried
        budget.font(0, expansion)
        return font

    def counted_decode(stream):
        budget.check()                               # refuse before inflating more
        data = decode(stream)
        budget.inflated(len(data))
        return data

    class CountedContentStream(content_stream):
        def __init__(self, stream, pdf, forced_encoding=None):
            budget.check()
            try:
                super().__init__(stream, pdf, forced_encoding)
            except LimitReachedError:
                # The library's own cap on what it joins or inflates for one
                # page or form (a stream past MAX_STREAM_BYTES, a split page
                # past MAX_PAGE_CONTENT_BYTES): too much content, said so.
                budget.refuse_page_content()
            # Counted after the bytes are joined and before they are parsed:
            # parsing is lazy, and `operations` is what costs the time.
            budget.parsed(len(self.get_data()))

    # Every limit the library's configuration has, set here rather than left
    # at its default, so that what bounds a read is written in this file.
    configuration = dict(
        # No stream is longer than the file that holds it.
        maximum_declared_stream_length=MAX_FILE_BYTES,
        # One inflated stream, whatever filter inflates it.
        zlib_maximum_output_length=MAX_STREAM_BYTES,
        lzw_maximum_output_length=MAX_STREAM_BYTES,
        run_length_maximum_output_length=MAX_STREAM_BYTES,
        jbig2_maximum_output_length=MAX_STREAM_BYTES,
        # Images are never decoded here; capped all the same.
        image_maximum_buffer_size=MAX_STREAM_BYTES,
        # The predictor geometry of a Flate stream (images, cross-reference
        # streams): the library's own values, written out.
        flate_maximum_columns=250_000,
        flate_maximum_row_length=4_000_000,
        zlib_maximum_recovery_input_length=MAX_RECOVERY_BYTES,
        # A page whose content is split over several streams, joined.
        array_based_stream_maximum_output_length=MAX_PAGE_CONTENT_BYTES,
        page_tree_maximum_entries=2 * MAX_PAGES,
        page_tree_maximum_depth=MAX_PAGE_TREE_DEPTH,
        outline_maximum_entries=MAX_OUTLINE_ENTRIES,
        outline_maximum_depth=MAX_OUTLINE_DEPTH,
        xform_maximum_invocations_per_extraction=MAX_FORM_DRAWS,
        xmp_maximum_input_length=MAX_XMP_BYTES,
        xmp_maximum_element_count=MAX_XMP_ELEMENTS,
        # The one external program the library can start (JBIG2 images): never.
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
        font_class.from_font_resource = classmethod(counted_font)
        try:
            yield
        finally:
            pypdf.filters.decode_stream_data = decode
            pypdf._page.ContentStream = content_stream
            font_class.from_font_resource = from_font_resource
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
    if raw.strip() and not (budget.content and budget.font_calls):
        # Text came out of a page, so the library parsed content and built a
        # font, and the counting points saw neither: it looks for them
        # somewhere else now, and nothing it does is bounded.
        budget.refuse(NOT_ENGAGED)
    if len(raw) > MAX_PAGE_CHARS:
        budget.refuse(page_chars_reason())
    return clean_text(raw)


def read_pages(reader: PdfReader, budget: _Budget) -> list[str]:
    try:
        count = len(reader.pages)
    except LimitReachedError as error:
        budget.check()
        # Too many entries or too many levels: the library does not say which.
        raise PdfRefused("its page tree is too deep or too large to read") from error
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
        return [], "its outline is too deep or too large to read"
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
                reader = _Reader(fp, strict=False,
                                 root_object_recovery_limit=MAX_ROOT_RECOVERY)
                if reader.is_encrypted:
                    raise PdfRefused(ENCRYPTED)
                texts = read_pages(reader, budget)
                title, author = metadata(reader, budget)
                starts, note = outline_starts(reader, budget, len(texts))
                budget.check()
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
    notes = [f"{note}; its pages are the sections instead"] if note else []
    with_text = sum(1 for text in texts if text)
    if with_text < SPARSE_TEXT_SHARE * len(texts):
        notes.append(f"only {with_text} of its {len(texts)} pages have text (the others "
                     "may be scanned images, which are not read)")
    return PdfBook(title=title, author=author, sections=sections, notes=notes)
