"""Replaying the planner: the real `plan()` node over a recorded reply, the
scores it produces, and the refusals that keep a replayed number honest.

The fixtures are `tests/fixtures/plan-replay-golden.yaml` (five items, one per
branch of the mapping) and `tests/fixtures/plan-replay-recording.jsonl` beside
it. Each test stages its own copy of the recording with the header stamped to
the checksums THIS tree has, so that editing `PLAN_RULES` or the fixture golden
does not fail a test about post-processing — the staleness tests stamp it wrong
on purpose instead, which is the behaviour actually under test.

No model and no network: the replayer never calls one, and
`test_the_replay_makes_no_network_attempt` proves it with the process-level
egress guard rather than with a patched client.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ask_your_library import llm, nodes

sys.path.insert(0, str(Path(__file__).resolve().parent))
from egress_guard import record_egress  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "eval" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


replay = load("run_plan_eval")
plan_recording = replay.plan_recording

GOLDEN = FIXTURES / "plan-replay-golden.yaml"
RECORDING = FIXTURES / "plan-replay-recording.jsonl"
# the second pair: one item whose recording holds TWO planner calls, because a
# clarify sent the run back through plan()
CLARIFY_GOLDEN = FIXTURES / "plan-replay-clarify-golden.yaml"
CLARIFY_RECORDING = FIXTURES / "plan-replay-clarify-recording.jsonl"
# what the fixture recording makes the planner decide, item by item
EXPECTED = {"f01-count": True, "f02-named-book": True, "f03-research-control": True,
            "f04-planner-gave-nothing": False,
            # the scope gate on a question this set expects an answer to (#70)
            "f05-gate-refusal": False}


def staged(tmp_path, *, golden=None, source=None, golden_sha=None, prompt_sha=None,
           retry_sha=None, drop=(), repayload=(), resystem=(), timeout=()) -> Path:
    """The fixture recording in `tmp_path`, stamped current unless a test asks
    for a stamp that is wrong. `repayload` / `resystem` spoil the recorded
    REQUEST of the named items, which is what a change to how plan() builds its
    payload would look like from here."""
    golden, source = golden or GOLDEN, source or RECORDING
    lines = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    header, calls = lines[0], [line for line in lines[1:] if line["id"] not in drop]
    for call in calls:
        if call["id"] in repayload:
            call["user"] = call["user"] + "\n<an older payload>"
        if call["id"] in resystem:
            call["system_sha256_12"] = "000000000000"
        if call["id"] in timeout:
            call["raw"], call["error"] = "", "APITimeoutError: the call ran out of time"
    header["golden_sha256_12"] = golden_sha or plan_recording.sha12(
        golden.read_text(encoding="utf-8"))
    header["plan_rules_sha256_12"] = prompt_sha or plan_recording.prompt_hash()
    header["retry_rule_sha256_12"] = retry_sha or plan_recording.retry_hash()
    path = tmp_path / source.name
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n"
                            for line in [header, *calls]), encoding="utf-8")
    return path


@pytest.fixture
def replayed(monkeypatch, tmp_path, capsys):
    """`main()` with the golden file, the results directory and the fingerprint
    pinned, and the catalogue forced onto the documented manifest fallback so a
    developer's own index cannot decide what these tests measure."""
    def run(*argv, recording=None, golden=None, **staging):
        golden = golden or GOLDEN
        monkeypatch.setattr(replay.harness, "GOLDEN_PATH", golden)
        monkeypatch.setattr(replay, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(replay.harness, "run_facts", lambda repeat=1: {
            "golden_name": golden.name, "golden_path": f"tests/fixtures/{golden.name}",
            "golden_sha256_12": plan_recording.sha12(golden.read_text(encoding="utf-8")),
            "model": "anthropic/claude-sonnet-4.6", "backend": "openrouter",
            "code": "1b88943", "repeat": repeat})
        monkeypatch.setattr(replay.harness, "render_fingerprint", lambda facts: "code 1b88943")
        monkeypatch.setattr(replay, "catalogue_from_index", lambda: None)
        path = (recording if recording is not None
                else staged(tmp_path, golden=golden, **staging))
        code = 0
        try:
            replay.main(["--recording", str(path), *argv])
        except SystemExit as exit_code:
            code = exit_code.code or 0
        out = capsys.readouterr()
        report = sorted((tmp_path / "results").glob("plan-replay-*.md"))
        sidecar = sorted((tmp_path / "results").glob("plan-replay-*.json"))
        return {"code": code, "out": out.out, "err": out.err,
                "report": report[-1].read_text(encoding="utf-8") if report else "",
                "sidecar": json.loads(sidecar[-1].read_text(encoding="utf-8")) if sidecar else {}}
    return run


# --- the replay itself --------------------------------------------------------
def test_the_recorded_planner_is_replayed_through_the_real_node(replayed):
    result = replayed()
    assert result["code"] == 0
    sidecar = result["sidecar"]
    assert sidecar["model_called"] is False and sidecar["cost_usd"] == 0.0
    assert sidecar["replayed"] == 5 and sidecar["missing"] == []
    verdicts = {a["id"]: a["score"]["plan_ok"] for a in sidecar["attempts"]}
    assert verdicts == EXPECTED
    # the deterministic half really ran: a catalogue request was parsed, a named
    # book was resolved against the catalogue, and a planner that gave nothing
    # fell back to the raw question
    by_id = {a["id"]: a["score"] for a in sidecar["attempts"]}
    assert by_id["f01-count"]["route"] == "catalog" and by_id["f01-count"]["op"] == "count"
    assert by_id["f02-named-book"]["book_filter"] == "Dracula — Bram Stoker"
    assert by_id["f03-research-control"]["route"] == "act"
    assert by_id["f04-planner-gave-nothing"]["plan_fallback"] is True
    # ... and a fallback is not a routing decision, so it is not a correct route
    assert by_id["f04-planner-gave-nothing"]["mode_ok"] is False
    # ... and the recorded out-of-scope plan really reached the gate: no query,
    # straight to synthesize, and not a correct route for an item of type answer
    assert by_id["f05-gate-refusal"]["gate_refusal"] is True
    assert by_id["f05-gate-refusal"]["route"] == "synthesize"
    assert by_id["f05-gate-refusal"]["mode_ok"] is False
    assert "REFUSED AT THE SCOPE GATE" in result["report"]
    assert result["sidecar"]["totals"]["gate_refusal"] == {"ok": 1, "of": 5}
    assert result["sidecar"]["totals"]["mode_ok"] == {"ok": 3, "of": 5}
    assert result["sidecar"]["payload_drift"] == {}


def test_the_report_says_no_model_was_called_and_what_it_cannot_measure(replayed):
    report = replayed()["report"]
    assert "NO MODEL WAS CALLED" in report
    assert "plan-replay-recording.jsonl" in report        # the recording it came from
    assert "CANNOT measure a change to `PLAN_RULES`" in report
    assert "plan PASS 3/4" in report
    assert "mode_ok 3/4" in report
    assert "corpus/manifest.yaml" in report               # which catalogue answered


def test_no_model_is_called(monkeypatch, replayed):
    """Not "the replayer returns early", but "the model path is never entered":
    every way into it raises."""
    def forbidden(*args, **kwargs):
        raise AssertionError("a model call was made during a replay")

    monkeypatch.setattr(llm, "llm_invoke", forbidden)
    monkeypatch.setattr(llm, "llm", forbidden)
    assert replayed()["code"] == 0


def test_the_replay_makes_no_network_attempt(replayed):
    """The claim "this costs nothing" is a claim about connections. Armed
    in-process, the guard records every outbound attempt at the socket layer,
    and a replay must make none at all — not even a loopback one to Ollama."""
    with record_egress() as guard:
        result = replayed()
    assert result["code"] == 0
    assert guard.attempts == [], [a.as_tuple() for a in guard.attempts]


# --- staleness ----------------------------------------------------------------
def test_a_fresh_recording_is_not_stale():
    """The committed fixture pair, exactly as committed — no re-stamping.

    Every other test in this file stamps the header current so that editing
    `PLAN_RULES` does not fail a test about post-processing. This one does not,
    which is what keeps the two files in step: edit the fixture golden or the
    planner's prompt without regenerating the recording beside it and this fails
    here, where the message is about the fixtures, instead of somewhere the
    stamping would have hidden it. At the commit that added them the two
    checksums were `e7d21ec4bd9b` (golden) and `acd673f471d3` (PLAN_RULES); the
    planner's prompt gained the scope rule (#70), the golden gained the item
    that exercises it (`f05-gate-refusal`), and the fixture was re-stamped to
    `ee76587c7722` / `aabb79d156d6` with them. Re-stamping is honest HERE and
    nowhere else:
    these five replies are hand-written fixtures for the post-processing, not a
    measurement of a model, so there is nothing to re-record. The recordings
    under `eval/recordings/` are measurements and were NOT re-stamped: they
    still carry `acd673f471d3` and replay the rules as they were."""
    recording = plan_recording.load_recording(RECORDING)
    golden_sha = plan_recording.sha12(GOLDEN.read_text(encoding="utf-8"))
    assert recording.header["golden_sha256_12"] == golden_sha
    assert recording.header["plan_rules_sha256_12"] == plan_recording.prompt_hash()
    assert recording.stale_against(golden_sha) == []
    # and every call in it carries the same prompt's hash as the header
    for calls in recording.calls.values():
        for call in calls:
            assert call["system_sha256_12"] == recording.header["plan_rules_sha256_12"]


def test_a_golden_checksum_that_moved_refuses(replayed):
    result = replayed(golden_sha="000000000000")
    assert result["code"] == 2
    assert "golden checksum" in result["err"] and "the questions changed" in result["err"]
    assert result["report"] == ""       # nothing was replayed and nothing was written


def test_a_prompt_hash_that_moved_refuses_and_says_a_replay_cannot_measure_it(replayed):
    result = replayed(prompt_sha="deadbeefcafe")
    assert result["code"] == 2
    assert "PLAN_RULES checksum" in result["err"]
    assert "a prompt change needs a NEW recording" in result["err"]
    assert result["report"] == ""


def test_allow_stale_replays_and_stamps_every_report_it_writes(replayed):
    result = replayed("--allow-stale", prompt_sha="deadbeefcafe")
    assert result["code"] == 0
    assert "STALE RECORDING, replayed anyway" in result["report"]
    assert "Nothing below is a measurement of this tree" in result["report"].replace("\n", " ")
    assert result["sidecar"]["stale"] and "PLAN_RULES" in result["sidecar"]["stale"][0]


def test_check_verifies_the_recording_and_replays_nothing(replayed):
    fresh = replayed("--check")
    assert fresh["code"] == 0
    assert "measures this tree" in fresh["out"]
    assert fresh["report"] == ""
    stale = replayed("--check", prompt_sha="deadbeefcafe")
    assert stale["code"] == 2
    assert "does NOT measure this tree" in stale["out"]


def test_a_recording_that_is_not_one_is_refused(replayed, tmp_path):
    broken = tmp_path / "broken.jsonl"
    broken.write_text('{"kind": "call", "id": "f01-count"}\n', encoding="utf-8")
    result = replayed(recording=broken)
    assert result["code"] == 2 and "not a recording header" in result["err"]


def test_a_recording_this_tree_cannot_read_is_refused(replayed, tmp_path):
    ahead = tmp_path / "ahead.jsonl"
    ahead.write_text(json.dumps({"schema": plan_recording.SCHEMA, "schema_version": 99,
                                 "kind": "header"}) + "\n", encoding="utf-8")
    result = replayed(recording=ahead)
    assert result["code"] == 2 and "schema_version" in result["err"]


# --- missing items ------------------------------------------------------------
def test_an_item_the_recording_does_not_hold_exits_one(replayed):
    result = replayed(drop={"f02-named-book"})
    assert result["code"] == 1
    assert "f02-named-book" in result["err"]
    # the run still happened and still reported: the exit code is the verdict,
    # not a reason to write nothing
    assert result["sidecar"]["missing"] == ["f02-named-book"]
    assert result["sidecar"]["replayed"] == 4
    assert "NOT IN THE RECORDING" in result["report"]


def test_allow_missing_accepts_it(replayed):
    result = replayed("--allow-missing", drop={"f02-named-book"})
    assert result["code"] == 0
    assert result["sidecar"]["missing"] == ["f02-named-book"]


def test_min_pass_is_a_floor_on_the_replayed_attempts(replayed):
    assert replayed("--min-pass", "3")["code"] == 0
    assert replayed("--min-pass", "4")["code"] == 1


# --- the scorer, row by row ---------------------------------------------------
def item(kind="answer", **over):
    return {"id": "x", "type": kind, "question": "q", "expected_books": [],
            "expected_facts": [], **over}


def update(**over):
    base = {"mode": "answer", "queries": ["b", "c"], "current_query": "a",
            "book_filter": "", "book_unresolved": "", "catalog_request": {}}
    return {**base, **over}


def test_a_catalogue_item_wants_the_catalogue_path_and_the_named_operation():
    good = replay.score_plan(item("catalog", expected_op="count"),
                             update(mode="catalog", catalog_request={"op": "count"},
                                    queries=[], current_query=""), "catalog")
    assert good["mode_ok"] and good["op_ok"] and good["plan_ok"]
    # the queries rows do not exist on this path: a catalogue decision carries
    # none by contract, and an absent row is not a failed one
    assert "queries_ok" not in good and "queries_range" not in good
    wrong_op = replay.score_plan(item("catalog", expected_op="list"),
                                 update(mode="catalog", catalog_request={"op": "count"},
                                        queries=[], current_query=""), "catalog")
    assert wrong_op["op_ok"] is False and wrong_op["plan_ok"] is False
    took_the_loop = replay.score_plan(item("catalog", expected_op="count"), update(), "act")
    assert took_the_loop["mode_ok"] is False


def test_a_gate_refusal_is_a_route_of_its_own_and_a_wrong_one_on_an_answerable_item():
    """The scope gate (#70) ends the run at plan. Before this row existed, such
    an attempt scored `mode_ok` GREEN on any non-catalogue item — "not the
    catalogue path" is true of a run that took no path at all — so a planner
    that started refusing real questions would have been reported as routing
    them correctly."""
    refused = replay.score_plan(item("answer"),
                                update(mode="refusal", queries=[], current_query=""),
                                "synthesize")
    assert refused["gate_refusal"] is True
    assert refused["mode_ok"] is False and refused["plan_ok"] is False
    # a refusal carries no queries by contract: absent rows, not red ones
    assert "queries_ok" not in refused and "queries_range" not in refused
    # on an item whose expected outcome IS a refusal, reaching it early is not
    # failed here — `mode_ok` is about the route the set pins
    expected = replay.score_plan(item("refusal"),
                                 update(mode="refusal", queries=[], current_query=""),
                                 "synthesize")
    assert expected["gate_refusal"] is True and expected["mode_ok"] is True
    assert expected["plan_ok"] is True
    # and an ordinary plan carries the row as False, so the count is a count
    assert replay.score_plan(item("answer"), update(), "act")["gate_refusal"] is False


def test_a_content_item_fails_when_the_planner_sent_it_to_the_catalogue():
    misrouted = replay.score_plan(item("answer"),
                                  update(mode="catalog", catalog_request={"op": "list"},
                                         queries=[], current_query=""), "catalog")
    assert misrouted["mode_ok"] is False and misrouted["plan_ok"] is False


def test_a_research_control_must_be_routed_by_the_planner_and_not_rescued_by_code():
    """`expected_behavior: research` is the one place the golden set asks for
    more than the route: a catalogue fallback means code rescued a misroute, and
    counting that as a pass would measure the guard instead of the planner."""
    own = replay.score_plan(item("answer", expected_behavior="research"), update(), "act")
    assert own["mode_ok"] is True
    rescued = replay.score_plan(item("answer", expected_behavior="research"),
                                update(catalog_fallback="mixed_intent"), "act")
    assert rescued["mode_ok"] is False
    # on any other item a rescue is not a failure of the planner's route
    assert replay.score_plan(item("answer"), update(catalog_fallback="mixed_intent"),
                             "act")["mode_ok"] is True


def test_the_named_book_must_resolve_to_the_expected_key():
    expected = item("answer", expected_book_filter="Dracula")
    ok = replay.score_plan(expected, update(book_filter="Dracula — Bram Stoker"), "act")
    assert ok["book_filter_ok"] and ok["plan_ok"]
    wrong = replay.score_plan(expected, update(book_filter="Frankenstein — Mary Shelley"), "act")
    assert wrong["book_filter_ok"] is False and wrong["plan_ok"] is False
    # a silent no-filter is the failure this row exists to catch
    assert replay.score_plan(expected, update(), "act")["book_filter_ok"] is False


def test_the_query_rows_read_the_range_the_prompt_asks_for():
    assert replay.score_plan(item(), update(current_query="a", queries=[]), "act")["queries_range"] is False
    assert replay.score_plan(item(), update(current_query="a", queries=["b"]), "act")["queries_range"] is True
    five = update(current_query="a", queries=["b", "c", "d", "e"])
    assert replay.score_plan(item(), five, "act")["queries_range"] is False
    assert replay.score_plan(item(), five, "act")["queries_ok"] is True


def test_a_planner_fallback_fails_the_item_and_its_route():
    """A fallback decided nothing. "Not the catalogue path" is true of it only
    because there was no path to take, so `mode_ok` must not be green on the
    one row a reader looks at first."""
    fell_back = replay.score_plan(item(), update(plan_fallback=True, queries=[]), "act")
    assert fell_back["fallback_ok"] is False and fell_back["plan_ok"] is False
    assert fell_back["mode_ok"] is False
    # and on a catalogue item, where it was already false for want of a request
    catalogue = replay.score_plan(item("catalog", expected_op="count"),
                                  update(plan_fallback=True, queries=[]), "act")
    assert catalogue["mode_ok"] is False


def test_the_identify_or_answer_reading_is_reported_and_never_part_of_the_verdict():
    """The golden `type` labels the question, not the planner's reading of it;
    an "identify" question whose book is obvious is legitimately answered."""
    answered = replay.score_plan(item("identify"), update(mode="answer"), "act")
    assert answered["mode_exact"] is False
    assert answered["plan_ok"] is True


# --- what a replay does NOT cover ---------------------------------------------
def clarify(replayed, *argv, **staging):
    return replayed(*argv, golden=CLARIFY_GOLDEN, source=CLARIFY_RECORDING, **staging)


def test_only_the_first_planner_call_of_an_item_is_replayed_and_it_is_accounted(replayed):
    """A clarify sends the run back through `plan()`, so this item recorded two
    calls. The second is a function of graph state — the evidence collected, the
    candidates offered, the reader's reply — that the observer never saw, so it
    is counted rather than invented, and the count is not a footnote: it decides
    the exit code."""
    result = clarify(replayed)
    assert result["code"] == 1
    assert result["sidecar"]["calls"] == {"g01-clarify-replan": {"recorded": 2, "replayed": 1}}
    assert "calls replayed 1/2" in result["report"]
    assert "only the first planner call of an item is replayed" in result["report"]
    assert "not replayed" in result["err"] and "g01-clarify-replan" in result["err"]
    # the first call DID replay, through the real node
    score = result["sidecar"]["attempts"][0]["score"]
    assert score["mode"] == "identify" and score["route"] == "act"


def test_allow_unreplayed_accepts_it_and_the_report_still_counts_it(replayed):
    result = clarify(replayed, "--allow-unreplayed")
    assert result["code"] == 0
    assert "recorded planner calls not replayed on 1 of 1 attempts" in result["report"]
    assert result["sidecar"]["calls"]["g01-clarify-replan"]["replayed"] == 1


def test_an_item_whose_only_call_is_replayed_is_not_reported_as_unreplayed(replayed):
    result = replayed()
    assert all(c == {"recorded": 1, "replayed": 1} for c in result["sidecar"]["calls"].values())
    assert "calls replayed" not in result["report"]


# --- a call that never came back ----------------------------------------------
def scripted_timeout_update():
    """What `plan()` returns when its own call times out, taken from a directly
    scripted run rather than from a reading of the node."""
    from openai import APITimeoutError
    from ask_your_library.runner import initial_state

    def timing_out(system, user, role):
        raise APITimeoutError(request=None)

    original, llm.ask_json = llm.ask_json, timing_out
    try:
        state = initial_state("Which of my books mention London?", history=[],
                              scratchpad=Path("/dev/null"))
        return nodes.plan(state)
    finally:
        llm.ask_json = original


def test_a_recorded_timeout_replays_as_the_timeout_branch(replayed):
    """The paid run's planner never got an answer and `plan()` has a branch for
    it. A replay that raised ValueError instead would put the item in the
    fallback branch and report a planner that produced nothing usable, which is
    a different state of the node."""
    result = replayed(timeout={"f03-research-control"})
    assert result["code"] == 0
    score = {a["id"]: a["score"] for a in result["sidecar"]["attempts"]}["f03-research-control"]
    # the timeout branch: no query at all, so routing goes straight to synthesize
    # — where the FALLBACK branch would have searched the raw question
    assert score["route"] == "synthesize"
    assert score["plan_fallback"] is False
    direct = scripted_timeout_update()
    assert (direct["mode"], direct["current_query"], direct["queries"]) == (
        score["mode"], "", [])
    assert direct["stop_reason"]


def test_a_timeout_on_the_retry_replays_as_the_timeout_branch_too(replayed, tmp_path):
    """The first reply was malformed and recorded; the retry never came back.
    One line parses to nothing and the next is the timeout, so the node takes
    the timeout branch and not the fallback."""
    path = staged(tmp_path)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for line in lines[1:]:
        if line["id"] == "f04-planner-gave-nothing" and line["json_attempt"] == 2:
            line["raw"], line["error"] = "", "APITimeoutError: the call ran out of time"
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                    encoding="utf-8")
    result = replayed(recording=path)
    assert result["code"] == 0
    score = {a["id"]: a["score"] for a in result["sidecar"]["attempts"]}["f04-planner-gave-nothing"]
    assert score["plan_fallback"] is False and score["route"] == "synthesize"


# --- payload drift ------------------------------------------------------------
def test_a_payload_the_node_no_longer_builds_is_reported_and_exits_one(replayed):
    """The reply is replayed whatever the question was. A change to how plan()
    ASSEMBLES its payload — a new data block, a different history window —
    would otherwise be graded against a reply to the payload of a year ago, and
    the run would look clean."""
    result = replayed(repayload={"f02-named-book"})
    assert result["code"] == 1
    assert "payload drift" in result["err"] and "f02-named-book" in result["err"]
    assert list(result["sidecar"]["payload_drift"]) == ["f02-named-book"]
    assert "PAYLOAD DRIFT" in result["report"]
    # the item still replayed and still scored: drift says the replay is
    # questionable, not that the planner decided wrongly
    assert result["sidecar"]["replayed"] == 5
    assert {a["id"]: a["score"]["plan_ok"] for a in result["sidecar"]["attempts"]} == EXPECTED


def test_a_system_prompt_that_does_not_match_the_recorded_call_is_drift(replayed):
    """The header's hash is checked once for the file; this is the same question
    per call, so a recording whose header was stamped by hand cannot hide it."""
    result = replayed(resystem={"f01-count"})
    assert result["code"] == 1
    assert "f01-count" in result["err"]
    assert any("system prompt" in reason
               for reason in result["sidecar"]["payload_drift"]["f01-count"])


def test_allow_drift_accepts_it_and_still_says_so(replayed):
    result = replayed("--allow-drift", repayload={"f02-named-book"})
    assert result["code"] == 0
    assert "payload drift on 1 of 4 attempts" in result["report"]
    assert list(result["sidecar"]["payload_drift"]) == ["f02-named-book"]


def test_the_retry_payload_is_compared_too(replayed, tmp_path):
    """Only the first attempt of a call used to be checked. The retry's payload
    is the first plus the retry wording, and both halves can move."""
    path = staged(tmp_path)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for line in lines[1:]:
        if line["id"] == "f04-planner-gave-nothing" and line["json_attempt"] == 2:
            line["user"] = line["user"].replace("INVALID JSON", "BAD JSON")
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                    encoding="utf-8")
    result = replayed(recording=path)
    assert result["code"] == 1
    assert any("attempt 2" in reason
               for reason in result["sidecar"]["payload_drift"]["f04-planner-gave-nothing"])


def test_attempts_recorded_out_of_order_are_drift(replayed, tmp_path):
    path = staged(tmp_path)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    for line in lines[1:]:
        if line["id"] == "f04-planner-gave-nothing" and line["json_attempt"] == 2:
            line["json_attempt"] = 7
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                    encoding="utf-8")
    result = replayed(recording=path)
    assert result["code"] == 1
    assert any("out of order" in reason
               for reason in result["sidecar"]["payload_drift"]["f04-planner-gave-nothing"])


def test_a_retry_wording_that_moved_is_stale(replayed):
    """The SECOND payload of a call is the first plus those words, so a change
    to them changes what the model was asked — and the PLAN_RULES hash does not
    cover it."""
    result = replayed(retry_sha="000000000000")
    assert result["code"] == 2
    assert "retry wording checksum" in result["err"]


def test_a_line_without_a_call_index_is_refused(replayed, tmp_path):
    """The order of the calls of one item is data, not a property of the file:
    a recording that leaves it implicit cannot be accounted for."""
    path = staged(tmp_path)
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lines[1].pop("call_index")
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                    encoding="utf-8")
    result = replayed(recording=path)
    assert result["code"] == 2 and "call_index" in result["err"]


# --- a partial recording ------------------------------------------------------
def test_a_subset_recording_is_reported_as_one(replayed, tmp_path):
    """A run of three ids records three items. A report that presented that as a
    run over the set would be a smaller measurement wearing a bigger name."""
    path = staged(tmp_path, drop={"f04-planner-gave-nothing"})
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    lines[0].update({"subset": True, "subset_items": 4, "golden_items": 5})
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines),
                    encoding="utf-8")
    result = replayed("--allow-missing", recording=path)
    assert result["code"] == 0
    assert "a SUBSET recording: 4 of 5 items" in result["report"]
    assert "not the set" in result["report"]
    assert result["sidecar"]["subset"].startswith("a SUBSET recording")


# --- the catalogue the replay resolves against --------------------------------
def test_the_manifest_fallback_is_the_catalogue_the_index_would_have_held():
    entries = replay.catalogue_from_manifest()
    keys = {entry.key for entry in entries}
    assert "Dracula — Bram Stoker" in keys
    # the canary fixtures the demo ingest plants are not books, here as in
    # library.list_books()
    assert not any("canary" in entry.key.lower() for entry in entries)


def test_the_catalogue_seam_is_restored_after_the_block():
    original = nodes.list_books
    with replay.catalogue([]):
        assert nodes.list_books is not original
    assert nodes.list_books is original
