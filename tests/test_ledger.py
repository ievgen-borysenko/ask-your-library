"""The `books` ledger, against a real local LanceDB.

What it has to get right is identity across a correction: the same book keeps
its `book_id` when its author is fixed or its file is renamed, because the id
is minted once and never derived from anything that can change.
"""
import lancedb
import pytest

from ask_your_library.bookkey import book_key
from ask_your_library.ingest import ledger as ledger_mod
from ask_your_library.ingest.ledger import (INDEXED, LEGACY_CHUNKER, REQUESTED,
                                            backfill_from_index, open_ledger)


@pytest.fixture
def ledger(tmp_path):
    return open_ledger(lancedb.connect(tmp_path / "db"))


def index_rows(*pairs):
    return [{"book": book, "note": note, "chunk_id": f"{note}/{i}", "text": "t",
             "vector": [float(i), 1.0]}
            for i, (book, note) in enumerate(pairs, 1)]


# --- minting an id -----------------------------------------------------------

def test_a_new_book_is_minted_once_and_the_same_book_resolves_to_it(ledger):
    first = ledger.resolve("Moby Dick", "Herman Melville", sha256="abc")
    again = ledger.resolve("Moby Dick", "Herman Melville", sha256="abc")
    assert first == again
    assert len(ledger.all_rows()) == 1


def test_the_id_is_opaque_and_not_derived_from_the_key(ledger):
    book_id = ledger.resolve("Moby Dick", "Herman Melville")
    assert "moby" not in book_id.lower() and "melville" not in book_id.lower()
    assert len(book_id) == 32


def test_a_new_row_starts_as_requested(ledger):
    book_id = ledger.resolve("Moby Dick", "Herman Melville")
    row = ledger.get(book_id)
    assert row["status"] == REQUESTED and row["requested_at"] and not row["indexed_at"]
    assert row["title"] == "Moby Dick" and row["author"] == "Herman Melville"


def test_two_books_with_the_same_title_are_two_books(ledger):
    one = ledger.resolve("Emma", "Jane Austen", sha256="a")
    two = ledger.resolve("Emma", "Other Author", sha256="b")
    assert one != two and len(ledger.all_rows()) == 2


# --- the two match rules -----------------------------------------------------

def test_a_corrected_author_keeps_the_id_because_the_content_is_the_same(ledger):
    """The defect this issue exists for: under the derived row key alone, this
    is a second book whose delete matches nothing."""
    before = ledger.resolve("Moby Dick", "H. Melville", sha256="deadbeef")
    after = ledger.resolve("Moby Dick", "Herman Melville", sha256="deadbeef")
    assert after == before
    assert len(ledger.all_rows()) == 1


def test_a_re_export_of_the_same_book_keeps_the_id_though_the_content_changed(ledger):
    before = ledger.resolve("Moby Dick", "Herman Melville", sha256="one")
    after = ledger.resolve("Moby Dick", "Herman Melville", sha256="two")
    assert after == before and len(ledger.all_rows()) == 1


def test_a_book_with_no_digest_never_collides_with_another_one(ledger):
    one = ledger.resolve("Emma", "Jane Austen", sha256="")
    two = ledger.resolve("Persuasion", "Jane Austen", sha256="")
    assert one != two


def test_the_key_wins_over_a_sha_match(ledger):
    """Two files with identical content under two different titles stay two
    books: the key is what the reader and the agent see."""
    emma = ledger.resolve("Emma", "Jane Austen", sha256="same")
    other = ledger.resolve("Persuasion", "Jane Austen", sha256="same")
    assert other == emma        # no key row yet for Persuasion, so the sha matched
    # ... but once each has its own row, the key decides
    ledger.resolve("Persuasion", "Jane Austen", sha256="same")
    assert ledger.resolve("Emma", "Jane Austen", sha256="same") == emma


# --- the write, before and after ---------------------------------------------

def test_begin_then_commit_records_what_was_written(ledger):
    book_id = ledger.resolve("Moby Dick", "Herman Melville", sha256="abc")
    ledger.begin(book_id, key=book_key("Moby Dick", "Herman Melville"),
                 source_ref="local:moby.txt", sha256="abc", embedding_model="bge-m3")
    assert ledger.get(book_id)["status"] == REQUESTED
    ledger.commit(book_id, rows=42, fts_seconds=1.5)
    row = ledger.get(book_id)
    assert row["status"] == INDEXED and row["rows"] == 42 and row["indexed_at"]
    assert row["fts_seconds"] == pytest.approx(1.5)
    assert row["embedding_model"] == "bge-m3" and row["source_ref"] == "local:moby.txt"
    assert row["chunker"] == ledger_mod.CHUNKER_VERSION


def test_a_failure_is_one_bounded_line(ledger):
    book_id = ledger.resolve("Moby Dick", "Herman Melville")
    ledger.begin(book_id)
    ledger.fail(book_id, "embedder down:\n  connection refused\n" + "x" * 900)
    row = ledger.get(book_id)
    assert row["status"] == "failed"
    assert row["error"].startswith("embedder down: connection refused")
    assert "\n" not in row["error"] and len(row["error"]) <= 500


def test_a_book_is_one_row_however_many_times_it_is_written(ledger):
    book_id = ledger.resolve("Moby Dick", "Herman Melville")
    for _ in range(3):
        ledger.begin(book_id)
        ledger.commit(book_id, rows=1)
    assert len(ledger.all_rows()) == 1


def test_committing_an_unknown_book_is_an_error_not_a_new_row(ledger):
    with pytest.raises(KeyError):
        ledger.commit("nosuchid", rows=1)
    assert ledger.all_rows() == []


# --- questions ---------------------------------------------------------------

def test_missing_reports_what_was_requested_and_never_indexed(ledger):
    done = ledger.resolve("Moby Dick", "Herman Melville")
    ledger.begin(done)
    ledger.commit(done, rows=3)
    interrupted = ledger.resolve("Emma", "Jane Austen")
    ledger.begin(interrupted)
    broken = ledger.resolve("Dracula", "Bram Stoker")
    ledger.begin(broken)
    ledger.fail(broken, "not UTF-8")

    keys = [row["key"] for row in ledger.missing()]
    assert keys == [book_key("Dracula", "Bram Stoker"), book_key("Emma", "Jane Austen")]


def test_diff_names_new_files_known_files_and_vanished_books(ledger, tmp_path):
    folder = tmp_path / "books"
    folder.mkdir()
    (folder / "moby.txt").write_text("x", encoding="utf-8")
    (folder / "new.txt").write_text("x", encoding="utf-8")

    moby = ledger.resolve("Moby Dick", "Herman Melville")
    ledger.begin(moby, key=book_key("Moby Dick", "Herman Melville"),
                 source_ref="local:moby.txt")
    ledger.commit(moby, rows=3)
    gone = ledger.resolve("Dracula", "Bram Stoker")
    ledger.begin(gone, key=book_key("Dracula", "Bram Stoker"), source_ref="local:dracula.txt")
    ledger.commit(gone, rows=3)

    keys = {"moby.txt": book_key("Moby Dick", "Herman Melville"),
            "new.txt": book_key("A New Book", "Someone")}
    result = ledger.diff(folder, files=sorted(folder.glob("*.txt")),
                         key_of=lambda p: keys[p.name])
    assert [p.name for p in result.new] == ["new.txt"]
    assert [(p.name, i) for p, i in result.known] == [("moby.txt", moby)]
    assert [row["book_id"] for row in result.vanished] == [gone]


def test_a_book_that_moved_inside_the_folder_is_not_a_new_book(ledger, tmp_path):
    folder = tmp_path / "books"
    (folder / "sub").mkdir(parents=True)
    moved = folder / "sub" / "moby.txt"
    moved.write_text("x", encoding="utf-8")
    key = book_key("Moby Dick", "Herman Melville")
    moby = ledger.resolve("Moby Dick", "Herman Melville")
    ledger.begin(moby, key=key, source_ref="local:moby.txt")
    ledger.commit(moby, rows=3)

    result = ledger.diff(folder, files=[moved], key_of=lambda p: key)
    assert result.new == [] and result.vanished == []
    assert result.known == [(moved, moby)]


def test_a_ledger_row_from_another_ingest_path_is_never_reported_as_vanished(ledger,
                                                                             tmp_path):
    """The demo corpus's rows carry no `local:` file, and a folder that does not
    contain them is not evidence that they are gone."""
    folder = tmp_path / "books"
    folder.mkdir()
    demo = ledger.resolve("Robinson Crusoe", "Daniel Defoe")
    ledger.begin(demo, key=book_key("Robinson Crusoe", "Daniel Defoe"),
                 source_ref="manifest:robinson-crusoe")
    ledger.commit(demo, rows=3)
    assert ledger.diff(folder, files=[], key_of=lambda p: "").vanished == []


# --- the upgrade -------------------------------------------------------------

def test_backfill_writes_one_indexed_row_per_book_already_in_the_index(tmp_path):
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama", index_rows(
        ("Moby Dick — Herman Melville", "moby"), ("Moby Dick — Herman Melville", "moby"),
        ("Emma — Jane Austen", "emma")))
    db.create_table("cards_ollama", index_rows(("Dracula — Bram Stoker", "dracula")))

    written = backfill_from_index(db, ["transcripts_ollama", "cards_ollama", "absent"],
                                  embedding_model="bge-m3")
    ledger = open_ledger(db)
    assert written == 3
    rows = {row["key"]: row for row in ledger.all_rows()}
    assert sorted(rows) == ["Dracula — Bram Stoker", "Emma — Jane Austen",
                            "Moby Dick — Herman Melville"]
    moby = rows["Moby Dick — Herman Melville"]
    assert moby["status"] == INDEXED and moby["chunker"] == LEGACY_CHUNKER
    assert moby["source_ref"] == "note:moby" and moby["embedding_model"] == "bge-m3"
    assert len({row["book_id"] for row in rows.values()}) == 3


def test_backfill_is_idempotent_and_never_touches_a_row_it_already_has(tmp_path):
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama", index_rows(("Emma — Jane Austen", "emma")))
    assert backfill_from_index(db, ["transcripts_ollama"]) == 1
    before = open_ledger(db).all_rows()[0]
    assert backfill_from_index(db, ["transcripts_ollama"]) == 0
    assert open_ledger(db).all_rows() == [before]


def test_a_backfilled_book_keeps_its_id_when_its_author_is_corrected_later(tmp_path):
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama", index_rows(("Moby Dick — H. Melville", "moby")))
    backfill_from_index(db, ["transcripts_ollama"])
    ledger = open_ledger(db)
    before = ledger.all_rows()[0]["book_id"]
    # No sha256 was recorded for a legacy row, so the correction mints a second
    # id — the honest outcome, and the reason `doctor` reports the pair.
    after = ledger.resolve("Moby Dick", "Herman Melville", sha256="abc")
    assert after != before
    assert ledger.resolve("Moby Dick", "H. Melville") == before
