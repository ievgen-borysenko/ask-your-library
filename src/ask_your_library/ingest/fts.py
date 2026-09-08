"""BM25 full-text index for hybrid retrieval.

LanceDB drops the FTS index together with the table, so it must be rebuilt
after every re-ingest of that table.
"""
import logging
import time

log = logging.getLogger(__name__)


def build_fts_index(db, name: str) -> None:
    if name not in db.table_names():
        log.warning("table %s does not exist — skipping FTS", name)
        return
    table = db.open_table(name)
    started = time.time()
    # Native FTS (no tantivy): BM25 over the text column.
    table.create_fts_index("text", use_tantivy=False, replace=True)
    log.info("%s: FTS index ready (%d rows, %.1fs)", name, table.count_rows(), time.time() - started)
