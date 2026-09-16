"""The provenance engine: what counts as evidence, and the code-only check
that every quote is a verbatim, contiguous run inside the retrieved passage it
is pinned to (ADR-004). No LLM anywhere in this module.

`_valid_evidence` is the entry gate (observe): malformed items are dropped and
every kept item is pinned to the hit it was copied from (book and section come
from the hit record, never from the model). `validate` is the exit gate (the
last graph node): confirmed / unattributed / card-only / broken partition every
checked item, and nothing that is not a retrieved passage can confirm a quote.

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

from .config import SEARCH_HIT_CHARS
from .i18n import t
from .library import title_of
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


def _valid_evidence(items, hits: list[dict] | None = None) -> list[dict]:
    """Keep only well-formed evidence items and pin each one to the hit it was
    copied from: book and section are taken from the hit record, never from the
    model. Malformed output is dropped, not crashed on. `hits` is None only in
    legacy callers/tests; then the model's book/section are kept as given."""
    by_id = {h["hit_id"]: h for h in (hits or []) if h.get("hit_id")}
    valid = []
    if not isinstance(items, list):
        # "evidence": 42 or "evidence": "none" is valid JSON and malformed
        # output: dropped like a malformed item, never a TypeError mid-run.
        return valid
    for e in items or []:
        if not isinstance(e, dict):
            continue
        book, quote = e.get("book"), e.get("quote")
        if not (isinstance(quote, str) and quote.strip()):
            continue
        quote = quote.strip()[:MAX_QUOTE_CHARS]
        hit_id = e.get("hit_id") if isinstance(e.get("hit_id"), str) else ""
        hit = by_id.get(hit_id)
        if hits is not None:
            if hit is None and not HIT_ID_STRICT:
                quote_norm = _normalize(quote)
                hit = next((h for h in hits if quote_norm
                            and any(_contains_tokens(seg, quote_norm) for seg in _segments(h["text"]))), None)
            if hit is None:
                llm._usage().evidence_dropped_no_hit += 1
                continue
            book, section, hit_id = hit["book"], hit["section"], hit["hit_id"]
        else:
            if not (isinstance(book, str) and book.strip()):
                continue
            book, section = book.strip(), str(e.get("section") or "").strip()
        valid.append({"hit_id": hit_id, "book": book, "section": section, "quote": quote,
                      "why": str(e.get("why") or "").strip()[:300]})
    return valid


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
CUT_MARKER_RE = re.compile(r"\n?\[chapter continues: \d+ characters not shown\]\s*$")


def _segments(hit_text: str) -> list[str]:
    """Normalized text of one hit, split where the text is NOT contiguous in
    the source: at the chunk joiner of a chapter read. The chapter-cut marker
    is service text, never evidence, and is removed before normalizing. A
    quote must fit inside ONE segment; "before [...] after" is two."""
    body = CUT_MARKER_RE.sub("", hit_text)
    return [_normalize(part) for part in body.split(CHUNK_JOINER)]


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
    body = CUT_MARKER_RE.sub("", passage)
    chunks: list[tuple[int, int] | None] = []
    tokens: list[str | None] = []
    where: list[int] = []
    offset = 0
    for index, part in enumerate(body.split(CHUNK_JOINER)):
        if index:
            # a barrier chunk: it holds a token no quote can carry, so no match
            # is allowed to run across the [...] that separates two chunks
            chunks.append(None)
            tokens.append(None)
            where.append(len(chunks) - 1)
        for word in re.finditer(r"\S+", part):
            chunks.append((offset + word.start(), offset + word.end()))
            for token in _normalize(word.group()).split():
                tokens.append(token)
                where.append(len(chunks) - 1)
        offset += len(part) + len(CHUNK_JOINER)
    for start in range(len(tokens) - len(needle) + 1):
        if tokens[start:start + len(needle)] == needle:
            first, last = chunks[where[start]], chunks[where[start + len(needle) - 1]]
            if first is not None and last is not None:
                return first[0], last[1]
    return None


def validate(state: AgentState) -> dict:
    """Quote-provenance guard (plain CODE, no LLM). Every evidence item names the
    hit it was copied from (hit_id, assigned by act; book/section taken from the
    hit record). The WHOLE quote, as a normalized word sequence, must be a
    contiguous substring of that hit's text as observe saw it:
      confirmed    found in the cited hit, and that hit is the book's own text
      unattributed not in the cited hit, but found in another retrieved book text
      card_only    found in no retrieved book text, but found in a book card
      broken       found in no retrieved passage at all
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
    character's lie quoted verbatim from the right chapter is confirmed."""
    empty = {"checked": 0, "checked_book_text": 0, "confirmed": 0, "unattributed": 0,
             "broken": 0, "card_only": 0, "unused": 0, "broken_items": [], "items": []}
    if state.get("catalog"):
        # The catalogue path (ADR-016): the answer is a list computed by code
        # from the index tables, with no quotes to check; the report says so,
        # and carries the numbers so an interface can show them instead of "0/0".
        listing = state["catalog"]
        return {"verification": t("verif_catalog", n=listing["count"], total=listing["total"]),
                "provenance": {**empty, "catalog": {"op": listing["op"], "count": listing["count"],
                                                    "total": listing["total"]}}}
    if not state["evidence"]:
        return {"verification": t("verif_no_evidence"), "provenance": empty}

    answer_norm = _normalize(state.get("answer", ""))
    evidence_to_check = state["evidence"]
    # Information only (checked all the same): items whose book title the
    # answer never mentions, leftovers of abandoned search branches.
    unused = sum(1 for e in evidence_to_check if _normalize(title_of(e["book"])) not in answer_norm)
    unused_note = t("unused_note", n=unused) if unused else ""

    corpus_of = {h["hit_id"]: h.get("corpus", "") for h in state.get("hits_log", [])
                 if h.get("hit_id")}
    hits = {h["hit_id"]: _segments(h["text"]) for h in state.get("hits_log", [])}
    # Two haystacks, because a match in one of them means something a match in
    # the other does not. Only the book text can confirm a quote FROM THE BOOK;
    # the cards are searched afterwards, to tell "the model wrote this summary
    # line" apart from "nobody wrote this at all".
    book_text = {hit_id: segs for hit_id, segs in hits.items()
                 if corpus_of.get(hit_id, "") != CARD_CORPUS}
    cards = {hit_id: segs for hit_id, segs in hits.items()
             if corpus_of.get(hit_id, "") == CARD_CORPUS}

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

    def found_in(quote_norm: str, segments: list[str]) -> bool:
        return bool(quote_norm) and any(_contains_tokens(seg, quote_norm) for seg in segments)

    confirmed = 0
    unattributed = 0
    card_only = 0
    broken = []
    items = []      # every evidence item with its verdict, in evidence order: what the interfaces open
    for e in evidence_to_check:
        quote_norm = _normalize(e["quote"])
        hit_id = e.get("hit_id", "")
        if found_in(quote_norm, book_text.get(hit_id, [])):
            confirmed += 1
            status = "confirmed"
        elif any(found_in(quote_norm, segs) for segs in book_text.values()):
            unattributed += 1
            status = "unattributed"
        elif any(found_in(quote_norm, segs) for segs in cards.values()):
            # Real text, really retrieved — and written by a model, so the
            # headline count must not say the book says it.
            card_only += 1
            status = "card_only"
        else:
            status = "broken"
            broken.append({"hit_id": hit_id, "book": e["book"],
                           "section": e.get("section", ""), "quote": e["quote"][:120]})
        items.append({"hit_id": hit_id, "book": e["book"], "section": e.get("section", ""),
                      "quote": e["quote"], "status": status, "source_kind": source_kind(hit_id)})

    checked = len(evidence_to_check)
    stats = {"checked": checked, "checked_book_text": checked - card_only,
             "confirmed": confirmed, "unattributed": unattributed, "broken": len(broken),
             "card_only": card_only, "unused": unused, "broken_items": broken, "items": items}
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
