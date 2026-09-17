"""Embedding-index fingerprint: which model built a table, and with what dims.

Tables are named per backend (cards_ollama, ...), but the model behind a
backend is configurable. Reusing an index built by another model fails late
(different dims) or, worse, silently degrades retrieval (same dims). Ingest
stamps every table it builds; readers check the stamp before searching.
"""
import logging
import time

# The staged publish this module needs is the ingest's, and `ingest.publish`
# imports nothing from the package, so this direction costs no cycle.
from .ingest.publish import rebuild_table, recover_staging

log = logging.getLogger(__name__)

META_TABLE = "_index_meta"


def _table_names(db) -> list[str]:
    names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    return list(getattr(names, "tables", names))


# The shape of an index row: bumped when a reader can no longer read a table
# written by an older ingest without knowing which one wrote it. 1 is every
# index built before the ledger; 2 adds the `book_id` column beside `note`.
SCHEMA_VERSION = 2


def write_index_meta(db, table: str, backend: str, model: str, dims: int,
                     chunker: str | None = None,
                     schema_version: int = SCHEMA_VERSION) -> None:
    """Stamp a table with what built it.

    `chunker` and `schema_version` are written here from 2026-09-17 (ADR-024).
    Readers must tolerate their absence — every index built before this has no
    such fields — and nothing refuses on them yet: the policy decided for that
    is warn on read, refuse on write (ADR-020's note, #27), and refusing before
    the warning exists would invalidate a half-hour build over a field that has
    never once been written."""
    recover_staging(db, META_TABLE)
    row = {"table": table, "backend": backend, "model": model, "dims": int(dims),
           "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "chunker": chunker or "", "schema_version": int(schema_version)}
    if META_TABLE in _table_names(db):
        meta = db.open_table(META_TABLE)
        meta.delete(f"`table` = '{table}'")
        try:
            meta.add([row])
        except Exception:
            # A `_index_meta` written before these two fields existed has a
            # five-column schema, and LanceDB will not take a wider row. The
            # table is tiny (one row per index table) and carries no vectors,
            # so it is rewritten with the wider schema rather than dropping the
            # new fields — which would make the stamp lie about itself.
            #
            # Through the staging table, not drop-then-create: this table is
            # what every reader checks before it opens an index, and a crash
            # between the drop and the create would leave an index that looks
            # unstamped — which `ayl-add` REFUSES to write to. `recover_staging`
            # above closes that window on the next open, the same way it does
            # for the index tables themselves.
            log.info("%s: widening the fingerprint table with chunker/schema_version",
                     META_TABLE)
            kept = [_with_new_fields(r) for r in _all_meta_rows(db) if r.get("table") != table]
            rebuild_table(db, META_TABLE, [kept + [row]])
    else:
        db.create_table(META_TABLE, [row])


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
    # A widening that was interrupted leaves the staged copy behind; finishing
    # it here means a reader never sees a stamped index as unstamped.
    recover_staging(db, META_TABLE)
    if META_TABLE not in _table_names(db):
        return None
    rows = db.open_table(META_TABLE).search().where(f"`table` = '{table}'").limit(1).to_list()
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
