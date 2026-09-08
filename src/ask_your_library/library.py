"""Library access: hybrid search over the LanceDB tables and chapter drill-down.

Search is hybrid — vector (embedding) + full-text BM25 (LanceDB FTS index) —
fused with Reciprocal Rank Fusion. RRF is implemented here rather than via
LanceDB's built-in rerankers so the fusion logic stays transparent: only the
rank of a chunk in each list matters, never the raw distance / BM25 score, so
the two scales need no calibration against each other.
"""
import logging

import lancedb
from lancedb.expr import col, lit

from .config import DB_PATH, EMBED_BACKEND, TABLES
from .embeddings import get_embedder
from .index_meta import check_index

log = logging.getLogger(__name__)

CANDIDATES_PER_LIST = 20  # candidates taken from each search before fusion
RRF_K = 60                # standard RRF constant

_embedder = None
_checked_tables: set[str] = set()
_reported_missing: set[str] = set()


def embedder():
    global _embedder
    if _embedder is None:
        _embedder = get_embedder(EMBED_BACKEND)
    return _embedder


def embed_query(text: str) -> list[float]:
    return embedder().embed_query(text)


def has_table(db, table_name: str) -> bool:
    """A corpus may legitimately be absent: `ayl-add` builds the transcripts
    table only, because book cards are LLM-distilled and cost money. Search
    then runs over the corpora that exist — but logs it, once per process, so a
    corpus lost to a broken ingest never passes for "nothing relevant found".
    That log is for the operator; the user is told by the preflight notice
    (`preflight.check_environment().notices`), which the interfaces show."""
    if table_name in db.table_names():
        return True
    if table_name not in _reported_missing:
        _reported_missing.add(table_name)
        log.warning("%s: no table %s in this index — searching the other corpus only",
                    DB_PATH, table_name)
    return False


def open_table(db, table_name: str):
    """Open a table, refusing (once per process) an index built by a different
    embedding model than the configured one."""
    if table_name not in _checked_tables:
        problem = check_index(db, table_name, embedder().model, embedder().dims)
        if problem:
            raise RuntimeError(problem)
        _checked_tables.add(table_name)
    return db.open_table(table_name)


def hit_key(hit: dict) -> tuple:
    """Dedupe key: the same chunk arrives from both the vector and the BM25 list."""
    if hit.get("chunk_id"):
        return ("chunk_id", hit["chunk_id"])
    return (hit["book"], hit["section"], hit["text"][:80])


def rrf_fuse(vector_hits: list[dict], fts_hits: list[dict], k: int) -> list[dict]:
    """Reciprocal Rank Fusion: score(chunk) = sum over lists of 1 / (RRF_K + rank)."""
    scores: dict[tuple, float] = {}
    best_hits: dict[tuple, dict] = {}   # first occurrence supplies the fields

    for hits_list in (vector_hits, fts_hits):
        for rank, hit in enumerate(hits_list, 1):
            key = hit_key(hit)
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
            best_hits.setdefault(key, hit)

    ranked_keys = sorted(scores, key=lambda key: scores[key], reverse=True)

    fused = []
    for key in ranked_keys[:k]:
        hit = dict(best_hits[key])
        hit["_rrf_score"] = scores[key]
        fused.append(hit)
    return fused


def search(corpus: str, query: str, k: int = 4, book: str | None = None) -> list[dict]:
    """Hybrid top-k search over one corpus ("cards" | "transcripts").

    `book` (an index key, "Title — Author") constrains both lists to that book:
    after a resolved clarify, retrieval is limited to the chosen book, not just
    the evidence (ADR-013); the coverage probe uses it to look inside one
    candidate. Returns flat hits: corpus, book, section, text, score (RRF) and,
    for hits that came through the vector list, distance.
    """
    db = lancedb.connect(DB_PATH)
    if not has_table(db, TABLES[corpus]):
        return []
    table = open_table(db, TABLES[corpus])
    # The one ordering difference from before: the query is embedded before the
    # book filter string is built (inside _search_corpus). Only the error path
    # notices: a non-string `book` now fails after the embedding call, not before.
    return _search_corpus(table, corpus, query, embed_query(query), k, book)


def _search_corpus(table, corpus: str, query: str, vector: list[float],
                   k: int, book: str | None) -> list[dict]:
    """One corpus, on a table the caller has already opened and a query it has
    already embedded — so `search_both` pays for the connection and the
    embedding once for both corpora instead of twice per agent step. Everything
    below is what `search` always did."""
    where = f"book = '{_sql_quote(book)}'" if book else None

    vector_query = table.search(vector)
    if where:
        vector_query = vector_query.where(where)
    vector_hits = vector_query.limit(CANDIDATES_PER_LIST).to_list()

    try:
        fts_query = table.search(query, query_type="fts")
        if where:
            fts_query = fts_query.where(where)
        fts_hits = fts_query.limit(CANDIDATES_PER_LIST).to_list()
    except Exception as error:  # LanceDB raises backend-specific types for a missing index
        # Degrade to vector-only rather than fail, but never silently: a broken
        # index would otherwise look like "slightly worse retrieval".
        log.warning("FTS search failed on %s (%s: %s) — vector-only results",
                    TABLES[corpus], type(error).__name__, error)
        fts_hits = []

    fused = rrf_fuse(vector_hits, fts_hits, k)

    hits = []
    for h in fused:
        hit = {
            "corpus": corpus,
            "book": h["book"],
            "section": h["section"],
            "text": h["text"],
            "score": round(h["_rrf_score"], 4),
        }
        if "_distance" in h:
            hit["distance"] = round(h["_distance"], 4)
        hits.append(hit)
    return hits


def search_both(query: str, k: int = 4, book: str | None = None) -> list[dict]:
    """Cards + transcripts in one call (no per-corpus routing yet).

    Two `search` calls embedded the query twice and opened LanceDB twice on
    every agent step; the corpora are asked on one connection, with one
    embedding, in the same order and for the same hits. The query is still
    embedded last, after the tables are found and their index fingerprints
    checked, so a missing corpus (or a whole missing index) costs no embedding.
    """
    db = lancedb.connect(DB_PATH)
    tables = [(corpus, open_table(db, TABLES[corpus]))
              for corpus in ("cards", "transcripts") if has_table(db, TABLES[corpus])]
    if not tables:
        return []
    vector = embed_query(query)
    hits: list[dict] = []
    for corpus, table in tables:
        hits += _search_corpus(table, corpus, query, vector, k, book)
    return hits


def _sql_quote(value: str) -> str:
    """Escape a value for the string `where` clauses that remain (search's book
    filter). The chapter filters below use LanceDB's expression builder
    (`lancedb.expr`), which takes values as literals instead — see
    `_chapter_candidates`."""
    return value.replace("'", "''")


TITLE_SEPARATOR = " — "   # index key for a book is "Title — Author"; reflect may hand back only the title

# Cap on a chapter query. With the book in the `where` clause it is no longer
# the boundary that decides WHICH book is found — the query returns the chunks
# of one section of one book (of the handful sharing a bare title), not the
# first N rows of every book that happens to have a section with this name.
# It can still truncate a single section: "chapter" holds for chaptered books,
# but an unstructured book indexed as one "Full text" section is thousands of
# chunks (a 1.4M-character book at ~1,400 characters per chunk), and the scan
# order under a filter is not guaranteed, so a hit at the cap is logged: the
# read still reports "found" and `join_chapter`'s "characters not shown"
# undercounts what was left in the database.
CHAPTER_ROW_CAP = 1000


def title_of(book_key: str) -> str:
    """'Moby Dick' for the index key 'Moby Dick — Herman Melville'."""
    return book_key.rsplit(TITLE_SEPARATOR, 1)[0].strip()


def rows_for_book(rows: list[dict], book: str) -> list[dict]:
    """Rows whose book key equals `book`, or whose title part equals it when the
    caller passed a bare title ("Don Quixote" for "Don Quixote — Miguel de
    Cervantes"). Title-only matching is exact, never a prefix: "Emma" must not
    match "Emma's Diary"."""
    exact = [r for r in rows if r["book"] == book]
    if exact:
        return exact
    # rsplit: the author is the last part, a title may itself contain the separator
    return [r for r in rows if r["book"].rsplit(TITLE_SEPARATOR, 1)[0] == book]


def join_chapter(rows: list[dict], max_chars: int) -> str:
    """Chunks in chapter order, at most max_chars including an in-band marker
    that tells the model when the chapter was cut, so "not in the text I read"
    is not mistaken for "not in the chapter"."""
    def chunk_number(row: dict) -> int:
        # chunk_id ends with "/N" — the chunk's position within the chapter
        try:
            return int(row["chunk_id"].rsplit("/", 1)[1])
        except (IndexError, ValueError):
            return 0

    text = "\n[...]\n".join(row["text"] for row in sorted(rows, key=chunk_number))
    if len(text) <= max_chars:
        return text
    # The marker lives INSIDE the max_chars budget, so every later cut at the
    # same limit (scratchpad, observe) still shows it.
    marker = f"\n[chapter continues: {len(text) - max_chars} characters not shown]"
    body = text[:max(0, max_chars - len(marker))]
    return body + marker


CUT_MARKER_SUFFIX = "characters not shown]"


def chapter_is_cut(text: str) -> bool:
    """True when join_chapter had to cut the chapter (read status "partial")."""
    return text.rstrip().endswith(CUT_MARKER_SUFFIX)


def read_chapter(book: str, section: str, max_chars: int = 12000) -> tuple[str, str, str]:
    """Drill-down: the full text of one chapter, i.e. all transcript chunks with
    this (book, section) joined in order, and the index key of the book the
    rows actually belong to. Neighbouring chunks overlap by design; the overlap
    is left in place because trimming it would cut sentences.

    The caller may pass a bare title ("Don Quixote"); the returned key is the
    canonical one ("Don Quixote — Miguel de Cervantes") so a chapter hit carries
    the same book identity as search hits and the clarify choice. The third
    value is the resolution: "found", "missing" (no such chapter) or
    "ambiguous" (a bare title matches chapters of two different books, two
    authors with the same title: refused rather than resolved by row order;
    text and key are then empty).
    """
    db = lancedb.connect(DB_PATH)
    if not has_table(db, TABLES["transcripts"]):
        return "", "", "missing"    # the caller unpacks three values
    table = open_table(db, TABLES["transcripts"])

    # Section naming differs between books ("Chapter 59" vs "59"): try both forms.
    variants = [section]
    if section.lower().startswith("chapter "):
        variants.append(section[8:])
    else:
        variants.append(f"Chapter {section}")
    rows: list[dict] = []
    for variant in variants:
        candidates, candidates_cut = _chapter_candidates(table, book, variant)
        if candidates_cut:
            # The bare-title query came back at the cap: other books sharing the
            # title may have been cut out of the candidates, so "one book" is not
            # a fact here. Refused like a known two-author title, never resolved
            # by whatever the cap happened to keep.
            return "", "", "ambiguous"
        rows = rows_for_book(candidates, book)
        if rows:
            break
    return chapter_of(rows, max_chars)


def _chapter_candidates(table, book: str, section: str) -> tuple[list[dict], bool]:
    """Rows of one section whose book can still be `book`, narrowed in SQL, and
    whether the bare-title fallback query was cut at the row cap (then the
    candidate set is incomplete and the caller must not pick a book from it).

    Two queries at most, because the caller may pass either an index key or a
    bare title, and a bare title cannot be matched by SQL alone:

    1. the exact key ("Don Quixote — Miguel de Cervantes"), which is what a
       search hit and a resolved clarify carry;
    2. only when that finds nothing: every book whose key CONTAINS
       "<book> — ", which covers the bare title reflect may hand back ("Don
       Quixote"; before it was resolved at all, c05 in the 05.09 core run read
       0 characters and still marked the chapter read). The separator is not a
       reliable test for "this is a bare title" — a title may itself contain it
       ("Title — Subtitle — Author") — so the exact query decides, and this one
       is the fallback either way.

    The narrowing is deliberately wider than the answer: `contains` is a
    substring test, so it is a superset of the prefix match, and `rows_for_book`
    still confirms the book exactly in Python (title-only matching stays exact:
    "Emma" must not match "Emma's Diary"). LanceDB 0.37 has no `starts_with` /
    `like` in its expression builder (`func("starts_with", ...)` raises "unknown
    function"), and `contains` matches literally — "%" and "_" in a title are
    not wildcards — so nothing needs escaping.

    Before this, the filter was on the section only, with `.limit(1000)`, and
    the book was resolved in Python afterwards: fine for 33 books, wrong for a
    large library, where the cap truncates the candidates before the book is
    known and the right chapter can fall outside it.

    The expressions are pushed down as expressions (LanceDB's `where_expr`),
    not as SQL this code renders: values travel as literals, so nothing is
    interpolated and nothing needs escaping. `Expr.to_sql()` is a lossy
    debugging rendering only and must never be fed back into `.where()` — for a
    title containing a backslash before a quote it emits SQL LanceDB itself
    refuses to parse.
    """
    section_is = col("section") == lit(section)
    exact, _ = _capped(table, section_is & (col("book") == lit(book)), book, section, fallback=False)
    if exact:
        return exact, False
    return _capped(table, section_is & col("book").contains(book + TITLE_SEPARATOR),
                   book, section, fallback=True)


def _capped(table, condition, book: str, section: str, fallback: bool) -> tuple[list[dict], bool]:
    """One filtered scan, cut at CHAPTER_ROW_CAP, and whether the cut may have
    happened. Said out loud either way, because nothing downstream can tell:
    on the exact-key query a cut means the section is longer than what was read
    (the read still says "found" and the cut marker counts only what was
    joined); on the bare-title fallback it means candidate BOOKS may have been
    cut out, which the caller turns into an "ambiguous" refusal."""
    rows = table.search().where(condition).limit(CHAPTER_ROW_CAP).to_list()
    cut = len(rows) >= CHAPTER_ROW_CAP
    if cut and fallback:
        log.warning("bare-title chapter query hit the %d-row cap (title %r, section %r): other books "
                    "sharing this title may have been cut out of the candidates; refused as ambiguous",
                    CHAPTER_ROW_CAP, book, section)
    elif cut:
        log.warning("chapter query hit the %d-row cap (book %r, section %r): "
                    "the section may be longer than what was read",
                    CHAPTER_ROW_CAP, book, section)
    return rows, cut


def chapter_of(rows: list[dict], max_chars: int) -> tuple[str, str, str]:
    """(text, canonical book key, resolution) for the rows of one chapter:
    ("", "", "missing") when there are none, ("", "", "ambiguous") when they
    span more than one book."""
    books = {r["book"] for r in rows}
    if not books:
        return "", "", "missing"
    if len(books) > 1:
        return "", "", "ambiguous"
    return join_chapter(rows, max_chars), books.pop(), "found"


def get_chapter(book: str, section: str, max_chars: int = 12000) -> str:
    """Text only; see read_chapter."""
    return read_chapter(book, section, max_chars)[0]
