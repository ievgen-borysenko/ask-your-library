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
    assert (call["id"], call["attempt"], call["call_index"]) == ("c01-ivanhoe", 2, 1)
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
    assert [(c["call_index"], c["json_attempt"]) for c in calls] == [(1, 1), (1, 2)]
    assert calls[0]["raw"] == "not json at all"
    assert calls[1]["raw"] == PLAN_REPLY


def test_a_reply_with_no_json_at_all_is_recorded_with_a_reason(monkeypatch, tmp_path):
    """An empty `error` on a line whose reply parsed to nothing reads like a
    success. `ask_json`'s own remembered error stays untouched — its retry
    prompt is a contract, pinned elsewhere — so the record says it instead."""
    scripted(monkeypatch, "no braces here", PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, "payload", role="plan")
    first, second = lines_of(recorder.path)[1:]
    assert first["error"] == llm.NO_JSON_OBJECT == "no JSON object in reply"
    assert second["error"] == ""


def test_a_malformed_reply_is_recorded_with_the_parser_s_own_reason(monkeypatch, tmp_path):
    scripted(monkeypatch, '{"mode": "answer", }', PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, "payload", role="plan")
    assert "Expecting property name" in lines_of(recorder.path)[1]["error"]


def test_two_plan_calls_of_one_item_are_numbered(monkeypatch, tmp_path):
    """A clarify sends the run back through `plan`; the second decision is a
    second line of the same item, not a replacement for the first."""
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c09"):
            llm.ask_json(PLAN_RULES, "first", role="plan")
            llm.ask_json(PLAN_RULES, "after the clarify", role="plan")
    assert [c["call_index"] for c in lines_of(recorder.path)[1:]] == [1, 2]


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
    # the two informative substitutions survive: the absolute-path sweep below
    # must not collapse what `redact_paths` already made readable
    assert call["user"] == "<question>~/private/library/notes.txt</question>"
    assert "<repo>/eval/golden/en-demo.yaml" in call["raw"]


def test_an_absolute_path_of_any_platform_is_dropped(monkeypatch, tmp_path):
    """`redact_paths` knows this machine's two prefixes. A payload can carry an
    external volume, another account's home, a system file, a Windows drive or a
    network share, and a recording is committed. The detection is generic and
    not a list of roots, because the roots are not enumerable: /etc/hosts,
    /usr/local/bin/x and /data/index are exactly the ones a list forgets."""
    elsewhere = ("/Volumes/backup/library/notes.txt", "/Users/someone-else/books",
                 "/etc/hosts", "/usr/local/bin/x", "/data/index", "/tmp/ayl-scratch/q.md",
                 r"C:\Users\reader\library", "C:/Users/reader/library", r"\\srv\share\f")
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS,
                                     redact=harness.redact_paths) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, "read " + " and ".join(elsewhere), role="plan")
    call = lines_of(recorder.path)[1]
    assert call["user"] == "read " + " and ".join(["<path>"] * len(elsewhere))
    for path in elsewhere:
        assert path not in recorder.path.read_text(encoding="utf-8")


def test_a_url_and_ordinary_prose_survive_the_path_sweep(monkeypatch, tmp_path):
    """The sweep must not eat what a planner legitimately says. A URL is not a
    path — its scheme slashes follow a colon or each other, and the path after
    the host follows a word character — and neither is a pair of names with a
    slash between them. The two informative stand-ins survive too."""
    kept = ("read https://example.com/docs/a/b about the key to the secret garden, "
            "the London/Paris route, 1/2 of the fleet, ~/notes.txt and <repo>/eval/golden/x.yaml")
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS,
                                     redact=harness.redact_paths) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, kept, role="plan")
    assert lines_of(recorder.path)[1]["user"] == kept


# --- nothing token-shaped reaches a committed file ----------------------------
def test_a_token_shaped_value_refuses_to_finalise_the_recording(monkeypatch, tmp_path):
    """Masking a secret still means one passed through, and nobody would go back
    and check a file that looks clean. So the line is not written at all and the
    recording never gets its final name."""
    leaked = "sk" + "-or-v1-0a1b2c3d4e5f6071"      # glued at run time, see TOKEN_SHAPES
    scripted(monkeypatch, '{"mode": "answer", "queries": ["' + leaked + '"]}')
    final = tmp_path / "r.jsonl"
    with pytest.raises(plan_recording.SecretInRecording) as raised:
        with plan_recording.PlanRecorder(final, FACTS) as recorder:
            with recorder.item("c01"):
                llm.ask_json(PLAN_RULES, "payload", role="plan")
    assert "line 2" in f"{raised.value}" and "c01" in f"{raised.value}"
    assert not final.exists()
    assert leaked not in recorder.partial.read_text(encoding="utf-8")
    assert lines_of(recorder.partial) == lines_of(recorder.partial)[:1]   # the header alone


# Every prefix is glued on at run time and never written whole into this file.
# These are synthetic and worthless, but they are the exact shapes GitHub's push
# protection and the gitleaks step in security.yml look for, and a test fixture
# is not worth a blocked push or a scanner alert on the repository. (That is
# also the second net the recorder's own gate has behind it, so the two rules
# agreeing on these shapes is the point.)
TOKEN_SHAPES = [
    ("ey" + "JhbGciOiJIUzI1NiJ9.eyJzdWIiOiJyZWFkZXIifQ.s1gn4tur3", "a JSON web token"),
    ("xo" + "xb-11112222-33334444-aBcDeFgHiJkLmNoP", "a Slack token"),
    ("gh" + "p_A1b2C3d4E5f6G7h8I9j0", "a GitHub token"),
    ("github" + "_pat_11ABCDEFG0aBcDeFgHiJ", "a GitHub token"),
    ("AI" + "zaSyD-A1b2C3d4E5f6G7h8I9j0", "a Google API key"),
    ("AK" + "IAIOSFODNN7EXAMPLE", "an AWS access key id"),
    ("AS" + "IAIOSFODNN7EXAMPLE", "an AWS access key id"),
    ("api_key = " + "0123456789abcdef0123", "an api key assignment"),
    ("-----BEGIN " + "RSA PRIVATE KEY-----", "a private key"),
    ("sk" + "-or-v1-0a1b2c3d4e5f6071", "an OpenRouter/OpenAI-style key"),
]


@pytest.mark.parametrize("value, what", TOKEN_SHAPES)
def test_every_token_shape_refuses_to_finalise(monkeypatch, tmp_path, value, what):
    scripted(monkeypatch, PLAN_REPLY)
    final = tmp_path / "r.jsonl"
    with pytest.raises(plan_recording.SecretInRecording) as raised:
        with plan_recording.PlanRecorder(final, FACTS) as recorder:
            with recorder.item("c01"):
                llm.ask_json(PLAN_RULES, f"the value is {value}", role="plan")
    assert what in f"{raised.value}"
    assert not final.exists()
    assert value not in recorder.partial.read_text(encoding="utf-8")


def test_the_literal_value_of_a_key_in_this_environment_refuses(monkeypatch, tmp_path):
    """A credential need not look like one. Whatever this machine's
    *_KEY / *_TOKEN / *_SECRET hold is compared literally."""
    monkeypatch.setenv("SOME_PROVIDER_TOKEN", "an-ordinary-looking-passphrase")
    scripted(monkeypatch, PLAN_REPLY)
    final = tmp_path / "r.jsonl"
    with pytest.raises(plan_recording.SecretInRecording):
        with plan_recording.PlanRecorder(final, FACTS) as recorder:
            with recorder.item("c01"):
                llm.ask_json(PLAN_RULES, "the setting is an-ordinary-looking-passphrase",
                             role="plan")
    assert not final.exists()
    assert "an-ordinary-looking-passphrase" not in recorder.partial.read_text(encoding="utf-8")


def test_an_ordinary_question_is_not_mistaken_for_a_secret(monkeypatch, tmp_path):
    scripted(monkeypatch, PLAN_REPLY)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            llm.ask_json(PLAN_RULES, "Which of my books mention the key to the secret garden?",
                         role="plan")
    assert len(lines_of(recorder.path)) == 2


# --- a recording that could not be written ------------------------------------
class BrokenFile:
    """A file whose writes fail, as a full disk's would."""

    def __init__(self, real):
        self.real = real
        self.broken = False

    def write(self, text):
        if self.broken:
            raise OSError(28, "No space left on device")
        return self.real.write(text)

    def flush(self):
        return self.real.flush()

    def close(self):
        return self.real.close()


def test_a_write_that_fails_does_not_stop_the_run_but_does_stop_the_recording(monkeypatch,
                                                                             tmp_path):
    """The observer swallows its own exceptions so a paid run goes on — and used
    to leave no state anywhere, so a recording that lost half its lines was
    finalised, named and committed as a complete one. The failure is latched;
    the call still returns; the file keeps its .partial name."""
    scripted(monkeypatch, PLAN_REPLY)
    final = tmp_path / "r.jsonl"
    with pytest.raises(plan_recording.RecordingIncomplete) as raised:
        with plan_recording.PlanRecorder(final, FACTS) as recorder:
            recorder._file = broken = BrokenFile(recorder._file)
            with recorder.item("q01"):
                broken.broken = True
                # the real ask_json, the real observer, the real _write
                assert llm.ask_json(PLAN_RULES, "payload", role="plan")["mode"] == "answer"
    assert "No space left on device" in f"{raised.value}"
    assert "line 2" in f"{raised.value}"
    assert not final.exists()
    assert recorder.partial.exists()
    assert llm.JSON_CALL_OBSERVER is None      # still disarmed


def test_a_run_whose_recording_failed_says_so_and_exits_one(monkeypatch, tmp_path, capsys):
    """The report a reader reads carries the reason, and the run does not exit
    green on a recording that is not there."""
    scripted(monkeypatch, PLAN_REPLY)
    recordings = staged_harness(monkeypatch, tmp_path)
    monkeypatch.setattr(harness, "run_one", fake_run_one)
    # eval/ holds scripts, not a package, so the harness loads its sibling by
    # path and would otherwise hold a SECOND module object that this test's
    # patch could not reach. Handing it the one loaded here also makes the
    # exception classes it catches the ones raised.
    monkeypatch.setattr(harness, "load_plan_recording", lambda: plan_recording)
    real_enter = plan_recording.PlanRecorder.__enter__

    def breaking_enter(self):
        real_enter(self)
        self._file = BrokenFile(self._file)
        self._file.broken = True
        return self

    monkeypatch.setattr(plan_recording.PlanRecorder, "__enter__", breaking_enter)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--record-plans"])
    with pytest.raises(SystemExit) as raised:
        harness.main()
    assert raised.value.code == 1
    report = next((tmp_path / "results").glob("answers-*.md")).read_text(encoding="utf-8")
    assert "RecordingIncomplete" in report and "No space left on device" in report
    assert "RecordingIncomplete" in capsys.readouterr().err
    assert not list(recordings.glob("*.jsonl"))


# --- a call that never came back ----------------------------------------------
def test_a_timed_out_call_is_recorded_and_the_exception_is_unchanged(monkeypatch, tmp_path):
    """Without a line, a timed-out planner is indistinguishable from an item
    nobody ran. The exception object itself must reach the caller untouched."""
    from openai import APITimeoutError

    boom = APITimeoutError(request=None)

    def timing_out(system, user, role):
        raise boom

    monkeypatch.setattr(llm, "llm_invoke", timing_out)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            with pytest.raises(llm.CallTimeout) as raised:
                llm.ask_json(PLAN_RULES, "payload", role="plan")
    assert raised.value is boom                    # the same object, not a copy
    call = lines_of(recorder.path)[1]
    assert call["raw"] == "" and call["error"].startswith("APITimeoutError: ")
    assert call["json_attempt"] == 1


def test_a_timeout_on_the_retry_is_recorded_after_the_malformed_first_reply(monkeypatch, tmp_path):
    from openai import APITimeoutError

    calls = []

    def once_then_timeout(system, user, role):
        calls.append(user)
        if len(calls) == 1:
            return Reply("not json")
        raise APITimeoutError(request=None)

    monkeypatch.setattr(llm, "llm_invoke", once_then_timeout)
    with plan_recording.PlanRecorder(tmp_path / "r.jsonl", FACTS) as recorder:
        with recorder.item("c01"):
            with pytest.raises(llm.CallTimeout):
                llm.ask_json(PLAN_RULES, "payload", role="plan")
    first, second = lines_of(recorder.path)[1:]
    assert (first["json_attempt"], second["json_attempt"]) == (1, 2)
    assert first["raw"] == "not json" and second["raw"] == ""
    assert second["error"].startswith("APITimeoutError: ")
    # the retry's payload is the one ask_json really sent
    assert second["user"] == llm.retry_payload("payload", None)


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


def fake_run_one(graph, item, attempt=1):
    """A `run_one` that makes the planner's call and nothing else, so the lines
    under test are produced by the real `ask_json` through the real observer."""
    llm.ask_json(PLAN_RULES, f"<question>{item['question']}</question>", role="plan")
    return {"id": item["id"], "type": item["type"], "question": item["question"],
            "answer": "Moby Dick aboard the Pequod", "verification": "0/0",
            "provenance": {}, "steps_taken": 1, "read_chapters": [], "evidence_items": 0,
            "clarify_asked": False, "clarify_candidates": [], "clarify_unresolved": False,
            "clarify_chosen": "", "plan_fallback": False, "stop_reason": "", "catalog": {},
            "book_filter": "", "book_unresolved": "", "catalog_fallback": "", "seconds": 0,
            "steps_log": [], "cost_usd": 0.0, "llm_calls": 1, "tokens_in": 1, "tokens_out": 1,
            "score": {"titles_mentioned": 1, "titles_expected": 1, "facts_found": 0,
                      "facts_expected": 0, "facts_ok": True, "behavior_ok": True}}


def staged_harness(monkeypatch, tmp_path) -> Path:
    """The main harness pointed at a two-item golden file in `tmp_path`, with a
    recordings directory of its own. Returns that directory."""
    golden = tmp_path / "en-demo.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    recordings = tmp_path / "recordings"
    monkeypatch.setenv("AYL_PLAN_RECORDINGS_DIR", str(recordings))
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(harness, "build_graph", lambda: object())
    monkeypatch.setattr(harness, "run_facts", lambda repeat=1: {**FACTS, "repeat": repeat})
    monkeypatch.setattr(harness, "render_fingerprint", lambda facts: "code 1b88943 | single run")
    return recordings


def test_record_plans_writes_the_recording_of_a_whole_run(monkeypatch, tmp_path):
    """`--record-plans` on eval/run_agent_eval.py: one recording per golden set,
    one line per item and attempt, written by the run that was happening
    anyway."""
    seen = scripted(monkeypatch, PLAN_REPLY)
    recordings = staged_harness(monkeypatch, tmp_path)
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


def test_recording_refuses_to_replace_one_that_is_already_there(monkeypatch, tmp_path, capsys):
    """That file is the artefact of a run somebody paid for. Refused BEFORE the
    graph is built and before the first call, not after the money is spent."""
    scripted(monkeypatch, PLAN_REPLY)
    recordings = staged_harness(monkeypatch, tmp_path)
    existing = recordings / "en-demo.abcdef012345.anthropic-claude-sonnet-4.6.jsonl"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("the recording of a paid run\n", encoding="utf-8")

    def never(graph, item, attempt=1):
        raise AssertionError("the run started before the recording was refused")

    monkeypatch.setattr(harness, "run_one", never)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--record-plans"])
    with pytest.raises(SystemExit) as raised:
        harness.main()
    assert raised.value.code == 2
    assert "refusing to record over" in capsys.readouterr().err
    assert existing.read_text(encoding="utf-8") == "the recording of a paid run\n"


def test_overwrite_replaces_it_on_purpose(monkeypatch, tmp_path):
    scripted(monkeypatch, PLAN_REPLY)
    recordings = staged_harness(monkeypatch, tmp_path)
    existing = recordings / "en-demo.abcdef012345.anthropic-claude-sonnet-4.6.jsonl"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("the recording of a paid run\n", encoding="utf-8")
    monkeypatch.setattr(harness, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--record-plans", "--overwrite"])
    harness.main()
    assert lines_of(existing)[0]["kind"] == "header"


def test_a_run_of_selected_ids_writes_a_subset_recording(monkeypatch, tmp_path):
    """Three ids recorded under the name of the whole set would destroy the
    complete recording and leave a file whose name still claims 42 items."""
    scripted(monkeypatch, PLAN_REPLY)
    recordings = staged_harness(monkeypatch, tmp_path)
    monkeypatch.setattr(harness, "run_one", fake_run_one)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--record-plans", "q02-drac"])
    harness.main()
    whole = recordings / "en-demo.abcdef012345.anthropic-claude-sonnet-4.6.jsonl"
    subset = recordings / "en-demo.abcdef012345.anthropic-claude-sonnet-4.6.subset-1of2.jsonl"
    assert subset.exists() and not whole.exists()
    header = lines_of(subset)[0]
    assert header["subset"] is True
    assert (header["subset_items"], header["golden_items"]) == (1, 2)
    assert header["requested_ids"] == ["q02-drac"]
    assert [r["id"] for r in lines_of(subset)[1:]] == ["q02-drac"]


def test_without_the_flag_nothing_is_recorded_and_no_observer_is_installed(monkeypatch, tmp_path):
    recordings = staged_harness(monkeypatch, tmp_path)

    def observed(graph, item, attempt=1):
        assert llm.JSON_CALL_OBSERVER is None
        raise RuntimeError("stop here; the observer is what this test reads")

    monkeypatch.setattr(harness, "run_one", observed)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py"])
    with pytest.raises(SystemExit):        # the two errored items exit 1
        harness.main()
    assert not recordings.exists()


def test_the_recording_header_names_the_hosted_thinking_switch():
    """`reasoning` is what `llm.llm` sends as LLM_REASONING on the hosted
    backend, and empty on the local one, which never gets that form."""
    from conftest import fresh_output
    code = ("import json, importlib.util, sys; sys.path.insert(0, %r)\n"
            "spec = importlib.util.spec_from_file_location('plan_recording', %r)\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "print(json.dumps(m.model_knobs()['reasoning']))"
            % (str(REPO / "eval"), str(REPO / "eval" / "plan_recording.py")))
    assert json.loads(fresh_output(code, LLM_BACKEND="openrouter", OPENROUTER_API_KEY="sk-test")) == "off"
    assert json.loads(fresh_output(code, LLM_BACKEND="openrouter", OPENROUTER_API_KEY="sk-test",
                                   LLM_REASONING="provider")) == "provider"
    assert json.loads(fresh_output(code, LLM_BACKEND="ollama")) == ""
