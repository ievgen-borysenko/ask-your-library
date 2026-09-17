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
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import lancedb

from ..bookkey import (MAX_TITLE_LINE, UNKNOWN_AUTHOR, book_key, slug,
                       split_title_author)
from ..config import DB_PATH, EMBED_BACKEND
from ..embeddings import get_embedder
from ..index_meta import check_index, read_index_meta, write_index_meta
from ..sanitize import LINE_BREAK_RE, strip_control_chars
from .chapters import MergedHeading, split_book_sections
from .chunking import Chunk, embedding_text, pack_sentences, parse_frontmatter, rows_for, \
    split_sentences
from .fts import build_fts_index
from .ledger import (CHUNKER_VERSION, REQUESTED, Ledger, backfill_from_index,
                     open_ledger)
from .publish import NoRowsError, add_book_id_column, rebuild_table, recover_staging, \
    replace_book_rows, rows_of_book, table_names

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
# `book_key`, `split_title_author` and `slug` live in `ask_your_library.bookkey`
# with the rest of book identity; what stays here is where a key is FOUND in a
# file — front matter, a first title line, the file name.


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


def sha256_of(path: Path) -> str:
    """Digest of the source file as it is on disk.

    The ledger matches on it when the book key changed (a corrected author),
    which is the case that used to index a second book. Streamed, because a
    library holds files of a few megabytes and there is no reason to hold one
    in memory to hash it. Unreadable is "" — never a hash of nothing, which
    would make every unreadable file the same book."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
    except OSError as error:
        log.warning("%s: could not be digested (%s); the ledger will match on the key alone",
                    path.name, error)
        return ""
    return digest.hexdigest()


def open_book_ledger(db, backend: str, embedder) -> Ledger:
    """The ledger of this index, backfilled on first sight of an older one.

    An index built before the ledger existed knows its books only as rows, and
    a per-book update keyed by a minted id cannot touch rows that have no id.
    So the first run over such an index mints one per distinct book key and
    records it as `indexed` with `chunker=legacy` — what is true of it, and no
    more."""
    ledger = open_ledger(db)
    if ledger.exists():
        return ledger
    names = table_names(db)
    present = [name for name in (f"transcripts_{backend}", f"cards_{backend}") if name in names]
    if present:
        backfill_from_index(db, present, embedding_model=embedder.model)
    return ledger


def recover_interrupted(db, table_name: str, ledger: Ledger, about_to_write: set[str]) -> list[str]:
    """The recovery pass at the start of a run: every ledger row that says a
    book was requested and never confirmed indexed.

    Two shapes, told apart by whether the index holds the book's rows.

    *Rows present* — the crash fell between the append and the ledger's second
    write. One book is one `table.add()`, and LanceDB commits an append as a
    unit, so rows present mean the whole book is there; the ledger is corrected
    to say so.

    *No rows* — the crash fell between the delete and the append, which is the
    window the per-book path opens and the reason this ledger exists. The book
    is re-ingested when this run covers it, and reported by key when it does
    not: nothing else in the index can tell the user that a book they added
    last week is silently absent.

    Returns the lines to report."""
    report: list[str] = []
    if table_name not in table_names(db):
        return report
    table = db.open_table(table_name)
    for row in ledger.missing():
        key, book_id = row.get("key") or "(no key)", row["book_id"]
        present = rows_of_book(table, book_id)
        if present and row.get("status") == REQUESTED:
            ledger.commit(book_id, rows=present)
            report.append(f"recovered {key}: its {present} rows are in the index, "
                          f"the ledger now says so")
        elif present:
            # `failed`, with rows: the index holds an EARLIER version of this
            # book. Never silently promoted to `indexed` — that would call
            # stale content current, which is the one thing a ledger is for.
            report.append(f"failed {key}: {row.get('error') or 'no reason recorded'} — the "
                          f"rows in the index are from an earlier run")
        elif key in about_to_write:
            report.append(f"re-indexing {key}: an earlier run did not finish it")
        else:
            source = row.get("source_ref") or "an unrecorded source"
            report.append(f"MISSING {key}: requested from {source}, never indexed — "
                          f"run ayl-add over that folder again to finish it")
    return report


def folder_diff(db_path: Path, backend: str, books: list[Book], folder: Path):
    """The ledger's view of this folder: which books are new, which it already
    has, and which of its rows name a file that is no longer there.

    Returns None when there is no index yet — `lancedb.connect` CREATES the
    directory it is given, and `--dry-run` must not leave one behind."""
    if not Path(db_path).exists():
        return None
    db = lancedb.connect(db_path)
    ledger = open_ledger(db)
    if not ledger.exists():
        return None
    by_path = {book.path: book.book for book in books}
    return ledger.diff(folder, files=list(by_path), key_of=by_path.get)


def add_books(books: list[Book], backend: str, db_path: Path, folder: Path | None = None,
              prune: bool = False) -> dict:
    """Index these books, one book at a time, keyed by the ledger's `book_id`.

    Not a whole-table rebuild any more (ADR-015's "an update is a staged
    rebuild with a single publish" is partly superseded by ADR-024). A run that
    adds one book to a library of three hundred now deletes and appends that
    book's rows, instead of copying every row of the index through a staging
    table twice. What is still whole is the BM25 index, which LanceDB drops with
    the table it belongs to and which has no incremental merge here: its
    seconds are measured and written into the ledger rows of the run, because
    the backlog asked for a measurement before anyone makes it incremental
    (#33).

    The crash window moved rather than closed: between the delete and the
    append one book is absent from the index, with a ledger row that says
    `requested`. That is what `recover_interrupted` looks for on the next run —
    and it is why the ledger comes before incrementality, not after it."""
    embedder = get_embedder(backend)
    db = lancedb.connect(db_path)
    table_name = f"transcripts_{backend}"
    recover_staging(db, table_name)
    refuse_model_mismatch(db, table_name, embedder)
    ledger = open_book_ledger(db, backend, embedder)

    counts = {"books": 0, "sections": 0, "chunks": 0, "merged_headings": 0,
              "recovered": [], "vanished": [], "pruned": 0}
    counts["recovered"] = recover_interrupted(db, table_name, ledger,
                                              {book.book for book in books})
    for line in counts["recovered"]:
        say(f"  {line}")

    existing = table_name in table_names(db)
    # Resolved for the whole run before anything is written, and each id is
    # taken out of circulation as it is handed out: two files with identical
    # bytes are two books, not one of them renamed.
    ids: dict[str, str] = {}
    for book in books:
        ids[book.note] = ledger.resolve(
            book.book, "", sha256=sha256_of(book.path),
            source_ref=f"local:{relative_name(book, folder)}",
            claimed=set(ids.values()))

    def prepare(book: Book) -> tuple[str, list[dict]] | None:
        """One book, embedded, as rows ready to write. None when it chunked to
        nothing — never an empty batch, never a blanked book."""
        book_id = ids[book.note]
        chunks = chunks_for(book)
        if not chunks:
            # Defensive: split_book_sections currently guarantees at least one
            # non-empty section, so a book always chunks to something. If a
            # future chunker stops guaranteeing it, skip the book.
            log.warning("%s: produced no text chunks, skipped", book.path.name)
            ledger.fail(book_id, "produced no text chunks")
            return None
        ledger.begin(book_id, key=book.book,
                     source_ref=f"local:{relative_name(book, folder)}",
                     sha256=sha256_of(book.path), embedding_model=embedder.model)
        try:
            vectors = embedder.embed_docs([embedding_text(c) for c in chunks])
        except Exception as error:
            # The ledger says `failed`, with the reason, and the book keeps
            # whatever rows it already had: the next run reports the pair
            # instead of promoting stale rows to current.
            ledger.fail(book_id, f"{type(error).__name__}: {error}")
            raise
        counts["books"] += 1
        counts["sections"] += len(book.sections)
        counts["chunks"] += len(chunks)
        counts["merged_headings"] += len(book.merged_headings)
        return book_id, rows_for(chunks, vectors, book_id)

    written: list[tuple[str, int]] = []
    if existing:
        # The per-book path. The column has to be there before a delete can be
        # keyed on it; filling it is a staged rebuild that re-embeds nothing.
        add_book_id_column(db, table_name, _book_id_by_note(ledger))
        table = db.open_table(table_name)
        for i, book in enumerate(books, 1):
            prepared = prepare(book)
            if prepared is None:
                continue
            book_id, rows = prepared
            say(f"  [{i}/{len(books)}] {book.book}: {len(book.sections)} sections, "
                f"{len(rows)} chunks")
            replace_book_rows(table, book_id, book.note, rows)
            written.append((book_id, len(rows)))
    else:
        # No table yet: one staged publish for the whole folder is both cheaper
        # and safer than creating a table and appending to it book by book.
        def batches():
            for i, book in enumerate(books, 1):
                prepared = prepare(book)
                if prepared is None:
                    continue
                book_id, rows = prepared
                say(f"  [{i}/{len(books)}] {book.book}: {len(book.sections)} sections, "
                    f"{len(rows)} chunks")
                written.append((book_id, len(rows)))
                yield rows

        try:
            rebuild_table(db, table_name, batches())
        except NoRowsError as error:
            raise IngestError(
                f"nothing to index: none of the {len(books)} files produced any text chunks "
                f"— the index was left unchanged") from error

    fts_seconds = build_fts_index(db, table_name)
    write_index_meta(db, table_name, backend, embedder.model, embedder.dims,
                     chunker=CHUNKER_VERSION)
    # After the FTS rebuild, so a crash during it leaves the books `requested`
    # and the next run's recovery pass sees rows and confirms them.
    for book_id, rows in written:
        ledger.commit(book_id, rows=rows, fts_seconds=fts_seconds)

    if folder is not None:
        counts["vanished"] = [row for row in folder_vanished(ledger, folder, books)]
        if prune and counts["vanished"]:
            counts["pruned"] = prune_books(db, table_name, ledger, counts["vanished"])
            fts_seconds = build_fts_index(db, table_name)

    counts["table"] = table_name
    counts["model"] = embedder.model
    counts["dims"] = embedder.dims
    counts["fts_seconds"] = fts_seconds
    counts["cards_table"] = f"cards_{backend}" in table_names(db)
    return counts


def relative_name(book: Book, folder: Path | None) -> str:
    """What the ledger records as the book's file: the path inside the folder,
    never an absolute one — the same rule the `source` column already follows,
    so a ledger read out loud names nothing about this machine."""
    if folder is None:
        return book.path.name
    try:
        return str(book.path.relative_to(folder))
    except ValueError:
        return book.path.name


def _book_id_by_note(ledger: Ledger):
    """`note` -> `book_id` for the column migration. A backfilled row carries
    the row key its chunks were written under (`note:<slug>`); a row written by
    a later run carries its file instead, and is found by re-deriving the slug
    from its key."""
    by_note: dict[str, str] = {}
    for row in ledger.all_rows():
        ref = row.get("source_ref") or ""
        if ref.startswith("note:"):
            by_note.setdefault(ref[len("note:"):], row["book_id"])
        key = row.get("key")
        if key:
            by_note.setdefault(slug(key), row["book_id"])
    return by_note.get


def folder_vanished(ledger: Ledger, folder: Path, books: list[Book]) -> list[dict]:
    by_path = {book.path: book.book for book in books}
    return ledger.diff(folder, files=list(by_path), key_of=by_path.get).vanished


def prune_books(db, table_name: str, ledger: Ledger, rows: list[dict]) -> int:
    """Delete the rows of books whose file is gone, and their ledger rows.

    Only ever under `--prune`. A folder that failed to mount, a file being
    edited in place, a partial sync — all of them look exactly like a deletion,
    and the difference between reporting and deleting is the difference between
    a warning and a lost book."""
    table = db.open_table(table_name)
    for row in rows:
        replace_book_rows(table, row["book_id"], slug(row.get("key") or ""), [])
        ledger.delete(row["book_id"])
        say(f"  pruned {row.get('key')}: its file is no longer in the folder")
    return len(rows)


def merged_headings_line(count: int) -> str:
    """The one-line report of the contents lines that did not open a section.
    Nothing was lost — their text is in the section above them — but the section
    list does not show them, so the count says so explicitly."""
    return (f"{count} short heading{'' if count == 1 else 's'} merged into their "
            f"preceding section (table-of-contents lines: the same heading appears "
            f"later in the file)")


def dry_run(books: list[Book], backend: str, db_path: Path, folder: Path | None = None) -> int:
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
    if folder is not None:
        print_diff(folder_diff(db_path, backend, books, folder), db_path)
    return 0


def print_diff(diff, db_path: Path) -> None:
    """What the run would change, against the ledger: the half of `--dry-run`
    that needs an index to answer. Without one every book is new, and saying so
    is more use than printing three empty lists."""
    if diff is None:
        say(f"\nno book ledger at {db_path} yet — every book above is new")
        return
    say(f"\nagainst the ledger at {db_path}:")
    say(f"  {len(diff.new)} new, {len(diff.known)} already indexed "
        f"(their rows would be replaced)")
    for path in diff.new:
        say(f"      new       {path.name}")
    for path, _ in diff.known:
        say(f"      replaces  {path.name}")
    for row in diff.vanished:
        say(f"      VANISHED  {row.get('key')} ({row.get('source_ref')}) — still in the "
            f"index; --prune removes it")


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
                        help="print the books, sections and chunk counts and the diff against "
                             "the book ledger; embed and write nothing")
    parser.add_argument("--prune", action="store_true",
                        help="also DELETE the rows of books whose file is no longer in the "
                             "folder (without it they are reported and kept)")
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
            return dry_run(books, args.backend, db_path, folder)
        say(f"embedding {len(books)} books with {args.backend} into {db_path} ...")
        counts = add_books(books, args.backend, db_path, folder, prune=args.prune)
    except IngestError as error:              # one readable line, not a traceback
        say(str(error), error=True)
        return 1

    say(f"\nadded {counts['books']} books, {counts['sections']} sections, "
        f"{counts['chunks']} chunks")
    if counts["merged_headings"]:
        say(merged_headings_line(counts["merged_headings"]))
    say(f"table {counts['table']} in {db_path}; embedding model {counts['model']} "
        f"({counts['dims']} dims), FTS index rebuilt in {counts['fts_seconds']:.1f}s "
        f"(whole, every run)")
    for row in counts["vanished"]:
        say(f"still in the index, but no longer in the folder: {row.get('key')} "
            f"({row.get('source_ref')}) — re-run with --prune to delete its rows")
    if counts["pruned"]:
        say(f"pruned {counts['pruned']} book(s) whose file is gone")
    if not counts["cards_table"]:
        say(f"no cards_{args.backend} table here: the agent will search full text only "
            f"(book cards need an LLM and are not generated by ayl-add)")
    say(f"ask it something:  LIBRARY_DB_PATH={db_path} uv run ask-library \"...\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
