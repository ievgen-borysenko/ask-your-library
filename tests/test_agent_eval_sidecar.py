"""The JSON sidecar, --repeat and the argparse front end of the agent eval.

No graph, no model, no network: `main()` runs with `run_one` replaced by a
fake that returns fixed results, the same way
tests/test_agent_eval_scoring.py::test_error_items_keep_the_cost_they_spent
does. What is under test is the record the harness leaves behind — that the
sidecar carries what a reader of a published number would need, that repeating
an item produces a spread rather than a second single sample, that a run of one
attempt still writes the Markdown report byte for byte as before, and that the
flags survived the move from hand-sliced sys.argv to argparse.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "run_agent_eval", Path(__file__).resolve().parents[1] / "eval" / "run_agent_eval.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

GOLDEN = ("questions:\n"
          "- id: q01-moby\n  type: answer\n  question: Which whale?\n"
          "  expected_books: [Moby Dick]\n  expected_facts: [Pequod]\n"
          "- id: q02-drac\n  type: identify\n  question: Which castle?\n"
          "  expected_books: [Dracula]\n  expected_facts: []\n")


def fake_result(item: dict, answer: str = "Moby Dick aboard the Pequod",
                behavior_ok: bool = True, **over) -> dict:
    """What run_one returns, in its own key order, with the score attached."""
    result = {"id": item["id"], "type": item["type"], "question": item["question"],
              "answer": answer, "verification": "2/2 confirmed",
              "provenance": {"checked": 2, "confirmed": 2, "unattributed": 0, "broken": 0},
              "steps_taken": 2, "read_chapters": [], "evidence_items": 3,
              "clarify_asked": False, "clarify_candidates": [], "clarify_unresolved": False,
              "clarify_chosen": "", "plan_fallback": False, "stop_reason": "enough evidence",
              "catalog": {}, "book_filter": "", "book_unresolved": "", "catalog_fallback": "",
              "seconds": 4, "steps_log": ["reflect -> whale"],
              "cost_usd": 0.01, "llm_calls": 3, "tokens_in": 1000, "tokens_out": 100,
              "score": {"titles_mentioned": 1, "titles_expected": 1, "facts_found": 1,
                        "facts_expected": 1, "facts_ok": True, "behavior_ok": behavior_ok}}
    result.update(over)
    return result


def prepared(monkeypatch, tmp_path, argv, results):
    """main() with the graph, the fingerprint and run_one replaced.

    `results` is called with (item, attempt) and returns the fake result for
    that attempt, so a test can make one attempt of one item fail."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    golden = tmp_path / "golden.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(harness, "build_graph", lambda: object())
    monkeypatch.setattr(harness, "run_facts", lambda repeat=1: {"code": "abc1234", "repeat": repeat})
    monkeypatch.setattr(harness, "render_fingerprint", lambda facts: "code abc1234 | single run")
    monkeypatch.setattr(harness, "run_one", lambda graph, item, attempt=1: results(item, attempt))
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", *argv])
    try:
        harness.main()
    except SystemExit as exit_code:      # --min-pass and errors exit 1; not what these test
        assert exit_code.code in (0, 1), exit_code.code
    return tmp_path


def only(tmp_path: Path, suffix: str) -> Path:
    found = sorted(tmp_path.glob(f"answers-*{suffix}"))
    assert len(found) == 1, found
    return found[0]


# ---------------------------------------------------------------- the sidecar
def test_the_sidecar_carries_the_run_and_every_attempt(monkeypatch, tmp_path):
    """The top-level record: what produced the numbers, when, and the totals;
    per question the group, every attempt as run_one produced it, and the score
    dict that was computed from that attempt."""
    out = prepared(monkeypatch, tmp_path, [], lambda item, attempt: fake_result(item))
    sidecar = json.loads(only(out, ".json").read_text(encoding="utf-8"))

    assert set(sidecar) == {"schema", "schema_version", "report", "fingerprint", "run", "started",
                            "ended", "seconds", "repeat", "requested_ids", "items", "totals",
                            "per_group", "attempt_totals", "questions"}
    assert sidecar["report"] == only(out, ".md").name        # the two files name each other
    assert sidecar["run"] == {"code": "abc1234", "repeat": 1}
    assert sidecar["repeat"] == 1 and sidecar["items"] == 2
    assert sidecar["requested_ids"] == []
    assert sidecar["totals"]["run"] == 2 and sidecar["totals"]["behavior_ok"] == 2
    assert sidecar["per_group"] == {"answer": {"behavior_ok": 1, "of": 1},
                                    "identify": {"behavior_ok": 1, "of": 1}}
    assert len(sidecar["attempt_totals"]) == 1               # one attempt index at --repeat 1

    question = sidecar["questions"][0]
    assert set(question) == {"id", "type", "group", "question", "attempts", "spread"}
    assert question["group"] == "answer"
    attempt = question["attempts"][0]
    for key in ("attempt", "answer", "verification", "provenance", "steps_taken", "read_chapters",
                "evidence_items", "clarify_asked", "clarify_chosen", "plan_fallback",
                "stop_reason", "catalog", "book_filter", "seconds", "steps_log",
                "cost_usd", "llm_calls", "tokens_in", "tokens_out", "score"):
        assert key in attempt, key
    # the full answer is IN the sidecar, not only in the Markdown: this file is
    # the machine-readable record of the run and has to stand on its own
    assert attempt["answer"] == "Moby Dick aboard the Pequod"
    assert attempt["score"]["behavior_ok"] is True
    assert attempt["provenance"] == {"checked": 2, "confirmed": 2, "unattributed": 0, "broken": 0}


def test_the_sidecar_round_trips_and_keeps_its_text_as_text(monkeypatch, tmp_path):
    """ensure_ascii=False, indent 2, and a second load that equals the first:
    a record nobody can read back is not a record."""
    answer = "Дракула у замку — Bram Stoker"
    out = prepared(monkeypatch, tmp_path, [],
                   lambda item, attempt: fake_result(item, answer=answer))
    raw = only(out, ".json").read_text(encoding="utf-8")
    assert answer in raw                                  # not Дра...
    assert raw.startswith("{\n  \"schema\"") and raw.endswith("\n")
    first = json.loads(raw)
    assert json.loads(json.dumps(first, ensure_ascii=False, indent=2)) == first


def test_no_json_writes_the_report_alone(monkeypatch, tmp_path):
    out = prepared(monkeypatch, tmp_path, ["--no-json"], lambda item, attempt: fake_result(item))
    assert only(out, ".md").exists()
    assert not list(out.glob("answers-*.json"))


# ---------------------------------------------------------------- --repeat
def test_repeat_counts_the_booleans_and_ranges_the_numbers(monkeypatch, tmp_path):
    """Scoring stays per attempt; the aggregation says how many of N passed and
    what the cost, the seconds and the tokens ranged over."""
    def results(item, attempt):
        if item["id"] != "q01-moby":
            return fake_result(item)
        # behaviour holds twice of three, and each attempt costs and takes its own
        return fake_result(item, behavior_ok=(attempt != 2),
                           score={"titles_mentioned": 1, "titles_expected": 1, "facts_found": attempt - 1,
                                  "facts_expected": 1, "facts_ok": attempt == 2,
                                  "behavior_ok": attempt != 2},
                           cost_usd=[0.01, 0.05, 0.03][attempt - 1],
                           seconds=[3, 9, 6][attempt - 1],
                           tokens_in=[100, 300, 200][attempt - 1])

    out = prepared(monkeypatch, tmp_path, ["--repeat", "3"], results)
    sidecar = json.loads(only(out, ".json").read_text(encoding="utf-8"))
    assert sidecar["repeat"] == 3 and len(sidecar["attempt_totals"]) == 3
    assert [t["behavior_ok"] for t in sidecar["attempt_totals"]] == [2, 1, 2]

    spread = sidecar["questions"][0]["spread"]
    assert spread == {"attempts": 3, "completed": 3, "errors": 0,
                      "behavior_ok": 2, "facts_ok": 1,
                      "cost_usd": {"min": 0.01, "median": 0.03, "max": 0.05},
                      "seconds": {"min": 3, "median": 6, "max": 9},
                      "llm_calls": {"min": 3, "median": 3, "max": 3},
                      "tokens_in": {"min": 100, "median": 200, "max": 300},
                      "tokens_out": {"min": 100, "median": 100, "max": 100}}

    report = only(out, ".md").read_text(encoding="utf-8")
    assert "### q01-moby — spread over 3 attempts" in report
    assert "- behavior PASS 2/3" in report and "- facts_ok 1/3" in report
    assert "- cost min / median / max: $0.0100 / $0.0300 / $0.0500" in report
    assert "- seconds min / median / max: 3 / 6 / 9" in report
    # every attempt is still its own scored row, and says which attempt it is
    assert report.count("- [ ] manual correctness") == 6
    assert ", attempt 2/3) — FAIL" in report


def test_the_headline_is_a_range_over_the_attempts_never_one_number(monkeypatch, tmp_path):
    """A pass count summed over three attempts (5 of 6) reads like a set of six
    questions. At N > 1 the headline states the range and the per-attempt mean,
    and every aggregate in the block gains its own spread line naming N."""
    def results(item, attempt):
        return fake_result(item, behavior_ok=not (item["id"] == "q01-moby" and attempt == 2))

    out = prepared(monkeypatch, tmp_path, ["--repeat", "3"], results)
    report = only(out, ".md").read_text(encoding="utf-8")
    tail = report[report.rindex("\n---\n"):]
    assert "behavior PASS 1–2/2 over 3 attempts (mean 1.67 per attempt; answer 0–1/1, identify 1–1/1)" in tail
    assert "spread over 3 attempts per item (every line above sums all 3 attempts):" in tail
    for line in ("- completed 2–2/2 over 3 attempts (mean 2.00 per attempt)",
                 "- errors 0–0 over 3 attempts (mean 0.00 per attempt)",
                 "- clarify interrupts 0–0 over 3 attempts (mean 0.00 per attempt)",
                 "- quotes confirmed 4–4/4 over 3 attempts (mean 4.00 per attempt)",
                 "- evidence items 6–6 over 3 attempts (mean 6.00 per attempt)",
                 "- behavior PASS 1–2/2 over 3 attempts (mean 1.67 per attempt)",
                 "- expected titles mentioned 2–2/2 over 3 attempts (mean 2.00 per attempt)",
                 "- expected facts found 2–2/2 over 3 attempts (mean 2.00 per attempt)",
                 "- answers carrying every expected fact 2–2/2 over 3 attempts (mean 2.00 per attempt)",
                 "- cost $0.0200–$0.0200 over 3 attempts (mean $0.0200 per attempt)",
                 "- llm calls 6–6 over 3 attempts (mean 6.00 per attempt)"):
        assert line in tail, line
    assert tail.endswith("manual correctness: not scored — tick the checkboxes above\n")


def test_an_errored_attempt_does_not_shrink_the_denominator(monkeypatch, tmp_path):
    """Two of three attempts completed and both passed: the item is 2/3, not
    2/2. A count out of what survived is how a flaky item comes to look green."""
    def results(item, attempt):
        if item["id"] == "q01-moby" and attempt == 3:
            raise RuntimeError("provider timeout")
        return fake_result(item)

    out = prepared(monkeypatch, tmp_path, ["--repeat", "3"], results)
    sidecar = json.loads(only(out, ".json").read_text(encoding="utf-8"))
    spread = sidecar["questions"][0]["spread"]
    assert spread["attempts"] == 3 and spread["completed"] == 2 and spread["errors"] == 1
    assert spread["behavior_ok"] == 2
    report = only(out, ".md").read_text(encoding="utf-8")
    assert "### q01-moby — spread over 3 attempts (1 errored)" in report
    assert "## q01-moby — ERROR\nprovider timeout\n(attempt 3/3, spent before the error:" in report


def test_repeat_runs_every_item_n_times_and_keeps_the_attempts_apart(monkeypatch, tmp_path):
    seen = []

    def results(item, attempt):
        seen.append((item["id"], attempt))
        return fake_result(item)

    prepared(monkeypatch, tmp_path, ["--repeat", "2"], results)
    assert seen == [("q01-moby", 1), ("q01-moby", 2), ("q02-drac", 1), ("q02-drac", 2)]


def test_repeat_zero_is_refused(monkeypatch, tmp_path):
    """Zero attempts is not a run: it would write an empty report and exit 0."""
    for bad in ("0", "-1"):
        with pytest.raises(SystemExit) as exc:
            harness.parse_args(["--repeat", bad])
        assert exc.value.code == 2
    assert harness.parse_args(["--repeat", "1"]).repeat == 1


# ---------------------------------------------------------------- byte-compat
def test_a_single_run_writes_the_markdown_it_always_wrote(monkeypatch, tmp_path):
    """The report and its `\\n---\\n` tail are a contract with
    eval/summarize_report.py and with every committed artifact under
    docs/eval-results/. At --repeat 1 nothing about them moves: no attempt
    marker, no per-item spread block, no extra totals line."""
    out = prepared(monkeypatch, tmp_path, [], lambda item, attempt: fake_result(item))
    report = only(out, ".md").read_text(encoding="utf-8")

    # no attempt marker in a heading, no per-item spread block, no spread lines
    # ("mean per attempted question" is the cost line this report has always had)
    assert ", attempt " not in report and "### " not in report and "spread" not in report
    assert ("## q01-moby (answer, 2 steps, 4s, $0.0100, 3 calls, 1000 in / 100 out tokens) — "
            "PASS: titles 1/1, facts 1/1, stop: enough evidence\n") in report
    tail = report[report.rindex("\n---\n"):]
    assert tail == (
        "\n---\n2 completed, 0 errors, 0 clarify interrupts; quotes verified 4/4 "
        "(confirmed / unattributed / broken = 4 / 0 / 0); evidence items 6\n"
        "behavior PASS 2/2 (answer 1/1, identify 1/1); expected titles mentioned 2/2\n"
        "expected facts found 2/2; answers carrying every expected fact 2/2 "
        "(substring presence, not correctness; not part of behaviour PASS)\n"
        "cost $0.0200 total, $0.0100 mean per attempted question (6 LLM calls, 2000 in / "
        "200 out tokens; configured rates "
        f"${harness.PRICE_IN_PER_MTOK}/M in, ${harness.PRICE_OUT_PER_MTOK}/M out, "
        "cache reads not discounted)\n"
        "manual correctness: not scored — tick the checkboxes above\n")


def test_the_same_fake_results_render_the_same_report_with_and_without_the_sidecar(
        monkeypatch, tmp_path):
    """The sidecar is written from the same records, not by a second pass over
    the report: turning it off must not change one byte of the Markdown."""
    with_json = prepared(monkeypatch, tmp_path / "a", [],
                         lambda item, attempt: fake_result(item))
    without = prepared(monkeypatch, tmp_path / "b", ["--no-json"],
                       lambda item, attempt: fake_result(item))
    first = only(with_json, ".md").read_text(encoding="utf-8")
    second = only(without, ".md").read_text(encoding="utf-8")
    # the header carries the run's own clock minute; compare everything under it
    assert first[first.index("run: "):] == second[second.index("run: "):]


def test_the_fingerprint_says_single_run_at_one_attempt_and_names_n_above_it():
    facts = {"code": "abc1234", "golden_name": "en-demo.yaml", "golden_sha256_12": "aaaa",
             "manifest_sha256_12": "bbbb", "toc_sha256_12": "cccc", "model": "m", "backend": "b",
             "index": ["cards=x"], "strict_hit_id": True, "clarify_pick": None,
             "search_hit_chars": 2500, "chapter_hit_chars": 6000, "max_steps": 8,
             "max_empty_streak": 2, "max_clarify_candidates": 4, "question_deadline_s": 120,
             "repeat": 1}
    assert harness.render_fingerprint(facts).endswith("| single run")
    assert harness.render_fingerprint({**facts, "repeat": 5}).endswith("| 5 attempts per item")


# ---------------------------------------------------------------- argparse
def test_the_old_flags_parse_to_what_they_always_meant():
    """Every flag the hand-rolled sys.argv slicing understood, in the orders it
    accepted them, and the ids left over as the positional argument."""
    assert harness.parse_args([]).ids == []
    assert harness.parse_args(["q01", "q02"]).ids == ["q01", "q02"]

    before = harness.parse_args(["--min-pass", "11", "--clarify-pick", "second", "q01"])
    after = harness.parse_args(["q01", "--min-pass", "11", "--clarify-pick", "second"])
    assert before.ids == after.ids == ["q01"]
    assert before.min_pass == after.min_pass == 11
    assert before.clarify_pick == after.clarify_pick == "second"

    clean = harness.parse_args(["--require-clean", "q01", "q02"])
    assert clean.require_clean is True and clean.ids == ["q01", "q02"]
    assert harness.parse_args([]).require_clean is False

    defaults = harness.parse_args([])
    assert defaults.min_pass is None and defaults.clarify_pick is None
    assert defaults.repeat == 1 and defaults.json is True
    assert harness.parse_args(["--no-json"]).json is False


def test_clarify_pick_still_reaches_the_module_global(monkeypatch, tmp_path):
    """`--clarify-pick second` is read by score() and by the fingerprint through
    the module global, exactly as the hand-rolled parsing set it."""
    monkeypatch.setattr(harness, "CLARIFY_PICK", None)
    prepared(monkeypatch, tmp_path, ["--clarify-pick", "second"],
             lambda item, attempt: fake_result(item))
    assert harness.CLARIFY_PICK == "second"


def test_min_pass_is_a_floor_on_every_attempt(monkeypatch, tmp_path):
    """Summed over three attempts a set of two questions can show 5 PASSes, and
    a --min-pass of 2 would be met by a run that failed a question twice."""
    def results(item, attempt):
        return fake_result(item, behavior_ok=not (item["id"] == "q01-moby" and attempt == 2))

    golden = tmp_path / "golden.yaml"
    golden.write_text(GOLDEN, encoding="utf-8")
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(harness, "build_graph", lambda: object())
    monkeypatch.setattr(harness, "run_facts", lambda repeat=1: {"repeat": repeat})
    monkeypatch.setattr(harness, "render_fingerprint", lambda facts: "code abc1234")
    monkeypatch.setattr(harness, "run_one", lambda graph, item, attempt=1: results(item, attempt))
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py", "--repeat", "3", "--min-pass", "2"])
    with pytest.raises(SystemExit) as exc:
        harness.main()
    assert exc.value.code == 1
