"""The demo corpus ingest writes the same ledger `ayl-add` does.

The two paths mint keys differently (a manifest id against a file name) and
publish differently (a staged whole-table rebuild against per-book delete and
append), but a book is a book: one ledger row, one minted id, `book_id` on
every row, and the chunker stamped on the table. Without this the demo index
would be the one index the reconciliation in `doctor` cannot check.

The prepared texts are not in the repository, so the documents are built here.
What is exercised is the ingest function itself, with the embedder faked.
"""
import importlib.util
import sys
from pathlib import Path

import lancedb
import pytest

from ask_your_library.index_meta import SCHEMA_VERSION, read_index_meta
from ask_your_library.ingest.ledger import CHUNKER_VERSION, open_ledger

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", REPO / "scripts" / "ingest_demo_corpus.py")
demo = importlib.util.module_from_spec(_spec)
sys.modules["ingest_demo_corpus"] = demo
_spec.loader.exec_module(demo)

PARA = ("The lighthouse keeper counted the ships that passed the headland. "
        "He wrote each name in a ledger bound in green cloth. ") * 3


class FakeEmbedder:
    name = "ollama"
    model = "fake-embed"
    dims = 4

    def embed_docs(self, texts):
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]

    def embed_query(self, text):
        return self.embed_docs([text])[0]


def doc(note, title, author, chapters=("Chapter 1", "Chapter 2")):
    return {"note": note, "book": f"{title} — {author}", "source": "pg:1",
            "chapters": [{"title": t, "text": PARA} for t in chapters]}


@pytest.fixture
def demo_index(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "DB_PATH", tmp_path / "db")
    monkeypatch.setattr(demo, "get_embedder", lambda backend: FakeEmbedder())
    monkeypatch.setattr(demo, "prepared_docs", lambda ids: [
        doc("moby-dick", "Moby Dick", "Herman Melville"),
        doc("emma", "Emma", "Jane Austen")])
    return tmp_path / "db"


def test_the_demo_ingest_writes_a_ledger_row_and_a_book_id_per_book(demo_index):
    demo.ingest_transcripts_table("ollama", None, ["moby-dick", "emma"])

    db = lancedb.connect(demo_index)
    entries = {row["key"]: row for row in open_ledger(db).all_rows()}
    assert sorted(entries) == ["Emma — Jane Austen", "Moby Dick — Herman Melville"]
    moby = entries["Moby Dick — Herman Melville"]
    assert moby["status"] == "indexed" and moby["rows"] > 0
    assert moby["source_ref"] == "manifest:moby-dick"
    assert moby["chunker"] == CHUNKER_VERSION and moby["embedding_model"] == "fake-embed"
    assert moby["fts_seconds"] >= 0

    ids = {key: row["book_id"] for key, row in entries.items()}
    rows = db.open_table("transcripts_ollama").search().limit(1000).to_list()
    assert {r["book_id"] for r in rows} == set(ids.values())
    for row in rows:
        assert row["book_id"] == ids[row["book"]]


def test_the_demo_ingest_stamps_the_chunker_and_the_schema_version(demo_index):
    demo.ingest_transcripts_table("ollama", None, ["moby-dick", "emma"])
    meta = read_index_meta(lancedb.connect(demo_index), "transcripts_ollama")
    assert meta["chunker"] == CHUNKER_VERSION and meta["schema_version"] == SCHEMA_VERSION


def test_a_second_full_rebuild_keeps_every_book_id(demo_index):
    demo.ingest_transcripts_table("ollama", None, ["moby-dick", "emma"])
    before = {row["key"]: row["book_id"] for row in open_ledger(
        lancedb.connect(demo_index)).all_rows()}
    demo.ingest_transcripts_table("ollama", None, ["moby-dick", "emma"])
    after = {row["key"]: row["book_id"] for row in open_ledger(
        lancedb.connect(demo_index)).all_rows()}
    assert after == before


def test_the_single_book_upsert_path_keeps_the_book_id_and_the_other_book(demo_index,
                                                                          monkeypatch):
    demo.ingest_transcripts_table("ollama", None, ["moby-dick", "emma"])
    db = lancedb.connect(demo_index)
    before = {row["key"]: row["book_id"] for row in open_ledger(db).all_rows()}

    monkeypatch.setattr(demo, "prepared_docs", lambda ids: [
        doc("moby-dick", "Moby Dick", "Herman Melville", ("Chapter 1",))])
    demo.ingest_transcripts_table("ollama", "moby", ["moby-dick"])

    db = lancedb.connect(demo_index)
    assert {row["key"]: row["book_id"] for row in open_ledger(db).all_rows()} == before
    rows = db.open_table("transcripts_ollama").search().limit(1000).to_list()
    assert {r["book"] for r in rows} == {"Moby Dick — Herman Melville", "Emma — Jane Austen"}
    assert len({r["chunk_id"] for r in rows}) == len(rows)


def test_a_single_book_reingest_into_a_pre_ledger_table_migrates_it_first(demo_index,
                                                                          monkeypatch):
    """The real demo index has no `book_id` column; rows that carry one cannot
    be appended to it, and the upsert would fail on the schema rather than on
    anything the user did."""
    demo.ingest_transcripts_table("ollama", None, ["moby-dick", "emma"])
    db = lancedb.connect(demo_index)
    old = [{k: v for k, v in row.items() if k != "book_id"}
           for row in db.open_table("transcripts_ollama").search().limit(1000).to_list()]
    db.drop_table("transcripts_ollama")
    db.create_table("transcripts_ollama", old)
    assert "book_id" not in db.open_table("transcripts_ollama").schema.names

    monkeypatch.setattr(demo, "prepared_docs", lambda ids: [
        doc("moby-dick", "Moby Dick", "Herman Melville", ("Chapter 1",))])
    demo.ingest_transcripts_table("ollama", "moby", ["moby-dick"])

    db = lancedb.connect(demo_index)
    table = db.open_table("transcripts_ollama")
    assert "book_id" in table.schema.names
    ids = {row["key"]: row["book_id"] for row in open_ledger(db).all_rows()}
    rows = table.search().limit(1000).to_list()
    assert {r["book"] for r in rows} == set(ids)
    for row in rows:
        assert row["book_id"] == ids[row["book"]]
