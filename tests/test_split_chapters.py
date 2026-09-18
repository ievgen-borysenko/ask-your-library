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


def test_a_part_without_chapters_is_its_own_section():
    """Dumas's Celebrated Crimes: "*THE CENCI—1598*" has no CHAPTER headings, and
    the whole essay used to run on inside "THE BORGIAS — CHAPTER XVI"."""
    cenci = "Should you ever go to Rome and visit the villa Pamphili. " * 8
    text = ("*THE BORGIAS*\n\nCHAPTER I\n" + BODY + "\nCHAPTER II\n" + BODY + "\n\n"
            "*THE CENCI—1598*\n\n" + cenci + "\n\n*MARY STUART*\n\nCHAPTER I\n" + BODY)
    chapters = dict(ingest.split_chapters(text, r"^CHAPTER [IVX]+$", r"^\*([^*]+)\*$"))
    assert list(chapters) == ["THE BORGIAS — CHAPTER I", "THE BORGIAS — CHAPTER II",
                              "THE CENCI—1598", "MARY STUART — CHAPTER I"]
    assert chapters["THE BORGIAS — CHAPTER II"] == BODY.strip()
    # the next part's bare heading line trails the essay, as a part heading
    # without text of its own always trailed the chapter before it
    assert chapters["THE CENCI—1598"] == cenci + "\n\n*MARY STUART*"


def test_a_parts_lead_in_before_its_first_chapter_is_its_own_section():
    prologue = "PROLOGUE. On the 8th of April, 1492, in a bedroom. " * 6
    text = ("OF BENEFITS.\n\nCHAPTER I.\n" + BODY + "\n"
            "OF ANGER.\n\n" + prologue + "\nCHAPTER I.\n" + BODY + "\n")
    chapters = dict(ingest.split_chapters(text, r"^CHAPTER [IVX]+\.$", r"^(OF [A-Z]+)\.$"))
    assert list(chapters) == ["OF BENEFITS — CHAPTER I.", "OF ANGER", "OF ANGER — CHAPTER I."]
    assert chapters["OF BENEFITS — CHAPTER I."] == BODY.strip()
    assert chapters["OF ANGER"] == prologue.strip()


def test_contents_page_part_lines_do_not_open_sections():
    """Romeo and Juliet's contents page lists "ACT II" above an indented scene
    list long enough to pass the size filter; only the last "ACT II" is the act."""
    scenes = "".join(f"     Scene {n}. A street in Verona, a long description.\n" for n in range(8))
    chorus = "CHORUS.\nNow old desire doth in his deathbed lie. " * 6
    text = ("Contents\n\nACT I\n" + scenes + "\nACT II\n" + scenes + "\n\n"
            "ACT I\nSCENE I. A public place.\n" + BODY + "\n"
            "ACT II\n" + chorus + "\nSCENE I. A garden.\n" + BODY + "\n")
    chapters = ingest.split_chapters(text, r"^SCENE [IVX]+\..*$", r"^(ACT [IV]+)$")
    assert [t for t, _ in chapters] == [
        "ACT I — SCENE I. A public place.", "ACT II", "ACT II — SCENE I. A garden."]


def test_contents_part_entries_after_an_uppercase_contents_heading_open_no_section():
    """A contents page whose first line matches the chapter regex is not the
    first real chapter: the long part entries under it are contents too."""
    synopsis = "     In which the travellers cross the mountains, a long synopsis.\n" * 5
    lead_in = "The second part opens with a long lead-in of its own. " * 6
    book = ("PART ONE\n\nCHAPTER I.\n" + BODY + "\nPART TWO\n\n" + lead_in
            + "\nCHAPTER II.\n" + BODY + "\nPART THREE\n\nCHAPTER III.\n" + BODY + "\n")
    contents = ("Contents\n\nPART ONE\nCHAPTER I. The Voyage Out\n\n"
                "PART TWO\n" + synopsis + "\nPART THREE\n" + synopsis + "\n\n")
    split = lambda text: ingest.split_chapters(text, r"^CHAPTER [IVX]+\..*$",
                                               r"^(PART [A-Z]+)$")
    assert split(contents + book) == split(book)
    assert [t for t, _ in split(book)] == [
        "PART ONE — CHAPTER I.", "PART TWO", "PART TWO — CHAPTER II.",
        "PART THREE — CHAPTER III."]


def test_a_part_heading_matched_mid_line_keeps_the_rest_of_its_line_out_of_the_body():
    intro = "Lemuel Gulliver sets out from Bristol on the Antelope. " * 6
    text = ("PART I. A VOYAGE TO LILLIPUT.\n\nCHAPTER I.\n" + BODY + "\n"
            "PART II. A VOYAGE TO BROBDINGNAG.\n\n" + intro + "\nCHAPTER I.\n" + BODY + "\n")
    chapters = dict(ingest.split_chapters(text, r"^CHAPTER [IVX]+\.$",
                                          r"^(PART [IV]+)\. A VOYAGE TO"))
    assert chapters["PART II"] == intro.strip()


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


def test_two_real_parts_with_the_same_name_lose_no_chapter():
    """Two plays in one file, each with an ACT I: every scene survives."""
    chorus = "CHORUS. Two households, both alike in dignity. " * 6
    text = ("ACT I\nSCENE I. a\n" + BODY + "\nACT II\n" + chorus + "\nSCENE I. b\n" + BODY
            + "\nACT I\n" + chorus + "\nSCENE I. c\n" + BODY + "\n")
    chapters = ingest.split_chapters(text, r"^SCENE [IVX]+\..*$", r"^(ACT [IV]+)$")
    assert [t for t, _ in chapters] == [
        "ACT I — SCENE I. a", "ACT II", "ACT II — SCENE I. b", "ACT I", "ACT I — SCENE I. c"]


def test_a_short_part_lead_in_stays_in_the_previous_chapter():
    """An epigraph under a part heading is too short to be a section; it stays
    where it always was instead of vanishing."""
    text = ("PART I\n\nCHAPTER I\n" + BODY + "\nPART II\n\n'All is vanity.'\n\n"
            "CHAPTER I\n" + BODY + "\n")
    chapters = dict(ingest.split_chapters(text, r"^CHAPTER [IVX]+$", r"^(PART [IV]+)$"))
    assert list(chapters) == ["PART I — CHAPTER I", "PART II — CHAPTER I"]
    assert chapters["PART I — CHAPTER I"].endswith("PART II\n\n'All is vanity.'")


def test_a_part_lead_in_before_the_first_chapter_does_not_shield_a_contents_leftover():
    lead_in = "The first part opens with a long lead-in of its own. " * 6
    front = "Front matter of the edition, a dedication and a preface. " * 6
    text = ("PART ONE\n" + lead_in + "\nCHAPTER II. The End\n" + front
            + "\nCHAPTER I.\n" + BODY + "\nCHAPTER II.\n" + BODY + "\n")
    chapters = ingest.split_chapters(text, r"^CHAPTER [IVX]+\..*$", r"^(PART [A-Z]+)$")
    assert [t for t, _ in chapters] == ["PART ONE — CHAPTER I.", "PART ONE — CHAPTER II."]
