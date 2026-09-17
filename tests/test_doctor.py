"""`check_ledger`: what the ledger and the index disagree about.

A stale ledger is the new failure mode ADR-024 accepted when it chose two
writes per book, so this is the check that makes it visible instead of assumed.
It never repairs: a report that rewrites what it reports on is not evidence.
"""
import lancedb
import pytest

from ask_your_library.ingest import add_folder
from ask_your_library.ingest.doctor import check_ledger
from ask_your_library.ingest.ledger import open_ledger
from test_add_folder import PARA, write  # noqa: F401
from test_add_folder import fake_embedder  # noqa: F401

BODY = PARA * 4
TABLES = ["transcripts_ollama", "cards_ollama"]


def make_folder(tmp_path):
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", BODY)
    write(folder, "Sea Notes - B. Mate.txt", BODY + " The tide turned at four.")
    return folder


@pytest.fixture
def index(tmp_path, fake_embedder):  # noqa: F811
    folder = make_folder(tmp_path)
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    return lancedb.connect(tmp_path / "db")


def test_a_freshly_written_index_has_no_drift(index):
    report = check_ledger(index, TABLES)
    assert report.ok
    assert report.books_in_ledger == 2 and report.books_in_index == 2
    assert any("no drift" in line for line in report.lines())


def test_a_book_the_ledger_calls_indexed_with_no_rows_is_reported(index):
    ledger = open_ledger(index)
    sea = next(row for row in ledger.all_rows() if row["key"].startswith("Sea"))
    index.open_table("transcripts_ollama").delete(f"book_id = '{sea['book_id']}'")

    report = check_ledger(index, TABLES)
    assert not report.ok
    assert report.indexed_but_absent == ["Sea Notes — B. Mate"]
    assert any("INDEXED BUT ABSENT" in line for line in report.lines())


def test_rows_no_ledger_row_claims_are_reported(index):
    ledger = open_ledger(index)
    sea = next(row for row in ledger.all_rows() if row["key"].startswith("Sea"))
    ledger.delete(sea["book_id"])

    report = check_ledger(index, TABLES)
    assert not report.ok
    assert report.in_index_but_not_in_ledger == ["Sea Notes — B. Mate"]
    assert report.orphan_row_counts.get("unknown book_id")
    assert any("NOT IN THE LEDGER" in line for line in report.lines())


def test_a_requested_book_that_never_finished_is_reported(index):
    ledger = open_ledger(index)
    ghost = ledger.resolve("A Ghost", "Nobody", sha256="ghost")
    ledger.begin(ghost, key="A Ghost — Nobody", source_ref="local:ghost.txt")

    report = check_ledger(index, TABLES)
    assert not report.ok
    assert report.never_indexed == ["A Ghost — Nobody (requested)"]


def test_a_failed_book_is_reported_with_its_reason(index):
    ledger = open_ledger(index)
    sea = next(row for row in ledger.all_rows() if row["key"].startswith("Sea"))
    ledger.fail(sea["book_id"], "embedder down")

    report = check_ledger(index, TABLES)
    assert report.never_indexed == ["Sea Notes — B. Mate (failed: embedder down)"]


def test_two_ids_for_one_key_are_reported_as_a_duplicate(index):
    ledger = open_ledger(index)
    sea = next(row for row in ledger.all_rows() if row["key"].startswith("Sea"))
    twin = dict(sea)
    twin["book_id"] = "a-second-minted-id"
    index.open_table("books").add([twin])

    report = check_ledger(index, TABLES)
    assert report.duplicate_keys == ["Sea Notes — B. Mate"]


def test_a_row_count_that_drifted_is_reported(index):
    ledger = open_ledger(index)
    sea = next(row for row in ledger.all_rows() if row["key"].startswith("Sea"))
    ledger.commit(sea["book_id"], rows=999)

    report = check_ledger(index, TABLES)
    assert not report.ok
    assert report.row_count_drift and "the ledger says 999" in report.row_count_drift[0]


def test_an_index_with_no_ledger_is_a_note_and_not_a_failure(tmp_path):
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama", [
        {"book": "Emma — Jane Austen", "note": "emma", "chunk_id": "emma/1",
         "text": "t", "vector": [1.0, 2.0]}])

    report = check_ledger(db, TABLES)
    assert report.ok                       # nothing to disagree with yet
    assert report.books_in_index == 1 and report.books_in_ledger == 0
    assert any("no books ledger" in note for note in report.notes)
    assert any("no book_id column" in note for note in report.notes)


def test_the_check_writes_nothing(index):
    before = {row["book_id"]: dict(row) for row in open_ledger(index).all_rows()}
    rows_before = index.open_table("transcripts_ollama").count_rows()
    check_ledger(index, TABLES)
    assert {row["book_id"]: dict(row) for row in open_ledger(index).all_rows()} == before
    assert index.open_table("transcripts_ollama").count_rows() == rows_before


def test_the_cli_reports_drift_and_exits_nonzero(tmp_path, fake_embedder, capsys):  # noqa: F811
    folder = make_folder(tmp_path)
    add_folder.main([str(folder), "--db", str(tmp_path / "db")])
    capsys.readouterr()
    assert add_folder.main(["--doctor", "--db", str(tmp_path / "db")]) == 0
    assert "no drift" in capsys.readouterr().out

    db = lancedb.connect(tmp_path / "db")
    sea = next(row for row in open_ledger(db).all_rows() if row["key"].startswith("Sea"))
    db.open_table("transcripts_ollama").delete(f"book_id = '{sea['book_id']}'")
    assert add_folder.main(["--doctor", "--db", str(tmp_path / "db")]) == 1
    assert "INDEXED BUT ABSENT" in capsys.readouterr().out


def test_the_cli_says_so_when_there_is_no_index(tmp_path, capsys):
    assert add_folder.main(["--doctor", "--db", str(tmp_path / "nope")]) == 1
    assert "no index at" in capsys.readouterr().err
    assert not (tmp_path / "nope").exists()
