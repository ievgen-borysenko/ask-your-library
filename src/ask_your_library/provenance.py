"""The provenance engine: what counts as evidence, and the code-only check
that every quote is a verbatim, contiguous run inside the retrieved passage it
is pinned to (ADR-004). No LLM anywhere in this module.

`_valid_evidence` is the entry gate (observe): malformed items are dropped,
every kept item is pinned to the hit it was copied from (book and section come
from the hit record, never from the model), and — since 2026-09-16 (#29) — the
quote itself is checked against that hit's text before the item becomes
evidence. `validate` is the exit gate (the last graph node): confirmed /
unattributed / card-only / broken partition every checked item, and nothing
that is not a retrieved passage can confirm a quote.

Both gates run ONE function, `classify_quote`, over one index of the run's
passages (`passage_index`). That is the point of the pair: the entry gate and
the report cannot drift apart into two different readings of the same quote, so
what `validate` reports is what the gate already decided, on the same text.

A book card is not the book. `act` records which corpus each passage came from,
and a quote that is verbatim only inside a card is verbatim in a MODEL's words —
one call per book at ingest time — not in the author's. It is reported as its
own outcome and never counted as traced to the book (design critique 16.09 §1.1;
ADR-002's recorded consequence, "interfaces still do not label evidence by
source type"). The three older counts keep exactly the meaning they had, now
over the book text alone.
"""
import os
import re
import unicodedata
from typing import NamedTuple

from .catalog import resolve_title
from .config import SEARCH_HIT_CHARS
from .i18n import t
from .bookkey import author_of, title_of
from .library import (CUT_MARKER_RE, HEAD_MARKER_RE, BookEntry, cut_marker,
                      head_marker)
from . import llm
from .sanitize import LINE_BREAK_RE, strip_control_chars
from .state import AgentState

MAX_QUOTE_CHARS = SEARCH_HIT_CHARS   # a quote cannot exceed the hit it was copied from

# The value `library.search` writes into a hit's "corpus" for the per-book
# summaries, as opposed to "transcripts", the book's own text. A hit whose
# corpus is missing or unknown is read as book text: that is what an index built
# before cards existed holds, and the conservative reading is the one that does
# not invent a card under a quote.
CARD_CORPUS = "cards"


# Strict: an evidence item must name the hit_id it was copied from, or it is
# dropped. Off: a missing/unknown hit_id is resolved by finding the current hit
# whose text contains the quote (still evidence-based, never the model's word).
# The release-pass abort rule flips this off if strict mode loses >20% evidence.
HIT_ID_STRICT = os.environ.get("AYL_STRICT_HIT_ID", "1") == "1"


# A quote that has to FIND its passage — because the one it cited does not hold
# it — must be at least this many normalized words long. Re-pinning is the one
# place the check can make a citation up rather than only accept or refuse one,
# and "the sea" or "he said" is inside almost every book: below this length a
# match is a coincidence, not a provenance. A quote that IS in the passage it
# cited is never measured against this — nothing is being invented there.
MIN_REPIN_TOKENS = 4

# Why a well-formed distillate did not become evidence. One number is the answer
# a reader wants — how many quotes this answer was refused — and these are the
# telemetry under it, because they call for different fixes: `no_hit` is a model
# that cites nothing usable, `cross_book` one that names the wrong work beside a
# real quote, `short` one that quotes three words, `not_found` one that writes
# sentences the passages do not contain. Every one of them counts in
# `dropped_unverified`; none of them is a fifth outcome beside it.
DROP_REASONS = ("no_hit", "cross_book", "short", "not_found")

# How much of a refused quote travels back to the model in the next `observe`
# prompt (#29). Enough for the model to recognize the sentence it wrote and find
# it again in the passage; short enough that six of them cost a line each rather
# than a page each, on a prompt that already carries the passages themselves.
DROPPED_QUOTE_CHARS = 120


class EvidenceGate(NamedTuple):
    """What `observe`'s gate made of one distillate: the evidence that survived
    it, and how it was spent — items re-pinned to another passage of their own
    book, and items dropped, counted by reason.

    `dropped` is the same refusals as the counters, said in words instead of in
    numbers: one entry per refused item, carrying the quote AS THE MODEL WROTE
    IT (cut at DROPPED_QUOTE_CHARS), the book it named and the rule that stopped
    it. The counters stay the record a report reads; this is what `observe`
    shows the model on the next step, so a run that keeps paraphrasing is told
    which sentences were refused instead of being refused again in silence
    (#29). It is additive: the counters are unchanged and still sum."""
    evidence: list[dict]
    repinned: int = 0
    dropped_no_hit: int = 0
    dropped_cross_book: int = 0
    dropped_short: int = 0
    dropped_not_found: int = 0
    dropped: tuple[dict, ...] = ()

    @property
    def dropped_unverified(self) -> int:
        """Every well-formed distillate this gate refused. The headline number:
        one quote that did not reach the answer is one quote that did not reach
        the answer, whichever rule stopped it."""
        return (self.dropped_no_hit + self.dropped_cross_book
                + self.dropped_short + self.dropped_not_found)

    @property
    def by_reason(self) -> dict:
        return {"no_hit": self.dropped_no_hit, "cross_book": self.dropped_cross_book,
                "short": self.dropped_short, "not_found": self.dropped_not_found}


def _valid_evidence(items, hits: list[dict] | None = None) -> EvidenceGate:
    """Keep only well-formed, PROVEN evidence items and pin each one to the hit
    its quote is actually in: book and section are taken from the hit record,
    never from the model. Malformed output is dropped, not crashed on.

    The outcomes for a well-formed item, all decided by `classify_quote` against
    this step's passages — the same function and the same normalization
    `validate` runs afterwards, so the gate and the report cannot drift:

      in the cited hit    kept as it stands: `confirmed` when that hit is the
                          book's own text, `card_only` when it is a book card —
                          still evidence, still pinned where the model put it,
                          and still never counted as traced to the book
                          (ADR-004, amended 16.09)
      in another hit      re-pinned to the hit that holds it (book, section and
                          hit_id come from that hit) and counted `repinned` —
                          BUT ONLY WITHIN THE CITED HIT'S BOOK, and only for a
                          quote of at least MIN_REPIN_TOKENS words
      anything else       DROPPED and counted, under the reason that stopped it:
                          `not_found` (in no passage of this step), `cross_book`
                          (its only holder is another work), `short` (too few
                          words to move without guessing) or `no_hit` (no usable
                          citation at all). Every one of them is inside
                          `dropped_unverified`. Before #29 such a quote reached
                          `synthesize` and was counted afterwards, by the report.

    Re-pinning across books is refused rather than done because the book on an
    evidence item is the book the ANSWER cites: moving a quote to a different
    work would swap one wrong citation for another and hand the reader a
    confident attribution to a book that was never asked about. Inside one book
    the correction is real — the same work, a better passage — which is the only
    case where re-pinning makes the citation truer than the model left it.

    With `AYL_STRICT_HIT_ID=0` an item may carry no usable hit id at all. It is
    then resolved by `_sole_holder`, which is the same rule seen from the other
    end: the model's own `book` field, resolved canonically by the catalogue's
    resolver, must name one retrieved book, and exactly one passage of that book
    must hold the quote. A name that matches nothing, a name that matches two
    books, and a quote two passages hold are all citations nobody can write down
    — they are dropped, not guessed at.

    `hits` is None only in legacy callers/tests; then the model's book/section
    are kept as given and there is nothing to check a quote against."""
    by_id = {h["hit_id"]: h for h in (hits or []) if h.get("hit_id")}
    index = passage_index(hits) if hits is not None else {}
    valid: list[dict] = []
    repinned = 0
    refused_counts = dict.fromkeys(DROP_REASONS, 0)
    refused_items: list[dict] = []

    def refuse(reason: str, cited_a_hit: bool, quote: str = "", book=None) -> None:
        """One place that records a refusal, so no path can drop a well-formed
        quote without it showing up in `dropped_unverified`. The usage counter
        keeps the meaning it has always had — an item with no resolvable hit id
        — and is now one reason among four rather than the only one recorded.

        The quote and the book are recorded as the MODEL wrote them, not as the
        gate would have corrected them: the item is being handed back to the
        model on the next step (#29), and a corrected citation would show it a
        sentence it never produced."""
        refused_counts[reason] += 1
        refused_items.append({"quote": quote[:DROPPED_QUOTE_CHARS],
                              "book": book.strip() if isinstance(book, str) else "",
                              "reason": reason})
        if not cited_a_hit:
            llm._usage().evidence_dropped_no_hit += 1

    if not isinstance(items, list):
        # "evidence": 42 or "evidence": "none" is valid JSON and malformed
        # output: dropped like a malformed item, never a TypeError mid-run.
        return EvidenceGate(valid)
    for e in items or []:
        if not isinstance(e, dict):
            continue
        book, quote = e.get("book"), e.get("quote")
        if not (isinstance(quote, str) and quote.strip()):
            continue
        quote = quote.strip()[:MAX_QUOTE_CHARS]
        hit_id = e.get("hit_id") if isinstance(e.get("hit_id"), str) else ""
        if hits is not None:
            cited = by_id.get(hit_id)
            if cited is None and HIT_ID_STRICT:
                refuse("no_hit", cited_a_hit=False, quote=quote, book=book)
                continue
            if cited is None:
                # Non-strict: the model named no usable hit, so there is no
                # citation to confirm or to correct — and the quote may not go
                # hunting through the whole window for one. It may land only
                # inside the book the model itself named, and only when that
                # book and that passage are both unambiguous.
                holder, why = _sole_holder(quote, book, index)
                if not holder:
                    refuse(why, cited_a_hit=False, quote=quote, book=book)
                    continue
            else:
                status, holder = classify_quote(quote, hit_id, index)
                # A quote that is not where it said it is has to be MOVED to the
                # passage that holds it, and the two refusals below say what may
                # not be moved: not into another book, and not on the strength of
                # three words. A refused move and a quote that is nowhere count
                # the same, because from the answer's side they are the same
                # event — a distillate that did not become evidence.
                if status == BROKEN:
                    refuse("not_found", cited_a_hit=True, quote=quote, book=book)
                    continue
                if holder != hit_id:
                    if quote_tokens(quote) < MIN_REPIN_TOKENS:
                        refuse("short", cited_a_hit=True, quote=quote, book=book)
                        continue
                    if index[holder]["book"] != cited["book"]:
                        refuse("cross_book", cited_a_hit=True, quote=quote, book=book)
                        continue
                    repinned += 1
            hit = by_id[holder]
            book, section, hit_id = hit["book"], hit["section"], hit["hit_id"]
        else:
            if not (isinstance(book, str) and book.strip()):
                continue
            book, section = book.strip(), str(e.get("section") or "").strip()
        valid.append({"hit_id": hit_id, "book": book, "section": section, "quote": quote,
                      "why": str(e.get("why") or "").strip()[:300]})
    return EvidenceGate(valid, repinned, **{f"dropped_{r}": n for r, n in refused_counts.items()},
                        dropped=tuple(refused_items))


# ---------------------------------------------------------------- validate
def _normalize(text: str) -> str:
    """For comparing quotes: compares the WORD SEQUENCE, not bytes — all
    punctuation becomes whitespace, case and line breaks collapse, Unicode is
    NFKC-composed (a decomposed "é" equals a composed one). When quoting, the
    model honestly "translates" typography (markdown **bold** in cards, curly
    quotes/apostrophes in books, "label — text" -> "label: text"), and a
    byte-level substring check used to flag such honest quotes as
    hallucinations. Punctuation that carries meaning inside numbers survives:
    a decimal or thousands separator between digits, a range dash between
    digits and a sign directly before a digit, so "-5" is not "5" and "1-2"
    is not "1.2". The underscore is punctuation here too, although `\\w` counts
    it as a letter: it is Project Gutenberg's italics markup, never a word. That
    is a separator everywhere, not only around italics, so "snake_case_name"
    reads as three words and "1_000" as two. A fabricated or paraphrased
    sentence still fails the word-by-word check regardless."""
    # Control and invisible formatting characters are never text: DROPPED, the
    # same class and the same way as where the passage becomes prompt text
    # (`act`, `llm.data_block`). Mapping them to a space instead would split a
    # word a zero-width space hides inside, so a quote the model copied
    # verbatim from the prompt ("the word") would not match the haystack the
    # check runs against ("the wo rd") and would read as broken. Dropping them
    # first also keeps them off the placeholders below. Tabs and line breaks are
    # real separators and survive the strip, so they become spaces here — every
    # form of break, not only LF: a passage split by a bare CR is two words.
    text = strip_control_chars(unicodedata.normalize("NFKC", text).lower())
    text = LINE_BREAK_RE.sub(" ", text).replace("\t", " ")
    # The underscore is punctuation, not a letter. `\w` — which the class below
    # is built from — keeps it, and Project Gutenberg writes italics as _go_, so
    # the markup used to survive as part of the token: a quote copied verbatim
    # out of such a passage ("I'll go to hell") did not match the passage it
    # came from ("I'll _go_ to hell") and was reported as broken. Both the quote
    # and the passage pass through here, so dropping it drops it on both sides.
    # Before the number rules below, so a signed number in italics ("_-5_") is
    # read the same way as a bare one. It is a separator everywhere, not only in
    # italics markup, so the loosening is wider than the bug: "snake_case_name"
    # is now three words and "1_000" is two, and a quote and its passage that
    # disagree only there ("snake_case" against "snake case") now match. Both
    # are strings a book prints rarely and an agreeing pair of them is not the
    # shape a hallucination takes, which is why the wider rule is acceptable.
    text = text.replace("_", " ")
    text = re.sub(r"(?<=\d)[.,](?=\d)", "\x00", text)
    text = re.sub(r"(?<=\d)[-–−](?=\d)", "\x01", text)
    text = re.sub(r"(?:(?<=\W)|^)[-–−](?=\d)", "\x02", text)   # sign after any non-word char: "(-5)"
    text = re.sub(r"[^\w\s\x00\x01\x02]", " ", text)
    text = text.replace("\x00", ".").replace("\x01", "-").replace("\x02", "-")
    return re.sub(r"\s+", " ", text).strip()


def _contains_tokens(haystack_norm: str, needle_norm: str) -> bool:
    """Whole-token containment on normalized text: "5 years old" is not inside
    "15 years old", and "5" is not inside "-5". Normalized text is single-space
    separated, so padding both sides with a space makes the check exact."""
    return f" {needle_norm} " in f" {haystack_norm} "


CHUNK_JOINER = "\n[...]\n"     # written by library.join_chapter between chunks
# CUT_MARKER_RE / HEAD_MARKER_RE are imported from `library`, beside the
# functions that write those markers: the strip here and the writing there have
# to agree, and two copies of one pattern agree only until somebody edits one.


def _without_markers(hit_text: str, keep_offsets: bool = False) -> str:
    """The hit's text with the chapter markers off it. They are service text
    this code wrote, never the book's, so no quote may be confirmed against
    them and no window may be centred on them.

    `keep_offsets` blanks the head marker instead of deleting it: `match_span`
    reports offsets INTO the string it was given, and deleting a prefix would
    move every one of them. Blanking leaves whitespace, which tokenizes to
    nothing — the same result, at the same coordinates."""
    body = CUT_MARKER_RE.sub("", hit_text)
    head = HEAD_MARKER_RE.match(body)
    if not head:
        return body
    return " " * head.end() + body[head.end():] if keep_offsets else body[head.end():]


def _segments(hit_text: str) -> list[str]:
    """Normalized text of one hit, split where the text is NOT contiguous in
    the source: at the chunk joiner of a chapter read. The chapter markers are
    service text, never evidence, and are removed before normalizing. A
    quote must fit inside ONE segment; "before [...] after" is two."""
    return [_normalize(part) for part in _without_markers(hit_text).split(CHUNK_JOINER)]


# The four outcomes of the quote check, named once. They are the statuses
# `validate` reports and the verdicts the `observe` gate acts on, and they must
# stay one vocabulary: the gate keeps the first three and drops the fourth.
CONFIRMED, UNATTRIBUTED, CARD_ONLY, BROKEN = "confirmed", "unattributed", "card_only", "broken"


def passage_index(hits) -> dict[str, dict]:
    """The haystack, built once per check: hit_id -> {segments, card}.

    `segments` is the hit's text normalized and split where it is not
    contiguous in the source; `card` says whether the passage is a book card (a
    per-book summary one model call wrote at ingest time) rather than the
    book's own text, because a match in a card means something a match in the
    book does not (ADR-004, amended 2026-09-16).

    A hit whose record carries no `corpus` counts as book text: that is what an
    index built before cards existed holds, and the conservative reading is the
    one that cannot invent a card under a quote. Both callers hand in records of
    the same shape — `observe` this step's `hits` (cut exactly as its prompt cut
    them), `validate` the run's `hits_log` (cut by `act`) — so the two read the
    same text."""
    index: dict[str, dict] = {}
    for h in hits or []:
        hit_id = h.get("hit_id")
        if not hit_id:
            continue
        index[hit_id] = {"segments": _segments(h.get("text", "")),
                         "card": h.get("corpus", "") == CARD_CORPUS,
                         "book": h.get("book", ""), "section": h.get("section", "")}
    return index


def _found_in(quote_norm: str, segments: list[str]) -> bool:
    return bool(quote_norm) and any(_contains_tokens(seg, quote_norm) for seg in segments)


def quote_tokens(quote: str) -> int:
    """How many words the check has to work with. A one- or two-word "quote"
    matches somewhere in almost any book, so the number is what tells a real
    re-pin from a coincidence (see `MIN_REPIN_TOKENS`)."""
    return len(_normalize(quote).split())


def _holder_among(quote_norm: str, index: dict[str, dict], card: bool,
                  book: str, section: str, skip: str) -> str:
    """The best passage of one kind (book text or card) that holds this quote,
    inside `book` if any does and anywhere otherwise.

    "Best" is not "first in the dict": a quote is re-pinned to what this returns,
    and the book on an evidence item is the book the ANSWER will cite. So a
    passage of the same book wins over any other, and within that book one from
    the same section wins over the rest; only then does retrieval order decide.
    Without this, a quote cited to one book and present in two was re-pinned to
    whichever hit the search happened to return first — across books, which is
    the one re-pin that makes a citation worse instead of better."""
    best = ""
    rank = 99
    for other, record in index.items():
        if other == skip or record["card"] != card:
            continue
        if not _found_in(quote_norm, record["segments"]):
            continue
        here = (0 if record["section"] == section else 1) if record["book"] == book else 2
        if here < rank:
            best, rank = other, here
            if rank == 0:
                break
    return best


def _book_entries(index: dict[str, dict]) -> list[BookEntry]:
    """The books this run retrieved, shaped as the catalogue's resolver reads
    them. Title and author are split off the index key by the same two helpers
    the catalogue uses, so "Dracula" means "Dracula — Bram Stoker" here exactly
    as it does when the reader asks whether the library holds it."""
    entries: dict[str, BookEntry] = {}
    for record in index.values():
        key = record["book"]
        if not key:
            continue
        seen = entries.get(key)
        entries[key] = BookEntry(key, title_of(key), author_of(key),
                                 has_cards=record["card"] or bool(seen and seen.has_cards),
                                 has_text=not record["card"] or bool(seen and seen.has_text))
    return list(entries.values())


def _sole_holder(quote: str, stated_book, index: dict[str, dict]) -> tuple[str, str]:
    """The one passage an item with NO usable hit id may be pinned to, or ("",
    reason) when there is no such passage.

    With `AYL_STRICT_HIT_ID=0` the model may return a quote without naming the
    passage it came from, and the old rule searched every hit of the window and
    took the first that matched — so an item whose `book` field said one thing
    was pinned, silently, to whatever else happened to hold those words. The
    model's own `book` is a claim, and here it is the one thing narrowing the
    search: it is resolved canonically against the books this run retrieved
    (`catalog.resolve_title`, the resolver the catalogue answers "do I have X"
    with), and the quote must then sit in exactly one passage of that one book.

    Three ways that fails and all three are drops, because none of them yields a
    citation anyone could write down: a name that matches no retrieved book or
    matches two, and a quote that two passages of the right book hold. The
    length floor applies here as it does to a re-pin — this is the same act of
    inventing a citation, seen from the other end."""
    if quote_tokens(quote) < MIN_REPIN_TOKENS:
        return "", "short"
    if not (isinstance(stated_book, str) and stated_book.strip()):
        return "", "no_hit"
    entries = _book_entries(index)
    matches, _ = resolve_title(stated_book.strip(), entries, strict=True)
    if not matches:
        matches, _ = resolve_title(stated_book.strip(), entries)
    if len(matches) != 1:
        return "", "no_hit"
    quote_norm = _normalize(quote)
    holders = [hit_id for hit_id, record in index.items()
               if record["book"] == matches[0].key and _found_in(quote_norm, record["segments"])]
    return (holders[0], "") if len(holders) == 1 else ("", "no_hit")


def classify_quote(quote: str, hit_id: str, index: dict[str, dict]) -> tuple[str, str]:
    """THE quote check, run by both gates: what is this quote, and which
    retrieved passage holds it? Returns (status, hit_id of the holder); the
    holder is "" when nothing holds it.

    The search runs **book before corpus**, in four passes. The cited passage
    first, and what it is decides the answer: its own book text **confirms**; a
    book card that holds the quote is **card_only**, because the citation is
    right and the source is a model's summary rather than the author's words.
    Then the rest of the CITED BOOK — its other chapters, then its cards — and
    only after that other books, whose holders exist to classify a drop rather
    than to receive a re-pin. Corpus-before-book was the wrong order: a
    transcript of some other work outranked a card of the book actually cited,
    so the gate dropped as `cross_book` an item whose own book held the quote
    one passage away. Nothing at all makes it **broken**; an empty or
    punctuation-only quote is broken by construction, there being no word
    sequence to find.

    Reading the cited passage first is what keeps the two gates telling the same
    story about one quote. The gate sees one step; `validate` sees the whole
    run, so a card quote from step 1 whose words a later step also retrieves as
    book text would otherwise be `card_only` at the gate and `unattributed` in
    the report — two verdicts, one quote, and the invariant below untrue.

    `observe` calls this before an item becomes evidence and `validate` calls it
    on the evidence afterwards. One function, one normalization, one verdict —
    which is why `confirmed == checked_book_text` holds by construction on a run
    whose evidence went through the gate."""
    quote_norm = _normalize(quote)
    if not quote_norm:
        return BROKEN, ""
    cited = index.get(hit_id)
    if cited is not None and _found_in(quote_norm, cited["segments"]):
        return (CARD_ONLY if cited["card"] else CONFIRMED), hit_id
    book = cited["book"] if cited is not None else ""
    section = cited["section"] if cited is not None else ""
    # Book before corpus: the cited book's own text, then the cited book's
    # cards, and only then anything else. `_holder_among` already prefers the
    # named book, so a pass is "inside this book" when it returns a holder from
    # it and "anywhere" otherwise — which is why the same-book passes come as a
    # pair before the two that may land in another work.
    for card, status in ((False, UNATTRIBUTED), (True, CARD_ONLY)):
        holder = _holder_among(quote_norm, index, card, book, section, hit_id)
        if holder and index[holder]["book"] == book:
            return status, holder
    for card, status in ((False, UNATTRIBUTED), (True, CARD_ONLY)):
        holder = _holder_among(quote_norm, index, card, book, section, hit_id)
        if holder:
            return status, holder
    return BROKEN, ""


def match_span(passage: str, quote: str) -> tuple[int, int] | None:
    """WHERE the quote sits inside the passage — (start, end) character offsets
    into `passage`, or None when it is not there.

    `validate` answers whether a quote is a contiguous run of a passage; this
    answers where, so an interface can point at the proof instead of printing it
    above six lines of text and leaving the reader to find it (design critique
    16.09 §1.3). It runs the same `_normalize` over both sides, so the two agree:
    what validate confirmed against this passage is found here, and a quote it
    did not confirm is not.

    The span covers whole whitespace-separated chunks of the RAW text. That is
    the finest boundary offsets survive: inside a chunk, NFKC composition, the
    dropped control characters and the punctuation rules all change lengths, so
    a normalized offset is not a raw one. The practical effect is that a
    trailing comma or a closing quotation mark is inside the span although the
    matched token run stops before it — which is what a reader wants marked
    anyway. The chunk joiner of a chapter read is a barrier, exactly as it is in
    `_segments`: a run that straddles it is not contiguous in the book and is
    not a match here either."""
    needle = _normalize(quote).split()
    if not needle:
        return None
    tokens, chunks, where = _tokens_with_offsets(_without_markers(passage, keep_offsets=True))
    for start in range(len(tokens) - len(needle) + 1):
        if tokens[start:start + len(needle)] == needle:
            first, last = chunks[where[start]], chunks[where[start + len(needle) - 1]]
            if first is not None and last is not None:
                return first[0], last[1]
    return None


def _tokens_with_offsets(body: str) -> tuple[list[str | None], list[tuple[int, int] | None],
                                             list[int]]:
    """The passage as normalized tokens, each pointing back at the raw text it
    came from: (tokens, spans, token -> span index).

    One raw whitespace-separated chunk can normalize into several tokens
    ("snake_case" is two), so the mapping is a list and not a zip. A chunk
    joiner becomes a None barrier in all three: nothing may match — or be
    measured as near — across text that is not contiguous in the book.

    Two readers: `match_span`, which wants where a known quote sits, and
    `window_around`, which wants where a query's words sit thickest."""
    spans: list[tuple[int, int] | None] = []
    tokens: list[str | None] = []
    where: list[int] = []
    offset = 0
    for index, part in enumerate(body.split(CHUNK_JOINER)):
        if index:
            spans.append(None)
            tokens.append(None)
            where.append(len(spans) - 1)
        for word in re.finditer(r"\S+", part):
            spans.append((offset + word.start(), offset + word.end()))
            for token in _normalize(word.group()).split():
                tokens.append(token)
                where.append(len(spans) - 1)
        offset += len(part) + len(CHUNK_JOINER)
    return tokens, spans, where


def best_match_span(passage: str, query: str, width: int) -> tuple[int, int] | None:
    """Where `query`'s words sit thickest in `passage`: the (start, end) of the
    tightest run of them that fits in `width` characters, or None when the
    passage holds none of them.

    "Thickest" is how many DIFFERENT words of the query the run covers, then —
    between runs that cover the same words — the shorter one, then the earlier
    one. Counting distinct words rather than occurrences is what keeps a page
    that repeats "the" from outranking the one page that carries the query's
    rare words together; the tie-breaks are there so the result is one span and
    not a set of equally good ones, because a retrieval this deterministic is
    the only kind that can be tested and re-run.

    There is no stop-word list: the corpus is not one language (the demo
    library holds Ukrainian), a list per language is a thing to maintain and
    get wrong, and "distinct words covered" already prices a common word at
    what it is worth — one word out of several.

    This is a LEXICAL match over the raw text, not the retrieval the index
    does: no vectors, no BM25 statistics, nothing but the query's own words.
    That is the whole of what is available here — neither retriever returns the
    offsets of what it matched (ADR-025) — and it is honest about what it
    cannot do: a window chosen for a query whose words the passage never spells
    is no window at all, and the caller falls back to the head."""
    terms = set(_normalize(query).split())
    if not terms:
        return None
    tokens, spans, where = _tokens_with_offsets(passage)
    hits = [(spans[where[i]], token) for i, token in enumerate(tokens)
            if token in terms and spans[where[i]] is not None]
    if not hits:
        return None
    best: tuple[int, int] | None = None
    best_key: tuple[int, int] | None = None
    counts: dict[str, int] = {}
    distinct = 0
    right = 0
    for left in range(len(hits)):
        if right < left:            # the previous window closed on nothing
            right, counts, distinct = left, {}, 0
        while right < len(hits) and hits[right][0][1] - hits[left][0][0] <= width:
            term = hits[right][1]
            counts[term] = counts.get(term, 0) + 1
            distinct += 1 if counts[term] == 1 else 0
            right += 1
        if right == left:           # this single hit is wider than the budget
            continue
        start, end = hits[left][0][0], hits[right - 1][0][1]
        key = (distinct, -(end - start))
        if best_key is None or key > best_key:
            best_key, best = key, (start, end)
        term = hits[left][1]
        counts[term] -= 1
        distinct -= 1 if counts[term] == 0 else 0
    return best


def _snap_forward(text: str, at: int) -> int:
    """`at`, moved to the start of the next whole word when it fell inside one.
    Only ever moves right, so a window that snaps never grows past its budget."""
    if at <= 0 or at >= len(text) or text[at - 1].isspace():
        return at
    while at < len(text) and not text[at].isspace():
        at += 1
    while at < len(text) and text[at].isspace():
        at += 1
    return at


def _snap_back(text: str, at: int) -> int:
    """`at`, moved to the end of the previous whole word when it fell inside
    one. Only ever moves left, for the same reason."""
    if at >= len(text) or at <= 0 or text[at].isspace():
        return at
    while at > 0 and not text[at - 1].isspace():
        at -= 1
    while at > 0 and text[at - 1].isspace():
        at -= 1
    return at


def _body_and_tail(text: str) -> tuple[str, int]:
    """A chapter read split into (its text, the characters of the chapter that
    are NOT in it).

    The second number is the marker's own count PLUS the marker's own length.
    A cut marker does not sit beside the text it replaces, it sits INSIDE the
    budget (`library.join_chapter`), so stripping it removes both what it says
    was hidden and the characters it was written over. Counting only the first
    loses the marker's length on every arithmetic done afterwards — which is
    how a chapter longer than the scan budget came back with a head cut whose
    "characters not shown" was short by exactly one marker, and therefore not
    the head cut an unaimed read of the same chapter produces."""
    marker = CUT_MARKER_RE.search(text)
    if not marker:
        return text, 0
    hidden = int(re.search(r"\d+", marker.group()).group())
    return text[:marker.start()], hidden + len(marker.group())


def window_around(text: str, query: str, budget: int) -> str:
    """`budget` characters of a chapter read around the best lexical match for
    `query`, with an in-band marker for what is left out at each end.

    This is the second half of ADR-025. The first half made a search chunk and
    the observation window one decision; a chapter read is the same decision at
    ten times the scale — 12,000 characters off the FRONT of a chapter, chosen
    by nothing, because the head is where a cut is cheapest to write. A
    question about the last page of a long chapter reads the first page of it.

    The window is computed ONCE, in `act`, and what this returns is stored in
    `hits_log` as the passage — which is what makes it safe. The window IS the
    provenance haystack (ADR-004): a quote is checked against the text the
    model was shown, so a window recomputed in `observe`, or later in
    `validate`, would turn honest quotes from a passage that moved into broken
    ones. Nothing downstream re-runs this; they all read the stored text.

    A query whose words the chapter does not carry gets the head of the
    chapter, exactly as before — a window centred on nothing is worse than an
    honest beginning — and "exactly" is meant character for character
    (`_head_cut`), so a query that misses cannot be told from a read that never
    named one. A request that names no query does not reach this function at
    all: `act` reads the head directly."""
    if len(text) <= budget and not CUT_MARKER_RE.search(text):
        return text                      # the whole chapter fits; nothing to choose
    # `hidden_beyond` is everything of the chapter that is not in `body`: what
    # an earlier cut said it left out, and the characters that cut wrote its own
    # marker over. len(body) + hidden_beyond is the chapter as it was.
    body, hidden_beyond = _body_and_tail(text)
    # Both markers live INSIDE the budget, like `join_chapter`'s does, so every
    # later cut at the same limit (the scratchpad, the observe prompt) still
    # shows them. Their length depends on numbers the window has not been
    # chosen yet, so the room reserved is an upper bound on both: the digits of
    # a count that cannot be larger than the chapter itself.
    reserve = len(head_marker(len(body))) + len(cut_marker(len(body) + hidden_beyond))
    width = max(1, budget - reserve)
    span = best_match_span(body, query, width)
    if span is None:
        start = 0
    elif span[1] - span[0] >= width:
        start = span[0]                  # the match itself fills the window
    else:
        start = max(0, span[0] - (width - (span[1] - span[0])) // 2)
    end = min(len(body), start + width)
    start = max(0, end - width)          # a window at the end of the chapter is still full
    start, end = _snap_forward(body, start), _snap_back(body, end)
    if end <= start:                     # one word longer than the whole budget
        start, end = max(0, min(start, len(body))), min(len(body), start + width)
    if start == 0:
        # The window opens where the chapter does, so it IS the head cut — and
        # it must be the head cut character for character, not a head cut minus
        # the room reserved for a marker that is not going to be written. That
        # is the difference between "this query found nothing, so you get the
        # opening as always" and a second, slightly shorter kind of head read
        # that only ever happens when a query was named and missed.
        return _head_cut(body, budget, hidden_beyond)
    hidden_after = (len(body) - end) + hidden_beyond
    return f"{head_marker(start)}{body[start:end]}" \
           f"{cut_marker(hidden_after) if hidden_after else ''}"


def window_span(window: str, scanned: str) -> dict:
    """Where a chapter read's window sits in its section, for the log (#81).

    Read back off the text `act` already built, never by choosing the window a
    second time: `scanned` is the chapter as `read_chapter` returned it (before
    any window), `window` is the passage the model was shown. The offsets are
    in the section as the index joins it (chunk joiners included), which is
    the text `window_around` counts in:

      start, end      the window's characters, [start, end)
      section_chars   the whole section, including what the scan never reached
      scanned_chars   how much of it the read could choose a window from

    Nothing here feeds a prompt or a decision; it only says where the reader
    was looking."""
    body, hidden_beyond = _body_and_tail(scanned)
    head = HEAD_MARKER_RE.match(window)
    start = int(re.search(r"\d+", head.group()).group()) if head else 0
    visible = CUT_MARKER_RE.sub("", window[head.end():] if head else window)
    return {"start": start, "end": start + len(visible),
            "section_chars": len(body) + hidden_beyond, "scanned_chars": len(body)}


def _head_cut(body: str, budget: int, hidden_beyond: int = 0) -> str:
    """The head of a chapter at `budget` characters — `library.join_chapter`'s
    own arithmetic, reproduced here so that a windowed read that lands on the
    head is byte-identical to a read that never asked for a window.

    `hidden_beyond` is the rest of the chapter: what an earlier cut (the scan
    budget) left out and the characters it wrote its marker over. `len(body) +
    hidden_beyond` is therefore the chapter's own length, which is what
    `join_chapter` counts from — so the count in the marker is the same number
    down to the digit whether the chapter fitted the scan budget or not."""
    hidden = len(body) + hidden_beyond - budget
    if hidden <= 0:
        return body[:budget]
    marker = cut_marker(hidden)
    return body[:max(0, budget - len(marker))] + marker


def gate_counts(state: AgentState) -> dict:
    """What the observe gate spent, as the report carries it (#29). Always the
    same keys and always the same shape, so an interface, the harness and a
    sidecar read one thing whether or not this run dropped anything; a state
    from before the gate (a recording, a legacy caller) reads back as a run that
    dropped nothing, which is exactly what it was.

    One headline and its telemetry. `dropped_unverified` is what a reader wants
    — how many quotes this answer was refused — and `dropped_by_reason` splits
    it four ways for whoever has to do something about it. The parts sum to the
    whole by construction; nothing in the breakdown is an outcome beside it."""
    reasons = state.get("dropped_by_reason") or {}
    return {"dropped_unverified": int(state.get("dropped_unverified") or 0),
            "repinned": int(state.get("repinned") or 0),
            "dropped_by_reason": {r: int(reasons.get(r) or 0) for r in DROP_REASONS}}


def validate(state: AgentState) -> dict:
    """Quote-provenance guard (plain CODE, no LLM). Every evidence item names the
    hit it was copied from (hit_id, assigned by act; book/section taken from the
    hit record). The WHOLE quote, as a normalized word sequence, must be a
    contiguous substring of that hit's text as observe saw it:
      confirmed    found in the cited hit, and that hit is the book's own text
      card_only    found in the cited hit and that hit is a book card, or found
                   in no cited passage and in no other book text but on a card
      unattributed not in the cited hit, but found in another retrieved book text
      broken       found in no retrieved passage at all
    The cited passage is read first (see `classify_quote`): a quote inside the
    card it cites is `card_only` even when a later step also retrieved those
    words as book text, because the citation is right and the source is a
    model's summary. That ordering is what makes the report agree with the gate,
    which saw only one step's passages.

    The four are a partition of `checked`; the first three are a partition of
    `checked_book_text` (= checked - card_only), which is the denominator of
    every "traced" count an interface shows. A card is a model-written summary,
    so a quote whose only match is a card is not a quote from the book and is
    never counted as traced — it is reported as what it is. No scratchpad
    parsing, no section or title substring matching, no fallback that confirms.

    Every item also carries `source_kind` — "book_text", "card", or "" when the
    cited hit is not in this run's log — so the CLI, the web UI and the eval
    harness label evidence by source type off the same record.

    Checks EVERY evidence item, whether or not the answer names its book: the
    answer may cite a book by a short title ("Dracula" for "Dracula — Bram
    Stoker"), so a title-based skip could leave exactly the evidence the answer
    used unchecked. Items for books the answer does not name by their index key
    are counted as `unused` for information only; they are checked all the same.
    (`unused` counts by title: "Dracula" in the answer covers "Dracula — Bram Stoker".)

    Proves retrieval provenance, not that the answer's reasoning is sound: a
    character's lie quoted verbatim from the right chapter is confirmed.

    Since #29 this is a REPORT on evidence that already passed the same check at
    the `observe` gate, so on any run whose evidence went through that gate
    `confirmed == checked_book_text` and `broken == 0` by construction — the
    numbers are the proof that the gate held, not the first time a quote is
    looked at. What the gate dropped is carried beside them
    (`dropped_unverified`, `repinned`) instead of standing in the answer. The
    quotations the ANSWER itself writes are still unchecked: this module checks
    the evidence the answer was written from, which is what the watermark and
    `docs/known-limits.md` say."""
    empty = {"checked": 0, "checked_book_text": 0, "confirmed": 0, "unattributed": 0,
             "broken": 0, "card_only": 0, "unused": 0, "broken_items": [], "items": [],
             **gate_counts(state)}
    # What the gate dropped before synthesis is part of THIS report, not a
    # separate one — and it matters most on the path where there is no evidence
    # left to report, because then the drops are the whole story of the refusal.
    dropped_note = (t("dropped_note", n=empty["dropped_unverified"])
                    if empty["dropped_unverified"] else "")
    if state.get("catalog"):
        # The catalogue path (ADR-016): the answer is a list computed by code
        # from the index tables, with no quotes to check; the report says so,
        # and carries the numbers so an interface can show them instead of "0/0".
        listing = state["catalog"]
        return {"verification": t("verif_catalog", n=listing["count"], total=listing["total"]),
                "provenance": {**empty, "catalog": {"op": listing["op"], "count": listing["count"],
                                                    "total": listing["total"]}}}
    if not state["evidence"]:
        return {"verification": t("verif_no_evidence") + dropped_note, "provenance": empty}

    answer_norm = _normalize(state.get("answer", ""))
    evidence_to_check = state["evidence"]
    # Information only (checked all the same): items whose book title the
    # answer never mentions, leftovers of abandoned search branches.
    unused = sum(1 for e in evidence_to_check if _normalize(title_of(e["book"])) not in answer_norm)
    unused_note = (t("unused_note", n=unused) if unused else "") + dropped_note

    corpus_of = {h["hit_id"]: h.get("corpus", "") for h in state.get("hits_log", [])
                 if h.get("hit_id")}
    # One haystack, built by the same function the observe gate builds it with,
    # and read by the same `classify_quote`: the book text and the cards are two
    # populations inside it, because a match in one of them means something a
    # match in the other does not. Only the book text can confirm a quote FROM
    # THE BOOK; a card tells "the model wrote this summary line" apart from
    # "nobody wrote this at all".
    index = passage_index(state.get("hits_log", []))

    def source_kind(hit_id: str) -> str:
        """What a reader opens when they open the cited passage — the label the
        interfaces put on the evidence item.

        "" means NO CLAIM, and there are two ways to get it: a hit this run
        never logged (an id the model invented, or a legacy caller with no
        hits_log), and a hit logged without a `corpus` — an index or a recording
        from before cards existed. The second is deliberately not "book_text":
        the classification above counts such a hit as book text, because that is
        the conservative reading and the only one that cannot invent a card, but
        that is an assumption the code makes and not a fact the record carries.
        An interface prints a label it is given; it must not print one this
        function guessed."""
        corpus = corpus_of.get(hit_id, "")
        if not corpus:
            return ""
        return "card" if corpus == CARD_CORPUS else "book_text"

    confirmed = 0
    unattributed = 0
    card_only = 0
    broken = []
    items = []      # every evidence item with its verdict, in evidence order: what the interfaces open
    for e in evidence_to_check:
        hit_id = e.get("hit_id", "")
        status, _holder = classify_quote(e["quote"], hit_id, index)
        if status == CONFIRMED:
            confirmed += 1
        elif status == UNATTRIBUTED:
            unattributed += 1
        elif status == CARD_ONLY:
            # Real text, really retrieved — and written by a model, so the
            # headline count must not say the book says it.
            card_only += 1
        else:
            broken.append({"hit_id": hit_id, "book": e["book"],
                           "section": e.get("section", ""), "quote": e["quote"][:120]})
        items.append({"hit_id": hit_id, "book": e["book"], "section": e.get("section", ""),
                      "quote": e["quote"], "status": status, "source_kind": source_kind(hit_id)})

    checked = len(evidence_to_check)
    stats = {"checked": checked, "checked_book_text": checked - card_only,
             "confirmed": confirmed, "unattributed": unattributed, "broken": len(broken),
             "card_only": card_only, "unused": unused, "broken_items": broken, "items": items,
             **gate_counts(state)}
    if not broken and not unattributed and not confirmed and card_only:
        # Nothing at all was traced to the book: saying "OK: all 0 quotes" would
        # be the green sentence for the one case that most needs a different one.
        return {"verification": t("verif_cards_only", n=card_only, unused=unused_note),
                "provenance": stats}
    if unattributed:
        unused_note += t("unattributed_note", n=unattributed)
    if card_only:
        unused_note += t("card_note", n=card_only)
    if not broken and not unattributed:
        return {"verification": t("verif_ok", n=confirmed, unused=unused_note),
                "provenance": stats}
    if not broken:
        return {"verification": t("verif_partial", ok=confirmed, checked=stats["checked_book_text"],
                                  unused=unused_note),
                "provenance": stats}
    items = "\n  - ".join(f"{b['book']}: \"{b['quote'][:80]}...\"" for b in broken)
    return {"verification": t("verif_warn", broken=len(broken), checked=stats["checked_book_text"],
                              unused=unused_note, items=items),
            "provenance": stats}
