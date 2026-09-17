"""BM25 full-text index for hybrid retrieval.

LanceDB drops the FTS index together with the table, so it must be rebuilt
after every re-ingest of that table.
"""
import logging
import time

log = logging.getLogger(__name__)


def build_fts_index(db, name: str) -> float:
    """Rebuild the BM25 index over `name`, and return the seconds it took.

    Whole, every time: LanceDB drops the FTS index together with the table it
    belongs to, and there is no incremental merge on this path. The seconds are
    RETURNED rather than only logged because `ayl-add` writes them into the
    ledger rows of the run — the backlog asks for this cost to be measured on a
    real library before anyone replaces it, and a number that exists only in a
    log line is a number nobody has (#33)."""
    if name not in db.table_names():
        log.warning("table %s does not exist — skipping FTS", name)
        return 0.0
    table = db.open_table(name)
    started = time.time()
    # Native FTS (no tantivy): BM25 over the text column.
    table.create_fts_index("text", use_tantivy=False, replace=True)
    seconds = time.time() - started
    log.info("%s: FTS index ready (%d rows, %.1fs)", name, table.count_rows(), seconds)
    return seconds
