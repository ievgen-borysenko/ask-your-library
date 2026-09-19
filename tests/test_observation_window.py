"""The chunk and the observation window are one decision (#28, ADR-025).

Two halves, and they meet in the middle:

* the CHUNKER packs a transcript chunk to less than the window `observe` reads,
  so a search hit arrives whole and nothing is ranked that the model never
  sees. Measured here against the audio transcripts that are actually in this
  repository — `corpus/prepared-audio/` is where the 10,140-character
  "sentence" lives, so the pathological case is a fixture and not a story.
* a CHAPTER READ that says what it is looking for is cut around the match
  instead of at the head, and the window is computed ONCE, in `act`, and stored
  in `hits_log` — because the window is the provenance haystack (ADR-004), and
  a window recomputed downstream turns honest quotes into broken ones.

No LLM, no network, no index: the chunker is a pure function and the chapter
read is faked.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ask_your_library import config, library, llm, nodes, provenance
from ask_your_library.bookkey import chapter_marker, split_read_query, unescape_marker
from ask_your_library.ingest import pack_sentences, split_sentences
from ask_your_library.ingest.chunking import (MAX_SENTENCE_CHARS, TRANSCRIPT_MAX_CHARS,
                                              TRANSCRIPT_TARGET_CHARS, cap_sentence)
from ask_your_library.provenance import best_match_span, window_around

REPO = Path(__file__).resolve().parents[1]
PREPARED_AUDIO = REPO / "corpus" / "prepared-audio"

_spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", REPO / "scripts" / "ingest_demo_corpus.py")
demo = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("ingest_demo_corpus", demo)
_spec.loader.exec_module(demo)


# --- the chunk is the window ------------------------------------------------

def test_the_chunker_packs_under_the_window_it_will_be_read_through():
    """The relation the whole issue is about, asserted once. The chunker does
    not import `config` — a chunker whose output depends on an environment
    variable writes chunks no version string can describe — so this is where
    the two numbers are held together instead."""
    assert TRANSCRIPT_MAX_CHARS <= config.SEARCH_HIT_CHARS
    # and with room for the overlap a chunk carries from its predecessor
    assert TRANSCRIPT_TARGET_CHARS < config.SEARCH_HIT_CHARS


@pytest.mark.parametrize("path", sorted(PREPARED_AUDIO.glob("*.json")), ids=lambda p: p.stem)
def test_no_chunk_of_a_committed_audio_transcript_is_over_the_window(path):
    """0% over the window, on the corpus that measured 90% over it.

    These two books are raw Whisper output, committed so the audio path builds
    on any OS — and they are the worst case by a distance: the longest
    unpunctuated run in the demo corpus (10,140 characters, `time-machine`
    Chapter 3) is in one of them, and it used to be packed whole into a
    10,778-character chunk."""
    doc = json.loads(path.read_text(encoding="utf-8"))
    chunks = demo.chunk_prepared(doc)
    assert chunks
    over = [len(c.text) for c in chunks if len(c.text) > config.SEARCH_HIT_CHARS]
    assert not over, f"{len(over)} chunk(s) over the window, longest {max(over, default=0)}"


def test_the_committed_transcripts_really_do_hold_a_sentence_over_the_window():
    """The test above would also pass on a corpus with nothing to cap. This is
    what makes it a measurement: the fixture carries the case."""
    longest = 0
    for path in PREPARED_AUDIO.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for chapter in doc["chapters"]:
            longest = max([longest] + [len(s) for s in split_sentences(chapter["text"])])
    assert longest > config.SEARCH_HIT_CHARS


def test_a_sentence_with_no_punctuation_in_it_is_capped_not_carried_whole():
    """The audio case as a unit: one 10,778-character "sentence", which is the
    size the demo corpus's largest chunk actually was."""
    run = " ".join(["speaking without any punctuation at all"] * 260)
    assert len(run) > 10_000
    pieces = cap_sentence(run)
    assert len(pieces) > 1
    assert all(len(p) <= MAX_SENTENCE_CHARS for p in pieces)
    assert " ".join(pieces) == run                       # nothing lost, nothing invented
    assert all(p in run for p in pieces)                 # and every piece is a slice of it
    chunks = pack_sentences([run])
    assert all(len(c) <= TRANSCRIPT_MAX_CHARS for c in chunks)


def test_a_capped_piece_is_the_book_s_own_characters():
    """Pieces are SLICES of the sentence: the tab, the double space and the
    Unicode spaces a book prints survive inside a piece. The quote check
    normalizes both sides and would not have noticed the difference — which is
    why this is asserted here, on the text the index stores and the reader is
    shown, and not left to the comparison that cannot see it."""
    run = ("a\u00a0word\tafter  another\u2009one and then some more of them " * 120)
    assert len(run) > MAX_SENTENCE_CHARS
    pieces = cap_sentence(run)

    assert len(pieces) > 1
    assert all(len(piece) <= MAX_SENTENCE_CHARS for piece in pieces)
    assert all(piece in run for piece in pieces)                  # every piece is a slice
    assert any("\t" in piece for piece in pieces)
    assert any("\u00a0" in piece for piece in pieces)
    assert any("  " in piece for piece in pieces)
    # nothing but the whitespace at the breaks is lost
    assert "".join("".join(piece.split()) for piece in pieces) == "".join(run.split())


def test_a_word_longer_than_the_cap_is_cut_because_nothing_else_is_left():
    piece, = cap_sentence("x" * MAX_SENTENCE_CHARS)
    assert piece == "x" * MAX_SENTENCE_CHARS
    pieces = cap_sentence("y" * (MAX_SENTENCE_CHARS * 2 + 7))
    assert [len(p) for p in pieces] == [MAX_SENTENCE_CHARS, MAX_SENTENCE_CHARS, 7]
    assert "".join(pieces) == "y" * (MAX_SENTENCE_CHARS * 2 + 7)


def test_the_length_that_is_counted_is_the_length_of_the_string_returned():
    """Hundreds of tiny sentences: the joining spaces are most of the chunk.

    The old packer counted the sentences and not the spaces between them, so a
    chapter of one-word lines packed to a "target" of 2,400 and came back a
    quarter longer — the second way a chunk used to escape its budget, and the
    one no chunk-size histogram would have explained."""
    chunks = pack_sentences(["Yes."] * 2000)
    assert len(chunks) > 1
    assert all(len(c) <= TRANSCRIPT_MAX_CHARS for c in chunks)


def test_chunks_still_overlap_and_still_end_on_a_whole_sentence():
    chunks = pack_sentences([f"Sentence number {i} is here." for i in range(400)])
    assert len(chunks) > 1
    assert all(c.endswith(".") for c in chunks)
    first_of_second = chunks[1].split(". ")[0] + "."
    assert first_of_second in chunks[0]


@pytest.mark.skipif(not (demo.PREPARED_DIR.exists() and any(demo.PREPARED_DIR.glob("*.json"))),
                    reason="the prepared demo texts are not in the repository (data/prepared)")
def test_no_chunk_of_the_prepared_demo_corpus_is_over_the_window():
    """The whole corpus, when the machine running the tests has it: this is the
    number the issue is closed by (90% over the window -> 0%), and the operator
    can produce it before spending half an hour on the re-ingest."""
    over, total = 0, 0
    for path in sorted(demo.PREPARED_DIR.glob("*.json")):
        for chunk in demo.chunk_prepared(json.loads(path.read_text(encoding="utf-8"))):
            total += 1
            over += len(chunk.text) > config.SEARCH_HIT_CHARS
    assert total and over == 0, f"{over} of {total} chunks over {config.SEARCH_HIT_CHARS}"
# --- the window around the match --------------------------------------------

NEEDLE = "The keeper found the drowned lamp under the seventh stair."
FILLER = ("The lighthouse keeper counted the ships that passed the headland. "
          "He wrote each name in a ledger bound in green cloth. ")


def long_chapter(needle_at: float = 0.8, length: int = 900) -> str:
    """A chapter far longer than one read, with one distinctive sentence in it.
    `length` is in repetitions of FILLER — 900 is ~110,000 characters, inside
    the scan budget; 1300 is over it."""
    body = FILLER * length
    cut = int(len(body) * needle_at)
    return f"{body[:cut]}{NEEDLE} {body[cut:]}"


def act_on_chapter(monkeypatch, tmp_path, marker, text, book="Some Book — A. Keeper"):
    """`act` over a faked chapter read, with the real cut and the real window."""
    monkeypatch.setattr(nodes, "read_chapter",
                        lambda asked, section, max_chars: (
                            library.join_chapter([{"chunk_id": "b/c/1", "text": text}], max_chars),
                            book, "found"))
    llm.reset_usage()
    scratchpad = tmp_path / "scratch.md"
    scratchpad.write_text("")
    return nodes.act({"current_query": marker, "steps_taken": 1, "read_chapters": [],
                      "scratchpad_path": str(scratchpad)}), scratchpad


def test_a_match_deep_in_a_long_chapter_is_inside_the_window(monkeypatch, tmp_path):
    """The failure this half exists for: 61% of the demo corpus's chapters are
    longer than one read, so the head is a coin toss about where the answer
    is."""
    text = long_chapter()
    marker = chapter_marker("Some Book", "Chapter 3", "drowned lamp seventh stair")

    result, _ = act_on_chapter(monkeypatch, tmp_path, marker, text)

    passage = result["hits"][0]["text"]
    assert NEEDLE in passage
    assert len(passage) <= config.CHAPTER_HIT_CHARS
    # and it says, in band, that it is not the beginning of the chapter
    assert passage.startswith(library.HEAD_MARKER_PREFIX)
    assert passage.rstrip().endswith(library.CUT_MARKER_SUFFIX)
    assert result["read_chapters"] == ["Some Book — A. Keeper|Chapter 3|partial"]


def test_without_a_read_query_the_chapter_is_read_from_its_head(monkeypatch, tmp_path):
    """Unchanged behaviour, byte for byte, for every request that says nothing
    about what it is looking for — including every request an index or a
    recording made before #28."""
    text = long_chapter()

    result, _ = act_on_chapter(monkeypatch, tmp_path, "__chapter__|Some Book|Chapter 3", text)

    passage = result["hits"][0]["text"]
    assert passage.startswith(text[:200])
    assert NEEDLE not in passage
    assert library.HEAD_MARKER_PREFIX not in passage


def test_a_query_the_chapter_does_not_carry_falls_back_to_the_head(monkeypatch, tmp_path):
    """And "falls back to the head" is meant character for character: a query
    that misses must be indistinguishable from a read that named none, or there
    are two kinds of head read and only one of them was ever measured."""
    text = long_chapter()
    marker = chapter_marker("Some Book", "Chapter 3", "zeppelins over montevideo")

    result, _ = act_on_chapter(monkeypatch, tmp_path, marker, text)

    passage = result["hits"][0]["text"]
    assert library.HEAD_MARKER_PREFIX not in passage
    assert passage == library.join_chapter([{"chunk_id": "b/c/1", "text": text}],
                                           config.CHAPTER_HIT_CHARS)


def test_a_chapter_longer_than_the_scan_budget_still_falls_back_to_the_exact_head(monkeypatch,
                                                                                  tmp_path):
    """The scan cut writes a marker INSIDE its budget, so stripping it removes
    both what it says was hidden and the characters it was written over. Count
    only the first and the head cut this falls back to is short by one marker —
    a read that is nearly, but not quite, the read an unaimed request gets."""
    text = long_chapter(length=1300)          # ~155,000 characters, over the scan budget
    assert len(text) > config.CHAPTER_SCAN_CHARS
    marker = chapter_marker("Some Book", "Chapter 3", "zeppelins over montevideo")

    result, _ = act_on_chapter(monkeypatch, tmp_path, marker, text)

    passage = result["hits"][0]["text"]
    assert passage == library.join_chapter([{"chunk_id": "b/c/1", "text": text}],
                                           config.CHAPTER_HIT_CHARS)
    hidden = int(passage.rsplit("continues: ", 1)[1].split(" ")[0])
    assert hidden == len(text) - config.CHAPTER_HIT_CHARS


def test_a_window_inside_a_chapter_longer_than_the_scan_budget_counts_the_whole_tail(monkeypatch,
                                                                                     tmp_path):
    text = long_chapter(needle_at=0.5, length=1300)
    marker = chapter_marker("Some Book", "Chapter 3", "drowned lamp seventh stair")

    result, _ = act_on_chapter(monkeypatch, tmp_path, marker, text)

    passage = result["hits"][0]["text"]
    assert NEEDLE in passage and len(passage) <= config.CHAPTER_HIT_CHARS
    hidden_before = int(passage.split("earlier: ", 1)[1].split(" ")[0])
    hidden_after = int(passage.rsplit("continues: ", 1)[1].split(" ")[0])
    shown = passage.split("characters not shown]\n", 1)[1]
    shown = shown[:shown.rindex("\n[chapter continues:")]
    # Every character of the chapter is either shown or reported as not shown —
    # the scan cut's own marker included, which is the arithmetic that was
    # wrong: its length was neither in the window nor in either count.
    assert hidden_before + len(shown) + hidden_after == len(text)


def test_a_window_that_opens_at_the_first_character_is_the_head_cut():
    """Not only the unmatched query: a match inside the first window IS the
    head of the chapter, and it must be written as one — markers reserve room,
    and room reserved for a marker that is not written is a shorter read."""
    text = long_chapter(needle_at=0.0)
    head = library.join_chapter([{"chunk_id": "b/c/1", "text": text}], config.CHAPTER_HIT_CHARS)
    assert window_around(text, "drowned lamp seventh stair", config.CHAPTER_HIT_CHARS) == head


def test_the_window_act_stored_is_the_text_observe_is_shown(monkeypatch, tmp_path):
    """ADR-004's equality, on the path #28 adds. `act` writes the window into
    `hits_log`; `observe` cuts `state["hits"]` at the same per-hit limit and
    must arrive at the same string — otherwise a quote copied out of the prompt
    is checked against a passage that moved."""
    text = long_chapter()
    marker = chapter_marker("Some Book", "Chapter 3", "drowned lamp seventh stair")
    result, scratchpad = act_on_chapter(monkeypatch, tmp_path, marker, text)
    logged = result["hits_log"][0]["text"]

    seen = {}
    monkeypatch.setattr(llm, "ask_json",
                        lambda system, user, role: seen.setdefault("user", user) and {}
                        or {"evidence": []})
    nodes.observe({"hits": result["hits"], "question": "q", "current_query": marker,
                   "evidence": [], "empty_streak": 0})

    assert logged == result["hits"][0]["text"]
    assert logged in seen["user"]          # the prompt carries the stored window verbatim
    assert logged in scratchpad.read_text()
    assert NEEDLE in logged


def test_a_quote_from_inside_the_window_confirms_and_one_outside_it_does_not(monkeypatch,
                                                                            tmp_path):
    """The provenance guarantee over a windowed read, both ways round. The
    sentence the window opened on is traceable; a sentence from the part of the
    chapter the window left out is not in any retrieved passage, and the check
    says so rather than trusting the citation."""
    text = long_chapter()
    outside = "The harbour master signed the register in violet ink."
    text = f"{outside} {text}"
    marker = chapter_marker("Some Book", "Chapter 3", "drowned lamp seventh stair")

    result, _ = act_on_chapter(monkeypatch, tmp_path, marker, text)
    hit = result["hits"][0]
    assert outside not in hit["text"]

    def status(quote):
        report = nodes.validate({
            "answer": "…", "hits_log": result["hits_log"],
            "evidence": [{"hit_id": hit["hit_id"], "book": hit["book"],
                          "section": hit["section"], "quote": quote}]})
        return report["provenance"]["items"][0]["status"]

    assert status(NEEDLE) == provenance.CONFIRMED
    assert status(outside) == provenance.BROKEN
    # and the span points at the proof inside the window it was cut from
    start, end = provenance.match_span(hit["text"], NEEDLE)
    assert hit["text"][start:end] == NEEDLE


def test_the_window_stays_inside_the_budget_and_reports_both_ends():
    body = long_chapter(needle_at=0.2)
    already_cut = library.join_chapter([{"chunk_id": "b/c/1", "text": body}], 40_000)
    windowed = window_around(already_cut, "drowned lamp seventh stair", 12_000)

    assert len(windowed) <= 12_000
    assert NEEDLE in windowed
    assert library.chapter_is_cut(windowed)
    # the tail count is the WHOLE remainder of the chapter, the part this
    # window left out and the part the scan already had
    hidden = int(windowed.rsplit("continues: ", 1)[1].split(" ")[0])
    assert hidden > len(body) - 40_000


def test_a_window_at_the_very_end_of_a_chapter_is_still_a_full_window():
    text = long_chapter(needle_at=0.999)
    windowed = window_around(text, "drowned lamp seventh stair", 12_000)
    assert NEEDLE in windowed
    assert 11_000 < len(windowed) <= 12_000
    assert not windowed.rstrip().endswith(library.CUT_MARKER_SUFFIX)  # nothing left after it


def test_a_whole_chapter_that_fits_is_returned_untouched():
    short = f"{FILLER}{NEEDLE}"
    assert window_around(short, "drowned lamp", 12_000) == short


def test_the_window_prefers_the_run_that_covers_most_of_the_query():
    """Distinct words covered, not occurrences: a paragraph repeating one
    common word must not outrank the one place the rare words sit together."""
    decoy = "the lamp. " * 200
    real = "drowned lamp under the seventh stair"
    passage = f"{decoy}{'filler words here. ' * 200}the {real}{' tail words. ' * 200}"
    span = best_match_span(passage, "drowned lamp seventh stair", 600)
    # the span opens on the first word of the query it found, not on the word
    # before it: "the" is not in the query
    assert span and passage[span[0]:span[1]] == real


def test_the_joiner_between_two_chunks_survives_the_window(monkeypatch, tmp_path):
    """A window may span the `[...]` that separates two chunks — it is text on
    the page and the reader is shown it — but it must carry the joiner through,
    because that is what tells the provenance gate the two sides are not
    contiguous in the book. A quote across it is not a quote (ADR-004)."""
    left = f"{FILLER * 20}{NEEDLE}"
    right = "The harbour master signed the register in violet ink." + FILLER * 20
    text = left + provenance.CHUNK_JOINER + right
    marker = chapter_marker("Some Book", "Chapter 3", "drowned lamp violet ink")

    result, _ = act_on_chapter(monkeypatch, tmp_path, marker, text)
    hit = result["hits"][0]
    assert provenance.CHUNK_JOINER in hit["text"]

    def status(quote):
        return nodes.validate({
            "answer": "…", "hits_log": result["hits_log"],
            "evidence": [{"hit_id": hit["hit_id"], "book": hit["book"],
                          "section": hit["section"], "quote": quote}]})["provenance"]["items"][0]["status"]

    assert status(NEEDLE) == provenance.CONFIRMED
    assert status("in violet ink") == provenance.CONFIRMED
    assert status("under the seventh stair. The harbour master") == provenance.BROKEN


# --- the marker that carries the read query ---------------------------------

def test_a_read_query_rides_on_a_marker_of_its_own():
    """Whether a read query is present is answered by the marker NAME, which
    only this code writes — never by a field peeled off the right, which a
    chapter heading could spell (see the probes below)."""
    plain = chapter_marker("A Book — An Author", "Chapter 3")
    assert plain == "__chapter__|A Book — An Author|Chapter 3"
    assert split_read_query(plain) == (plain, "")

    aimed = chapter_marker("A Book — An Author", "Chapter 3", "the drowned lamp")
    assert aimed == "__chapter_q__|the drowned lamp|A Book — An Author|Chapter 3"
    assert split_read_query(aimed) == (plain, "the drowned lamp")


# Two headings a book may really have, and both of them used to be read as the
# grammar's own punctuation: the first handed `act` a read query the model never
# wrote and a section the index does not hold, the second truncated the section
# to "A". The section has to come back out byte for byte, with and without a
# query of its own.
SECTION_PROBES = ["Weird|q=evil query", "A|q=", "Chapter 3 | part two", "q=", "|"]


@pytest.mark.parametrize("section", SECTION_PROBES)
@pytest.mark.parametrize("query", ["", "the drowned lamp"])
def test_a_section_that_spells_the_grammar_round_trips_byte_for_byte(section, query):
    """On the wire the separator is encoded, so the parse cannot be fooled by a
    heading that spells the grammar; off the wire the section is the heading
    again, character for character."""
    action, read_query = split_read_query(chapter_marker("A Book — An Author", section, query))

    assert read_query == query
    assert action.startswith("__chapter__|")
    marker_parts = action.split("|", 2)          # exactly what `act` does
    assert len(marker_parts) == 3
    assert "|" not in marker_parts[2]            # nothing left for the split to take
    assert unescape_marker(marker_parts[1]) == "A Book — An Author"
    assert unescape_marker(marker_parts[2]) == section


BOOK_PROBES = ["A Book — An Author", "Either|Or — S. Kierkegaard", "100%|Pure — A. Nother",
               "Already%7CEncoded — A. Nother"]


@pytest.mark.parametrize("book", BOOK_PROBES)
@pytest.mark.parametrize("section", SECTION_PROBES)
@pytest.mark.parametrize("query", ["", "the drowned lamp"])
def test_every_component_of_a_marker_comes_back_out_as_it_went_in(book, section, query,
                                                                 monkeypatch, tmp_path):
    """Not only the section: a book key may contain "|" too — nothing in the
    front matter, the title line or a file name forbids one — and under a plain
    split it would hand part of the book to the section, so the chapter would be
    looked up in a book the catalogue does not have. The components are
    percent-encoded in the marker and decoded once, in `act`, which is where
    the key has to be the catalogue's own key again."""
    asked = []
    monkeypatch.setattr(nodes, "read_chapter",
                        lambda b, sec, max_chars: (asked.append((b, sec)) or "the chapter text",
                                                   b, "found"))
    llm.reset_usage()
    scratchpad = tmp_path / "scratch.md"
    scratchpad.write_text("")
    result = nodes.act({"current_query": chapter_marker(book, section, query), "steps_taken": 1,
                        "read_chapters": [], "scratchpad_path": str(scratchpad)})

    assert asked == [(book, section)]                     # byte for byte, to the resolver
    assert result["hits"][0]["book"] == book
    assert result["read_chapters"] == [f"{book}|{section}|complete"]


def test_the_coverage_probe_carries_a_piped_book_key_too(monkeypatch, tmp_path):
    """The other marker built from a book key (ADR-013). Same separator, same
    hole, and `act` decodes it in the same place."""
    from ask_your_library import coverage

    book = "Either|Or — S. Kierkegaard"
    probe = coverage.coverage_probe(
        {"mode": "answer", "coverage_probed": False, "steps_taken": 1, "evidence": [],
         "question": f"what does {book} say about the aesthetic life",
         "hits_log": [{"book": book, "hit_id": "s1h1"}], "queries": [],
         "clarify_asked": False, "clarify_chosen": ""}, "enough")
    assert probe.startswith("__book__|")

    searched = []
    monkeypatch.setattr(nodes, "search_both",
                        lambda query, k, book=None: searched.append(book) or [])
    llm.reset_usage()
    scratchpad = tmp_path / "scratch.md"
    scratchpad.write_text("")
    nodes.act({"current_query": probe, "steps_taken": 1, "read_chapters": [],
               "scratchpad_path": str(scratchpad)})

    assert searched == [book]


@pytest.mark.parametrize("length", [900, 1300])
def test_a_chapter_read_logs_where_its_window_sat_in_the_section(monkeypatch, tmp_path, length):
    """#81 (h14): the window's offsets in the section, the section's length —
    including what the scan budget never reached (1300 repetitions is over it) —
    and what the read was aimed at, on the event and in the scratchpad. The
    passage itself is what `window_around` chose; the log only says where."""
    text = long_chapter(length=length)
    marker = chapter_marker("Some Book", "Chapter 3", "drowned lamp seventh stair")

    result, scratchpad = act_on_chapter(monkeypatch, tmp_path, marker, text)

    (window,) = result["chapter_windows"]
    assert window["step"] == 2 and window["section"] == "Chapter 3"
    assert window["looking_for"] == "drowned lamp seventh stair"
    assert window["section_chars"] == len(text)
    assert (window["scanned_chars"] < len(text)) == (length == 1300)
    needle_at = text.index(NEEDLE)
    if length == 900:
        assert window["start"] <= needle_at < needle_at + len(NEEDLE) <= window["end"]
    else:
        # the answer sits past the scan: the read falls back to the head, and
        # the log is what shows the passage was out of reach, not skipped
        assert window["start"] == 0 and needle_at >= window["scanned_chars"]
    # the offsets name the very characters the model was shown
    passage = result["hits"][0]["text"]
    assert text[window["start"]:window["end"]] in passage
    assert window["end"] - window["start"] <= config.CHAPTER_HIT_CHARS
    assert (f"characters {window['start']}-{window['end']} of {len(text)} "
            f"(scanned {window['scanned_chars']}) | looking_for \"drowned lamp seventh stair\"]"
            in scratchpad.read_text())


def test_an_unaimed_read_logs_the_head_window(monkeypatch, tmp_path):
    text = long_chapter()
    result, _ = act_on_chapter(monkeypatch, tmp_path,
                               chapter_marker("Some Book", "Chapter 3", ""), text)
    (window,) = result["chapter_windows"]
    assert window["start"] == 0 and window["looking_for"] == ""
    assert window["section_chars"] == len(text) and window["scanned_chars"] < len(text)
    assert result["hits"][0]["text"].startswith(text[:window["end"]])


def test_a_pipe_in_the_read_query_cannot_eat_the_book_or_the_section():
    marker = chapter_marker("A Book", "Chapter 3", "the lamp | the stair")
    action, query = split_read_query(marker)
    assert action.split("|", 2) == ["__chapter__", "A Book", "Chapter 3"]
    assert query == "the lamp the stair"


def test_a_search_query_is_never_trimmed_by_the_marker_rule():
    assert split_read_query("what happened|q=really") == ("what happened|q=really", "")
    assert split_read_query("__chapter__|A Book|Weird|q=evil query") == (
        "__chapter__|A Book|Weird|q=evil query", "")


def test_a_malformed_query_marker_is_handed_on_whole_and_reads_nothing(monkeypatch, tmp_path):
    """`__chapter_q__|` with nothing after it names no chapter. It must reach
    `act`'s malformed-marker guard, not a read of some invented section."""
    assert split_read_query("__chapter_q__|only a query") == ("__chapter_q__|only a query", "")

    monkeypatch.setattr(nodes, "read_chapter",
                        lambda *a, **k: pytest.fail("no read for a malformed marker"))
    llm.reset_usage()
    scratchpad = tmp_path / "scratch.md"
    scratchpad.write_text("")
    result = nodes.act({"current_query": "__chapter_q__|only a query", "steps_taken": 1,
                        "read_chapters": [], "scratchpad_path": str(scratchpad)})
    assert result["hits"] == [] and result["read_chapters"] == []


def test_reflect_passes_on_what_the_model_is_looking_for(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {
        "decision": "read_chapter", "book": "Some Book", "section": "Chapter 3",
        "looking_for": "the drowned lamp"})
    monkeypatch.setattr(llm, "deadline_passed", lambda: False)
    state = {"evidence": [], "queries": [], "read_chapters": [], "question": "q",
             "mode": "answer", "steps_taken": 1, "empty_streak": 0, "clarify_asked": False}

    marker = nodes.reflect(state)["current_query"]

    assert split_read_query(marker) == ("__chapter__|Some Book|Chapter 3", "the drowned lamp")


def test_a_read_decision_without_the_field_is_the_marker_it_always_was(monkeypatch):
    monkeypatch.setattr(llm, "ask_json", lambda system, user, role: {
        "decision": "read_chapter", "book": "Some Book", "section": "Chapter 3"})
    monkeypatch.setattr(llm, "deadline_passed", lambda: False)
    state = {"evidence": [], "queries": [], "read_chapters": [], "question": "q",
             "mode": "answer", "steps_taken": 1, "empty_streak": 0, "clarify_asked": False}

    assert nodes.reflect(state)["current_query"] == "__chapter__|Some Book|Chapter 3"


# --- what the report can say about all this ---------------------------------

def test_the_counts_tell_a_read_that_aimed_from_one_that_found_nothing(monkeypatch, tmp_path):
    """The three numbers a run has to be able to publish (#28). The middle one
    is the point: whether the model fills the optional field at all is invisible
    in the steps log, and a read path that never aims looks exactly like one
    that aims and misses."""
    text = long_chapter()

    def counts(marker):
        act_on_chapter(monkeypatch, tmp_path, marker, text)    # resets the usage itself
        usage = llm.usage_snapshot()
        return (usage["chapter_reads"], usage["chapter_reads_aimed"],
                usage["chapter_windows_opened"])

    assert counts("__chapter__|Some Book|Chapter 3") == (1, 0, 0)
    assert counts(chapter_marker("Some Book", "Chapter 3",
                                 "drowned lamp seventh stair")) == (1, 1, 1)
    assert counts(chapter_marker("Some Book", "Chapter 3",
                                 "zeppelins over montevideo")) == (1, 1, 0)


def test_a_book_that_talks_about_chapters_beginning_earlier_is_not_service_text():
    """The head marker is in-band text, so a book could in principle spell it.
    The read status is decided on the WHOLE marker, digits and all, which no
    sentence of prose is; an exact imitation is still read as service text, and
    that limit is the one the cut marker at the other end has always had."""
    prose = "[chapter begins earlier: the storm had broken] and the keeper slept."
    assert not library.chapter_is_cut(prose)
    assert provenance._segments(prose)[0].startswith("chapter begins earlier")

    exact = library.head_marker(40) + "and the keeper slept."
    assert library.chapter_is_cut(exact)
    assert "begins earlier" not in provenance._segments(exact)[0]
