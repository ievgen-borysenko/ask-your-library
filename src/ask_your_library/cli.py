"""Ask Your Library — command-line interface.

  uv run ask-library                        # chat: question after question, with memory
  uv run ask-library "What did X say about Y?"   # single question (scripts, evals)
  uv run ask-library --help / --version     # no API key, no index needed

The web UI (ui.py, Chainlit) shares the same core: runner.run_question.
Answering a question requires an embedding backend (local Ollama with bge-m3 by
default), a LanceDB built by scripts/ingest_demo_corpus.py or pointed to by
LIBRARY_DB_PATH, and OPENROUTER_API_KEY when the answering model or the embeddings come from
OpenRouter (not with LLM_BACKEND=ollama and local embeddings) — checked by the preflight, which runs
only when a run is actually about to start.
"""
import argparse
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .config import QUESTION_DEADLINE_S, SUPPORTED_LANGS
from .graph import build_graph
from .i18n import set_lang, status_word, t
from .preflight import check_environment
from .runner import run_question
from .sanitize import LINE_BREAK_RE, strip_control_chars

EXIT_WORDS = {"exit", "quit", "q", "вихід"}
SCRATCH_DIR = Path(os.environ.get("ASK_SCRATCH_DIR", ".scratch"))

# Session totals live in the interface: the metrics event is always about one question.
SESSION = {"questions": 0, "cost_usd": 0.0}
# Per-question memory of the CLI: the passages of this run by hit_id (from the act
# events), so --verbose can print each evidence item on the text it was checked
# against. The CLI answers one question at a time; _run resets it.
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
        say(t("ev_plan", mode=update["mode"],
              queries=[update["current_query"]] + update["queries"]))
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
        nxt = update.get("current_query")
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
    elif node_name == "synthesize":
        say(t("ev_answer_header", a=update["answer"]))
    elif node_name == "validate":
        say(t("ev_provenance", v=update["verification"]))
        items = (update.get("provenance") or {}).get("items") or []
        if RUN["verbose"] and items:
            say(t("ev_evidence_header", n=len(items)))
            shown: set[str] = set()
            for item in items:
                say(t("ev_evidence_item", status=status_word(item["status"]), book=item["book"],
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


def _run(graph, question: str, history: list[str], deadline_s: float | None = None) -> str:
    """One question with human-readable failure instead of a traceback
    (ASK_DEBUG=1 re-raises)."""
    RUN["passages"] = {}
    try:
        return run_question(graph, question, history, SCRATCH_DIR,
                            on_event=print_event, on_clarify=ask_in_terminal,
                            deadline_s=deadline_s)
    except Exception as error:
        if os.environ.get("ASK_DEBUG"):
            raise
        # The message can carry index text (a book named in a lookup failure).
        say(t("cli_run_error", e=f"{type(error).__name__}: {error}"), error=True)
        return ""


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
        raise SystemExit(1)
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
        # not a failed session.)
        if not _run(graph, question, history=[], deadline_s=args.deadline):
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

        answer = _run(graph, question, history, deadline_s=args.deadline)
        if not answer:
            continue
        # Conversation memory: the question plus a truncated answer.
        history.append(f"Q: {question}\nA: {answer[:500]}")

    say(t("cli_bye"))


if __name__ == "__main__":
    main()
