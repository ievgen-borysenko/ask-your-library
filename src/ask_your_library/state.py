"""Agent state shared by all graph nodes."""
import operator
from typing import Annotated, TypedDict


def is_loop_marker(query) -> bool:
    """The loop's own action markers in current_query (__chapter__|book|section,
    __book__|key|query, __clarify__) are never search queries. Only reflect
    writes them; a planner query, a queued query or a question that looks like
    one is not obeyed (plan, reflect and the coverage gate all filter with this)."""
    return isinstance(query, str) and query.strip().startswith("__")


class AgentState(TypedDict):
    question: str          # the user's original question
    history: list[str]     # prior chat turns: "Q: ... -> A: ..." (context for follow-ups)
    mode: str              # "identify" (find which book) or "answer" (answer from content)
    queries: list[str]     # queue of search queries from plan
    current_query: str     # the query being executed right now
    hits: list[dict]       # raw results of the last search (live for one step), each with hit_id
    # every hit of the run as observe saw it: {hit_id, step, book, section, corpus, text};
    # append-reduced, so act returns only its own step's passages
    hits_log: Annotated[list[dict], operator.add]
    evidence: list[dict]   # accumulated evidence distillates {hit_id, book, section, quote, why}
    steps_taken: int       # how many search steps have run so far
    empty_streak: int      # consecutive steps that yielded no evidence (CRAG gate)
    read_chapters: list[str]  # chapter reads attempted: "book|section|status", status = complete | partial | empty
    clarification: str     # the user's reply to a clarifying question
    clarify_candidates: list[str]  # book keys the clarify question offered, in the order shown
    clarify_unresolved: bool       # the reply matched no candidate: evidence kept for all, reported
    clarify_chosen: str            # the resolved candidate key; later evidence is filtered to it
    clarify_asked: bool    # a clarify interrupt already happened this run (one allowed)
    coverage_probed: bool  # the one forced query at an uncovered candidate book has run (ADR-013)
    plan_fallback: bool    # the planner returned no valid JSON twice; the raw question became the one query
    scratchpad_path: str   # file the raw hits are written to (kept out of the LLM context)
    answer: str            # the final answer
    verification: str      # quote-provenance report on quotes (text, for humans)
    provenance: dict       # the same report as numbers: checked/confirmed/broken/unused/broken_items
    stop_reason: str       # why the loop stopped (enough / CRAG gate / step limit / fallback)
