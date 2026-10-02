"""One `.epub` -> the title, the author and the chapters `ayl add` indexes.

An EPUB is a zip archive of XHTML documents with an XML package document that
says what order they are read in (the spine), what the book is called (the
metadata) and, through a navigation document, what each part is called. This
module reads exactly that and nothing else, and hands `add_folder` the same
three things a text book gives it: a title and author (or none, for the
file-name rule to fill in), and `[(section title, text)]`.

Chapters come from structure, never from heuristics over the text:

- one spine item (an XHTML/HTML content document) is the unit; the spine is
  read in order, linear items first and then any marked `linear="no"`
  (footnotes, answer keys: supplementary text with no place of its own in the
  reading order, kept rather than dropped);
- a spine item opens a section when the navigation document points at it (EPUB
  3 `nav` with `epub:type="toc"`, else the EPUB 2 `toc.ncx`), titled with the
  first entry that does, in document order, so a parent entry names a file
  before its nested children do;
- a spine item the navigation does not name continues the section before it
  (a chapter split over two files), and one before the first named item opens
  `Front matter` (cover, title page, copyright), the same rule as text before
  the first heading of a `.txt`; an unnamed non-linear item is a section of its
  own, `Notes`, since it continues nothing;
- the navigation document itself, when the spine lists it, is not read as
  text: it is the contents page, and its entries are already the titles;
- with no usable navigation at all, every spine item with text is a section of
  its own, `Section 1`, `Section 2`, … in reading order (`Full text` when there
  is only one).

The title is `dc:title` and the author `dc:creator` (the creators with the
author role, or with no role, joined; every creator when none has one). With no
`dc:title`, the caller falls back to the file-name rule of a text book.

An EPUB is untrusted input. What is bounded, and how:

- the archive is read member by member, by name, into memory; nothing is ever
  extracted to disk, and a member name that is absolute or contains `..` makes
  the whole file refused;
- the archive's directory is checked before `zipfile` reads it: a ZIP64
  archive is refused outright (an EPUB never needs one), and then the entry
  count the end record declares, whether the file is large enough to hold
  that many entries, the directory's size, and the entries the directory
  actually holds, counted without allocating anything per entry — so a
  directory of a million entries is refused before a single `ZipInfo` exists;
- member count, the declared size of each member and of all of them, and the
  bytes actually read from each member are capped (`MAX_MEMBERS`,
  `MAX_MEMBER_BYTES`, `MAX_TOTAL_BYTES`): a zip bomb is refused before it is
  inflated, and a member whose header lies about its size is cut off at the cap
  and refused;
- a reference from the package or the navigation that resolves outside the
  archive's root is ignored, and one to a member that is not there is refused;
- XML (`container.xml`, the package, the NCX, `encryption.xml`) is parsed by
  `xml.etree.ElementTree`, which fetches no external entity; any of those that
  declares an entity (the only way to a "billion laughs") is refused before it
  is parsed. Content documents are read by `html.parser`, which never expands
  a declared entity, so a DTD there is dropped rather than refused;
- every document is decoded strictly, as the encoding it declares, and must
  come out as text that UTF-8 can carry: UTF-7 and the escape codecs are not
  accepted as a book's encoding;
- only spine items with an XHTML/HTML media type are read; scripts, styles,
  SVG and images are ignored; text is taken out of the markup with
  `html.parser` (not a regular expression), its whitespace normalised and its
  control and invisible characters stripped (`sanitize.strip_control_chars`);
  the extraction is linear in the size of the document, however the markup
  nests or fails to close;
- a file that is DRM-protected — an `encryption.xml` entry with any algorithm
  other than the IDPF or Adobe font obfuscation — is refused, and nothing is
  decrypted or worked around.

Every refusal is an `EpubRefused` carrying a reason written here: it names no
member and quotes no text of the book, so the caller's one line about the file
says which file and why, and nothing of what is in it.
"""
import codecs
import posixpath
import re
import struct
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

from ..sanitize import strip_control_chars
from .chapters import FRONT_MATTER_SECTION, FULL_TEXT_SECTION, unique_titles

# --- bounds -------------------------------------------------------------------
# A long novel is a few hundred members and well under 10 MiB of text; an
# illustrated one is mostly images, which are counted against the totals here
# but never read.
MAX_MEMBERS = 10_000
MAX_MEMBER_BYTES = 64 * 1024 * 1024          # declared and actually read, per member
MAX_TOTAL_BYTES = 512 * 1024 * 1024          # declared, all members together
# The central directory is read whole by `zipfile`; 16 MiB is over 1.6 KiB an
# entry at MAX_MEMBERS, several times what a real EPUB's entry takes.
MAX_DIRECTORY_BYTES = 16 * 1024 * 1024

# Zip record signatures and fixed sizes (APPNOTE 4.3).
EOCD_SIG, EOCD_LEN = b"PK\x05\x06", 22
ZIP64_LOCATOR_SIG, ZIP64_LOCATOR_LEN = b"PK\x06\x07", 20
CENTRAL_SIG, CENTRAL_LEN = b"PK\x01\x02", 46

CONTAINER = "META-INF/container.xml"
ENCRYPTION = "META-INF/encryption.xml"

# The two font-obfuscation algorithms an encryption.xml may list without the
# book being protected: they mangle the first bytes of an embedded font file so
# it cannot be lifted out of the book, and touch no text.
FONT_OBFUSCATION = frozenset({
    "http://www.idpf.org/2008/embedding",
    "http://ns.adobe.com/pdf/enc#RC",
})

CONTENT_TYPES = frozenset({"application/xhtml+xml", "text/html"})
NCX_TYPE = "application/x-dtbncx+xml"
SECTION_FALLBACK = "Section {n}"
NOTES_SECTION = "Notes"

NS = {
    "c": "urn:oasis:names:tc:opendocument:xmlns:container",
    "opf": "http://www.idpf.org/2007/opf",
    "dc": "http://purl.org/dc/elements/1.1/",
    "ncx": "http://www.daisy.org/z3986/2005/ncx/",
    "enc": "http://www.w3.org/2001/04/xmlenc#",
}
OPF_ROLE = "{http://www.idpf.org/2007/opf}role"


class EpubRefused(Exception):
    """The file is not indexed. The message is a reason, never a quote."""


@dataclass
class EpubBook:
    title: str                          # "" when the package names none
    author: str                         # "" when the package names none
    sections: list[tuple[str, str]]


# --- the archive --------------------------------------------------------------

def unsafe_name(name: str) -> bool:
    """A member name that could point outside an extraction root, were the
    archive ever extracted: absolute, a drive letter, a `..` segment, a NUL."""
    if not name or "\x00" in name or name[0] in "/\\" or re.match(r"[A-Za-z]:", name):
        return True
    return any(part == ".." for part in re.split(r"[/\\]", name))


def too_many(count: int | str) -> EpubRefused:
    return EpubRefused(f"too many files in the archive ({count}, the limit is {MAX_MEMBERS})")


def check_directory(fp) -> None:
    """Refuse an archive whose directory is too large BEFORE `zipfile` reads it.

    `zipfile.ZipFile` materialises one `ZipInfo` per central-directory entry
    while it opens the file, so a count checked afterwards (`Archive`) is
    checked after the memory is spent — a 20,000-entry archive of under 2 MiB
    took over 10 MiB to refuse. Here the end record is read from the file's
    tail first.

    A ZIP64 archive is refused before anything else: a ZIP64 locator before
    the end record, or any end-record field at its ZIP64 escape value (0xFFFF,
    0xFFFFFFFF). ZIP64 exists for more than 65,535 entries or a member or
    archive over 4 GiB, both far past the caps here, so an EPUB never needs
    it — and its end record has an extensible-data sector of any length, which
    a check that assumed a fixed size let a 20,000-entry directory past. Not
    parsing it at all is the bound.

    Then three numbers: the declared entry count, whether the file is large
    enough to hold that many entries (46 bytes each at least), and the
    directory's declared size. The count alone can lie, and `zipfile` walks the
    directory's BYTES, not its count; so the entries are then counted over the
    same bytes the same way `zipfile` will walk them — a header at a time, with
    nothing allocated per entry — and the walk stops at MAX_MEMBERS + 1.

    Anything that does not parse is left for `zipfile` to call damaged: this
    function only ever refuses on numbers, it never decides that a file is a
    zip archive."""
    fp.seek(0, 2)
    size = fp.tell()
    tail_len = min(size, 0xFFFF + EOCD_LEN)
    fp.seek(size - tail_len)
    tail = fp.read(tail_len)
    pos = tail.rfind(EOCD_SIG)
    while pos >= 0 and pos + EOCD_LEN > len(tail):
        pos = tail.rfind(EOCD_SIG, 0, pos)
    if pos < 0:
        return
    eocd_at = size - tail_len + pos
    _, disk, cd_disk, on_disk, total, cd_size, cd_offset, _ = struct.unpack(
        "<4s4H2LH", tail[pos:pos + EOCD_LEN])
    locator_at = eocd_at - ZIP64_LOCATOR_LEN
    locator = b""
    if locator_at >= 0:
        fp.seek(locator_at)
        locator = fp.read(4)
    if (locator == ZIP64_LOCATOR_SIG or 0xFFFF in (disk, cd_disk, on_disk, total)
            or 0xFFFFFFFF in (cd_size, cd_offset)):
        raise EpubRefused("ZIP64 archives are not read (an EPUB never needs one)")
    count = max(on_disk, total)
    if count > MAX_MEMBERS:
        raise too_many(count)
    if count * CENTRAL_LEN > size:
        raise EpubRefused("malformed: its directory declares more files than the archive "
                          "could hold")
    if cd_size > MAX_DIRECTORY_BYTES:
        raise EpubRefused(f"the archive's directory is larger than "
                          f"{MAX_DIRECTORY_BYTES // (1024 * 1024)} MiB")
    cd_at = eocd_at - cd_size
    if cd_at < 0:
        return
    fp.seek(cd_at)
    directory = fp.read(cd_size)
    seen = at = 0
    while at + CENTRAL_LEN <= len(directory) and directory[at:at + 4] == CENTRAL_SIG:
        name_len, extra_len, comment_len = struct.unpack_from("<3H", directory, at + 28)
        at += CENTRAL_LEN + name_len + extra_len + comment_len
        seen += 1
        if seen > MAX_MEMBERS:
            raise too_many(f"over {MAX_MEMBERS}")


class Archive:
    """A zip archive read by member name into memory, within the caps."""

    def __init__(self, zf: zipfile.ZipFile):
        infos = zf.infolist()
        # The second line of the same check: `check_directory` has already
        # refused a directory over the cap before `zipfile` read it, so this
        # holds only if the two ever count differently.
        if len(infos) > MAX_MEMBERS:
            raise too_many(len(infos))
        total = 0
        for info in infos:
            if unsafe_name(info.filename):
                raise EpubRefused("the archive holds a file whose path is absolute or "
                                  "climbs out of it with '..'")
            if info.file_size > MAX_MEMBER_BYTES:
                raise EpubRefused(f"a file in the archive is larger than "
                                  f"{MAX_MEMBER_BYTES // (1024 * 1024)} MiB uncompressed")
            total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise EpubRefused(f"the archive is larger than "
                              f"{MAX_TOTAL_BYTES // (1024 * 1024)} MiB uncompressed")
        self.zf = zf
        self.names = {info.filename for info in infos}

    def has(self, name: str) -> bool:
        return name in self.names

    def read(self, name: str) -> bytes:
        if name not in self.names:
            raise EpubRefused("malformed: the package names a file the archive does not hold")
        try:
            with self.zf.open(name) as member:
                data = member.read(MAX_MEMBER_BYTES + 1)
        except RuntimeError as error:               # a password-protected zip entry
            raise EpubRefused("protected (an encrypted archive entry; nothing was "
                              "decrypted)") from error
        except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError,
                ValueError) as error:
            raise EpubRefused("the archive is damaged or uses an unsupported "
                              "compression") from error
        if len(data) > MAX_MEMBER_BYTES:
            raise EpubRefused(f"a file in the archive inflates past "
                              f"{MAX_MEMBER_BYTES // (1024 * 1024)} MiB")
        return data


def resolve(base: str, href: str) -> str | None:
    """A reference inside the package, relative to the member `base`, as a
    member name: fragment dropped, percent-escapes decoded. None for a URL with
    a scheme, an empty reference, or one that leaves the archive root."""
    parts = urlsplit(href)
    if parts.scheme or parts.netloc or not parts.path:
        return None
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(base), unquote(parts.path)))
    if joined.startswith("/") or joined == ".." or joined.startswith("../"):
        return None
    return joined


# --- text and XML -------------------------------------------------------------

_XML_DECL = re.compile(rb"^<\?xml[^>]*?encoding\s*=\s*[\"']([A-Za-z0-9._:-]+)[\"']")
_XML_DECL_TEXT = re.compile(r"^\s*<\?xml[^>]*\?>")
# Python codecs that decode bytes to text but are not character sets: an XML
# declaration naming one is not an encoding a book was ever written in.
# UTF-7 is a character set, but one that can spell a lone surrogate, which no
# later step can encode; no book needs it.
NOT_A_CHARSET = frozenset({"unicode_escape", "raw_unicode_escape", "punycode", "idna",
                           "utf_7"})


def decode(data: bytes) -> str:
    """The document as text: a byte-order mark first, then the encoding the XML
    declaration names, then UTF-8. Strict: a document that does not decode as
    what it says it is refuses the book rather than indexing mojibake."""
    for bom, encoding in ((codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF16_LE, "utf-16-le"),
                          (codecs.BOM_UTF16_BE, "utf-16-be")):
        if data.startswith(bom):
            data, declared = data[len(bom):], encoding
            break
    else:
        match = _XML_DECL.match(data.lstrip())
        declared = match.group(1).decode("ascii") if match else "utf-8"
    try:
        if codecs.lookup(declared).name.replace("-", "_") in NOT_A_CHARSET:
            raise LookupError(declared)
        text = data.decode(declared)
        text.encode("utf-8")            # a lone surrogate would fail every later step
        return text
    # UnicodeError, not only UnicodeDecodeError: a codec that cannot decode at
    # all (`encoding="undefined"`) raises the base class.
    except (LookupError, UnicodeError) as error:
        raise EpubRefused("a document in it is not readable in the encoding it "
                          "declares") from error


def refuse_entities(text: str) -> None:
    """Entity declarations are the one way XML text can multiply itself while
    it is parsed (the "billion laughs"), and a book has no use for them. The
    check is a literal one over the whole document, before any parser sees it:
    there is no DOCTYPE shape that can hide a declaration from it."""
    if "<!ENTITY" in text:
        raise EpubRefused("a document in it declares XML entities, which a book does "
                          "not need and which can expand without bound")


def parse_xml(archive: Archive, name: str) -> ET.Element:
    text = decode(archive.read(name))
    refuse_entities(text)
    try:
        return ET.fromstring(_XML_DECL_TEXT.sub("", text, count=1))
    except ET.ParseError as error:
        raise EpubRefused("malformed: a package file in it is not well-formed XML") from error


_DOCTYPE_SUBSET_END = re.compile(r"\]\s*>")


def drop_doctype(text: str) -> str:
    """A content document without its DOCTYPE. `html.parser` never expands a
    declared entity, so a DTD in XHTML is harmless, but it does not parse an
    internal subset either and would leave its tail (`]>`) as text."""
    start = text.find("<!DOCTYPE")
    if start < 0:
        return text
    close = text.find(">", start)
    bracket = text.find("[", start)
    if 0 <= bracket < close or (bracket >= 0 and close < 0):
        end = _DOCTYPE_SUBSET_END.search(text, bracket)
        close = end.end() - 1 if end else -1
    return text if close < 0 else text[:start] + text[close + 1:]


def read_text_member(archive: Archive, name: str) -> str:
    """A content or navigation document, as text for `html.parser`."""
    return drop_doctype(decode(archive.read(name)))


# Elements whose content is not the book's text.
SKIPPED = frozenset({"script", "style", "head", "title", "svg", "math", "noscript",
                     "template", "object", "iframe", "button", "select", "textarea"})
# Elements that end a paragraph: their text never runs into the next block's.
BLOCKS = frozenset({"p", "div", "section", "article", "aside", "header", "footer",
                    "nav", "main", "blockquote", "pre", "ul", "ol", "li", "dl", "dt",
                    "dd", "table", "tr", "td", "th", "thead", "tbody", "caption",
                    "figure", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6",
                    "hr", "br", "address", "body", "html"})
VOID = frozenset({"br", "hr", "img", "meta", "link", "input", "area", "base", "col",
                  "embed", "source", "track", "wbr", "param"})


class _TextExtractor(HTMLParser):
    """The readable text of one content document, as paragraphs."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._current: list[str] = []
        # The stack of open skipped elements, and how many of each tag it
        # holds: an end tag is looked up in the counter, never in the stack,
        # so stray end tags cost O(1) each and every push is popped at most
        # once. A list scan here made 40,000 stray `</q>` inside an `<svg>`
        # quadratic — seconds for a 2 KB file.
        self._skip: list[str] = []
        self._open: Counter[str] = Counter()

    def _push(self, tag: str) -> None:
        self._skip.append(tag)
        self._open[tag] += 1

    def _end_paragraph(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._current)).strip()
        if text:
            self.paragraphs.append(text)
        self._current = []

    def handle_starttag(self, tag, attrs):
        if self._skip:
            if tag not in VOID:
                self._push(tag)
            return
        if tag in SKIPPED:
            self._push(tag)
            return
        if tag in BLOCKS:
            self._end_paragraph()

    def handle_startendtag(self, tag, attrs):
        if not self._skip and tag in BLOCKS:
            self._end_paragraph()

    def handle_endtag(self, tag):
        if self._skip:
            # Closes the innermost open skipped element, and anything left open
            # inside it: markup that forgets a close tag must not leak a
            # script's text into the book, nor swallow the rest of the chapter.
            if self._open[tag]:
                while True:
                    popped = self._skip.pop()
                    self._open[popped] -= 1
                    if popped == tag:
                        break
            return
        if tag in BLOCKS:
            self._end_paragraph()

    def handle_data(self, data):
        if not self._skip:
            self._current.append(data)

    def text(self) -> str:
        self._end_paragraph()
        return "\n\n".join(self.paragraphs)


def extract_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return strip_control_chars(parser.text())


def clean_label(label: str) -> str:
    return re.sub(r"\s+", " ", strip_control_chars(label)).strip()


# --- the navigation -----------------------------------------------------------

class _NavReader(HTMLParser):
    """(href, label) of every link inside the EPUB 3 table of contents, in
    document order — which flattens nested lists depth-first, parent first."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries: list[tuple[str, str]] = []
        self._nav_depth = 0             # >0 inside the toc nav (counting nested navs)
        self._link: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "nav":
            kinds = (attributes.get("epub:type") or "").split()
            if self._nav_depth:
                self._nav_depth += 1
            elif "toc" in kinds or attributes.get("role") == "doc-toc":
                self._nav_depth = 1
            return
        if self._nav_depth and tag == "a" and attributes.get("href"):
            self._link, self._label = attributes["href"], []

    def handle_endtag(self, tag):
        if tag == "nav" and self._nav_depth:
            self._nav_depth -= 1
        elif tag == "a" and self._link is not None:
            self.entries.append((self._link, clean_label("".join(self._label))))
            self._link = None

    def handle_data(self, data):
        if self._link is not None:
            self._label.append(data)


def nav_entries(archive: Archive, nav_name: str) -> list[tuple[str, str]]:
    """(member, label) for an EPUB 3 navigation document's table of contents."""
    reader = _NavReader()
    reader.feed(read_text_member(archive, nav_name))
    reader.close()
    out = []
    for href, label in reader.entries:
        target = resolve(nav_name, href)
        if target:
            out.append((target, label))
    return out


def ncx_entries(archive: Archive, ncx_name: str) -> list[tuple[str, str]]:
    """(member, label) for an EPUB 2 `toc.ncx`, navPoints in document order."""
    root = parse_xml(archive, ncx_name)
    out = []
    for point in root.iter(f"{{{NS['ncx']}}}navPoint"):
        content = point.find("ncx:content", NS)
        label = point.find("ncx:navLabel/ncx:text", NS)
        if content is None or not content.get("src"):
            continue
        target = resolve(ncx_name, content.get("src"))
        if target:
            out.append((target, clean_label(label.text or "") if label is not None else ""))
    return out


# --- the package --------------------------------------------------------------

def refuse_drm(archive: Archive) -> None:
    """An `encryption.xml` entry with anything but font obfuscation means the
    content is encrypted: refused, with nothing decrypted or stripped."""
    if not archive.has(ENCRYPTION):
        return
    root = parse_xml(archive, ENCRYPTION)
    for data in root.iter(f"{{{NS['enc']}}}EncryptedData"):
        method = data.find("enc:EncryptionMethod", NS)
        algorithm = method.get("Algorithm", "") if method is not None else ""
        if algorithm not in FONT_OBFUSCATION:
            raise EpubRefused("DRM-protected (its content is encrypted; nothing was "
                              "decrypted)")


def package_path(archive: Archive) -> str:
    root = parse_xml(archive, CONTAINER)
    for rootfile in root.iter(f"{{{NS['c']}}}rootfile"):
        media = rootfile.get("media-type", "application/oebps-package+xml")
        path = rootfile.get("full-path", "")
        if media == "application/oebps-package+xml" and path and not unsafe_name(path):
            return posixpath.normpath(path)
    raise EpubRefused("malformed: its container names no package document")


def creators(metadata: ET.Element) -> str:
    """The author line: creators with the author role, or with no role at all;
    every creator when none qualifies. EPUB 2 puts the role on the element
    (`opf:role`), EPUB 3 in a `meta` that refines the creator's id."""
    roles: dict[str, str] = {}
    for meta in metadata.findall("opf:meta", NS):
        if meta.get("property") == "role" and (meta.get("refines") or "").startswith("#"):
            roles[meta.get("refines")[1:]] = (meta.text or "").strip()
    named = []
    for creator in metadata.findall("dc:creator", NS):
        name = clean_label("".join(creator.itertext()))
        if name:
            role = creator.get(OPF_ROLE) or roles.get(creator.get("id") or "", "")
            named.append((name, role))
    authors = [name for name, role in named if role in ("", "aut")]
    return ", ".join(authors or [name for name, _ in named])


@dataclass
class Package:
    title: str
    author: str
    spine: list[tuple[str, bool]]       # (content document, linear)
    nav: str | None                     # EPUB 3 navigation document
    ncx: str | None                     # EPUB 2 NCX


def read_package(archive: Archive, opf_name: str) -> Package:
    root = parse_xml(archive, opf_name)
    if root.tag != f"{{{NS['opf']}}}package":
        raise EpubRefused("malformed: its package document is not an OPF package")
    metadata = root.find("opf:metadata", NS)
    title = ""
    author = ""
    if metadata is not None:
        first = metadata.find("dc:title", NS)
        title = clean_label("".join(first.itertext())) if first is not None else ""
        author = creators(metadata)

    manifest: dict[str, tuple[str, str, str]] = {}      # id -> (member, media type, properties)
    nav = ncx = None
    for item in root.iterfind("opf:manifest/opf:item", NS):
        target = resolve(opf_name, item.get("href", ""))
        if not target or not item.get("id"):
            continue
        media = (item.get("media-type") or "").strip().lower()
        properties = (item.get("properties") or "").split()
        manifest[item.get("id")] = (target, media, " ".join(properties))
        if "nav" in properties and media in CONTENT_TYPES:
            nav = nav or target
        if media == NCX_TYPE:
            ncx = ncx or target

    spine_el = root.find("opf:spine", NS)
    if spine_el is None:
        raise EpubRefused("malformed: its package has no spine (no reading order)")
    toc_id = spine_el.get("toc")
    if toc_id and toc_id in manifest and manifest[toc_id][1] == NCX_TYPE:
        ncx = manifest[toc_id][0]
    spine = []
    for ref in spine_el.findall("opf:itemref", NS):
        entry = manifest.get(ref.get("idref") or "")
        if entry is None or entry[1] not in CONTENT_TYPES:
            continue                    # images, SVG, anything that is not a text document
        spine.append((entry[0], (ref.get("linear") or "yes").strip().lower() != "no"))
    return Package(title=title, author=author, spine=spine, nav=nav, ncx=ncx)


def titles_by_document(archive: Archive, package: Package) -> dict[str, str]:
    """member -> the first navigation label pointing at it (any fragment)."""
    entries: list[tuple[str, str]] = []
    if package.nav and archive.has(package.nav):
        entries = nav_entries(archive, package.nav)
    if not entries and package.ncx and archive.has(package.ncx):
        entries = ncx_entries(archive, package.ncx)
    titles: dict[str, str] = {}
    for member, label in entries:
        if label and member not in titles:
            titles[member] = label
    return titles


def build_sections(documents: list[tuple[str, str, bool]], titles: dict[str, str]
                   ) -> list[tuple[str, str]]:
    """[(member, text, linear)] in reading order -> [(section title, text)].

    A section's text is collected as a list of parts and joined once: joining
    as it grew made a chapter of a few thousand unnamed files quadratic."""
    named = [member for member, _, _ in documents if member in titles]
    if not named:
        with_text = [text for _, text, _ in documents if text.strip()]
        if len(with_text) == 1:
            return [(FULL_TEXT_SECTION, with_text[0])]
        return [(SECTION_FALLBACK.format(n=n), text) for n, text in enumerate(with_text, 1)]
    sections: list[tuple[str, list[str]]] = []
    for member, text, linear in documents:
        if member in titles:
            sections.append((titles[member], [text]))
        elif not linear:
            # Supplementary text out of the reading order continues nothing:
            # appended to the last chapter, a note would be cited as that chapter.
            sections.append((NOTES_SECTION, [text]))
        elif sections:
            sections[-1][1].append(text)
        else:
            sections.append((FRONT_MATTER_SECTION, [text]))
    joined = [(title, "\n\n".join(p.strip() for p in parts if p.strip()))
              for title, parts in sections]
    return unique_titles([(title, text) for title, text in joined if text])


def read_epub(path: Path) -> EpubBook:
    """The whole read. Raises `EpubRefused` for anything that is not indexed."""
    try:
        with open(path, "rb") as fp:
            check_directory(fp)
            with zipfile.ZipFile(fp) as zf:
                archive = Archive(zf)
                refuse_drm(archive)
                package = read_package(archive, package_path(archive))
                ordered = ([(m, True) for m, linear in package.spine if linear]
                           + [(m, False) for m, linear in package.spine if not linear])
                # The contents page is not text of the book: its entries are the
                # section titles already.
                ordered = [(m, linear) for m, linear in ordered if m != package.nav]
                if not ordered:
                    raise EpubRefused("no readable spine: it lists no XHTML/HTML document")
                documents, seen = [], set()
                for member, linear in ordered:
                    if member in seen:
                        continue
                    seen.add(member)
                    documents.append((member, extract_text(read_text_member(archive, member)),
                                      linear))
                sections = build_sections(documents, titles_by_document(archive, package))
    except zipfile.BadZipFile as error:
        raise EpubRefused("malformed: not a readable zip archive") from error
    except (UnicodeError, ValueError) as error:
        # A member name flagged UTF-8 that is not, and anything else `zipfile`
        # reports as a bad value while reading the archive's directory.
        raise EpubRefused("malformed: the archive's directory is not readable") from error
    except (zlib.error, EOFError, NotImplementedError) as error:
        raise EpubRefused("the archive is damaged or uses an unsupported "
                          "compression") from error
    except OSError as error:
        raise EpubRefused("the file cannot be read") from error
    if not sections:
        raise EpubRefused("no text in it")
    return EpubBook(title=package.title, author=package.author, sections=sections)
