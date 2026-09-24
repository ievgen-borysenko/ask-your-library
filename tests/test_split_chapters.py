"""Chapter splitting with part-aware sections, the back-matter cut, and the
`--book` re-ingest guard (pure functions from the ingest script)."""
import importlib.util
import json
import re
from pathlib import Path

import lancedb
import pytest
import yaml

from ask_your_library.index_meta import write_index_meta

REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", REPO / "scripts" / "ingest_demo_corpus.py")
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)

MANIFEST = yaml.safe_load((REPO / "corpus" / "manifest.yaml").read_text(encoding="utf-8"))

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


# --- the contents leftover whose period the contents page dropped -------------

EITHER_RE = r"^CHAPTER [IVX]+\.?$"
PREFACE = "The translator's preface, his introduction and the dedication. " * 6


def test_a_contents_line_without_the_headings_period_is_still_a_leftover():
    """Don Quixote: the contents page's last line is "CHAPTER LII" and every
    real heading is "CHAPTER LII." — on an exact comparison the front matter
    stayed as a 115,506-character section named after the last chapter, listed
    before chapter one, and a request for chapter LII landed on the preface."""
    text = ("CONTENTS\nCHAPTER I\nCHAPTER II\n" + PREFACE
            + "\nCHAPTER I.\n" + BODY + "\nCHAPTER II.\n" + BODY + "\n")
    chapters = ingest.split_chapters(text, EITHER_RE)
    assert chapters == [("CHAPTER I.", BODY.strip()), ("CHAPTER II.", BODY.strip())]


def test_a_contents_line_with_a_period_the_heading_lacks_is_still_a_leftover():
    """The mirror shape, which the strictly-longer branch already caught: the
    contents page punctuates "CHAPTER II." and the book prints "CHAPTER II"."""
    text = ("CONTENTS\nCHAPTER I.\nCHAPTER II.\n" + PREFACE
            + "\nCHAPTER I\n" + BODY + "\nCHAPTER II\n" + BODY + "\n")
    chapters = ingest.split_chapters(text, EITHER_RE)
    assert chapters == [("CHAPTER I", BODY.strip()), ("CHAPTER II", BODY.strip())]


def test_the_generic_path_keeps_the_front_matter_the_demo_path_drops():
    """`drop_toc_leftovers=False` drops nothing, period or no period: in a
    stranger's file the leading section is text, not a contents artifact."""
    text = ("CONTENTS\nCHAPTER I\nCHAPTER II\n" + PREFACE
            + "\nCHAPTER I.\n" + BODY + "\nCHAPTER II.\n" + BODY + "\n")
    chapters = ingest.split_chapters(text, EITHER_RE, min_chapter_chars=0,
                                     keep_preamble=True, drop_toc_leftovers=False)
    assert [t for t, _ in chapters] == [
        "", "CHAPTER I", "CHAPTER II", "CHAPTER I.", "CHAPTER II."]
    assert dict(chapters)["CHAPTER II"] == PREFACE.strip()


# --- back matter: the manifest's end_regex (#82) -------------------------------

NOTES = "[1] The footstool kept bare feet off a floor that was often wet. " * 4
CHAPTERS = "CHAPTER I.\n" + BODY + "\nCHAPTER II.\n" + BODY + "\n"
CHAPTER_RE = r"^CHAPTER [IVX]+\.$"


def test_back_matter_becomes_a_section_of_its_own():
    """There is no end-of-book boundary in the heading regex, so notes and
    appendices were text of the last chapter — cited as that chapter, and read
    instead of it when the chapter was read."""
    chapters = dict(ingest.split_chapters(CHAPTERS + "FOOTNOTES:\n" + NOTES,
                                          CHAPTER_RE, end_re=r"^FOOTNOTES:$"))
    assert list(chapters) == ["CHAPTER I.", "CHAPTER II.", "FOOTNOTES:"]
    assert chapters["CHAPTER II."] == BODY.strip()
    assert chapters["FOOTNOTES:"] == NOTES.strip()


def test_without_an_end_regex_the_back_matter_stays_in_the_last_chapter():
    """A book with no end_regex splits byte for byte as it always did."""
    chapters = ingest.split_chapters(CHAPTERS + "FOOTNOTES:\n" + NOTES, CHAPTER_RE)
    assert [t for t, _ in chapters] == ["CHAPTER I.", "CHAPTER II."]
    assert chapters[-1][1].endswith(NOTES.strip())


def test_a_back_matter_heading_inside_an_earlier_chapter_is_no_boundary():
    """Only the last section is searched, so a heading that reads like back
    matter in the middle of the book cannot cut a chapter in half."""
    text = ("CHAPTER I.\n" + BODY + "\nFOOTNOTES:\n" + NOTES
            + "\nCHAPTER II.\n" + BODY + "\nFOOTNOTES:\n" + NOTES)
    chapters = ingest.split_chapters(text, CHAPTER_RE, end_re=r"^FOOTNOTES:$")
    assert [t for t, _ in chapters] == ["CHAPTER I.", "CHAPTER II.", "FOOTNOTES:"]
    assert "FOOTNOTES:" in dict(chapters)["CHAPTER I."]


def test_an_end_heading_with_nothing_under_it_is_no_boundary():
    """A match on the file's last line is not back matter; cutting there would
    take the line out of the chapter and open an empty section."""
    text = CHAPTERS + "FOOTNOTES:\n"
    assert (ingest.split_chapters(text, CHAPTER_RE, end_re=r"^FOOTNOTES:$")
            == ingest.split_chapters(text, CHAPTER_RE))


def test_a_last_section_that_is_back_matter_only_is_renamed_not_emptied():
    """An edition that prints its notes under a heading of their own: the
    section is the notes, so it takes their name instead of leaving an empty
    chapter behind."""
    text = CHAPTERS + "CHAPTER III.\nFOOTNOTES:\n" + NOTES
    chapters = ingest.split_chapters(text, CHAPTER_RE, end_re=r"^FOOTNOTES:$")
    assert [t for t, _ in chapters] == ["CHAPTER I.", "CHAPTER II.", "FOOTNOTES:"]
    assert chapters[-1][1] == NOTES.strip()


def test_end_title_names_the_section_when_the_heading_names_only_its_first_item():
    """Ivanhoe's apparatus opens with "NOTE TO CHAPTER I." and holds the notes
    to ten chapters: under the heading's own name, a quote from the note to
    chapter XLI would be cited as a note to chapter I."""
    text = CHAPTERS + "NOTE TO CHAPTER I.\n" + NOTES
    chapters = ingest.split_chapters(text, CHAPTER_RE, end_re=r"^NOTE TO CHAPTER I\.$",
                                     end_title="NOTES")
    assert [t for t, _ in chapters] == ["CHAPTER I.", "CHAPTER II.", "NOTES"]
    # the heading is nobody's title now, so it is kept as the section's first
    # line rather than dropped with it
    assert chapters[-1][1] == "NOTE TO CHAPTER I.\n" + NOTES.strip()


def test_the_back_matter_section_carries_no_part_prefix():
    """An appendix at the end of the last volume is the book's, not that
    volume's: the chapters keep their "VOLUME — CHAPTER" names and the cut
    section is named for its heading alone."""
    text = ("VOLUME I\nCHAPTER I.\n" + BODY + "\nVOLUME II\nCHAPTER I.\n" + BODY
            + "\nFOOTNOTES:\n" + NOTES)
    chapters = ingest.split_chapters(text, CHAPTER_RE, r"^(VOLUME [IV]+)$",
                                     end_re=r"^FOOTNOTES:$")
    assert [t for t, _ in chapters] == [
        "VOLUME I — CHAPTER I.", "VOLUME II — CHAPTER I.", "FOOTNOTES:"]


def book_entry(book_id: str) -> dict:
    return next(e for e in MANIFEST["books"] if e["id"] == book_id)


def test_an_end_regex_that_cut_nothing_stops_the_prepare_stage():
    """The cut is silent by construction, so a manifest regex that no longer
    matches — a typo, an edition that renamed its appendix — would prepare the
    book with its notes back inside the last chapter and say nothing."""
    text = CHAPTERS + "FOOTNOTES:\n" + NOTES
    uncut = ingest.split_chapters(text, CHAPTER_RE)
    entry = {"id": "book", "end_regex": r"^NOTES AND QUERIES$"}
    with pytest.raises(SystemExit) as raised:
        ingest.cut_back_matter_or_exit(entry, uncut)
    assert "cut nothing" in str(raised.value)

    # a heading that matches only outside the last chapter: the cut cannot
    # happen there, and the back matter is still somebody's chapter
    mid_book = "CHAPTER I.\nFOOTNOTES:\n" + NOTES + "\nCHAPTER II.\n" + BODY
    entry = {"id": "book", "end_regex": r"^FOOTNOTES:$"}
    with pytest.raises(SystemExit):
        ingest.cut_back_matter_or_exit(entry, ingest.split_chapters(mid_book, CHAPTER_RE))

    # and the cut that did happen passes, under the heading's name or end_title
    for entry in ({"id": "book", "end_regex": r"^FOOTNOTES:$"},
                  {"id": "book", "end_regex": r"^FOOTNOTES:$", "end_title": "NOTES"}):
        cut = ingest.cut_back_matter_or_exit(entry, uncut)
        assert cut[-1][0] == entry.get("end_title", "FOOTNOTES:")
        assert cut[:-1] == [(t, b) for t, b in uncut[:-1]] + [("CHAPTER II.", BODY.strip())]


def test_a_cut_that_did_not_happen_is_not_read_off_the_section_titles():
    """The guard asks the cut whether it moved anything; asking the RESULT —
    "is the last section named what the manifest asked for?" — answers yes to a
    book where the end_regex matched nothing and `end_title` happens to be the
    last chapter's own name."""
    mid_book = "CHAPTER I.\nFOOTNOTES:\n" + NOTES + "\nCHAPTER II.\n" + BODY
    entry = {"id": "book", "end_regex": r"^FOOTNOTES:$", "end_title": "CHAPTER II."}
    sections = ingest.split_chapters(mid_book, CHAPTER_RE)
    assert sections[-1][0] == entry["end_title"]      # the collision
    with pytest.raises(SystemExit) as raised:
        ingest.cut_back_matter_or_exit(entry, sections)
    assert "cut nothing" in str(raised.value)


def test_a_book_whose_chapter_regex_matched_nothing_is_not_cut_at_all():
    """With no chapter found the whole text is one untitled section, and the
    back-matter heading would be found inside it: the cut would succeed and the
    real fault — the chapter regex — would go unsaid."""
    text = "No headings here.\n" + BODY + "\nFOOTNOTES:\n" + NOTES
    sections = ingest.split_chapters(text, CHAPTER_RE)
    assert sections == [("", text)]
    with pytest.raises(SystemExit) as raised:
        ingest.cut_back_matter_or_exit({"id": "book", "end_regex": r"^FOOTNOTES:$"}, sections)
    assert "chapter regex matched nothing" in str(raised.value)


def test_a_positional_call_written_before_end_re_still_means_what_it_meant():
    """`end_re` and `end_title` are keyword-only and come after the options
    this function already had, so the generic ingest's fully positional call
    (min_chapter_chars=0, keep_preamble=True, drop_toc_leftovers=False) cannot
    silently bind a regex to a size limit."""
    text = "Front matter of this edition.\n\nCHAPTER I.\nOne short line.\n"
    assert ingest.split_chapters(text, CHAPTER_RE, None, 0, True, False) == [
        ("", "Front matter of this edition."), ("CHAPTER I.", "One short line.")]


def test_the_napoleon_regex_reads_the_editions_misprinted_chapter_number():
    """The source prints "CHAPTER XXYI." for XXVI, which no chapter regex
    matched, so volume II's chapters XXV and XXVI were one section. The
    manifest regex covers the misprint, and still volume I's "CHAPTER 1", the
    one heading this edition numbers in arabic. The text itself is not edited:
    the section keeps the number the page carries."""
    regex = book_entry("napoleon-memoirs")["chapter_regex"]
    text = ("CHAPTER 1\n" + BODY + "\nCHAPTER XXV.\n" + BODY
            + "\nCHAPTER XXYI.\n" + BODY + "\nCHAPTER XXVII.\n" + BODY)
    assert [t for t, _ in ingest.split_chapters(text, regex)] == [
        "CHAPTER 1", "CHAPTER XXV.", "CHAPTER XXYI.", "CHAPTER XXVII."]


@pytest.mark.skipif(not (ingest.PREPARED_DIR.exists()
                         and any(ingest.PREPARED_DIR.glob("*.json"))),
                    reason="the prepared demo texts are not in the repository (data/prepared)")
def test_every_end_regex_is_the_back_matter_heading_and_nothing_else():
    """An end_regex that also matches earlier in its book would cut a chapter
    in half, and the prepared texts are the only place that can be checked —
    they are not committed, so this runs where they are.

    Title and text are searched together, which makes the check true before the
    re-prepare and after it: the heading is a line of the last chapter until
    the book is prepared again, and the name of the last section afterwards."""
    checked = 0
    for entry in MANIFEST["books"]:
        prepared = ingest.PREPARED_DIR / f"{entry['id']}.json"
        if not entry.get("end_regex") or not prepared.exists():
            continue
        checked += 1
        sections = json.loads(prepared.read_text(encoding="utf-8"))["chapters"]
        blocks = [f"{c['title']}\n{c['text']}" for c in sections]
        found = [i for i, block in enumerate(blocks)
                 if re.search(entry["end_regex"], block, re.M)]
        assert found == [len(blocks) - 1], (
            f"{entry['id']}: end_regex {entry['end_regex']!r} matches in sections "
            f"{[sections[i]['title'] for i in found]}, not only in the last one")
        assert len(re.findall(entry["end_regex"], blocks[-1], re.M)) == 1, entry["id"]
    assert checked, "no prepared text for any book with an end_regex"
