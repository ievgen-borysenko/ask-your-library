"""Crash-safe table publishing against a real local LanceDB."""
import lancedb
import pytest

from ask_your_library.ingest import publish


def rows(note, n, tag="v1"):
    return [{"note": note, "chunk_id": f"{note}/{i}", "text": f"{tag}-{i}", "vector": [float(i), 1.0]}
            for i in range(n)]


def test_rebuild_keeps_old_table_when_build_fails(tmp_path):
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("a", 3))

    def broken():
        yield rows("b", 2)
        raise RuntimeError("embedder down")

    with pytest.raises(RuntimeError):
        publish.rebuild_table(db, "t", broken())
    assert db.open_table("t").count_rows() == 3
    assert "t__staging" not in publish.table_names(db)


def test_rebuild_replaces_table_and_cleans_staging(tmp_path):
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("a", 3))
    publish.rebuild_table(db, "t", [rows("b", 2), rows("c", 4)])
    assert db.open_table("t").count_rows() == 6
    assert "t__staging" not in publish.table_names(db)


def test_recover_promotes_completed_staging_when_table_missing(tmp_path):
    db = lancedb.connect(tmp_path)
    db.create_table("t__staging", rows("a", 5))   # crash after old 't' was dropped
    publish.recover_staging(db, "t")
    assert db.open_table("t").count_rows() == 5
    assert "t__staging" not in publish.table_names(db)


def test_recover_drops_stale_staging_when_table_exists(tmp_path):
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("a", 3))
    db.create_table("t__staging", rows("b", 1))   # crash mid-build
    publish.recover_staging(db, "t")
    assert db.open_table("t").count_rows() == 3
    assert "t__staging" not in publish.table_names(db)


def test_rebuild_without_rows_raises_no_rows_error_and_keeps_the_old_table(tmp_path):
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("a", 3))
    with pytest.raises(publish.NoRowsError):
        publish.rebuild_table(db, "t", [[], []])
    assert db.open_table("t").count_rows() == 3       # nothing was dropped
    assert "t__staging" not in publish.table_names(db)
    assert isinstance(publish.NoRowsError("x"), ValueError)   # old callers still catch it


def test_publishing_streams_the_staging_table_instead_of_materializing_it(tmp_path,
                                                                          monkeypatch):
    # to_arrow() on staging would hold the whole new index in memory at the
    # moment of the swap, which is exactly what the batched rebuild avoids.
    db = lancedb.connect(tmp_path)

    def no_to_arrow(self, *args, **kwargs):
        raise AssertionError("the staging table was materialized with to_arrow()")

    monkeypatch.setattr(lancedb.table.LanceTable, "to_arrow", no_to_arrow)
    publish.rebuild_table(db, "t", [rows("a", 3), rows("b", 4)])
    assert db.open_table("t").count_rows() == 7


def test_copy_table_preserves_a_fixed_size_vector_column(tmp_path):
    # The agent's tables have a fixed-size-list vector column; a copy that went
    # through Python floats could come back as a variable-size list.
    db = lancedb.connect(tmp_path)
    db.create_table("t", rows("a", 5))
    assert db.open_table("t").schema.field("vector").type.list_size == 2
    publish.copy_table(db, "t", "copy", batch_rows=2)
    copied = db.open_table("copy")
    assert copied.count_rows() == 5
    assert copied.schema == db.open_table("t").schema


def test_recover_promotes_a_large_staging_table_in_batches(tmp_path, monkeypatch):
    db = lancedb.connect(tmp_path)
    db.create_table("t__staging", rows("a", 25))

    def no_to_arrow(self, *args, **kwargs):
        raise AssertionError("the staging table was materialized with to_arrow()")

    monkeypatch.setattr(lancedb.table.LanceTable, "to_arrow", no_to_arrow)
    publish.recover_staging(db, "t")
    assert db.open_table("t").count_rows() == 25
    assert "t__staging" not in publish.table_names(db)


def test_upsert_replaces_a_books_rows_without_duplicates(tmp_path):
    db = lancedb.connect(tmp_path)
    table = db.create_table("t", rows("a", 3) + rows("b", 2))
    publish.upsert_book_rows(table, "a", rows("a", 4, tag="v2"))
    got = table.search().where("note = 'a'").limit(100).to_list()
    assert len(got) == 4 and all(r["text"].startswith("v2") for r in got)
    assert table.count_rows() == 6
