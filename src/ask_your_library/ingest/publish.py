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
