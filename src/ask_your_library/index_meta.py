"""Embedding-index fingerprint: which model built a table, and with what dims.

Tables are named per backend (cards_ollama, ...), but the model behind a
backend is configurable. Reusing an index built by another model fails late
(different dims) or, worse, silently degrades retrieval (same dims). Ingest
stamps every table it builds; readers check the stamp before searching.
"""
import logging
import time

log = logging.getLogger(__name__)

META_TABLE = "_index_meta"


def _table_names(db) -> list[str]:
    names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    return list(getattr(names, "tables", names))


def write_index_meta(db, table: str, backend: str, model: str, dims: int) -> None:
    row = {"table": table, "backend": backend, "model": model, "dims": int(dims),
           "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if META_TABLE in _table_names(db):
        meta = db.open_table(META_TABLE)
        meta.delete(f"`table` = '{table}'")
        meta.add([row])
    else:
        db.create_table(META_TABLE, [row])


def read_index_meta(db, table: str) -> dict | None:
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
