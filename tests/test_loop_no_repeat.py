"""The loop never pays for the same search twice (#163).

On a library of about 250 audiobooks a research question ran q1 -> q3 -> q1 -> q1
and stopped at the step limit with plan query q2 never run: nothing recorded
which searches had been made, `reflect` saw only the queue, and the queue kept
q2 behind a repeat. `act` now records every search it runs as (normalised
query, effective book); `plan` queues each key once and drops what already ran,
and `reflect` replaces a repeat with the first unrun queued query, gives the
coverage gate its one chance when none is left, and otherwise stops with its own
reason.

No LLM, no network, no index: `llm.ask_json` and `search_both` are fakes.
"""
import pytest

from ask_your_library import llm, nodes
from ask_your_library.bookkey import escape_marker
from ask_your_library.i18n import t
from ask_your_library.runner import initial_state

MOBY = "Moby Dick — Herman Melville"
GULLIVER = "Gulliver's Travels — Jonathan Swift"
CRUSOE = "Robinson Crusoe — Daniel Defoe"


def decide(monkeypatch, **decision):
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: dict(decision))


def reflect_state(**over) -> dict:
    state = {"question": "q", "mode": "answer", "steps_taken": 1, "empty_streak": 0,
             "evidence": [], "queries": [], "read_chapters": [], "clarification": "",
             "clarify_asked": False, "clarify_chosen": "", "book_filter": "",
             "coverage_probed": False, "hits_log": [], "searches_run": []}
    state.update(over)
    return state


def ran(*queries, book=""):
    return [[nodes.normalise_query(q), book] for q in queries]


# ---------------------------------------------------------------- the key
@pytest.mark.parametrize("variant", ["Ahab's leg", "ahab's leg", "  AHAB'S   LEG  ", "Ahab's leg?",
                                     "«Ahab's leg»", "Ahab's\tleg.", "Ａhab's leg"])
def test_case_space_and_edge_punctuation_variants_are_one_search(variant):
    assert nodes.normalise_query(variant) == "ahab's leg"


def test_words_and_inner_punctuation_still_make_another_search():
    assert nodes.normalise_query("Ahab leg") != nodes.normalise_query("Ahab's leg")
    assert nodes.normalise_query("whale, white") != nodes.normalise_query("white whale")
    # accents are kept: the search engine ranks on the words it was given
    assert nodes.normalise_query("café") != nodes.normalise_query("cafe")


def test_the_key_names_the_book_the_search_really_ran_in():
    plain = reflect_state()
    assert nodes.search_key(plain, "White whale?") == ["white whale", ""]
    assert nodes.search_key({**plain, "book_filter": MOBY}, "white whale") == ["white whale", MOBY]
    # the reader's choice governs retrieval over a filter, exactly as in act
    chosen = {**plain, "book_filter": MOBY, "clarify_chosen": GULLIVER}
    assert nodes.search_key(chosen, "white whale") == ["white whale", GULLIVER]
    # a coverage probe searches its one book, whatever a plain search would use
    book = "Either|Or — Søren Kierkegaard"
    probe = f"__book__|{escape_marker(book)}|Which is it?"
    assert nodes.search_key(chosen, probe) == ["which is it", book]
    # what is not a search has no key
    for not_a_search in ("__chapter__|Moby Dick|Chapter 1", "__chapter_q__|purse|Moby Dick|Chapter 1",
                         "__clarify__", "", "   ", None, 42, "__book__|only-two"):
        assert nodes.search_key(chosen, not_a_search) is None


def test_initial_state_starts_with_no_searches():
    state = initial_state("q", [], "/tmp/x.md")
    assert state["searches_run"] == [] and state["query_replaced"] == {}


# ---------------------------------------------------------------- act
def test_act_records_the_search_it_ran_and_never_a_chapter_read(monkeypatch, tmp_path):
    monkeypatch.setattr(nodes, "search_both", lambda query, k=4, book=None: [])
    monkeypatch.setattr(nodes, "read_chapter", lambda book, section, max_chars=0: ("", "", "missing"))
    llm.reset_usage()
    scratchpad = tmp_path / "s.md"
    scratchpad.write_text("")
    base = {"steps_taken": 1, "read_chapters": [], "scratchpad_path": str(scratchpad)}

    assert nodes.act({**base, "current_query": "White whale?"})["searches_run"] == [["white whale", ""]]
    assert nodes.act({**base, "current_query": "white whale", "book_filter": MOBY,
                      "clarify_chosen": GULLIVER})["searches_run"] == [["white whale", GULLIVER]]
    probe = nodes.act({**base, "current_query": f"__book__|{escape_marker(MOBY)}|Who is Ahab?"})
    assert probe["searches_run"] == [["who is ahab", MOBY]]
    # a chapter read and a malformed marker search nothing, and say nothing about it
    assert "searches_run" not in nodes.act({**base, "current_query": f"__chapter__|{MOBY}|Chapter 1"})
    assert "searches_run" not in nodes.act({**base, "current_query": "__book__|x"})


# ---------------------------------------------------------------- reflect
def test_a_repeat_is_replaced_by_the_first_unrun_queued_query(monkeypatch):
    decide(monkeypatch, decision="search", next_query="Q1")
    state = reflect_state(queries=["q2", "q3"], searches_run=ran("q1"))
    result = nodes.reflect(state)
    assert result == {"current_query": "q2", "queries": ["q3"],
                      "query_replaced": {"from": "Q1", "to": "q2"}}


def test_the_reference_run_q1_q3_q1_now_runs_q2(monkeypatch):
    """The run of the issue: plan queued q2 and q3 behind q1, reflect chose q3,
    then named q1 again. q2 runs instead, and the queue is empty after it."""
    decide(monkeypatch, decision="search", next_query="q3")
    step1 = nodes.reflect(reflect_state(queries=["q2", "q3"], searches_run=ran("q1")))
    assert step1 == {"current_query": "q3", "queries": ["q2"]}      # no repeat, the old event

    decide(monkeypatch, decision="search", next_query="q1")
    step2 = nodes.reflect(reflect_state(steps_taken=2, queries=step1["queries"],
                                        searches_run=ran("q1", "q3")))
    assert step2 == {"current_query": "q2", "queries": [], "query_replaced": {"from": "q1", "to": "q2"}}


def test_queued_queries_that_already_ran_are_skipped_and_leave_the_queue(monkeypatch):
    decide(monkeypatch, decision="search", next_query="q1")
    state = reflect_state(queries=["Q1?", "q2", "q2 "], searches_run=ran("q1"))
    result = nodes.reflect(state)
    # "Q1?" is q1 again, so q2 is the first new one; its variant leaves with it
    assert result["current_query"] == "q2" and result["queries"] == ["Q1?"]


def test_a_queued_marker_is_never_the_replacement(monkeypatch):
    decide(monkeypatch, decision="search", next_query="q1")
    result = nodes.reflect(reflect_state(queries=["__chapter__|x|y", "q2"], searches_run=ran("q1")))
    assert result["current_query"] == "q2"


def test_with_nothing_queued_the_probe_runs_once_and_then_the_loop_stops(monkeypatch):
    """Answer mode, a comparison whose second book is in the window and not in
    the evidence: the repeat gives the coverage gate its chance, once; the next
    repeat has nothing left and stops on its own reason."""
    question = "How does Crusoe compare with Gulliver's Travels?"
    hits = [{"hit_id": "s1h1", "step": 1, "book": CRUSOE, "section": "s", "corpus": "cards", "text": "t"},
            {"hit_id": "s1h2", "step": 1, "book": GULLIVER, "section": "s", "corpus": "cards", "text": "t"}]
    evidence = [{"hit_id": "s1h1", "book": CRUSOE, "section": "s", "quote": "q", "why": "w"}]
    decide(monkeypatch, decision="search", next_query="castaway")
    state = reflect_state(question=question, evidence=evidence, hits_log=hits,
                          searches_run=ran("castaway"))
    first = nodes.reflect(state)
    probe = f"__book__|{GULLIVER}|{question}"
    assert first == {"current_query": probe, "queries": [], "coverage_probed": True,
                     "query_replaced": {"from": "castaway", "to": probe}}

    after = {**state, "steps_taken": 2, "coverage_probed": True,
             "searches_run": state["searches_run"] + [nodes.search_key(state, probe)]}
    second = nodes.reflect(after)
    assert second == {"current_query": "", "stop_reason": t("stop_no_new_query"),
                      "query_replaced": {"from": "castaway", "to": ""}}
    assert nodes.route_after_reflect({**after, **second}) == "synthesize"


def test_an_ineligible_probe_means_the_loop_stops_at_once(monkeypatch):
    decide(monkeypatch, decision="search", next_query="q1")
    # nothing queued and the question names no uncovered book: no probe to give
    stop = nodes.reflect(reflect_state(searches_run=ran("q1")))
    assert stop == {"current_query": "", "stop_reason": t("stop_no_new_query"),
                    "query_replaced": {"from": "q1", "to": ""}}
    # the gate already spent, or after a clarify: no probe either
    for spent in ({"coverage_probed": True}, {"clarify_asked": True}):
        assert nodes.reflect(reflect_state(searches_run=ran("q1"), **spent))["stop_reason"] == \
            t("stop_no_new_query")


def test_a_probe_the_run_already_made_is_no_probe(monkeypatch):
    """Identify mode probes with the next queued query: one that already ran
    is not forced again, neither on the model's 'enough' nor after a repeat."""
    evidence = [{"hit_id": "s1h1", "book": CRUSOE, "section": "s", "quote": "q", "why": "w"}]
    state = reflect_state(mode="identify", evidence=evidence, queries=["q2"],
                          searches_run=ran("q1", "q2"))
    decide(monkeypatch, decision="enough")
    assert nodes.reflect(state) == {"current_query": "", "stop_reason": t("stop_enough")}
    decide(monkeypatch, decision="search", next_query="q1")
    assert nodes.reflect(state)["stop_reason"] == t("stop_no_new_query")


def test_a_repeated_coverage_marker_is_a_repeat(monkeypatch):
    marker = f"__book__|{escape_marker(GULLIVER)}|Who is the narrator?"
    decide(monkeypatch, decision="search", next_query="who is the narrator")
    # the same words as a plain search are another search: the probe was inside one book
    state = reflect_state(searches_run=[["who is the narrator", GULLIVER]])
    assert nodes.reflect(state)["current_query"] == "who is the narrator"
    # the marker itself is the loop's, and reflect never takes one from the model
    decide(monkeypatch, decision="search", next_query=marker)
    assert nodes.reflect(state)["stop_reason"] == t("stop_no_new_query")


def test_an_empty_proposal_with_nothing_queued_is_the_new_stop_not_a_silent_end(monkeypatch):
    """It used to return an empty query and no reason, which every renderer
    read as "enough". With a queued query the old fallback is unchanged."""
    decide(monkeypatch, decision="search", next_query="")
    assert nodes.reflect(reflect_state()) == {"current_query": "", "stop_reason": t("stop_no_new_query"),
                                              "query_replaced": {"from": "", "to": ""}}
    assert nodes.reflect(reflect_state(queries=["q2"])) == {"current_query": "q2", "queries": []}


def test_the_same_query_under_another_book_is_not_a_repeat(monkeypatch):
    decide(monkeypatch, decision="search", next_query="q1")
    before_clarify = ran("q1")                               # searched the whole library
    chosen = reflect_state(clarify_chosen=MOBY, clarify_asked=True, searches_run=before_clarify)
    assert nodes.reflect(chosen) == {"current_query": "q1", "queries": []}
    # under the same book it is
    again = {**chosen, "searches_run": before_clarify + ran("q1", book=MOBY)}
    assert nodes.reflect(again)["stop_reason"] == t("stop_no_new_query")


def test_the_chapter_guard_is_unchanged(monkeypatch):
    """Chapter reads are not searches: the read_chapters guard and its stop
    own them, whatever searches have run."""
    decide(monkeypatch, decision="read_chapter", book=MOBY, section="Chapter 1")
    state = reflect_state(searches_run=ran("q1"))
    assert nodes.reflect(state) == {"current_query": f"__chapter__|{MOBY}|Chapter 1"}
    read = {**state, "read_chapters": [f"{MOBY}|Chapter 1|complete"]}
    assert nodes.reflect(read) == {"current_query": "", "stop_reason": t("stop_chapter_again")}


# ---------------------------------------------------------------- plan
def plan_with(monkeypatch, queries, **over):
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {"mode": "answer", "queries": queries})
    state = {"question": "q", "history": [], "clarification": "", "evidence": [], "steps_taken": 0,
             "searches_run": []}
    state.update(over)
    return nodes.plan(state)


def test_plan_queues_each_search_once(monkeypatch):
    result = plan_with(monkeypatch, ["White whale", "white whale?", "Ahab", "  WHITE WHALE ", "ahab."])
    assert result["current_query"] == "White whale" and result["queries"] == ["Ahab"]
    assert "stop_reason" not in result
    # a plan without duplicates is the plan it always was
    clean = plan_with(monkeypatch, ["q1", "q2", "q3"])
    assert clean["current_query"] == "q1" and clean["queries"] == ["q2", "q3"]


def test_a_replan_after_clarify_drops_what_ran_under_the_chosen_book_only(monkeypatch):
    """Before the clarify the run searched the whole library; the reader chose
    a book, and the same words inside that book are a new search. What already
    ran inside it is not queued again."""
    monkeypatch.setattr(nodes, "_chosen_book", lambda state, unresolved: MOBY)
    monkeypatch.setattr(nodes, "_evidence_after_clarify", lambda state: ([], False))
    over = {"clarification": "the first one", "clarify_asked": True, "steps_taken": 2,
            "searches_run": ran("q1", "q2") + ran("q3", book=MOBY)}
    result = plan_with(monkeypatch, ["q1", "q3", "q4"], **over)
    assert result["current_query"] == "q1" and result["queries"] == ["q4"]
    assert result["clarify_chosen"] == MOBY

    # everything the planner asked for already ran there: nothing new to search
    done = plan_with(monkeypatch, ["Q3"], **over)
    assert done["current_query"] == "" and done["queries"] == []
    assert done["stop_reason"] == t("stop_no_new_query")
    assert nodes.route_after_plan({**over, **done}) == "synthesize"


def test_a_replan_without_a_chosen_book_drops_what_ran_in_the_whole_library(monkeypatch):
    monkeypatch.setattr(nodes, "_chosen_book", lambda state, unresolved: "")
    monkeypatch.setattr(nodes, "_evidence_after_clarify", lambda state: ([], True))
    result = plan_with(monkeypatch, ["q1", "q2"], clarification="neither", clarify_asked=True,
                       steps_taken=2, searches_run=ran("q1"))
    assert result["current_query"] == "q2" and result["queries"] == []


# ---------------------------------------------------------------- what the reader sees
def test_the_cli_names_the_search_that_already_ran(capsys):
    from ask_your_library import cli
    cli.print_event("reflect", {"current_query": "q2", "queries": [],
                                "query_replaced": {"from": "q1", "to": "q2"}})
    cli.print_event("reflect", {"current_query": "", "stop_reason": t("stop_no_new_query"),
                                "query_replaced": {"from": "q1", "to": ""}})
    cli.print_event("reflect", {"current_query": "q3", "queries": []})
    lines = capsys.readouterr().out.splitlines()
    assert lines == [t("ev_reflect_repeat", q="q1"), t("ev_reflect_search", q="q2"),
                     t("ev_reflect_repeat", q="q1"),
                     t("ev_reflect_stopped", r=t("stop_no_new_query")),
                     t("ev_reflect_search", q="q3")]
