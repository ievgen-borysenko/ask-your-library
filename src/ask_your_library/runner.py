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
             operation; "after_clarify" — a catalogue request after a clarify reply;
             "mixed_intent" — the question also asks about content, so the research loop
             ran, with the named book as the filter when it resolves)
  catalog    answer, catalog {op, count (= len(books)), total, books (index keys), query,
             resolved, suggestions}, stop_reason — the catalogue path: code over the index
             tables, no model call, no search step; validate then reports a catalogue answer
             (provenance carries `catalog` {op, count, total} next to the zero quote counts)
  act        steps_taken, hits (list[dict], each with hit_id), hits_log (THIS step's
             passages only; the graph state append-reduces them across steps)
  observe    evidence (accumulated), empty_streak; a distillation call that timed out sends
             call_timed_out=True and stop_reason instead, and the loop ends at reflect.
             The provenance gate (#29) adds dropped_unverified and repinned — run totals,
             each present ONLY on a step that dropped or re-pinned something, so a run
             where every quote checks out emits exactly the event it always did
  reflect    current_query ("" = synthesize; "__clarify__" + clarify_candidates; "__chapter__|book|section";
             "__book__|book|query" = coverage probe, one search inside one candidate) + coverage_probed
  clarify    clarification (the user's reply)
  synthesize answer
  validate   verification (human-readable) + provenance (numbers:
             checked/confirmed/unattributed/broken (a partition of checked) + unused
             (items for books the answer does not name, checked anyway)
             + dropped_unverified/repinned (what the observe gate spent before the
             answer was written: always present, 0 on a run that dropped nothing),
             + broken_items[{hit_id,book,section,quote}]
             + items[{hit_id,book,section,quote,status}]: every evidence item with its
             verdict, in evidence order; with the passages from the act events (hits_log,
             keyed by hit_id) an interface can open each quote on the text it was checked against)
  metrics    (once at the end — a question that FAILED included; once more with
             partial=True at a clarify interrupt, covering the run so far)
             llm_calls, input_tokens, output_tokens, cache_read_tokens, cost_usd,
             model, seconds, steps_taken, stop_reason,
             by_role ({node: calls/tokens/seconds/cost_usd}),
             hits_seen, evidence_distilled (retrieval selectivity),
             redacted_lines (injection telemetry from sanitize)
             Synthetic event emitted by the runner after the graph finishes, not a
             node. Always describes ONE question; session totals are the
             interface's job.

`run_question` returns a RunResult: what is true about the run once it is over
(the answer, the evidence and its provenance, the clarify and catalogue fields,
the usage snapshot, the wall clock, and the failure if there was one). No caller
reads the graph's state; the harness is a consumer of this runner like the CLI
and the web UI, not a second execution path (ADR-009, amended 16.09.2026).
"""
import os
import stat
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from langgraph.types import Command

from .i18n import t
from .llm import pause_deadline, reset_usage, usage_snapshot
from .paths import redact_paths


def initial_state(question: str, history: list[str], scratchpad: Path) -> dict:
    return {
        "question": question, "history": history,
        "mode": "", "queries": [], "current_query": "",
        "hits": [], "hits_log": [], "evidence": [], "steps_taken": 0,
        "empty_streak": 0, "dropped_unverified": 0, "repinned": 0,
        "clarification": "", "clarify_asked": False, "coverage_probed": False,
        "plan_fallback": False, "catalog_fallback": "",
        "clarify_candidates": [], "clarify_unresolved": False, "clarify_chosen": "",
        "read_chapters": [],
        "catalog_request": {}, "catalog": {}, "book_filter": "", "book_unresolved": "",
        "scratchpad_path": str(scratchpad),
        "call_timed_out": False,
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


def _state_of(graph, config) -> dict:
    """The graph's final state for this thread, and it may raise.

    On the path where the stream finished, this read IS the run: a state the
    checkpointer cannot produce means there is no answer to return, and
    swallowing it would hand the caller `ok=True` with an empty answer — a
    failure told as a successful question with nothing in it."""
    values = graph.get_state(config).values
    return values if isinstance(values, dict) else {}


def _state_or_empty(graph, config) -> dict:
    """The same read, guarded, for the two places where a failure is ALREADY in
    hand and the state is only what can still be salvaged for the record: the
    `except` below, and the partial metrics of a run paused at a clarify (a
    fake graph in tests has no state, and a run that died inside the first node
    may have left nothing checkpointed). It must never be the reason a failed
    run raises a second time."""
    try:
        return _state_of(graph, config)
    except Exception:
        return {}


def _steps_so_far(graph, config) -> int:
    try:
        return int(_state_or_empty(graph, config).get("steps_taken", 0))
    except Exception:
        return 0


@dataclass(frozen=True)
class RunFailure:
    """What ended the run instead of an answer: the exception's class name and
    its message with local paths redacted. `error` is the exception itself, for
    a caller that wants to re-raise it (the CLI under ASK_DEBUG); everything a
    report or a chat message should show is already in the two strings."""
    type: str
    message: str
    error: BaseException | None = None

    def __str__(self) -> str:
        return f"{self.type}: {self.message}"


@dataclass(frozen=True)
class RunResult:
    """One question, answered or failed — everything an interface reads about
    the run, instead of reaching into the graph's state.

    The events are still the live account of a run (ADR-009): this is what is
    true when it is over. The two say the same things about the same run; the
    result exists so that a caller does not have to reconstruct the end state
    by accumulating events, and so that a caller which never subscribed to the
    events (a script, the eval harness's scoring) has one.

    Frozen: a consumer may not edit a run's record. The collections inside are
    the graph's own objects, not copies — read them, do not mutate them.

    Every field but the question has the value a run that produced nothing
    would carry, so a failure before the graph ever ran is still a result."""
    question: str
    answer: str = ""
    verification: str = ""
    provenance: dict = field(default_factory=dict)
    stop_reason: str = ""
    steps_taken: int = 0
    evidence: list = field(default_factory=list)
    read_chapters: list = field(default_factory=list)
    # what the provenance gate spent on this question (#29): quotes dropped
    # because no retrieved passage of their step held them, and quotes re-pinned
    # to the passage that did. They are also inside `provenance`; they are
    # fields of their own because they are facts about the RUN, and a question
    # that ends with no evidence at all still has them to report.
    dropped_unverified: int = 0
    repinned: int = 0
    # the clarify interrupt: whether it happened at all (the runner knows, the
    # state does not say it after a resume), what was offered and what code
    # resolved the reply to
    clarify_asked: bool = False
    clarify_candidates: list = field(default_factory=list)
    clarify_unresolved: bool = False
    clarify_chosen: str = ""
    plan_fallback: bool = False
    # the catalogue path (ADR-016) and the book filter, as the state left them
    catalog: dict = field(default_factory=dict)
    catalog_fallback: str = ""
    book_filter: str = ""
    book_unresolved: str = ""
    # usage_snapshot() taken at the same instant as the metrics event, wall
    # clock of the whole run (the clarify pause included), and the scratchpad
    # this run wrote its passages to
    usage: dict = field(default_factory=dict)
    seconds: float = 0.0
    scratchpad: Path | None = None
    failure: RunFailure | None = None
    # The consumer's own failure while being handed the metrics event, kept
    # apart from the run's: the question may have answered perfectly and the
    # renderer of its account still have raised. `ok` is about the run.
    metrics_failure: RunFailure | None = None

    @property
    def ok(self) -> bool:
        return self.failure is None

    @property
    def metrics_delivered(self) -> bool:
        return self.metrics_failure is None


def _failure(error: BaseException) -> RunFailure:
    """One place that turns an exception into the record of it: the class name,
    and the message with this machine's paths taken out of it."""
    return RunFailure(type=type(error).__name__, message=redact_paths(f"{error}"), error=error)


def failed_result(question: str, error: Exception) -> RunResult:
    """A result for a question that never reached the graph — the scratchpad
    could not be created, say. The run inside the graph reports its own failure
    on the result it returns; this is for the caller that has no result at all
    and still has to tell a reader what happened."""
    return RunResult(question=question, failure=_failure(error))


def _result(question: str, state: dict, usage: dict, seconds: float,
            scratchpad: Path, clarify_asked: bool, failure: RunFailure | None,
            metrics_failure: RunFailure | None = None) -> RunResult:
    """The graph's final state, read once, here — the one place that knows
    which state fields an interface is allowed to depend on."""
    return RunResult(
        question=question,
        answer=state.get("answer", ""),
        verification=state.get("verification", ""),
        provenance=state.get("provenance") or {},
        stop_reason=state.get("stop_reason", "") or "",
        steps_taken=state.get("steps_taken", 0),
        evidence=state.get("evidence") or [],
        read_chapters=state.get("read_chapters") or [],
        dropped_unverified=int(state.get("dropped_unverified") or 0),
        repinned=int(state.get("repinned") or 0),
        clarify_asked=clarify_asked,
        clarify_candidates=state.get("clarify_candidates") or [],
        clarify_unresolved=bool(state.get("clarify_unresolved")),
        clarify_chosen=state.get("clarify_chosen") or "",
        plan_fallback=bool(state.get("plan_fallback")),
        catalog=state.get("catalog") or {},
        catalog_fallback=state.get("catalog_fallback") or "",
        book_filter=state.get("book_filter") or "",
        book_unresolved=state.get("book_unresolved") or "",
        usage=usage, seconds=seconds, scratchpad=scratchpad, failure=failure,
        metrics_failure=metrics_failure)


def run_question(graph, question: str, history: list[str], scratch_dir: Path,
                 on_event: Callable[[str, dict], None],
                 on_clarify: Callable[[str], str],
                 deadline_s: float | None = None,
                 scratchpad_name: str | None = None) -> RunResult:
    """One full pass of the graph for one question. Returns a RunResult.

    A failure inside the graph is part of the result (`failure`), not an
    exception: the run still spent model calls and the metrics event still has
    to report them, and every interface has to say something about a question
    that did not finish. Only a BaseException (Ctrl-C) leaves through here, and
    even then the metrics event is emitted first — and a consumer that raises
    while being handed that event is recorded on the result too
    (`metrics_failure`), never propagated and never mistaken for the run's own
    outcome.

    `deadline_s` overrides QUESTION_DEADLINE_S for this run (0 = none); the
    loop stops searching once it is spent and answers from what it found.
    `scratchpad_name` names the scratchpad inside `scratch_dir` instead of the
    generated one — for a caller that keeps one file per question id and
    re-runs it (the eval harness); it is then truncated, not refused."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    # Timestamp for humans browsing the dir, uuid so concurrent runs never share
    # a file (validate would otherwise confirm quotes against another run's text).
    scratchpad = scratch_dir / (scratchpad_name
                                or f"run-{int(time.time())}-{uuid.uuid4().hex[:8]}.md")
    # 0600 from the first byte rather than touch() + chmod: the file holds the
    # retrieved passages as the model saw them, and the umask would otherwise
    # make it world-readable for the length of the run. O_EXCL turns the
    # (already unlikely) name collision into an error instead of an append to
    # another run's evidence; a caller that chose the name means to reuse it,
    # so that one is truncated instead.
    reuse = os.O_TRUNC if scratchpad_name else os.O_EXCL
    os.close(os.open(scratchpad, os.O_WRONLY | os.O_CREAT | reuse,
                     stat.S_IRUSR | stat.S_IWUSR))

    reset_usage(deadline_s)     # metrics and the deadline clock are per question
    started = time.monotonic()

    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    run_input = initial_state(question, history, scratchpad)
    final_state: dict = {}
    clarify_asked = False
    failure: RunFailure | None = None
    try:
        try:
            while True:
                interrupted = False
                for step in graph.stream(run_input, config):
                    if "__interrupt__" in step:
                        # The run pauses for the reader: report what it has cost so
                        # far (partial), the final metrics event covers the whole run.
                        clarify_asked = True
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
            # Not guarded: on this path the state is the run's product.
            final_state = _state_of(graph, config)
        except Exception as error:
            # The question is over, but what it spent is not lost: the state as
            # far as it got is still read, and the metrics event below is
            # emitted for this run exactly as for one that answered.
            failure = _failure(error)
            final_state = _state_or_empty(graph, config)
        finally:
            # Every question gets a fresh thread; without cleanup (also on failure)
            # a long-lived web process accumulates checkpoints forever.
            checkpointer = getattr(graph, "checkpointer", None)
            if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
                checkpointer.delete_thread(config["configurable"]["thread_id"])
    finally:
        # In a `finally`, so that a question which failed is measured like any
        # other — and a Ctrl-C still leaves the account of what was spent.
        seconds = round(time.monotonic() - started, 1)
        usage = usage_snapshot()
        try:
            on_event("metrics", {**usage, "seconds": seconds,
                                 "steps_taken": final_state.get("steps_taken", 0),
                                 "stop_reason": final_state.get("stop_reason", "")})
            metrics_failure = None
        except Exception as error:
            # Delivering the account is the consumer's business and its failure
            # is its own: a renderer that raises here (the web UI runs Chainlit
            # inside this callback) must not replace the run's outcome — nor
            # turn an answered question into an exception, which is exactly what
            # an unguarded emission in a `finally` does. It is recorded on the
            # result instead, beside whatever really happened to the run.
            metrics_failure = _failure(error)
    return _result(question, final_state, usage, seconds, scratchpad, clarify_asked,
                   failure, metrics_failure)
