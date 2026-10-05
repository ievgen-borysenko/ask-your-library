"""An interrupted publish copy never costs the only complete copy (ADR-031).

LanceDB OSS has no rename, so publishing a rebuild drops the live table and
copies staging over. A copy interrupted part way, by an exception or a kill,
leaves the live name LISTED with data files and no committed version: it does
not open. Recovery used to read the list alone, took the listed name for a live
table and dropped staging, the one complete copy. The states here are made the
way the review of 2026-10-04 made them: the installed LanceDB in a temporary
directory, a reader that raises part way, and a child process killed mid-copy.
No network, no model.
"""
import os
import signal
import subprocess
import sys

import lancedb
import pytest

from ask_your_library.ingest import add_folder, publish
from ask_your_library.ingest.add_folder import IngestError
from test_add_folder import PARA, FakeEmbedder, write

ROWS = 120


def rows(note, n, start=0):
    return [{"note": note, "chunk_id": f"{note}/{i}", "text": f"text-{i}", "vector": [float(i), 1.0]}
            for i in range(start, start + n)]


def failing_after(monkeypatch, batches: int, error=RuntimeError("disk full")):
    """`table_batches` that yields `batches` batches of 10 rows, then raises."""
    original = publish.table_batches

    def broken(table, batch_rows=publish.COPY_BATCH_ROWS):
        for number, batch in enumerate(original(table, 10)):
            if number == batches:
                raise error
            yield batch
    monkeypatch.setattr(publish, "table_batches", broken)
    return original


def broken_live(db, monkeypatch, name="t"):
    """The state an interrupted publish copy leaves: staging complete, the
    live name listed, nothing behind it that opens."""
    db.create_table(name + publish.STAGING_SUFFIX, rows("a", ROWS))
    original = failing_after(monkeypatch, 3)
    with pytest.raises(Exception):
        publish.copy_table(db, name + publish.STAGING_SUFFIX, name)
    monkeypatch.setattr(publish, "table_batches", original)
    assert name in publish.table_names(db) and not publish.opens(db, name)


def watch_drops(db):
    """Fail the moment staging is dropped while its live table does not open."""
    drop = db.drop_table
    dropped = []

    def guarded(name, *args, **kwargs):
        if name.endswith(publish.STAGING_SUFFIX):
            live = name[:-len(publish.STAGING_SUFFIX)]
            assert publish.opens(db, live), f"{name} dropped while {live} cannot be opened"
        dropped.append(name)
        return drop(name, *args, **kwargs)
    db.drop_table = guarded
    return dropped


# --- recovery ----------------------------------------------------------------

def test_after_an_exception_mid_copy_recovery_promotes_staging_with_every_row(tmp_path,
                                                                              monkeypatch):
    db = lancedb.connect(tmp_path)
    broken_live(db, monkeypatch)
    dropped = watch_drops(db)

    publish.recover_staging(db, "t")

    assert db.open_table("t").count_rows() == ROWS
    assert "t__staging" not in publish.table_names(db)
    assert dropped == ["t", "t__staging"]          # the broken live name first


CHILD = r"""
import importlib.util, sys, time, lancedb
spec = importlib.util.spec_from_file_location("publish", sys.argv[1])
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)
original = publish.table_batches
def slow(table, batch_rows=publish.COPY_BATCH_ROWS):
    for number, batch in enumerate(original(table, 10)):
        if number == 3:
            print("COPYING", flush=True)
            time.sleep(60)
        yield batch
publish.table_batches = slow
publish.copy_table(lancedb.connect(sys.argv[2]), "t__staging", "t")
"""


def test_after_a_kill_mid_copy_recovery_promotes_staging_with_every_row(tmp_path):
    """SIGKILL: no handler runs, so the partial table is whatever the store had
    written. The child loads publish.py by its path, so it reads no setting."""
    db = lancedb.connect(tmp_path)
    db.create_table("t__staging", rows("a", ROWS))
    child = subprocess.Popen([sys.executable, "-c", CHILD, publish.__file__, str(tmp_path)],
                             stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "COPYING"
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait()
        child.stdout.close()
    assert child.returncode == -signal.SIGKILL
    assert "t" in publish.table_names(db) and not publish.opens(db, "t")
    assert os.listdir(tmp_path / "t.lance") == ["data"]     # files, no committed version
    dropped = watch_drops(db)

    publish.recover_staging(db, "t")

    assert db.open_table("t").count_rows() == ROWS
    assert "t__staging" not in publish.table_names(db)
    assert dropped == ["t", "t__staging"]


def test_an_interrupted_promote_keeps_staging_for_the_next_recovery(tmp_path, monkeypatch):
    """The same window inside recovery's own copy."""
    db = lancedb.connect(tmp_path)
    broken_live(db, monkeypatch)
    dropped = watch_drops(db)
    original = failing_after(monkeypatch, 5)
    with pytest.raises(Exception):
        publish.recover_staging(db, "t")
    assert db.open_table("t__staging").count_rows() == ROWS
    assert not publish.opens(db, "t")

    monkeypatch.setattr(publish, "table_batches", original)
    publish.recover_staging(db, "t")
    assert db.open_table("t").count_rows() == ROWS
    assert dropped[-1] == "t__staging"


def test_when_neither_table_opens_nothing_is_dropped(tmp_path, monkeypatch):
    db = lancedb.connect(tmp_path)
    db.create_table("source", rows("a", ROWS))
    original = failing_after(monkeypatch, 2)
    for target in ("t", "t__staging"):
        with pytest.raises(Exception):
            publish.copy_table(db, "source", target)
    monkeypatch.setattr(publish, "table_batches", original)
    dropped = watch_drops(db)

    with pytest.raises(publish.RecoveryError, match="neither t nor t__staging can be opened"):
        publish.recover_staging(db, "t")
    assert dropped == []
    assert {"t", "t__staging"} <= set(publish.table_names(db))


def test_a_stale_staging_beside_a_live_table_that_opens_is_still_dropped(tmp_path):
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("a", 3))
    db.create_table("t__staging", rows("b", 1))     # a staging build that did not finish
    publish.recover_staging(db, "t")
    assert db.open_table("t").count_rows() == 3
    assert "t__staging" not in publish.table_names(db)


# --- the rebuild's own publish copy --------------------------------------------

@pytest.mark.parametrize("interruption", ["exception", "ctrl-c"])
def test_an_interrupted_publish_copy_keeps_staging_and_drops_the_partial_table(
        tmp_path, monkeypatch, interruption):
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("old", 3))
    dropped = watch_drops(db)
    original = failing_after(monkeypatch, 4)
    if interruption == "ctrl-c":
        # LanceDB turns anything raised inside the reader into a RuntimeError;
        # a Ctrl-C is delivered to the copying thread instead, after the store
        # has written part of the table
        copy = publish.copy_table

        def interrupted(*args, **kwargs):
            with pytest.raises(RuntimeError):
                copy(*args, **kwargs)
            raise KeyboardInterrupt
        monkeypatch.setattr(publish, "copy_table", interrupted)
    with pytest.raises(KeyboardInterrupt if interruption == "ctrl-c" else RuntimeError):
        publish.rebuild_table(db, "t", [rows("new", ROWS)])
    monkeypatch.undo()
    monkeypatch.setattr(publish, "table_batches", original)

    assert "t" not in publish.table_names(db)                 # the partial copy is gone
    assert db.open_table("t__staging").count_rows() == ROWS   # the complete one is not
    publish.recover_staging(db, "t")
    assert db.open_table("t").count_rows() == ROWS
    assert dropped.count("t__staging") == 1


def test_a_rebuild_over_a_broken_live_table_does_not_drop_the_staging_copy_first(tmp_path,
                                                                                 monkeypatch):
    """`rebuild_table` used to drop any leftover staging on its way in."""
    db = lancedb.connect(tmp_path)
    broken_live(db, monkeypatch)
    watch_drops(db)
    publish.rebuild_table(db, "t", [rows("new", 4)])
    assert db.open_table("t").count_rows() == 4


# --- `ayl add` over the interrupted state ---------------------------------------

TABLE = "transcripts_ollama"


def build(tmp_path, monkeypatch, model="fake-embed"):
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder(model))
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", PARA * 4)
    return add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db",
                                folder), folder


def interrupt_the_publish(db, monkeypatch):
    """Leave TABLE as an interrupted publish copy leaves it: complete in
    staging, listed and unreadable under its own name."""
    publish.copy_table(db, TABLE, TABLE + publish.STAGING_SUFFIX)
    count = db.open_table(TABLE).count_rows()
    db.drop_table(TABLE)
    original = failing_after(monkeypatch, 0)
    with pytest.raises(Exception):
        publish.copy_table(db, TABLE + publish.STAGING_SUFFIX, TABLE)
    monkeypatch.setattr(publish, "table_batches", original)
    assert not publish.opens(db, TABLE)
    return count


def test_ayl_add_over_an_interrupted_publish_recovers_and_writes(tmp_path, monkeypatch):
    """Before ADR-031 the write guards opened the live name and the run ended
    in a traceback before recovery; recovery itself would have dropped staging."""
    counts, folder = build(tmp_path, monkeypatch)
    db = lancedb.connect(tmp_path / "db")
    before = interrupt_the_publish(db, monkeypatch)

    write(folder, "Sea Notes - B. Mate.txt", PARA * 4 + " The tide turned at four.")
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)

    table = lancedb.connect(tmp_path / "db").open_table(TABLE)
    assert table.count_rows() > before
    assert TABLE + publish.STAGING_SUFFIX not in publish.table_names(db)


def test_the_write_guards_judge_the_staged_copy_before_recovery_promotes_it(tmp_path,
                                                                           monkeypatch):
    """Mid-swap, the guards used to see no live table and let the run go on;
    recovery then promoted staging and the write went in unchecked. A table
    built by another embedding model is refused, and nothing is written."""
    build(tmp_path, monkeypatch)
    db = lancedb.connect(tmp_path / "db")
    interrupt_the_publish(db, monkeypatch)
    names = sorted(publish.table_names(db))

    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder("other-embed"))
    folder = tmp_path / "books"
    with pytest.raises(IngestError, match="was built with 'fake-embed'"):
        add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    assert sorted(publish.table_names(db)) == names        # the refusal wrote nothing
    assert not publish.opens(db, TABLE)
