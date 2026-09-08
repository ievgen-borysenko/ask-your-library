"""The deterministic coverage gate (ADR-013): before the model stops or asks,
spend one more search, once per run, on the part of the question the evidence
has not covered. Code, not prompt: prompt-only variants were measured and had
no effect (04.09).
"""
import re

from .config import MAX_STEPS
from .library import TITLE_SEPARATOR, title_of
from .state import AgentState, is_loop_marker

def _uncovered_books(state: AgentState) -> list[tuple[str, int]]:
    """Books in the retrieval window the evidence never names, with their hit
    counts, most hits first (first appearance breaks ties)."""
    covered = {e["book"] for e in state.get("evidence", [])}
    counts: dict[str, int] = {}
    for h in state.get("hits_log", []):
        if h["book"] not in covered:
            counts[h["book"]] = counts.get(h["book"], 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])   # stable sort


def _named_in(question: str, book: str) -> bool:
    """Does the question name this book, by title or by the author's surname?"""
    q = question.lower()

    def whole(phrase: str) -> bool:
        # word boundaries on both ends: "It" must not match inside "with"
        return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", q) is not None

    if whole(title_of(book).lower()):
        return True
    author = book.rsplit(TITLE_SEPARATOR, 1)[1].strip().lower() if TITLE_SEPARATOR in book else ""
    return whole(author.split()[-1] if author else "")


def coverage_probe(state: AgentState, decision: str | None) -> str:
    """Deterministic coverage gate (ADR-013, code not prompt). Before the model
    stops ("enough") or asks ("clarify"), spend ONE more search, once per run:
      identify mode, evidence for at most one book: the next QUEUED planner
        query, i.e. another aspect of the question the planner already
        decomposed (measured 05.09: probing the most-hit uncovered book of the
        window picked a noise book in four of four firings, because the right
        second candidate was not in the window at all; a different query is
        what brought Gulliver in the v0.1.0 run);
      answer mode: a search inside a book the QUESTION NAMES (title or author
        surname) that the retrieval window holds but the evidence never touched,
        i.e. a comparison whose second side was skipped; the most-hit such book
        first. A book the question does not name is never probed, however many
        hits it has, and unrelated books in the evidence do not switch the gate
        off. Nothing when the question names no uncovered book.
    Never after a resolved clarify, never at the step limit. Returns the next
    current_query (a plain query or a "__book__|key|query" marker), or "".
    Limit: the window is the universe; a book no query ever retrieved cannot be
    probed (h17)."""
    if decision not in ("enough", "clarify") or state.get("coverage_probed"):
        return ""
    if state.get("clarify_chosen") or state.get("clarify_asked") or state["steps_taken"] >= MAX_STEPS:
        # after a clarify, resolved or not, the extra search is the user's
        # answer, not the gate's
        return ""
    if state.get("mode") == "identify":
        if len({e["book"] for e in state.get("evidence", [])}) > 1:
            return ""
        queued = [q for q in state.get("queries", []) if isinstance(q, str) and q.strip()
                  and not is_loop_marker(q)]
        return queued[0] if queued else ""
    for book, _count in _uncovered_books(state):
        if _named_in(state["question"], book):
            return f"__book__|{book}|{state['question']}"
    return ""

