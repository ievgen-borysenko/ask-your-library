"""`ayl-add --backup` / `--restore`, and the lock that says when a copy is safe.

The product here is not the copy — `cp -r` makes copies. It is the statement
that the copy was taken at a moment when the index was whole: no ingest
running, no staged rebuild half-swapped, and a digest per file so that a backup
which rotted is found before it replaces a working index rather than after.

No network: the embedder is faked and every path is under tmp_path.
"""
import contextlib
import fcntl
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import lancedb
import pytest

from ask_your_library.ingest import add_folder, backup as backup_module
from ask_your_library.ingest.backup import (BackupError, backup, manifest_lines,
                                            restore, verify)
from ask_your_library.ingest.doctor import check_ledger
from ask_your_library.ingest.lock import (IngestBusy, acquire, ingest_lock, lock_path,
                                          read_lock, release)
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


def chat_db(tmp_path, rows=("what is the ledger for",), wal=False):
    """A real SQLite chat database: the backup goes through SQLite's own backup
    API now, so a file of plausible bytes is not a substitute for one."""
    path = tmp_path / "chainlit" / "chat.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(path)) as conn:
        if wal:
            conn.execute("PRAGMA journal_mode=WAL")
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS steps ("id" TEXT, "output" TEXT)')
            conn.executemany("INSERT INTO steps VALUES (?, ?)",
                             [(str(i), text) for i, text in enumerate(rows)])
    return path


def chat_rows(path):
    with contextlib.closing(sqlite3.connect(path)) as conn:
        return [row[0] for row in conn.execute('SELECT "output" FROM steps ORDER BY "id"')]


# --- the lock: the kernel's, not a file whose presence is the lock -----------

def held_by_somebody(db_path) -> bool:
    """Is this index's lock held? Asked the only way that is true by
    construction — by trying to take it on a descriptor of our own. flock is
    per open file description, so this conflicts with a holder in this process
    exactly as it would with one in another."""
    fd = os.open(lock_path(db_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


HOLDER_SCRIPT = """
import sys, time
from ask_your_library.ingest.lock import acquire
acquire(sys.argv[1], command=sys.argv[2])
print("held", flush=True)
time.sleep(600)
"""


def a_holder(db_path, command="ayl-add ~/books"):
    """Another process holding the lock, ready when it says so."""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER_SCRIPT, str(db_path), command],
        stdout=subprocess.PIPE, text=True)
    assert process.stdout.readline().strip() == "held"
    return process


def test_an_ingest_drops_the_lock_at_the_end(built, tmp_path):
    """The file stays — it is not the lock, only the thing the lock is held on
    — and the note in it is truncated away, so a reader of a lock nobody holds
    sees nothing rather than the last holder's line."""
    assert not held_by_somebody(tmp_path / "db")
    assert read_lock(tmp_path / "db") == {}


def test_a_second_writer_is_refused_while_the_first_holds_the_lock(built, tmp_path):
    with ingest_lock(tmp_path / "db", command="pretend ingest"):
        with pytest.raises(IngestBusy) as error:
            add_folder.add_books(add_folder.read_folder(built), "ollama", tmp_path / "db", built)
    assert "an ingest is writing" in str(error.value)
    assert "pretend ingest" in str(error.value)
    # and no instruction to delete anything: deleting the file releases nothing
    assert "delete" not in str(error.value)


def test_exactly_one_of_two_contending_processes_wins(tmp_path):
    """The race the old scheme could not close: two contenders that both read
    the same stale lock, the first replacing it and the second unlinking the
    first's live one. There is nothing to read and nothing to replace now."""
    db_path = tmp_path / "db"
    db_path.mkdir()
    holder = a_holder(db_path)
    try:
        with pytest.raises(IngestBusy) as error:
            acquire(db_path)
        assert str(holder.pid) in str(error.value)
    finally:
        holder.kill()
        holder.wait()


def test_the_lock_dies_with_its_holder_and_needs_no_reclaim(tmp_path):
    """SIGKILL runs no code of ours — no `finally`, no unlink, no recorded pid
    consulted. The kernel closes the descriptor and the lock is simply gone,
    which is the whole reason for holding it this way."""
    db_path = tmp_path / "db"
    db_path.mkdir()
    holder = a_holder(db_path)
    assert held_by_somebody(db_path)

    holder.kill()
    holder.wait()

    acquire(db_path, command="the next run")          # no reclaim, no warning, no delay
    try:
        assert read_lock(db_path)["pid"] == os.getpid()
    finally:
        release(db_path)


def test_an_unreadable_note_does_not_affect_taking_the_lock(tmp_path):
    """The payload is for the message and nothing else. Under the old scheme
    an unparseable file was a decision — stale, or refuse — and both answers
    were wrong for somebody."""
    db_path = tmp_path / "db"
    db_path.mkdir()
    lock_path(db_path).write_bytes(b"not json at all")

    acquire(db_path, command="ayl-add ~/books")
    try:
        assert read_lock(db_path)["command"] == "ayl-add ~/books"   # overwritten, not consulted
    finally:
        release(db_path)


def test_a_note_from_another_host_only_changes_the_words(tmp_path):
    """flock on a network share is the share's to implement. The refusal says
    so instead of implying a guarantee this code cannot make."""
    from ask_your_library.ingest import lock as lock_module

    message = lock_module.busy_message(tmp_path / "db", {"pid": 7, "host": "some-other-laptop"},
                                       "back up")
    assert "shared volume" in message and "some-other-laptop" in message


def test_two_spellings_of_one_index_are_one_lock(tmp_path):
    """`~/index`, `./index` and a symlink to it must exclude each other, or the
    lock is decoration."""
    real = tmp_path / "db"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real, target_is_directory=True)
    assert lock_path(link) == lock_path(real)

    with ingest_lock(real, command="ayl-add ~/books"):
        with pytest.raises(IngestBusy):
            acquire(link)


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
    """It lives BESIDE the index now, so this holds by construction — asserted
    anyway, because the reason it moved there was a different one (surviving a
    rename), and nothing should quietly put it back inside."""
    target = backup(tmp_path / "db", tmp_path / "backups")
    names = [entry["path"] for entry in
             json.loads((target / "MANIFEST.json").read_text())["files"]]
    assert not any("ayl-ingest" in name for name in names)


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

    assert not held_by_somebody(tmp_path / "db")
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
    assert not held_by_somebody(tmp_path / "db")


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


# --- the chat database is one consistent snapshot ----------------------------

def test_the_chat_db_is_copied_through_sqlites_own_backup(built, tmp_path):
    """A WAL database is two files plus a shared-memory index, and copying them
    one after another is three reads at three different moments — the result can
    hold a page the log has already superseded. `Connection.backup()` takes the
    snapshot the engine itself calls consistent, and produces ONE file, which is
    also what makes the per-file digest mean anything."""
    live = chat_db(tmp_path, rows=("committed one", "committed two"), wal=True)

    # a second connection with a write in flight and NOT committed
    with contextlib.closing(sqlite3.connect(live)) as writer:
        writer.execute("INSERT INTO steps VALUES ('99', 'never committed')")
        target = backup(tmp_path / "db", tmp_path / "backups", chat_db=live)
        writer.rollback()

    copied = target / "chat.db"
    assert copied.is_file()
    assert not (target / "chat.db-wal").exists() and not (target / "chat.db-shm").exists()
    with contextlib.closing(sqlite3.connect(copied)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert chat_rows(copied) == ["committed one", "committed two"]
    # and the one file is what the manifest digests
    files = [entry["path"] for entry in
             json.loads((target / "MANIFEST.json").read_text())["files"]]
    assert "chat.db" in files and not any(name.startswith("chat.db-") for name in files)


def test_a_chat_db_that_is_not_a_database_does_not_lose_the_index_backup(built, tmp_path,
                                                                        capsys):
    broken = tmp_path / "chainlit" / "broken.db"
    broken.parent.mkdir(parents=True, exist_ok=True)
    broken.write_bytes(b"SQLite format 3\x00 but not really")

    target = backup(tmp_path / "db", tmp_path / "backups", chat_db=broken)

    manifest = json.loads((target / "MANIFEST.json").read_text())
    assert manifest["chat_db_error"] and manifest["source"]["chat_db"] is None
    assert not (target / "chat.db").exists()
    assert manifest["tables"]["transcripts_ollama"] > 0        # the index is there
    assert verify(target) == []
    assert any("NOT copied" in line for line in manifest_lines(target, manifest))


def test_a_restored_chat_db_is_a_database_again(built, tmp_path):
    live = chat_db(tmp_path, rows=("keep me",), wal=True)
    target = backup(tmp_path / "db", tmp_path / "backups", chat_db=live)
    import shutil
    shutil.rmtree(tmp_path / "db")

    restore(target, tmp_path / "db", chat_db=tmp_path / "back" / "chat.db")

    # no journal beside it: `backup()` writes one file, and a stale sidecar of
    # the database being replaced would be read as this one's journal
    assert not (tmp_path / "back" / "chat.db-wal").exists()
    assert chat_rows(tmp_path / "back" / "chat.db") == ["keep me"]


# --- the restore is staged, locked and reversible ----------------------------

def test_a_restore_into_a_fresh_path_still_holds_the_lock(built, tmp_path):
    """It used to take none at all, so an ingest could start into a directory
    that was half-restored."""
    target = backup(tmp_path / "db", tmp_path / "backups")
    fresh = tmp_path / "fresh"

    with ingest_lock(fresh, command="ayl-add ~/books"):
        with pytest.raises(IngestBusy):
            restore(target, fresh)

    assert not fresh.exists() or list(fresh.iterdir()) == []


def test_the_lock_is_held_across_the_swap_and_survives_the_rename(built, tmp_path):
    """The lock lives beside the index, so renaming the directory does not
    carry it away and leave the name it guards unguarded mid-swap."""
    assert lock_path(tmp_path / "db").parent == tmp_path        # beside, not inside
    seen = {}
    real_copy = backup_module._copy_tree

    def watching(source, target, skip=frozenset()):
        seen["locked_during_copy"] = held_by_somebody(tmp_path / "db")
        return real_copy(source, target, skip)

    target = backup(tmp_path / "db", tmp_path / "backups")
    backup_module._copy_tree = watching
    try:
        restore(target, tmp_path / "db", force=True)
    finally:
        backup_module._copy_tree = real_copy
    assert seen["locked_during_copy"] is True
    assert not held_by_somebody(tmp_path / "db")                 # and released at the end


def test_a_failure_mid_copy_leaves_the_old_index_exactly_where_it_was(built, tmp_path,
                                                                     monkeypatch):
    """The copy is staged BESIDE the target and only a complete one is swapped
    in, so a full disk or an interrupt costs nothing."""
    target = backup(tmp_path / "db", tmp_path / "backups")
    before = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows()
    monkeypatch.setattr(backup_module, "_copy_tree",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk went away")))

    with pytest.raises(OSError, match="disk went away"):
        restore(target, tmp_path / "db", force=True)

    assert lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows() == before
    assert not list(tmp_path.glob("db.replaced-*"))     # nothing was moved aside
    assert not list(tmp_path.glob("db.restoring-*"))    # and nothing half-written is left


def test_a_failed_swap_puts_the_moved_aside_index_back(built, tmp_path, monkeypatch):
    target = backup(tmp_path / "db", tmp_path / "backups")
    before = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows()
    real_rename = Path.rename

    def fail_on_publish(self, other):
        if ".restoring-" in self.name:
            raise OSError("cross-device link")
        return real_rename(self, other)

    monkeypatch.setattr(Path, "rename", fail_on_publish)
    with pytest.raises(OSError, match="cross-device link"):
        restore(target, tmp_path / "db", force=True)
    monkeypatch.undo()

    assert (tmp_path / "db").is_dir()
    assert lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows() == before
    assert not list(tmp_path.glob("db.replaced-*")) and not list(tmp_path.glob("db.restoring-*"))


# --- a tree that cannot be copied faithfully ---------------------------------

def test_a_symlink_inside_the_index_is_named_and_refused(built, tmp_path):
    """`copytree(symlinks=False)` FOLLOWS a link and writes what it points at,
    while the digests skip links entirely — so a linked file would be in the
    backup and in no digest, and the manifest would describe a set of files
    that is not the set of files in the directory. A link pointing outside the
    index would pull whatever it names into the copy."""
    secret = tmp_path / "outside.txt"
    secret.write_text("not part of any index")
    (tmp_path / "db" / "pointer.txt").symlink_to(secret)

    with pytest.raises(BackupError) as error:
        backup(tmp_path / "db", tmp_path / "backups")

    assert "pointer.txt" in str(error.value) and "symlink" in str(error.value)
    assert not (tmp_path / "backups").exists()


def test_a_symlinked_index_ROOT_is_still_fine(built, tmp_path):
    """Only links INSIDE the tree are refused: `data/lancedb` is itself a
    symlink in this project's own dev checkout, and following the path you were
    handed is the point."""
    link = tmp_path / "linked-db"
    link.symlink_to(tmp_path / "db", target_is_directory=True)
    assert verify(backup(link, tmp_path / "backups")) == []


def test_a_symlink_planted_in_a_backup_fails_verification_and_the_restore(built, tmp_path):
    target = backup(tmp_path / "db", tmp_path / "backups")
    (target / "lancedb" / "sneaky").symlink_to(tmp_path / "db")

    assert any("symlink" in problem for problem in verify(target))
    with pytest.raises(BackupError):
        restore(target, tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


# --- the chat restore is staged too ------------------------------------------

def test_a_failed_chat_restore_leaves_the_live_history_alone(built, tmp_path, monkeypatch):
    """`Connection.backup()` writes INTO a database, so the target used to be
    deleted first — and a failure there destroyed the reader's history with
    nothing to put back."""
    live = chat_db(tmp_path, rows=("the history I still have",), wal=True)
    target = backup(tmp_path / "db", tmp_path / "backups", chat_db=live)
    calls = {"n": 0}
    real = backup_module.copy_chat_db

    def fail_on_the_restore(source, dest):
        calls["n"] += 1
        raise OSError("disk went away")

    monkeypatch.setattr(backup_module, "copy_chat_db", fail_on_the_restore)
    with pytest.raises(OSError, match="disk went away"):
        restore(target, tmp_path / "db", chat_db=live, force=True)
    monkeypatch.setattr(backup_module, "copy_chat_db", real)

    assert calls["n"] == 1
    assert chat_rows(live) == ["the history I still have"]
    assert not list(live.parent.glob("chat.db.restoring-*"))


def test_the_chat_restore_replaces_by_rename(built, tmp_path):
    live = chat_db(tmp_path, rows=("old history",), wal=True)
    target = backup(tmp_path / "db", tmp_path / "backups", chat_db=live)
    with contextlib.closing(sqlite3.connect(live)) as conn:
        with conn:
            conn.execute("INSERT INTO steps VALUES ('9', 'written after the backup')")
    assert chat_rows(live) == ["old history", "written after the backup"]

    restore(target, tmp_path / "db", chat_db=live, force=True)

    assert chat_rows(live) == ["old history"]
    assert not list(live.parent.glob("chat.db.restoring-*"))
