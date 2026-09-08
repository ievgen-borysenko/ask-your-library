"""summarize_report must not drop errored items: an ERROR row has no FAIL
marker, and a summary that says 'Failures: none' while totals count an error
misleads the reader."""
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load():
    spec = importlib.util.spec_from_file_location("summarize_report", REPO / "eval" / "summarize_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_error_rows_are_listed_under_failures(tmp_path, capsys, monkeypatch):
    report = tmp_path / "answers-1.md"
    report.write_text(
        "# Agent eval — x\n\nrun: code abc\n\n"
        "## q01-a (identify, 1 steps, 3s) — PASS: titles 1/1\n\ntext\n\n"
        "## q02-b — ERROR\nRuntimeError: provider timeout\n\n"
        "---\n1 completed, 1 errors, 0 clarify interrupts; quotes verified 1/1; evidence items 1\n"
        "behavior PASS 1/1 (identify 1/1); expected titles mentioned 1/1\n"
        "manual correctness: not scored — tick the checkboxes above\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_report.py", str(report)])
    load().main()
    out = capsys.readouterr().out
    assert "`q02-b`: ERROR, not completed: RuntimeError: provider timeout" in out
    assert "- none" not in out


def test_headings_with_cost_and_calls_still_parse(tmp_path, capsys, monkeypatch):
    """The per-question heading carries cost and call counts since 0.1.0; the
    FAIL regex must still find the item and its reason."""
    report = tmp_path / "answers-2.md"
    report.write_text(
        "# Agent eval — x\n\nrun: code abc\n\n"
        "## q01-a (identify, 2 steps, 9s, $0.0123, 5 calls, 100 in / 20 out tokens, clarify) — FAIL: titles 0/1\n\ntext\n\n"
        "---\n1 completed, 0 errors, 1 clarify interrupts; quotes verified 1/1; evidence items 1\n"
        "behavior PASS 0/1 (identify 0/1); expected titles mentioned 0/1\n"
        "cost $0.0123 total, $0.0123 mean per attempted question (5 LLM calls, 100 in / 20 out tokens; configured rates $3.0/M in, $15.0/M out, cache reads not discounted)\n"
        "manual correctness: not scored — tick the checkboxes above\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_report.py", str(report)])
    load().main()
    out = capsys.readouterr().out
    assert "`q01-a` (identify, 2 steps, 9s, $0.0123, 5 calls, 100 in / 20 out tokens, clarify): titles 0/1" in out
    assert "cost $0.0123 total" in out
