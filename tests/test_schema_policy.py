"""The mismatch policy where a user meets it: `ayl-add`, the reader, `--doctor`.

`tests/test_index_meta.py` covers the decision itself — what counts as a
mismatch and what does not. This covers the four places the decision is acted
on, and the one thing they must not agree about: a read goes on, a write stops.

No network: the embedder is faked and the index is a tmp_path LanceDB.
"""
import lancedb
import pytest

from ask_your_library import index_meta, library
from ask_your_library.ingest import add_folder
from ask_your_library.ingest.doctor import check_ledger
from test_add_folder import PARA, fake_embedder, write  # noqa: F401

TABLES = ["transcripts_ollama", "cards_ollama"]
BODY = PARA * 4


@pytest.fixture
def index(tmp_path, fake_embedder):  # noqa: F811
    """A folder of two books, indexed exactly as `ayl-add` would."""
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", BODY)
    write(folder, "Sea Notes - B. Mate.txt", BODY + " The tide turned at four.")
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    return folder


def restamp(db_path, chunker="sentence-pack-2", schema_version=None):
    """Re-write the fingerprint as some other version of the code would have.

    The stamp is rewritten rather than the rows: what the policy acts on is the
    claim, and a test that re-chunked would be testing the chunker instead."""
    db = lancedb.connect(db_path)
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "fake-embed", 4,
                                chunker=chunker, schema_version=schema_version)
    return db


def test_a_fresh_index_is_stamped_with_the_chunker_that_built_it(index, tmp_path):
    row = index_meta.read_index_meta(lancedb.connect(tmp_path / "db"), "transcripts_ollama")
    assert row["chunker"] == add_folder.CHUNKER_VERSION
    assert row["schema_version"] == index_meta.SCHEMA_VERSION


def test_the_ledger_records_the_same_chunker_as_the_stamp(index, tmp_path):
    """One constant, two places that record it. They are the same string or the
    stamp is a claim about something the ledger disagrees with."""
    from ask_your_library.ingest.ledger import open_ledger

    db = lancedb.connect(tmp_path / "db")
    stamp = index_meta.read_index_meta(db, "transcripts_ollama")["chunker"]
    assert {row["chunker"] for row in open_ledger(db).all_rows()} == {stamp}


def test_ayl_add_refuses_to_write_an_index_another_chunker_built(index, tmp_path, capsys):
    restamp(tmp_path / "db")

    code = add_folder.main([str(index), "--db", str(tmp_path / "db")])

    assert code == 1
    error = capsys.readouterr().err
    assert "refusing to write transcripts_ollama" in error
    assert "sentence-pack-2" in error and add_folder.CHUNKER_VERSION in error
    assert "--rebuild" in error and "--backup" in error


def test_ayl_add_refuses_an_index_written_by_a_newer_release(index, tmp_path, capsys):
    restamp(tmp_path / "db", chunker=add_folder.CHUNKER_VERSION,
            schema_version=index_meta.SCHEMA_VERSION + 1)

    code = add_folder.main([str(index), "--db", str(tmp_path / "db")])

    assert code == 1
    assert "refusing to write transcripts_ollama" in capsys.readouterr().err


def test_a_refused_write_leaves_the_index_exactly_as_it_was(index, tmp_path):
    """The refusal comes before anything is embedded or deleted, which is the
    only order in which it is worth anything: a mixed index is what it exists
    to prevent."""
    db = lancedb.connect(tmp_path / "db")
    before = db.open_table("transcripts_ollama").count_rows()
    restamp(tmp_path / "db")

    assert add_folder.main([str(index), "--db", str(tmp_path / "db")]) == 1

    db = lancedb.connect(tmp_path / "db")
    assert db.open_table("transcripts_ollama").count_rows() == before
    assert index_meta.read_index_meta(db, "transcripts_ollama")["chunker"] == "sentence-pack-2"


def test_a_reader_warns_and_goes_on(index, tmp_path, monkeypatch, caplog, fake_embedder):  # noqa: F811
    """The half that must NOT refuse. An index another chunker built took the
    same half hour to build as any other, and it answers from the chunks it
    has."""
    restamp(tmp_path / "db")
    monkeypatch.setattr(library, "_embedder", fake_embedder)
    monkeypatch.setattr(library, "_checked_tables", set())
    db = lancedb.connect(tmp_path / "db")

    with caplog.at_level("WARNING"):
        table = library.open_table(db, "transcripts_ollama")

    assert table.count_rows() > 0                 # opened, not refused
    assert any("sentence-pack-2" in record.message for record in caplog.records)


def test_the_reader_warns_once_per_process(index, tmp_path, monkeypatch, caplog, fake_embedder):  # noqa: F811
    """Every search opens the table. A warning per search would be a warning
    per question, which is how a real one stops being read."""
    restamp(tmp_path / "db")
    monkeypatch.setattr(library, "_embedder", fake_embedder)
    monkeypatch.setattr(library, "_checked_tables", set())
    db = lancedb.connect(tmp_path / "db")

    with caplog.at_level("WARNING"):
        for _ in range(3):
            library.open_table(db, "transcripts_ollama")

    assert sum("sentence-pack-2" in record.message for record in caplog.records) == 1


def test_preflight_reports_a_mismatch_as_a_notice_not_a_problem(monkeypatch, tmp_path):
    """Degraded, not broken: the interfaces start, and the person asking is
    told — before the next `ayl-add` refuses them mid-ingest."""
    from ask_your_library import preflight as pf
    from test_preflight import healthy

    # `healthy` describes the hosted default; without this the local-model
    # check runs too and reports an Ollama model nobody pulled. test_preflight's
    # own autouse fixture does the same thing for the tests in that file.
    monkeypatch.setattr(pf, "LLM_BACKEND", "openrouter")
    monkeypatch.setattr(pf, "EMBED_BACKEND", "ollama")
    monkeypatch.setattr(pf, "OPENROUTER_NEEDS_KEY", True)
    monkeypatch.setattr(pf, "OLLAMA_EMBED_MODEL", "bge-m3")
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))
    monkeypatch.setattr(preflight, "warn_version_mismatch",
                        lambda db, name: f"{name} was built by chunker 'x'")

    result = preflight.check_environment()

    assert result == []                                  # not fatal
    assert any("chunker" in notice for notice in result.notices)


def test_doctor_reads_the_stamp_out_whether_or_not_it_disagrees(index, tmp_path):
    report = check_ledger(lancedb.connect(tmp_path / "db"), TABLES)
    assert report.ok
    assert any(add_folder.CHUNKER_VERSION in line for line in report.stamps)
    assert any("row schema" in line for line in report.stamps)


def test_doctor_names_a_mismatch_and_exits_non_zero(index, tmp_path, capsys):
    restamp(tmp_path / "db")

    code = add_folder.main(["--doctor", "--db", str(tmp_path / "db")])

    assert code == 1
    out = capsys.readouterr().out
    assert "VERSION MISMATCH" in out and "sentence-pack-2" in out
    assert "ayl-add --backup" in out


# --- the way out: `ayl-add --rebuild` ----------------------------------------

def test_the_refusal_names_a_command_that_actually_gets_out_of_it(index, tmp_path, capsys):
    """The refusal used to recommend `ayl-add <folder>`, which hits the same
    refusal. The only way out was deleting the index directory by hand, and
    nothing said so."""
    restamp(tmp_path / "db")
    add_folder.main([str(index), "--db", str(tmp_path / "db")])
    error = capsys.readouterr().err
    assert "--rebuild" in error


def test_rebuild_replaces_the_table_and_the_stamp_is_current(index, tmp_path, capsys):
    restamp(tmp_path / "db")
    before = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows()

    code = add_folder.main([str(index), "--db", str(tmp_path / "db"), "--rebuild", "--force"])

    assert code == 0
    db = lancedb.connect(tmp_path / "db")
    assert index_meta.read_index_meta(db, "transcripts_ollama")["chunker"] \
        == add_folder.CHUNKER_VERSION
    assert index_meta.version_mismatch(db, "transcripts_ollama") is None
    assert db.open_table("transcripts_ollama").count_rows() == before
    # and the index is writable again by an ordinary run
    assert add_folder.main([str(index), "--db", str(tmp_path / "db")]) == 0


def test_rebuild_keeps_the_minted_ids(index, tmp_path):
    """Dropping the ledger with the table would turn every book in the library
    into a new book — the defect the ledger exists to prevent, by the back
    door."""
    from ask_your_library.ingest.ledger import open_ledger

    before = {row["key"]: row["book_id"]
              for row in open_ledger(lancedb.connect(tmp_path / "db")).all_rows()}
    restamp(tmp_path / "db")

    add_folder.main([str(index), "--db", str(tmp_path / "db"), "--rebuild", "--force"])

    after = {row["key"]: row["book_id"]
             for row in open_ledger(lancedb.connect(tmp_path / "db")).all_rows()}
    assert after == before


def test_rebuild_names_the_books_it_does_not_cover(index, tmp_path, capsys, fake_embedder):  # noqa: F811
    """A second folder's books were in the table too. Their rows went with it,
    so the ledger's `indexed` is no longer true of them — and saying nothing
    would leave `--doctor` as the only place the loss ever surfaced."""
    other = tmp_path / "more-books"
    write(other, "Harbour Lights - C. Watch.txt", BODY)
    add_folder.add_books(add_folder.read_folder(other), "ollama", tmp_path / "db", other)
    capsys.readouterr()

    add_folder.main([str(index), "--db", str(tmp_path / "db"), "--rebuild", "--force"])

    from ask_your_library.ingest.ledger import open_ledger

    out = capsys.readouterr().out
    assert "Harbour Lights — C. Watch" in out and "does not cover it" in out
    rows = open_ledger(lancedb.connect(tmp_path / "db")).all_rows()
    assert next(r for r in rows if r["key"].startswith("Harbour"))["status"] == "requested"


def test_rebuild_without_a_backup_or_force_is_refused(index, tmp_path, capsys):
    code = add_folder.main([str(index), "--db", str(tmp_path / "db"), "--rebuild"])
    assert code == 2
    assert "--backup" in capsys.readouterr().err


def test_rebuild_with_backup_takes_the_copy_first(index, tmp_path, capsys):
    restamp(tmp_path / "db")

    code = add_folder.main([str(index), "--db", str(tmp_path / "db"), "--rebuild",
                            "--backup", str(tmp_path / "backups")])

    assert code == 0
    taken = list((tmp_path / "backups").iterdir())
    assert len(taken) == 1 and (taken[0] / "MANIFEST.json").is_file()
    # the copy is of the index as it WAS: the stamp it holds is the old one
    import json
    manifest = json.loads((taken[0] / "MANIFEST.json").read_text())
    stamp = next(r for r in manifest["index_meta"] if r["table"] == "transcripts_ollama")
    assert stamp["chunker"] == "sentence-pack-2"


def test_a_failed_backup_stops_the_rebuild(index, tmp_path, capsys):
    """The one sequence --rebuild exists to make safe, run in reverse, is the
    one thing it must never do."""
    code = add_folder.main([str(index), "--db", str(tmp_path / "db"), "--rebuild",
                            "--backup", str(tmp_path / "db" / "inside")])
    assert code == 1
    assert "inside the index itself" in capsys.readouterr().err
    assert lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows() > 0


def test_force_on_its_own_is_an_error(index, tmp_path, capsys):
    code = add_folder.main([str(index), "--db", str(tmp_path / "db"), "--force"])
    assert code == 2
    assert "--force belongs to" in capsys.readouterr().err


# --- one chunker per table kind ----------------------------------------------

def test_cards_are_compared_with_the_card_chunker_not_the_sentence_packer(tmp_path):
    """A card is cut on its "## section" headings; the packer's version says
    nothing about it. Stamping the packer's version on cards would make #28's
    bump refuse every card write for a reason that is not true of cards."""
    from ask_your_library.ingest.chunking import CARD_CHUNKER_VERSION

    db = lancedb.connect(tmp_path / "db")
    db.create_table("cards_ollama", [{"chunk_id": "c/1", "note": "c", "book": "A — B",
                                      "source": "card", "section": "One", "text": "t",
                                      "vector": [0.0] * 4}])
    index_meta.write_index_meta(db, "cards_ollama", "ollama", "fake-embed", 4,
                                chunker=CARD_CHUNKER_VERSION)
    assert index_meta.expected_chunker("cards_ollama") == CARD_CHUNKER_VERSION
    assert index_meta.version_mismatch(db, "cards_ollama") is None
    # the transcripts rule applied to a cards table would be a false mismatch
    assert index_meta.version_mismatch(
        db, "cards_ollama", chunker=add_folder.CHUNKER_VERSION) is not None


def test_a_cards_table_stamped_with_the_packer_is_a_mismatch(tmp_path):
    db = lancedb.connect(tmp_path / "db")
    db.create_table("cards_ollama", [{"chunk_id": "c/1", "note": "c", "book": "A — B",
                                      "source": "card", "section": "One", "text": "t",
                                      "vector": [0.0] * 4}])
    index_meta.write_index_meta(db, "cards_ollama", "ollama", "fake-embed", 4,
                                chunker=add_folder.CHUNKER_VERSION)
    detail = index_meta.version_mismatch(db, "cards_ollama")
    assert detail and add_folder.CHUNKER_VERSION in detail


def test_the_warning_is_logged_once_per_process_across_call_sites(index, tmp_path, caplog):
    """The dedupe is the module's, not each caller's: the reader and the
    preflight must not each log the same sentence about the same table."""
    restamp(tmp_path / "db")
    db = lancedb.connect(tmp_path / "db")
    index_meta._warned.clear()

    with caplog.at_level("WARNING"):
        first = index_meta.warn_version_mismatch(db, "transcripts_ollama")
        second = index_meta.warn_version_mismatch(db, "transcripts_ollama")

    assert first == second and first is not None      # every caller still gets the line
    assert sum("sentence-pack-2" in r.message for r in caplog.records) == 1


# --- a refusal writes nothing, not even a recovery ---------------------------

def test_a_refused_run_does_not_finish_somebody_elses_staged_rebuild(index, tmp_path, capsys):
    """The checks are reads — `read_index_meta` never recovers — so they come
    BEFORE `recover_staging`. Otherwise a run on its way to saying no could
    still drop or promote a staging table, which is a write nobody asked for."""
    from ask_your_library.ingest.publish import copy_table, table_names

    db = lancedb.connect(tmp_path / "db")
    copy_table(db, "transcripts_ollama", "transcripts_ollama__staging")   # live + staging
    restamp(tmp_path / "db")

    assert add_folder.main([str(index), "--db", str(tmp_path / "db")]) == 1

    names = table_names(lancedb.connect(tmp_path / "db"))
    assert "transcripts_ollama__staging" in names and "transcripts_ollama" in names
    assert "refusing to write" in capsys.readouterr().err


def test_a_refused_run_leaves_a_staging_only_fingerprint_table_alone(index, tmp_path):
    """The sharper shape: the fingerprint table is mid-widening, so only the
    staged copy exists. A reader takes it read-only (ADR-024); a refusal must
    not promote it on the way out."""
    from ask_your_library.ingest.publish import copy_table, table_names

    restamp(tmp_path / "db")
    db = lancedb.connect(tmp_path / "db")
    copy_table(db, index_meta.META_TABLE, index_meta.META_TABLE + "__staging")
    db.drop_table(index_meta.META_TABLE)

    assert add_folder.main([str(index), "--db", str(tmp_path / "db")]) == 1

    names = table_names(lancedb.connect(tmp_path / "db"))
    assert index_meta.META_TABLE + "__staging" in names
    assert index_meta.META_TABLE not in names          # not promoted by a refusal


# --- the doctor example in the docs, kept true -------------------------------

def test_the_doctor_output_matches_the_example_in_the_upgrading_page(index, tmp_path, capsys,
                                                                    fake_embedder):  # noqa: F811
    """The page shows a `--doctor` run with a stamp line per table. It had the
    cards table stamped with the sentence packer, which is exactly the mistake
    the two constants exist to prevent — so the example is asserted here rather
    than proof-read."""
    from pathlib import Path

    from ask_your_library.index_meta import write_index_meta
    from ask_your_library.ingest.chunking import CARD_CHUNKER_VERSION

    db = lancedb.connect(tmp_path / "db")
    db.create_table("cards_ollama", [{"chunk_id": "c/1", "note": "c", "book": "A — B",
                                      "source": "card", "section": "One", "text": "t",
                                      "vector": [0.0] * 4}])
    write_index_meta(db, "cards_ollama", "ollama", "fake-embed", 4,
                     chunker=CARD_CHUNKER_VERSION)
    capsys.readouterr()

    add_folder.main(["--doctor", "--db", str(tmp_path / "db")])

    out = capsys.readouterr().out
    assert f"stamp: transcripts_ollama: fake-embed / 4d, chunker {add_folder.CHUNKER_VERSION}, " \
           f"row schema 2" in out
    assert f"stamp: cards_ollama: fake-embed / 4d, chunker {CARD_CHUNKER_VERSION}, " \
           f"row schema 1" in out

    page = (Path(__file__).resolve().parents[1] / "docs" / "upgrading.md").read_text()
    assert f"chunker {CARD_CHUNKER_VERSION}, row schema 1" in page
    assert f"chunker {add_folder.CHUNKER_VERSION}, row schema 2" in page
