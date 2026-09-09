"""`ayl-add <folder>`: index a folder of .txt / .md books into the agent's LanceDB.

The demo corpus is built from a checksum-pinned manifest; this is the generic
path for your own library. Everything downstream is the demo pipeline's code —
`chapters.split_book_sections` for sections, `chunking` for chunks, the
configured embedder (local Ollama bge-m3 by default), `publish` for the staged
write and `index_meta` for the embedding fingerprint — so a folder of your own
files is chunked and stamped exactly like the demo corpus.

    uv run ayl-add ~/books
    LIBRARY_DB_PATH=~/my-lancedb uv run ayl-add ~/books
    uv run ayl-add ~/books --dry-run       # what would be indexed, no embedding

One file = one book. The book key ("Title — Author", the form the agent cites
and filters on) is taken from, in order:

1. a YAML front matter block at the top of the file (`title:` / `author:`);
2. the first line, when it is a standalone title line ("Title — Author" or
   "Title by Author"); that line is then dropped from the body;
3. the file name: "Title - Author.txt" -> "Title — Author"; "Title.txt" ->
   "Title — Unknown".

Writes the transcripts table only. Book cards are a separate, paid step (they
need an LLM to distil each book) and are not generated here — the agent
searches full text alone when the cards table is absent.
"""
import argparse
import hashlib
import logging
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import lancedb
import pyarrow as pa

from ..config import DB_PATH, EMBED_BACKEND
from ..embeddings import get_embedder
from ..index_meta import check_index, read_index_meta, write_index_meta
from ..library import TITLE_SEPARATOR
from ..sanitize import LINE_BREAK_RE, strip_control_chars
from .chapters import MergedHeading, split_book_sections
from .chunking import Chunk, embedding_text, pack_sentences, parse_frontmatter, rows_for, \
    split_sentences
from .fts import build_fts_index
from .publish import COPY_BATCH_ROWS, NoRowsError, rebuild_table, recover_staging, \
    table_batches, table_names

log = logging.getLogger(__name__)


def terminal_safe(text: str) -> str:
    """One line of this CLI, ready for a terminal: the control and invisible
    characters dropped, and every form of line break left as a plain LF — a
    bare CR in a heading would otherwise put the cursor back at the start of
    the line just written and let the rest overwrite it."""
    return LINE_BREAK_RE.sub("\n", strip_control_chars(text))


class _StripControlChars(logging.Filter):
    """Every warning this module writes names something from the indexed
    folder: a file name, a heading, a book key. The strip sits on the logger
    instead of on each call site, so a warning added later is safe by
    construction and cannot repaint the terminal it is read in."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(self._clean(a) for a in record.args)
        elif isinstance(record.args, Mapping):
            # log.warning("%(book)s ...", {"book": key}): logging keeps a lone
            # mapping argument as the args itself, so the tuple branch never
            # sees it and those names would reach the terminal unstripped.
            record.args = {key: self._clean(value) for key, value in record.args.items()}
        return True

    @staticmethod
    def _clean(value):
        # Names arrive as str or as Path (always formatted with %s here);
        # counts and exceptions are left alone so %d keeps working.
        if isinstance(value, (str, Path)):
            return terminal_safe(str(value))
        return value


log.addFilter(_StripControlChars())


def say(line: str, error: bool = False) -> None:
    """The CLI's own output, through the same strip as the warnings: book keys
    and section titles come from the files being indexed."""
    print(terminal_safe(line), file=sys.stderr if error else sys.stdout, flush=True)


class IngestError(Exception):
    """A problem the user can fix, reported as one line instead of a traceback."""


BOOK_SUFFIXES = (".txt", ".md", ".markdown")
MARKDOWN_SUFFIXES = (".md", ".markdown")
UNKNOWN_AUTHOR = "Unknown"

# Separators accepted between a title and an author, longest first so " -- "
# is not consumed by " - ". The canonical key always uses TITLE_SEPARATOR.
AUTHOR_SEPARATORS = (" — ", " – ", " -- ", " - ", "—", "–")
# A first line is only read as a title line when it is this short: a narrative
# sentence containing " by " must not be mistaken for "Title by Author".
MAX_TITLE_LINE = 120


@dataclass
class Book:
    """One source file, resolved into what the index needs."""
    note: str                          # row key for idempotent re-adds
    book: str                          # "Title — Author", the agent's citation key
    source: str                        # provenance, file name only (no local paths)
    path: Path
    sections: list[tuple[str, str]]
    # contents lines merged into the section above them, reported by the CLI
    merged_headings: list[MergedHeading] = field(default_factory=list)


# --- book key ---------------------------------------------------------------

def book_key(title: str, author: str) -> str:
    """The key the agent cites and filters on, so it is also the string that
    ends up in a terminal, in a prompt and in a chunk id: control and invisible
    formatting characters are dropped before anything downstream sees them."""
    title = re.sub(r"\s+", " ", strip_control_chars(title)).strip()
    author = re.sub(r"\s+", " ", strip_control_chars(author)).strip() or UNKNOWN_AUTHOR
    return f"{title}{TITLE_SEPARATOR}{author}"


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


def key_from_frontmatter(meta: dict) -> str | None:
    title = (meta.get("title") or "").strip()
    if not title:
        return None
    return book_key(title, (meta.get("author") or "").strip())


def key_from_first_line(body: str) -> tuple[str, str] | None:
    """(key, body without the title line), or None.

    A first line counts as a title line only when it is short and structurally
    set apart — a Markdown heading, or followed by a blank line — so a book
    that opens straight into prose is never mined for a fake author."""
    stripped = body.lstrip("\n")
    first, newline, rest = stripped.partition("\n")
    line = first.strip()
    is_heading = line.startswith("#")
    if is_heading:
        line = line.lstrip("#").strip().rstrip("#").strip()
    if not line or len(line) > MAX_TITLE_LINE:
        return None
    if not newline or not rest.strip():
        return None                     # nothing follows: not a title line
    if not is_heading and not rest.startswith("\n"):
        return None                     # no blank line after it: ordinary prose
    parts = split_title_author(line)
    if not parts:
        return None
    return book_key(*parts), rest.lstrip("\n")


def key_from_filename(path: Path) -> str:
    parts = split_title_author(path.stem)
    if parts:
        return book_key(*parts)
    return book_key(path.stem, UNKNOWN_AUTHOR)


SLUG_DIGEST_CHARS = 8


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


# --- reading a folder -------------------------------------------------------

def book_files(folder: Path) -> list[Path]:
    """Every .txt / .md file under the folder, recursively.

    Skipped, and reported: hidden files and hidden directories; symlinks, in or
    out of the folder; anything that resolves outside the folder (a symlinked
    parent directory). `is_file()` follows symlinks, so without this a
    `books/notes.md -> ~/.ssh/id_rsa` would be read and its text handed to the
    embedding backend. Copy the file in if you want it indexed.

    Hidden paths are reported as one line, not one per file: a single hidden
    directory can hold hundreds of them, and a warning per file would bury the
    per-file warnings that need reading."""
    root = folder.resolve()
    found = []
    hidden = []
    for path in folder.rglob("*"):
        relative = path.relative_to(folder)
        if path.suffix.lower() not in BOOK_SUFFIXES:
            continue
        if any(part.startswith(".") for part in relative.parts):
            # Checked after the suffix, so the count names the files that would
            # otherwise have been indexed, not everything under a .git.
            hidden.append(relative)
            continue
        if path.is_symlink():
            log.warning("%s: symlink, skipped (copy the file in to index it)", relative)
            continue
        if not path.is_file():
            continue
        try:
            resolved = path.resolve()
        except OSError as error:                    # broken link, permissions
            log.warning("%s: cannot be resolved (%s), skipped", relative, error)
            continue
        if not resolved.is_relative_to(root):
            log.warning("%s: resolves outside %s, skipped", relative, folder)
            continue
        found.append(path)
    if hidden:
        hidden.sort()                               # same report for the same folder
        names = ", ".join(str(h) for h in hidden[:3])
        more = f", and {len(hidden) - 3} more" if len(hidden) > 3 else ""
        log.warning("%d hidden file%s skipped (hidden, or under a hidden directory): %s%s "
                    "(rename or move them out to index them)",
                    len(hidden), "" if len(hidden) == 1 else "s", names, more)
    return sorted(found)


def read_book(path: Path, folder: Path) -> Book | None:
    """One file -> a Book, or None when the file cannot be indexed.

    Unreadable files are warned about and skipped, never fatal: a folder of a
    few hundred books should not be blocked by one stray PDF that happens to be
    named .txt, and the run reports every file it left out."""
    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        log.warning("%s: not UTF-8 text (%s), skipped — convert it or move it out of "
                    "the folder", path.relative_to(folder), error)
        return None
    meta, body = parse_frontmatter(raw)
    key = key_from_frontmatter(meta)
    if not key:
        from_line = key_from_first_line(body)
        if from_line:
            key, body = from_line
        else:
            key = key_from_filename(path)
    if not body.strip():
        log.warning("%s: no text after the title/front matter, skipped",
                    path.relative_to(folder))
        return None
    sections, merged = split_book_sections(
        body, markdown=path.suffix.lower() in MARKDOWN_SUFFIXES)
    for heading in merged:
        # Not silent: the user asked for this file to be indexed, and part of it
        # is now searchable under a section name other than its own heading.
        log.warning("%s: %r looks like a table-of-contents line (%d characters of text, "
                    "and the same heading appears later in the file) — its text was merged "
                    "into %r instead of opening a section",
                    path.relative_to(folder), heading.title, heading.body_chars,
                    heading.target)
    return Book(note=slug(key), book=key, source=f"local:{path.name}", path=path,
                sections=sections, merged_headings=merged)


def read_folder(folder: Path) -> list[Book]:
    files = book_files(folder)
    if not files:
        raise IngestError(f"no .txt or .md files in {folder}")
    books: list[Book] = []
    by_note: dict[str, Book] = {}
    for path in files:
        book = read_book(path, folder)
        if book is None:
            continue
        clash = by_note.get(book.note)
        if clash:
            raise IngestError(
                f"two files resolve to the same book {book.book!r}: "
                f"{clash.path.name} and {path.name} — give them distinct titles "
                f"(front matter `title:`/`author:`) or remove one")
        by_note[book.note] = book
        books.append(book)
    if not books:
        raise IngestError(f"no readable text in {folder}")
    return books


def chunks_for(book: Book) -> list[Chunk]:
    """Chunks for one book, with the demo pipeline's chunker and a chunk_id of
    the shape `note#index.section/n`: the id is the retrieval dedupe key and the
    ordering key inside a chapter, so it must stay unique and parseable
    (`rsplit("/", 1)` gives the position within the section).

    The section's ordinal is part of the id because the section TITLE alone is
    not a unique name: an untitled preamble is written as "full", and a book may
    well contain a section actually titled "full" — the two would then share
    every chunk id, and each would drop the other's chunks out of the retrieval
    results. No sentinel string fixes that, since any sentinel could itself be a
    heading; the ordinal cannot repeat."""
    chunks: list[Chunk] = []
    for section, (title, text) in enumerate(book.sections, 1):
        for i, packed in enumerate(pack_sentences(split_sentences(text)), 1):
            chunks.append(Chunk(
                chunk_id=f"{book.note}#{section}.{title or 'full'}/{i}",
                note=book.note,
                book=book.book,
                source=book.source,
                section=title,
                text=packed,
            ))
    ids = [c.chunk_id for c in chunks]
    if len(set(ids)) != len(ids):      # invariant guard: the ordinal makes this unreachable
        duplicates = sorted({i for i in ids if ids.count(i) > 1})[:3]
        raise IngestError(f"{book.path.name}: duplicate chunk ids, e.g. {duplicates}")
    return chunks


# --- writing the index ------------------------------------------------------

def refuse_model_mismatch(db, table: str, embedder) -> None:
    """One table, one embedding model. Adding bge-m3 rows to a table built by
    another model degrades retrieval silently whenever the dims happen to
    match, so the mismatch is fatal here, before anything is written.

    Unlike the readers (`library`, `preflight`), which tolerate a table built
    before fingerprints existed, `ayl-add` requires a full fingerprint match:
    an unstamped table would let a partial write mix two embedding models and
    then stamp the whole table with the model that wrote only some of it."""
    if table not in table_names(db):
        return
    problem = check_index(db, table, embedder.model, embedder.dims)
    if problem:
        raise IngestError(
            f"refusing to write {table}: {problem}\n"
            f"Point LIBRARY_DB_PATH at a different database, or rebuild this one "
            f"with the matching model.")
    meta = read_index_meta(db, table)
    if meta is None:
        raise IngestError(
            f"refusing to write {table}: it has no embedding fingerprint, so the model "
            f"that built it is unknown — the dims match {embedder.model!r}, but so would "
            f"another model of the same size, and mixing two models in one table degrades "
            f"retrieval silently.\n"
            f"Stamp the existing table if you know it was built with {embedder.model!r} "
            f"(`uv run scripts/ingest_demo_corpus.py --stage stamp-meta`), or rebuild the "
            f"index, or point LIBRARY_DB_PATH at a different database.")
    if int(meta["dims"]) != int(embedder.dims):
        raise IngestError(
            f"refusing to write {table}: it is stamped {meta['dims']} dims, configured "
            f"embedder {embedder.model!r} produces {embedder.dims} — rebuild the index.")


def kept_rows(db, table_name: str, replaced: set[str], batch_rows: int = COPY_BATCH_ROWS):
    """The existing rows this run does NOT replace, as Arrow record batches.

    Streamed rather than materialized: reading the live table with `to_arrow()`
    would hold the entire index in memory for the length of the run, so adding
    one small book to a large library would cost as much memory as rebuilding
    it. One batch at a time is held instead, and the rows are handed straight
    to the staging table.

    Arrow rather than row dicts so the staging table is created with the live
    table's own schema — the vector column is a fixed-size list, and inferring
    that again from Python floats is not guaranteed to reproduce it."""
    for batch in table_batches(db.open_table(table_name), batch_rows):
        if not replaced:
            yield batch
            continue
        keep = pa.array([note not in replaced for note in batch.column("note").to_pylist()])
        kept = batch.filter(keep)
        if kept.num_rows:               # a batch of nothing but replaced books
            yield kept


def add_books(books: list[Book], backend: str, db_path: Path) -> dict:
    embedder = get_embedder(backend)
    db = lancedb.connect(db_path)
    table_name = f"transcripts_{backend}"
    recover_staging(db, table_name)
    refuse_model_mismatch(db, table_name, embedder)

    counts = {"books": 0, "sections": 0, "chunks": 0, "merged_headings": 0}
    existing = table_name in table_names(db)
    replaced = {book.note for book in books}

    def batches():
        # Update = merged rebuild, not delete-then-add on the live table: the
        # books that stay, then the books of this run. The old table is only
        # dropped once the staging table holds every row, so an embedder that
        # dies on book 7 leaves the index exactly as it was (FTS index and
        # fingerprint included) instead of a half-updated table.
        if existing:
            yield from kept_rows(db, table_name, replaced)
        for i, book in enumerate(books, 1):
            chunks = chunks_for(book)
            if not chunks:
                # Defensive: split_book_chapters currently guarantees at least
                # one non-empty section, so a book always chunks to something.
                # If a future chunker stops guaranteeing it, skip the book —
                # never embed an empty batch, never blank the table.
                log.warning("%s: produced no text chunks, skipped", book.path.name)
                continue
            vectors = embedder.embed_docs([embedding_text(c) for c in chunks])
            counts["books"] += 1
            counts["sections"] += len(book.sections)
            counts["chunks"] += len(chunks)
            counts["merged_headings"] += len(book.merged_headings)
            say(f"  [{i}/{len(books)}] {book.book}: {len(book.sections)} sections, "
                f"{len(chunks)} chunks")
            yield rows_for(chunks, vectors)

    try:
        rebuild_table(db, table_name, batches())
    except NoRowsError as error:
        # Every file in the folder chunked to nothing. rebuild_table left the
        # live table alone; report it as the one-line user error the CLI
        # promises instead of letting a bare ValueError reach the terminal.
        raise IngestError(
            f"nothing to index: none of the {len(books)} files produced any text chunks "
            f"— the index was left unchanged") from error
    build_fts_index(db, table_name)
    write_index_meta(db, table_name, backend, embedder.model, embedder.dims)
    counts["table"] = table_name
    counts["model"] = embedder.model
    counts["dims"] = embedder.dims
    counts["cards_table"] = f"cards_{backend}" in table_names(db)
    return counts


def merged_headings_line(count: int) -> str:
    """The one-line report of the contents lines that did not open a section.
    Nothing was lost — their text is in the section above them — but the section
    list does not show them, so the count says so explicitly."""
    return (f"{count} short heading{'' if count == 1 else 's'} merged into their "
            f"preceding section (table-of-contents lines: the same heading appears "
            f"later in the file)")


def dry_run(books: list[Book], backend: str, db_path: Path) -> int:
    sections = chunks = merged = 0
    for book in books:
        book_chunks = chunks_for(book)
        sections += len(book.sections)
        chunks += len(book_chunks)
        merged += len(book.merged_headings)
        say(f"  {book.book}  ({book.path.name})")
        for title, _ in book.sections:
            say(f"      - {title or '(untitled)'}")
        say(f"      {len(book_chunks)} chunks")
    say(f"\nwould index {len(books)} books, {sections} sections, {chunks} chunks "
        f"into transcripts_{backend} at {db_path} (nothing written, nothing embedded)")
    if merged:
        say(merged_headings_line(merged))
    return 0


# --- entry point ------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(
        prog="ayl-add",
        description="Index a folder of .txt / .md books into the Ask Your Library LanceDB.")
    parser.add_argument("folder", type=Path, help="folder of .txt / .md files (searched recursively)")
    parser.add_argument("--backend", default=EMBED_BACKEND, choices=("ollama", "openrouter"),
                        help="embedding backend; also selects the table suffix")
    parser.add_argument("--db", type=Path, default=None,
                        help=f"LanceDB directory (default: LIBRARY_DB_PATH, now {DB_PATH})")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the books, sections and chunk counts; embed and write nothing")
    parser.add_argument("--cards", action="store_true",
                        help="not implemented (see the message it prints)")
    args = parser.parse_args(argv)

    if args.cards:
        say("--cards is not implemented: book cards are LLM-distilled summaries, which "
            "means paid model calls per book. The demo corpus ships its cards in "
            "corpus/cards/ and indexes them with "
            "`uv run scripts/ingest_demo_corpus.py --stage cards`; there is no generic "
            "card generator yet. Run ayl-add without --cards for a full-text-only index.",
            error=True)
        return 2

    folder = args.folder.expanduser()
    if not folder.is_dir():
        say(f"not a folder: {folder}", error=True)
        return 2
    db_path = (args.db.expanduser() if args.db else DB_PATH)

    try:
        books = read_folder(folder)
        if args.dry_run:
            return dry_run(books, args.backend, db_path)
        say(f"embedding {len(books)} books with {args.backend} into {db_path} ...")
        counts = add_books(books, args.backend, db_path)
    except IngestError as error:              # one readable line, not a traceback
        say(str(error), error=True)
        return 1

    say(f"\nadded {counts['books']} books, {counts['sections']} sections, "
        f"{counts['chunks']} chunks")
    if counts["merged_headings"]:
        say(merged_headings_line(counts["merged_headings"]))
    say(f"table {counts['table']} in {db_path}; embedding model {counts['model']} "
        f"({counts['dims']} dims), FTS index rebuilt")
    if not counts["cards_table"]:
        say(f"no cards_{args.backend} table here: the agent will search full text only "
            f"(book cards need an LLM and are not generated by ayl-add)")
    say(f"ask it something:  LIBRARY_DB_PATH={db_path} uv run ask-library \"...\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
