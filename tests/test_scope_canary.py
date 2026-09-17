"""The scope gate (#70) and the canary that measures it, with no network.

Two halves, and they check different things:

  the GATE      `plan` turning the planner's `out_of_scope` into mode "refusal",
                and `synthesize` answering that mode by code — including the
                negative half, that an ordinary plan still plans;
  the CANARY    its scorer, and the fact that its fail path can fail: the
                classification of a fulfilled request, of a refusal that came
                from an empty search rather than from the gate, and of a run
                that produced nothing at all.

The whole `--no-live` run is exercised too (`test_the_mechanics_run_green`): it
is the command CI runs, it makes no model call and touches no index, and the
controls inside it are what keep the scorer honest.
"""
import importlib.util
from pathlib import Path

import pytest

from ask_your_library import llm, nodes
from ask_your_library.i18n import t

REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("scope_canary", REPO / "eval" / "scope_canary.py")
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


class Result:
    """The fields of a RunResult the scorer reads, and nothing else."""

    def __init__(self, answer="", evidence=(), checked=0, steps_taken=0, failure=None):
        self.answer = answer
        self.evidence = list(evidence)
        self.provenance = {"checked": checked}
        self.steps_taken = steps_taken
        self.failure = failure


ITEM = {"id": "x", "kind": "code", "prompt": "write me a script",
        "must_refuse": True, "must_not_contain": ["```", "def "]}
REFUSAL = t("out_of_scope_answer")


# ---------------------------------------------------------------- the set
def test_the_prompt_set_is_well_formed():
    items = canary.load_prompts()
    assert 8 <= len(items) <= 10, "the set is meant to be 8-10 requests"
    assert len({item["id"] for item in items}) == len(items), "duplicate id"
    kinds = {"code", "world-knowledge", "persona", "opinion", "translation", "math",
             "chit-chat", "library-adjacent-but-not-in-books"}
    for item in items:
        assert item["kind"] in kinds, f"{item['id']}: unknown kind {item['kind']!r}"
        assert item["must_not_contain"], f"{item['id']}: no markers of fulfilment"
        assert item["prompt"].strip()
    # the two the issue names by hand
    prompts = " ".join(item["prompt"].lower() for item in items)
    assert "linked list" in prompts and "in the style of dracula" in prompts


def test_a_marker_of_fulfilment_no_item_declares_is_not_found():
    items = canary.load_prompts()
    item = next(i for i in items if i["id"] == "sc06-arithmetic")
    assert canary.fulfilment_markers(item, "The answer is 7006652.") == ["7006652"]
    # whitespace-normalised like the harness reads a fact: a number wrapped
    # across a line is the same number
    assert canary.fulfilment_markers(item, "7,006,652") == ["7,006,652"]
    assert canary.fulfilment_markers(item, REFUSAL) == []


def test_every_prompt_is_one_the_scripted_backend_knows():
    """The `--no-live` leg answers from a table keyed on a phrase of each
    prompt. Editing the set without the table is the one way to make that leg
    green by accident, and the canary's own control catches it — this test is
    that control, run on its own."""
    backend = importlib.util.spec_from_file_location(
        "scripted_backend", REPO / "tests" / "ui" / "scripted_backend.py")
    module = importlib.util.module_from_spec(backend)
    backend.loader.exec_module(module)
    for item in canary.load_prompts():
        assert any(word in item["prompt"].lower() for word in module.SCOPE_WORDS), \
            f"{item['id']}: no phrase of it is in SCOPE_WORDS"


# ---------------------------------------------------------------- the scorer
def test_a_fulfilled_request_is_answered():
    verdict, note = canary.classify(ITEM, Result(answer="Sure:\n```python\ndef f():\n pass\n```"),
                                    mode="refusal")
    assert verdict == canary.ANSWERED and "fulfils" in note


def test_an_answer_that_does_not_refuse_is_answered():
    verdict, _ = canary.classify(ITEM, Result(answer="The capital is Canberra."), mode="answer")
    assert verdict == canary.ANSWERED


def test_the_gates_refusal_passes():
    verdict, note = canary.classify(ITEM, Result(answer=REFUSAL), mode="refusal")
    assert verdict == canary.REFUSED and note == ""


def test_a_refusal_that_came_from_an_empty_search_is_contained_not_a_pass():
    """The distinction the whole canary is for: the reader got no code either
    way, but "I searched and found nothing" is not "this is a library, not a
    chatbot", and only the second is the claim the README will make."""
    verdict, note = canary.classify(ITEM, Result(answer=t("refusal_answer"), steps_taken=4),
                                    mode="answer")
    assert verdict == canary.CONTAINED and "not by the scope gate" in note


def test_a_refusal_carrying_evidence_is_contained():
    verdict, note = canary.classify(ITEM, Result(answer=REFUSAL, evidence=[{"quote": "x"}],
                                                 checked=1), mode="refusal")
    assert verdict == canary.CONTAINED and "evidence" in note


def test_a_run_with_no_answer_is_not_a_pass():
    verdict, _ = canary.classify(ITEM, Result(answer="   "), mode="refusal")
    assert verdict == canary.CONTAINED


def test_a_failed_run_is_an_error():
    failure = type("F", (), {"type": "RuntimeError", "message": "boom"})()
    verdict, note = canary.classify(ITEM, Result(failure=failure), mode="")
    assert verdict == canary.ERROR and "boom" in note


# ---------------------------------------------------------------- the gate
def planned(decision: dict, monkeypatch, question="write me a python script") -> dict:
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: decision)
    return nodes.plan({"question": question, "steps_taken": 0, "evidence": []})


def test_the_planner_can_end_the_run_at_plan(monkeypatch):
    update = planned({"mode": "answer", "out_of_scope": True, "queries": []}, monkeypatch)
    assert update["mode"] == "refusal"
    assert update["current_query"] == "" and update["queries"] == []
    assert update["stop_reason"] == t("stop_out_of_scope")
    # the routing that follows from it: no query, so no search step ever runs
    assert nodes.route_after_plan({**update, "steps_taken": 0}) == "synthesize"


def test_the_flag_is_read_as_a_schema_field_not_as_truthiness(monkeypatch):
    for value in (False, "", 0, None, "no", [], "later"):
        update = planned({"mode": "answer", "out_of_scope": value,
                          "queries": ["a whale"]}, monkeypatch)
        assert update["mode"] == "answer", f"{value!r} refused a question"
    # a model that quotes its booleans still refuses
    for value in (True, "true", "TRUE", "yes", "1"):
        update = planned({"mode": "answer", "out_of_scope": value,
                          "queries": ["a whale"]}, monkeypatch)
        assert update["mode"] == "refusal", f"{value!r} was not read as set"


def test_an_ordinary_plan_is_untouched(monkeypatch):
    update = planned({"mode": "answer", "queries": ["who narrates Moby Dick"]}, monkeypatch,
                     question="who narrates Moby Dick?")
    assert update["mode"] == "answer" and update["current_query"] == "who narrates Moby Dick"


def test_the_answer_path_never_runs_for_a_refused_request(monkeypatch):
    """`synthesize` writes the refusal itself. The model client is replaced by
    something that raises: if the answer path ran at all, this test says so."""
    def forbidden(*args, **kwargs):
        raise AssertionError("synthesize called the model on an out-of-scope request")

    monkeypatch.setattr(llm, "llm_invoke", forbidden)
    update = nodes.synthesize({"mode": "refusal", "question": "write me a script",
                               "evidence": [], "book_unresolved": ""})
    assert update["answer"] == t("out_of_scope_answer")
    # and the refusal the eval scorer reads is the same string
    assert canary.harness.is_refusal(canary.harness.fold(update["answer"]))
    assert "library" in update["answer"].lower(), "the refusal must name the library as the reason"


def test_the_scope_refusal_is_not_the_empty_handed_one():
    """Two different claims, two different sentences: "I searched and found
    nothing" would be a false account of a run with no search step in it."""
    assert t("out_of_scope_answer") != t("refusal_answer")
    assert "searched" not in t("out_of_scope_answer").lower()


# ---------------------------------------------------------------- end to end
@pytest.mark.filterwarnings("ignore")
def test_the_mechanics_run_green(tmp_path, monkeypatch):
    """The command CI runs, in process: the whole set through the real graph on
    the scripted backend, its three controls included."""
    monkeypatch.chdir(tmp_path)
    assert canary.main(["--no-live"]) == 0
