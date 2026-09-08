"""library.py: the chapter tests run against a real LanceDB table; the search-cost
tests at the end use fakes on purpose, because they count calls, not results.

The chapter tests build a small on-disk index in tmp_path and wrap its table in a
recorder. The weight is carried by the results: LanceDB itself decides what a
filter means, so `contains` behaves the way it will in production, not the way
a mock imagines. The assertions on the recorded clauses are a rendering
snapshot on top of that — how many queries ran, and roughly what went into
them; `Expr.to_sql()` is a lossy debugging rendering, not the expression that
was pushed down, so they check for fragments rather than exact SQL.
"""
import logging

import lancedb
import pytest

from ask_your_library import library

CHAPTER = "Chapter 1"


class RecordingQuery:
    def __init__(self, query, clauses):
        self._query, self._clauses = query, clauses

    def where(self, condition):
        # `condition` is a lancedb.expr.Expr for the chapter filters; the
        # expression itself goes to LanceDB, to_sql() only to the record.
        self._clauses.append(condition.to_sql() if hasattr(condition, "to_sql") else condition)
        return RecordingQuery(self._query.where(condition), self._clauses)

    def limit(self, n):
        return RecordingQuery(self._query.limit(n), self._clauses)

    def to_list(self):
        return self._query.to_list()


class RecordingTable:
    """The real table, with every `where` clause recorded as SQL."""

    def __init__(self, table):
        self._table = table
        self.clauses: list[str] = []

    def search(self, *args, **kwargs):
        return RecordingQuery(self._table.search(*args, **kwargs), self.clauses)


@pytest.fixture
def transcripts(tmp_path, monkeypatch):
    """Build a transcripts table from rows and point library.read_chapter at it."""
    def build(rows):
        db = lancedb.connect(str(tmp_path / "db"))
        table = RecordingTable(db.create_table("transcripts", rows))
        monkeypatch.setattr(library, "lancedb",
                            type("L", (), {"connect": staticmethod(lambda path: object())})())
        monkeypatch.setattr(library, "has_table", lambda db, name: True)
        monkeypatch.setattr(library, "open_table", lambda db, name: table)
        return table
    return build


def chunk(book, section=CHAPTER, text="text", n=1):
    return {"book": book, "section": section, "text": text, "chunk_id": f"{book}/{section}/{n}"}


# ---------------------------------------------------------------- the book is in the where clause

def test_an_index_key_is_asked_for_in_sql_and_needs_no_fallback(transcripts):
    """A search hit and a resolved clarify carry the full key: one query, with
    the book in it — no scan of every book that has a "Chapter 1"."""
    table = transcripts([chunk("Don Quixote — Miguel de Cervantes", text="windmills"),
                         chunk("Emma — Jane Austen", text="Highbury")])

    assert library.read_chapter("Don Quixote — Miguel de Cervantes", CHAPTER) == (
        "windmills", "Don Quixote — Miguel de Cervantes", "found")
    assert len(table.clauses) == 1      # the exact key hit: no fallback query
    assert "section = 'Chapter 1'" in table.clauses[0]
    assert "book = 'Don Quixote — Miguel de Cervantes'" in table.clauses[0]


def test_a_bare_title_falls_back_to_a_narrowed_book_query(transcripts):
    """reflect may hand back "Don Quixote"; no key equals that, so the second
    query narrows on the book too ("Don Quixote — ..."), never on the section
    alone, and rows_for_book confirms the title part exactly."""
    table = transcripts([chunk("Don Quixote — Miguel de Cervantes", text="windmills"),
                         chunk("Emma — Jane Austen", text="Highbury")])

    assert library.read_chapter("Don Quixote", CHAPTER) == (
        "windmills", "Don Quixote — Miguel de Cervantes", "found")
    assert len(table.clauses) == 2
    assert "book = 'Don Quixote'" in table.clauses[0]
    assert "contains(book, 'Don Quixote — ')" in table.clauses[1]
    assert all("section = 'Chapter 1'" in clause for clause in table.clauses)


def test_a_bare_title_never_matches_a_longer_title(transcripts):
    """The SQL narrowing is a substring test (LanceDB 0.37 has no starts_with /
    like), so Python still decides: "Emma" is not "Emma's Diary"."""
    transcripts([chunk("Emma's Diary — Nobody", text="diary")])

    assert library.read_chapter("Emma", CHAPTER) == ("", "", "missing")


def test_a_title_that_contains_the_separator_still_resolves(transcripts):
    """"Title — Subtitle" looks like a full key but is a bare title here, so the
    fallback must run whenever the exact query finds nothing — the separator is
    not a test for "the caller passed a key"."""
    table = transcripts([chunk("Title — Subtitle — Author", text="body"),
                         chunk("Title — Other", text="other")])

    assert library.read_chapter("Title — Subtitle", CHAPTER) == (
        "body", "Title — Subtitle — Author", "found")
    assert "contains(book, 'Title — Subtitle — ')" in table.clauses[-1]


def test_wildcard_characters_in_a_title_are_not_wildcards(transcripts):
    """A LIKE prefix ('50% — %') would also match "50 percent off — B"; the
    expression builder's contains() takes the value literally, so "%" and "_"
    in a title match themselves."""
    transcripts([chunk("50% — Author A", text="percent"),
                 chunk("50 percent off — Author B", text="spelled out"),
                 chunk("Emma_s — Author C", text="underscore"),
                 chunk("EmmaXs — Author D", text="other letter")])

    assert library.read_chapter("50%", CHAPTER) == ("percent", "50% — Author A", "found")
    assert library.read_chapter("Emma_s", CHAPTER) == ("underscore", "Emma_s — Author C", "found")


def test_a_quote_in_the_title_is_passed_as_a_value(transcripts):
    """No hand-escaping: the value goes into the expression as a literal."""
    transcripts([chunk("O'Brien's Book — X", text="apostrophes")])

    assert library.read_chapter("O'Brien's Book", CHAPTER) == ("apostrophes", "O'Brien's Book — X", "found")


def test_a_bare_title_shared_by_two_authors_is_still_refused(transcripts):
    """Both books survive the SQL narrowing, and the ambiguity is refused
    rather than resolved by row order."""
    transcripts([chunk("Emma — Jane Austen", text="austen"),
                 chunk("Emma — Somebody Else", text="other")])

    assert library.read_chapter("Emma", CHAPTER) == ("", "", "ambiguous")
    assert library.get_chapter("Emma", CHAPTER) == ""


def test_the_section_variants_are_still_tried(transcripts):
    """Section naming differs between books ("59" vs "Chapter 59"): the second
    variant is a second pair of queries, still with the book in them."""
    table = transcripts([chunk("Some Book — A", section="Chapter 59", text="fifty-nine")])

    assert library.read_chapter("Some Book — A", "59") == ("fifty-nine", "Some Book — A", "found")
    assert len(table.clauses) == 3      # variant "59" x (exact, fallback), then "Chapter 59"
    assert all("book = 'Some Book — A'" in clause or "contains(book, 'Some Book — A — ')" in clause
               for clause in table.clauses)
    assert [("section = '59'" in clause, "section = 'Chapter 59'" in clause)
            for clause in table.clauses] == [(True, False), (True, False), (False, True)]


def test_the_row_cap_is_no_longer_the_correctness_boundary(transcripts):
    """1,200 other books have a "Chapter 1" too. Filtering on the section alone
    and cutting at limit(1000) dropped the wanted book before Python ever saw
    it; with the book in the where clause the cap is only a safety net."""
    rows = [chunk(f"Filler {i} — A", text="filler") for i in range(1200)]
    rows.append(chunk("Target — Author", text="the real chapter"))
    table = transcripts(rows)

    assert library.read_chapter("Target", CHAPTER) == ("the real chapter", "Target — Author", "found")
    # what the old code did: the wanted row is past the cap
    section_only = table.search().where(f"section = '{CHAPTER}'").limit(library.CHAPTER_ROW_CAP).to_list()
    assert len(section_only) == library.CHAPTER_ROW_CAP
    assert not any(row["book"] == "Target — Author" for row in section_only)


def test_a_section_that_fills_the_cap_is_logged(monkeypatch, caplog):
    """The cap can still truncate ONE section: an unstructured book indexed as a
    single "Full text" section is thousands of chunks. Nothing downstream can
    tell — the read reports "found" and the cut marker counts only what was
    joined — so the operator is told. A fake table returns exactly the cap."""
    rows = [chunk("Big Book — A", section="Full text", text="x", n=i)
            for i in range(library.CHAPTER_ROW_CAP)]

    class FullTable:
        def search(self):
            return self

        def where(self, condition):
            return self

        def limit(self, n):
            return self

        def to_list(self):
            return rows[:library.CHAPTER_ROW_CAP]

    monkeypatch.setattr(library, "lancedb",
                        type("L", (), {"connect": staticmethod(lambda path: object())})())
    monkeypatch.setattr(library, "has_table", lambda db, name: True)
    monkeypatch.setattr(library, "open_table", lambda db, name: FullTable())

    with caplog.at_level(logging.WARNING, logger="ask_your_library.library"):
        text, key, resolution = library.read_chapter("Big Book — A", "Full text")

    assert (key, resolution) == ("Big Book — A", "found")
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert str(library.CHAPTER_ROW_CAP) in message
    assert "Big Book — A" in message and "Full text" in message


def test_a_chapter_below_the_cap_is_not_logged(transcripts, caplog):
    """The warning is about truncation, not about every read."""
    transcripts([chunk("Some Book — A", text="body")])

    with caplog.at_level(logging.WARNING, logger="ask_your_library.library"):
        assert library.read_chapter("Some Book — A", CHAPTER)[2] == "found"

    assert caplog.records == []


def test_a_missing_chapter_is_missing_not_an_error(transcripts):
    table = transcripts([chunk("Some Book — A", text="body")])

    assert library.read_chapter("Some Book — A", "Chapter 7") == ("", "", "missing")
    assert len(table.clauses) == 4      # two variants x (exact, fallback)


def test_a_capped_bare_title_fallback_is_refused_as_ambiguous(monkeypatch, caplog):
    """"Big — Author A" has 1,500 chunks in one section and "Big — Author B" 20:
    the bare-title query is cut at the cap with A's rows only, so Python would
    see one book. That is not a fact but an artefact of the cap: refused."""
    rows_a = [chunk("Big — Author A", section="Full text", text="x", n=i) for i in range(library.CHAPTER_ROW_CAP)]

    class Table:
        def __init__(self):
            self.conditions = []

        def search(self):
            return self

        def where(self, condition):
            self.conditions.append(condition.to_sql())
            return self

        def limit(self, n):
            return self

        def to_list(self):
            # the exact-key query ("Big" is not a key) finds nothing; the fallback comes back at the cap
            return [] if "contains" not in self.conditions[-1] else rows_a

    table = Table()
    monkeypatch.setattr(library, "lancedb", type("L", (), {"connect": staticmethod(lambda path: object())})())
    monkeypatch.setattr(library, "has_table", lambda db, name: True)
    monkeypatch.setattr(library, "open_table", lambda db, name: table)

    with caplog.at_level(logging.WARNING, logger="ask_your_library.library"):
        text, key, resolution = library.read_chapter("Big", "Full text")

    assert (text, key, resolution) == ("", "", "ambiguous")
    assert any("cut out of the candidates" in r.getMessage() and "Big" in r.getMessage() for r in caplog.records)
    # the exact-key path keeps its own wording and its own outcome
    caplog.clear()
    table.to_list = lambda: rows_a
    with caplog.at_level(logging.WARNING, logger="ask_your_library.library"):
        assert library.read_chapter("Big — Author A", "Full text")[2] == "found"
    assert any("longer than what was read" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------- search_both: one embed, one connect

class FakeSearchTable:
    """A corpus table for the search path. The vector list returns `rows` with a
    `_distance` (as LanceDB does); the FTS list returns `fts_rows` without one
    (a hit reaching the result through FTS alone carries no `distance`), or
    raises when `fts_ok` is False (no FTS index). Every `where` clause and every
    `limit` is recorded (search's book filter is still a string)."""

    def __init__(self, corpus, rows, fts_rows=None, fts_ok=True):
        self.corpus, self.rows = corpus, rows
        self.fts_rows = [dict(r, **{}) for r in (fts_rows if fts_rows is not None else rows)]
        for r in self.fts_rows:
            r.pop("_distance", None)
        self.fts_ok = fts_ok
        self.clauses: list[str] = []
        self.limits: list[int] = []

    def search(self, query, query_type=None):
        kind = query_type or "vector"
        if kind == "fts" and not self.fts_ok:
            raise ValueError("no FTS index on this table")
        rows = self.rows if kind == "vector" else self.fts_rows
        table = self

        class Query:
            def where(self, clause):
                table.clauses.append((kind, clause))
                return self

            def limit(self, n):
                table.limits.append(n)
                return self

            def to_list(self):
                return [dict(row) for row in rows]

        return Query()


@pytest.fixture
def counted_index(monkeypatch):
    """Point library.search at fake corpus tables, counting what a search costs:
    connections opened and query embeddings computed."""
    def build(corpora=("cards", "transcripts"), fts_ok=True, mismatch=()):
        counts = {"connect": 0, "embed": 0}
        tables = {}
        for corpus in corpora:
            tables[library.TABLES[corpus]] = FakeSearchTable(
                corpus, [{"book": f"Book {corpus} — A", "section": CHAPTER,
                          "text": f"{corpus} passage", "chunk_id": f"{corpus}/1", "_distance": 0.5}],
                # a second row only the FTS list knows: it must come back without `distance`
                fts_rows=[{"book": f"Book {corpus} — A", "section": CHAPTER,
                           "text": f"{corpus} passage", "chunk_id": f"{corpus}/1"},
                          {"book": f"Book {corpus} — A", "section": CHAPTER,
                           "text": f"{corpus} fts-only passage", "chunk_id": f"{corpus}/2"}],
                fts_ok=fts_ok)

        class DB:
            def table_names(self):
                return list(tables)
            list_tables = table_names

        def connect(path):
            counts["connect"] += 1
            return DB()

        def embed(text):
            counts["embed"] += 1
            return [0.0]

        monkeypatch.setattr(library.lancedb, "connect", connect)
        monkeypatch.setattr(library, "embed_query", embed)
        # the real open_table: check_index runs per table (once per process) before db.open_table
        DB.open_table = staticmethod(lambda name: tables[name])
        monkeypatch.setattr(library, "_checked_tables", set())
        monkeypatch.setattr(library, "embedder", lambda: type("E", (), {"model": "bge-m3", "dims": 1024})())
        monkeypatch.setattr(library, "check_index",
                            lambda db, name, model, dims: f"{name} was built by another model" if name in mismatch else None)
        monkeypatch.setattr(library, "_reported_missing", set())
        return counts, tables
    return build


def test_search_both_embeds_once_and_connects_once(counted_index):
    """Two search() calls cost two embeddings and two connections on every
    agent step; both corpora are asked on one of each now."""
    counts, _ = counted_index()

    hits = library.search_both("q", k=4)

    assert counts == {"connect": 1, "embed": 1}
    assert [hit["corpus"] for hit in hits] == ["cards", "cards", "transcripts", "transcripts"]   # fused per corpus, in order


def test_search_both_returns_what_the_two_separate_searches_returned(counted_index):
    counts, _ = counted_index()

    separate = library.search("cards", "q", 4) + library.search("transcripts", "q", 4)
    assert counts == {"connect": 2, "embed": 2}      # what it used to cost
    counts.update(connect=0, embed=0)

    assert library.search_both("q", k=4) == separate
    assert counts == {"connect": 1, "embed": 1}


def test_search_alone_is_unchanged(counted_index):
    """One corpus, one connection, one embedding — and the book filter still
    reaches the vector list and the FTS list alike."""
    counts, tables = counted_index()

    hits = library.search("cards", "q", 4, book="O'Brien — X")

    assert counts == {"connect": 1, "embed": 1}
    assert [hit["corpus"] for hit in hits] == ["cards", "cards"]
    assert tables[library.TABLES["cards"]].clauses == [("vector", "book = 'O''Brien — X'"),
                                                       ("fts", "book = 'O''Brien — X'")]


def test_a_missing_cards_table_is_searched_around_and_warned(counted_index, caplog):
    """`ayl-add` builds transcripts only: search_both runs over the corpus that
    exists, says so once, and does not pay for the missing one."""
    counts, _ = counted_index(corpora=("transcripts",))

    with caplog.at_level("WARNING"):
        hits = library.search_both("q", k=4)

    assert [hit["corpus"] for hit in hits] == ["transcripts", "transcripts"]   # vector row + FTS-only row
    assert counts == {"connect": 1, "embed": 1}
    assert sum("no table" in record.getMessage() for record in caplog.records) == 1
    assert library.search("cards", "q", 4) == []


def test_an_index_with_neither_corpus_costs_no_embedding(counted_index):
    counts, _ = counted_index(corpora=())

    assert library.search_both("q", k=4) == []
    assert counts == {"connect": 1, "embed": 0}


def test_an_index_fingerprint_mismatch_raises_before_any_embedding(counted_index):
    """open_table runs check_index for each corpus before the query is embedded:
    a transcripts table built by another model refuses the search at zero cost."""
    counts, _ = counted_index(mismatch=(library.TABLES["transcripts"],))

    with pytest.raises(RuntimeError, match="another model"):
        library.search_both("q", k=4)
    assert counts == {"connect": 1, "embed": 0}


def test_fts_failure_on_one_corpus_degrades_that_corpus_only(counted_index, caplog):
    """No FTS index on the cards table: cards come from the vector list alone
    (with one warning), transcripts stay hybrid, the step still costs one
    embedding and one connection."""
    counts, tables = counted_index(fts_ok=True)
    tables[library.TABLES["cards"]].fts_ok = False

    with caplog.at_level("WARNING"):
        hits = library.search_both("q", k=4)

    assert counts == {"connect": 1, "embed": 1}
    assert sum("FTS search failed" in r.getMessage() for r in caplog.records) == 1
    cards = [h for h in hits if h["corpus"] == "cards"]
    transcripts = [h for h in hits if h["corpus"] == "transcripts"]
    assert [h["text"] for h in cards] == ["cards passage"]                 # vector list only
    assert [h["text"] for h in transcripts] == ["transcripts passage", "transcripts fts-only passage"]
    # a hit that reached the result through FTS alone carries no distance; a vector hit does
    assert "distance" in transcripts[0] and "distance" not in transcripts[1]
    assert set(tables[library.TABLES["transcripts"]].limits) == {library.CANDIDATES_PER_LIST}
