"""The CLI's argument handling: `--help` and `--version` are documentation, not
a run, so they must work in a fresh clone with no API key and no index."""
import pytest

from ask_your_library import cli


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    """No key, and a preflight that explodes if anything calls it: these tests
    fail loudly if --help/--version ever start touching the environment."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_ENV_FILE", raising=False)

    def forbidden():
        raise AssertionError("check_environment() was called for --help/--version")
    monkeypatch.setattr(cli, "check_environment", forbidden)

    def no_graph():
        raise AssertionError("build_graph() was called for --help/--version")
    monkeypatch.setattr(cli, "build_graph", no_graph)


@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_exit_zero_without_a_key(flag, capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main([flag])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip()          # something was printed


def test_version_reports_the_installed_version(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--version"])
    out = capsys.readouterr().out
    assert out.startswith("ask-library ") and cli.package_version() in out


def test_help_lists_the_question_and_the_language_switch(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    assert "question" in out and "--lang" in out and "--version" in out


def test_a_question_is_still_the_remaining_arguments():
    """The old contract (`ask-library what did X say`) must survive argparse."""
    args = cli.build_parser().parse_args(["what", "did", "X", "say"])
    assert " ".join(args.question) == "what did X say"
    assert args.lang is None
    assert cli.build_parser().parse_args(["--lang", "ua", "q"]).lang == "ua"
    assert cli.build_parser().parse_args([]).question == []


def test_an_unsupported_language_is_refused_before_anything_runs(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["--lang", "de", "q"])
    assert exit_info.value.code == 2
    assert "--lang" in capsys.readouterr().err


@pytest.fixture
def a_working_environment(monkeypatch):
    """Undo the autouse fixture's traps: a preflight that passes and records
    every call, and a graph that is a placeholder. Returns the call log."""
    calls = []

    def ok():
        calls.append("check_environment")
        return []
    monkeypatch.setattr(cli, "check_environment", ok)
    monkeypatch.setattr(cli, "build_graph", lambda: "graph")
    return calls


def test_the_interactive_loop_checks_the_environment_once_before_it_starts(
        a_working_environment, monkeypatch, capsys):
    """No arguments = the chat loop. The preflight belongs in front of the
    loop, not inside it: once per session, before the first prompt."""
    def eof(_prompt):
        # the loop's first input() ends the session, so nothing runs afterwards
        assert a_working_environment == ["check_environment"]      # already checked
        raise EOFError
    monkeypatch.setattr("builtins.input", eof)
    monkeypatch.setattr(cli, "_run", lambda *a, **k: pytest.fail("no question was asked"))

    assert cli.main([]) is None                                    # a clean session exits 0
    assert a_working_environment == ["check_environment"]
    assert capsys.readouterr().out.strip()                         # banner and goodbye


def test_a_failed_single_question_exits_non_zero(a_working_environment, monkeypatch):
    """_run() reports the failure and returns "": scripts and evals must see
    that in the exit code too, not only in the message."""
    monkeypatch.setattr(cli, "_run", lambda *a, **k: "")
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["what", "did", "X", "say"])
    assert exit_info.value.code == 1

    monkeypatch.setattr(cli, "_run", lambda *a, **k: "an answer")
    assert cli.main(["what", "did", "X", "say"]) is None            # a good run still exits 0


def test_a_failing_run_is_reported_without_a_traceback(a_working_environment, monkeypatch, capsys):
    """The single-question exit code comes from _run() returning "" — which is
    what _run does with any exception unless ASK_DEBUG is set."""
    def explode(*_args, **_kwargs):
        raise RuntimeError("no index")
    monkeypatch.setattr(cli, "run_question", explode)
    monkeypatch.delenv("ASK_DEBUG", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["a", "question"])
    assert exit_info.value.code == 1
    assert "RuntimeError" in capsys.readouterr().err

    monkeypatch.setenv("ASK_DEBUG", "1")
    with pytest.raises(RuntimeError):
        cli.main(["a", "question"])


def test_deadline_flag_is_an_integer_of_seconds_and_optional():
    args = cli.build_parser().parse_args(["--deadline", "45", "what", "happened"])
    assert args.deadline == 45 and " ".join(args.question) == "what happened"
    assert cli.build_parser().parse_args(["q"]).deadline is None       # None = the configured default
    assert cli.build_parser().parse_args(["--deadline", "0", "q"]).deadline == 0


def test_a_negative_deadline_is_refused_like_the_env_knob(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.build_parser().parse_args(["--deadline", "-5", "q"])
    assert exit_info.value.code == 2 and "0 (none) or a positive" in capsys.readouterr().err


def test_plan_event_says_when_the_planner_fell_back_to_the_raw_question(capsys):
    from ask_your_library.i18n import t
    cli.print_event("plan", {"mode": "answer", "current_query": "q", "queries": []})
    assert t("ev_plan_fallback") not in capsys.readouterr().out
    cli.print_event("plan", {"mode": "answer", "current_query": "q", "queries": [], "plan_fallback": True})
    assert t("ev_plan_fallback") in capsys.readouterr().out


def test_verbose_prints_every_evidence_item_on_the_passage_it_was_checked_against(capsys, monkeypatch):
    from ask_your_library.i18n import t
    monkeypatch.setitem(cli.RUN, "verbose", True)
    monkeypatch.setitem(cli.RUN, "passages", {})
    cli.print_event("act", {"steps_taken": 1, "hits": [{}],
                            "hits_log": [{"hit_id": "s1h1", "text": "Call me Ishmael.\x1b\x00\nSome years ago."}]})
    items = [{"hit_id": "s1h1", "book": "Moby Dick — Herman Melville", "section": "Chapter 1",
              "quote": "Call me Ishmael.", "status": "confirmed"},
             {"hit_id": "s1h1", "book": "Moby Dick — Herman Melville", "section": "Chapter 1",
              "quote": "Some years ago.", "status": "confirmed"},
             {"hit_id": "s9h9", "book": "B — A", "section": "s", "quote": "gone\x07", "status": "broken"}]
    cli.print_event("validate", {"verification": "OK", "provenance": {"items": items}})
    out = capsys.readouterr().out
    assert t("ev_evidence_header", n=3) in out
    assert f'{t("ev_status_confirmed")}: Moby Dick — Herman Melville — Chapter 1 [s1h1]: "Call me Ishmael."' in out
    assert out.count("    Call me Ishmael.\n    Some years ago.") == 1      # the passage once, under its first quote
    assert "\x1b" not in out and "\x07" not in out                        # control characters never reach the terminal
    assert f'{t("ev_status_broken")}: B — A' in out and t("ev_passage_missing") in out
    monkeypatch.setitem(cli.RUN, "verbose", False)
    cli.print_event("validate", {"verification": "OK", "provenance": {"items": items}})
    assert t("ev_evidence_header", n=3) not in capsys.readouterr().out


def test_no_line_of_a_run_carries_an_escape_sequence(capsys, monkeypatch):
    """Book keys, queries, the answer, the provenance line and the clarify
    question all come from the corpus or from a model that read it. The verbose
    evidence list was sanitized; the rest of the report was not, so one crafted
    title could retitle or repaint the terminal of whoever ran the question."""
    osc = "\x1b]0;pwned\x07"
    monkeypatch.setitem(cli.RUN, "verbose", False)
    cli.print_event("plan", {"mode": "answer", "current_query": f"whales {osc}", "queries": []})
    cli.print_event("act", {"steps_taken": 1, "hits": [{}], "hits_log": []})
    cli.print_event("reflect", {"current_query": f"__chapter__|Moby Dick{osc}|Chapter 1"})
    cli.print_event("reflect", {"current_query": "", "stop_reason": f"reflect: {osc}"})
    cli.print_event("clarify", {"clarification": f"the first one {osc}"})
    cli.print_event("synthesize", {"answer": f"An answer [Moby Dick{osc}, Chapter 1]."})
    cli.print_event("validate", {"verification": f"OK: 1 quote {osc}",
                                 "provenance": {"items": []}})
    cli.print_event("metrics", {"model": f"m{osc}", "llm_calls": 1, "input_tokens": 1,
                                "output_tokens": 1, "cost_usd": 0.01, "seconds": 1,
                                "steps_taken": 1, "stop_reason": f"enough {osc}", "by_role": {},
                                "hits_seen": 1, "evidence_distilled": 1, "redacted_lines": 0,
                                "cache_read_tokens": 0})
    monkeypatch.setattr("builtins.input", lambda prompt="": "the first one")
    cli.ask_in_terminal(f"Which book? {osc}")
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "pwned" in out and "An answer [Moby Dick" in out    # shown as text, only inert


def test_each_question_starts_with_no_passages(monkeypatch):
    """The interactive loop asks question after question: passages of question
    N-1 must not be shown under the quotes of question N."""
    cli.RUN["passages"]["stale"] = "old text"
    seen = {}

    def fake_run_question(graph, question, history, scratch_dir, on_event, on_clarify, deadline_s=None):
        seen["passages_at_start"] = dict(cli.RUN["passages"])
        return "answer"
    monkeypatch.setattr(cli, "run_question", fake_run_question)
    assert cli._run(None, "q", []) == "answer" and seen["passages_at_start"] == {}


def test_verbose_flag_parses():
    assert cli.build_parser().parse_args(["--verbose", "q"]).verbose is True
    assert cli.build_parser().parse_args(["q"]).verbose is False
