"""The stamp is checked against the rows before it is written (#75).

`--stage stamp-meta --chunker current` writes an operator's assertion into
`_index_meta`, and that field is what `ayl-add` refuses a write on. On
2026-09-17 it was written onto a table the named chunker had never touched: the
ingest before it had exited 1 with nothing prepared, the runbook stamped
anyway, `--doctor` said "no drift", and an hour of measurement ran on an index
that claimed one chunker and held another.

Four things are pinned here, one per proposal in the issue:

1. the sample before the vouching — both refusals, with their numbers, and a
   stamp that is legitimately allowed to go through;
2. `--doctor` reading the chunk lengths against the stamped chunker;
3. the documented procedure stopping on a failed ingest instead of stamping;
4. `--stage ingest` exiting non-zero on "nothing prepared", saying where it
   looked.

No network and no embedder: the tables are tiny LanceDB tables under tmp_path,
built either by the real ingest with a fake embedder or by hand where the point
is rows this code would never write.
"""
import importlib.util
import json
import sys
from pathlib import Path

import lancedb
import pytest

from ask_your_library.index_meta import read_index_meta, write_index_meta
from ask_your_library.ingest.chunking import (CHUNKER_VERSION, TRANSCRIPT_CEILING_CHARS,
                                              TRANSCRIPT_MAX_CHARS, transcript_chunk_floor)
from ask_your_library.ingest.doctor import check_ledger

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", REPO / "scripts" / "ingest_demo_corpus.py")
demo = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("ingest_demo_corpus", demo)
_spec.loader.exec_module(demo)

TABLES = ["transcripts_ollama", "cards_ollama"]
MOBY = "Moby Dick — Herman Melville"
# Long enough that the packer cuts each chapter into several chunks, so a real
# ingest here has the shape a real ingest has.
PARA = ("The lighthouse keeper counted the ships that passed the headland. "
        "He wrote each name in a ledger bound in green cloth. ") * 40


class FakeEmbedder:
    name = "ollama"
    model = "fake-embed"
    dims = 4

    def embed_docs(self, texts):
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]

    def embed_query(self, text):
        return self.embed_docs([text])[0]


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """A prepared-texts directory with one book in it, and the demo script
    pointed at it and at a tmp index. The prepared JSON is written for real so
    that the row-count check reads the same files the ingest would."""
    folder = tmp_path / "prepared"
    folder.mkdir()
    monkeypatch.setattr(demo, "PREPARED_DIR", folder)
    monkeypatch.setattr(demo, "DB_PATH", tmp_path / "db")
    monkeypatch.setattr(demo, "get_embedder", lambda backend: FakeEmbedder())
    (folder / "moby-dick.json").write_text(json.dumps({
        "note": "moby-dick", "book": MOBY, "source": "pg:1",
        "chapters": [{"title": "Chapter 1", "text": PARA},
                     {"title": "Chapter 2", "text": PARA}]}), encoding="utf-8")
    return tmp_path / "db"


def hand_built_table(db_path, texts, book=MOBY, chunker=None):
    """A transcripts table whose rows are whatever the test says they are —
    the one thing a test of this must be able to write, because the rows that
    matter are rows this code would never produce."""
    db = lancedb.connect(db_path)
    db.create_table("transcripts_ollama", [
        {"chunk_id": f"{book}/{i}", "note": "moby-dick", "book": book, "source": "transcript",
         "section": f"Chapter {i}", "text": text, "vector": [0.1, 0.2, 0.3, 0.4]}
        for i, text in enumerate(texts, 1)])
    if chunker is not None:
        write_index_meta(db, "transcripts_ollama", "ollama", "fake-embed", 4, chunker=chunker)
    return db


def stamped_chunker(db_path, table="transcripts_ollama"):
    meta = read_index_meta(lancedb.connect(db_path), table)
    return None if meta is None else (meta.get("chunker") or "")


# --- 1. the sample before the vouching --------------------------------------

def test_a_chunk_longer_than_the_packer_can_return_refuses_the_stamp(prepared):
    """`sentence-pack-1` packed to 4,000 characters with no sentence cap, so
    its rows are longer than any arrangement of this packer's three numbers can
    produce. That is the whole test: not "unusual", but impossible."""
    over = TRANSCRIPT_CEILING_CHARS + 100
    hand_built_table(prepared, ["a" * over, "b" * 500])

    with pytest.raises(SystemExit) as raised:
        demo.stamp_existing_tables("ollama", "current", ["moby-dick"])

    message = str(raised.value)
    assert f"refusing to stamp transcripts_ollama with chunker {CHUNKER_VERSION!r}" in message
    assert f"{TRANSCRIPT_CEILING_CHARS:,}" in message and f"{over:,}" in message
    assert "--chunker <version>" in message and "--stage ingest" in message
    # and nothing was written: a refused stamp leaves the fingerprint as it was
    assert stamped_chunker(prepared) is None


def test_a_row_count_the_prepared_text_cannot_fit_into_refuses_the_stamp(prepared):
    """#75's shape: the table held the 7,285 rows of a coarser chunker while
    the prepared corpus needed about 11,300 of this one. Expressed in the
    chunker's own numbers — no chunk holds more than its ceiling, so fewer rows
    than `transcript_chunk_floor` cannot hold the text at all."""
    chars = 2 * len(PARA)
    floor = transcript_chunk_floor(chars)
    hand_built_table(prepared, ["short chunk"] * (floor - 2))

    with pytest.raises(SystemExit) as raised:
        demo.stamp_existing_tables("ollama", "current", ["moby-dick"])

    message = str(raised.value)
    assert f"refusing to stamp transcripts_ollama with chunker {CHUNKER_VERSION!r}" in message
    assert f"{TRANSCRIPT_MAX_CHARS:,} characters" in message
    assert f"{MOBY} has {floor - 2:,}, needs {floor:,}" in message
    assert stamped_chunker(prepared) is None


def test_a_table_this_chunker_really_built_is_stamped(prepared):
    """The other half of a refusal that is worth anything: the legitimate case
    goes through. An index built by this very packer and then left unstamped —
    which is every index built before the field existed — is exactly what the
    command is for."""
    demo.ingest_transcripts_table("ollama", None, ["moby-dick"])
    db = lancedb.connect(prepared)
    write_index_meta(db, "transcripts_ollama", "ollama", "fake-embed", 4, chunker="")
    assert stamped_chunker(prepared) == ""

    demo.stamp_existing_tables("ollama", "current", ["moby-dick"])

    assert stamped_chunker(prepared) == CHUNKER_VERSION


def test_naming_the_old_version_explicitly_is_not_sampled(prepared):
    """The way out for an operator who really means the old chunker. Nothing
    here knows what `sentence-pack-1` would have produced, so there is nothing
    to check the claim against and it is taken as what it is: an assertion
    about the past."""
    hand_built_table(prepared, ["a" * (TRANSCRIPT_CEILING_CHARS + 100)])

    demo.stamp_existing_tables("ollama", "sentence-pack-1", ["moby-dick"])

    assert stamped_chunker(prepared) == "sentence-pack-1"


def test_an_index_of_other_books_is_not_judged_by_this_corpus_row_count(prepared):
    """A second index (the engineer's shelf has one) shares no book key with
    the prepared texts, so the count has nothing to compare with and says so
    rather than refusing on numbers that are not about it."""
    hand_built_table(prepared, ["a chunk of text"] * 3, book="Designing Data — M. Kleppmann")

    demo.stamp_existing_tables("ollama", "current", ["moby-dick"])

    assert stamped_chunker(prepared) == CHUNKER_VERSION


# --- 2. the doctor reads the lengths ----------------------------------------

def test_the_doctor_reports_the_distribution_and_flags_the_mismatch_as_drift(prepared):
    db = hand_built_table(prepared, ["a" * (TRANSCRIPT_CEILING_CHARS + 100), "b" * 900],
                          chunker=CHUNKER_VERSION)

    report = check_ledger(db, TABLES)

    assert not report.ok
    assert report.length_drift and CHUNKER_VERSION in report.length_drift[0]
    lines = report.lines()
    assert any(line.startswith("  CHUNK LENGTH") for line in lines)
    assert any("chunks: transcripts_ollama: 2 row(s), median" in line for line in lines)
    assert any("longest 2,740 characters" in line for line in lines)


def test_the_doctor_reports_the_distribution_of_a_table_that_agrees(prepared):
    demo.ingest_transcripts_table("ollama", None, ["moby-dick"])
    db = lancedb.connect(prepared)

    report = check_ledger(db, TABLES)

    assert not report.length_drift
    assert any("chunks: transcripts_ollama:" in line and f"chunker {CHUNKER_VERSION} packs to"
               in line for line in report.lines())


def test_the_doctor_does_not_measure_rows_against_another_chunkers_numbers(prepared):
    """A table stamped `sentence-pack-1` is already reported as a version
    mismatch, in the only terms that are true — the two names differ. Measuring
    its rows against THIS packer's ceiling would add a second sentence saying
    the same thing in numbers that were never its own."""
    db = hand_built_table(prepared, ["a" * (TRANSCRIPT_CEILING_CHARS + 100)],
                          chunker="sentence-pack-1")

    report = check_ledger(db, TABLES)

    assert not report.length_drift
    assert report.version_mismatches


# --- 3. the documented procedure stops on a failed ingest -------------------

def test_the_upgrading_page_says_the_chain_stops_on_a_failed_ingest():
    page = (REPO / "docs" / "upgrading.md").read_text(encoding="utf-8")
    assert "A failed ingest stops the chain" in page
    assert "--stage ingest || exit 1" in page


# --- 4. nothing prepared: non-zero, and where it looked ---------------------

def test_an_ingest_with_nothing_prepared_exits_non_zero_and_says_where_it_looked(prepared):
    (demo.PREPARED_DIR / "moby-dick.json").unlink()

    with pytest.raises(SystemExit) as raised:
        demo.ingest_transcripts_table("ollama", None, ["moby-dick"])

    # A string exit code is status 1 to the interpreter, which is what the next
    # line of a runbook reads.
    assert isinstance(raised.value.code, str) and raised.value.code
    assert "nothing prepared" in raised.value.code
    assert "the directory does not exist" not in raised.value.code   # it exists, it is empty
    assert str(demo.PREPARED_DIR) in raised.value.code


def test_the_path_it_looked_in_is_relative_to_the_checkout():
    """The default, unpatched: `data/prepared` is what the runbooks and the
    docs spell, and an absolute path here would name the machine it ran on."""
    assert demo.prepared_where() == "data/prepared/ (relative to the checkout)"
    assert "looked in data/prepared/ (relative to the checkout)" in demo.nothing_prepared(None)
