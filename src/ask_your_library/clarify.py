"""The clarify resolver (ADR-006): deterministic code that turns the reader's
free-text reply to a clarify question into exactly one candidate book key, or
None (fail-open, never guess), plus the helpers that decide which books the
question offers and which evidence survives the reader's choice.
"""
import re

from .library import title_of
from .state import AgentState

# Ordinal words are matched as whole words; Ukrainian stems take a suffix
# ("перший", "другу", "третьої"), English ones do not ("secondhand" is not 2).
# Ukrainian ordinals as an explicit case list: a stem would also match the
# noun "друг" (friend) or "першість".
ORDINALS = [(0, r"1|first|перш(?:ий|а|е|у|ої|ого|им|ою|ому|ій|их|ими|і)"), (1, r"2|second|друг(?:ий|а|е|у|ої|ого|им|ою|ому|ій|их|ими|і)"),
            (2, r"3|third|трет(?:ій|я|є|ю|ьої|ього|ім|ьою|ьому|іх|іми|і)"), (3, r"4|fourth|четверт(?:ий|а|е|у|ої|ого|им|ою|ому|ій|их|ими|і)"),
            (4, r"5|fifth|п[’']ят(?:ий|а|е|у|ої|ого|им|ою|ому|ій|их|ими|і)")]



NEGATION_RE = re.compile(r"(?<!\w)(?:not|no|never|don'?t|do not|didn'?t|isn'?t|wasn'?t|не|ні|нема)"
                         r"(?!\w)[^.,;!?]{0,24}$")


def _mentions(text: str, phrase: str) -> bool:
    """Whole-word mention of `phrase` in `text` that is not inside a negated
    clause ("not Emma", "I don't mean Emma", "не Емма", "not the first"): a
    title that is a common word ("It", "Emma") must not fire from inside
    another word or a rejection. The negation window ends at punctuation."""
    for m in re.finditer(rf"(?<!\w){phrase}(?!\w)", text):
        before = text[max(0, m.start() - 40):m.start()]
        if not NEGATION_RE.search(before):
            return True
    return False


def _affirmed_titles(text: str, candidates: list[str]) -> list[str]:
    """Candidates whose key or title is mentioned without negation. When one
    matched title contains another ("It Ends with Us" and "It"), the longer
    one wins: the shorter is a substring hit, not a choice."""
    hits = [c for c in candidates
            if _mentions(text, re.escape(c.lower())) or _mentions(text, re.escape(title_of(c).lower()))]
    titles = {c: title_of(c).lower() for c in hits}
    return [c for c in hits if not any(o != c and titles[c] in titles[o] for o in hits)]


# Doubt: the reply is not a choice at all, even if it names a book ("maybe the
# second book", "perhaps Moby Dick"): checked before titles and ordinals.
DOUBT_RE = re.compile(r"(?<!\w)(?:maybe|perhaps|possibly|probably|unlikely|hardly|unsure|doubt\w*|not sure|"
                      r"forget it|never mind|можливо|мабуть|напевно|хіба|навряд(?: чи)?|сумнів\w*|не впевнен\w*|"
                      r"не знаю|забудь)(?!\w)")
# Rejection: the single offered book is not it; "not X, Y" corrections are
# handled by the negation window in _mentions, so plain negation words are
# not doubt.
REJECTION_RE = re.compile(r"(?<!\w)(?:not|no|nope|nah|none|neither|never|wrong|don'?t|do not|didn'?t|isn'?t|"
                          r"wasn'?t|different|other|another|else|instead|"
                          r"не|ні|нема|жодн\w*|інш\w*|помилк\w*|неправильн\w*)(?!\w)")
# Explicit yes at the start of the reply ("yes, and ...", "так, а що ...").
AFFIRMATION_RE = re.compile(r"^(?:yes|yeah|yep|yup|sure|correct|right|exactly|indeed|ok|okay|that one|this one|"
                            r"that'?s (?:it|the one|right)|the same|так|ага|саме так|точно|вірно|це вона|це та)(?!\w)")
# A follow-up that carries on with the book: a pronoun or "the book/author".
ANAPHORA_RE = re.compile(r"(?<!\w)(?:he|she|it|him|her|his|hers|its|they|them|their|"
                         r"(?:this|that|the) (?:book|novel|story|one|author)|"
                         r"він|вона|воно|вони|його|її|їх|ним|нею|ньому|ній|нього|неї|"
                         r"(?:ця|та|цієї|тієї|цю|ту|цей|той|цього|того|цім|тім|цій|тій) (?:книг\w*|книз\w*|книжк\w*|книжц\w*|історі\w*|повіст\w*|роман\w*)|"
                         r"автор(?:а|у|ом|ові|ка|ки|ці|ку|кою)?)(?!\w)")
# A meta question about the choice itself is not a follow-up about the book:
# a modal aimed at the selection ("could it be this one?", "might that be it?"),
# a complete assistant-control act ("can you repeat it?", "say that again"),
# or an explicit meta phrase ("it doesn't matter", "which one?"). A modal
# about the story ("what would he do?") and a polite request about the story
# ("can you tell me what he did next?") stay follow-ups.
META_RE = re.compile(r"(?<!\w)(?:(?:could|might|would|should|may|can|is|was) (?:it|that|this) (?:be )?(?:this|that|the) one|"
                     r"(?:could|might|would|should|may|can|is|was) (?:it|that|this) (?:be )?it|"
                     r"(?:(?:can|could|would|will) you )?(?:repeat|say) (?:it|that|this|again)|say (?:it|that) again|"
                     r"(?:it |that )?(?:doesn'?t|does not) matter|"
                     r"what (?:do you|does that|does it) mean|what time is it|which one|"
                     r"(?:можеш |можете )?повтор\w*|байдуже|неважливо|не має значення|що ти маєш на увазі|котр\w*)(?!\w)")
CLAUSE_SPLIT_RE = re.compile(r"[.,;:!?—–-]+|\s+(?:but|although|though|але|хоча|проте)\s+")


def _retracted(text: str, mention_end: int) -> bool:
    """A bare rejection clause AFTER the mention retracts it ("Moby Dick, no";
    "the second one, actually not"); a bare rejection BEFORE it is a correction
    that keeps the later mention ("no, the second one")."""
    tail = text[mention_end:]
    for clause in CLAUSE_SPLIT_RE.split(tail):
        clause = clause.strip()
        if clause and REJECTION_RE.search(clause) and not any(
                re.search(rf"(?<!\w)(?:{pattern})(?!\w)", clause) for _, pattern in ORDINALS):
            return True
    return False
# An ordinal is a choice only in a selection context: the whole reply is the
# ordinal phrase ("the second one", "друга", "2.") or the ordinal stands next
# to a selection word ("number 2", "варіант 1", "second book"); "what
# happened first?" and "його друг?" are not choices.
SELECTION_BEFORE = r"(?:the|number|option|no\.?|#|номер|варіант|книга|книжка)\s*$"
SELECTION_AFTER = r"^\s*(?:one|book|option|choice|варіант\w*|книг\w*|книз\w*)(?!\w)"
ORDINAL_ONLY_RE = re.compile(r"^\s*(?:(?:no|nope|yes|так|ні|не|ага)[,\s]+)?(?:the\s+|це\s+|то\s+)?(?:{})(?:\s+(?:one|book|варіант\w*|книг\w*|книз\w*))?\s*[.!]?\s*$".format(
    "|".join(pattern for _, pattern in ORDINALS)))


def _ordinal_hits(text: str) -> set[int]:
    whole = ORDINAL_ONLY_RE.match(text) is not None
    hits = set()
    for idx, pattern in ORDINALS:
        for m in re.finditer(rf"(?<!\w)(?:{pattern})(?!\w)", text):
            before, after = text[max(0, m.start() - 12):m.start()], text[m.end():m.end() + 12]
            if whole or re.search(SELECTION_BEFORE, before) or re.search(SELECTION_AFTER, after):
                if not NEGATION_RE.search(text[max(0, m.start() - 40):m.start()]):
                    hits.add(idx)
    return hits


def resolve_choice(reply: str, candidates: list[str]) -> str | None:
    """Map a free-text clarify reply to exactly one candidate book key, or None.
    Accepts the full key, the bare title as a whole-word mention (negated
    mentions ignored), or an ordinal (1..5, first..fifth, перший..п'ятий) when
    no title is named. With exactly ONE candidate offered ("is this the one?"),
    a reply that names no book and rejects nothing is taken as yes: a follow-up
    question about "him" or "it" is the reader carrying on with that book, not
    an unresolved reply (06.09 demo: "what has he said or done when he saw
    them first?" left the choice unresolved and the next search unfiltered).
    Only an explicit yes or a follow-up that refers to the book (a pronoun,
    "the book", "the author") counts; "hmm", "maybe", "which one do you mean?"
    and any reply with a rejection word ("no", "none", "a different one",
    "жодна") resolve to None. An ordinal is a choice only in a selection
    context ("the second one", "друга"), never as an adverb ("saw them first")
    or a noun ("його друг"). Ambiguous replies (several titles, several
    ordinals) resolve to None: fail-open, never guess."""
    text = (reply or "").strip().lower()
    if not text or not candidates:
        return None
    if DOUBT_RE.search(text):
        return None
    by_title = _affirmed_titles(text, candidates)
    if len(by_title) == 1:
        end = max((m.end() for m in re.finditer(re.escape(title_of(by_title[0]).lower()), text)), default=len(text))
        return None if _retracted(text, end) else by_title[0]
    if len(by_title) > 1:
        return None
    ordinal_hits = _ordinal_hits(text)
    if len(ordinal_hits) == 1:
        idx = ordinal_hits.pop()
        pattern = ORDINALS[idx][1]
        end = max((m.end() for m in re.finditer(rf"(?<!\w)(?:{pattern})(?!\w)", text)), default=len(text))
        if _retracted(text, end):
            return None
        return candidates[idx] if idx < len(candidates) else None
    if ordinal_hits:
        return None
    if len(candidates) == 1 and not REJECTION_RE.search(text):
        if AFFIRMATION_RE.search(text):
            return candidates[0]
        if ANAPHORA_RE.search(text) and not META_RE.search(text):
            # Heuristic, fail-open on doubt: a wrong acceptance costs one
            # search filtered to the offered book, and the answer still cites
            # what it found; a wrong "unresolved" costs the old, unfiltered turn.
            return candidates[0]
    return None


def _clarify_candidates(state: AgentState) -> list[str]:
    """Ordered unique book keys the clarify question is about: what reflect
    stored, else the books present in the evidence, then every other book
    retrieved during the run (hits_log, first appearance first). The second
    candidate is often only in the retrieval window, never distilled: c09 in
    the 05.09 pick run offered Moby Dick from the last step while Gulliver sat
    in the first step's window."""
    stored = state.get("clarify_candidates") or []
    if stored:
        return stored
    seen: list[str] = []
    for e in state.get("evidence", []):
        if e["book"] not in seen:
            seen.append(e["book"])
    for h in state.get("hits_log", []):
        if h["book"] not in seen:
            seen.append(h["book"])
    return seen


def _chosen_book(state: AgentState, unresolved: bool) -> str:
    """The resolved candidate key after a clarify reply, "" when none."""
    if unresolved or not state.get("clarification"):
        return state.get("clarify_chosen", "") or ""
    return resolve_choice(state["clarification"], _clarify_candidates(state)) or ""


def _evidence_after_clarify(state: AgentState) -> tuple[list[dict], bool]:
    """After clarify keep evidence ONLY for the chosen book: the identify phase
    may have collected distillates from candidates the user just ruled out,
    which would clutter synthesize and confuse the provenance report.
    Returns (evidence, unresolved). Fail-open: an unrecognised reply keeps
    everything and is reported as unresolved instead of guessing."""
    evidence = state.get("evidence", [])
    if not (state.get("clarification") and (evidence or state.get("clarify_candidates"))):
        return evidence, False
    chosen = resolve_choice(state["clarification"], _clarify_candidates(state))
    if chosen is None:
        return evidence, True
    # A candidate offered from the retrieval window may have no evidence yet:
    # the choice is still valid, the rejected books' evidence goes, and the
    # loop (or synthesize's honest refusal at the step limit) continues from
    # an empty slate rather than answering from what the user just ruled out.
    return [e for e in evidence if e["book"] == chosen], False


