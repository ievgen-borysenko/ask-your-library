"""Run loop: the single entry point shared by every interface (CLI, web, eval).

An interface plugs in with two callbacks:
  on_event(node_name, update)  called after every graph node
                               (CLI prints a line, web renders a step)
  on_clarify(question) -> str  the agent asks the user a question
                               (CLI: input(), web: dialog message)

Event contract (node_name -> keys present in update):
  plan       mode, current_query, queries, clarify_unresolved (after a clarify reply),
             plan_fallback (present, True, only when the planner returned no valid JSON
             twice and the raw question became the one query);
             mode "catalog": catalog_request {op, title, author} and no query (ADR-016);
             book_filter (a book the question names, resolved against the catalogue:
             retrieval is limited to it) or book_unresolved (the name matched nothing:
             the whole library is searched and the answer says so); catalog_fallback (present
             only when it happened: "invalid_op" — the planner said catalog without a usable
             operation; "after_clarify" — a catalogue request after a clarify reply; the
             research loop ran instead)
  catalog    answer, catalog {op, count (= len(books)), total, books (index keys), query,
             resolved, suggestions}, stop_reason — the catalogue path: code over the index
             tables, no model call, no search step; validate then reports a catalogue answer
             (provenance carries `catalog` {op, count, total} next to the zero quote counts)
  act        steps_taken, hits (list[dict], each with hit_id), hits_log (THIS step's
             passages only; the graph state append-reduces them across steps)
  observe    evidence (accumulated), empty_streak
  reflect    current_query ("" = synthesize; "__clarify__" + clarify_candidates; "__chapter__|book|section";
             "__book__|book|query" = coverage probe, one search inside one candidate) + coverage_probed
  clarify    clarification (the user's reply)
  synthesize answer
  validate   verification (human-readable) + provenance (numbers:
             checked/confirmed/unattributed/broken (a partition of checked) + unused
             (items for books the answer does not name, checked anyway),
             + broken_items[{hit_id,book,section,quote}]
             + items[{hit_id,book,section,quote,status}]: every evidence item with its
             verdict, in evidence order; with the passages from the act events (hits_log,
             keyed by hit_id) an interface can open each quote on the text it was checked against)
  metrics    (once at the end; once more with partial=True at a clarify interrupt,
             covering the run so far) llm_calls, input_tokens, output_tokens, cache_read_tokens, cost_usd,
             model, seconds, steps_taken, stop_reason,
             by_role ({node: calls/tokens/cost_usd}),
             hits_seen, evidence_distilled (retrieval selectivity),
             redacted_lines (injection telemetry from sanitize)
             Synthetic event emitted by the runner after the graph finishes, not a
             node. Always describes ONE question; session totals are the
             interface's job.
"""
import time
import uuid
from pathlib import Path
from typing import Callable

from langgraph.types import Command

from .i18n import t
from .llm import pause_deadline, reset_usage, usage_snapshot


def initial_state(question: str, history: list[str], scratchpad: Path) -> dict:
    return {
        "question": question, "history": history,
        "mode": "", "queries": [], "current_query": "",
        "hits": [], "hits_log": [], "evidence": [], "steps_taken": 0,
        "empty_streak": 0, "clarification": "", "clarify_asked": False, "coverage_probed": False,
        "plan_fallback": False, "catalog_fallback": "",
        "clarify_candidates": [], "clarify_unresolved": False, "clarify_chosen": "",
        "read_chapters": [],
        "catalog_request": {}, "catalog": {}, "book_filter": "", "book_unresolved": "",
        "scratchpad_path": str(scratchpad),
        "answer": "", "verification": "", "provenance": {}, "stop_reason": "",
    }


def history_entry(question: str, answer: str, catalog: dict | None = None) -> str:
    """One turn of conversation memory, as the interfaces hand it to the next
    plan and synthesize call (`history`). A catalogue answer IS the book list:
    only its shape is kept (the operation, the counts, the name the user asked
    about), never the titles, so the list does not reach the model on a later
    turn (ADR-016). Every other answer is kept truncated, as before."""
    if catalog:
        shape = t("history_catalog", op=catalog.get("op", "?"), n=catalog.get("count", 0),
                  total=catalog.get("total", 0), q=catalog.get("query") or "-",
                  found=t("history_yes") if catalog.get("resolved") else t("history_no"))
        return f"Q: {question}\nA: {shape}"
    return f"Q: {question}\nA: {answer[:500]}"


def _steps_so_far(graph, config) -> int:
    try:
        return int(graph.get_state(config).values.get("steps_taken", 0))
    except Exception:  # a fake graph in tests has no state
        return 0


def run_question(graph, question: str, history: list[str], scratch_dir: Path,
                 on_event: Callable[[str, dict], None],
                 on_clarify: Callable[[str], str],
                 deadline_s: float | None = None) -> str:
    """One full pass of the graph for one question. Returns the answer.
    `deadline_s` overrides QUESTION_DEADLINE_S for this run (0 = none); the
    loop stops searching once it is spent and answers from what it found."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    # Timestamp for humans browsing the dir, uuid so concurrent runs never share
    # a file (validate would otherwise confirm quotes against another run's text).
    scratchpad = scratch_dir / f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}.md"
    scratchpad.touch()

    reset_usage(deadline_s)     # metrics and the deadline clock are per question
    started = time.monotonic()

    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    run_input = initial_state(question, history, scratchpad)
    try:
        while True:
            interrupted = False
            for step in graph.stream(run_input, config):
                if "__interrupt__" in step:
                    # The run pauses for the reader: report what it has cost so
                    # far (partial), the final metrics event covers the whole run.
                    on_event("metrics", {**usage_snapshot(), "partial": True,
                                         "seconds": round(time.monotonic() - started, 1),
                                         "steps_taken": _steps_so_far(graph, config),
                                         "stop_reason": ""})
                    pause_started = time.monotonic()
                    user_reply = on_clarify(step["__interrupt__"][0].value)
                    # The reader's thinking time is not the agent's: `seconds` in
                    # the metrics keeps counting it, the deadline does not.
                    pause_deadline(time.monotonic() - pause_started)
                    run_input = Command(resume=user_reply)
                    interrupted = True
                    break
                for node_name, update in step.items():
                    on_event(node_name, update)
            if not interrupted:
                break
        final_state = graph.get_state(config).values
    finally:
        # Every question gets a fresh thread; without cleanup (also on failure)
        # a long-lived web process accumulates checkpoints forever.
        checkpointer = getattr(graph, "checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(config["configurable"]["thread_id"])
    on_event("metrics", {**usage_snapshot(),
                         "seconds": round(time.monotonic() - started, 1),
                         "steps_taken": final_state.get("steps_taken", 0),
                         "stop_reason": final_state.get("stop_reason", "")})
    return final_state.get("answer", "")
