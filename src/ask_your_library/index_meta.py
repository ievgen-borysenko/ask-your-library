"""Embedding-index fingerprint: which model built a table, and with what dims.

Tables are named per backend (cards_ollama, ...), but the model behind a
backend is configurable. Reusing an index built by another model fails late
(different dims) or, worse, silently degrades retrieval (same dims). Ingest
stamps every table it builds; readers check the stamp before searching.
"""
import logging
import time

# The staged publish this module needs is the ingest's, and `ingest.publish`
# imports nothing from the package, so this direction costs no cycle. Only
# `write_index_meta` uses the recovery half: see the note in `read_index_meta`.
from .ingest.publish import (LEDGER_COLUMNS, STAGING_SUFFIX, rebuild_table,
                             recover_staging)

log = logging.getLogger(__name__)

META_TABLE = "_index_meta"


def _table_names(db) -> list[str]:
    names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    return list(getattr(names, "tables", names))


# The shape of an index row: bumped when a reader can no longer read a table
# written by an older ingest without knowing which one wrote it. 1 is every
# index built before the ledger, and the cards table, which never gains the
# ledger columns; 2 adds `book_id` and `book_rev` beside `note`.
SCHEMA_VERSION = 2
SCHEMA_VERSION_LEGACY = 1

# The two fields ADR-024 added to the fingerprint row itself.
NEW_FIELDS = ("chunker", "schema_version")


def write_index_meta(db, table: str, backend: str, model: str, dims: int,
                     chunker: str | None = None,
                     schema_version: int | None = None) -> None:
    """Stamp a table with what built it.

    `chunker` and `schema_version` are written here from 2026-09-17 (ADR-024).
    Readers must tolerate their absence — every index built before this has no
    such fields — and nothing refuses on them yet: the policy decided for that
    is warn on read, refuse on write (ADR-020's note, #27), and refusing before
    the warning exists would invalidate a half-hour build over a field that has
    never once been written.

    `schema_version` is DERIVED from the table being stamped unless the caller
    names one. A version is a claim about the rows, and a stamp that claims
    what the rows do not have is worse than no stamp: a legacy transcripts
    table that an ingest has not yet migrated, and the cards table, which
    carries no ledger columns by design, are both version 1 and are stamped as
    such (see `schema_version_of`)."""
    recover_staging(db, META_TABLE)
    if schema_version is None:
        schema_version = schema_version_of(db, table)
    row = {"table": table, "backend": backend, "model": model, "dims": int(dims),
           "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "chunker": chunker or "", "schema_version": int(schema_version)}
    if META_TABLE not in _table_names(db):
        db.create_table(META_TABLE, [row])
        return

    meta = db.open_table(META_TABLE)
    if all(name in meta.schema.names for name in NEW_FIELDS):
        meta.delete(f"`table` = '{table}'")
        meta.add([row])
        return

    # A `_index_meta` written before these two fields existed has a five-column
    # schema, and LanceDB will not take a wider row. The table is tiny (one row
    # per index table) and carries no vectors, so it is rewritten with the wider
    # schema rather than dropping the new fields — which would make the stamp
    # lie about itself.
    #
    # The width is read from the schema rather than discovered by attempting the
    # narrow write, and the snapshot is taken before anything is touched, so the
    # live table is not mutated at all until a COMPLETE replacement exists.
    # `rebuild_table` builds staging in full, then drops and copies: a failure
    # while staging is being built leaves the live table exactly as it was, and
    # a crash in the drop/copy window is finished by `recover_staging` on the
    # next write. This table is what every reader checks before opening an
    # index, and an index that looks unstamped is one `ayl-add` refuses to
    # write to — so the order matters more here than the code length suggests.
    log.info("%s: widening the fingerprint table with chunker/schema_version", META_TABLE)
    snapshot = [_with_new_fields(r) for r in _all_meta_rows(db) if r.get("table") != table]
    rebuild_table(db, META_TABLE, [snapshot + [row]])


def schema_version_of(db, table: str) -> int:
    """The row shape of `table`, as its own columns report it.

    2 — rows carry the ledger's `book_id` and `book_rev` beside `note`.
    1 — they do not: an index built before the ledger and not yet migrated, or
        the cards table, whose rows will never carry them (a card is a
        distillate of a book, and the ledger's unit is the book; `ayl-add` does
        not write that table at all).

    A table that is not there yet is 1: nothing has been written, and claiming
    the newer shape for rows that do not exist is the mistake this replaces."""
    if table not in _table_names(db):
        return SCHEMA_VERSION_LEGACY
    try:
        names = db.open_table(table).schema.names
    except Exception:                      # a table being rebuilt underneath us
        return SCHEMA_VERSION_LEGACY
    return SCHEMA_VERSION if all(column in names for column in LEDGER_COLUMNS) \
        else SCHEMA_VERSION_LEGACY


def _all_meta_rows(db) -> list[dict]:
    table = db.open_table(META_TABLE)
    count = table.count_rows() if hasattr(table, "count_rows") else 0
    return table.search().limit(max(count, 1)).to_list()


def _with_new_fields(row: dict) -> dict:
    """An old fingerprint row, carried into the wider schema. Empty and 1, not
    a guess: nothing recorded which chunker wrote that table, and saying
    "legacy" is the ledger's word for the same absence."""
    return {"table": row.get("table", ""), "backend": row.get("backend", ""),
            "model": row.get("model", ""), "dims": int(row.get("dims", 0) or 0),
            "created": row.get("created", ""),
            "chunker": row.get("chunker", "") or "", "schema_version": int(row.get("schema_version", 1) or 1)}


def read_index_meta(db, table: str) -> dict | None:
    """The fingerprint row for `table`, or None.

    A reader NEVER recovers. It tolerates an interrupted widening instead: the
    live table if it is there, the staged copy read-only if it is not. Recovery
    is a write — it drops or promotes a table — and every search goes through
    here (`library.open_table`), as does the preflight of every interface. A
    reader that recovered would race the `ayl-add` that is mid-widening, could
    drop the staging table the writer is still filling, and would leave the
    index unstamped: exactly the state `ayl-add` then refuses to write to. It
    would also break the rule `doctor` is held to — a check does not rewrite
    what it checks.

    So recovery belongs to the write path, and is done there: at the start of
    every ingest run and inside `write_index_meta`."""
    names = _table_names(db)
    if META_TABLE in names:
        source = META_TABLE
    elif META_TABLE + STAGING_SUFFIX in names:
        # Mid-widening, or a crash during one. The staged copy is complete by
        # construction (it is built before the live table is dropped), so it is
        # the honest answer — and reading it is better than reporting an index
        # with no fingerprint, which is what the caller would act on.
        source = META_TABLE + STAGING_SUFFIX
        log.info("%s is being rebuilt; reading %s instead (the next ingest finishes it)",
                 META_TABLE, source)
    else:
        return None
    rows = db.open_table(source).search().where(f"`table` = '{table}'").limit(1).to_list()
    return rows[0] if rows else None


def vector_dims(table) -> int | None:
    try:
        return table.schema.field("vector").type.list_size
    except Exception:
        return None


def check_index(db, table_name: str, model: str, dims: int) -> str | None:
    """Return a human-readable problem if `table_name` was not built by
    (model, dims); None when it matches. A table without a stamp (built before
    fingerprints existed) is checked on dims alone and logged, not rejected."""
    table = db.open_table(table_name)
    actual_dims = vector_dims(table)
    if actual_dims is not None and actual_dims != dims:
        return (f"{table_name}: vectors have {actual_dims} dims, configured embedder "
                f"{model!r} produces {dims} — rebuild the index or switch EMBED_BACKEND/model")
    meta = read_index_meta(db, table_name)
    if meta is None:
        log.info("%s has no embedding fingerprint (built before stamps existed); "
                 "dims match, proceeding", table_name)
        return None
    if meta["model"] != model:
        return (f"{table_name} was built with {meta['model']!r}, configured embedder is "
                f"{model!r} — rebuild the index or set the matching embedding model")
    return None
