"""Chapter splitting with part-aware sections, and the `--book` re-ingest guard
(pure functions from the ingest script)."""
import importlib.util
from pathlib import Path

import lancedb
import pytest

from ask_your_library.index_meta import write_index_meta

spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", Path(__file__).resolve().parents[1] / "scripts" / "ingest_demo_corpus.py")
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)

BODY = "Lorem ipsum dolor sit amet. " * 12   # > MIN_CHAPTER_CHARS
TEXT = (
    "CONTENTS\nCHAPTER I.\nCHAPTER II.\n\n"            # contents lines: tiny bodies, dropped
    "OF BENEFITS.\n\nCHAPTER I.\n" + BODY + "\nCHAPTER II.\n" + BODY + "\n"
    "OF ANGER.\n\nCHAPTER I.\n" + BODY + "\nCHAPTER II.\n" + BODY + "\n"
)


def test_a_downloaded_chapter_is_named_after_its_number_not_after_the_remote_file():
    """The file name in an archive.org item's metadata is not ours, and it was
    joined straight onto the download directory: "../" or an absolute path in
    it would have decided where the mp3 landed. The number decides now; the
    remote name is only used in the URL."""
    item_dir = Path("/tmp/ayl-item")
    hostile = [(1, "../../../etc/cron.d/evil.mp3"), (2, "/etc/passwd"), (12, "ch_12_64kb.mp3")]
    names = [ingest.local_chapter_name(number, ".mp3") for number, _ in hostile]
    assert names == ["ch01.mp3", "ch02.mp3", "ch12.mp3"]
    assert all((item_dir / name).parent == item_dir for name in names)
    assert ingest.local_chapter_name(3, ".txt") == "ch03.txt"


def test_repeated_chapter_titles_get_their_part():
    chapters = ingest.split_chapters(TEXT, r"^CHAPTER [IVX]+\.$", r"^(OF [A-Z]+)\.$")
    assert [t for t, _ in chapters] == [
        "OF BENEFITS — CHAPTER I.", "OF BENEFITS — CHAPTER II.",
        "OF ANGER — CHAPTER I.", "OF ANGER — CHAPTER II."]


def test_without_part_regex_titles_are_unchanged():
    chapters = ingest.split_chapters(TEXT, r"^CHAPTER [IVX]+\.$")
    assert [t for t, _ in chapters] == ["CHAPTER I.", "CHAPTER II.", "CHAPTER I.", "CHAPTER II."]


def test_parts_use_heading_offsets_not_body_search():
    """Two chapters with byte-identical bodies must still land in their own parts."""
    same = "Identical body text repeated verbatim across parts. " * 6
    text = ("PART ONE\nCHAPTER I.\n" + same + "\nPART TWO\nCHAPTER I.\n" + same + "\n")
    chapters = ingest.split_chapters(text, r"^CHAPTER [IVX]+\.$", r"^(PART (?:ONE|TWO))$")
    assert [t for t, _ in chapters] == ["PART ONE — CHAPTER I.", "PART TWO — CHAPTER I."]


# --- the --book partial re-ingest guard ---------------------------------------

class FakeEmbedder:
    """Deterministic 4-dim vectors: no Ollama, no OpenRouter, no network."""
    def __init__(self, model="fake-embed", dims=4):
        self.model, self.dims = model, dims

    def embed_docs(self, texts):
        return [[1.0, 0.5, 0.25, 0.125] for _ in texts]


def a_table(tmp_path, dims=4):
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama",
                    [{"chunk_id": "x", "note": "n", "book": "b", "source": "s",
                      "section": "", "text": "t", "vector": [0.0] * dims}])
    return db


def test_partial_reingest_into_an_unstamped_table_is_refused(tmp_path):
    # check_index alone lets this through — same dims, no fingerprint — and the
    # upsert would then mix two embedding models and stamp the result.
    db = a_table(tmp_path)
    with pytest.raises(SystemExit) as raised:
        ingest.refuse_unsafe_partial_reingest(db, "transcripts_ollama", FakeEmbedder())
    assert "no embedding fingerprint" in str(raised.value)
    assert "stamp-meta" in str(raised.value)


def test_partial_reingest_into_a_table_built_by_another_model_is_refused(tmp_path):
    db = a_table(tmp_path)
    write_index_meta(db, "transcripts_ollama", "ollama", "model-a", 4)
    with pytest.raises(SystemExit) as raised:
        ingest.refuse_unsafe_partial_reingest(db, "transcripts_ollama",
                                              FakeEmbedder("model-b"))
    assert "model-a" in str(raised.value)


def test_partial_reingest_into_a_matching_table_is_allowed(tmp_path):
    db = a_table(tmp_path)
    write_index_meta(db, "transcripts_ollama", "ollama", "fake-embed", 4)
    assert ingest.refuse_unsafe_partial_reingest(db, "transcripts_ollama",
                                                 FakeEmbedder()) is None
