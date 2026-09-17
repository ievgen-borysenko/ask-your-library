"""The CLI's argument handling: `--help` and `--version` are documentation, not
a run, so they must work in a fresh clone with no API key and no index."""
import re
from pathlib import Path

import pytest

from ask_your_library import cli
from ask_your_library import nodes as cli_nodes


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
    """_run() reports the failure and comes back with no answer: scripts and
    evals must see that in the exit code too, not only in the message."""
    from ask_your_library.runner import RunResult
    monkeypatch.setattr(cli, "_run", lambda *a, **k: RunResult(question="q"))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["what", "did", "X", "say"])
    assert exit_info.value.code == 1

    monkeypatch.setattr(cli, "_run", lambda *a, **k: RunResult(question="q", answer="an answer"))
    assert cli.main(["what", "did", "X", "say"]) is None            # a good run still exits 0


def test_a_failing_run_is_reported_without_a_traceback(a_working_environment, monkeypatch, capsys):
    """The single-question exit code comes from _run() coming back with no
    answer — which is what _run does with any exception unless ASK_DEBUG is
    set. A failure INSIDE the run arrives on the result instead (the runner
    keeps the metrics of what it spent); this is the other half: anything
    raised around the run, the scratchpad included."""
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


def test_a_run_that_reports_its_failure_on_the_result_still_exits_non_zero(
        a_working_environment, monkeypatch, capsys):
    """The runner reports a failure inside the run on the result (so that the
    metrics of what it spent are still emitted) instead of raising. The CLI must
    treat that exactly like the exception it used to catch: one line, no
    traceback, and exit 1 in single-question mode."""
    from ask_your_library.runner import RunFailure, RunResult

    failed = RunResult(question="q", failure=RunFailure(type="RuntimeError",
                                                        message="no checkpoint"))
    monkeypatch.setattr(cli, "run_question", lambda *a, **k: failed)
    monkeypatch.delenv("ASK_DEBUG", raising=False)
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["a", "question"])
    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "RuntimeError: no checkpoint" in err and "Traceback" not in err


def test_a_salvaged_answer_from_a_failed_run_is_not_taken_for_an_answer(
        a_working_environment, monkeypatch, capsys):
    """A run can die after synthesize has written something: the result then
    carries BOTH a failure and text. Single-question mode must still exit 1 —
    a script that reads exit 0 would publish a half-finished answer — and the
    interactive loop must not put that text into the conversation memory, where
    the next planner and synthesize prompt would read it as a turn that
    happened."""
    from ask_your_library.runner import RunFailure, RunResult
    from ask_your_library.runner import history_entry as real_history_entry

    half = RunResult(question="q", answer="partial",
                     failure=RunFailure(type="RuntimeError", message="the index went away"))
    monkeypatch.setattr(cli, "run_question", lambda *a, **k: half)
    monkeypatch.delenv("ASK_DEBUG", raising=False)

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["a", "question"])
    assert exit_info.value.code == 1
    assert "RuntimeError: the index went away" in capsys.readouterr().err

    remembered = []
    monkeypatch.setattr(cli, "history_entry",
                        lambda *a, **k: remembered.append(a) or real_history_entry(*a, **k))
    answers = iter(["a question", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    cli.main([])
    assert remembered == []            # the session goes on; its memory does not take it


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


def test_the_plan_event_of_a_catalogue_question_names_the_operation(capsys):
    from ask_your_library.i18n import t
    cli.print_event("plan", {"mode": "catalog", "current_query": "", "queries": [],
                             "catalog_request": {"op": "count", "title": "", "author": ""}})
    out = capsys.readouterr().out
    assert t("ev_plan_catalog", op="count") in out
    assert t("ev_plan", mode="catalog", queries=[""]) not in out       # not the research-loop line
    moby = "Moby Dick — Herman Melville"
    cli.print_event("plan", {"mode": "answer", "current_query": "q", "queries": [],
                             "catalog_fallback": "mixed_intent", "book_filter": moby})
    out = capsys.readouterr().out
    assert t("ev_catalog_fallback_mixed_intent") in out
    assert t("ev_book_filter", book=moby) in out


def test_the_plan_event_of_a_refused_request_says_so_instead_of_listing_no_queries(capsys):
    """The scope gate (#70) plans no query at all. The research-loop line would
    print `queries: ['']` — the empty current_query in a list — which is the one
    thing the reader must not read as "it searched for nothing"."""
    from ask_your_library.i18n import t
    cli.print_event("plan", {"mode": "refusal", "current_query": "", "queries": [],
                             "stop_reason": t("stop_out_of_scope")})
    out = capsys.readouterr().out
    assert t("ev_plan_refusal") in out
    assert t("ev_plan", mode="refusal", queries=[""]) not in out
    assert "queries" not in out


def test_the_catalog_event_prints_the_listing_and_keeps_only_its_shape(capsys, monkeypatch):
    """The CLI's history entry after a catalogue answer: the operation and the
    counts, never the titles (they went to the terminal, not to the next
    planner call). Titles are index metadata, so control characters are
    stripped from the answer as from any other passage the CLI prints."""
    from ask_your_library.i18n import t
    from ask_your_library.runner import history_entry
    listing = {"op": "list", "count": 2, "total": 2, "query": "", "resolved": True,
               "books": ["Moby Dick — Herman Melville", "My Private Notes — Unknown"]}
    answer = ("2 books in your library:\n- Moby Dick — Herman Melville\n"
              "- My Private\x1b[2J Notes — Unknown")
    cli.print_event("catalog", {"catalog": listing, "answer": answer})
    out = capsys.readouterr().out
    assert t("ev_catalog", op="list", n=2, total=2) in out
    assert "Moby Dick — Herman Melville" in out and "\x1b" not in out
    # the listing the conversation memory is built from comes back on the run's
    # result (runner.RunResult.catalog), not out of the rendering of this event
    entry = history_entry("what are my books called?", answer, listing)
    assert "Moby Dick" not in entry and "My Private" not in entry
    assert entry == "Q: what are my books called?\nA: " + t(
        "history_catalog", op="list", n=2, total=2, q="-", found=t("history_yes"))


@pytest.mark.parametrize("reason", cli_nodes.CATALOG_FALLBACKS)
@pytest.mark.parametrize("lang", ["en", "ua"])
def test_every_catalogue_fallback_has_a_line_in_both_interfaces_and_languages(reason, lang):
    """The interfaces build these keys by composition ("ev_catalog_fallback_" +
    reason), and t() raises KeyError on an unknown one: a fourth reason must
    not reach a user as a crash in one language only."""
    from ask_your_library import i18n
    from ask_your_library.i18n import t
    before = i18n.get_lang()
    try:
        i18n.set_lang(lang)
        assert t("ev_catalog_fallback_" + reason) and t("ui_catalog_fallback_" + reason)
    finally:
        i18n.set_lang(before)


# Every line that shows a stop reason already says that the run stopped, and the
# three of them are these: cli.print_event's `[reflect] stopped: {r}` and its
# metrics `  stop: {r}`, and ui.render_event's `stopped: {r}`. Each is paired
# here with the word it carries, because English uses two of them.
STOP_LINES = {
    "en": (("ev_reflect_stopped", "stopped:"), ("ui_stopped", "stopped:"), ("m_stop", "stop:")),
    "ua": (("ev_reflect_stopped", "зупинка:"), ("ui_stopped", "зупинка:"), ("m_stop", "зупинка:")),
}

# eval/run_agent_eval.py is a fourth renderer of the same reasons — nodes.py puts
# `t("stop_*")` into state["stop_reason"] and the report prints it — but it has
# no i18n table behind it: its prefixes are English literals in two f-strings,
# the step log's `reflect -> stop: ` and the header's `, stop: `. They are read
# out of the file instead of copied here, so a rename, a removal or a third site
# fails this test rather than drifting away from it silently.
EVAL_SCRIPT = Path(__file__).resolve().parents[1] / "eval" / "run_agent_eval.py"


def eval_stop_prefixes():
    source = EVAL_SCRIPT.read_text(encoding="utf-8")
    return re.findall(r'f"([^"]*?)\{[^"}]*stop_reason[^"}]*\}"', source)


@pytest.mark.parametrize("lang", ["en", "ua"])
def test_a_stop_reason_never_repeats_the_word_its_own_line_carries(lang):
    """`stop_chapter_again` opened with "stopped: " while all three renderers
    add that word themselves, so a chapter asked for twice printed
    `[reflect] stopped: stopped: requested chapter was already attempted`.
    The reasons are read out of the table rather than listed here: the next one
    someone writes with the prefix baked in has to fail this, not just the one
    that had it. The eval report renders the same reasons and is checked with
    them, its prefixes being English in both languages."""
    from ask_your_library import i18n
    from ask_your_library.i18n import t
    prefixes = eval_stop_prefixes()
    assert len(prefixes) == 2, f"eval/run_agent_eval.py renders {len(prefixes)} stop lines"
    before = i18n.get_lang()
    try:
        i18n.set_lang(lang)
        reasons = sorted(key for key in i18n._T if key.startswith("stop_"))
        assert "stop_chapter_again" in reasons                  # the table is being read, not an empty set
        for key in reasons:
            # Placeholder values for the reasons that take one; format ignores
            # the arguments a reason does not name.
            reason = t(key, n=2, s=30)
            for word in {word for _, word in STOP_LINES[lang]}:
                assert not reason.startswith(word), f"{key} ({lang}) opens with {word!r}"
            for line, word in STOP_LINES[lang]:
                assert t(line, r=reason).count(word) == 1, f"{line} doubles {word!r} on {key}"
            for prefix in prefixes:
                assert "stop:" in prefix, f"eval prefix {prefix!r} no longer says it stopped"
                assert f"{prefix}{reason}".count("stop:") == 1, \
                    f"eval's {prefix!r} doubles 'stop:' on {key} ({lang})"
    finally:
        i18n.set_lang(before)


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


def test_verbose_says_which_evidence_is_pinned_to_a_book_card(capsys, monkeypatch):
    """"not found verbatim" against a book CARD and the same verdict against a
    chapter are different facts — one says a model's summary does not contain
    the quote, the other says the book does not — and a reader of a verbose run
    could not tell them apart. Every item carries `source_kind`; the line says
    it, in the reader's language, and says nothing when the record does not."""
    from ask_your_library.i18n import source_word, status_word, t
    monkeypatch.setitem(cli.RUN, "verbose", True)
    monkeypatch.setitem(cli.RUN, "passages", {})
    items = [{"hit_id": "s1h1", "book": "Dracula — Bram Stoker", "section": "Key Takeaways",
              "quote": "The hunters chase the count", "status": "card_only", "source_kind": "card"},
             {"hit_id": "s1h2", "book": "Dracula — Bram Stoker", "section": "Chapter 27",
              "quote": "crumbled into dust", "status": "confirmed", "source_kind": "book_text"},
             {"hit_id": "s1h3", "book": "Dracula — Bram Stoker", "section": "Summary",
              "quote": "nowhere at all", "status": "broken", "source_kind": "card"},
             # a record from before source_kind existed claims nothing
             {"hit_id": "s1h4", "book": "B — A", "section": "s", "quote": "old", "status": "broken"}]
    cli.print_event("validate", {"verification": "OK", "provenance": {"items": items}})
    out = capsys.readouterr().out
    card, text = source_word("card"), source_word("book_text")
    assert f'{status_word("card_only")} ({card}): Dracula — Bram Stoker — Key Takeaways' in out
    assert f'{status_word("confirmed")} ({text}): Dracula — Bram Stoker — Chapter 27' in out
    # the point of the item: a broken quote pinned to a card says so
    assert f'{status_word("broken")} ({card}): Dracula — Bram Stoker — Summary' in out
    assert f'{status_word("broken")}: B — A' in out          # no empty parentheses
    assert "()" not in out
    # and it speaks the session's language
    import ask_your_library.i18n as i18n
    before = i18n.get_lang()
    try:
        i18n.set_lang("ua")
        cli.print_event("validate", {"verification": "OK", "provenance": {"items": items[:1]}})
        assert source_word("card") in capsys.readouterr().out
    finally:
        i18n.set_lang(before)


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

    from ask_your_library.runner import RunResult

    def fake_run_question(graph, question, history, scratch_dir, on_event, on_clarify, deadline_s=None):
        seen["passages_at_start"] = dict(cli.RUN["passages"])
        return RunResult(question=question, answer="answer")
    monkeypatch.setattr(cli, "run_question", fake_run_question)
    assert cli._run(None, "q", []).answer == "answer" and seen["passages_at_start"] == {}


def test_verbose_flag_parses():
    assert cli.build_parser().parse_args(["--verbose", "q"]).verbose is True
    assert cli.build_parser().parse_args(["q"]).verbose is False


# --- the exit status of a first run ------------------------------------------

@pytest.mark.parametrize("kind, expected", [
    ("no_ollama", 5),          # nothing to answer with yet
    ("no_db", 3),              # nothing to search yet
    ("no_key", 4),             # a hosted backend without its key
    ("index_mismatch", 1),     # anything else: the status it always had
])
def test_the_preflight_status_reaches_the_shell(monkeypatch, capsys, kind, expected):
    """The CLI exits with preflight's classification, not a flat 1. A wrapper
    script around `ask-library` has nothing else to read: the messages are
    translated, so matching on their prose is what these codes replace."""
    from ask_your_library.preflight import PreflightResult

    monkeypatch.setattr(cli, "check_environment",
                        lambda: PreflightResult(["the problem, in prose"], (), [kind]))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["a question"])
    assert exit_info.value.code == expected
    # Whatever the status, the reader still gets the sentence with the remedy.
    assert "the problem, in prose" in capsys.readouterr().err


def test_a_first_run_prints_every_problem_and_leads_with_one(monkeypatch, capsys):
    """No Ollama and no index at once is the ordinary shape of a fresh clone.
    Both are printed; the status names the one that has to be fixed first."""
    from ask_your_library.preflight import PreflightResult

    monkeypatch.setattr(cli, "check_environment",
                        lambda: PreflightResult(["no ollama", "no index"], (),
                                                ["no_ollama", "no_db"]))
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["a question"])
    assert exit_info.value.code == 5
    err = capsys.readouterr().err
    assert "no ollama" in err and "no index" in err
