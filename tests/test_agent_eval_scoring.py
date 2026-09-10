"""Behavioural scoring of the agent eval (pure function, no LLM)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "run_agent_eval", Path(__file__).resolve().parents[1] / "eval" / "run_agent_eval.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def run(answer="", clarify=False, checked=1, chapters=None):
    return {"answer": answer, "clarify_asked": clarify,
            "provenance": {"checked": checked}, "read_chapters": chapters or []}


def test_answer_requires_every_expected_book_cited():
    item = {"type": "aggregation", "expected_books": ["Moby Dick", "Dracula"]}
    assert not harness.score(item, run("Only Moby Dick here"))["behavior_ok"]
    assert harness.score(item, run("Moby Dick vs Dracula"))["behavior_ok"]


def test_clarify_semantics():
    item = {"type": "identify", "expected_books": ["Moby Dick"], "expected_behavior": "clarify"}
    assert harness.score(item, run("Moby Dick", clarify=False))["behavior_ok"] is False
    assert harness.score(item, run("", clarify=True))["behavior_ok"] is True
    either = {**item, "expected_behavior": "clarify_or_answer"}
    assert harness.score(either, run("Moby Dick"))["behavior_ok"] is True


def test_refusal_requires_an_explicit_refusal_marker():
    item = {"type": "refusal", "expected_books": []}
    assert harness.score(item, run("I don't know", checked=0))["behavior_ok"]
    assert not harness.score(item, run("Here is an answer", checked=3))["behavior_ok"]
    # evidence-free but answered from model knowledge: must FAIL
    assert not harness.score(item, run("Bond wins the baccarat game against Le Chiffre.", checked=0))["behavior_ok"]


def test_drilldown_is_part_of_the_verdict_and_must_be_the_expected_book():
    item = {"type": "answer", "expected_books": ["Moby Dick"], "expects_chapter_read": True}
    good = harness.score(item, run("Moby Dick", chapters=["Moby Dick — Herman Melville|CHAPTER 135"]))
    assert good["drilldown_ok"] and good["behavior_ok"]
    wrong_book = harness.score(item, run("Moby Dick", chapters=["Dracula|Chapter 2"]))
    assert not wrong_book["drilldown_ok"] and not wrong_book["behavior_ok"]
    no_read = harness.score(item, run("Moby Dick"))
    assert not no_read["behavior_ok"]
    assert "drilldown_ok" not in harness.score({"type": "answer", "expected_books": ["Moby Dick"]}, run("Moby Dick"))


def test_groups_are_question_types_not_id_prefixes():
    assert harness.group_of({"id": "q06-verne", "type": "identify"}) == "identify"
    assert harness.group_of({"id": "c08-tom", "type": "refusal"}) == "refusal"


def test_book_match_folds_accents():
    item = {"type": "identify", "expected_books": ["The Extraordinary Adventures of Arsène Lupin"]}
    assert harness.score(item, run("It is The Extraordinary Adventures of Arsene Lupin."))["behavior_ok"]


def test_refusal_may_cite_evidence_when_it_says_so():
    """Near-miss inside a present book: the honest answer cites the card that
    says the poem is not in this edition."""
    item = {"type": "refusal", "expected_books": []}
    honest = run("The poem is not included in this English selection [Kobzar, Key Takeaways].", checked=1)
    assert harness.score(item, honest)["behavior_ok"]


def test_refusal_markers_cover_the_evidence_does_not_contain_it_phrasing():
    """c08 is declined by both local models as "the evidence provided does not
    contain information about ..." or "... does not cover how ...", which is a
    refusal by any reading and used to score FAIL for want of a marker. The
    family added is the one whose subject can only be the evidence or the
    library, in both voices: which verb a model reaches for, and whether it
    writes it actively, must not be what decides the score."""
    item = {"type": "refusal", "expected_books": []}
    for answer in ("The evidence provided does not contain information about Tom Sawyer making "
                   "the other boys pay him for the chance to paint the fence.",
                   "The retrieved passages do not contain that episode.",
                   "That episode is not contained in the evidence.",
                   "The evidence does not include the whitewashing scene.",
                   "The provided evidence does not cover how Tom Sawyer made the boys pay him.",
                   "The passages here do not cover the fence at all.",
                   "That episode is not covered by the books here.",
                   "Бібліотека не містить цієї книжки.",
                   "Ці книжки не містять цього епізоду."):
        assert harness.score(item, run(answer, checked=1))["behavior_ok"], answer
    # the metric's meaning is unchanged: told from model memory, with no such
    # phrase anywhere, it is still a FAIL
    told_from_memory = ("Tom Sawyer persuaded the other boys that whitewashing the fence was a "
                        "privilege, and they paid him with an apple and a dead rat for a turn.")
    assert not harness.score(item, run(told_from_memory, checked=0))["behavior_ok"]
    # and an answer that answers may say a chapter does not MENTION a detail
    # without that turning it into a refusal — the phrase is deliberately absent
    assert not harness.score(item, run(
        "Chapter II does not mention the rat, but Tom traded the whitewashing for marbles.",
        checked=2))["behavior_ok"]


def test_a_refusal_that_goes_on_to_narrate_from_memory_is_not_a_refusal():
    """A marker is where a refusal ENDS. Declining and then telling the story
    anyway is the failure the item measures, and the widened marker list makes
    that shape likelier — it now covers hedges models emit constantly. So the
    rule is: an explicit marker, and at most REFUSAL_TAIL_WORDS words after it."""
    item = {"type": "refusal", "expected_books": []}
    # (a) a pure refusal: the marker, and nothing after it but the apology
    pure = ("The Adventures of Tom Sawyer is not in the library, so I cannot answer this "
            "from the evidence I have.")
    assert harness.score(item, run(pure, checked=0))["behavior_ok"]
    # (b) the same refusal that then narrates the episode from the model's memory
    narrated = ("The library does not contain The Adventures of Tom Sawyer. In the novel Tom is "
                "set to whitewash his aunt's fence as a punishment, and when Ben Rogers comes by "
                "to jeer at him he pretends the work is a rare privilege; Ben begs for a turn and "
                "gives up his apple for it, and by the afternoon every boy in the village has "
                "traded a kite, twelve marbles, a piece of blue bottle glass and a dead rat on a "
                "string for the chance to paint.")
    assert not harness.score(item, run(narrated, checked=0))["behavior_ok"]
    # (c) an ANSWER item that mentions the phrase about a sub-point is untouched:
    # the tail rule lives on the refusal branch only, and this is scored on titles
    answer_item = {"type": "answer", "expected_books": ["Moby Dick"]}
    hedged = ("Moby Dick has it, though the evidence does not include the exact wording of the "
              "sermon: Ishmael ships aboard the Pequod under Ahab, who has sworn to kill the "
              "white whale that took his leg, and the voyage ends with the ship destroyed and "
              "Ishmael the only man left alive to tell it. [Moby Dick, Summary]")
    assert harness.score(answer_item, run(hedged, checked=3))["behavior_ok"]


def test_the_tail_budget_still_passes_the_c08_answers_that_were_measured():
    """The three c08 refusals in docs/eval-results/2026-09-10-local-models.md,
    verbatim: the budget was chosen from them (37 / 36 / 11 words after the
    first marker) and must not re-score the report's own runs."""
    item = {"type": "refusal", "expected_books": []}
    measured = [
        # qwen2.5:7b, both research runs
        'The evidence provided does not contain information about Tom Sawyer making the other '
        'boys pay him for the chance to paint the fence. This information is from "Adventures of '
        'Huckleberry Finn" by Mark Twain, but it does not address the specific question asked.',
        # qwen2.5:14b, research run
        'The provided evidence does not cover how Tom Sawyer made the other boys pay him for the '
        'chance to paint the fence. The evidence is from "Adventures of Huckleberry Finn" and '
        'does not relate to the question about Tom Sawyer\'s fence-painting trick.',
        # qwen3.6 probe (the code's own refusal text)
        "I searched both the book cards and the transcripts, but found no evidence for this "
        "question in the library. Honest answer: I don't know.",
    ]
    for answer in measured:
        assert harness.score(item, run(answer, checked=3))["behavior_ok"], answer


def test_a_refusal_may_end_by_naming_the_passages_it_read():
    """The tail budget is for prose, not for citations. Once every evidence line
    carried a filled label, a refusal that ends by naming the chapters it read
    pays six or seven whitespace tokens per label, and the measured c08 answer
    of `qwen2.5:7b` spends 13 of its 55 tail tokens that way. So labels are
    stripped before the words are counted: the answer below is the c08 refusal
    the budget was READ OFF (37 words, docs/eval-results/2026-09-10-local-models.md)
    with two labels appended, and appending them must not fail it."""
    item = {"type": "refusal", "expected_books": []}
    cited = ('The evidence provided does not contain information about Tom Sawyer making the '
             'other boys pay him for the chance to paint the fence. This information is from '
             '"Adventures of Huckleberry Finn" by Mark Twain, but it does not address the '
             'specific question asked. '
             "[Adventures of Huckleberry Finn — Mark Twain, CHAPTER XXXIV.] "
             "[Adventures of Huckleberry Finn — Mark Twain, CHAPTER XLII.]")
    marker = "does not contain"
    tail = cited[cited.find(marker) + len(marker):]
    assert len(tail.split()) > harness.REFUSAL_TAIL_WORDS     # raw, the labels blow the budget
    assert len(harness.CITATION_RE.sub(" ", tail).split()) == 37   # the prose is the measured one
    assert harness.score(item, run(cited, checked=3))["behavior_ok"]
    # and the rule keeps its teeth: brackets buy no room for a retold episode
    narrated_with_a_citation = (
        "The library does not contain The Adventures of Tom Sawyer. "
        "[Adventures of Huckleberry Finn — Mark Twain, CHAPTER II.] In the novel Tom is set to "
        "whitewash his aunt's fence as a punishment, and when Ben Rogers comes by to jeer at him "
        "he pretends the work is a rare privilege; Ben begs for a turn and gives up his apple "
        "for it, and by the afternoon every boy in the village has traded a kite, twelve "
        "marbles, a piece of blue bottle glass and a dead rat on a string for the chance.")
    assert not harness.score(item, run(narrated_with_a_citation, checked=0))["behavior_ok"]


def test_drilldown_ignores_empty_reads_but_counts_partial_ones():
    item = {"type": "answer", "expected_books": ["Moby Dick"], "expects_chapter_read": True}
    empty = harness.score(item, run("Moby Dick", chapters=["Moby Dick — Herman Melville|Chapter 59|empty"]))
    partial = harness.score(item, run("Moby Dick", chapters=["Moby Dick — Herman Melville|Chapter 59|partial"]))
    legacy = harness.score(item, run("Moby Dick", chapters=["Moby Dick|Chapter 59"]))
    assert not empty["drilldown_ok"] and not empty["behavior_ok"]
    assert partial["drilldown_ok"] and legacy["drilldown_ok"]


def test_drilldown_status_is_read_from_the_right():
    item = {"type": "answer", "expected_books": ["Moby Dick"], "expects_chapter_read": True}
    piped_empty = harness.score(item, run("Moby Dick", chapters=["Moby Dick|Part I|Notes|empty"]))
    piped_partial = harness.score(item, run("Moby Dick", chapters=["Moby Dick|Part I|Notes|partial"]))
    assert not piped_empty["drilldown_ok"] and piped_partial["drilldown_ok"]


def test_clarify_pick_second_scores_the_choice_as_a_diagnostic(monkeypatch):
    monkeypatch.setattr(harness, "CLARIFY_PICK", "second")
    item = {"type": "identify", "expected_behavior": "clarify",
            "expected_books": ["Robinson Crusoe", "Gulliver's Travels"]}
    cands = ["Robinson Crusoe — Daniel Defoe", "Gulliver's Travels — Jonathan Swift"]
    base = {**run("", clarify=True), "clarify_chosen": cands[1], "clarify_unresolved": False}
    applied = harness.score(item, {**base, "answer": "It is Gulliver's Travels by Swift.", "clarify_candidates": cands})
    violated = harness.score(item, {**base, "answer": "Robinson Crusoe fits; Gulliver's Travels too.", "clarify_candidates": cands})
    missing = harness.score(item, {**base, "answer": "Gulliver's Travels.", "clarify_candidates": [cands[0]]})
    assert applied["choice"] == "applied" and applied["behavior_ok"] and applied["others_mentioned"] == 0
    assert violated["choice"] == "applied" and violated["others_mentioned"] == 1   # contrasting the other is fine
    really_violated = harness.score(item, {**base, "answer": "It is Robinson Crusoe.", "clarify_candidates": cands})
    negated = harness.score(item, {**base, "answer": "It is Robinson Crusoe, not Gulliver's Travels.", "clarify_candidates": cands})
    assert negated["choice"] == "violated"
    unresolved = harness.score(item, {**base, "clarify_unresolved": True, "clarify_chosen": "",
                                      "answer": "You wrote Gulliver's Travels; here is Robinson Crusoe.", "clarify_candidates": cands})
    assert unresolved["choice"] == "unresolved"
    mismatch = harness.score(item, {**base, "clarify_chosen": cands[0], "answer": "Gulliver's Travels.", "clarify_candidates": cands})
    assert mismatch["choice"] == "resolver_mismatch"
    assert really_violated["choice"] == "violated" and really_violated["behavior_ok"]   # PASS semantics unchanged
    assert missing["choice"] == "candidate_missing"
    monkeypatch.setattr(harness, "CLARIFY_PICK", None)
    assert "choice" not in harness.score(item, {**base, "answer": "x", "clarify_candidates": cands})
    assert harness.auto_clarify_reply(item).startswith("I can't") or "уточн" in harness.auto_clarify_reply(item)


def _git_stub(answers, failing=()):
    import subprocess

    def fake_run(args, **kwargs):
        class R:
            returncode = 128 if args[1] in failing else 0
            stdout = "" if args[1] in failing else answers.get(args[1], "")
            stderr = "fatal: not a git repository" if args[1] in failing else ""
        return R()
    return fake_run


def test_code_stamp_three_states(monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(subprocess, "run", _git_stub({"rev-parse": "abc1234\n", "status": "", "diff": ""}))
    assert harness.git_code_stamp() == "abc1234"                      # verified clean

    monkeypatch.setattr(subprocess, "run", _git_stub({"rev-parse": "abc1234\n", "status": " M file.py\n", "diff": "-a\n+b\n"}))
    stamp = harness.git_code_stamp()
    assert stamp.startswith("abc1234+dirty(") and len(stamp) == len("abc1234+dirty(") + 13

    monkeypatch.setattr(subprocess, "run", _git_stub({}, failing=("rev-parse",)))
    assert harness.git_code_stamp() == "unknown"                       # git failed: not clean


def test_code_stamp_counts_untracked_source_files(monkeypatch, tmp_path):
    import subprocess

    (tmp_path / "new_module.py").write_text("x = 1\n")
    answers = {"rev-parse": "abc1234\n", "status": "?? new_module.py\n", "diff": ""}

    def fake_run(args, **kwargs):
        class R:
            returncode = 0
            stderr = ""
            stdout = str(tmp_path) + "\n" if args[1:3] == ["rev-parse", "--show-toplevel"] else answers.get(args[1], "")
        return R()

    monkeypatch.setattr(subprocess, "run", fake_run)
    first = harness.git_code_stamp()
    assert first.startswith("abc1234+dirty(")
    (tmp_path / "new_module.py").write_text("x = 2\n")
    assert harness.git_code_stamp() != first                           # content of the untracked file counts


def test_require_clean_refuses_a_dirty_tree(monkeypatch):
    import sys

    import pytest

    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--require-clean"])
    monkeypatch.setattr(harness, "build_graph", lambda: (_ for _ in ()).throw(AssertionError("must not build")))
    for stamp in ("abc1234+dirty(deadbeefdead)", "unknown"):
        monkeypatch.setattr(harness, "git_code_stamp", lambda stamp=stamp: stamp)
        with pytest.raises(SystemExit) as exc:
            harness.main()
        assert exc.value.code == 2


def test_unknown_golden_id_exits_nonzero(monkeypatch, tmp_path):
    import sys
    import pytest

    golden = tmp_path / "g.yaml"
    golden.write_text("questions:\n- id: q01-x\n  question: q\n  type: answer\n  expected_books: [A]\n")
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "q01-typo"])
    monkeypatch.setattr(harness, "build_graph", lambda: (_ for _ in ()).throw(AssertionError("must not build")))
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 2


def test_error_items_keep_the_cost_they_spent(monkeypatch, tmp_path):
    """A question that fails after LLM calls was billed all the same: its cost
    goes into the totals and the mean is per attempted question."""
    import sys
    from ask_your_library import llm
    ev = harness

    def fake_run_one(graph, item):
        llm.reset_usage()
        u = llm._usage()
        u.llm_calls += 2
        u.input_tokens += 1000
        u.output_tokens += 100
        if item["id"] == "bad":
            raise RuntimeError("provider timeout")
        return {"id": item["id"], "type": item["type"], "question": "q", "answer": "a", "verification": "v",
                "provenance": {}, "steps_taken": 1, "read_chapters": [], "evidence_items": 0,
                "clarify_asked": False, "clarify_candidates": [], "clarify_unresolved": False,
                "clarify_chosen": "", "seconds": 1, "steps_log": [], "score": {"behavior_ok": True,
                "titles_mentioned": 0, "titles_expected": 0}, **ev.usage_fields()}

    golden = tmp_path / "golden.yaml"
    golden.write_text("questions:\n- id: good\n  type: answer\n  question: q\n  expected_books: []\n"
                      "- id: bad\n  type: answer\n  question: q\n  expected_books: []\n", encoding="utf-8")
    # The dollar figures below are the hosted list prices; config reads them at
    # import time, so pin them here rather than depend on the developer's
    # LLM_BACKEND (the local mode prices every token at 0). Two namespaces, two
    # readers: llm._cost computes the numbers, the harness imported the same
    # names to print the "configured rates" line, and a report where those two
    # disagree is worse than either of them alone.
    for module in (llm, ev):
        monkeypatch.setattr(module, "PRICE_IN_PER_MTOK", 3.0)
        monkeypatch.setattr(module, "PRICE_OUT_PER_MTOK", 15.0)
    monkeypatch.setattr(ev, "run_one", fake_run_one)
    monkeypatch.setattr(ev, "build_graph", lambda: object())
    monkeypatch.setattr(ev, "run_fingerprint", lambda: "code test")
    monkeypatch.setattr(ev, "GOLDEN_PATH", golden)
    monkeypatch.setattr(ev, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py"])
    try:
        ev.main()
    except SystemExit:
        pass
    report = next(tmp_path.glob("answers-*.md")).read_text(encoding="utf-8")
    assert "spent before the error: $0.0045, 2 calls" in report
    assert "cost $0.0090 total, $0.0045 mean per attempted question (4 LLM calls" in report
    assert "configured rates $3.0/M in, $15.0/M out" in report   # the rates the figures were computed at


def test_fingerprint_names_the_observe_window(monkeypatch):
    """ADR-012: a number measured at one window must never be read as one
    measured at another; the fingerprint names both budgets. The index part
    is allowed to be unavailable in a unit test."""
    monkeypatch.setattr(harness, "git_code_stamp", lambda: "abc1234")
    fp = harness.run_fingerprint()
    from ask_your_library import config
    assert "code abc1234" in fp and f"hit_chars={config.SEARCH_HIT_CHARS}/{config.CHAPTER_HIT_CHARS}" in fp
    # the loop budgets are knobs since the nodes split: a run at MAX_STEPS=6 is another system
    assert f"steps={config.MAX_STEPS}/{config.MAX_EMPTY_STREAK}" in fp
    assert f"candidates={config.MAX_CLARIFY_CANDIDATES}" in fp     # the clarify list length changes clarify behaviour
    assert f"deadline={config.QUESTION_DEADLINE_S}s" in fp        # a run cut by the deadline is another run


def test_the_report_row_and_line_carry_the_planner_fallback(monkeypatch, tmp_path):
    """A planner that never produced a plan completes as an ordinary row since
    0.2; the eval must still show it (that is how a local model is judged)."""
    class FinalGraph:
        checkpointer = None

        def stream(self, run_input, config):
            yield {"plan": {"mode": "answer", "current_query": "q", "queries": [], "plan_fallback": True}}

        def get_state(self, config):
            return type("S", (), {"values": {"answer": "Dracula.", "verification": "OK", "provenance": {},
                                             "steps_taken": 1, "read_chapters": [], "evidence": [{}],
                                             "plan_fallback": True}})()
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    item = {"id": "x", "type": "answer", "question": "q", "expected_books": ["Dracula"]}
    r = harness.run_one(FinalGraph(), item)
    assert r["plan_fallback"] is True


def test_the_report_row_and_line_carry_the_stop_reason(monkeypatch, tmp_path):
    """A run cut by the deadline and one written after "enough" must not read
    the same: the result row carries stop_reason and the steps log records the
    reflect stop, even though reflect emits no query then."""
    class DeadlineGraph:
        checkpointer = None

        def stream(self, run_input, config):
            yield {"plan": {"mode": "answer", "current_query": "q", "queries": []}}
            yield {"reflect": {"current_query": "", "queries": [], "stop_reason": "question deadline (30 s) reached"}}

        def get_state(self, config):
            return type("S", (), {"values": {"answer": "Dracula.", "verification": "OK", "provenance": {},
                                             "steps_taken": 1, "read_chapters": [], "evidence": [{}],
                                             "stop_reason": "question deadline (30 s) reached"}})()
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    item = {"id": "x", "type": "answer", "question": "q", "expected_books": ["Dracula"]}
    r = harness.run_one(DeadlineGraph(), item)
    assert r["stop_reason"] == "question deadline (30 s) reached"
    assert "reflect -> stop: question deadline (30 s) reached" in r["steps_log"]


BOOKS = ["Moby Dick — Herman Melville", "Dracula — Bram Stoker"]


def test_catalog_items_are_scored_on_the_listed_set_not_on_wording():
    item = {"type": "catalog", "expected_books": BOOKS, "expected_count": 2, "expected_total": 2}
    good = {**run("whatever the text says"),
            "catalog": {"op": "list", "count": 2, "total": 2, "books": BOOKS, "resolved": True}}
    assert harness.score(item, good)["behavior_ok"]
    short = {**good, "catalog": {**good["catalog"], "books": BOOKS[:1], "count": 1}}
    assert not harness.score(item, short)["behavior_ok"]
    extra = {**good, "catalog": {**good["catalog"], "count": 3,
                                 "books": BOOKS + ["Ivanhoe — Walter Scott"]}}
    assert not harness.score(item, extra)["behavior_ok"]             # one book too many fails: strict equality
    miscounted = {**good, "catalog": {**good["catalog"], "count": 3}}
    assert not harness.score(item, miscounted)["behavior_ok"]        # the number must be the length of the list
    assert not harness.score(item, run("Moby Dick and Dracula"))["behavior_ok"]   # the research loop: no result


def test_a_listing_of_the_right_size_with_the_wrong_books_fails():
    """Set EQUALITY, not overlap and not a count: two books listed, one of them
    the expected one, is a wrong answer of the right shape."""
    item = {"type": "catalog", "expected_books": BOOKS, "expected_count": 2, "expected_total": 2}
    swapped = {**run(""), "catalog": {
        "op": "list", "count": 2, "total": 2, "resolved": True,
        "books": ["Moby Dick — Herman Melville", "Ivanhoe — Walter Scott"]}}
    verdict = harness.score(item, swapped)
    assert verdict["behavior_ok"] is False
    assert verdict["titles_mentioned"] == 1 and verdict["titles_expected"] == 2


def test_the_right_title_under_the_wrong_author_is_not_the_expected_book():
    """The keys are compared whole, so the author is part of the answer: "do I
    have Ivanhoe?" answered with an Ivanhoe nobody indexed (k03 against wrong
    metadata) used to pass, because the comparison dropped everything after the
    separator."""
    k03 = {"type": "catalog", "expected_books": ["Ivanhoe — Walter Scott"], "expected_op": "has",
           "expected_resolved": True, "expected_total": 33}
    listing = {"op": "has", "count": 1, "total": 33, "resolved": True}
    right = {**run(""), "catalog": {**listing, "books": ["Ivanhoe — Walter Scott"]}}
    wrong = {**run(""), "catalog": {**listing, "books": ["Ivanhoe — Wrong Author"]}}
    assert harness.score(k03, right)["behavior_ok"]
    assert not harness.score(k03, wrong)["behavior_ok"]


def test_a_targeted_run_over_a_partial_catalogue_fails():
    """expected_total is the size of the library the item was written for: the
    same right answer over an index that holds twenty of the thirty-three books
    certifies a benchmark nobody built, so it fails. An item that names no total
    cannot pass at all."""
    k03 = {"type": "catalog", "expected_books": ["Ivanhoe — Walter Scott"], "expected_op": "has",
           "expected_resolved": True, "expected_total": 33}
    listing = {"op": "has", "count": 1, "total": 33, "resolved": True,
               "books": ["Ivanhoe — Walter Scott"]}
    assert harness.score(k03, {**run(""), "catalog": listing})["behavior_ok"]
    partial = {**listing, "total": 20}
    assert not harness.score(k03, {**run(""), "catalog": partial})["behavior_ok"]
    no_total = {k: v for k, v in k03.items() if k != "expected_total"}
    assert not harness.score(no_total, {**run(""), "catalog": listing})["behavior_ok"]


def test_each_count_guard_stands_on_its_own():
    """The two count rules are not the same rule: the state's count must be the
    length of the list it carries, AND it must be what the item expects."""
    listing = {"op": "list", "count": 3, "total": 2, "books": BOOKS, "resolved": True}
    no_expectation = {"type": "catalog", "expected_books": BOOKS, "expected_total": 2}
    assert not harness.score(no_expectation, {**run(""), "catalog": listing})["behavior_ok"]
    honest = {**listing, "count": 2}
    assert harness.score(no_expectation, {**run(""), "catalog": honest})["behavior_ok"]
    assert not harness.score({**no_expectation, "expected_count": 3},
                             {**run(""), "catalog": honest})["behavior_ok"]


def test_a_has_question_must_resolve_as_the_golden_says():
    absent = {"type": "catalog", "expected_books": [], "expected_resolved": False,
              "expected_total": 2}
    r = {**run(""), "catalog": {"op": "has", "count": 0, "total": 2, "books": [], "resolved": False}}
    assert harness.score(absent, r)["behavior_ok"]
    assert not harness.score({**absent, "expected_resolved": True}, r)["behavior_ok"]


def test_an_item_that_expects_nothing_found_still_needs_a_catalogue_to_look_in():
    """"Is War and Peace in my library?" passed over an EMPTY index: nothing
    expected, nothing listed, resolved false. A library of no books answers no
    to every question, which is not the behaviour this item measures."""
    item = {"type": "catalog", "expected_books": [], "expected_resolved": False,
            "expected_op": "has", "expected_total": 33}
    empty = {**run(""), "catalog": {"op": "has", "count": 0, "total": 0, "books": [],
                                    "resolved": False}}
    assert not harness.score(item, empty)["behavior_ok"]
    stocked = {**run(""), "catalog": {**empty["catalog"], "total": 33}}
    assert harness.score(item, stocked)["behavior_ok"]


def test_the_operation_the_code_ran_is_scored_when_the_item_names_one():
    """The same empty result comes back from "has" and from a count over an
    empty shelf; expected_op says which operation the question is about."""
    item = {"type": "catalog", "expected_books": [], "expected_resolved": False,
            "expected_op": "has", "expected_total": 33}
    wrong_op = {**run(""), "catalog": {"op": "count", "count": 0, "total": 33, "books": [],
                                       "resolved": False}}
    assert not harness.score(item, wrong_op)["behavior_ok"]
    right_op = {**wrong_op, "catalog": {**wrong_op["catalog"], "op": "has"}}
    assert harness.score(item, right_op)["behavior_ok"]
    without_op = {k: v for k, v in item.items() if k != "expected_op"}
    assert harness.score(without_op, wrong_op)["behavior_ok"]      # scored as before


def test_a_content_question_answered_by_the_catalogue_fails_whatever_it_lists():
    item = {"type": "answer", "expected_books": ["The Three Musketeers"]}
    assert harness.score(item, run("The Three Musketeers: Athos, Porthos, Aramis"))["behavior_ok"]
    listed = {**run("The Three Musketeers and 32 others"),
              "catalog": {"op": "list", "count": 33, "total": 33, "books": [], "resolved": True}}
    verdict = harness.score(item, listed)
    assert verdict["behavior_ok"] is False and verdict["catalog_misroute"] is True


def test_a_research_control_is_scored_on_routing_alone():
    item = {"type": "answer", "expected_behavior": "research", "expected_books": []}
    routed = {**run("whatever it names"), "steps_taken": 1}
    assert harness.score(item, routed)["behavior_ok"]
    assert not harness.score(item, {**routed, "catalog": {"op": "list", "count": 33, "total": 33, "books": []}})["behavior_ok"]
    assert not harness.score(item, {**routed, "steps_taken": 0})["behavior_ok"]


def test_a_research_control_the_planner_did_not_route_itself_is_not_a_pass():
    """The control measures the planner's reading. A run that searched because
    the planner produced no usable JSON, or because code caught a catalogue
    misroute, searched for another reason: it passed the guards, not the item."""
    item = {"type": "answer", "expected_behavior": "research", "expected_books": []}
    routed = {**run("whatever it names"), "steps_taken": 1}
    assert not harness.score(item, {**routed, "plan_fallback": True})["behavior_ok"]
    assert not harness.score(item, {**routed, "catalog_fallback": "mixed_intent"})["behavior_ok"]
    assert not harness.score(item, {**routed, "catalog_fallback": "invalid_op"})["behavior_ok"]


def test_the_hybrid_filter_must_be_the_expected_book():
    item = {"type": "answer", "expected_books": ["Dracula"], "expected_book_filter": "Dracula"}
    good = {**run("Harker stays because [Dracula, Chapter 2]"), "book_filter": "Dracula — Bram Stoker"}
    assert harness.score(item, good)["behavior_ok"] and harness.score(item, good)["book_filter_ok"]
    wrong = {**good, "book_filter": "The Time Machine — H. G. Wells"}
    assert not harness.score(item, wrong)["behavior_ok"]
    assert not harness.score(item, {**good, "book_filter": ""})["behavior_ok"]

