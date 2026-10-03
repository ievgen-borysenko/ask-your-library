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
  `Front matter`. A page is the smallest unit: the page an entry points to
  belongs wholly to that entry's section, so a chapter that starts halfway
  down a page takes the end of the chapter before it along; when two entries
  point at the same page the first one names it;
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

A PDF is untrusted input, and **the bound is a process boundary**. `read_pdf`
does not read the file: it starts a child Python process
(`python -I -m ask_your_library.ingest.pdf --child <path>`) that does, in a
session (and process group) of its own, and bounds it. The parent caps the
child's wall-clock time (`MAX_SECONDS_PER_FILE`): past it the whole process
group is killed, and so it is on any abnormal end. The child never forks; if a
`fork` happened anyway, the group kill takes the descendant too. The child caps
its own memory: at start-up it starts one watcher thread that reads the
process's high-water mark of resident memory (`getrusage(RUSAGE_SELF).ru_maxrss`)
every `MEMORY_SAMPLE_SECONDS` and ends the process with `EXIT_MEMORY` past
`MAX_CHILD_RSS_BYTES`; the mark only rises, so an allocation freed between two
samples is still seen, and the same check runs once more before the child
prints its result. On Linux the child also caps its address space at twice
that (`RLIMIT_AS`). A watcher that cannot start or cannot measure ends the
child with `EXIT_UNMEASURED`, a refusal: a file is never read unmeasured.
Whatever the library does inside, however a hostile file makes it allocate or
loop, it ends in one of those refusals. No external program is started; the
parent never imports `pypdf`, runs no thread and handles no signal.

Inside the child, the first line is a set of caps that give a precise reason
fast, on what the library lets a caller bound:

- **never done**: no JavaScript is evaluated and no action (launch, URI,
  submit, GoTo another file) is followed — `pypdf` implements none of them, and
  an outline entry is used only for the page number of this document it names;
  embedded files and attachments are never read; pages are not rendered, images
  are never decoded, and no font is loaded to draw a glyph (a Type 1 font
  program embedded without a `/ToUnicode` map is read by `pypdf` for its
  encoding table only); `pypdf`'s one external program, `jbig2dec` for JBIG2
  images, is switched off in its configuration; an encrypted file is refused
  before any password, the empty one included, is tried;
- **the library's configuration**, every field set explicitly (`CONFIGURATION`):
  each inflated stream capped (`MAX_STREAM_BYTES`), the page-tree walk stopped
  past `2 * MAX_PAGES` entries or `MAX_PAGE_TREE_DEPTH` levels and the outline
  walk past `MAX_OUTLINE_ENTRIES` entries or `MAX_OUTLINE_DEPTH` levels, at most
  `MAX_FORM_DRAWS` forms drawn a page, XMP size and element count, the
  recovery of a damaged stream; the library also detects reference cycles,
  forbids entity declarations in XMP and rebuilds a damaged cross-reference
  table by one scan;
- **ours**: the file size (`MAX_FILE_BYTES`, on the open file before the library
  reads it); the number of pages (`MAX_PAGES`); the bytes a page shows as
  text, counted per instruction through the library's public extraction
  callback while the page is interpreted, and the characters it yields
  (`MAX_PAGE_CHARS`); the characters of the whole book (`MAX_TOTAL_CHARS`).

What these do not bound — the work and memory the library spends building a
font's maps, a `/Differences` array of millions of names, a CMap range that
stands for 65,536 entries, a form drawn two hundred times — the process
boundary does. An earlier version counted those from inside, by replacing names
in the library; each review found one more allocation the counters did not
see, and the process boundary is the bound that does not depend on finding
them all.

The child prints one JSON document on stdout and exits with a known status
(`EXIT_READ`, `EXIT_REFUSED`, `EXIT_ERROR`; `EXIT_MEMORY` and
`EXIT_UNMEASURED` print nothing); its stderr is discarded unread.
Every refusal is a `PdfRefused` carrying a reason written here: it names no
part of the document and quotes no text of it, so the caller's one line about
the file says which file and why, and nothing of what is in it. Inside the
child, `pypdf`'s own log lines and warnings are silenced while it reads (they
can quote bytes of the document): the handler lists of the `pypdf` loggers are
replaced, not added to, and `logging.lastResort` with them, and all of it is
put back afterwards. That is process-global state for the length of one read,
so `read_in_process` assumes it is the only code using `pypdf` while it runs;
in the child, it is.
"""
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from ..sanitize import LINE_BREAK_RE, strip_control_chars
from .chapters import FRONT_MATTER_SECTION, unique_titles

# --- bounds -------------------------------------------------------------------
# A long novel is 300-600 pages and under 2 MB of text; a dense page is 3,000 to
# 5,000 characters. Every cap is far past that.
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_PAGES = 5_000
MAX_STREAM_BYTES = 16 * 1024 * 1024          # one inflated stream (the library's cap)
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
# Recovering a damaged compressed stream is a byte-at-a-time loop in the
# library; a real damaged stream is a page's worth.
MAX_RECOVERY_BYTES = 1024 * 1024
MAX_XMP_BYTES = 1024 * 1024
MAX_XMP_ELEMENTS = 10_000
# Objects the library may visit to find a document catalogue that is missing.
MAX_ROOT_RECOVERY = 10_000

# The process boundary. A 400-page book reads in about 0.6 s and 40 MiB.
MAX_SECONDS_PER_FILE = 60
MAX_CHILD_RSS_BYTES = 1024 * 1024 * 1024
# How often the child's watcher reads its high-water mark; the mark itself
# catches what happens between two reads, so this sets only how far past the
# cap a fast allocation can run before the child is ended.
MEMORY_SAMPLE_SECONDS = 0.02

# Every field of the library's `Configuration`, set here rather than left at its
# default, so that what bounds a read is written in this file.
CONFIGURATION = dict(
    # No stream is longer than the file that holds it.
    maximum_declared_stream_length=MAX_FILE_BYTES,
    # One inflated stream, whatever filter inflates it.
    zlib_maximum_output_length=MAX_STREAM_BYTES,
    lzw_maximum_output_length=MAX_STREAM_BYTES,
    run_length_maximum_output_length=MAX_STREAM_BYTES,
    jbig2_maximum_output_length=MAX_STREAM_BYTES,
    # A page whose content is split over several streams, joined.
    array_based_stream_maximum_output_length=MAX_STREAM_BYTES,
    # Images are never decoded here; capped all the same.
    image_maximum_buffer_size=MAX_STREAM_BYTES,
    # The predictor geometry of a Flate stream (images, cross-reference
    # streams): the library's own values, written out.
    flate_maximum_columns=250_000,
    flate_maximum_row_length=4_000_000,
    zlib_maximum_recovery_input_length=MAX_RECOVERY_BYTES,
    page_tree_maximum_entries=2 * MAX_PAGES,
    page_tree_maximum_depth=MAX_PAGE_TREE_DEPTH,
    outline_maximum_entries=MAX_OUTLINE_ENTRIES,
    outline_maximum_depth=MAX_OUTLINE_DEPTH,
    xform_maximum_invocations_per_extraction=MAX_FORM_DRAWS,
    xmp_maximum_input_length=MAX_XMP_BYTES,
    xmp_maximum_element_count=MAX_XMP_ELEMENTS,
    # The one external program the library can start (JBIG2 images): never.
    jbig2dec_binary=None,
    # Page merging, which is never done here; the library's own value.
    page_merge_box="cropbox",
    # The library's older module-level constants are not consulted: what
    # bounds a read is this dictionary and nothing a module elsewhere set.
    disable_legacy_handling=True,
)

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

# The child's exit statuses. Anything else (a crash, a signal) is a refusal
# that names the status and nothing else.
EXIT_READ, EXIT_REFUSED, EXIT_ERROR, EXIT_MEMORY, EXIT_UNMEASURED = 0, 3, 4, 5, 6


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
    """A size as the docs write it: whole GiB when it is one, else MiB."""
    gib = 1024 * 1024 * 1024
    return f"{n // gib} GiB" if n >= gib and n % gib == 0 else f"{n // (1024 * 1024)} MiB"


ENCRYPTED = ("encrypted (password-protected or restricted; no password was tried and "
             "nothing was decrypted)")


def too_slow_reason() -> str:
    return f"it took longer than {MAX_SECONDS_PER_FILE} s to read"


def too_big_reason() -> str:
    return f"it needed more than {mib(MAX_CHILD_RSS_BYTES)} of memory to read"


UNMEASURED = "memory cannot be measured here, so the file is not read"


def page_chars_reason() -> str:
    return f"a page in it holds more than {MAX_PAGE_CHARS:,} characters of text"


# === the parent: one child process per file ======================================

def child_command(path: Path) -> list[str]:
    """The child's command line. `-I`: isolated, so neither the working
    directory nor a PYTHON* variable can put another module in front of this
    package's (a `json.py` in the folder `ayl add` was started from, say)."""
    return [sys.executable, "-I", "-m", "ask_your_library.ingest.pdf", "--child", str(path),
            "--max-bytes", str(MAX_CHILD_RSS_BYTES)]


def read_pdf(path: Path) -> PdfBook:
    """The whole read, in a child process bounded from here. Raises
    `PdfRefused` for anything that is not indexed."""
    try:
        if Path(path).stat().st_size > MAX_FILE_BYTES:
            raise PdfRefused(f"the file is larger than {mib(MAX_FILE_BYTES)}")
    except OSError as error:
        raise PdfRefused("the file cannot be read") from error
    try:
        # A session of its own: the child leads a new process group, and the
        # group is what is killed, descendants included.
        proc = subprocess.Popen(child_command(path), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                start_new_session=True)
    except OSError as error:
        raise PdfRefused(UNMEASURED) from error
    normal = False
    try:
        try:
            # Reads the child's stdout while it runs, so a large book cannot
            # fill the pipe and stall it.
            out, _ = proc.communicate(timeout=MAX_SECONDS_PER_FILE)
        except subprocess.TimeoutExpired as error:
            raise PdfRefused(too_slow_reason()) from error
        normal = proc.returncode in (EXIT_READ, EXIT_REFUSED, EXIT_ERROR)
    finally:
        if not normal:
            kill_group(proc)
    return parse_child_output(proc.returncode, out)


def kill_group(proc: subprocess.Popen) -> None:
    """Kill the child's process group — the child and anything it started —
    and reap the child. A group with no member left is not an error."""
    for kill in (lambda: os.killpg(proc.pid, signal.SIGKILL), proc.kill):
        try:
            kill()
        except OSError:                              # already gone
            pass
    try:
        proc.communicate(timeout=5)                  # reap it, close the pipe
    except (ValueError, OSError, subprocess.TimeoutExpired):
        pass                                         # already reaped


def parse_child_output(status: int, out: bytes) -> PdfBook:
    """The child's exit status and stdout -> the book, or the refusal."""
    if status == EXIT_MEMORY:
        raise PdfRefused(too_big_reason())
    if status == EXIT_UNMEASURED:
        raise PdfRefused(UNMEASURED)
    if status not in (EXIT_READ, EXIT_REFUSED, EXIT_ERROR):
        raise PdfRefused(f"could not be read (the reader stopped with status {status})")
    unreadable = PdfRefused("could not be read (the reader's output was not readable)")
    try:
        doc = json.loads(out.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise unreadable from error
    if not isinstance(doc, dict):
        raise unreadable
    if status == EXIT_REFUSED and isinstance(doc.get("refused"), str):
        raise PdfRefused(doc["refused"])
    if status == EXIT_ERROR and isinstance(doc.get("error"), str):
        raise PdfRefused(f"could not be read ({doc['error']})")
    sections, notes = doc.get("sections"), doc.get("notes")
    if (status != EXIT_READ or not isinstance(doc.get("title"), str)
            or not isinstance(doc.get("author"), str) or not isinstance(sections, list)
            or not isinstance(notes, list) or not all(isinstance(n, str) for n in notes)
            or not all(isinstance(s, list) and len(s) == 2
                       and all(isinstance(part, str) for part in s) for s in sections)):
        raise unreadable
    return PdfBook(title=doc["title"], author=doc["author"],
                   sections=[(title, text) for title, text in sections], notes=notes)


# === the child: the read itself =====================================================

def memory_over(limit: int) -> bool:
    """Whether this process's resident memory has ever passed `limit`: the
    high-water mark, in bytes on macOS and KiB on Linux."""
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak * (1 if sys.platform == "darwin" else 1024) > limit


def watch_memory(limit: int) -> None:
    """The child's memory cap: one daemon thread that ends the process when
    its high-water mark passes `limit`, or when it cannot be read. Only ever
    called in the child, which is the process it may end."""
    import threading

    def watch():
        try:
            while True:
                if memory_over(limit):
                    os._exit(EXIT_MEMORY)
                time.sleep(MEMORY_SAMPLE_SECONDS)
        except BaseException:
            os._exit(EXIT_UNMEASURED)

    try:
        memory_over(limit)                       # measurable at all, before reading
        threading.Thread(target=watch, name="memory-watch", daemon=True).start()
    except BaseException:
        os._exit(EXIT_UNMEASURED)


def emit(status: int, doc: dict, limit: int) -> int:
    """The child's last act: the memory check once more (an allocation since
    the watcher's last look is in the high-water mark), then the one JSON
    document on stdout."""
    try:
        over = memory_over(limit)
    except BaseException:
        os._exit(EXIT_UNMEASURED)
    if over:
        os._exit(EXIT_MEMORY)
    sys.stdout.buffer.write(json.dumps(doc, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()
    return status


def child_main(argv: list[str]) -> int:
    """`python -I -m ask_your_library.ingest.pdf --child <path> --max-bytes N`:
    read one file, print one JSON document on stdout, exit with a known status.
    Never forks."""
    if len(argv) != 4 or argv[0] != "--child" or argv[2] != "--max-bytes":
        return 2
    global MAX_CHILD_RSS_BYTES
    path, max_bytes = Path(argv[1]), int(argv[3])
    # The parent's cap, so that a MemoryError here is reported in its terms.
    MAX_CHILD_RSS_BYTES = max_bytes
    if sys.platform.startswith("linux"):
        # A second wall on Linux, set before anything is read. Address space
        # runs ahead of resident memory, hence twice; macOS does not enforce
        # RLIMIT_AS.
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (2 * max_bytes, 2 * max_bytes))
    watch_memory(max_bytes)
    try:
        book = read_in_process(path)
        status, doc = EXIT_READ, {"title": book.title, "author": book.author,
                                  "sections": book.sections, "notes": book.notes}
    except PdfRefused as reason:
        status, doc = EXIT_REFUSED, {"refused": str(reason)}
    except MemoryError:
        os._exit(EXIT_MEMORY)
    except Exception as error:
        # The class only: the message can quote the document.
        status, doc = EXIT_ERROR, {"error": type(error).__name__}
    return emit(status, doc, max_bytes)


@contextmanager
def quiet_pypdf():
    """The library's log lines and warnings, dropped for the length of a read.

    Its messages can quote the document, so it is not enough to add a handler
    that drops them: a handler someone attached earlier would still receive
    them. The handler list of the `pypdf` logger and of every `pypdf.*` logger
    that exists is replaced by a single `NullHandler`, propagation is turned
    off, and `logging.lastResort` is a `NullHandler` too; the exact lists,
    levels and flags are put back afterwards. Process-global, for one read."""
    manager = logging.Logger.manager
    loggers = [logging.getLogger("pypdf")] + [
        logger for name, logger in list(manager.loggerDict.items())
        if name.startswith("pypdf.") and isinstance(logger, logging.Logger)]
    saved = [(logger, logger.handlers, logger.level, logger.propagate) for logger in loggers]
    last_resort = logging.lastResort
    try:
        for logger in loggers:
            logger.handlers = [logging.NullHandler()]
            logger.propagate = False
        logging.lastResort = logging.NullHandler()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            yield
    finally:
        for logger, handlers, level, propagate in saved:
            logger.handlers = handlers
            logger.setLevel(level)
            logger.propagate = propagate
        logging.lastResort = last_resort


def reader_class():
    """`PdfReader` that refuses an encrypted file instead of trying a password.

    `PdfReader` tries the empty password on any encrypted file as it opens it
    (an owner-password-only file opens that way). This project does not work
    around a protection, whichever kind, so the attempt is replaced by the
    refusal; `read_in_process` checks `is_encrypted` afterwards as well, in
    case a later version of the library stops calling this method. Built on
    demand, so that the parent never imports the library."""
    from pypdf import PdfReader

    class Reader(PdfReader):
        def _handle_encryption(self, password) -> None:
            raise PdfRefused(ENCRYPTED)

    return Reader


class _PageText:
    """The text a page shows, counted per instruction while it is interpreted.

    The refusal is sticky: the library catches broad exceptions in a few places
    (a form it cannot draw is skipped), so one raised inside them can be
    swallowed; once `over` is set, every later instruction raises it again, and
    `page_text` checks it after the page, so it always surfaces."""

    def __init__(self):
        self.shown = 0
        self.over = False

    def visit(self, operator, operands, *_matrices) -> None:
        """The library's per-instruction callback (a public extraction hook)."""
        if not self.over and operator in SHOW_TEXT:
            self.shown += sum(shown_length(operand) for operand in operands)
            self.over = self.shown > MAX_PAGE_CHARS
        if self.over:
            raise PdfRefused(page_chars_reason())


def shown_length(operand) -> int:
    if isinstance(operand, (str, bytes)):
        return len(operand)
    if isinstance(operand, list):                    # TJ: strings and kerning numbers
        return sum(len(item) for item in operand if isinstance(item, (str, bytes)))
    return 0


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


def page_text(page) -> str:
    counter = _PageText()
    raw = page.extract_text(visitor_operand_before=counter.visit)
    # A refusal the library swallowed, and the characters a page's fonts made
    # of what it showed: one code may map to a string of up to 256.
    if counter.over or len(raw) > MAX_PAGE_CHARS:
        raise PdfRefused(page_chars_reason())
    return clean_text(raw)


def read_pages(reader) -> list[str]:
    from pypdf.errors import LimitReachedError
    try:
        count = len(reader.pages)
    except LimitReachedError as error:
        # Too many entries or too many levels: the library does not say which.
        raise PdfRefused("its page tree is too deep or too large to read") from error
    if count > MAX_PAGES:
        raise PdfRefused(f"it has {count:,} pages, and the limit is {MAX_PAGES:,}")
    if count == 0:
        raise PdfRefused("it has no pages")
    texts: list[str] = []
    total = 0
    for index in range(count):
        text = page_text(reader.pages[index])
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

def metadata(reader) -> tuple[str, str]:
    """(title, author) from the information dictionary, else from XMP."""
    title = author = ""
    try:
        info = reader.metadata
        if info is not None:
            title, author = clean_label(info.title), clean_label(info.author)
    except Exception:
        pass                                         # absent, for the file-name rule
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
    except Exception:
        pass
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


def outline_starts(reader, count: int) -> tuple[list[tuple[int, str]], str]:
    """[(first page index, title)] in page order, one per page, and the reason
    the outline was not used when it was not ("" when there is none)."""
    from pypdf.errors import LimitReachedError
    try:
        outline = reader.outline
    except LimitReachedError:
        return [], "its outline is too deep or too large to read"
    except Exception as error:
        return [], f"its outline could not be read ({type(error).__name__})"
    if not outline:
        return [], ""
    starts: dict[int, str] = {}
    for entry in outline_level(outline):
        title = clean_label(getattr(entry, "title", None))
        try:
            page = reader.get_destination_page_number(entry)
        except Exception:
            page = None
        if not title or not isinstance(page, int) or not 0 <= page < count:
            continue                                 # points at no page of this file
        starts.setdefault(page, title)
    if not starts:
        return [], "no entry of its outline points at a page of the document"
    return sorted(starts.items()), ""


def build_sections(texts: list[str], starts: list[tuple[int, str]]) -> list[tuple[str, str]]:
    """Page texts -> [(section title, text)]: one section per outline start,
    from the page it points to up to the page before the next one; one per page
    without starts."""
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


def read_in_process(path: Path) -> PdfBook:
    """The read itself, in this process: what the child runs. Raises
    `PdfRefused` for anything that is not indexed.

    Any exception the library raises on a damaged file is a refusal naming its
    class only: its message can quote bytes of the document. Called directly,
    nothing but the caps above bounds it; `read_pdf` is the bounded read."""
    from pypdf import apply_configuration
    try:
        with open(path, "rb") as fp:
            size = os.fstat(fp.fileno()).st_size
            if size > MAX_FILE_BYTES:
                raise PdfRefused(f"the file is larger than {mib(MAX_FILE_BYTES)}")
            with quiet_pypdf(), apply_configuration(**CONFIGURATION):
                reader = reader_class()(fp, strict=False,
                                        root_object_recovery_limit=MAX_ROOT_RECOVERY)
                if reader.is_encrypted:
                    raise PdfRefused(ENCRYPTED)
                texts = read_pages(reader)
                title, author = metadata(reader)
                starts, note = outline_starts(reader, len(texts))
    except (PdfRefused, MemoryError):
        raise                                        # the child reports memory itself
    except OSError as error:
        raise PdfRefused("the file cannot be read") from error
    except Exception as error:
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


if __name__ == "__main__":
    raise SystemExit(child_main(sys.argv[1:]))
