"""Ask Your Library — command-line interface.

  uv run ask-library                        # chat: question after question, with memory
  uv run ask-library "What did X say about Y?"   # single question (scripts, evals)
  uv run ask-library --help / --version     # no API key, no index needed

The web UI (ui.py, Chainlit) shares the same core: runner.run_question.
Answering a question requires an answering model and an embedding backend —
both a local Ollama by default (qwen2.5:14b and bge-m3), so a fresh clone needs
no account and no key — plus a LanceDB built by scripts/ingest_demo_corpus.py or
`ayl-add`, or pointed to by LIBRARY_DB_PATH. OPENROUTER_API_KEY is needed only
when the answering model or the embeddings are moved to OpenRouter. All of it is
checked by the preflight, which runs only when a run is actually about to start.

Exit codes: 0 an answer, 1 the environment is not ready (or the run failed),
3 no index yet, 4 a hosted backend with no key, 5 Ollama is not there yet — the
codes preflight.exit_code assigns, so a wrapper script can tell the first-run
conditions apart without matching on translated text. 2 is argparse's own, for a
bad command line.
"""
import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .bookkey import split_read_query
from .config import QUESTION_DEADLINE_S, SUPPORTED_LANGS
from .graph import build_graph
from .i18n import set_lang, source_word, status_word, t
from .preflight import check_environment, exit_code
from .runner import RunResult, failed_result, history_entry, run_question
from .sanitize import LINE_BREAK_RE, strip_control_chars

EXIT_WORDS = {"exit", "quit", "q", "вихід"}
SCRATCH_DIR = Path(os.environ.get("ASK_SCRATCH_DIR", ".scratch"))

# Session totals live in the interface: the metrics event is always about one
# question. A question that FAILED emits that event too (since 16.09, so the
# calls it paid for are not lost), so it counts here as well: the session line
# is what the session spent and how many questions were attempted, not how many
# were answered. That is what a cost line should say.
SESSION = {"questions": 0, "cost_usd": 0.0}
# Per-question memory of the CLI: the passages of this run by hit_id (from the act
# events), so --verbose can print each evidence item on the text it was checked
# against. The CLI answers one question at a time; _run resets it. The catalogue
# result is NOT kept here any more — it comes back on the result object, so the
# conversation memory reads it from the one record of the run.
RUN = {"passages": {}, "verbose": False}


def terminal_safe(text: str) -> str:
    """Text printed by the CLI must not repaint or clear the terminal:
    sanitize_context redacts instruction lines, not escape sequences.

    A line break is text and stays, but it leaves as a plain LF, whatever form
    it arrived in: a bare CR would put the cursor back at the start of the line
    just printed and let the next characters overwrite it."""
    return LINE_BREAK_RE.sub("\n", strip_control_chars(text))


def say(line: str, error: bool = False) -> None:
    """Every line the CLI prints goes out through here, the banner and the
    echoed question included.

    Book titles, section names, queries, the answer, the provenance line and
    the failure messages all carry corpus text or model output shaped by it,
    and the labels around them are ours, so one strip on the finished line
    covers the lot, and there is no second place a poisoned title could reach
    the terminal from."""
    print(terminal_safe(line), file=sys.stderr if error else sys.stdout)


def print_event(node_name: str, update: dict) -> None:
    """One line per graph event (language: ASK_LANG)."""
    if node_name == "plan":
        if update["mode"] == "catalog":
            say(t("ev_plan_catalog", op=update["catalog_request"]["op"]))
        else:
            say(t("ev_plan", mode=update["mode"],
                  queries=[update["current_query"]] + update["queries"]))
        if update.get("catalog_fallback"):
            say(t("ev_catalog_fallback_" + update["catalog_fallback"]))
        if update.get("book_filter"):
            say(t("ev_book_filter", book=update["book_filter"]))
        if update.get("book_unresolved"):
            say(t("ev_book_unresolved", q=update["book_unresolved"]))
        if update.get("clarify_unresolved"):
            say(t("ev_clarify_unresolved"))
        if update.get("plan_fallback"):
            say(t("ev_plan_fallback"))
    elif node_name == "act":
        say(t("ev_act", n=update["steps_taken"], hits=len(update["hits"])))
        for h in update.get("hits_log", []):
            RUN["passages"][h["hit_id"]] = h["text"]
    elif node_name == "observe":
        streak = update["empty_streak"]
        note = t("ev_streak", n=streak) if streak else ""
        say(t("ev_observe", n=len(update["evidence"]), streak=note))
    elif node_name == "reflect":
        # A chapter read may carry what the model is looking for (ADR-025); the
        # line a reader sees is about the chapter, so the query comes off here
        # and everything below reads the marker it always read.
        nxt, _ = split_read_query(update.get("current_query") or "")
        if nxt == "__clarify__":
            say(t("ev_reflect_clarify"))
        elif nxt and nxt.startswith("__chapter__|"):
            _, book, section = nxt.split("|", 2)
            say(t("ev_reflect_chapter", book=book, section=section))
        elif nxt and nxt.startswith("__book__|"):
            _, book, _ = nxt.split("|", 2)
            say(t("ev_reflect_probe", book=book))
        elif nxt:
            say(t("ev_reflect_search", q=nxt))
        elif update.get("stop_reason"):
            say(t("ev_reflect_stopped", r=update["stop_reason"]))
        else:
            say(t("ev_reflect_enough"))
    elif node_name == "clarify":
        say(t("ev_clarify", a=update["clarification"]))
    elif node_name == "catalog":
        listing = update["catalog"]
        say(t("ev_catalog", op=listing["op"], n=listing["count"], total=listing["total"]))
        say(t("ev_answer_header", a=update["answer"]))
    elif node_name == "synthesize":
        say(t("ev_answer_header", a=update["answer"]))
    elif node_name == "validate":
        say(t("ev_provenance", v=update["verification"]))
        items = (update.get("provenance") or {}).get("items") or []
        if RUN["verbose"] and items:
            say(t("ev_evidence_header", n=len(items)))
            shown: set[str] = set()
            for item in items:
                # What kind of passage the quote is pinned to, beside the
                # verdict: "unattributed" or "not found verbatim" against a book
                # CARD is a different fact from the same verdict against a
                # chapter, and the reader of a verbose run could not tell them
                # apart. Empty when the record does not say, which is the only
                # case where nothing is claimed.
                source = source_word(item.get("source_kind", ""))
                say(t("ev_evidence_item", status=status_word(item["status"]),
                      source=f" ({source})" if source else "", book=item["book"],
                      section=item["section"], hit_id=item["hit_id"], quote=item["quote"]))
                if item["hit_id"] in shown:
                    continue                      # the passage is printed once, under its first quote
                shown.add(item["hit_id"])
                passage = RUN["passages"].get(item["hit_id"])
                if passage is None:
                    say(t("ev_passage_missing"))
                else:
                    say("    " + passage.replace("\n", "\n    "))
    elif node_name == "metrics" and update.get("partial"):
        # paused at a clarify: what the run has cost so far, not a session total
        say(t("m_partial", cost=update["cost_usd"], calls=update["llm_calls"],
              sec=update["seconds"]))
    elif node_name == "metrics":
        SESSION["questions"] += 1
        SESSION["cost_usd"] += update["cost_usd"]
        say(t("m_line1", model=update["model"], calls=update["llm_calls"],
              tin=update["input_tokens"], tout=update["output_tokens"],
              cost=update["cost_usd"], sec=update["seconds"],
              steps=update["steps_taken"]))
        say(t("m_stop", r=update["stop_reason"] or t("m_stop_default")))
        roles = ", ".join(f"{role} ${u['cost_usd']:.4f} ({u['calls']}x)"
                          for role, u in update["by_role"].items())
        say(t("m_roles", roles=roles))
        say(t("m_retrieval", hits=update["hits_seen"],
              ev=update["evidence_distilled"], red=update["redacted_lines"]))
        if update["cache_read_tokens"]:
            say(t("m_cache", n=update["cache_read_tokens"]))
        if SESSION["questions"] > 1:
            say(t("m_session", q=SESSION["questions"], cost=SESSION["cost_usd"]))


def ask_in_terminal(question_to_user: str) -> str:
    # The clarify question is written by the model around book titles it read.
    say(f"\n[?] {question_to_user}")
    return input(t("cli_your_answer")).strip()


def _run(graph, question: str, history: list[str], deadline_s: float | None = None) -> RunResult:
    """One question with human-readable failure instead of a traceback
    (ASK_DEBUG=1 re-raises).

    The runner reports a failure INSIDE the run on the result rather than by
    raising, so that the calls it spent are still accounted for; anything that
    goes wrong around the run (the scratchpad, mostly) still arrives as an
    exception. Both end the same way for the reader: one line, an empty answer,
    and exit 1 in single-question mode."""
    RUN["passages"] = {}
    try:
        result = run_question(graph, question, history, SCRATCH_DIR,
                              on_event=print_event, on_clarify=ask_in_terminal,
                              deadline_s=deadline_s)
    except Exception as error:
        if os.environ.get("ASK_DEBUG"):
            raise
        result = failed_result(question, error)
    if result.failure is not None:
        if os.environ.get("ASK_DEBUG") and result.failure.error is not None:
            raise result.failure.error
        # The message can carry index text (a book named in a lookup failure).
        say(t("cli_run_error", e=str(result.failure)), error=True)
    return result


def package_version() -> str:
    """The installed distribution's version; `unknown` when the package is run
    from a source tree that was never installed."""
    try:
        return version("ask-your-library")
    except PackageNotFoundError:
        return "unknown"


def _seconds(value: str) -> int:
    """--deadline: 0 or a positive number of seconds; the env knob rejects a
    negative value at import, so the flag must not accept one silently."""
    seconds = int(value)
    if seconds < 0:
        raise argparse.ArgumentTypeError("the deadline is 0 (none) or a positive number of seconds")
    return seconds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ask-library",
        description="Agentic RAG over your own book library.",
        epilog="Without a question the CLI opens an interactive chat with memory "
               "(`exit`, `quit` or Ctrl-D leaves it). Everything else is configured "
               "through environment variables; see .env.example.")
    parser.add_argument("--version", action="version",
                        version=f"ask-library {package_version()}")
    # ASK_LANG is otherwise the only way to switch language, and it is a process
    # default; this is the same switch for a single run.
    parser.add_argument("--lang", choices=sorted(SUPPORTED_LANGS),
                        help="language of the interface and of the agent's answers for "
                             "this run (default: $ASK_LANG, else en)")
    parser.add_argument("--verbose", action="store_true",
                        help="after the provenance line, print every evidence item with its verdict "
                             "and the retrieved passage it was checked against")
    parser.add_argument("--deadline", type=_seconds, metavar="SECONDS",
                        help="time budget per question: the loop stops searching once it is "
                             "spent and answers from what it found, with the reason shown; "
                             f"0 = none (default: $QUESTION_DEADLINE_S, else {QUESTION_DEADLINE_S})")
    parser.add_argument("question", nargs="*",
                        help="the question to ask; quote it, or put it after `--` if it "
                             "starts with a dash")
    return parser


def main(argv: list[str] | None = None) -> None:
    # Parsing first: --help and --version must work in a fresh clone with no API
    # key and no index, so nothing may touch the environment before this.
    args = build_parser().parse_args(argv)
    if args.lang:
        set_lang(args.lang)
    RUN["verbose"] = bool(args.verbose)

    problems = check_environment()
    if problems:
        say(t("pf_header"), error=True)
        for problem in problems:
            say(f"  - {problem}", error=True)
        # Every problem is printed; the status names the one to fix first. A
        # missing Ollama and a missing index are the two ways a fresh clone
        # fails, they are not the same failure, and neither is a traceback —
        # so they do not share the one exit code they used to.
        raise SystemExit(exit_code(problems))
    # Non-fatal: the agent runs, but the user is told how the index is degraded.
    notices = getattr(problems, "notices", [])
    if notices:
        say(t("pf_notice_header"), error=True)
        for notice in notices:
            say(f"  - {notice}", error=True)

    graph = build_graph()

    if args.question:
        question = " ".join(args.question)
        say(t("cli_question", q=question) + "\n")
        # Single-question mode is what scripts and evals call: a failed run has
        # to be visible in the exit code, not only in the message _run printed.
        # (The interactive loop keeps going instead — a bad question there is
        # not a failed session.) `ok` is asked FIRST and separately from the
        # answer: a run that died after synthesize carries the text it had
        # written, and a caller that reads exit 0 would take that half-finished
        # answer for a complete one.
        result = _run(graph, question, history=[], deadline_s=args.deadline)
        if not result.ok or not result.answer:
            raise SystemExit(1)
        return

    say(t("cli_banner"))
    history: list[str] = []
    while True:
        try:
            question = input(t("cli_you")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question or question.lower() in EXIT_WORDS:
            break

        result = _run(graph, question, history, deadline_s=args.deadline)
        if not result.ok or not result.answer:
            # The session goes on, the memory does not take it: an answer from a
            # run that failed is whatever had been written when it died, and the
            # next planner and synthesize prompt would read it as a turn that
            # happened. The failure was already printed by _run.
            continue
        # Conversation memory: the question plus a truncated answer; a catalogue
        # answer only as its shape, never the list of titles.
        history.append(history_entry(question, result.answer, result.catalog or None))

    say(t("cli_bye"))


if __name__ == "__main__":
    main()
