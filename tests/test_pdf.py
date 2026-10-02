"""`ayl add` reads `.pdf` (#34): structure, bounds, refusals, and the private book.

Every PDF here is written in code into tmp_path by `make_pdf`, a small writer
of uncompressed (or Flate-compressed) content streams in the standard Type 1
font Helvetica, which no PDF needs to embed: no binary fixture is committed,
no real book is read, and the tests do not depend on the library's own writer.
The text is invented, low-entropy and plainly synthetic. No network: the
embedder is faked as in test_add_folder.py, the index is a tmp_path LanceDB.
"""
import logging
import os
import time
import tracemalloc
import zlib

import lancedb
import pypdf
import pypdf._page
import pypdf.filters
import pytest

from ask_your_library import ayl, library
from ask_your_library.ingest import add_folder, pdf
from ask_your_library.ingest.chapters import FRONT_MATTER_SECTION
from ask_your_library.ingest.lock import lock_path
from ask_your_library.preflight import PreflightResult
from conftest import REPO
from test_add_folder import PARA, fake_embedder, write  # noqa: F401
# The audit hook that watches every write is installed once, by test_epub, for
# the whole process; the PDF leak test arms the same one.
from test_epub import ROOM, _armed, _writes, make_epub, three_chapters

# --- writing a PDF ---------------------------------------------------------------


def esc(text: str) -> bytes:
    return (text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            .encode("latin-1"))


def show(lines) -> bytes:
    """A content stream that shows each line, one under the other."""
    ops = [b"BT /F1 11 Tf 14 TL 72 740 Td"]
    ops += [b"(" + esc(line) + b") Tj T*" for line in lines]
    return b"\n".join(ops + [b"ET"])


def room(word: str, times: int = 4) -> list[str]:
    return [ROOM.format(word).strip()] * times


class Outline:
    """One outline entry: `target` is a page index, or the raw bytes of a
    destination's first element (`b"99 0 R"`, `b"40"`)."""

    def __init__(self, title, target, children=()):
        self.title, self.target, self.children = title, target, list(children)


def make_pdf(path, pages, *, info=None, outline=None, encrypt=False, compress=False,
             form=None, xmp=None, outline_first=None):
    """A minimal PDF 1.4 at `path`. `pages` holds, per page, a list of lines or
    the raw bytes of its content stream; `form` (bytes) is a form XObject every
    page can draw as `/X1 Do`; `outline_first` replaces the outline root's
    `/First` with raw bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    objects: list[bytes | None] = [None, None]        # 1: catalog, 2: page tree

    def add(body):
        objects.append(body)
        return len(objects)

    def stream(data: bytes) -> int:
        extra = b""
        if compress:
            data, extra = zlib.compress(data, 9), b" /Filter /FlateDecode"
        return add(b"<< /Length %d%s >>\nstream\n" % (len(data), extra) + data
                   + b"\nendstream")

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
               b"/Encoding /WinAnsiEncoding >>")
    xobject = b""
    if form is not None:
        data = zlib.compress(form, 9) if compress else form
        flt = b" /Filter /FlateDecode" if compress else b""
        x = add(b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] /Resources "
                b"<< /Font << /F1 %d 0 R >> >> /Length %d%s >>\nstream\n"
                % (font, len(data), flt) + data + b"\nendstream")
        xobject = b" /XObject << /X1 %d 0 R >>" % x
    page_ids = []
    for content in pages:
        c = stream(content if isinstance(content, bytes) else show(content))
        page_ids.append(add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                            b"/Resources << /Font << /F1 %d 0 R >>%s >> /Contents %d 0 R >>"
                            % (font, xobject, c)))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (
        b" ".join(b"%d 0 R" % p for p in page_ids), len(page_ids))
    catalog = b"<< /Type /Catalog /Pages 2 0 R"

    def entries(items, parent):
        ids = [add(None) for _ in items]
        for i, item in enumerate(items):
            target = (b"%d 0 R" % page_ids[item.target] if isinstance(item.target, int)
                      else item.target)
            body = b"<< /Title (%s) /Parent %d 0 R /Dest [%s /Fit]" % (
                esc(item.title), parent, target)
            if i:
                body += b" /Prev %d 0 R" % ids[i - 1]
            if i + 1 < len(ids):
                body += b" /Next %d 0 R" % ids[i + 1]
            if item.children:
                kids = entries(item.children, ids[i])
                body += b" /First %d 0 R /Last %d 0 R /Count %d" % (kids[0], kids[-1],
                                                                     len(kids))
            objects[ids[i] - 1] = body + b" >>"
        return ids

    if outline or outline_first:
        root = add(None)
        if outline_first:
            objects[root - 1] = b"<< /Type /Outlines /First %s >>" % outline_first
        else:
            ids = entries(outline, root)
            objects[root - 1] = b"<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (
                ids[0], ids[-1], len(ids))
        catalog += b" /Outlines %d 0 R" % root
    if xmp is not None:
        catalog += b" /Metadata %d 0 R" % add(
            b"<< /Type /Metadata /Subtype /XML /Length %d >>\nstream\n" % len(xmp)
            + xmp + b"\nendstream")
    objects[0] = catalog + b" >>"
    trailer = b""
    if info:
        trailer += b" /Info %d 0 R" % add(
            b"<< " + b" ".join(b"/%s (%s)" % (k.encode(), esc(v)) for k, v in info.items())
            + b" >>")
    if encrypt:
        # A standard security handler, RC4 40-bit: its keys are left as zero
        # bytes, since nothing here may ever try to use them.
        zeros = b"<" + b"00" * 32 + b">"
        enc = add(b"<< /Filter /Standard /V 1 /R 2 /O %s /U %s /P -44 >>" % (zeros, zeros))
        trailer += b" /Encrypt %d 0 R /ID [<%s> <%s>]" % (enc, b"00" * 16, b"00" * 16)

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R%s >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, trailer, xref)
    path.write_bytes(bytes(out))
    return path


KETTLE = {"Title": "The Copper Kettle", "Author": "Ada Quill"}


def five_pages():
    return [room("amber", 1), room("birch"), room("cedar"), room("delta"), room("ember")]


def titles(book):
    return [t for t, _ in book.sections]


def refused(path):
    with pytest.raises(pdf.PdfRefused) as refusal:
        pdf.read_pdf(path)
    return str(refusal.value)


# --- structure -----------------------------------------------------------------------

def test_one_page_is_one_section_and_the_metadata_is_the_key(tmp_path):
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", [room("amber")], info=KETTLE))
    assert (book.title, book.author) == ("The Copper Kettle", "Ada Quill")
    assert book.sections == [("Page 1", "\n".join(room("amber")))]
    assert book.outline_note == ""


def test_without_an_outline_every_page_with_text_is_a_section(tmp_path):
    pages = [room("amber"), [], room("cedar"), room("delta")]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", pages))
    # The empty page is no section, and the numbering keeps its gap.
    assert titles(book) == ["Page 1", "Page 3", "Page 4"]
    assert "cedar room" in book.sections[1][1] and "amber" not in book.sections[1][1]


def test_an_outline_of_three_entries_is_three_sections_and_front_matter(tmp_path):
    outline = [Outline("Chapter One", 1), Outline("Chapter Two", 2), Outline("Chapter Three", 4)]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == [FRONT_MATTER_SECTION, "Chapter One", "Chapter Two",
                            "Chapter Three"]
    text = dict(book.sections)
    assert "amber" in text[FRONT_MATTER_SECTION]
    assert "birch" in text["Chapter One"] and "cedar" not in text["Chapter One"]
    # A section runs to the page before the next entry's: two pages here.
    assert text["Chapter Two"].count("room") == 2 * len(room("cedar")) * 2
    assert "cedar" in text["Chapter Two"] and "delta" in text["Chapter Two"]
    assert "ember" in text["Chapter Three"]


def test_outline_entries_that_point_at_no_page_are_ignored(tmp_path):
    outline = [Outline("Chapter One", 0),
               Outline("Past the end", b"40 0 R"),         # no such object
               Outline("A page number", b"40"),             # an integer, not a page
               Outline("", 2),                              # no title
               Outline("Chapter Two", 3)]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["Chapter One", "Chapter Two"]
    assert "cedar" in dict(book.sections)["Chapter One"]


def test_outline_order_does_not_decide_reading_order_and_a_page_has_one_name(tmp_path):
    outline = [Outline("Later", 3), Outline("Earlier", 0), Outline("Also earlier", 0)]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["Earlier", "Later"]


def test_a_single_root_entry_is_read_through_to_its_children(tmp_path):
    outline = [Outline("The Copper Kettle", 0, [Outline("One", 1), Outline("Two", 3)])]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == [FRONT_MATTER_SECTION, "One", "Two"]


def test_nested_entries_below_the_top_level_do_not_split_a_section(tmp_path):
    outline = [Outline("One", 0, [Outline("One, part two", 1)]), Outline("Two", 2)]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["One", "Two"]
    assert "birch" in dict(book.sections)["One"]


def test_repeated_outline_titles_are_made_unique(tmp_path):
    outline = [Outline("Notes", 0), Outline("Notes", 2)]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["Notes", "Notes (2)"]


def test_an_outline_that_points_nowhere_falls_back_to_pages_and_says_so(tmp_path):
    outline = [Outline("Lost", b"40 0 R"), Outline("Also lost", b"41 0 R")]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages()[:2], outline=outline))
    assert titles(book) == ["Page 1", "Page 2"]
    assert book.outline_note == "no entry of its outline points at a page of the document"


def test_an_outline_that_is_not_a_tree_falls_back_to_pages(tmp_path):
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages()[:2],
                                 outline_first=b"(not an entry)"))
    assert titles(book) == ["Page 1", "Page 2"]


def test_an_outline_over_its_cap_falls_back_to_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_OUTLINE_ENTRIES", 2)
    outline = [Outline("One", 0), Outline("Two", 1), Outline("Three", 2)]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book)[:2] == ["Page 1", "Page 2"]
    assert book.outline_note == "its outline has more than 2 entries"


def test_whitespace_is_normalised_controls_stripped_and_hyphens_kept(tmp_path):
    lines = ["The   amber\troom is quiet-", "ly lit\x1b[2J at noon.", "   ", "A  lamp."]
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", [lines + room("birch")]))
    assert book.sections[0][1].startswith(
        "The amber room is quiet-\nly lit[2J at noon.\nA lamp.\n")


def test_flate_compressed_pages_are_read(tmp_path):
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), compress=True))
    assert titles(book) == ["Page 1", "Page 2", "Page 3", "Page 4", "Page 5"]


def test_text_drawn_through_a_form_is_read(tmp_path):
    form = show(room("fern"))
    book = pdf.read_pdf(make_pdf(tmp_path / "b.pdf", [b"/X1 Do"], form=form))
    assert "fern room" in book.sections[0][1]


# --- metadata --------------------------------------------------------------------------

XMP = (b'<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>'
       b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
       b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
       b'<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
       b'<dc:title><rdf:Alt><rdf:li xml:lang="x-default">The Tin Bell</rdf:li></rdf:Alt>'
       b"</dc:title><dc:creator><rdf:Seq><rdf:li>Bo Reed</rdf:li><rdf:li>Cy Ink</rdf:li>"
       b"</rdf:Seq></dc:creator></rdf:Description></rdf:RDF></x:xmpmeta>"
       b'<?xpacket end="r"?>')


def test_xmp_fills_what_the_information_dictionary_lacks(tmp_path):
    book = pdf.read_pdf(make_pdf(tmp_path / "x.pdf", five_pages(), xmp=XMP))
    assert (book.title, book.author) == ("The Tin Bell", "Bo Reed, Cy Ink")
    both = pdf.read_pdf(make_pdf(tmp_path / "y.pdf", five_pages(), xmp=XMP,
                                 info={"Title": "The Copper Kettle"}))
    assert (both.title, both.author) == ("The Copper Kettle", "Bo Reed, Cy Ink")


def test_xmp_with_an_entity_declaration_is_ignored_not_expanded(tmp_path):
    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]>'
            + XMP.replace(b"The Tin Bell", b"&a;"))
    book = pdf.read_pdf(make_pdf(tmp_path / "x.pdf", five_pages(), xmp=bomb))
    assert (book.title, book.author) == ("", "")


def test_the_file_name_rule_when_there_is_no_title(tmp_path):
    folder = tmp_path / "books"
    make_pdf(folder / "The Quiet Mill - Bo Reed.pdf", five_pages())
    make_pdf(folder / "Plain.pdf", five_pages(), info={"Author": "Ada Quill"})
    make_pdf(folder / "Titled.pdf", five_pages(), info={"Title": "The Tin Bell\x07"})
    books = {b.path.name: b.book for b in add_folder.read_folder(folder)}
    assert books == {"The Quiet Mill - Bo Reed.pdf": "The Quiet Mill — Bo Reed",
                     "Plain.pdf": "Plain — Unknown",
                     "Titled.pdf": "The Tin Bell — Unknown"}


# --- refusals ----------------------------------------------------------------------------

NO_TEXT_LAYER = ("no text layer (fewer than 200 characters of text on its first {n} "
                 "page{s}): a scanned PDF needs OCR, which ayl does not do")


def test_a_scanned_pdf_is_refused(tmp_path):
    """An image-only page draws no text: its content stream is empty here."""
    assert refused(make_pdf(tmp_path / "b.pdf", [b""] * 3)) == NO_TEXT_LAYER.format(n=3, s="s")
    assert refused(make_pdf(tmp_path / "c.pdf", [b""])) == NO_TEXT_LAYER.format(n=1, s="")


def test_the_scan_rule_reads_the_first_ten_pages(tmp_path):
    # Text from page 11 on is not enough: the rule is the first ten pages.
    late = [b""] * 10 + [room("amber")] * 2
    assert refused(make_pdf(tmp_path / "late.pdf", late)) == NO_TEXT_LAYER.format(n=10, s="s")
    # A near-empty cover and title page are not a scan.
    early = [[], ["The Copper Kettle"], room("amber"), room("birch")]
    assert titles(pdf.read_pdf(make_pdf(tmp_path / "early.pdf", early))) == [
        "Page 2", "Page 3", "Page 4"]


def test_a_page_number_alone_is_not_a_text_layer(tmp_path):
    pages = [[str(n)] for n in range(1, 13)]
    assert refused(make_pdf(tmp_path / "b.pdf", pages)) == NO_TEXT_LAYER.format(n=10, s="s")


def test_an_encrypted_pdf_is_refused_and_no_password_is_tried(tmp_path, monkeypatch):
    def tried(*args, **kwargs):
        raise AssertionError("a password was tried")
    monkeypatch.setattr(pypdf._encryption.Encryption, "read", tried)
    monkeypatch.setattr(pypdf._encryption.Encryption, "verify", tried)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages(), encrypt=True)) == (
        "encrypted (password-protected or restricted; no password was tried and nothing "
        "was decrypted)")


def test_the_encryption_check_stands_without_the_reader_override(tmp_path, monkeypatch):
    """Belt and braces: were the library to stop calling the method the
    override replaces, `is_encrypted` still refuses the file."""
    monkeypatch.delattr(pdf._Reader, "_handle_encryption")
    monkeypatch.setattr(pypdf.PdfReader, "_handle_encryption", lambda self, password: None)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages(), encrypt=True)).startswith(
        "encrypted")


@pytest.mark.parametrize("damage", ["garbage", "empty", "truncated", "no xref", "half"])
def test_a_malformed_pdf_is_refused_by_class(tmp_path, damage):
    path = make_pdf(tmp_path / "b.pdf", five_pages(), info=KETTLE)
    data = path.read_bytes()
    path.write_bytes({"garbage": b"this is not a PDF at all " * 4,
                      "empty": b"",
                      "truncated": data[:40],
                      "no xref": b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n",
                      "half": data[:len(data) // 2]}[damage])
    reason = refused(path)
    assert reason.startswith("could not be read (") and reason.endswith(")")
    assert "amber" not in reason and "Kettle" not in reason


def test_a_damaged_cross_reference_table_is_rebuilt(tmp_path):
    path = make_pdf(tmp_path / "b.pdf", five_pages())
    data = path.read_bytes()
    at = data.rindex(b"startxref\n") + len(b"startxref\n")
    path.write_bytes(data[:at] + b"999999\n%%EOF\n")          # points at nothing
    assert len(pdf.read_pdf(path).sections) == 5


def test_a_file_over_the_size_cap_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_FILE_BYTES", 1024)
    monkeypatch.setattr(pdf, "_Reader", None)                  # never reached
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "the file is larger than 0 MiB")


def test_too_many_pages_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PAGES", 3)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "it has 5 pages, and the limit is 3")


def test_a_page_tree_past_the_cap_is_not_walked_to_its_end(tmp_path, monkeypatch):
    """The library's page-tree walk stops at 2 * MAX_PAGES entries, so a tree
    of a million entries is not materialised before the count is refused."""
    monkeypatch.setattr(pdf, "MAX_PAGES", 2)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "its page tree is larger than the limit of 2 pages")


def test_a_page_over_the_text_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PAGE_CHARS", 500)
    pages = [room("amber"), room("birch", 12)]
    assert refused(make_pdf(tmp_path / "b.pdf", pages)) == (
        "a page in it holds more than 500 characters of text")


def test_a_book_over_the_total_text_cap_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_TOTAL_CHARS", 500)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "it holds more than 500 characters of text")


def tj_bomb(times: int) -> bytes:
    return b"BT /F1 11 Tf 72 740 Td " + b"(aaaa) Tj " * times + b"ET"


def peak_bytes(call) -> int:
    tracemalloc.start()
    try:
        call()
    finally:
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
    return peak


def test_a_compression_bomb_under_the_stream_cap_stops_at_the_page_text_cap(tmp_path):
    """3.3 MB of `(aaaa) Tj` in a 7 KB page: interpreted, it would be 1.3
    million characters, and the library's text assembly grows faster than
    linearly (the same shape at 14 MB took 36 s). The count of shown bytes
    stops it at MAX_PAGE_CHARS instead, well before the end of the page."""
    path = make_pdf(tmp_path / "b.pdf", [room("amber"), tj_bomb(330_000)], compress=True)
    assert path.stat().st_size < 20_000
    started = time.monotonic()
    assert refused(path) == "a page in it holds more than 100,000 characters of text"
    assert time.monotonic() - started < 5


def test_a_compression_bomb_over_the_stream_cap_is_cut_off_by_the_library(tmp_path):
    """24 MB of drawing instructions in a 24 KB stream: the library stops
    inflating at MAX_STREAM_BYTES, and nothing past it is allocated (the peak
    is the capped output and one copy of it). The library's refusal is said
    as what it is, too much content for a page."""
    path = make_pdf(tmp_path / "b.pdf", [room("amber"), b"q Q " * 6_000_000], compress=True)
    assert path.stat().st_size < 100_000
    started = time.monotonic()
    peak = peak_bytes(lambda: refused(path))
    assert refused(path) == "a page in it has more than 4 MiB of drawing instructions"
    assert peak < 2 * pdf.MAX_STREAM_BYTES + 4 * 1024 * 1024, peak
    assert time.monotonic() - started < 5


def test_drawing_instructions_past_the_page_cap_are_refused_before_they_are_parsed(
        tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_PAGE_CONTENT_BYTES", 64 * 1024)
    path = make_pdf(tmp_path / "b.pdf", [room("amber"), b"q Q " * 20_000], compress=True)
    assert refused(path) == "a page in it has more than 0 MiB of drawing instructions"


def test_a_form_drawn_many_times_counts_every_time(tmp_path, monkeypatch):
    """A 10 KB form drawn 50 times is 500 KB to parse, though it is one
    object: every draw is counted, before the library parses it."""
    monkeypatch.setattr(pdf, "MAX_PAGE_CONTENT_BYTES", 256 * 1024)
    form = b"q Q " * 2_500 + show(["x"])
    path = make_pdf(tmp_path / "b.pdf", [room("amber"), b"/X1 Do " * 50], form=form)
    assert refused(path) == "a page in it has more than 0 MiB of drawing instructions"
    # Drawn a few times, the same form is read.
    fine = make_pdf(tmp_path / "f.pdf", [room("amber"), b"/X1 Do " * 3], form=form)
    assert len(pdf.read_pdf(fine).sections) == 2


def test_drawing_instructions_past_the_file_cap_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_CONTENT_BYTES", 600)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "it has more than 0 MiB of drawing instructions in all")


def test_everything_inflated_in_one_file_is_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_DECODED_BYTES", 600)
    path = make_pdf(tmp_path / "b.pdf", five_pages(), compress=True)
    assert refused(path) == "its compressed streams inflate past 0 MiB in all"


def test_the_library_is_left_as_it_was_found(tmp_path, monkeypatch, caplog):
    """The two counting points are put back after every read, refused or not,
    and are still the names the library looks up when it inflates a stream and
    when it parses a page: if a later version moved them, the counting would
    stop silently, and this is where that shows."""
    decode, content_stream = pypdf.filters.decode_stream_data, pypdf._page.ContentStream
    propagate = logging.getLogger("pypdf").propagate
    seen = []
    monkeypatch.setattr(pdf._Budget, "inflated", lambda self, n: seen.append(("inflated", n)))
    monkeypatch.setattr(pdf._Budget, "parsed", lambda self, n: seen.append(("parsed", n)))
    pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages(), compress=True))
    assert {kind for kind, _ in seen} == {"inflated", "parsed"}
    refused(make_pdf(tmp_path / "e.pdf", five_pages(), encrypt=True))
    assert pypdf.filters.decode_stream_data is decode
    assert pypdf._page.ContentStream is content_stream
    assert logging.getLogger("pypdf").propagate is propagate


def test_the_library_logs_nothing_while_it_reads(tmp_path, caplog):
    """A damaged outline makes the library log the node it could not read,
    quoting it; nothing of that reaches the log."""
    path = make_pdf(tmp_path / "b.pdf", five_pages()[:2],
                    outline_first=b"(the amber room logs this)")
    data = path.read_bytes()
    at = data.rindex(b"startxref\n") + len(b"startxref\n")
    path.write_bytes(data[:at] + b"999999\n%%EOF\n")
    with caplog.at_level(logging.DEBUG):
        pdf.read_pdf(path)
    assert caplog.records == []


# --- in a folder -----------------------------------------------------------------------

def mixed_folder(tmp_path):
    folder = tmp_path / "books"
    write(folder, "Sea Notes - B. Mate.txt", PARA)
    write(folder, "The Green Ledger - A. Keeper.md", "## One\n\n" + PARA)
    make_epub(folder / "kettle.epub", three_chapters())
    make_pdf(folder / "mill.pdf", five_pages(), info={"Title": "The Quiet Mill",
                                                      "Author": "Bo Reed"},
             outline=[Outline("Chapter One", 0), Outline("Chapter Two", 2)])
    make_pdf(folder / "nested" / "Scanned.pdf", [b""] * 4)
    return folder


def test_a_refused_pdf_is_left_out_and_named_and_the_rest_is_read(tmp_path, caplog):
    folder = mixed_folder(tmp_path)
    with caplog.at_level("WARNING"):
        books = add_folder.read_folder(folder)
    assert sorted(b.book for b in books) == ["Sea Notes — B. Mate",
                                             "The Copper Kettle — Ada Quill",
                                             "The Green Ledger — A. Keeper",
                                             "The Quiet Mill — Bo Reed"]
    assert [r.getMessage() for r in caplog.records] == [
        f"{os.path.join('nested', 'Scanned.pdf')}: {NO_TEXT_LAYER.format(n=4, s='s')}, skipped"]


def test_a_folder_with_a_refused_pdf_still_adds_the_others_and_exits_0(tmp_path,
                                                                    fake_embedder, capsys):
    folder = mixed_folder(tmp_path)
    assert add_folder.main([str(folder), "--db", str(tmp_path / "db")]) == 0
    assert "added 4 books" in capsys.readouterr().out
    rows = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").to_arrow().to_pylist()
    mill = [r for r in rows if r["book"] == "The Quiet Mill — Bo Reed"]
    assert {r["section"] for r in mill} == {"Chapter One", "Chapter Two"}
    assert {r["source"] for r in mill} == {"local:mill.pdf"}


def test_an_unusable_outline_is_named_and_the_pages_are_indexed(tmp_path, caplog):
    folder = tmp_path / "books"
    make_pdf(folder / "lost.pdf", five_pages()[:2], outline=[Outline("Lost", b"40 0 R")])
    with caplog.at_level("WARNING"):
        [book] = add_folder.read_folder(folder)
    assert [t for t, _ in book.sections] == ["Page 1", "Page 2"]
    assert [r.getMessage() for r in caplog.records] == [
        "lost.pdf: no entry of its outline points at a page of the document; its pages are "
        "the sections instead"]


def test_a_folder_named_like_a_pdf_is_named_once_and_nothing_inside_it_is_read(tmp_path,
                                                                             caplog):
    folder = tmp_path / "books"
    write(folder, "Sea Notes - B. Mate.txt", PARA)
    odd = folder / "Odd.pdf"
    write(odd, "notes.txt", PARA)
    make_pdf(odd / "inner.pdf", five_pages())
    with caplog.at_level("WARNING"):
        books = add_folder.read_folder(folder)
    assert [b.path.name for b in books] == ["Sea Notes - B. Mate.txt"]
    assert [r.getMessage() for r in caplog.records] == [
        "Odd.pdf: a folder named like a PDF, skipped (a PDF is a single file)"]


def test_a_folder_of_only_refused_pdfs_is_one_error_line(tmp_path, fake_embedder, capsys):
    folder = tmp_path / "books"
    make_pdf(folder / "Locked.pdf", five_pages(), encrypt=True)
    assert add_folder.main([str(folder), "--db", str(tmp_path / "db")]) == 1
    assert "no readable text" in capsys.readouterr().err
    assert not (tmp_path / "db").exists()


def test_an_unexpected_exception_is_a_skip_named_without_its_text(tmp_path, fake_embedder,
                                                                 capsys, caplog, monkeypatch):
    def boom(path):
        raise RuntimeError(f"the {CANARY} room said something")
    monkeypatch.setattr(add_folder, "read_pdf", boom)
    folder = tmp_path / "books"
    write(folder, "Sea Notes - B. Mate.txt", PARA)
    make_pdf(folder / "odd.pdf", five_pages())
    with caplog.at_level("WARNING"):
        assert add_folder.main([str(folder), "--db", str(tmp_path / "db")]) == 0
    out = capsys.readouterr()
    messages = [r.getMessage() for r in caplog.records]
    assert "odd.pdf: could not be read (RuntimeError), skipped" in messages
    assert CANARY not in out.out + out.err + "\n".join(messages)


def test_ayl_add_then_ayl_books_lists_the_pdf(tmp_path, fake_embedder, monkeypatch, capsys):
    folder = tmp_path / "books"
    make_pdf(folder / "kettle.pdf", five_pages(), info=KETTLE)
    write(folder, "Sea Notes - B. Mate.txt", PARA)
    db = tmp_path / "db"
    assert ayl.main(["add", str(folder), "--db", str(db)]) == 0
    capsys.readouterr()
    monkeypatch.setattr(library, "DB_PATH", db)
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult([], (), []))
    assert ayl.main(["books"]) == 0
    out = capsys.readouterr().out
    assert "The Copper Kettle — Ada Quill" in out and "Sea Notes — B. Mate" in out


# --- the private book ------------------------------------------------------------------
# The same two tests as the EPUB's: where the run writes, and what it says.

CANARY = "zqzqxvxv"
SECRET_ROOM = f"The {CANARY} room keeps its own counsel."


def private_folder(tmp_path):
    folder = tmp_path / "reader" / "my books"
    secret = [[SECRET_ROOM] * 6, [SECRET_ROOM] * 6]
    make_pdf(folder / "private.pdf", secret, info={"Title": "A Private Book",
                                                   "Author": "R. Reader"},
             outline=[Outline("Chapter One", 0), Outline(f"{CANARY} lost", b"40 0 R")],
             compress=True)
    # Refused ones too: a refusal must name the file, not quote it.
    make_pdf(folder / "Locked.pdf", secret, info={"Title": f"The {CANARY} Book"},
             encrypt=True)
    damaged = make_pdf(folder / "damaged.pdf", secret, info={"Title": f"The {CANARY} Book"})
    damaged.write_bytes(damaged.read_bytes()[:-400])
    # And one the library complains about while it reads it, quoting the file.
    noisy = make_pdf(folder / "noisy.pdf", secret, outline_first=f"({CANARY})".encode())
    data = noisy.read_bytes()
    at = data.rindex(b"startxref\n") + len(b"startxref\n")
    noisy.write_bytes(data[:at] + b"999999\n%%EOF\n")
    return folder


def test_a_private_pdf_is_written_only_to_the_index_named_for_the_run(tmp_path, monkeypatch,
                                                                     fake_embedder):
    """The EPUB's audit-hook test, over PDFs: every write the run attempts from
    Python lands in the index this run was given or the lock beside it; the
    tables LanceDB's native code writes are read back from that index."""
    folder = private_folder(tmp_path)
    db = tmp_path / "run-index"
    monkeypatch.setattr(add_folder, "DB_PATH", db)
    monkeypatch.chdir(tmp_path)
    _writes.clear()
    _armed.set()
    try:
        assert add_folder.main([str(folder)]) == 0
    finally:
        _armed.clear()
    targets = [(event, os.path.realpath(os.path.abspath(p))) for event, p in _writes]
    assert targets, "the audit hook saw no write at all: it is not watching"
    index, lock = os.path.realpath(db), os.path.realpath(lock_path(db))

    def allowed(event, path):
        return (path in (index, lock) or path.startswith(index + os.sep)
                or (event == "os.mkdir" and path == os.path.realpath(db.parent)))

    stray = [(event, path) for event, path in targets if not allowed(event, path)]
    assert stray == [], stray
    assert not any(p.startswith(os.path.realpath(REPO) + os.sep) for _, p in targets)
    rows = lancedb.connect(db).open_table("transcripts_ollama").to_arrow().to_pylist()
    assert {r["book"] for r in rows} == {"A Private Book — R. Reader", "noisy — Unknown"}
    assert sorted(p.name for p in folder.iterdir()) == ["Locked.pdf", "damaged.pdf",
                                                        "noisy.pdf", "private.pdf"]


def test_nothing_of_a_private_pdf_reaches_the_output_or_the_log(tmp_path, monkeypatch,
                                                               fake_embedder, capsys, caplog):
    folder = private_folder(tmp_path)
    monkeypatch.setattr(add_folder, "DB_PATH", tmp_path / "run-index")
    with caplog.at_level(logging.DEBUG):
        assert add_folder.main([str(folder)]) == 0
        assert add_folder.main([str(folder), "--dry-run"]) == 0
    out = capsys.readouterr()
    records = [r.getMessage() for r in caplog.records]
    everything = out.out + out.err + "\n".join(records)
    assert CANARY not in everything
    assert any(CANARY in text for text in fake_embedder.seen)   # it WAS read and embedded
    refusals = [m for m in records if m.startswith(("damaged.pdf", "Locked.pdf"))]
    assert len(refusals) == 4, records                          # two files, two runs
    for line in refusals:
        assert str(folder) not in line and str(tmp_path) not in line
