"""`ayl-add --backup` / `--restore`, and the lock that says when a copy is safe.

The product here is not the copy — `cp -r` makes copies. It is the statement
that the copy was taken at a moment when the index was whole: no ingest
running, no staged rebuild half-swapped, and a digest per file so that a backup
which rotted is found before it replaces a working index rather than after.

No network: the embedder is faked and every path is under tmp_path.
"""
import json
import os

import lancedb
import pytest

from ask_your_library.ingest import add_folder, backup as backup_module
from ask_your_library.ingest.backup import BackupError, backup, restore, verify
from ask_your_library.ingest.doctor import check_ledger
from ask_your_library.ingest.lock import (IngestBusy, LOCK_NAME, acquire, ingest_lock,
                                          lock_path, read_lock, release)
from test_add_folder import PARA, fake_embedder, write  # noqa: F401

BODY = PARA * 4
TABLES = ["transcripts_ollama", "cards_ollama"]


@pytest.fixture
def built(tmp_path, fake_embedder):  # noqa: F811
    """An index of two books and a folder that produced it."""
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", BODY)
    write(folder, "Sea Notes - B. Mate.txt", BODY + " The tide turned at four.")
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    return folder


def chat_db(tmp_path, text=b"SQLite format 3\x00 pretend"):
    path = tmp_path / "chainlit" / "chat.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text)
    return path


# --- the lock ----------------------------------------------------------------

def test_an_ingest_holds_the_lock_and_drops_it_at_the_end(built, tmp_path):
    assert not lock_path(tmp_path / "db").exists()


def test_a_second_writer_is_refused_while_the_first_holds_the_lock(built, tmp_path):
    with ingest_lock(tmp_path / "db", command="pretend ingest"):
        with pytest.raises(IngestBusy) as error:
            add_folder.add_books(add_folder.read_folder(built), "ollama", tmp_path / "db", built)
    assert "an ingest is writing" in str(error.value)
    assert "pretend ingest" in str(error.value)
    assert LOCK_NAME in str(error.value)          # the file to delete, named


def test_a_lock_left_by_a_dead_process_is_taken_over(tmp_path, caplog):
    """A power cut leaves the file behind. The pid is what makes that
    recoverable without a human deleting a file they have never heard of."""
    db_path = tmp_path / "db"
    db_path.mkdir()
    lock_path(db_path).write_text(json.dumps(
        {"pid": _a_pid_that_is_not_running(), "host": os.uname().nodename,
         "started": "2026-01-01T00:00:00", "command": "ayl-add ~/books"}))

    with caplog.at_level("WARNING"):
        acquire(db_path, command="ayl-add again")

    assert read_lock(db_path)["pid"] == os.getpid()
    assert any("clearing a lock" in record.message for record in caplog.records)
    release(db_path)


def test_a_lock_from_another_machine_is_never_taken_over(tmp_path):
    """A network share is the only way this happens, and nothing here can ask
    that machine whether its process is alive. Refuse, and name the file."""
    db_path = tmp_path / "db"
    db_path.mkdir()
    lock_path(db_path).write_text(json.dumps(
        {"pid": _a_pid_that_is_not_running(), "host": "some-other-laptop",
         "started": "2026-01-01T00:00:00", "command": "ayl-add"}))

    with pytest.raises(IngestBusy) as error:
        acquire(db_path)
    assert "some-other-laptop" in str(error.value)


def _a_pid_that_is_not_running() -> int:
    """A pid nothing holds. Searching downwards from a high number, because a
    fixed one might be in use on the machine running the tests."""
    for pid in range(99999, 40000, -1):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return pid
        except OSError:
            continue
    raise AssertionError("no free pid found")


# --- the backup --------------------------------------------------------------

def test_a_backup_copies_the_index_the_chat_db_and_a_manifest(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups", chat_db=chat_db(tmp_path))

    assert (target / "lancedb" / "transcripts_ollama.lance").is_dir()
    assert (target / "chat.db").is_file()
    manifest = json.loads((target / "MANIFEST.json").read_text())
    assert manifest["tables"]["transcripts_ollama"] > 0
    assert manifest["ledger_rows"] == 2
    assert manifest["expects"]["chunker"] == add_folder.CHUNKER_VERSION
    assert manifest["files"] and all(entry["sha256"] for entry in manifest["files"])
    # what the copy IS, which is what a restore after a rebuilding upgrade
    # needs in order to know which index it is holding
    stamp = next(row for row in manifest["index_meta"]
                 if row["table"] == "transcripts_ollama")
    assert stamp["chunker"] == add_folder.CHUNKER_VERSION


def test_a_fresh_backup_verifies(built, tmp_path):
    assert verify(backup(tmp_path / "db", tmp_path / "backups")) == []


def test_the_lock_is_never_copied_into_the_backup(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")
    assert not (target / "lancedb" / LOCK_NAME).exists()
    assert not any(LOCK_NAME in entry["path"] for entry in
                   json.loads((target / "MANIFEST.json").read_text())["files"])


def test_a_backup_refuses_while_an_ingest_is_in_flight(built, tmp_path):
    with ingest_lock(tmp_path / "db", command="ayl-add ~/books"):
        with pytest.raises(IngestBusy) as error:
            backup(tmp_path / "db", tmp_path / "backups")
    assert "refusing to back up" in str(error.value) and "ayl-add ~/books" in str(error.value)


def test_a_backup_finishes_an_interrupted_rebuild_before_copying(built, tmp_path):
    """The window a plain `cp -r` cannot see: LanceDB OSS has no rename, so a
    rebuild drops the live table and copies the staged one over. A copy taken
    in between restores to an index with a table missing."""
    db = lancedb.connect(tmp_path / "db")
    from ask_your_library.ingest.publish import copy_table

    copy_table(db, "transcripts_ollama", "transcripts_ollama__staging")
    db.drop_table("transcripts_ollama")              # mid-swap, exactly

    target = backup(tmp_path / "db", tmp_path / "backups")

    manifest = json.loads((target / "MANIFEST.json").read_text())
    assert manifest["recovered_staging"] == ["transcripts_ollama"]
    assert manifest["tables"]["transcripts_ollama"] > 0
    assert (target / "lancedb" / "transcripts_ollama.lance").is_dir()


def test_backing_up_an_index_that_is_not_there_is_one_line(tmp_path):
    with pytest.raises(BackupError, match="nothing to back up"):
        backup(tmp_path / "nope", tmp_path / "backups")


# --- the restore -------------------------------------------------------------

def test_a_tampered_backup_is_refused_and_nothing_is_touched(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")
    victim = next(p for p in sorted((target / "lancedb").rglob("*")) if p.is_file())
    victim.write_bytes(victim.read_bytes() + b"rot")

    with pytest.raises(BackupError) as error:
        restore(target, tmp_path / "db", force=True)

    assert "does not match its own manifest" in str(error.value)
    assert "Nothing was touched" in str(error.value)
    # and the live index is still there, still readable
    assert lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows() > 0


def test_a_file_removed_from_a_backup_is_caught_too(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")
    next(p for p in sorted((target / "lancedb").rglob("*")) if p.is_file()).unlink()
    assert any(line.startswith("missing:") for line in verify(target))


def test_a_restore_refuses_to_overwrite_a_live_index_without_force(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")
    with pytest.raises(BackupError) as error:
        restore(target, tmp_path / "db")
    assert "--force" in str(error.value)


def test_a_restore_keeps_the_index_it_replaces(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")

    report = restore(target, tmp_path / "db", force=True)

    kept = [line for line in report if "is kept at" in line]
    assert kept and "replaced-" in kept[0]
    assert list(tmp_path.glob("db.replaced-*"))


def test_backup_then_restore_leaves_an_index_doctor_calls_clean(built, tmp_path):
    """The whole point, end to end: the copy is a working index, not a pile of
    files that happens to verify."""
    target = backup(tmp_path / "db", tmp_path / "backups", chat_db=chat_db(tmp_path))
    before = check_ledger(lancedb.connect(tmp_path / "db"), TABLES)
    import shutil
    shutil.rmtree(tmp_path / "db")

    restore(target, tmp_path / "db", chat_db=tmp_path / "restored" / "chat.db")

    report = check_ledger(lancedb.connect(tmp_path / "db"), TABLES)
    assert report.ok
    assert report.books_in_ledger == before.books_in_ledger == 2
    assert report.books_in_index == before.books_in_index == 2
    assert (tmp_path / "restored" / "chat.db").is_file()


def test_a_restored_index_can_be_written_to_again(built, tmp_path, fake_embedder):  # noqa: F811
    """A restore that left a lock behind, or a stamp the write path refuses,
    would be a restore of something nobody can use."""
    target = backup(tmp_path / "db", tmp_path / "backups")
    import shutil
    shutil.rmtree(tmp_path / "db")
    restore(target, tmp_path / "db")

    assert not lock_path(tmp_path / "db").exists()
    counts = add_folder.add_books(add_folder.read_folder(built), "ollama", tmp_path / "db", built)
    assert counts["books"] == 2


def test_a_restore_refuses_while_an_ingest_is_writing_the_live_index(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")
    with ingest_lock(tmp_path / "db", command="ayl-add ~/books"):
        with pytest.raises(IngestBusy) as error:
            restore(target, tmp_path / "db", force=True)
    assert "refusing to restore over" in str(error.value)
    assert lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows() > 0


def test_a_directory_that_is_not_a_backup_says_so(tmp_path):
    (tmp_path / "not-a-backup").mkdir()
    with pytest.raises(BackupError, match="is not there"):
        restore(tmp_path / "not-a-backup", tmp_path / "db")


# --- the command line --------------------------------------------------------

def test_the_cli_reports_what_it_copied_and_how_to_put_it_back(built, tmp_path, capsys,
                                                               monkeypatch):
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))
    chat_db(tmp_path)

    code = add_folder.main(["--backup", str(tmp_path / "backups"), "--db", str(tmp_path / "db")])

    assert code == 0
    out = capsys.readouterr().out
    assert "backup written to" in out
    assert "transcripts_ollama:" in out and "books ledger: 2 row(s)" in out
    assert f"chunker {add_folder.CHUNKER_VERSION}" in out
    assert "--restore" in out


def test_the_cli_restores_and_points_at_the_check(built, tmp_path, capsys):
    add_folder.main(["--backup", str(tmp_path / "backups"), "--db", str(tmp_path / "db")])
    target = next((tmp_path / "backups").iterdir())
    capsys.readouterr()

    code = add_folder.main(["--restore", str(target), "--db", str(tmp_path / "db"), "--force"])

    assert code == 0
    out = capsys.readouterr().out
    assert "verified" in out and "index restored to" in out and "--doctor" in out


def test_the_cli_turns_a_refusal_into_one_line(built, tmp_path, capsys):
    add_folder.main(["--backup", str(tmp_path / "backups"), "--db", str(tmp_path / "db")])
    target = next((tmp_path / "backups").iterdir())
    capsys.readouterr()

    code = add_folder.main(["--restore", str(target), "--db", str(tmp_path / "db")])

    assert code == 1
    error = capsys.readouterr().err
    assert error.count("\n") <= 2 and "--force" in error


def test_the_default_chat_db_follows_the_variable_the_ui_reads(tmp_path, monkeypatch):
    """Resolved at call time, not at import: `ui.py` reads the same variable at
    ITS import, and the tests set it per test."""
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "elsewhere"))
    assert backup_module.default_chat_db() == tmp_path / "elsewhere" / "chat.db"


# --- a destination that would swallow itself ---------------------------------

def test_a_destination_inside_the_index_is_refused_and_writes_nothing(built, tmp_path):
    """Copying a directory into itself: `copytree` would race its own output,
    and the best case is a backup containing a partial copy of itself."""
    inside = tmp_path / "db" / "backups"
    with pytest.raises(BackupError, match="inside the index itself"):
        backup(tmp_path / "db", inside)
    assert not inside.exists()


def test_the_check_follows_links_rather_than_names(built, tmp_path):
    """A `..` or a symlink must not walk into the index under another name."""
    link = tmp_path / "looks-outside"
    link.symlink_to(tmp_path / "db" / "sub", target_is_directory=True)
    (tmp_path / "db" / "sub").mkdir()
    with pytest.raises(BackupError, match="inside the index itself"):
        backup(tmp_path / "db", link)


def test_a_failed_copy_leaves_no_half_written_backup(built, tmp_path, monkeypatch):
    """A partial backup is worse than none: a directory named like a backup,
    with no manifest to say what it is missing, waiting for the day somebody
    reaches for it."""
    monkeypatch.setattr(backup_module, "_sha256",
                        lambda path: (_ for _ in ()).throw(OSError("disk went away")))

    with pytest.raises(OSError, match="disk went away"):
        backup(tmp_path / "db", tmp_path / "backups")

    assert not any((tmp_path / "backups").iterdir())
    # and the lock was released, so the index is still usable
    assert not lock_path(tmp_path / "db").exists()


# --- a symlinked index path --------------------------------------------------

def test_a_restore_follows_a_symlinked_index_path(built, tmp_path, fake_embedder):  # noqa: F811
    """`data/lancedb` is a symlink in this project's own dev checkout. Renaming
    the LINK would move the link, leave the real directory in place and write
    the restored index onto the wrong volume."""
    real = tmp_path / "db"
    link = tmp_path / "linked-db"
    link.symlink_to(real, target_is_directory=True)
    target = backup(link, tmp_path / "backups")

    report = restore(target, link, force=True)

    assert link.is_symlink() and link.resolve() == real
    assert real.is_dir()
    assert lancedb.connect(link).open_table("transcripts_ollama").count_rows() > 0
    # the REAL directory is what was moved aside, not the link
    assert list(tmp_path.glob("db.replaced-*")) and not list(tmp_path.glob("linked-db.replaced-*"))
    assert any("still points at the restored index" in line for line in report)


# --- the lock is complete from the instant its name exists -------------------

def test_the_lock_file_is_never_observed_empty(tmp_path):
    """The window this closes: create-then-write lets a competitor read `{}`,
    call it a lock nobody can be identified from, and take it over."""
    db_path = tmp_path / "db"
    db_path.mkdir()
    acquire(db_path, command="ayl-add ~/books")
    try:
        info = read_lock(db_path)
        assert info["pid"] == os.getpid() and info["command"] == "ayl-add ~/books"
        assert info["host"] and info["started"]
        # and nothing left beside it
        assert [p.name for p in db_path.iterdir()] == [LOCK_NAME]
    finally:
        release(db_path)
