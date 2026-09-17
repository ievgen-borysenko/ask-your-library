"""Crash-safe publishing of LanceDB tables.

LanceDB OSS has no rename, so a rebuild goes through a staging table: build
`<name>__staging` completely, then drop the old table and copy staging over.
The only crash window (old dropped, new not yet created) is closed by
`recover_staging`, which the ingest calls before every stage.
"""
import logging
from collections.abc import Iterable
from typing import Any

import pyarrow as pa

log = logging.getLogger(__name__)

STAGING_SUFFIX = "__staging"

# Rows per Arrow batch when a whole table is read or copied. Big enough that
# the per-batch overhead is noise, small enough that peak memory is a function
# of the batch, not of the index.
COPY_BATCH_ROWS = 2000


class NoRowsError(ValueError):
    """A rebuild whose batches yielded no rows at all — nothing was written.

    A ValueError subclass so callers that predate it keep catching it, and a
    named type so a caller can turn it into its own one-line user message
    instead of a traceback."""


def table_names(db) -> list[str]:
    names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    return list(getattr(names, "tables", names))


def table_batches(table, batch_rows: int = COPY_BATCH_ROWS):
    """Every row of `table`, streamed as Arrow record batches in the table's
    own schema (the vector column stays a fixed-size list).

    `to_arrow()` would materialize the whole table instead, which makes the
    memory cost of any rebuild a function of the index size."""
    return table.search(None).limit(None).to_batches(batch_rows)


def copy_table(db, source: str, target: str, batch_rows: int = COPY_BATCH_ROWS):
    """Create `target` holding every row of `source`, streamed batch by batch.

    LanceDB OSS has no rename, so publishing a staged build is a copy; doing it
    through a RecordBatchReader keeps one batch in memory rather than the whole
    table, and carries the source schema over exactly."""
    table = db.open_table(source)
    reader = pa.RecordBatchReader.from_batches(table.schema,
                                               table_batches(table, batch_rows))
    return db.create_table(target, reader)


def recover_staging(db, name: str) -> None:
    """Finish or discard an interrupted rebuild of `name`."""
    staging = name + STAGING_SUFFIX
    names = table_names(db)
    if staging not in names:
        return
    if name in names:
        # Old table still there: the staging build did not finish — start over.
        db.drop_table(staging)
        log.warning("dropped stale %s (interrupted rebuild)", staging)
        return
    # Old table gone, staging complete: promote it.
    copy_table(db, staging, name)
    db.drop_table(staging)
    log.warning("promoted %s to %s (recovered interrupted swap)", staging, name)


def rebuild_table(db, name: str, batches: Iterable[Any]):
    """Staged, recoverable replacement of `name`: the old table stays queryable
    until the staging build has fully succeeded. Not atomic — the drop/create
    window is closed by recover_staging() on the next run, not by the store.

    A batch is anything LanceDB accepts as data — a list of row dicts, or an
    Arrow table or record batch (which `ayl-add` uses to carry existing rows
    over with the live table's own schema). The first batch defines the staging
    schema. Raises NoRowsError when the batches produced nothing, leaving the
    old table in place."""
    staging = name + STAGING_SUFFIX
    if staging in table_names(db):
        db.drop_table(staging)
    table = None
    try:
        for rows in batches:
            if not rows:
                continue
            if table is None:
                table = db.create_table(staging, rows)
            else:
                table.add(rows)
    except Exception:
        if staging in table_names(db):
            db.drop_table(staging)
        raise
    if table is None:
        raise NoRowsError(f"no rows produced for {name}")

    if name in table_names(db):
        db.drop_table(name)
    published = copy_table(db, staging, name)
    db.drop_table(staging)
    return published


def upsert_book_rows(table, note: str, rows: list[dict]) -> None:
    """Replace one book's rows (matched by `note`) so a re-ingest of a single
    book never duplicates chunks. delete -> add is not transactional: a crash
    in between leaves the book missing until the next ingest."""
    table.delete(f"note = '{note.replace(chr(39), chr(39) * 2)}'")
    if rows:
        table.add(rows)


# --- the per-book path ------------------------------------------------------

BOOK_ID_COLUMN = "book_id"


def has_book_id(table) -> bool:
    return BOOK_ID_COLUMN in table.schema.names


def add_book_id_column(db, name: str, book_id_of, batch_rows: int = COPY_BATCH_ROWS):
    """Give an existing table a `book_id` column, without re-embedding anything.

    An index built before the ledger has rows keyed by `note` alone, and a
    per-book update keyed by `book_id` cannot touch them. The column is filled
    from the ledger through `book_id_of(note)`; a row whose `note` the ledger
    does not know gets "", which `doctor` then reports rather than the ingest
    guessing.

    A staged rebuild, so the live table stays queryable and an interrupted run
    is finished or discarded by `recover_staging` like any other. The vectors
    are carried over as Arrow batches in the table's own schema — the fixed-size
    list stays a fixed-size list, and no row is re-read through Python floats."""
    table = db.open_table(name)
    if has_book_id(table):
        return table

    def batches():
        for batch in table_batches(table, batch_rows):
            ids = [book_id_of(note) or "" for note in batch.column("note").to_pylist()]
            yield batch.append_column(BOOK_ID_COLUMN, pa.array(ids, pa.string()))

    log.info("%s: adding a %s column (%d rows, no re-embedding)",
             name, BOOK_ID_COLUMN, table.count_rows())
    return rebuild_table(db, name, batches())


def replace_book_rows(table, book_id: str, note: str, rows: list[dict]) -> None:
    """Replace one book's rows in the live table: delete, then append.

    Matched on `book_id` OR `note`, and both are needed. `book_id` is what
    survives a corrected author — the rows written under the old key carry the
    same id, and only this clause removes them. `note` is what a row written
    before the column existed has, and what a row whose ledger entry was lost
    has: without it a re-add of such a book would append a second copy of every
    chunk under the same chunk ids.

    Not transactional — a crash between the delete and the add leaves the book
    out of the index, with its ledger row still `requested`, which is exactly
    what the recovery pass looks for."""
    quoted_id = book_id.replace("'", "''")
    quoted_note = note.replace("'", "''")
    if has_book_id(table):
        table.delete(f"{BOOK_ID_COLUMN} = '{quoted_id}' OR note = '{quoted_note}'")
    else:
        table.delete(f"note = '{quoted_note}'")
    if rows:
        table.add(rows)


def rows_of_book(table, book_id: str) -> int:
    """How many rows the index holds for a book id (0 when the column is not
    there yet, which is the pre-ledger state, not an empty book)."""
    if not has_book_id(table):
        return 0
    return table.count_rows(f"{BOOK_ID_COLUMN} = '{book_id.replace(chr(39), chr(39) * 2)}'")
