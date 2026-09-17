"""Book identity: the one home for the strings that name a book.

Every string here ends up in an index — as the `book` column the agent cites
and filters on, as the `note` row key an update deletes by, or inside a
`chunk_id`, which is the retrieval dedupe key and the ordering key within a
chapter. So none of them may change without a rebuild of every index that
holds them, and `tests/test_book_identity_fixtures.py` pins what they are.

They used to be spread over four modules, each with its own half of the rule:
`book_key`/`slug` and the file-name parsing in `ingest/add_folder.py`,
`title_of`/`author_of` and the bare-title row match in `library.py`, the
`read_chapters` grammar in `nodes.py`, and a second separator parser in
`catalog.py`. Four places is three too many for a rule that decides whether a
delete matches a row.

This module imports nothing from the package but `sanitize`, so every layer
(ingest, retrieval, the agent, the catalogue) can depend on it.

A note on what identity this is. `book_key` is a *derived* string: correct an
author and the key changes, which is exactly why a stable `book_id` is minted
and kept in the ledger (`ingest/ledger.py`) instead of being derived from
anything here. The key stays what the reader sees and what the agent cites;
the id is what the index is updated by.
"""
import hashlib
import re

from .sanitize import strip_control_chars

# The index key for a book is "Title — Author". Reflect may hand back only the
# title, which is why every consumer below has a bare-title rule.
TITLE_SEPARATOR = " — "
UNKNOWN_AUTHOR = "Unknown"

# Separators accepted between a title and an author when one is parsed out of a
# file name or a first line, longest first so " -- " is not consumed by " - ".
# The canonical key always uses TITLE_SEPARATOR.
AUTHOR_SEPARATORS = (" — ", " – ", " -- ", " - ", "—", "–")

# A first line is only read as a title line when it is this short: a narrative
# sentence containing " by " must not be mistaken for "Title by Author".
MAX_TITLE_LINE = 120

SLUG_DIGEST_CHARS = 8


# --- the key ----------------------------------------------------------------

def book_key(title: str, author: str) -> str:
    """The key the agent cites and filters on, so it is also the string that
    ends up in a terminal, in a prompt and in a chunk id: control and invisible
    formatting characters are dropped before anything downstream sees them."""
    title = re.sub(r"\s+", " ", strip_control_chars(title)).strip()
    author = re.sub(r"\s+", " ", strip_control_chars(author)).strip() or UNKNOWN_AUTHOR
    return f"{title}{TITLE_SEPARATOR}{author}"


def title_of(key: str) -> str:
    """'Moby Dick' for the index key 'Moby Dick — Herman Melville'."""
    return key.rsplit(TITLE_SEPARATOR, 1)[0].strip()


def author_of(key: str) -> str:
    """'Herman Melville' for 'Moby Dick — Herman Melville'; "" for a key without
    the separator."""
    return key.rsplit(TITLE_SEPARATOR, 1)[1].strip() if TITLE_SEPARATOR in key else ""


def split_title_author(raw: str) -> tuple[str, str] | None:
    """"Title — Author" / "Title by Author" -> (title, author); None otherwise.
    Split on the LAST separator: a title may itself contain a dash."""
    text = raw.strip()
    for separator in AUTHOR_SEPARATORS:
        if separator in text:
            title, _, author = text.rpartition(separator)
            if title.strip() and author.strip():
                return title.strip(), author.strip()
    match = re.search(r"^(.+)\s+by\s+(\S.*)$", text, re.I)   # greedy: the LAST " by "
    if match and match.group(1).strip():
        return match.group(1).strip(), match.group(2).strip()
    return None


# --- the row key ------------------------------------------------------------

def slug(text: str) -> str:
    """Row key derived from the book key: stable across file renames, so
    re-adding the same book replaces its rows instead of duplicating them.

    The readable part is ASCII-only and cut to 80 characters, which alone would
    collapse distinct keys onto one row key (two Cyrillic titles both become
    "book", and the second add would delete the first book's rows). A short
    digest of the FULL key is appended, so the row key is unique per key while
    still being readable in a chunk id."""
    readable = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80] or "book"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:SLUG_DIGEST_CHARS]
    return f"{readable}-{digest}"


# --- the chunk id -----------------------------------------------------------

# What an untitled section is called inside a chunk id. Not a sentinel — a book
# may genuinely contain a section titled "full" — which is why the folder
# ingest's ids carry an ordinal as well (see `chunk_id`).
UNTITLED_SECTION = "full"


def chunk_id(note: str, section: str, position: int, ordinal: int | None = None) -> str:
    """The id of one chunk: `note#[ordinal.]section/position`.

    This is the retrieval dedupe key, the ordering key within a chapter
    (`rsplit("/", 1)` gives the position) and part of what a re-ingest must
    reproduce byte for byte, so it lives here with the rest of book identity
    rather than once per ingest path — it used to be an f-string in each, and
    the two were only the same by inspection.

    `ordinal` is the section's position in the book, and the two ingest paths
    differ in whether they need it. The folder ingest passes it because a
    section TITLE alone is not a unique name: an untitled preamble is written as
    "full" and a book may contain a section actually titled "full", which would
    give the two identical ids and drop each other's chunks out of the results.
    The demo corpus omits it because its titles are already unique per book —
    `save_prepared` refuses a book with repeated chapter titles outright, which
    is a stronger guarantee made earlier."""
    name = section or UNTITLED_SECTION
    head = f"{ordinal}.{name}" if ordinal is not None else name
    return f"{note}#{head}/{position}"


# --- the bare-title rules ---------------------------------------------------
# Three consumers ask the same question in three shapes: does this name, which
# may be a full key or only a title, mean this book?

def names_book(wanted: str, key: str) -> bool:
    """Does `wanted` name the book whose index key is `key`? An exact key
    matches; a bare title matches the title part exactly, never as a prefix
    ("Emma" must not match "Emma's Diary")."""
    return key == wanted or title_of(key) == wanted


READ_STATUSES = ("complete", "partial", "empty", "ambiguous")


def read_key(entry: str) -> str:
    """'book|section' of a read_chapters entry, whether or not it carries a
    trailing '|status'. Section names may themselves contain '|', so the status
    is recognised from the right and only when it is a known value."""
    head, _, last = entry.rpartition("|")
    return head if last in READ_STATUSES else entry


def read_status(entry: str) -> str:
    """Status of a read_chapters entry; legacy two-part entries count as complete."""
    last = entry.rpartition("|")[2]
    return last if last in READ_STATUSES else "complete"


CHAPTER_MARKER = "__chapter__|"
# The SAME action, carrying one field more: what the model is looking for in
# that chapter (ADR-025). It is a second marker NAME rather than a fourth field
# on the first one, and the reason is the section.
#
# A section name is the book's own words. It is looked up literally in the
# index and must come back out of the marker byte for byte — pipes included,
# which is why every component is escaped below — so it is the field that
# absorbs the rest of the string, and no new
# field may be recognised after it. Any rule that peels a trailing field off
# the right can be spelled by a heading: a chapter called `Weird|q=evil query`
# would hand out a read query the model never wrote and a section the index
# does not have. A trailing SENTINEL only moves the problem — the sentinel is a
# string, and a heading can contain it.
#
# The marker name cannot be spelled by corpus text, because nothing but this
# function writes it. So "is there a read query" is answered by which name was
# used, and the query — the model's own words, which this code may neutralise —
# goes FIRST, where a "|" of its own would break the parse and is therefore
# removed. Book and section then sit exactly where they always sat.
CHAPTER_QUERY_MARKER = "__chapter_q__|"


# The separator is "|", so a component that contains one has to say so rather
# than spell one. Percent-encoding, and only of the two characters that make it
# ambiguous: "%" first (or decoding a real "%7C" in a title would produce a
# separator), then "|". It is LOSSLESS, which matters more here than it looks —
# the book key is matched against the catalogue and the section is looked up
# literally in the index, so a component that came back "cleaned" would find
# nothing, and a book called "Either|Or" would simply have no chapters.
MARKER_ESCAPES = (("%", "%25"), ("|", "%7C"))
_MARKER_UNESCAPE = re.compile("%(25|7C)")


def escape_marker(part: str) -> str:
    """One component of an action marker, with the separator encoded."""
    for raw, encoded in MARKER_ESCAPES:
        part = part.replace(raw, encoded)
    return part


def unescape_marker(part: str) -> str:
    """The inverse, in ONE left-to-right pass — two `str.replace` calls would
    decode the output of the first ("%257C" -> "%7C" -> "|"), which is how an
    escape scheme silently loses the difference between a book called "Either%7COr"
    and one called "Either|Or"."""
    return _MARKER_UNESCAPE.sub(lambda m: "%" if m.group(1) == "25" else "|", part)


def chapter_marker(book: str, section: str, query: str = "") -> str:
    """The action marker for a chapter read: "__chapter__|book|section", or
    "__chapter_q__|query|book|section" when the model said what it is looking
    for (ADR-025).

    The book and the section are encoded and come back out of `act` exactly as
    they went in, "|" included — a book key may contain one (nothing in the
    front matter or the file name forbids it) and a section name is a heading
    the book itself supplied. The query is the model's own words and is not a
    lookup key, so it is simply cleaned of separators and surrounding space."""
    query = " ".join(query.replace("|", " ").split())
    book, section = escape_marker(book), escape_marker(section)
    if not query:
        return f"{CHAPTER_MARKER}{book}|{section}"
    return f"{CHAPTER_QUERY_MARKER}{query}|{book}|{section}"


def split_read_query(marker: str) -> tuple[str, str]:
    """A chapter marker split into (the three-part marker every reader of this
    channel already understands, the read query or "").

    Nothing is peeled off a plain `__chapter__|` marker — whatever its section
    contains — and nothing at all off any other string: a search query is free
    text, and a rule about markers must never trim it."""
    if not marker.startswith(CHAPTER_QUERY_MARKER):
        return marker, ""
    parts = marker.split("|", 2)
    if len(parts) != 3:
        # A malformed action marker: handed back whole, so `act`'s guard for
        # exactly that sees it instead of a read of some invented chapter.
        return marker, ""
    return f"{CHAPTER_MARKER}{parts[2]}", parts[1]


def same_chapter(wanted: str, entry: str) -> bool:
    """Does a read_chapter request name a chapter already in read_chapters?
    "Some Book|Chapter 59" and "Some Book|59" are the same chapter; so are
    "Don Quixote|..." and "Don Quixote — Miguel de Cervantes|..." (act records
    the canonical key, reflect may ask with the bare title), but two different
    full keys never are ("Emma — Jane Austen" is not "Emma — Other Author").
    After an ambiguous read only the identical bare request is a repeat: the
    full key is exactly what the model is told to try next. The trailing
    "|status" of an entry is not part of the key, but a "|" inside a section
    name is."""
    def split(value: str) -> tuple[str, str]:
        book, _, section = read_key(value).partition("|")
        return book.strip().lower(), section.lower().replace("chapter ", "").strip()

    w_book, w_section = split(wanted)
    e_book, e_section = split(entry)
    if w_section != e_section:
        return False
    if w_book == e_book:
        return True
    if read_status(entry) == "ambiguous":
        return False
    w_full, e_full = TITLE_SEPARATOR in w_book, TITLE_SEPARATOR in e_book
    if w_full and e_full:
        return False
    return title_of(w_book) == title_of(e_book)
