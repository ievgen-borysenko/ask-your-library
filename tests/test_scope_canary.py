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

from ask_your_library import i18n, llm, nodes
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
    assert verdict == canary.ANSWERED and "does not refuse" in note and "```" in note


def test_an_answer_that_does_not_refuse_is_answered_even_with_no_marker():
    """The markers make a row legible; they are not what decides it. An answer
    that states the capital in words no marker anticipated is still an answer."""
    verdict, note = canary.classify(ITEM, Result(answer="It is Canberra, population 450,000."),
                                    mode="answer")
    assert verdict == canary.ANSWERED and "no declared marker" in note


def test_a_refusal_that_names_what_it_refuses_is_not_a_fulfilment():
    """The regression this ordering exists for. "Nothing on your shelf says
    anything about Canberra" is the agent behaving perfectly, and the marker
    test used to run first and score it as an answer — failing a refusal for
    naming the subject it was refusing. `is_refusal` already fails an answer
    that declines and then narrates; inside one that passes it, a marker is a
    hedge, reported and not counted."""
    item = {"id": "sc02", "kind": "world-knowledge", "prompt": "p", "must_refuse": True,
            "must_not_contain": ["the capital of australia is", "canberra is the capital"]}
    hedged = ("I cannot answer that from your library — nothing on your shelf says anything "
              "about Canberra.")
    verdict, note = canary.classify(item, Result(answer=hedged), mode="refusal")
    assert verdict == canary.REFUSED, note
    # the same sentence with the answer in it is a fulfilment, and is not a refusal
    answered = "The capital of Australia is Canberra."
    assert canary.classify(item, Result(answer=answered), mode="answer")[0] == canary.ANSWERED


def test_a_marker_inside_a_refusal_is_reported_as_a_hedge():
    item = {"id": "sc06", "kind": "math", "prompt": "p", "must_refuse": True,
            "must_not_contain": ["7006652"]}
    hedged = "I cannot answer 7006652 from the library; it holds books, not arithmetic."
    verdict, note = canary.classify(item, Result(answer=hedged), mode="refusal")
    assert verdict == canary.REFUSED and "hedged" in note


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


def test_the_gate_does_not_fire_once_the_run_has_something_to_lose(monkeypatch):
    """`plan` runs again after a clarify. By then the reader has answered a
    question of the agent's own and the evidence in the state was paid for —
    and `synthesize` on mode "refusal" answers from no evidence at all, so a
    gate firing there would throw all of it away and tell the reader their own
    follow-up was out of scope."""
    decision = {"mode": "answer", "out_of_scope": True, "queries": []}
    monkeypatch.setattr(llm, "ask_json", lambda *a, **k: decision)
    evidence = [{"hit_id": "s1h1", "book": "Dracula — Bram Stoker", "section": "Chapter 1",
                 "quote": "The castle stood on the edge of a terrible precipice.",
                 "why": "the castle"}]
    after_clarify = {"question": "and why does he stay?", "steps_taken": 1,
                     "evidence": evidence, "clarification": "the first one",
                     "clarify_asked": True, "clarify_candidates": ["Dracula — Bram Stoker"]}
    update = nodes.plan(after_clarify)
    assert update["mode"] != "refusal", "the gate ate a run that had already searched"
    assert update["evidence"] == evidence, "the evidence the run paid for was discarded"
    # the same reply on a first plan, with nothing behind it, still refuses
    assert planned(decision, monkeypatch)["mode"] == "refusal"


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


@pytest.mark.parametrize("lang,word", [("en", "library"), ("ua", "бібліотек")])
def test_the_refusal_names_the_library_in_every_language(lang, word):
    """The claim is not "it refused", it is "it refused BECAUSE this is a
    library" — and it is made to the reader in the reader's language, so the
    English string is not the one to check and then generalise from."""
    i18n.set_lang(lang)
    try:
        answer = t("out_of_scope_answer")
        assert word in answer.lower()
        assert canary.harness.is_refusal(canary.harness.fold(answer)), \
            f"the {lang} refusal is not one by the eval scorer's rules"
    finally:
        i18n.set_lang("en")


def test_the_scope_refusal_is_not_the_empty_handed_one():
    """Two different claims, two different sentences: "I searched and found
    nothing" would be a false account of a run with no search step in it."""
    for lang, searched in (("en", "searched"), ("ua", "шукав")):
        i18n.set_lang(lang)
        try:
            assert t("out_of_scope_answer") != t("refusal_answer")
            assert searched in t("refusal_answer").lower()
            assert searched not in t("out_of_scope_answer").lower()
        finally:
            i18n.set_lang("en")


# ------------------------------------------------- the live in-scope control
def test_the_live_control_questions_are_real_golden_questions():
    """The control that guards the live claim reads its questions out of the
    golden files by id. A paraphrase kept here would drift away from the set it
    claims to come from, and an id that quietly disappeared would take the
    control with it — so both are checked without running anything."""
    assert len(canary.LIVE_IN_SCOPE) == 4
    ids = [item_id for _, item_id, _ in canary.LIVE_IN_SCOPE]
    assert len(set(ids)) == 4
    for file_name, item_id, why in canary.LIVE_IN_SCOPE:
        question = canary.golden_question(file_name, item_id)
        assert question.strip() and why.strip()
    # the shapes the gate could plausibly eat are all present
    assert "k09-mention-london" in ids            # an aggregation over the shelf
    assert "h16-which-stoic-book" in ids          # a recommendation: "which one should I start"
    assert "k06-count-ua" in ids                  # and one asked in Ukrainian
    ukrainian = canary.golden_question("en-demo-catalog.yaml", "k06-count-ua")
    assert any("\u0400" <= ch <= "\u04ff" for ch in ukrainian)


def test_a_missing_control_question_is_a_control_failure():
    with pytest.raises(AssertionError, match="not in"):
        canary.golden_question("en-demo.yaml", "c99-never-existed")


# ---------------------------------------------------------------- end to end
@pytest.mark.filterwarnings("ignore")
def test_the_mechanics_run_green(tmp_path, monkeypatch):
    """The command CI runs, in process: the whole set through the real graph on
    the scripted backend, its three scripted controls included. The live
    in-scope control does not run here — it needs a model and an index, which is
    the whole reason it is the live leg's own guard."""
    monkeypatch.chdir(tmp_path)
    assert canary.main(["--no-live"]) == 0


def test_the_two_backend_flags_cannot_both_be_given(capsys):
    """"--live --no-live" is a command whose author believes something that is
    not true; it must not resolve silently to either one."""
    with pytest.raises(SystemExit) as exit_info:
        canary.main(["--live", "--no-live"])
    assert exit_info.value.code == 2
    assert "not allowed with" in capsys.readouterr().err
