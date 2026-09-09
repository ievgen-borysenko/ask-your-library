"""The catalogue path (ADR-016) without a model: list_books over a real LanceDB
in tmp (canaries excluded by their source column, a text-only book flagged),
the planner's catalog object validated by code, title and author resolution,
the rendered answers in both languages, and the planner-side guards (a
catalogue request after a clarify, an operation that is not ours) that keep a
question in the research loop. The graph-level runs are in test_graph_e2e.py."""
import contextvars

import lancedb
import pytest

from ask_your_library import i18n, library, llm, nodes, provenance
from ask_your_library.catalog import (CatalogResult, content_clue, parse_catalog_request, render_catalog,
                                      resolve_author, resolve_title, run_catalog)
from ask_your_library.i18n import t
from ask_your_library.library import TITLE_SEPARATOR, BookEntry, list_books


def key(title, author):
    return f"{title}{TITLE_SEPARATOR}{author}"


MOBY = key("Moby Dick", "Herman Melville")
GULLIVER = key("Gulliver's Travels", "Jonathan Swift")
IVANHOE = key("Ivanhoe", "Walter Scott")
HOLMES_A = key("The Adventures of Sherlock Holmes", "Arthur Conan Doyle")
HOLMES_B = key("The Return of Sherlock Holmes", "Arthur Conan Doyle")
SCARLET = key("A Study in Scarlet", "Arthur Conan Doyle")
CANARY = key("The Whispering Archive", "Vera Holloway")
OWN = key("My Notes", "Unknown")


def entries(*keys):
    return [BookEntry(k, library.title_of(k), library.author_of(k), True, True) for k in keys]


ALL = entries(GULLIVER, IVANHOE, MOBY, HOLMES_A, HOLMES_B, SCARLET)


def in_lang(lang, fn):
    """Run fn with the session language set, without leaking it to other tests."""
    def go():
        i18n.set_lang(lang)
        return fn()
    return contextvars.copy_context().run(go)


# ---------------------------------------------------------------- list_books over a real index

def row(book, source="pg:1", section="Chapter 1", n=1):
    return {"chunk_id": f"{book}/{section}/{n}", "note": "n", "book": book, "source": source,
            "section": section, "text": "text", "vector": [0.0, 1.0]}


@pytest.fixture
def index(tmp_path, monkeypatch):
    """A two-table index in tmp, the one library.DB_PATH points at."""
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "db")
    db = lancedb.connect(str(tmp_path / "db"))

    def build(cards, transcripts):
        if cards:
            db.create_table(library.TABLES["cards"], cards)
        if transcripts:
            db.create_table(library.TABLES["transcripts"], transcripts)
    return build


def test_list_books_is_the_distinct_union_of_both_corpora_without_the_canaries(index):
    index(cards=[row(MOBY, "Herman Melville — Moby Dick"), row(MOBY, "Herman Melville — Moby Dick", n=2),
                 row(IVANHOE, "Walter Scott — Ivanhoe")],
          transcripts=[row(MOBY), row(GULLIVER, "pg:829"), row(CANARY, "canary"), row(CANARY, "canary", n=2),
                       row(OWN, "transcript")])
    books = list_books()
    assert [b.key for b in books] == [GULLIVER, IVANHOE, MOBY, OWN]        # by title; the canary is not a book
    by_key = {b.key: b for b in books}
    assert by_key[MOBY] == BookEntry(MOBY, "Moby Dick", "Herman Melville", has_cards=True, has_text=True)
    assert by_key[IVANHOE].has_text is False and by_key[IVANHOE].has_cards is True
    assert by_key[GULLIVER].has_cards is False and by_key[GULLIVER].has_text is True
    assert by_key[OWN].author == "Unknown" and by_key[OWN].has_cards is False


def test_a_canary_is_excluded_by_its_source_column_not_by_its_name(index):
    # The same title as a canary, ingested as a real book, is listed: the column decides.
    index(cards=[], transcripts=[row(CANARY, "transcript"), row(MOBY, "canary")])
    assert [b.key for b in list_books()] == [CANARY]


def test_a_book_with_a_canary_row_among_real_rows_is_still_a_book(index):
    # A stray `source: canary` on one card must not delete a real book from the catalogue:
    # a canary row counts for nothing, the other rows make it a book.
    index(cards=[row(MOBY, "canary")], transcripts=[row(MOBY, "pg:2701"), row(CANARY, "canary")])
    assert [b.key for b in list_books()] == [MOBY]


def test_a_row_without_a_book_key_is_skipped(index):
    index(cards=[], transcripts=[row(MOBY), {**row(GULLIVER, n=2), "book": None}])
    assert [b.key for b in list_books()] == [MOBY]


class RecordingQuery:
    def __init__(self, query, record):
        self._query, self._record = query, record

    def select(self, columns):
        self._record["select"] = list(columns)
        return RecordingQuery(self._query.select(columns), self._record)

    def limit(self, n):
        self._record["limit"] = n
        return RecordingQuery(self._query.limit(n), self._record)

    def to_list(self):
        return self._query.to_list()


class RecordingTable:
    def __init__(self, table, record):
        self._table, self._record = table, record

    def search(self, *args, **kwargs):
        return RecordingQuery(self._table.search(*args, **kwargs), self._record)

    def count_rows(self):
        return self._table.count_rows()


class RecordingDB:
    """The real database; every table opened is wrapped so the query the
    catalogue runs (projection, limit) is recorded next to its results."""

    def __init__(self, db, records):
        self._db, self._records = db, records

    def table_names(self):
        return self._db.table_names()

    def list_tables(self):
        return self._db.list_tables()

    def open_table(self, name):
        record = self._records.setdefault(name, {})
        return RecordingTable(self._db.open_table(name), record)


def test_the_catalogue_reads_every_row_through_a_two_column_projection(index, monkeypatch):
    """More books than LanceDB's default result limit of ten, split over both
    tables: the listing must be complete, loaded through the two metadata columns
    only, with a limit that covers every row of each table."""
    books = [key(f"Book {i:02d}", f"Author {i}") for i in range(1, 15)]
    index(cards=[row(b, "frontmatter") for b in books[:8]],
          transcripts=[row(b, f"pg:{i}", n=n) for i, b in enumerate(books) for n in (1, 2)])
    records: dict[str, dict] = {}
    real_connect = library.lancedb.connect
    monkeypatch.setattr(library.lancedb, "connect", lambda path: RecordingDB(real_connect(path), records))
    listed = list_books()
    assert [b.key for b in listed] == books                       # 14 of 14, sorted by title
    assert [b.has_cards for b in listed] == [True] * 8 + [False] * 6
    for name, record in records.items():
        assert record["select"] == ["book", "source"], name
        assert record["limit"] >= (8 if name == library.TABLES["cards"] else 28), name


def test_a_missing_corpus_is_skipped_and_the_other_one_is_listed(index, caplog):
    index(cards=[row(IVANHOE, "x")], transcripts=[])
    library._reported_missing.clear()
    with caplog.at_level("WARNING"):
        assert [b.key for b in list_books()] == [IVANHOE]
    assert "no table" in caplog.text


def test_an_index_with_neither_corpus_lists_nothing(index):
    index(cards=[], transcripts=[])
    assert list_books() == []


# ---------------------------------------------------------------- the operation, validated by code

def test_the_count_is_the_length_of_the_list_it_shows():
    result = run_catalog({"op": "count", "title": "", "author": ""}, ALL)
    assert result.as_state()["count"] == len(result.books) == result.total == len(ALL)
    assert render_catalog(result) == t("catalog_count", n=len(ALL))
    listing = run_catalog({"op": "list", "title": "", "author": ""}, ALL)
    assert render_catalog(listing).count("\n- ") == len(ALL)


@pytest.mark.parametrize("raw", [
    None, "count", 42, {}, {"op": "delete_all"}, {"op": 7}, {"op": "has"}, {"op": "has", "title": "  "},
    {"op": "has", "title": ["Moby Dick"]}, {"op": "by_author"}, {"op": "by_author", "author": ""},
])
def test_an_operation_that_is_not_ours_or_has_nothing_to_look_up_is_refused(raw):
    assert parse_catalog_request({"mode": "catalog", "catalog": raw}) is None


def test_a_valid_operation_is_kept_with_its_names_trimmed():
    assert parse_catalog_request({"catalog": {"op": "has", "title": " Moby Dick "}}) == {
        "op": "has", "title": "Moby Dick", "author": ""}
    assert parse_catalog_request({"catalog": {"op": "by_author", "author": "Doyle", "title": 5}}) == {
        "op": "by_author", "title": "", "author": "Doyle"}
    assert parse_catalog_request({"catalog": {"op": "count"}}) == {"op": "count", "title": "", "author": ""}


# ---------------------------------------------------------------- resolving names

@pytest.mark.parametrize("name, expected", [
    ("Moby Dick", [MOBY]),                                   # exact
    ("moby dick", [MOBY]),                                   # case
    ("Moby Dick — Herman Melville", [MOBY]),                 # the full key
    ("Gulliver\u2019s Travels", [GULLIVER]),                  # curly apostrophe
    ("adventures of sherlock holmes", [HOLMES_A]),           # leading article
    ("Ivanho", [IVANHOE]),                                   # a typo
    ("Moby Duck", [MOBY]),
    ("Sherlock Holmes", [HOLMES_A, HOLMES_B]),               # contained: every Holmes title, as several
    ("Scarlet", [SCARLET]),
])
def test_a_title_resolves_exactly_with_a_typo_or_as_several(name, expected):
    matches, suggestions = resolve_title(name, ALL)
    assert sorted(m.key for m in matches) == sorted(expected) and suggestions == []


def test_a_title_that_is_not_there_resolves_to_nothing_with_at_most_three_suggestions():
    matches, suggestions = resolve_title("War and Peace", ALL)
    assert matches == [] and len(suggestions) <= 3
    matches, suggestions = resolve_title("It", ALL)          # too short to be "contained" in every title
    assert matches == [] and suggestions == []
    assert resolve_title("   ", ALL) == ([], [])


def test_strict_resolution_refuses_a_fragment_of_a_longer_title():
    """The hybrid's retrieval filter: a one-word fragment inside a longer title
    ("Time" for The Time Machine) must not silently limit the search to one
    book; several words, most of a title, an exact title or a typo still do."""
    library_with_time = ALL + entries(key("The Time Machine", "H. G. Wells"))
    assert resolve_title("Time", library_with_time, strict=True)[0] == []
    assert [m.title for m in resolve_title("Time", library_with_time)[0]] == ["The Time Machine"]
    assert [m.title for m in resolve_title("Time Machine", library_with_time, strict=True)[0]] == ["The Time Machine"]
    assert [m.title for m in resolve_title("Scarlet", ALL, strict=True)[0]] == []          # 7 of 18 chars
    assert sorted(m.key for m in resolve_title("Sherlock Holmes", ALL, strict=True)[0]) == sorted([HOLMES_A, HOLMES_B])
    assert [m.key for m in resolve_title("Ivanho", ALL, strict=True)[0]] == [IVANHOE]


def test_an_explicit_author_is_a_constraint_not_a_hint():
    """Two books share a title. The full key picks one; a typo in the surname
    still picks it; an author who wrote neither resolves to nothing and names
    both as the closest; no author given keeps both, as before."""
    one, two = key("Shared Title", "Author One"), key("Shared Title", "Author Two")
    shelf = ALL + entries(one, two)
    assert [m.key for m in resolve_title("Shared Title — Author Two", shelf)[0]] == [two]
    assert [m.key for m in resolve_title("Shared Title by Author One", shelf)[0]] == [one]
    assert [m.key for m in resolve_title("Shared Title — Author Twoo", shelf)[0]] == [two]
    assert [m.key for m in resolve_title("Shared Title — Author Two", shelf, strict=True)[0]] == [two]
    matches, suggestions = resolve_title("Shared Title — Missing Author", shelf)
    assert matches == [] and sorted(suggestions) == sorted([one, two])
    assert sorted(m.key for m in resolve_title("Shared Title", shelf)[0]) == sorted([one, two])


def test_a_title_that_contains_the_separator_still_resolves_as_a_whole():
    perec = key("Life — A User's Manual", "Georges Perec")
    shelf = ALL + entries(perec)
    assert [m.key for m in resolve_title("Life — A User's Manual", shelf)[0]] == [perec]
    assert [m.key for m in resolve_title("Life — A User's Manual — Georges Perec", shelf)[0]] == [perec]


def test_an_author_resolves_by_full_name_surname_or_typo():
    assert [m.key for m in resolve_author("Herman Melville", ALL)[0]] == [MOBY]
    assert [m.key for m in resolve_author("melville", ALL)[0]] == [MOBY]
    assert [m.key for m in resolve_author("Melvile", ALL)[0]] == [MOBY]
    assert sorted(m.key for m in resolve_author("Conan Doyle", ALL)[0]) == sorted([HOLMES_A, HOLMES_B, SCARLET])
    matches, suggestions = resolve_author("Tolstoy", ALL)
    assert matches == [] and len(suggestions) <= 3


# ---------------------------------------------------------------- the rendered answers

def test_has_and_by_author_answers_name_what_was_found_or_what_was_closest():
    yes = run_catalog({"op": "has", "title": "Ivanho", "author": ""}, ALL)
    assert yes.resolved and render_catalog(yes) == t("catalog_has_yes", items=f"- {IVANHOE}")
    no = CatalogResult("has", [], len(ALL), "War and Peace", False, ["Ivanhoe"])
    assert render_catalog(no) == t("catalog_has_no", q="War and Peace") + t("catalog_closest_titles", items="Ivanhoe")
    doyle = run_catalog({"op": "by_author", "title": "", "author": "Doyle"}, ALL)
    assert render_catalog(doyle) == t("catalog_by_author", n=3, author="Arthur Conan Doyle",
                                      items="\n".join(f"- {k}" for k in (HOLMES_A, HOLMES_B, SCARLET)))
    nobody = run_catalog({"op": "by_author", "title": "", "author": "Tolstoy"}, ALL)
    assert render_catalog(nobody).startswith(t("catalog_by_author_none", q="Tolstoy"))


def test_the_answers_follow_the_session_language():
    count = run_catalog({"op": "count", "title": "", "author": ""}, ALL)
    assert in_lang("ua", lambda: render_catalog(count)) == "У бібліотеці 6 книжок (за таблицями індексу)."
    assert render_catalog(count) == "Your library holds 6 books (by the index tables)."


# ---------------------------------------------------------------- the content-clue gate

@pytest.mark.parametrize("question", [
    "How many books do I have in my library?", "What are the names of all the books in my library?",
    "Do I have Ivanhoe?", "Is War and Peace in my library?", "What do I have by Jules Verne?",
    "Скільки книжок у моїй бібліотеці?", "Які книжки в мене є?", "Чи є в мене Айвенго?",
])
def test_a_pure_holdings_question_carries_no_content_clue(question):
    assert content_clue(question) == ""


@pytest.mark.parametrize("question, clue", [
    ("Do I have Dracula, and why does Jonathan Harker stay at the castle?", "why"),
    ("What do I have about whaling?", "about"),
    ("Which of my books mention London?", "mention"),
    ("Is Moby Dick in my library, and who narrates it?", "who"),
    ("How does Ivanhoe end?", "how"),
    ("Чи є в мене Дракула, і чому Гаркер лишається в замку?", "чому"),
    ("Що в мене є про китів?", "про"),
    ("Чи є Дракула, йдеться там про замок?", "йдеться"),     # a breve survives: the gate must not accent-fold
])
def test_a_question_that_also_asks_about_content_is_flagged(question, clue):
    assert content_clue(question) == clue


def test_a_title_inside_a_question_is_beyond_the_gate():
    # Known limit, recorded in the ADR: the gate knows words, not titles.
    assert content_clue("What are the names of the three musketeers?") == ""


# ---------------------------------------------------------------- the planner-side guards (nodes.plan, no graph)

def fresh_state(**over):
    state = {"question": "How many books do I have?", "history": [], "clarification": "",
             "evidence": [], "steps_taken": 0, "clarify_asked": False, "clarify_candidates": []}
    return {**state, **over}


def test_plan_hands_a_catalogue_question_to_the_catalog_node_with_no_query(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"mode": "catalog", "queries": [],
                                                                     "catalog": {"op": "count"}})
    monkeypatch.setattr(nodes, "list_books", lambda: pytest.fail("no lookup is needed to route"))
    result = nodes.plan(fresh_state())
    assert result["mode"] == "catalog" and result["catalog_request"] == {"op": "count", "title": "", "author": ""}
    assert result["current_query"] == "" and result["queries"] == []
    assert "catalog_fallback" not in result and "plan_fallback" not in result
    assert nodes.route_after_plan({**fresh_state(), **result}) == "catalog"


def test_an_operation_that_is_not_ours_sends_the_question_to_the_research_loop(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"mode": "catalog",
                                                                     "catalog": {"op": "delete_all"}, "queries": []})
    result = nodes.plan(fresh_state())
    assert result["mode"] == "answer" and result["catalog_fallback"] == "invalid_op"
    assert result["current_query"] == "How many books do I have?" and result["plan_fallback"] is True
    assert "catalog_request" not in result
    assert nodes.route_after_plan({**fresh_state(), **result}) == "act"


def test_a_catalogue_request_after_a_clarify_reply_is_not_honoured(monkeypatch):
    """The reader's reply settled a book of the research loop; a listing would
    throw that away. The resolved book wins and the loop goes on."""
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"mode": "catalog",
                                                                     "catalog": {"op": "count"}, "queries": []})
    monkeypatch.setattr(nodes, "list_books", lambda: ALL)
    llm.reset_usage()        # a resumed plan checks the deadline clock: this question's, not a previous test's
    state = fresh_state(question="which one?", clarification="the first one", clarify_asked=True,
                        clarify_candidates=[MOBY, GULLIVER])
    result = nodes.plan(state)
    assert result["mode"] == "answer" and result["clarify_chosen"] == MOBY
    assert result["catalog_fallback"] == "after_clarify" and result["current_query"] == "which one?"
    assert "plan_fallback" not in result        # the raw question by design, not for want of a plan


def test_a_named_book_is_resolved_by_code_into_a_retrieval_filter(monkeypatch):
    monkeypatch.setattr(nodes, "list_books", lambda: ALL)

    def plan_with(book):
        monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"mode": "answer", "queries": ["q"], "book": book})
        return nodes.plan(fresh_state(question="content question"))

    assert plan_with("moby dick")["book_filter"] == MOBY                       # one match: the filter
    assert plan_with("moby dick")["book_unresolved"] == ""
    absent = plan_with("War and Peace")
    assert absent["book_filter"] == "" and absent["book_unresolved"] == "War and Peace"   # none: say so
    several = plan_with("Sherlock Holmes")
    assert several["book_filter"] == "" and several["book_unresolved"] == ""            # several: no filter, no note
    assert plan_with("")["book_filter"] == "" and plan_with(None)["book_unresolved"] == ""


def test_a_mixed_question_the_planner_labelled_catalogue_takes_the_research_loop_with_the_filter(monkeypatch):
    """The planner says `has Dracula`; the question also asks why Harker stays.
    Code sends it to the research loop, the raw question as the query (not a
    planner fallback), and the named title becomes the retrieval filter."""
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"mode": "catalog", "queries": [],
                                                                     "catalog": {"op": "has", "title": "moby dick"}})
    monkeypatch.setattr(nodes, "list_books", lambda: ALL)
    question = "Do I have Moby Dick, and why does Ishmael go to sea?"
    result = nodes.plan(fresh_state(question=question))
    assert result["mode"] == "answer" and result["catalog_fallback"] == "mixed_intent"
    assert result["current_query"] == question and result["queries"] == [] and "plan_fallback" not in result
    assert result["book_filter"] == MOBY and result["book_unresolved"] == ""
    assert "catalog_request" not in result and nodes.route_after_plan({**fresh_state(), **result}) == "act"


def test_the_catalog_node_answers_from_the_list_and_validate_reports_it(monkeypatch):
    monkeypatch.setattr(nodes, "list_books", lambda: ALL)
    update = nodes.catalog({"catalog_request": {"op": "has", "title": "Ivanhoe", "author": ""}})
    assert update["catalog"] == {"op": "has", "count": 1, "total": len(ALL), "books": [IVANHOE],
                                 "query": "Ivanhoe", "resolved": True, "suggestions": []}
    assert update["answer"] == t("catalog_has_yes", items=f"- {IVANHOE}")
    assert update["stop_reason"] == t("stop_catalog") and update["current_query"] == ""
    verdict = provenance.validate({"evidence": [], "answer": update["answer"], "catalog": update["catalog"]})
    assert verdict["verification"] == t("verif_catalog", n=1, total=len(ALL))
    assert verdict["provenance"]["checked"] == 0 and verdict["provenance"]["items"] == []
    assert verdict["provenance"]["catalog"] == {"op": "has", "count": 1, "total": len(ALL)}
