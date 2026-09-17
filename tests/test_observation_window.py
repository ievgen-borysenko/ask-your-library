"""The chunk and the observation window are one decision (#28, ADR-025).

Two halves, and they meet in the middle:

* the CHUNKER packs a transcript chunk to less than the window `observe` reads,
  so a search hit arrives whole and nothing is ranked that the model never
  sees. Measured here against the audio transcripts that are actually in this
  repository — `corpus/prepared-audio/` is where the 10,140-character
  "sentence" lives, so the pathological case is a fixture and not a story.
* a CHAPTER READ that says what it is looking for is cut around the match
  instead of at the head — the second half of the same decision, and the tests
  for it land with it.

No LLM, no network, no index: the chunker is a pure function.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from ask_your_library import config
from ask_your_library.ingest import pack_sentences, split_sentences
from ask_your_library.ingest.chunking import (MAX_SENTENCE_CHARS, TRANSCRIPT_MAX_CHARS,
                                              TRANSCRIPT_TARGET_CHARS, cap_sentence)

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
    chunks = pack_sentences([run])
    assert all(len(c) <= TRANSCRIPT_MAX_CHARS for c in chunks)


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
