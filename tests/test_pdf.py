"""`ayl add` reads `.pdf` (#34): structure, bounds, refusals, and the private book.

Every PDF here is written in code into tmp_path by `make_pdf`, a small writer
of uncompressed (or Flate-compressed) content streams in the standard Type 1
font Helvetica, which no PDF needs to embed: no binary fixture is committed,
no real book is read, and the tests do not depend on the library's own writer.
The text is invented, low-entropy and plainly synthetic. No network: the
embedder is faked as in test_add_folder.py, the index is a tmp_path LanceDB.
"""
import dataclasses
import io
import logging
import os
import subprocess
import sys
import threading
import time
import tracemalloc
import zlib
from pathlib import Path

import lancedb
import pypdf
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
             form=None, xmp=None, outline_first=None, cmaps=None, fonts_per_page=False):
    """A minimal PDF 1.4 at `path`. `pages` holds, per page, a list of lines or
    the raw bytes of its content stream; `form` (bytes) is a form XObject every
    page can draw as `/X1 Do`; `outline_first` replaces the outline root's
    `/First` with raw bytes. `cmaps` maps more font names to `/ToUnicode`
    CMaps (Helvetica with that map, one CMap stream each); with
    `fonts_per_page`, every page gets font dictionaries of its own."""
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
    maps = {name: stream(data) for name, data in (cmaps or {}).items()}

    def font_resources() -> bytes:
        extra = b"".join(
            b" /%s %d 0 R" % (name.encode(), add(
                b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode %d 0 R >>" % m))
            for name, m in maps.items())
        return b"<< /F1 %d 0 R%s >>" % (font, extra)

    shared_fonts = font_resources()
    xobject = b""
    if form is not None:
        data = zlib.compress(form, 9) if compress else form
        flt = b" /Filter /FlateDecode" if compress else b""
        x = add(b"<< /Type /XObject /Subtype /Form /BBox [0 0 612 792] /Resources "
                b"<< /Font %s >> /Length %d%s >>\nstream\n"
                % (shared_fonts, len(data), flt) + data + b"\nendstream")
        xobject = b" /XObject << /X1 %d 0 R >>" % x
    page_ids = []
    for content in pages:
        c = stream(content if isinstance(content, bytes) else show(content))
        fonts = font_resources() if fonts_per_page else shared_fonts
        page_ids.append(add(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                            b"/Resources << /Font %s%s >> /Contents %d 0 R >>"
                            % (fonts, xobject, c)))
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


def make_differences_pdf(path, names: int):
    """A PDF 1.5 whose one font has an `/Encoding` with a `/Differences` array
    of `names` repeated glyph names, kept in a Flate-compressed object stream
    behind a cross-reference stream: millions of entries in a few KiB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = b"<< /Type /Encoding /Differences [0" + b" /A" * names + b"] >>"
    packed = zlib.compress(b"5 0 " + encoding, 9)
    content = show(room("amber"))
    bodies = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
           b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        4: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding 5 0 R >>",
        6: b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream",
        7: b"<< /Type /ObjStm /N 1 /First 4 /Filter /FlateDecode /Length %d >>\nstream\n"
           % len(packed) + packed + b"\nendstream",
    }
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for n, body in bodies.items():
        offsets[n] = len(out)
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    offsets[8] = len(out)
    rows = [b"\x00" + (0).to_bytes(4, "big") + b"\xff\xff"]
    for n in range(1, 9):
        if n == 5:
            rows.append(b"\x02" + (7).to_bytes(4, "big") + (0).to_bytes(2, "big"))
        else:
            rows.append(b"\x01" + offsets[n].to_bytes(4, "big") + (0).to_bytes(2, "big"))
    xref = b"".join(rows)
    out += (b"8 0 obj\n<< /Type /XRef /Size 9 /W [1 4 2] /Root 1 0 R /Length %d >>\nstream\n"
            % len(xref) + xref + b"\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % offsets[8])
    path.write_bytes(bytes(out))
    return path


def cmap(*sections: bytes) -> bytes:
    """A `/ToUnicode` CMap with these `beginbfchar`/`beginbfrange` sections."""
    return (b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
            b"/CMapName /Synthetic def\n1 begincodespacerange <00> <FF> endcodespacerange\n"
            + b"\n".join(sections)
            + b"\nendcmap CMapName currentdict /CMap defineresource pop end end")


# One range, 31 bytes, that the library expands to 65,536 mapping entries.
WIDE_RANGE = b"1 beginbfrange\n<0000> <FFFF> <0041>\nendbfrange"


def five_pages():
    return [room("amber", 1), room("birch"), room("cedar"), room("delta"), room("ember")]


def titles(book):
    return [t for t, _ in book.sections]


def refused(path):
    with pytest.raises(pdf.PdfRefused) as refusal:
        pdf.read_in_process(path)
    return str(refusal.value)


# --- structure -----------------------------------------------------------------------

def test_one_page_is_one_section_and_the_metadata_is_the_key(tmp_path):
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", [room("amber")], info=KETTLE))
    assert (book.title, book.author) == ("The Copper Kettle", "Ada Quill")
    assert book.sections == [("Page 1", "\n".join(room("amber")))]
    assert book.notes == []


def test_without_an_outline_every_page_with_text_is_a_section(tmp_path):
    pages = [room("amber"), [], room("cedar"), room("delta")]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", pages))
    # The empty page is no section, and the numbering keeps its gap.
    assert titles(book) == ["Page 1", "Page 3", "Page 4"]
    assert "cedar room" in book.sections[1][1] and "amber" not in book.sections[1][1]


def test_an_outline_of_three_entries_is_three_sections_and_front_matter(tmp_path):
    outline = [Outline("Chapter One", 1), Outline("Chapter Two", 2), Outline("Chapter Three", 4)]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
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
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["Chapter One", "Chapter Two"]
    assert "cedar" in dict(book.sections)["Chapter One"]


def test_outline_order_does_not_decide_reading_order_and_a_page_has_one_name(tmp_path):
    outline = [Outline("Later", 3), Outline("Earlier", 0), Outline("Also earlier", 0)]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["Earlier", "Later"]


def test_a_single_root_entry_is_read_through_to_its_children(tmp_path):
    outline = [Outline("The Copper Kettle", 0, [Outline("One", 1), Outline("Two", 3)])]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == [FRONT_MATTER_SECTION, "One", "Two"]


def test_nested_entries_below_the_top_level_do_not_split_a_section(tmp_path):
    outline = [Outline("One", 0, [Outline("One, part two", 1)]), Outline("Two", 2)]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["One", "Two"]
    assert "birch" in dict(book.sections)["One"]


def test_repeated_outline_titles_are_made_unique(tmp_path):
    outline = [Outline("Notes", 0), Outline("Notes", 2)]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book) == ["Notes", "Notes (2)"]


def test_an_outline_that_points_nowhere_falls_back_to_pages_and_says_so(tmp_path):
    outline = [Outline("Lost", b"40 0 R"), Outline("Also lost", b"41 0 R")]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages()[:2], outline=outline))
    assert titles(book) == ["Page 1", "Page 2"]
    assert book.notes == ["no entry of its outline points at a page of the document; its pages "
                          "are the sections instead"]


def test_an_outline_that_is_not_a_tree_falls_back_to_pages(tmp_path):
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages()[:2],
                                 outline_first=b"(not an entry)"))
    assert titles(book) == ["Page 1", "Page 2"]


OUTLINE_TOO_BIG = ("its outline is too deep or too large to read; its pages are the sections "
                   "instead")


def test_an_outline_over_its_cap_falls_back_to_pages(tmp_path, monkeypatch):
    monkeypatch.setitem(pdf.CONFIGURATION, "outline_maximum_entries", 2)
    outline = [Outline("One", 0), Outline("Two", 1), Outline("Three", 2)]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), outline=outline))
    assert titles(book)[:2] == ["Page 1", "Page 2"]
    assert book.notes == [OUTLINE_TOO_BIG]


def test_an_outline_too_deep_falls_back_to_pages(tmp_path):
    entry = Outline("Leaf", 1)
    for depth in range(40):                          # past MAX_OUTLINE_DEPTH
        entry = Outline(f"Level {depth}", 0, [entry])
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(),
                                 outline=[entry, Outline("Two", 2)]))
    assert titles(book)[:2] == ["Page 1", "Page 2"]
    assert book.notes == [OUTLINE_TOO_BIG]


def test_whitespace_is_normalised_controls_stripped_and_hyphens_kept(tmp_path):
    lines = ["The   amber\troom is quiet-", "ly lit\x1b[2J at noon.", "   ", "A  lamp."]
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", [lines + room("birch")]))
    assert book.sections[0][1].startswith(
        "The amber room is quiet-\nly lit[2J at noon.\nA lamp.\n")


def test_flate_compressed_pages_are_read(tmp_path):
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", five_pages(), compress=True))
    assert titles(book) == ["Page 1", "Page 2", "Page 3", "Page 4", "Page 5"]


def test_text_drawn_through_a_form_is_read(tmp_path):
    form = show(room("fern"))
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", [b"/X1 Do"], form=form))
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
    book = pdf.read_in_process(make_pdf(tmp_path / "x.pdf", five_pages(), xmp=XMP))
    assert (book.title, book.author) == ("The Tin Bell", "Bo Reed, Cy Ink")
    both = pdf.read_in_process(make_pdf(tmp_path / "y.pdf", five_pages(), xmp=XMP,
                                 info={"Title": "The Copper Kettle"}))
    assert (both.title, both.author) == ("The Copper Kettle", "Bo Reed, Cy Ink")


def test_xmp_with_an_entity_declaration_is_ignored_not_expanded(tmp_path):
    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]>'
            + XMP.replace(b"The Tin Bell", b"&a;"))
    book = pdf.read_in_process(make_pdf(tmp_path / "x.pdf", five_pages(), xmp=bomb))
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
    assert titles(pdf.read_in_process(make_pdf(tmp_path / "early.pdf", early))) == [
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
    monkeypatch.setattr(pdf, "reader_class", lambda: pypdf.PdfReader)
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
    assert len(pdf.read_in_process(path).sections) == 5


def test_a_file_over_the_size_cap_is_refused_before_it_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_FILE_BYTES", 1024)
    monkeypatch.setattr(pdf, "reader_class", None)             # never reached
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
    monkeypatch.setitem(pdf.CONFIGURATION, "page_tree_maximum_entries", 4)
    assert refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "its page tree is too deep or too large to read")


def test_a_page_tree_too_deep_is_refused(tmp_path):
    """A chain of page-tree nodes, each holding the next: the library walks
    it recursively, and stops at MAX_PAGE_TREE_DEPTH."""
    path = make_pdf(tmp_path / "b.pdf", [room("amber")])
    data = path.read_bytes()
    # Object 2 is the page tree; wrap it in 80 more levels, appended as an
    # incremental update with its own cross-reference section.
    size = int(data.rsplit(b"/Size ", 1)[1].split()[0])
    out = bytearray(data)
    offsets = {}
    kid = 2
    for n in range(size, size + 80):
        offsets[n] = len(out)
        out += b"%d 0 obj\n<< /Type /Pages /Kids [%d 0 R] /Count 1 >>\nendobj\n" % (n, kid)
        kid = n
    offsets[1] = len(out)
    out += b"1 0 obj\n<< /Type /Catalog /Pages %d 0 R >>\nendobj\n" % kid
    xref = len(out)
    out += b"xref\n0 1\n0000000000 65535 f \n1 1\n%010d 00000 n \n" % offsets[1]
    out += b"%d 80\n" % size + b"".join(b"%010d 00000 n \n" % offsets[n]
                                         for n in range(size, size + 80))
    prev = int(data.rsplit(b"startxref", 1)[1].split()[0])
    out += b"trailer\n<< /Size %d /Root 1 0 R /Prev %d >>\nstartxref\n%d\n%%%%EOF\n" % (
        size + 80, prev, xref)
    path.write_bytes(bytes(out))
    assert refused(path) == "its page tree is too deep or too large to read"


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
    is the capped output and one copy of it)."""
    path = make_pdf(tmp_path / "b.pdf", [room("amber"), b"q Q " * 6_000_000], compress=True)
    assert path.stat().st_size < 100_000
    started = time.monotonic()
    peak = peak_bytes(lambda: refused(path))
    assert refused(path) == "could not be read (LimitReachedError)"
    assert peak < 2 * pdf.MAX_STREAM_BYTES + 4 * 1024 * 1024, peak
    assert time.monotonic() - started < 5


def test_the_form_draws_on_a_page_are_capped(tmp_path, monkeypatch):
    """Past MAX_FORM_DRAWS the library skips the rest of a page's forms."""
    monkeypatch.setitem(pdf.CONFIGURATION, "xform_maximum_invocations_per_extraction", 3)
    form = show(["The fern room has one lamp."])
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf",
                                        [show(room("amber")) + b" /X1 Do" * 10], form=form))
    assert book.sections[0][1].count("fern room") == 3


# --- what the page text cap counts --------------------------------------------------
# One code can map to a long string: the library caps a `/ToUnicode`
# destination at 512 bytes, 256 characters. 250 here.

LONG_CODE = cmap(b"1 beginbfchar\n<01> <" + b"0061" * 250 + b">\nendbfchar")


def long_codes(times: int) -> bytes:
    return b"BT /F2 11 Tf 72 400 Td " + b"(\\001) Tj " * times + b"ET"


def test_the_page_text_cap_counts_shown_bytes_and_then_the_characters_they_made(tmp_path):
    """While the page is interpreted the cap counts shown bytes; after it, the
    characters the fonts made of them. 300 one-byte codes of 250 characters
    each are 75,000 characters: read. 500 are 125,000: under the cap on shown
    bytes, over it on characters, refused when the page is done. Between the
    two, the work is bounded by the process boundary, not by this cap."""
    fine = pdf.read_in_process(make_pdf(tmp_path / "f.pdf", [long_codes(300)],
                                        cmaps={"F2": LONG_CODE}))
    assert len(fine.sections[0][1]) == 300 * 250
    assert refused(make_pdf(tmp_path / "b.pdf", [long_codes(500)], cmaps={"F2": LONG_CODE})) == (
        "a page in it holds more than 100,000 characters of text")


# --- the scan rule's other edge --------------------------------------------------------

def test_mostly_textless_pages_are_indexed_and_named(tmp_path):
    """Text-layer front matter over a scanned body passes the first-ten-pages
    rule; what it has is indexed, and the caller is told how little that is."""
    pages = [room("amber")] * 10 + [b""] * 15
    book = pdf.read_in_process(make_pdf(tmp_path / "b.pdf", pages))
    assert len(book.sections) == 10
    assert book.notes == ["only 10 of its 25 pages have text (the others may be scanned "
                          "images, which are not read)"]
    half = pdf.read_in_process(make_pdf(tmp_path / "h.pdf", [room("amber")] * 10 + [b""] * 10))
    assert half.notes == []


# --- the library's logging --------------------------------------------------------------

def noisy_pdf(path, words=b"the amber room logs this"):
    """A PDF whose damaged outline the library logs, quoting it."""
    path = make_pdf(path, five_pages()[:2], outline_first=b"(" + words + b")")
    data = path.read_bytes()
    at = data.rindex(b"startxref\n") + len(b"startxref\n")
    path.write_bytes(data[:at] + b"999999\n%%EOF\n")
    return path


def test_the_library_logs_nothing_while_it_reads(tmp_path, caplog):
    with caplog.at_level(logging.DEBUG):
        pdf.read_in_process(noisy_pdf(tmp_path / "b.pdf"))
    assert caplog.records == []


def test_a_handler_already_on_the_library_s_loggers_hears_nothing(tmp_path):
    """Adding a handler that drops records is not enough: one attached
    earlier, to `pypdf` or to one of its module loggers, would still receive
    the quote. The lists are replaced for the read and put back exactly."""
    heard = io.StringIO()
    handler = logging.StreamHandler(heard)
    parent, module = logging.getLogger("pypdf"), logging.getLogger("pypdf._doc_common")
    before = [(lg.handlers[:], lg.level, lg.propagate) for lg in (parent, module)]
    last_resort = logging.lastResort
    parent.addHandler(handler)
    module.addHandler(handler)
    try:
        pdf.read_in_process(noisy_pdf(tmp_path / "b.pdf"))
        assert heard.getvalue() == ""
        assert parent.handlers[-1] is handler and module.handlers[-1] is handler
        assert logging.lastResort is last_resort
    finally:
        parent.removeHandler(handler)
        module.removeHandler(handler)
    assert [(lg.handlers, lg.level, lg.propagate) for lg in (parent, module)] == before


# --- the process boundary ---------------------------------------------------------------
# `read_pdf` reads in a child process and bounds it from outside. The first
# review's reproducers and the merge gate's `/Differences` array, measured on
# the machine the bounds were set on before the boundary existed, in process:
# an empty form drawn 40 times, 6.6 s; 60 wide CMaps in a 23 KB file, 602 MiB
# under allocation tracing; 5 million `/Differences` names in a 15 KB file,
# 630 MiB of resident memory.

FOUR_WIDE_FONTS = {f"F{n}": cmap(WIDE_RANGE) for n in range(2, 6)}


def child_peak(call):
    """(seconds, the parent's peak bytes) of `call`."""
    started = time.monotonic()
    peak = peak_bytes(call)
    return time.monotonic() - started, peak


def child_refused(path):
    with pytest.raises(pdf.PdfRefused) as refusal:
        pdf.read_pdf(path)
    return str(refusal.value)


@pytest.mark.parametrize("build", [
    lambda p: make_pdf(p, five_pages(), info=KETTLE),
    lambda p: make_pdf(p, five_pages(), compress=True,
                       outline=[Outline("Chapter One", 1), Outline("Chapter Two", 3)]),
    lambda p: make_pdf(p, [room("amber")] * 10 + [b""] * 15, xmp=XMP),
    lambda p: make_pdf(p, [["café ½"] + room("amber")], info={"Title": "Café"}),
])
def test_the_child_reads_what_the_process_reads(tmp_path, build):
    path = build(tmp_path / "b.pdf")
    assert pdf.read_pdf(path) == pdf.read_in_process(path)


@pytest.mark.parametrize("build", [
    lambda p: make_pdf(p, five_pages(), encrypt=True),
    lambda p: make_pdf(p, [b""] * 3),
    lambda p: p.write_bytes(b"this is not a PDF at all") and p,
])
def test_the_child_refuses_what_the_process_refuses(tmp_path, build):
    path = tmp_path / "b.pdf"
    path = build(path) or path
    assert child_refused(path) == refused(path)


def test_the_differences_array_is_bounded_by_the_child_s_memory(tmp_path, monkeypatch):
    """The merge gate's fixture: 5 million glyph names in a 15 KB file. In
    process it costs about 630 MiB and is read; the child is killed at the
    memory cap (lowered here to make the test quick), and the parent's own
    memory does not move."""
    monkeypatch.setattr(pdf, "MAX_CHILD_RSS_BYTES", 256 * 1024 * 1024)
    path = make_differences_pdf(tmp_path / "b.pdf", 5_000_000)
    assert path.stat().st_size < 20_000
    reason = []
    seconds, peak = child_peak(lambda: reason.append(child_refused(path)))
    assert reason == ["it needed more than 256 MiB of memory to read"]
    assert seconds < 10 and peak < 16 * 1024 * 1024, (seconds, peak)


def test_many_wide_fonts_are_bounded_by_the_child_s_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_CHILD_RSS_BYTES", 256 * 1024 * 1024)
    many = {f"G{n}": cmap(WIDE_RANGE) for n in range(60)}
    path = make_pdf(tmp_path / "b.pdf", [room("amber")], cmaps=many, compress=True)
    reason = []
    seconds, peak = child_peak(lambda: reason.append(child_refused(path)))
    assert reason == ["it needed more than 256 MiB of memory to read"]
    assert seconds < 10 and peak < 16 * 1024 * 1024, (seconds, peak)


def test_an_empty_form_drawn_many_times_is_bounded_by_the_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_SECONDS_PER_FILE", 1)
    page = show(room("amber")) + b" /X1 Do" * 40
    path = make_pdf(tmp_path / "b.pdf", [page], form=b"", cmaps=FOUR_WIDE_FONTS, compress=True)
    seconds, peak = child_peak(lambda: child_refused(path))
    assert child_refused(path) == "it took longer than 1 s to read"
    assert seconds < 3 and peak < 16 * 1024 * 1024, (seconds, peak)


def test_a_font_on_every_page_is_read_in_time(tmp_path):
    path = make_pdf(tmp_path / "b.pdf", [room("amber")] * 3, cmaps=FOUR_WIDE_FONTS,
                    compress=True)
    seconds, _ = child_peak(lambda: pdf.read_pdf(path))
    assert seconds < 10


def test_a_child_that_hangs_is_killed_at_the_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf, "MAX_SECONDS_PER_FILE", 0.5)
    monkeypatch.setattr(pdf, "child_command",
                        lambda path: [sys.executable, "-c", "import time; time.sleep(30)"])
    started = time.monotonic()
    assert child_refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "it took longer than 0.5 s to read")
    assert time.monotonic() - started < 3


def test_a_child_that_dies_says_nothing_of_its_traceback(tmp_path, monkeypatch, capsys,
                                                       caplog):
    monkeypatch.setattr(pdf, "child_command", lambda path: [
        sys.executable, "-c", f"print('the {CANARY} room'); raise RuntimeError('{CANARY}')"])
    with caplog.at_level(logging.DEBUG):
        reason = child_refused(make_pdf(tmp_path / "b.pdf", five_pages()))
    assert reason == "could not be read (the reader stopped with status 1)"
    out = capsys.readouterr()
    assert CANARY not in out.out + out.err + reason + "\n".join(
        r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("status, stdout, reason", [
    (0, b"not json", "could not be read (the reader's output was not readable)"),
    (0, b'{"title": 1}', "could not be read (the reader's output was not readable)"),
    (3, b'{"refused": "it has no pages"}', "it has no pages"),
    (4, b'{"error": "KeyError"}', "could not be read (KeyError)"),
    (-9, b"", "could not be read (the reader stopped with status -9)"),
    (5, b"", "it needed more than 1 GiB of memory to read"),
    (6, b"", "memory cannot be measured here, so the file is not read"),
])
def test_the_child_s_output_is_checked_before_it_is_believed(status, stdout, reason):
    with pytest.raises(pdf.PdfRefused) as refusal:
        pdf.parse_child_output(status, stdout)
    assert str(refusal.value) == reason


def child_code(body: str) -> list[str]:
    """A stand-in child: this package's watcher and `emit`, around `body`."""
    return [sys.executable, "-I", "-c",
            "import sys\nfrom ask_your_library.ingest import pdf\n"
            f"LIMIT = {pdf.MAX_CHILD_RSS_BYTES}\n" + body]


READ_DOC = ("raise SystemExit(pdf.emit(0, {'title': 'T', 'author': '', 'notes': [], "
            "'sections': [['Page 1', 'x']]}, LIMIT))")


def test_an_allocation_freed_between_two_samples_is_still_seen(tmp_path, monkeypatch):
    """The gate's case: 512 MiB allocated, touched and freed at once, under a
    cap of 128 MiB (the child's interpreter and this package alone are about
    21 MiB on macOS, more on Linux). Sampling resident memory missed it and
    accepted the result; the high-water mark keeps it, and the child is
    ended. The control child below, under the same cap, is read on both
    platforms."""
    monkeypatch.setattr(pdf, "MAX_CHILD_RSS_BYTES", 128 * 1024 * 1024)
    allocate = ("pdf.watch_memory(LIMIT)\nb = bytearray(512 * 1024 * 1024)\n"
                "b[::4096] = b'x' * len(b[::4096])\ndel b\n")
    monkeypatch.setattr(pdf, "child_command", lambda path: child_code(allocate + READ_DOC))
    path = make_pdf(tmp_path / "b.pdf", five_pages())
    assert child_refused(path) == "it needed more than 128 MiB of memory to read"
    # The same child without the allocation stays under the cap and is read.
    monkeypatch.setattr(pdf, "child_command",
                        lambda path: child_code("pdf.watch_memory(LIMIT)\n" + READ_DOC))
    assert pdf.read_pdf(path).title == "T"


def test_a_child_that_cannot_measure_its_memory_reads_nothing(tmp_path, monkeypatch):
    broken = ("import resource\n"
              "def fail(*args): raise OSError('no rusage')\n"
              "resource.getrusage = fail\npdf.watch_memory(LIMIT)\n" + READ_DOC)
    monkeypatch.setattr(pdf, "child_command", lambda path: child_code(broken))
    assert child_refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "memory cannot be measured here, so the file is not read")


def test_a_child_that_cannot_be_started_is_a_refusal_not_an_error(tmp_path, monkeypatch):
    """A sandbox that denies starting a process: one fixed line, not a
    traceback that stops the folder."""
    def denied(*args, **kwargs):
        raise PermissionError(13, "Operation not permitted")
    monkeypatch.setattr(pdf.subprocess, "Popen", denied)
    assert child_refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "memory cannot be measured here, so the file is not read")


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone_soon(pid: int) -> bool:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("child_end, reason", [
    ("time.sleep(30)", "it took longer than 1 s to read"),
    ("raise SystemExit(1)", "could not be read (the reader stopped with status 1)"),
])
def test_a_process_the_child_forked_goes_with_it(tmp_path, monkeypatch, child_end, reason):
    """The child never forks; one that did anyway, and left a grandchild
    sleeping, has its whole process group killed — on the deadline, and on an
    abnormal end. (In the second case the grandchild lets go of the output
    pipe, so the child's exit is seen at once rather than at the deadline.)"""
    monkeypatch.setattr(pdf, "MAX_SECONDS_PER_FILE", 1)
    pid_file = tmp_path / "grandchild.pid"
    body = ("import os, time\npid = os.fork()\nif pid == 0:\n    os.close(1)\n"
            "    time.sleep(30)\n    os._exit(0)\n"
            f"open({str(pid_file)!r}, 'w').write(str(pid))\n{child_end}\n")
    monkeypatch.setattr(pdf, "child_command", lambda path: child_code(body))
    assert child_refused(make_pdf(tmp_path / "b.pdf", five_pages())) == reason
    assert gone_soon(int(pid_file.read_text()))


def recorded_samples(monkeypatch):
    """Every resident-memory sample the parent takes, with the number of
    threads the parent had when it took it."""
    samples = []
    reader = pdf.resident_memory_reader

    def recording():
        read = reader()

        def sample(pid):
            value = read(pid)
            samples.append((pid, value, threading.active_count()))
            return value
        return sample
    monkeypatch.setattr(pdf, "resident_memory_reader", recording)
    return samples


def test_a_child_growing_inside_one_c_call_is_killed_from_outside(tmp_path, monkeypatch):
    """`bytearray(2 GiB)` zero-fills its memory in one C call that holds the
    child's interpreter lock, so the child's own watcher cannot run until it
    returns (at the previous design, the child reached 2,068 MiB under a
    256 MiB cap). The parent, a different process, samples it every 20 ms and
    kills it. The overshoot is what the machine faults in between two samples:
    measured here at 263 to 696 MiB of peak over ten runs, so the bound below
    is generous."""
    monkeypatch.setattr(pdf, "MAX_CHILD_RSS_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr(pdf, "child_command", lambda path: [
        sys.executable, "-I", "-c", "b = bytearray(2 * 1024 ** 3)\nimport time\ntime.sleep(30)"])
    samples = recorded_samples(monkeypatch)
    started = time.monotonic()
    assert child_refused(make_pdf(tmp_path / "b.pdf", five_pages())) == (
        "it needed more than 256 MiB of memory to read")
    assert time.monotonic() - started < 5
    child = [value for pid, value, _ in samples if pid != os.getpid() and value]
    assert child and child[-1] > 256 * 1024 * 1024
    assert child[-1] < 1024 * 1024 * 1024, child[-1]


def test_the_parent_reads_with_no_thread_and_no_process_but_the_child(tmp_path, monkeypatch):
    samples = recorded_samples(monkeypatch)
    started = []
    popen = subprocess.Popen

    def counted(*args, **kwargs):
        started.append(args[0])
        return popen(*args, **kwargs)
    monkeypatch.setattr(pdf.subprocess, "Popen", counted)
    threads = threading.active_count()
    pdf.read_pdf(make_pdf(tmp_path / "b.pdf", five_pages()))
    assert len(started) == 1 and started[0][:4] == [sys.executable, "-I", "-m",
                                                    "ask_your_library.ingest.pdf"]
    assert samples and {count for _, _, count in samples} == {threads}


def test_a_platform_where_memory_cannot_be_read_reads_nothing(tmp_path, monkeypatch):
    path = make_pdf(tmp_path / "b.pdf", five_pages())
    monkeypatch.setattr(pdf, "resident_memory_reader", lambda: None)
    assert child_refused(path) == "memory cannot be measured here, so the file is not read"
    # Readable for this process, unreadable for the running child: the same.
    monkeypatch.setattr(pdf, "resident_memory_reader",
                        lambda: lambda pid: 1 if pid == os.getpid() else None)
    monkeypatch.setattr(pdf, "child_command",
                        lambda path: [sys.executable, "-I", "-c", "import time; time.sleep(5)"])
    assert child_refused(path) == "memory cannot be measured here, so the file is not read"


LINUX_STATUS = "Name:\tpython3\nVmPeak:\t  900000 kB\nVmHWM:\t   30000 kB\nVmRSS:\t   29000 kB\n"


def test_the_linux_high_water_mark_is_this_image_s_own(monkeypatch):
    """On Linux `ru_maxrss` survives `execve`: a child of a parent that once
    held 400 MiB reads 400 MiB at its first instruction. The watcher reads
    `VmHWM` instead, in kB."""
    import resource
    monkeypatch.setattr(pdf.sys, "platform", "linux")
    monkeypatch.setattr(pdf.Path, "read_text", lambda self, *a, **k: LINUX_STATUS)
    monkeypatch.setattr(resource, "getrusage",
                        lambda who: type("R", (), {"ru_maxrss": 400 * 1024})())
    assert pdf.peak_resident_bytes() == 30000 * 1024
    assert not pdf.memory_over(64 * 1024 * 1024)
    with pytest.raises(ValueError):
        pdf.linux_peak_bytes("Name:\tpython3\n")


def test_the_macos_high_water_mark_is_in_bytes(monkeypatch):
    import resource
    monkeypatch.setattr(pdf.sys, "platform", "darwin")
    monkeypatch.setattr(resource, "getrusage",
                        lambda who: type("R", (), {"ru_maxrss": 30 * 1024 * 1024})())
    assert pdf.peak_resident_bytes() == 30 * 1024 * 1024


def test_every_field_of_the_library_configuration_is_set():
    """A field a later version adds fails here, rather than being left at a
    default nobody chose."""
    assert set(pdf.CONFIGURATION) == {f.name for f in dataclasses.fields(pypdf.Configuration)}


def test_the_child_cannot_be_shadowed_from_the_working_directory():
    """`-I`: a `json.py` in the folder `ayl add` runs from is not imported."""
    assert pdf.child_command(Path("b.pdf"))[1] == "-I"


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
                or (event == "os.mkdir" and path == os.path.realpath(db.parent))
                # Each PDF is read by a child process whose stdin and stderr
                # are the null device: opened for writing, and nothing lands.
                or (event == "open" and path == os.path.realpath(os.devnull)))

    stray = [(event, path) for event, path in targets if not allowed(event, path)]
    assert stray == [], stray
    assert not any(p.startswith(os.path.realpath(REPO) + os.sep) for _, p in targets)
    # Four PDFs, four children, each with its stderr discarded.
    assert sum(1 for event, p in targets if p == os.path.realpath(os.devnull)) == 4
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
