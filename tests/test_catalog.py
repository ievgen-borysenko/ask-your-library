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
from ask_your_library.catalog import (CatalogResult, parse_catalog_request, render_catalog,
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
    assert result["mode"] == "answer" and result["catalog_fallback"] is True
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
    assert result["catalog_fallback"] is True and result["current_query"] == "which one?"


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
