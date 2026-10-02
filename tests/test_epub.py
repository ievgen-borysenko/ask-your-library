"""`ayl add` reads `.epub` (#34): structure, bounds, refusals, and the private book.

Every EPUB here is built in code into tmp_path with `zipfile`: no binary
fixture is committed and no real book is read. The text of the test books is
invented, low-entropy and plainly synthetic. No network: the embedder is faked
as in test_add_folder.py, the index is a tmp_path LanceDB.
"""
import logging
import os
import sys
import threading
import time
import zipfile

import lancedb
import pytest

from ask_your_library import ayl, library
from ask_your_library.ingest import add_folder, epub
from ask_your_library.ingest.chapters import FRONT_MATTER_SECTION, FULL_TEXT_SECTION
from ask_your_library.ingest.lock import lock_path
from ask_your_library.preflight import PreflightResult
from conftest import REPO
from test_add_folder import PARA, fake_embedder, write  # noqa: F401

# --- building an EPUB ----------------------------------------------------------

ROOM = "The {0} room has one chair and one lamp. The {0} room is quiet at noon. "


def body(word: str, times: int = 3) -> str:
    return "<p>" + ROOM.format(word) * times + "</p>"


def xhtml(inner: str, head: str = "<title>doc</title>", prolog: str = "") -> str:
    return (prolog + '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops">'
            f"<head>{head}</head><body>{inner}</body></html>")


class Doc:
    """One spine item: its file, its text, and how the navigation names it."""

    def __init__(self, name, inner, label=None, linear=True, children=(), raw=None,
                 media="application/xhtml+xml", in_spine=True):
        self.name, self.inner, self.label, self.linear = name, inner, label, linear
        self.children, self.raw, self.media, self.in_spine = children, raw, media, in_spine

    @property
    def id(self):
        return "d-" + self.name.replace("/", "-").replace(".", "-").replace("#", "-")


def nav_list(entries) -> str:
    items = []
    for href, label, children in entries:
        nested = nav_list(children) if children else ""
        items.append(f'<li><a href="{href}">{label}</a>{nested}</li>')
    return "<ol>" + "".join(items) + "</ol>"


def nav_tree(docs):
    """(href, label, children) for the docs that have a label; a child given as
    (href, label) points wherever it says (a fragment of a document, say)."""
    return [(f"text/{d.name}", d.label, list((h, lab, ()) for h, lab in d.children))
            for d in docs if d.label]


def ncx_points(entries) -> str:
    out = []
    for n, (href, label, children) in enumerate(entries):
        out.append(f'<navPoint id="p{n}-{len(href)}"><navLabel><text>{label}</text></navLabel>'
                   f'<content src="{href}"/>{ncx_points(children)}</navPoint>')
    return "".join(out)


def make_epub(path, docs, *, title="The Copper Kettle", creators=(("Ada Quill", None),),
              version=3, nav=True, ncx=False, encryption=None, extra=(), opf=None,
              container=None, spine_toc=True):
    """A minimal valid EPUB 3 (nav document) or EPUB 2 (NCX) at `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = []
    if title is not None:
        meta.append(f"<dc:title>{title}</dc:title>")
    for n, (name, role) in enumerate(creators):
        if version == 2:
            attr = f' opf:role="{role}"' if role else ""
            meta.append(f"<dc:creator{attr}>{name}</dc:creator>")
        else:
            meta.append(f'<dc:creator id="cr{n}">{name}</dc:creator>')
            if role:
                meta.append(f'<meta refines="#cr{n}" property="role" '
                            f'scheme="marc:relators">{role}</meta>')
    manifest = [f'<item id="{d.id}" href="text/{d.name}" media-type="{d.media}"/>'
                for d in docs]
    manifest += ['<item id="css" href="style.css" media-type="text/css"/>',
                 '<item id="img" href="cover.png" media-type="image/png"/>']
    tree = nav_tree(docs)
    if nav:
        manifest.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
                        'properties="nav"/>')
    if ncx:
        manifest.append('<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>')
    spine_attr = ' toc="ncx"' if ncx and spine_toc else ""
    nonlinear = ' linear="no"'
    spine = [f'<itemref idref="{d.id}"{"" if d.linear else nonlinear}/>'
             for d in docs if d.in_spine]
    package = opf or (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<package xmlns="http://www.idpf.org/2007/opf" version="{version}.0" '
        'xmlns:opf="http://www.idpf.org/2007/opf" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        '<dc:identifier id="uid">urn:uuid:00000000-0000-0000-0000-000000000000</dc:identifier>'
        + "".join(meta) + "</metadata>"
        f"<manifest>{''.join(manifest)}</manifest>"
        f"<spine{spine_attr}>{''.join(spine)}</spine></package>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
        zf.writestr("META-INF/container.xml", container or (
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>'))
        zf.writestr("OEBPS/content.opf", package)
        if nav:
            zf.writestr("OEBPS/nav.xhtml", xhtml(
                '<nav epub:type="landmarks"><ol><li><a href="text/x.xhtml">Start</a></li>'
                '</ol></nav><nav epub:type="toc" id="toc"><h1>Contents</h1>'
                + nav_list(tree) + "</nav>"))
        if ncx:
            zf.writestr("OEBPS/toc.ncx", (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
                f"<head/><docTitle><text>{title}</text></docTitle>"
                f"<navMap>{ncx_points(tree)}</navMap></ncx>"))
        zf.writestr("OEBPS/style.css", "p { color: black }")
        zf.writestr("OEBPS/cover.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
        for d in docs:
            zf.writestr(f"OEBPS/text/{d.name}", d.raw if d.raw is not None else xhtml(d.inner))
        if encryption is not None:
            zf.writestr("META-INF/encryption.xml", encryption)
        for name, data in extra:
            zf.writestr(name, data)
    return path


def three_chapters():
    return [Doc("c1.xhtml", "<h1>One</h1>" + body("amber"), "Chapter One"),
            Doc("c2.xhtml", "<h1>Two</h1>" + body("birch"), "Chapter Two"),
            Doc("c3.xhtml", "<h1>Three</h1>" + body("cedar"), "Chapter Three")]


def titles(book):
    return [t for t, _ in book.sections]


# --- structure -----------------------------------------------------------------

def test_epub3_chapters_come_from_the_spine_titled_by_the_nav(tmp_path):
    book = epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters()))
    assert (book.title, book.author) == ("The Copper Kettle", "Ada Quill")
    assert titles(book) == ["Chapter One", "Chapter Two", "Chapter Three"]
    assert "amber room" in book.sections[0][1] and "cedar" not in book.sections[0][1]
    assert book.sections[2][1].startswith("Three\n\nThe cedar room")


def test_the_spine_decides_the_order_not_the_nav(tmp_path):
    docs = three_chapters()
    path = make_epub(tmp_path / "b.epub", docs)
    # A package whose spine lists the files in another order than the manifest.
    with zipfile.ZipFile(path) as zf:
        opf = zf.read("OEBPS/content.opf").decode()
    reordered = opf.replace('<itemref idref="d-c1-xhtml"/><itemref idref="d-c2-xhtml"/>',
                            '<itemref idref="d-c2-xhtml"/><itemref idref="d-c1-xhtml"/>')
    assert reordered != opf
    book = epub.read_epub(make_epub(tmp_path / "r.epub", docs, opf=reordered))
    assert titles(book) == ["Chapter Two", "Chapter One", "Chapter Three"]


def test_epub2_chapters_are_titled_by_the_ncx(tmp_path):
    book = epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(), version=2,
                                    nav=False, ncx=True,
                                    creators=(("Ada Quill", "aut"), ("Bo Reed", "trl"))))
    assert titles(book) == ["Chapter One", "Chapter Two", "Chapter Three"]
    assert book.author == "Ada Quill"                    # the translator is not the author


def test_an_ncx_found_by_media_type_when_the_spine_does_not_name_it(tmp_path):
    book = epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(), version=2,
                                    nav=False, ncx=True, spine_toc=False))
    assert titles(book) == ["Chapter One", "Chapter Two", "Chapter Three"]


def test_without_navigation_every_spine_item_is_a_numbered_section(tmp_path):
    docs = [Doc(d.name, d.inner) for d in three_chapters()]          # no labels
    book = epub.read_epub(make_epub(tmp_path / "b.epub", docs, nav=False))
    assert titles(book) == ["Section 1", "Section 2", "Section 3"]
    single = epub.read_epub(make_epub(tmp_path / "s.epub", docs[:1], nav=False))
    assert titles(single) == [FULL_TEXT_SECTION]


def test_a_nav_that_names_no_spine_item_counts_as_no_nav(tmp_path):
    docs = [Doc("c1.xhtml", body("amber")), Doc("c2.xhtml", body("birch")),
            Doc("elsewhere.xhtml", "", "Lost Label", in_spine=False)]
    book = epub.read_epub(make_epub(tmp_path / "b.epub", docs))
    assert titles(book) == ["Section 1", "Section 2"]


def test_nested_nav_entries_flatten_parent_first(tmp_path):
    docs = [Doc("p1.xhtml", "<h1>Part One</h1>", "Part One",
                children=[("text/c1.xhtml", "Chapter 1"),
                          ("text/c1.xhtml#later", "Chapter 1, later scene"),
                          ("text/c2.xhtml", "Chapter 2")]),
            Doc("c1.xhtml", body("amber") + '<p id="later">' + ROOM.format("aspen") + "</p>"),
            Doc("c2.xhtml", body("birch"))]
    book = epub.read_epub(make_epub(tmp_path / "b.epub", docs))
    # One spine item is one section, named by the first entry that points at
    # it: the fragment entry does not split chapter 1 in two.
    assert titles(book) == ["Part One", "Chapter 1", "Chapter 2"]
    assert "aspen room" in book.sections[1][1]


def test_a_spine_item_the_nav_does_not_name_continues_the_section_before_it(tmp_path):
    docs = [Doc("cover.xhtml", "<p>Copper Kettle press, first printing.</p>"),
            Doc("c1.xhtml", body("amber"), "Chapter One"),
            Doc("c1b.xhtml", body("alder")),                 # chapter one, second file
            Doc("c2.xhtml", body("birch"), "Chapter Two")]
    book = epub.read_epub(make_epub(tmp_path / "b.epub", docs))
    assert titles(book) == [FRONT_MATTER_SECTION, "Chapter One", "Chapter Two"]
    assert "first printing" in book.sections[0][1]
    assert "amber room" in book.sections[1][1] and "alder room" in book.sections[1][1]


def test_non_linear_items_follow_the_reading_order(tmp_path):
    docs = [Doc("c1.xhtml", body("amber"), "Chapter One"),
            Doc("notes.xhtml", body("ivory", 1), "Notes", linear=False),
            Doc("c2.xhtml", body("birch"), "Chapter Two")]
    book = epub.read_epub(make_epub(tmp_path / "b.epub", docs))
    assert titles(book) == ["Chapter One", "Chapter Two", "Notes"]
    assert "ivory room" in book.sections[2][1]


def test_scripts_styles_images_and_svg_are_not_text(tmp_path):
    inner = ("<style>p { margin: 0 }</style><script>var hidden = 'script text';</script>"
             '<p>The <b>amber</b>   room\n has <img src="x.png" alt="picture words"/> a lamp.</p>'
             '<svg xmlns="http://www.w3.org/2000/svg"><text>svg words</text></svg>'
             "<p>Second\tparagraph.<br/>After a break.</p>")
    book = epub.read_epub(make_epub(tmp_path / "b.epub", [Doc("c1.xhtml", inner, "One")]))
    text = book.sections[0][1]
    assert text == "The amber room has a lamp.\n\nSecond paragraph.\n\nAfter a break."


def test_control_and_invisible_characters_are_stripped(tmp_path):
    raw = xhtml("<p>The amber\x1b[2J room\u200b is \u202equiet.</p>")
    book = epub.read_epub(make_epub(
        tmp_path / "b.epub", [Doc("c1.xhtml", "", "Chapter\u200b One\x07", raw=raw)]))
    assert book.sections == [("Chapter One", "The amber[2J room is quiet.")]


def test_html_named_entities_in_content_are_read(tmp_path):
    raw = xhtml("<p>Tea&nbsp;&amp;&nbsp;toast in the amber room.</p>")
    book = epub.read_epub(make_epub(tmp_path / "b.epub", [Doc("c1.xhtml", "", "One", raw=raw)]))
    assert book.sections[0][1] == "Tea & toast in the amber room."      # no-break spaces too


def test_a_non_utf8_document_declared_in_its_prolog_is_decoded(tmp_path):
    raw = xhtml("<p>The caf\u00e9 room is quiet.</p>",
                prolog='<?xml version="1.0" encoding="windows-1252"?>').encode("cp1252")
    book = epub.read_epub(make_epub(tmp_path / "b.epub", [Doc("c1.xhtml", "", "One", raw=raw)]))
    assert book.sections[0][1] == "The caf\u00e9 room is quiet."


def test_a_document_that_does_not_decode_as_declared_is_refused(tmp_path):
    raw = b'<?xml version="1.0" encoding="utf-8"?><html><body><p>caf\xe9</p></body></html>'
    with pytest.raises(epub.EpubRefused, match="encoding it declares"):
        epub.read_epub(make_epub(tmp_path / "b.epub", [Doc("c1.xhtml", "", "One", raw=raw)]))


@pytest.mark.parametrize("codec", ["unicode_escape", "x-no-such-charset"])
def test_a_declared_encoding_that_is_not_a_charset_is_refused(tmp_path, codec):
    raw = f'<?xml version="1.0" encoding="{codec}"?><html><body><p>x</p></body></html>'
    with pytest.raises(epub.EpubRefused, match="encoding it declares"):
        epub.read_epub(make_epub(tmp_path / "b.epub", [Doc("c1.xhtml", "", "One", raw=raw)]))


def test_a_utf16_document_with_a_bom_is_decoded(tmp_path):
    raw = "\ufeff" + xhtml("<p>The amber room.</p>",
                           prolog='<?xml version="1.0" encoding="UTF-16"?>')
    book = epub.read_epub(make_epub(tmp_path / "b.epub",
                                    [Doc("c1.xhtml", "", "One", raw=raw.encode("utf-16-le"))]))
    assert book.sections[0][1] == "The amber room."


# --- metadata --------------------------------------------------------------------

def test_creators_without_a_role_are_all_authors(tmp_path):
    book = epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(),
                                    creators=(("Ada Quill", None), ("Bo Reed", None),
                                              ("Cy Ink", "ill"))))
    assert book.author == "Ada Quill, Bo Reed"


def test_epub3_roles_come_from_refining_meta(tmp_path):
    book = epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(),
                                    creators=(("Bo Reed", "trl"), ("Ada Quill", "aut"))))
    assert book.author == "Ada Quill"


def test_missing_title_falls_back_to_the_file_name(tmp_path):
    folder = tmp_path / "books"
    make_epub(folder / "The Quiet Mill - Bo Reed.epub", three_chapters(), title=None,
              creators=())
    make_epub(folder / "Plain.epub", three_chapters(), title=None, creators=())
    make_epub(folder / "Titled.epub", three_chapters(), title="The Tin Bell", creators=())
    books = {b.path.name: b.book for b in add_folder.read_folder(folder)}
    assert books == {"The Quiet Mill - Bo Reed.epub": "The Quiet Mill — Bo Reed",
                     "Plain.epub": "Plain — Unknown",
                     "Titled.epub": "The Tin Bell — Unknown"}


# --- refusals ----------------------------------------------------------------------

ENCRYPTION = ('<?xml version="1.0"?><encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:'
              'container" xmlns:enc="http://www.w3.org/2001/04/xmlenc#">'
              '<enc:EncryptedData><enc:EncryptionMethod Algorithm="{algo}"/>'
              '<enc:CipherData><enc:CipherReference URI="{uri}"/></enc:CipherData>'
              "</enc:EncryptedData></encryption>")


def test_drm_protected_content_is_refused(tmp_path):
    enc = ENCRYPTION.format(algo="http://www.w3.org/2001/04/xmlenc#aes128-cbc",
                            uri="OEBPS/text/c1.xhtml")
    with pytest.raises(epub.EpubRefused, match="DRM-protected"):
        epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(), encryption=enc))


def test_font_obfuscation_alone_is_not_drm(tmp_path):
    for n, algo in enumerate(sorted(epub.FONT_OBFUSCATION)):
        enc = ENCRYPTION.format(algo=algo, uri="OEBPS/fonts/serif.otf")
        book = epub.read_epub(make_epub(tmp_path / f"b{n}.epub", three_chapters(),
                                        encryption=enc,
                                        extra=[("OEBPS/fonts/serif.otf", b"\x00" * 64)]))
        assert titles(book) == ["Chapter One", "Chapter Two", "Chapter Three"]


@pytest.mark.parametrize("name", ["../escape.txt", "OEBPS/../../escape.txt", "/abs.txt",
                                  "C:/abs.txt", "OEBPS\\..\\escape.txt"])
def test_a_member_path_that_could_leave_the_archive_refuses_the_file(tmp_path, name):
    with pytest.raises(epub.EpubRefused, match="climbs out"):
        epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(), extra=[(name, "x")]))


def test_a_reference_out_of_the_archive_root_is_never_followed(tmp_path):
    docs = three_chapters()
    path = make_epub(tmp_path / "b.epub", docs)
    with zipfile.ZipFile(path) as zf:
        opf = zf.read("OEBPS/content.opf").decode()
    opf = opf.replace('href="text/c3.xhtml"', 'href="../../../outside.xhtml"')
    book = epub.read_epub(make_epub(tmp_path / "o.epub", docs, opf=opf))
    assert titles(book) == ["Chapter One", "Chapter Two"]


def test_an_oversized_member_is_refused_before_it_is_inflated(tmp_path, monkeypatch):
    monkeypatch.setattr(epub, "MAX_MEMBER_BYTES", 4096)
    with pytest.raises(epub.EpubRefused, match="larger than"):
        epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(),
                                 extra=[("OEBPS/big.bin", b"\x00" * 5000)]))


def test_an_archive_too_large_in_total_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(epub, "MAX_TOTAL_BYTES", 6000)
    with pytest.raises(epub.EpubRefused, match="archive is larger than"):
        epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters(),
                                 extra=[("OEBPS/a.bin", b"\x00" * 4000)]))


def test_a_member_whose_header_understates_its_size_is_cut_off(tmp_path, monkeypatch):
    """The declared size is a claim of the archive; the read is bounded on its own."""
    path = make_epub(tmp_path / "b.epub", three_chapters())
    archive = epub.Archive(zipfile.ZipFile(path))
    monkeypatch.setattr(epub, "MAX_MEMBER_BYTES", 16)
    with pytest.raises(epub.EpubRefused, match="inflates past"):
        archive.read("OEBPS/content.opf")


def test_too_many_members_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(epub, "MAX_MEMBERS", 8)
    with pytest.raises(epub.EpubRefused, match="too many files"):
        epub.read_epub(make_epub(tmp_path / "b.epub", three_chapters()))


def _level(i: int) -> str:
    inner = (f"&lol{i - 1};" if i > 1 else "&lol;") * 10
    return f'<!ENTITY lol{i} "{inner}">'


BOMB = ('<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        + "".join(_level(i) for i in range(1, 10)) + "]>")


def test_an_entity_bomb_in_the_package_is_refused_before_parsing(tmp_path):
    docs = three_chapters()
    path = make_epub(tmp_path / "b.epub", docs)
    with zipfile.ZipFile(path) as zf:
        opf = zf.read("OEBPS/content.opf").decode()
    bombed = BOMB + opf.split("?>", 1)[1].replace(
        "<dc:title>The Copper Kettle</dc:title>", "<dc:title>&lol9;</dc:title>")
    started = time.monotonic()
    with pytest.raises(epub.EpubRefused, match="declares XML entities"):
        epub.read_epub(make_epub(tmp_path / "bomb.epub", docs, opf=bombed))
    assert time.monotonic() - started < 2


def test_an_entity_declaration_in_a_content_document_is_refused(tmp_path):
    raw = BOMB.replace("lolz", "html") + "<html><body><p>&lol9;</p></body></html>"
    with pytest.raises(epub.EpubRefused, match="declares XML entities"):
        epub.read_epub(make_epub(tmp_path / "b.epub", [Doc("c1.xhtml", "", "One", raw=raw)]))


@pytest.mark.parametrize("damage", ["not a zip", "no container", "no spine", "bad xml",
                                    "missing member"])
def test_a_malformed_file_is_refused(tmp_path, damage):
    docs = three_chapters()
    path = tmp_path / "b.epub"
    if damage == "not a zip":
        path.write_bytes(b"PK\x03\x04 this is not an archive")
    elif damage == "no container":
        make_epub(path, docs, container="<container/>")
    elif damage == "no spine":
        make_epub(path, docs, opf='<package xmlns="http://www.idpf.org/2007/opf"><metadata/>'
                                  "<manifest/></package>")
    elif damage == "bad xml":
        make_epub(path, docs, opf="<package><unclosed></package>")
    else:
        with zipfile.ZipFile(make_epub(tmp_path / "src.epub", docs)) as zf, \
                zipfile.ZipFile(path, "w") as out:
            for info in zf.infolist():
                if info.filename != "OEBPS/text/c2.xhtml":
                    out.writestr(info, zf.read(info))
    with pytest.raises(epub.EpubRefused, match="malformed"):
        epub.read_epub(path)


def test_a_spine_of_images_only_is_refused(tmp_path):
    docs = [Doc("pic.png", "", "Picture", media="image/png", raw=b"\x89PNG")]
    with pytest.raises(epub.EpubRefused, match="no readable spine"):
        epub.read_epub(make_epub(tmp_path / "b.epub", docs))


def test_an_empty_book_is_refused(tmp_path):
    docs = [Doc("c1.xhtml", "<p>  </p>", "One"), Doc("c2.xhtml", '<img src="x.png"/>', "Two")]
    with pytest.raises(epub.EpubRefused, match="no text"):
        epub.read_epub(make_epub(tmp_path / "b.epub", docs))


# --- in a folder -------------------------------------------------------------------

def mixed_folder(tmp_path):
    folder = tmp_path / "books"
    write(folder, "Sea Notes - B. Mate.txt", PARA)
    write(folder, "The Green Ledger - A. Keeper.md", "## One\n\n" + PARA)
    make_epub(folder / "kettle.epub", three_chapters())
    make_epub(folder / "nested" / "Locked.epub", three_chapters(),
              encryption=ENCRYPTION.format(algo="http://www.w3.org/2001/04/xmlenc#aes256-cbc",
                                           uri="OEBPS/text/c1.xhtml"))
    return folder


def test_a_refused_epub_is_left_out_and_named_and_the_rest_is_read(tmp_path, caplog):
    folder = mixed_folder(tmp_path)
    with caplog.at_level("WARNING"):
        books = add_folder.read_folder(folder)
    assert sorted(b.book for b in books) == ["Sea Notes — B. Mate",
                                             "The Copper Kettle — Ada Quill",
                                             "The Green Ledger — A. Keeper"]
    refused = [r.getMessage() for r in caplog.records if "Locked.epub" in r.getMessage()]
    assert refused == [f"{os.path.join('nested', 'Locked.epub')}: DRM-protected (its content "
                       f"is encrypted; nothing was decrypted), skipped"]


def test_a_folder_with_a_refused_epub_still_adds_the_others_and_exits_0(tmp_path,
                                                                     fake_embedder, capsys):
    folder = mixed_folder(tmp_path)
    assert add_folder.main([str(folder), "--db", str(tmp_path / "db")]) == 0
    assert "added 3 books" in capsys.readouterr().out
    rows = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").to_arrow().to_pylist()
    kettle = {r["section"] for r in rows if r["book"] == "The Copper Kettle — Ada Quill"}
    assert kettle == {"Chapter One", "Chapter Two", "Chapter Three"}
    assert {r["source"] for r in rows if r["book"].startswith("The Copper")} == {
        "local:kettle.epub"}


def test_a_folder_of_only_refused_epubs_is_one_error_line(tmp_path, fake_embedder, capsys):
    folder = tmp_path / "books"
    make_epub(folder / "Locked.epub", three_chapters(),
              encryption=ENCRYPTION.format(algo="http://www.w3.org/2001/04/xmlenc#aes256-cbc",
                                           uri="OEBPS/text/c1.xhtml"))
    assert add_folder.main([str(folder), "--db", str(tmp_path / "db")]) == 1
    assert "no readable text" in capsys.readouterr().err
    assert not (tmp_path / "db").exists()


def test_re_adding_an_epub_with_corrected_metadata_updates_the_same_book(tmp_path,
                                                                        fake_embedder):
    folder = tmp_path / "books"
    make_epub(folder / "kettle.epub", three_chapters(), creators=(("Ada Quil", None),))
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    make_epub(folder / "kettle.epub", three_chapters(), creators=(("Ada Quill", None),))
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    rows = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").to_arrow().to_pylist()
    assert {r["book"] for r in rows} == {"The Copper Kettle — Ada Quill"}
    assert len({r["book_id"] for r in rows}) == 1


def test_ayl_add_then_ayl_books_lists_the_epub(tmp_path, fake_embedder, monkeypatch, capsys):
    folder = tmp_path / "books"
    make_epub(folder / "kettle.epub", three_chapters())
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


# --- the private book ----------------------------------------------------------------
# A book from the reader's own folder is the one thing in this project that may
# never leave the index it was added to. Two tests: where the run writes, and
# what it says.

CANARY = "zqzqxvxv"
SECRET_ROOM = f"The {CANARY} room keeps its own counsel. "

_armed = threading.Event()
_writes: list[tuple[str, str]] = []
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _hook(event, args):
    if not _armed.is_set():
        return
    if event == "open":
        path, mode, flags = args
        writing = (any(c in str(mode or "") for c in "wax+")
                   or (mode is None and isinstance(flags, int) and flags & _WRITE_FLAGS))
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            _writes.append((event, os.fsdecode(path)))
    elif event in ("os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir",
                   "os.truncate", "shutil.rmtree", "shutil.copyfile"):
        _writes.extend((event, os.fsdecode(v)) for v in args
                       if isinstance(v, (str, bytes, os.PathLike)))


sys.addaudithook(_hook)


def private_folder(tmp_path):
    folder = tmp_path / "reader" / "my books"
    docs = [Doc("c1.xhtml", "<p>" + SECRET_ROOM * 4 + "</p>", "Chapter One"),
            Doc("c2.xhtml", "<p>" + SECRET_ROOM * 4 + "</p>", "Chapter Two")]
    make_epub(folder / "private.epub", docs, title="A Private Book",
              creators=(("R. Reader", None),))
    # Refused ones too: a refusal must name the file, not quote it.
    make_epub(folder / "damaged.epub", docs, opf="<package>" + SECRET_ROOM + "<unclosed>")
    make_epub(folder / "Locked.epub", docs,
              encryption=ENCRYPTION.format(algo="http://www.w3.org/2001/04/xmlenc#aes256-cbc",
                                           uri="OEBPS/text/c1.xhtml"))
    return folder


def test_a_private_epub_is_written_only_to_the_index_named_for_the_run(tmp_path, monkeypatch,
                                                                      fake_embedder):
    """Every write the run attempts from Python — the index's Python-side files,
    the ingest lock, the ledger — is watched by an audit hook, and must land in
    the index this run was given (or the lock file beside it) and nowhere in
    the repository or the reader's folder. LanceDB's own native writes are not
    visible to the hook; they go to the path it is handed, which is the same
    index, and the last assertion reads them back from there."""
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
                # the lock's `mkdir(parents=True, exist_ok=True)` of the
                # directory the index sits in, which already exists
                or (event == "os.mkdir" and path == os.path.realpath(db.parent)))

    stray = [(event, path) for event, path in targets if not allowed(event, path)]
    assert stray == [], stray
    assert not any(p.startswith(os.path.realpath(REPO) + os.sep) for _, p in targets)
    rows = lancedb.connect(db).open_table("transcripts_ollama").to_arrow().to_pylist()
    assert {r["book"] for r in rows} == {"A Private Book — R. Reader"}
    assert sorted(p.name for p in folder.iterdir()) == ["Locked.epub", "damaged.epub",
                                                        "private.epub"]


def test_nothing_of_a_private_epub_reaches_the_output_or_the_log(tmp_path, monkeypatch,
                                                                fake_embedder, capsys,
                                                                caplog):
    folder = private_folder(tmp_path)
    monkeypatch.setattr(add_folder, "DB_PATH", tmp_path / "run-index")
    with caplog.at_level(logging.INFO):
        assert add_folder.main([str(folder)]) == 0
        assert add_folder.main([str(folder), "--dry-run"]) == 0
    out = capsys.readouterr()
    records = [r.getMessage() for r in caplog.records]
    everything = out.out + out.err + "\n".join(records)
    assert CANARY not in everything
    assert any(CANARY in text for text in fake_embedder.seen)   # it WAS read and embedded
    refusals = [m for m in records if m.startswith(("damaged.epub", "Locked.epub"))]
    assert len(refusals) == 4, records                          # two files, two runs
    for line in refusals:
        assert str(folder) not in line and str(tmp_path) not in line
