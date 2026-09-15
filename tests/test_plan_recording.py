"""Recording the planner: the `llm.JSON_CALL_OBSERVER` seam, what one line of a
recording holds, and `--record-plans` on the main harness.

No model, no network, no graph: `llm.llm_invoke` is scripted, so every call goes
through the REAL `ask_json` — which is where the observer lives — and comes back
with the reply the test wrote. What is under test is the record left behind: that
it carries what a replay needs, that it carries only the planner, that a path
that names the machine never reaches it, and that a recorder can neither change
what a call returns nor lose what a crashed run already paid for.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ask_your_library import llm
from ask_your_library.prompts import PLAN_RULES

REPO = Path(__file__).resolve().parents[1]


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


plan_recording = load("plan_recording")
harness = load("run_agent_eval")

FACTS = {"golden_name": "en-demo.yaml", "golden_path": "eval/golden/en-demo.yaml",
         "golden_sha256_12": "abcdef012345", "model": "anthropic/claude-sonnet-4.6",
         "backend": "openrouter", "code": "1b88943", "code_clean": True, "repeat": 1}

PLAN_REPLY = '{"mode": "answer", "queries": ["whale", "white whale"]}'


class Reply:
    """What `llm_invoke` returns: anything with a `.content`."""

    def __init__(self, content):
        self.content = content


def scripted(monkeypatch, *replies):
    """`llm_invoke` handing back `replies` in order, and recording what it was
    asked. Nothing else of the model path is replaced, so the observer under
    test is reached through the real `ask_json`."""
    seen = []

    def invoke(system, user, role):
        seen.append((system, user, role))
        return Reply(replies[min(len(seen) - 1, len(replies) - 1)])

    monkeypatch.setattr(llm, "llm_invoke", invoke)
    return seen


def lines_of(path: Path) -> list:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# --- the file's identity ------------------------------------------------------
def test_the_name_carries_the_golden_checksum_and_the_model():
    name = plan_recording.recording_name("en-demo.yaml", "abcdef012345",
                                         "anthropic/claude-sonnet-4.6")
    assert name == "en-demo.abcdef012345.anthropic-claude-sonnet-4.6.jsonl"
    # the slash of a model id must not become a directory
    assert "/" not in name


def test_the_header_carries_the_golden_and_prompt_checksums(tmp_path):
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        pass
    header = lines_of(recorder.path)[0]
    assert header["kind"] == "header"
    assert header["schema"] == plan_recording.SCHEMA
    assert header["golden_sha256_12"] == "abcdef012345"
    # the hash of the prompt the replies answered: the whole staleness rule
    assert header["plan_rules_sha256_12"] == plan_recording.sha12(PLAN_RULES)
    assert header["model"] == "anthropic/claude-sonnet-4.6"


# --- one call -----------------------------------------------------------------
def test_a_plan_call_is_recorded_with_what_it_asked_and_what_came_back(monkeypatch, tmp_path):
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS,
                                     knobs={"temperature": 0}) as recorder:
        with recorder.item("c01-ivanhoe", attempt=2):
            assert llm.ask_json(PLAN_RULES, "<question>whales</question>", role="plan") == {
                "mode": "answer", "queries": ["whale", "white whale"]}
    call = lines_of(recorder.path)[1]
    assert call["kind"] == "call"
    assert (call["id"], call["attempt"], call["call"]) == ("c01-ivanhoe", 2, 1)
    assert call["role"] == "plan"
    assert call["user"] == "<question>whales</question>"      # the exact payload
    assert call["raw"] == PLAN_REPLY                          # the raw reply text
    assert call["error"] == ""
    # the prompt is identified, never copied into the file
    assert call["system_sha256_12"] == plan_recording.sha12(PLAN_RULES)
    assert PLAN_RULES[:40] not in json.dumps(call)
    assert call["model"] == "anthropic/claude-sonnet-4.6" and call["backend"] == "openrouter"
    assert call["temperature"] == 0
    assert call["timestamp"] and set(("cost_usd", "tokens_in", "tokens_out")) <= set(call)


def test_both_attempts_of_a_retry_are_recorded(monkeypatch, tmp_path):
    """`ask_json` retries a malformed reply once, and the recording keeps both:
    a replay that dropped the bad first one would replay a retry that never
    happened — and, worse, would silently succeed where the run degraded."""
    scripted(monkeypatch, "not json at all", PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, "payload", role="plan")
    calls = lines_of(recorder.path)[1:]
    assert [(c["call"], c["json_attempt"]) for c in calls] == [(1, 1), (1, 2)]
    assert calls[0]["raw"] == "not json at all"
    assert calls[1]["raw"] == PLAN_REPLY


def test_two_plan_calls_of_one_item_are_numbered(monkeypatch, tmp_path):
    """A clarify sends the run back through `plan`; the second decision is a
    second line of the same item, not a replacement for the first."""
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c09"):
            llm.ask_json(PLAN_RULES, "first", role="plan")
            llm.ask_json(PLAN_RULES, "after the clarify", role="plan")
    assert [c["call"] for c in lines_of(recorder.path)[1:]] == [1, 2]


# --- what is NOT recorded -----------------------------------------------------
def test_only_the_planner_is_recorded(monkeypatch, tmp_path):
    scripted(monkeypatch, '{"decision": "enough"}')
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            llm.ask_json("reflect rules", "payload", role="reflect")
            llm.ask_json("observe rules", "payload", role="observe")
    assert lines_of(recorder.path)[1:] == []      # header only


def test_a_call_outside_an_item_is_not_recorded(monkeypatch, tmp_path):
    """A recording line has to belong to a golden id and an attempt, or a replay
    could not find it. A call made between items is dropped rather than filed
    under whichever item ran last."""
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        llm.ask_json(PLAN_RULES, "payload", role="plan")
    assert lines_of(recorder.path)[1:] == []


def test_absolute_paths_are_redacted_from_the_payload_and_the_reply(monkeypatch, tmp_path):
    """A recording is committed. A path under the home directory in a payload or
    a reply is the reader's login, and `redact_paths` is the same function the
    report and the sidecar already pass every error message through."""
    home_path = f"{Path.home()}/private/library/notes.txt"
    repo_path = f"{REPO}/eval/golden/en-demo.yaml"
    scripted(monkeypatch, '{"mode": "answer", "queries": ["' + repo_path + '"]}')
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS,
                                     redact=harness.redact_paths) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, f"<question>{home_path}</question>", role="plan")
    written = recorder.path.read_text(encoding="utf-8")
    assert str(Path.home()) not in written and str(REPO) not in written
    call = lines_of(recorder.path)[1]
    assert call["user"] == "<question>~/private/library/notes.txt</question>"
    assert "<repo>/eval/golden/en-demo.yaml" in call["raw"]


# --- the seam cannot hurt the run ---------------------------------------------
def test_an_observer_that_raises_does_not_fail_the_call(monkeypatch):
    """A recorder rides on a run that costs money. Its own failure is logged and
    swallowed: losing the recording is cheap, losing the run is not."""
    scripted(monkeypatch, PLAN_REPLY)

    def explode(call):
        raise RuntimeError("the disk is full")

    monkeypatch.setattr(llm, "JSON_CALL_OBSERVER", explode)
    assert llm.ask_json(PLAN_RULES, "payload", role="plan")["mode"] == "answer"


def test_no_observer_is_installed_by_default():
    assert llm.JSON_CALL_OBSERVER is None


def test_the_observer_is_restored_after_the_block(monkeypatch, tmp_path):
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS):
        assert llm.JSON_CALL_OBSERVER is not None
    assert llm.JSON_CALL_OBSERVER is None


def test_a_crashed_run_keeps_its_partial_recording(monkeypatch, tmp_path):
    """The final name means "a run that finished". A run that died mid-way
    leaves everything it managed to record under `.partial` — those calls were
    paid for, and the point of the whole change is not to pay twice."""
    scripted(monkeypatch, PLAN_REPLY)
    final = tmp_path / "r.jsonl"
    with pytest.raises(RuntimeError):
        with plan_recording.PlanRecorder(final, FACTS) as recorder:
            with recorder.item("c01"):
                llm.ask_json(PLAN_RULES, "payload", role="plan")
            raise RuntimeError("the run died")
    assert not final.exists()
    assert len(lines_of(recorder.partial)) == 2


# --- the flag on the main harness ---------------------------------------------
GOLDEN = ("questions:\n"
          "- id: q01-moby\n  type: answer\n  question: Which whale?\n"
          "  expected_books: [Moby Dick]\n  expected_facts: [Pequod]\n"
          "- id: q02-drac\n  type: identify\n  question: Which castle?\n"
          "  expected_books: [Dracula]\n  expected_facts: []\n")


def test_record_plans_writes_the_recording_of_a_whole_run(monkeypatch, tmp_path):
    """`--record-plans` on eval/run_agent_eval.py: one recording per golden set,
    one line per item and attempt, written by the run that was happening anyway.

    The graph is replaced by a `run_one` that makes the planner's call and
    nothing else, with `llm_invoke` scripted — so the line under test is
    produced by the real `ask_json` through the real observer."""
    seen = scripted(monkeypatch, PLAN_REPLY)
    golden = tmp_path / "en-demo.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    recordings = tmp_path / "recordings"
    monkeypatch.setenv("AYL_PLAN_RECORDINGS_DIR", str(recordings))
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "build_graph", lambda: object())
    monkeypatch.setattr(harness, "run_facts", lambda repeat=1: {**FACTS, "repeat": repeat})
    monkeypatch.setattr(harness, "render_fingerprint", lambda facts: "code 1b88943 | single run")

    def fake_run_one(graph, item, attempt=1):
        llm.ask_json(PLAN_RULES, f"<question>{item['question']}</question>", role="plan")
        return {"id": item["id"], "type": item["type"], "question": item["question"],
                "answer": "Moby Dick aboard the Pequod", "verification": "0/0",
                "provenance": {}, "steps_taken": 1, "read_chapters": [], "evidence_items": 0,
                "clarify_asked": False, "clarify_candidates": [], "clarify_unresolved": False,
                "clarify_chosen": "", "plan_fallback": False, "stop_reason": "", "catalog": {},
                "book_filter": "", "book_unresolved": "", "catalog_fallback": "", "seconds": 0,
                "steps_log": [], "cost_usd": 0.0, "llm_calls": 1, "tokens_in": 1,
                "tokens_out": 1,
                "score": {"titles_mentioned": 1, "titles_expected": 1, "facts_found": 0,
                          "facts_expected": 0, "facts_ok": True, "behavior_ok": True}}

    monkeypatch.setattr(harness, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--record-plans", "--repeat", "2"])
    harness.main()

    path = recordings / "en-demo.abcdef012345.anthropic-claude-sonnet-4.6.jsonl"
    assert path.exists(), sorted(p.name for p in recordings.iterdir())
    records = lines_of(path)
    assert records[0]["kind"] == "header"
    # one line per item AND per attempt, which is what --repeat asks for
    assert [(r["id"], r["attempt"]) for r in records[1:]] == [
        ("q01-moby", 1), ("q01-moby", 2), ("q02-drac", 1), ("q02-drac", 2)]
    assert len(seen) == 4
    # the report a reader reads says where the recording went
    report = next((tmp_path / "results").glob("answers-*.md")).read_text(encoding="utf-8")
    assert "planner calls recorded into: en-demo.abcdef012345" in report


def test_without_the_flag_nothing_is_recorded_and_no_observer_is_installed(monkeypatch, tmp_path):
    golden = tmp_path / "en-demo.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    recordings = tmp_path / "recordings"
    monkeypatch.setenv("AYL_PLAN_RECORDINGS_DIR", str(recordings))
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "build_graph", lambda: object())
    monkeypatch.setattr(harness, "run_facts", lambda repeat=1: {**FACTS, "repeat": repeat})
    monkeypatch.setattr(harness, "render_fingerprint", lambda facts: "code 1b88943 | single run")

    def observed(graph, item, attempt=1):
        assert llm.JSON_CALL_OBSERVER is None
        raise RuntimeError("stop here; the observer is what this test reads")

    monkeypatch.setattr(harness, "run_one", observed)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py"])
    with pytest.raises(SystemExit):        # the two errored items exit 1
        harness.main()
    assert not recordings.exists()
