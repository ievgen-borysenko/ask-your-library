"""The `books` ledger: which books were requested, which are indexed, and why
the rest are not.

The index tables answer "what can be searched". They cannot answer "what did I
ask for", "did this file fail", or "is this the same book I indexed last month
under a different author spelling" — because the row key is `slug("Title —
Author")`, a digest of a DERIVED string. Correct the author and the key
changes: the delete matches nothing, the old rows stay, and the library holds
the book twice (ADR-015's recorded consequence, ADR-024's decision).

So identity is minted, not derived. `book_id` is an opaque token assigned the
first time a book is seen and never recomputed from title, author, path or
content; everything else in the row may change under it.

    resolve(...) -> book_id      the id for this book, minting one if it is new
    begin(book_id)               status `requested`: a write is about to start
    commit(book_id, rows=...)    status `indexed`, with what was written
    fail(book_id, error)         status `failed`, with the reason
    missing()                    requested but never indexed — an interrupted run
    diff(folder)                 files present vs ledger rows, both directions

Two writes per book that must agree is the cost ADR-024 accepted: a ledger that
says `indexed` for rows that are not in the index is a new failure mode, which
is why it is reconciled explicitly (`doctor.check_ledger`) instead of trusted.

The catalogue does NOT read this table. "N of N books, by the index tables"
(ADR-016) is exhaustive because it counts the rows that can actually be
searched; counting ledger rows instead would make it a history of ingests.
"""
import logging
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from ..bookkey import author_of, book_key, title_of
# The chunker version is the chunking module's own name for what it produces,
# re-exported here because a ledger row records it and half the tree imports it
# from the ledger. Defined in one place only: see `chunking.CHUNKER_VERSION`.
from .chunking import CHUNKER_VERSION  # noqa: F401

log = logging.getLogger(__name__)

TABLE = "books"

# What a backfill writes: "indexed before anything recorded which chunker did
# it". Not a version — it is the ledger's word for the absence of one, and
# nothing compares it to `CHUNKER_VERSION` expecting a match.
LEGACY_CHUNKER = "legacy"

REQUESTED, INDEXED, FAILED = "requested", "indexed", "failed"

# Every column, in the order the table is created with. LanceDB infers the
# schema from the first row, so a row missing a field would fix a narrower
# schema for the life of the table: `_row()` fills all of them, always.
FIELDS = ("book_id", "key", "title", "author", "source_ref", "sha256", "chunker",
          "embedding_model", "status", "error", "requested_at", "indexed_at", "rows",
          "fts_seconds")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _table_names(db) -> list[str]:
    names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    return list(getattr(names, "tables", names))


def _quote(value: str) -> str:
    return value.replace("'", "''")


def _parse_local_ref(ref: str) -> tuple[str, str] | None:
    """(folder tag, path inside it) of a `local:<tag>:<path>` reference.

    None for any other shape — `manifest:` from the demo corpus, `note:` from a
    backfill, or a `local:` reference written before the folder tag existed.
    None means "this folder says nothing about that row", which is what keeps
    `--prune` from deleting a book it has no evidence about."""
    if not ref.startswith("local:"):
        return None
    parts = ref.split(":", 2)
    return (parts[1], parts[2]) if len(parts) == 3 else None


def _row(**values) -> dict:
    row = {name: "" for name in FIELDS}
    row["rows"] = 0
    row["fts_seconds"] = 0.0
    row.update({k: v for k, v in values.items() if v is not None})
    unknown = set(row) - set(FIELDS)
    if unknown:                      # a typo would otherwise widen the schema
        raise ValueError(f"unknown ledger fields: {sorted(unknown)}")
    return row


@dataclass(frozen=True)
class FolderDiff:
    """What `diff(folder)` found, as three lists rather than a printed report:
    the caller decides whether a vanished book is news, a warning or a delete."""
    new: list[Path]               # files with no ledger row
    known: list[tuple[Path, str]] # (file, book_id) — a row already covers it
    vanished: list[dict]          # ledger rows whose source file is gone


class Ledger:
    """The ledger of one index (one LanceDB directory).

    Constructed against an open `db`, not a path, so it lives inside whatever
    connection the ingest already has and cannot open a second one against a
    different directory by accident."""

    def __init__(self, db, table_name: str = TABLE):
        self.db = db
        self.table_name = table_name

    # --- the table ---------------------------------------------------------

    def exists(self) -> bool:
        return self.table_name in _table_names(self.db)

    def _table(self):
        return self.db.open_table(self.table_name)

    def _create(self, rows: list[dict]):
        return self.db.create_table(self.table_name, rows)

    def all_rows(self) -> list[dict]:
        if not self.exists():
            return []
        table = self._table()
        return table.search().limit(max(table.count_rows(), 1)).to_list()

    def get(self, book_id: str) -> dict | None:
        if not self.exists():
            return None
        rows = self._table().search().where(
            f"book_id = '{_quote(book_id)}'").limit(1).to_list()
        return rows[0] if rows else None

    def _put(self, row: dict) -> None:
        """One row per `book_id`: replace, never append. Not transactional, and
        it does not need to be — a crash between the delete and the add loses a
        ledger row for a book whose rows are either all there or not there at
        all, and `doctor.check_ledger` sees exactly that."""
        if not self.exists():
            self._create([row])
            return
        table = self._table()
        table.delete(f"book_id = '{_quote(row['book_id'])}'")
        table.add([row])

    # --- identity ----------------------------------------------------------

    def resolve(self, title: str, author: str = "", sha256: str = "",
                source_ref: str = "", claimed: frozenset[str] | set[str] = frozenset()) -> str:
        """The `book_id` for this book: an existing row's id when this is a book
        the ledger already holds, a newly minted one otherwise.

        Two rules adopt an existing id, and their order is the whole design.

        **The key.** `Title — Author` is what the reader sees and what the agent
        cites, so a book that still answers to its key is that book, whatever
        happened to its text: a re-export, a re-chunk, a corrected typo in the
        body all keep the id.

        **The source.** Failing that, the file at the same place in the same
        folder is the same book whose metadata was corrected — which is the case
        the derived row key could never express, and the reason this issue
        exists. `source_ref` carries a digest of the folder beside the path
        inside it, so two libraries that happen to share a relative path are not
        each other.

        **The digest adopts nothing.** A sha256 match alone is *reported and not
        acted on*: a byte-identical copy of a book under another title, in
        another folder, would otherwise take over the first book's id and its
        next write would delete the first book's rows — a loss the staged
        rebuild this replaced could not produce. The reviewer's rule, kept
        exactly: a digest may adopt an id only where the key or the source
        already matched, and in both those cases a rule above has returned. So
        the digest's job here is to say "you have this text already, under
        another name", which is information, not a decision. It is still
        recorded on the row, where `--doctor` reads it.

        `claimed` is the ids this run has already handed out, and it narrows
        both adopting rules: within one run two files are two books, never one
        of them twice."""
        key = book_key(title, author)
        rows = self.all_rows()
        for row in rows:
            if row.get("key") == key:
                return row["book_id"]
        if source_ref:
            for row in rows:
                if row.get("source_ref") == source_ref and row["book_id"] not in claimed:
                    log.info("%s: the file %s already holds %r — either the same book with "
                             "its metadata corrected, or the file at this path now holds a "
                             "different book; either way it keeps the slot's id %s",
                             key, source_ref, row.get("key"), row["book_id"])
                    return row["book_id"]
        if sha256:
            twin = next((row for row in rows
                         if row.get("sha256") == sha256 and row["book_id"] not in claimed), None)
            if twin:
                log.warning("%s: the same text is already indexed as %r (%s). Indexing it as a "
                            "SECOND book: a book is replaced only when its key or its file "
                            "matches, never on content alone.",
                            key, twin.get("key"), twin.get("source_ref") or "no source recorded")
        book_id = uuid.uuid4().hex
        self._put(_row(book_id=book_id, key=key, title=title_of(key), author=author_of(key),
                       sha256=sha256, source_ref=source_ref, status=REQUESTED,
                       requested_at=_now()))
        return book_id

    # --- the write, before and after ---------------------------------------

    def begin(self, book_id: str, *, key: str = "", source_ref: str = "", sha256: str = "",
              chunker: str = CHUNKER_VERSION, embedding_model: str = "") -> dict:
        """Mark a book as being written. A row in `requested` with no rows in
        the index is what `missing()` reports and what the recovery pass at the
        start of the next run acts on."""
        existing = self.get(book_id) or {}
        row = _row(book_id=book_id,
                   key=key or existing.get("key", ""),
                   title=title_of(key or existing.get("key", "")),
                   author=author_of(key or existing.get("key", "")),
                   source_ref=source_ref or existing.get("source_ref", ""),
                   sha256=sha256 or existing.get("sha256", ""),
                   chunker=chunker, embedding_model=embedding_model,
                   status=REQUESTED, error="", requested_at=_now(),
                   indexed_at=existing.get("indexed_at", ""),
                   rows=int(existing.get("rows", 0) or 0))
        self._put(row)
        return row

    def commit(self, book_id: str, rows: int = 0, fts_seconds: float = 0.0, **fields) -> dict:
        """Mark a book as indexed, with the number of rows written.

        `fts_seconds` is the FTS rebuild this write paid for. It is recorded
        rather than acted on: the backlog asked for the whole-index rebuild to
        be MEASURED before anyone makes it incremental (#33), and the ledger is
        where a number per run survives the run."""
        existing = self.get(book_id)
        if existing is None:
            raise KeyError(f"no ledger row for {book_id}")
        row = _row(**{**{k: existing.get(k) for k in FIELDS},
                      **fields,
                      "book_id": book_id, "status": INDEXED, "error": "",
                      "rows": int(rows), "fts_seconds": float(fts_seconds),
                      "indexed_at": _now()})
        self._put(row)
        return row

    def fail(self, book_id: str, error: str) -> dict:
        existing = self.get(book_id)
        if existing is None:
            raise KeyError(f"no ledger row for {book_id}")
        row = _row(**{**{k: existing.get(k) for k in FIELDS},
                      "book_id": book_id, "status": FAILED,
                      # One line, and bounded: this is an exception's text, and
                      # it is printed by `doctor` and read in a terminal.
                      "error": " ".join(str(error).split())[:500]})
        self._put(row)
        return row

    # --- questions ---------------------------------------------------------

    def missing(self) -> list[dict]:
        """Books that were requested and never reached `indexed` — an
        interrupted run, or a file that failed. Sorted by key so two runs over
        the same index report in the same order."""
        return sorted((row for row in self.all_rows() if row.get("status") != INDEXED),
                      key=lambda row: (row.get("key") or "", row.get("book_id") or ""))

    def by_key(self) -> dict[str, dict]:
        return {row["key"]: row for row in self.all_rows() if row.get("key")}

    def diff(self, folder: Path, files: Iterable[Path] | None = None,
             key_of=None, scope: str = "", path_of=None) -> FolderDiff:
        """What this folder holds against what the ledger holds.

        `files`, `key_of` and `path_of` are injected by the caller (`ayl-add`
        passes its own file discovery, its own key rules and its own source
        references) so this module does not have to know how a folder becomes
        books — and so the diff is computed from exactly the files the ingest
        would read, never a second, subtly different listing.

        A file is "known" when its KEY has a ledger row, or when its SOURCE
        REFERENCE has one: a book that moved inside the folder is the same book,
        and so is a book whose author was corrected in place.

        A row is "vanished" when it belongs to THIS folder and names a file that
        is no longer there. `scope` is the caller's folder tag, and it is what
        keeps a second library out of the answer: without it every book of every
        other folder in the same index reads as vanished here — and `--prune`
        would then delete them. Rows written by another ingest path (the demo
        corpus's `manifest:`, a backfill's `note:`) are never vanished either,
        for the same reason: this folder is no evidence about them."""
        if files is None or key_of is None:
            raise ValueError("diff needs the caller's file list and key rule")
        folder = Path(folder)
        rows_by_key = self.by_key()
        rows_by_source = {row["source_ref"]: row for row in self.all_rows()
                          if row.get("source_ref")}
        new: list[Path] = []
        known: list[tuple[Path, str]] = []
        seen_ids: set[str] = set()
        for path in files:
            key = key_of(path)
            row = rows_by_key.get(key) if key else None
            if row is None and path_of is not None:
                row = rows_by_source.get(path_of(path))
            if row:
                known.append((path, row["book_id"]))
                seen_ids.add(row["book_id"])
            else:
                new.append(path)
        vanished = []
        for row in self.all_rows():
            if row["book_id"] in seen_ids:
                continue
            parsed = _parse_local_ref(row.get("source_ref") or "")
            if parsed is None:
                continue                    # not from a folder: the demo corpus
            row_scope, relative = parsed
            if scope and row_scope != scope:
                continue                    # another folder's book, not this one's
            if not (folder / relative).exists():
                vanished.append(row)
        vanished.sort(key=lambda row: row.get("key") or "")
        return FolderDiff(new=sorted(new), known=sorted(known), vanished=vanished)

    def delete(self, book_id: str) -> None:
        if self.exists():
            self._table().delete(f"book_id = '{_quote(book_id)}'")

    # --- the upgrade -------------------------------------------------------

    def backfill(self, index_rows: Iterable[dict], embedding_model: str = "") -> int:
        """One ledger row per distinct book key already in the index.

        An index built before the ledger existed knows its books only as rows.
        Those books really are indexed, so they are written as `indexed` — but
        with `chunker=legacy`, because nothing recorded which chunker made
        them, and `source_ref` empty, because nothing recorded where they came
        from. The id is minted here, which is the point at which those books
        acquire an identity that survives a corrected author.

        Idempotent: a key that already has a row is left exactly as it is.
        Returns the number of rows written."""
        existing = set(self.by_key())
        seen: dict[str, str] = {}
        for row in index_rows:
            key = row.get("book")
            note = row.get("note") or ""
            if key and key not in existing:
                seen.setdefault(key, note)
        written = []
        for key, note in sorted(seen.items()):
            written.append(_row(book_id=uuid.uuid4().hex, key=key, title=title_of(key),
                                author=author_of(key),
                                # The row key the book's chunks already carry —
                                # the only provenance an old index kept.
                                source_ref=f"note:{note}" if note else "",
                                chunker=LEGACY_CHUNKER, embedding_model=embedding_model,
                                status=INDEXED, requested_at=_now(), indexed_at=_now()))
        if not written:
            return 0
        if self.exists():
            self._table().add(written)
        else:
            self._create(written)
        log.info("books ledger: backfilled %d book%s from the index (chunker=%s)",
                 len(written), "" if len(written) == 1 else "s", LEGACY_CHUNKER)
        return len(written)


def open_ledger(db, table_name: str = TABLE) -> Ledger:
    return Ledger(db, table_name)


def backfill_from_index(db, table_names: Iterable[str], embedding_model: str = "",
                        ledger_table: str = TABLE) -> int:
    """Backfill the ledger from the index tables of this database, once.

    Called on the first open of an index that has no ledger. Reads only the two
    metadata columns, so the cost is a projection over the rows and not the
    vectors."""
    ledger = open_ledger(db, ledger_table)
    present = _table_names(db)
    rows: list[dict] = []
    for name in table_names:
        if name not in present:
            continue
        table = db.open_table(name)
        count = table.count_rows()
        if not count:
            continue
        rows += table.search().select(["book", "note"]).limit(count).to_list()
    return ledger.backfill(rows, embedding_model=embedding_model)
