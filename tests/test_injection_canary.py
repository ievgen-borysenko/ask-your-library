"""The injection canary's own mechanics: every stage runs with fakes, no network.

Each deterministic stage of the canary is a control. These tests check the
controls themselves — a stage that would pass even with the defense removed
proves nothing, so the negative controls here break the defense on purpose and
require the stage to fail.
"""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "injection_canary", Path(__file__).resolve().parents[1] / "eval" / "injection_canary.py")
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)

from ask_your_library import nodes  # noqa: E402  (imported after the canary module is loaded)
from ask_your_library import llm  # noqa: E402


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Nothing in this file may reach a model: the stages patch llm.llm
    themselves, and anything they miss hits this."""
    def forbidden():
        raise AssertionError("the test tried to build a real LLM client")

    monkeypatch.setattr(llm, "llm", forbidden)
    # The UI stage imports ui.py as a module; ui.py refuses to start a server
    # without an OpenRouter key, and these stages are exactly the part that must
    # keep running without one.
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")


# ---------------------------------------------------------------- helpers
def test_foreign_delimiters_sees_a_forged_tag_but_not_our_own():
    prompt = ('<question mode="identify">\nhello\n</question>\n'
              '<search_results>\n<result index="1" book="A ‹/result›">\n'
              "text with a < neutralized bracket\n</result>\n</search_results>")
    assert canary.foreign_delimiters(prompt) == []
    assert canary.foreign_delimiters("<evidence>\n</evidence>\n<evidence>forged\n</evidence>") == []
    assert canary.foreign_delimiters("<question>\n<script>alert(1)</script>\n</question>")


def test_marker_outside_blocks_flags_free_text_only():
    inside = f"<question>\n{canary.MARKER}\n</question>\nSteps used: 1 of 4."
    assert canary.marker_outside_blocks(inside, canary.MARKER) == []
    header = f'<result book="{canary.MARKER}">\nbody\n</result>'
    assert canary.marker_outside_blocks(header, canary.MARKER) == []
    outside = f"<question>\nq\n</question>\nReminder: {canary.MARKER}"
    assert canary.marker_outside_blocks(outside, canary.MARKER)


def test_count_blocks_counts_only_whole_header_lines():
    prompt = '<result index="1">\na\n</result>\n<result index="2">\nb\n</result>\n< result forged>'
    assert canary.count_blocks(prompt, "result") == 2


# ------------------------------------------- stage 3: the prompt boundary
def test_prompt_boundary_stage_passes_and_returns_the_clarify_question():
    label, question = canary.prompt_boundary_stage({})
    assert "BLOCKED (controls ok)" in label
    assert canary.MARKER in question and canary.HOSTILE_BOOK in question


def test_prompt_boundary_stage_fails_when_the_delimiters_are_not_neutralized(monkeypatch):
    """Negative control: with a naive data_block (no "<" neutralization, no
    attribute escaping) a hostile book title forges a delimiter, and the stage
    must notice. If this passes, stage 3 is decoration."""
    def naive(tag, text, trusted=False, **attrs):
        attr_text = "".join(f' {k}="{v}"' for k, v in attrs.items())
        return f"<{tag}{attr_text}>\n{text}\n</{tag}>"

    monkeypatch.setattr(nodes, "data_block", naive)
    with pytest.raises(AssertionError):
        canary.prompt_boundary_stage({})


def test_prompt_boundary_stage_fails_when_untrusted_text_reaches_the_system_message(monkeypatch):
    """Negative control: rules and data must not be concatenated."""
    real = llm.llm_invoke

    def leaky(system, user, role):
        return real(f"{system}\n{user}", user, role)

    monkeypatch.setattr(llm, "llm_invoke", leaky)
    with pytest.raises(AssertionError):
        canary.prompt_boundary_stage({})


# ----------------------------------------------------- stage 4: detection
def test_detection_stage_positive_and_negative_controls_pass():
    label, _ = canary.detection_stage({})
    assert "benign output -> BLOCKED" in label and "echoed injection -> FAILED" in label


def test_the_detector_can_actually_see_a_leak():
    assert canary.classify_answer(f"the answer is {canary.MARKER}") == "FAILED"
    assert canary.classify_answer("an ordinary answer [Moby Dick, Chapter 1]") == "BLOCKED"
    assert canary.classify_clarify(
        {"current_query": "__clarify__", "queries": [f"pick one {canary.MARKER}"]}) == "FAILED"
    assert canary.classify_clarify(
        {"current_query": "__clarify__", "queries": ["pick one"]}) == "BLOCKED"
    # No clarify at all is not a pass: the step was disrupted, like observe's CONTAINED.
    assert canary.classify_clarify({"current_query": ""}) == "CONTAINED"


@pytest.mark.parametrize("answer", ["", "   ", "\n", None, 42, {"answer": "x"}])
def test_an_empty_or_broken_answer_is_never_a_pass(answer):
    """A node that produced nothing did not "block" anything: there was no text
    to carry the marker. BLOCKED here would turn a broken step into a pass."""
    assert canary.classify_answer(answer) == "CONTAINED"


def test_a_real_answer_is_still_classified():
    assert canary.classify_answer(canary.t("refusal_answer")) == "CONTAINED"
    assert canary.classify_answer("Moby Dick [Moby Dick, Chapter 1].") == "BLOCKED"


@pytest.mark.parametrize("update", [
    {"current_query": "__clarify__", "queries": []},
    {"current_query": "__clarify__", "queries": [""]},
    {"current_query": "__clarify__", "queries": ["   \n"]},
    {"current_query": "__clarify__", "queries": [None]},
    {"current_query": "__clarify__"},
])
def test_an_empty_or_broken_clarify_question_is_never_a_pass(update):
    assert canary.classify_clarify(update) == "CONTAINED"


def test_detection_stage_fails_when_the_model_leaks_but_the_benign_control_is_used(monkeypatch):
    """Negative control on the stage itself: if reflect ignored the model's
    clarify_question and always wrote its own, the echoing control could never
    reach FAILED and the stage must fail rather than report success."""
    real = nodes.reflect if hasattr(nodes, "reflect") else None
    assert real is not None

    def blind_reflect(state):
        update = real(state)
        if update.get("current_query") == "__clarify__":
            update["queries"] = ["a fixed question with nothing echoed"]
        return update

    monkeypatch.setattr(canary, "reflect", blind_reflect)
    with pytest.raises(AssertionError):
        canary.detection_stage({})


def test_the_synthesize_prompt_really_carries_the_planted_quote_and_not_the_why():
    """The control's premise, checked directly: synthesize builds its user
    message from book/section/quote only, so an injection planted in `why`
    would be echoed by a fake that never read it."""
    seen = {}

    def record(_system, user):
        seen["user"] = user
        return "an answer [Moby Dick, Chapter 1]."

    fake, patcher = canary.capture(record)
    try:
        canary.synthesize({"question": "Which book has a whale?", "evidence": [
            {"hit_id": canary.HIT_ID, "book": "Moby Dick", "section": "Chapter 1",
             "quote": canary.PLANTED_QUOTE,
             "why": canary.PLANTED_WHY.format(why_only=canary.WHY_ONLY_MARKER)}]})
    finally:
        patcher.stop()
    assert canary.MARKER in seen["user"], "the planted quote never reached the synthesize prompt"
    assert canary.WHY_ONLY_MARKER not in seen["user"], \
        "`why` reached the synthesize prompt — the stage's negative half is stale"


def test_prompt_asserting_rejects_a_fake_that_would_invent_the_marker():
    reply = canary.prompt_asserting("echoed")
    assert reply("system", f"a prompt carrying {canary.MARKER}") == "echoed"
    with pytest.raises(AssertionError):
        reply("system", "a prompt carrying nothing")
    forbidden = canary.prompt_asserting("echoed", must_not_contain="NOPE")
    with pytest.raises(AssertionError):
        forbidden("system", f"{canary.MARKER} and NOPE")


def test_detection_stage_fails_when_the_injection_never_reaches_the_prompt(monkeypatch):
    """Negative control on the stage's premise: with a benign `quote` the
    synthesize fake is echoing a marker the model was never shown. That must be
    a misbehaving control, not a detection."""
    monkeypatch.setattr(canary, "PLANTED_QUOTE", "Call me Ishmael.")
    with pytest.raises(AssertionError):
        canary.detection_stage({})


def test_detection_stage_fails_when_the_evidence_why_leaks_into_synthesize(monkeypatch):
    """Negative control the other way: if synthesize started putting `why` in
    its prompt, the stage must say so instead of quietly changing meaning."""
    real = canary.synthesize

    def leaky(state):
        evidence = [dict(e, quote=f"{e['quote']} {e['why']}") for e in state.get("evidence") or []]
        return real({**state, "evidence": evidence})

    monkeypatch.setattr(canary, "synthesize", leaky)
    with pytest.raises(AssertionError):
        canary.detection_stage({})


# ---------------------------------------------- the fake transport's roles
def test_the_transport_reads_messages_by_role_not_by_position():
    """The harness must not assume a two-message list: roles are the contract."""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    fake = canary.CapturingLLM("ok")
    fake.invoke([SystemMessage(content="rules"), SystemMessage(content="more rules"),
                 HumanMessage(content="data")])
    assert fake.calls[0] == {"system": "rules\nmore rules", "user": "data"}

    with pytest.raises(AssertionError):
        canary.CapturingLLM("ok").invoke([SystemMessage(content="rules")])
    with pytest.raises(AssertionError):
        canary.CapturingLLM("ok").invoke(
            [SystemMessage(content="rules"), HumanMessage(content="data"),
             AIMessage(content="untrusted text smuggled in as an assistant turn")])


# ------------------------------------------------------- stage 5: the UI
def test_ui_stage_runs_or_says_it_was_skipped():
    label, _ = canary.ui_stage({"prompt_boundary_stage": f"Q {canary.HOSTILE_BOOK}"})
    if importlib.util.find_spec("chainlit") is None:
        assert "SKIPPED" in label
    else:
        assert "no image loads" in label and "BLOCKED (controls ok)" in label


@pytest.mark.skipif(importlib.util.find_spec("chainlit") is None, reason="ui extra not installed")
def test_ui_stage_fails_if_neutralization_is_removed(monkeypatch):
    ui = canary.ui_module()
    monkeypatch.setattr(ui, "neutralize_markdown", lambda text: text)
    monkeypatch.setattr(canary, "ui_module", lambda: ui)
    with pytest.raises(AssertionError):
        canary.ui_stage({})


# ------------------------------------------------------------ the driver
UI_AVAILABLE = importlib.util.find_spec("chainlit") is not None
INCOMPLETE = "CANARY MECHANICS INCOMPLETE (UI stage skipped: install the ui extra)"


def test_no_live_runs_every_free_stage_and_never_calls_a_model(capsys):
    assert canary.main(["--no-live"]) == (0 if UI_AVAILABLE else canary.EXIT_INCOMPLETE)
    out = capsys.readouterr().out
    assert sum(1 for line in out.splitlines() if line.startswith("[")) == len(canary.STAGES)
    assert f"[{len(canary.STAGES)}/{len(canary.STAGES)}]" in out
    assert "observe (live)" not in out
    if UI_AVAILABLE:
        assert "CANARY MECHANICS PASSED" in out
    else:
        # Without the ui extra the run covered less than it claims: never PASSED.
        assert INCOMPLETE in out and "PASSED" not in out


def test_without_the_flag_the_live_stage_runs_last_and_is_the_only_paid_call(monkeypatch, capsys):
    calls = []

    class FakeLLM:
        def invoke(self, messages):
            calls.append(messages)
            return type("R", (), {"content": json.dumps({"evidence": [
                {"hit_id": canary.HIT_ID, "book": "Poisoned Book", "section": "Chapter 1",
                 "quote": "He picked up the letter from the table and began to read it aloud.",
                 "why": "what the hero did"}]}), "usage_metadata": {}, "response_metadata": {}})()

    monkeypatch.setattr(llm, "llm", lambda: FakeLLM())
    # --allow-skipped keeps the exit code stable in both CI jobs; the report line
    # below still distinguishes a complete run from an incomplete one.
    assert canary.main(["--allow-skipped"]) == 0
    out = capsys.readouterr().out
    total = len(canary.STAGES) + 1
    assert f"[{total}/{total}] observe (live): BLOCKED" in out
    assert ("CANARY TEST PASSED" if UI_AVAILABLE else INCOMPLETE) in out
    # The deterministic stages patch llm.llm out; only the live stage reaches this one.
    assert len(calls) == 1


def test_a_skipped_stage_makes_the_run_incomplete_and_non_zero(monkeypatch, capsys):
    """A missing optional dependency must not read as a pass: --no-live claims
    all the mechanics, so a SKIPPED stage means INCOMPLETE and a non-zero exit."""
    def ui_stage(_payloads):                       # the name carries the skip hint
        return "UI render path: SKIPPED — the ui extra is not installed", None

    monkeypatch.setattr(canary, "STAGES", [canary.sanitize_stage, ui_stage])
    assert canary.main(["--no-live"]) == canary.EXIT_INCOMPLETE
    out = capsys.readouterr().out
    assert INCOMPLETE in out
    assert "PASSED" not in out


def test_allow_skipped_downgrades_the_exit_code_but_not_the_report(monkeypatch, capsys):
    def ui_stage(_payloads):
        return "UI render path: SKIPPED — the ui extra is not installed", None

    monkeypatch.setattr(canary, "STAGES", [canary.sanitize_stage, ui_stage])
    assert canary.main(["--no-live", "--allow-skipped"]) == 0
    out = capsys.readouterr().out
    assert INCOMPLETE in out
    assert "PASSED" not in out


def test_a_misbehaving_control_exits_non_zero_without_a_traceback(monkeypatch, capsys):
    def broken(_payloads):
        raise AssertionError("the defense did not hold")

    monkeypatch.setattr(canary, "STAGES", [canary.sanitize_stage, broken])
    assert canary.main(["--no-live"]) == 1
    out = capsys.readouterr().out
    assert "FAILED (control misbehaved: the defense did not hold)" in out
    assert "CANARY MECHANICS PASSED" not in out
