"""Replaying the planner: the real `plan()` node over a recorded reply, the
scores it produces, and the refusals that keep a replayed number honest.

The fixtures are `tests/fixtures/plan-replay-golden.yaml` (four items, one per
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
# what the fixture recording makes the planner decide, item by item
EXPECTED = {"f01-count": True, "f02-named-book": True, "f03-research-control": True,
            "f04-planner-gave-nothing": False}


def staged(tmp_path, *, golden_sha=None, prompt_sha=None, drop=()) -> Path:
    """The fixture recording in `tmp_path`, stamped current unless a test asks
    for a stamp that is wrong."""
    lines = [json.loads(line) for line in RECORDING.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    header, calls = lines[0], [line for line in lines[1:] if line["id"] not in drop]
    header["golden_sha256_12"] = golden_sha or plan_recording.sha12(
        GOLDEN.read_text(encoding="utf-8"))
    header["plan_rules_sha256_12"] = prompt_sha or plan_recording.prompt_hash()
    path = tmp_path / RECORDING.name
    path.write_text("".join(json.dumps(line, ensure_ascii=False) + "\n"
                            for line in [header, *calls]), encoding="utf-8")
    return path


@pytest.fixture
def replayed(monkeypatch, tmp_path, capsys):
    """`main()` with the golden file, the results directory and the fingerprint
    pinned, and the catalogue forced onto the documented manifest fallback so a
    developer's own index cannot decide what these tests measure."""
    def run(*argv, recording=None, **staging):
        monkeypatch.setattr(replay.harness, "GOLDEN_PATH", GOLDEN)
        monkeypatch.setattr(replay, "RESULTS_DIR", tmp_path / "results")
        monkeypatch.setattr(replay.harness, "run_facts", lambda repeat=1: {
            "golden_name": GOLDEN.name, "golden_path": f"tests/fixtures/{GOLDEN.name}",
            "golden_sha256_12": plan_recording.sha12(GOLDEN.read_text(encoding="utf-8")),
            "model": "anthropic/claude-sonnet-4.6", "backend": "openrouter",
            "code": "1b88943", "repeat": repeat})
        monkeypatch.setattr(replay.harness, "render_fingerprint", lambda facts: "code 1b88943")
        monkeypatch.setattr(replay, "catalogue_from_index", lambda: None)
        path = recording if recording is not None else staged(tmp_path, **staging)
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
    assert sidecar["replayed"] == 4 and sidecar["missing"] == []
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


def test_the_report_says_no_model_was_called_and_what_it_cannot_measure(replayed):
    report = replayed()["report"]
    assert "NO MODEL WAS CALLED" in report
    assert "plan-replay-recording.jsonl" in report        # the recording it came from
    assert "CANNOT measure a change to `PLAN_RULES`" in report
    assert "plan PASS 3/4" in report
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
    assert result["sidecar"]["replayed"] == 3
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


def test_a_planner_fallback_fails_the_item():
    fell_back = replay.score_plan(item(), update(plan_fallback=True, queries=[]), "act")
    assert fell_back["fallback_ok"] is False and fell_back["plan_ok"] is False


def test_the_identify_or_answer_reading_is_reported_and_never_part_of_the_verdict():
    """The golden `type` labels the question, not the planner's reading of it;
    an "identify" question whose book is obvious is legitimately answered."""
    answered = replay.score_plan(item("identify"), update(mode="answer"), "act")
    assert answered["mode_exact"] is False
    assert answered["plan_ok"] is True


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
