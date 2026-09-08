"""Graph nodes: plan -> act -> observe -> reflect -> synthesize -> validate.

Each node is a plain function of the state that returns only the fields it
updates (LangGraph merges them into the state). The concerns the nodes lean on
live next door, one module each:

  llm.py         the model client (ChatOpenAI, usage accounting, data_block, ask_json)
  prompts.py     the rules of the four model-calling nodes
  clarify.py     the clarify resolver: reply -> exactly one candidate key, or None
  coverage.py    the deterministic coverage gate (one extra search before "enough")
  provenance.py  what counts as evidence, and the code-only quote check (`validate`)

Budgets (MAX_STEPS, MAX_EMPTY_STREAK, the per-hit windows) come from config.
"""
from langgraph.types import interrupt

from . import llm
from .catalog import content_clue, parse_catalog_request, render_catalog, resolve_title, run_catalog
from .clarify import _chosen_book, _clarify_candidates, _evidence_after_clarify
from .config import CHAPTER_HIT_CHARS, MAX_CLARIFY_CANDIDATES, MAX_EMPTY_STREAK, MAX_STEPS, SEARCH_HIT_CHARS
from .coverage import coverage_probe
from .i18n import t
from .library import TITLE_SEPARATOR, chapter_is_cut, list_books, read_chapter, search_both, title_of
from .llm import data_block
from .prompts import OBSERVE_RULES, PLAN_RULES, REFLECT_RULES, SYNTHESIZE_RULES
from .provenance import _valid_evidence, validate  # noqa: F401  (validate is wired by graph.py)
from .sanitize import sanitize_context
from .state import AgentState, is_loop_marker

# Per-hit text budget, shared by act (hits_log) and observe (prompt): the
# quote-provenance check compares quotes against the passage as observe saw it,
# so the two MUST stay equal or honest quotes from a hit's tail read as broken.
# SEARCH_HIT_CHARS: several hits per step. CHAPTER_HIT_CHARS: chapter drill-down,
# one hit gets the whole read_chapter budget, so the "[chapter continues ...]"
# marker at its end reaches the model. Both come from config (env-tunable).


def per_hit_limit(hit_count: int) -> int:
    return CHAPTER_HIT_CHARS if hit_count == 1 else SEARCH_HIT_CHARS

def _budget_spent(state: AgentState) -> bool:
    """No further search may run: the step budget is spent, or the time budget
    is (checked only once a clarify reply is in, i.e. when plan runs mid-loop;
    the first plan of a run is never past its deadline)."""
    return state.get("steps_taken", 0) >= MAX_STEPS or (
        _after_clarify(state) and llm.deadline_passed())


def _after_clarify(state: AgentState) -> bool:
    """Has this run resumed from a clarify? The fact of the resume is the flag,
    not the reply's length: an empty reply (the web UI's timeout) is a
    legitimate resume and must not bypass the deadline."""
    return bool(state.get("clarify_asked") or state.get("clarification"))


def _deadline_reason() -> str:
    return t("stop_deadline", s=int(llm.deadline_seconds()))


def plan(state: AgentState) -> dict:
    # Clarify can fire on the last allowed step; re-planning a search we may
    # not run would only cost an LLM call — filter the evidence and let
    # route_after_plan go straight to synthesize.
    if _after_clarify(state) and _budget_spent(state):
        evidence, unresolved = _evidence_after_clarify(state)
        chosen = _chosen_book(state, unresolved)
        out_of_steps = state.get("steps_taken", 0) >= MAX_STEPS
        return {"mode": "answer" if chosen else (state.get("mode") or "identify"), "queries": [],
                "current_query": "", "evidence": evidence, "clarify_unresolved": unresolved,
                "clarify_chosen": chosen,
                "steps_taken": state.get("steps_taken", 0), "empty_streak": 0,
                "stop_reason": t("stop_limit", n=MAX_STEPS) if out_of_steps else _deadline_reason()}

    # Resolve the clarify reply BEFORE planning: the planner is a stateless
    # call and never saw the numbered list, so "the second one" means nothing
    # to it; it gets the canonical key the resolver chose, next to the raw reply.
    evidence, unresolved = _evidence_after_clarify(state)
    chosen = _chosen_book(state, unresolved)

    data = [data_block("question", state["question"])]
    if state.get("history"):
        data.insert(0, data_block("conversation", "\n".join(state["history"][-3:])))
    if state.get("clarification"):
        data.append(data_block("clarification", state["clarification"]))
        if chosen:
            data.append(data_block("user_chose_book", chosen))
        elif unresolved:
            data.append(data_block("clarification_note",
                                   "the reply matched none of the offered candidates"))

    try:
        decision = llm.ask_json(PLAN_RULES, "\n".join(data), role="plan")
    except ValueError:
        # No JSON twice (small local models do this): the run goes on with the
        # raw question as its one query, like reflect and observe degrade, and
        # the event says so. A planner failure must not end the question.
        decision = {}

    mode = llm.str_field(decision, "mode", ("identify", "answer", "catalog")) or "answer"
    common = {"evidence": evidence, "clarify_unresolved": unresolved, "clarify_chosen": chosen,
              "steps_taken": state.get("steps_taken", 0), "empty_streak": 0}
    catalog_request = parse_catalog_request(decision) if mode == "catalog" else None
    mixed = bool(catalog_request) and content_clue(state["question"]) != ""
    if catalog_request and not mixed and not _after_clarify(state):
        # The catalogue path (ADR-016): the planner named an operation of ours
        # and code runs it; no query, no search step. Never after a clarify:
        # the reader's reply settled a book of the research loop, not a listing.
        return {"mode": "catalog", "catalog_request": catalog_request, "queries": [],
                "current_query": "", **common}
    # "catalog" without a usable operation, after a clarify reply, or on a
    # question that also asks about content (a content word the gate in
    # catalog.py knows), is the research loop with the planner's queries or the
    # raw question, and the event says which. The gate is a vocabulary check,
    # not an understanding: a title hidden inside a question is beyond it, so
    # that routing stays the planner's reading, measured by the eval set's
    # controls rather than enforced here.
    catalog_fallback = ""
    if mode == "catalog":
        catalog_fallback = ("after_clarify" if catalog_request and _after_clarify(state)
                            else "mixed_intent" if mixed else "invalid_op")
        mode = "answer"

    # Valid JSON is not necessarily our schema; degrade instead of raising —
    # the raw question is always a usable search query. A query that looks like
    # one of the loop's own markers is not a query: only reflect may decide a
    # chapter read, a probe or a clarify. The same rule guards the fallback: a
    # question that itself starts with "__" loses its underscores before it
    # becomes a query, so no user text can drive act as a marker either.
    # The container first, then the items: 42, true or "one string" are valid
    # JSON and no list of queries (a string would search its own letters).
    raw_queries = decision.get("queries")
    queries = [q for q in (raw_queries if isinstance(raw_queries, list) else [])
               if isinstance(q, str) and q.strip() and not is_loop_marker(q)]
    fallback = not queries      # no JSON, no queries, or nothing usable: the planner gave no plan
    if fallback:
        queries = [state["question"].lstrip("_ ") or state["question"]]
    if chosen:
        # The book is settled by the reader's choice; from here on the loop
        # answers from it. Code decides this, not the planner (06.09 demo: the
        # planner kept "identify" and searched every book again).
        mode = "answer"

    # The hybrid of ADR-016: a content question that names ONE book is answered
    # from that book. The planner only repeats the name; code resolves it
    # against the catalogue (the same resolver as "do I have X"), and retrieval
    # is limited to the resolved key (act, like the filter after a clarify).
    # No match: the whole library is searched and the answer says so. Several
    # matches ("Holmes"): no filter, the loop's own clarify may sort it out.
    # Strict resolution: a fragment of a title ("Time" for The Time Machine)
    # sets no filter either — a silent wrong filter would hide a whole library.
    book_filter = book_unresolved = ""
    named = llm.str_field(decision, "book") or (catalog_request["title"] if mixed and catalog_request else "")
    if named and mode == "answer" and not chosen:
        matches, _ = resolve_title(named, list_books(), strict=True)
        if len(matches) == 1:
            book_filter = matches[0].key
        elif not matches:
            book_unresolved = named

    update = {
        "mode": mode,
        "queries": queries[1:],
        "current_query": queries[0],
        "book_filter": book_filter, "book_unresolved": book_unresolved,
        **common,
    }
    if fallback and catalog_fallback != "mixed_intent":
        # present only when it happened: the interfaces and the eval show it (a
        # mixed intent searches the raw question by design, not for want of a plan)
        update["plan_fallback"] = True
    if catalog_fallback:
        update["catalog_fallback"] = catalog_fallback
    return update


def catalog(state: AgentState) -> dict:
    """The catalogue path (ADR-016): the operation the planner named, run by
    code over library.list_books(); the number in the answer is len() of the
    list under it. No model call and no search step, so steps_taken stays
    where it is (0 on a fresh run) and the stop reason names the path;
    validate reports a catalogue answer instead of a quote check."""
    result = run_catalog(state["catalog_request"], list_books())
    return {"answer": render_catalog(result), "catalog": result.as_state(),
            "queries": [], "current_query": "", "stop_reason": t("stop_catalog")}


READ_STATUSES = ("complete", "partial", "empty", "ambiguous")


def read_key(entry: str) -> str:
    """'book|section' of a read_chapters entry, whether or not it carries a
    trailing '|status'. Section names may themselves contain '|', so the status
    is recognised from the right and only when it is a known value."""
    head, _, last = entry.rpartition("|")
    return head if last in READ_STATUSES else entry


def read_status(entry: str) -> str:
    """Status of a read_chapters entry; legacy two-part entries count as complete."""
    last = entry.rpartition("|")[2]
    return last if last in READ_STATUSES else "complete"


def same_chapter(wanted: str, entry: str) -> bool:
    """Does a read_chapter request name a chapter already in read_chapters?
    "Some Book|Chapter 59" and "Some Book|59" are the same chapter; so are
    "Don Quixote|..." and "Don Quixote — Miguel de Cervantes|..." (act records
    the canonical key, reflect may ask with the bare title), but two different
    full keys never are ("Emma — Jane Austen" is not "Emma — Other Author").
    After an ambiguous read only the identical bare request is a repeat: the
    full key is exactly what the model is told to try next. The trailing
    "|status" of an entry is not part of the key, but a "|" inside a section
    name is."""
    def split(value: str) -> tuple[str, str]:
        book, _, section = read_key(value).partition("|")
        return book.strip().lower(), section.lower().replace("chapter ", "").strip()

    w_book, w_section = split(wanted)
    e_book, e_section = split(entry)
    if w_section != e_section:
        return False
    if w_book == e_book:
        return True
    if read_status(entry) == "ambiguous":
        return False
    w_full, e_full = TITLE_SEPARATOR in w_book, TITLE_SEPARATOR in e_book
    if w_full and e_full:
        return False
    return title_of(w_book) == title_of(e_book)


# ---------------------------------------------------------------- act
def act(state: AgentState) -> dict:
    # Two kinds of action: a regular search, or reading a whole chapter (drill-down)
    marker_parts = state["current_query"].split("|", 2) if is_loop_marker(state["current_query"]) else []
    if marker_parts and len(marker_parts) != 3:
        # A malformed marker (fewer than three parts) is nothing to act on: no
        # hits, a note in the scratchpad, and the loop's CRAG gate counts the
        # dry step. Only reflect writes markers, so this is a guard, not a path.
        hits = []
        empty_read_note = f"[malformed action marker ignored: {state['current_query']}]\n"
        read_chapters = state.get("read_chapters", [])
    elif state["current_query"].startswith("__chapter__|"):
        _, asked_book, section = marker_parts
        chapter_text, found_book, resolution = read_chapter(asked_book, section, max_chars=CHAPTER_HIT_CHARS)
        # The hit carries the index key of the book actually read, not the
        # string reflect asked with: a bare title ("Don Quixote") would otherwise
        # produce evidence that the exact-key filter after a clarify ("Don
        # Quixote — Miguel de Cervantes") silently drops.
        book = found_book or asked_book
        # An empty read produces NO hit: a note inside a hit could be quoted as
        # evidence and pass provenance. It is logged in the scratchpad outside any
        # <<<hit>>> block, and the chapter still lands in read_chapters so reflect
        # does not loop on a lookup that cannot succeed (it stops with
        # stop_chapter_again on the second request).
        hits = ([{"corpus": "transcripts", "book": book, "section": section,
                  "text": chapter_text, "score": 1.0}] if chapter_text else [])
        empty_read_note = ("" if chapter_text
                           else f"[title '{asked_book}' belongs to more than one book: {section} not read, "
                                f"ask with the full 'Title — Author' key]\n" if resolution == "ambiguous"
                           else f"[no text in the index for {asked_book} | {section}]\n")
        # Honest read status: "this chapter was attempted", "this chapter was
        # read completely" and "that title is two books" are different facts,
        # and reflect sees the difference.
        status = ("ambiguous" if resolution == "ambiguous"
                  else "empty" if not chapter_text
                  else "partial" if chapter_is_cut(chapter_text) else "complete")
        read_chapters = state.get("read_chapters", []) + [f"{book}|{section}|{status}"]
    elif state["current_query"].startswith("__book__|"):
        # Coverage probe (ADR-013): one search inside a single candidate book.
        _, probe_book, probe_query = marker_parts
        hits = search_both(probe_query, k=4, book=probe_book)
        empty_read_note = ""
        read_chapters = state.get("read_chapters", [])
    else:
        # After a resolved clarify, retrieval itself is limited to the chosen
        # book (ADR-013), not only the evidence that survives observe; a book
        # the question named and the catalogue resolved works the same way (ADR-016).
        hits = search_both(state["current_query"], k=4,
                           book=state.get("clarify_chosen") or state.get("book_filter") or None)
        empty_read_note = ""
        read_chapters = state.get("read_chapters", [])

    # Injection defense: sanitize hit text before the model ever sees it
    usage = llm._usage()
    usage.hits_seen += len(hits)
    for h in hits:
        clean_text, redacted = sanitize_context(h["text"])
        h["text"] = clean_text
        if redacted:
            h["redacted_lines"] = redacted
            usage.redacted_lines += redacted

    # Raw hits go to the scratchpad file, not into the orchestrator's context.
    # Stable ids: evidence points at the hit it was copied from, and validate
    # checks the quote against that hit's text as observe saw it (cut at limit).
    # The scratchpad is a human log only; no code parses it any more.
    step = state["steps_taken"] + 1
    limit = per_hit_limit(len(hits))
    for i, h in enumerate(hits, 1):
        h["hit_id"] = f"s{step}h{i}"
    # Only this step's passages are returned: hits_log has an append reducer in
    # AgentState, so checkpoints and events stay linear in the number of steps.
    new_log = [{"hit_id": h["hit_id"], "step": step, "book": h["book"], "section": h["section"],
                "corpus": h["corpus"], "text": h["text"][:limit]} for h in hits]
    with open(state["scratchpad_path"], "a", encoding="utf-8") as f:
        f.write(f"\n## step {step}: {state['current_query']}\n{empty_read_note}")
        for h in hits:
            # score = RRF, distance only exists on hits from the vector list.
            f.write(f"<<<hit>>> {h['hit_id']} | {h['book']} | {h['section']} | {h['corpus']} | "
                    f"rrf {h.get('score', '?')} | dist {h.get('distance', '-')}\n")
            f.write(f"{h['text'][:limit]}\n")

    return {"hits": hits, "hits_log": new_log, "steps_taken": step,
            "read_chapters": read_chapters}


# ---------------------------------------------------------------- observe
def observe(state: AgentState) -> dict:
    limit = per_hit_limit(len(state["hits"]))
    results = "\n".join(
        data_block("result", h["text"][:limit], index=i, hit_id=h.get("hit_id", ""),
                   corpus=h["corpus"], book=h["book"], section=h["section"])
        for i, h in enumerate(state["hits"], 1))
    user = "\n".join([data_block("question", state["question"]),
                      data_block("search_query", state["current_query"]),
                      data_block("search_results", results, trusted=True),
                      # Restated next to the data on purpose: with the rules in
                      # the system message, aggregation questions tempted the
                      # model into writing comparison sentences as "quotes".
                      "Reminder: every quote must be a contiguous, character-exact "
                      "copy from ONE <result> above — never your own summary or "
                      "comparison — and must carry that result's hit_id. "
                      "Return ONLY the JSON described in the rules."])
    try:
        distilled = llm.ask_json(OBSERVE_RULES, user, role="observe")
    except ValueError:
        # Distillation failed: count the step as dry and let the loop decide
        distilled = {"evidence": []}

    new_evidence = _valid_evidence(distilled.get("evidence"), state["hits"])
    if state.get("clarify_chosen"):
        # After a resolved clarify, evidence about the rejected candidates
        # must not creep back in through later searches.
        new_evidence = [e for e in new_evidence if e["book"] == state["clarify_chosen"]]
    llm._usage().evidence_distilled += len(new_evidence)
    # CRAG gate: count "dry" steps — steps that produced NO evidence at all
    if new_evidence:
        empty_streak = 0
    else:
        empty_streak = state["empty_streak"] + 1

    return {"evidence": state["evidence"] + new_evidence, "empty_streak": empty_streak}


# ---------------------------------------------------------------- reflect
def reflect(state: AgentState) -> dict:
    # CRAG gate: consecutive dry steps mean the library has nothing on this;
    # stop without another LLM call
    if state["empty_streak"] >= MAX_EMPTY_STREAK:
        return {"current_query": "", "queries": [],
                "stop_reason": t("stop_crag", n=MAX_EMPTY_STREAK)}
    # Time budget: checked here, before the next decision costs a call and a
    # search; the step that just ran counts, whatever it took.
    if llm.deadline_passed():
        return {"current_query": "", "queries": [], "stop_reason": _deadline_reason()}

    evidence_lines = "\n".join(f"- {e['book']} ({e['section']}): {e['why']}"
                               for e in state["evidence"]) or "(none)"
    queued = state["queries"]
    user = "\n".join([
        data_block("question", state["question"], mode=state["mode"]),
        f"Steps used: {state['steps_taken']} of {MAX_STEPS}.",
        data_block("evidence_so_far", evidence_lines),
        data_block("queued_queries", "\n".join(queued) or "(none)"),
        data_block("chapters_already_read", "\n".join(state.get("read_chapters") or []) or "(none)"),
    ])
    try:
        decision = llm.ask_json(REFLECT_RULES.format(clarify_lang=t("clarify_lang_instruction")),
                            user, role="reflect")
    except ValueError:
        # No usable decision: finish with the evidence collected so far
        return {"current_query": "", "stop_reason": t("stop_json")}

    probe = coverage_probe(state, decision.get("decision"))
    if probe:
        remaining = [q for q in state["queries"] if q != probe]
        return {"current_query": probe, "queries": remaining, "coverage_probed": True}

    if decision.get("decision") == "read_chapter" and not (
            isinstance(decision.get("book"), str) and isinstance(decision.get("section"), str)):
        # Schema-less read_chapter: nothing to read, treat as enough.
        decision = {"decision": "enough"}

    if decision.get("decision") == "read_chapter" and state["steps_taken"] < MAX_STEPS:
        wanted = f"{decision['book']}|{decision['section']}"

        if not any(same_chapter(wanted, entry) for entry in state.get("read_chapters", [])):
            return {"current_query": f"__chapter__|{wanted}"}
        # Model is asking for the same chapter again: no continuation cursor
        # exists yet, so a repeat cannot show more text — finish with what we have
        return {"current_query": "", "stop_reason": t("stop_chapter_again")}

    # One clarify per run, gated by the flag: an empty reply (web timeout)
    # must not re-open the clarify loop.
    if decision.get("decision") == "clarify" and not state.get("clarify_asked"):
        # The candidates are what the user picks from: books in the evidence,
        # topped up from the last hits when the evidence names fewer than two.
        candidates = _clarify_candidates(state)[:MAX_CLARIFY_CANDIDATES]
        question = decision.get("clarify_question") or t("clarify_default_q")
        if not isinstance(question, str):
            question = t("clarify_default_q")
        # Always listed, in this order: ordinals in the reply refer to it.
        listed = "\n".join(f"{i}) {c}" for i, c in enumerate(candidates, 1))
        question = f"{question}\n{t('clarify_candidates_list', items=listed)}"
        return {"current_query": "__clarify__", "queries": [question],
                "clarify_candidates": candidates}

    if decision.get("decision") != "search" or state["steps_taken"] >= MAX_STEPS:
        what = decision.get("decision")
        if state["steps_taken"] >= MAX_STEPS and what in ("search", "read_chapter"):
            reason = t("stop_limit", n=MAX_STEPS)
        elif what == "enough":
            reason = t("stop_enough")
        elif what == "clarify":
            reason = t("stop_clarify_repeat")
        else:
            reason = t("stop_other", what=what)
        return {"current_query": "", "stop_reason": reason}

    next_query = llm.str_field(decision, "next_query") or ""
    if not next_query or is_loop_marker(next_query):
        # Not a query (wrong type, empty, or a reserved marker): fall back to the queue
        next_query = queued[0] if queued else ""
    remaining = [q for q in queued if q != next_query]
    return {"current_query": next_query, "queries": remaining}


def route_after_plan(state: AgentState) -> str:
    """Conditional edge: plan found no query to run (its budget was spent after
    a clarify, or the step budget is) -> synthesize directly. Routes on what
    plan produced, not on a second reading of the clock: a deadline that lapses
    during plan's own call still gets its one more step, and reflect then
    stops it with the honest reason."""
    if state.get("mode") == "catalog" and state.get("catalog_request"):
        return "catalog"
    if not state.get("current_query") or state["steps_taken"] >= MAX_STEPS:
        return "synthesize"
    return "act"


def route_after_reflect(state: AgentState) -> str:
    """Conditional edge: clarify -> ask the user; a query left -> loop again; else synthesize."""
    if state["current_query"] == "__clarify__":
        return "clarify"
    if state["current_query"] and state["steps_taken"] < MAX_STEPS:
        return "act"
    return "synthesize"


# ---------------------------------------------------------------- clarify
def clarify(state: AgentState) -> dict:
    """Human-in-the-loop: the graph suspends on interrupt(); the user's reply
    is delivered back as its return value when the run is resumed."""
    question_to_user = state["queries"][0]
    user_reply = interrupt(question_to_user)
    return {"clarification": user_reply, "clarify_asked": True, "queries": []}


# ---------------------------------------------------------------- synthesize
def synthesize(state: AgentState) -> dict:
    # The question named a book the catalogue does not hold: the answer comes
    # from the whole library and must say so before anything else (ADR-016).
    note = t("book_not_in_catalog", q=state["book_unresolved"]) + "\n\n" if state.get("book_unresolved") else ""
    if not state["evidence"]:
        return {"answer": note + t("refusal_answer")}

    evidence_text = "\n".join(f"- {e['book']} — {e['section']}: \"{e['quote']}\""
                              for e in state["evidence"])
    data = [data_block("question", state["question"])]
    if state.get("clarification"):
        data.append(data_block("clarification", state["clarification"]))
    if state.get("history"):
        data.append(data_block("conversation", "\n".join(state["history"][-3:])))
    data.append(data_block("evidence", evidence_text))

    reply = llm.llm_invoke(SYNTHESIZE_RULES.format(lang=t("answer_lang_instruction")),
                       "\n".join(data), role="synthesize").content
    return {"answer": note + reply}

