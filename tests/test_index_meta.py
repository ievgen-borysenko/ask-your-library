"""Embedding-index fingerprint checks with an in-memory fake LanceDB."""
import pyarrow as pa

from ask_your_library import index_meta


class FakeTable:
    def __init__(self, rows, dims):
        self.rows = rows
        self.schema = pa.schema([("vector", pa.list_(pa.float32(), dims))])

    def search(self):
        return self

    def where(self, expr):
        key = expr.split("'")[1]
        self._filtered = [r for r in self.rows if r["table"] == key]
        return self

    def limit(self, n):
        return self

    def to_list(self):
        return self._filtered

    def delete(self, expr):
        key = expr.split("'")[1]
        self.rows[:] = [r for r in self.rows if r["table"] != key]

    def add(self, rows):
        self.rows.extend(rows)


class FakeDB:
    def __init__(self, dims=1024):
        self.tables = {"cards_ollama": FakeTable([], dims)}

    def list_tables(self):
        return list(self.tables)

    def open_table(self, name):
        return self.tables[name]

    def create_table(self, name, rows):
        self.tables[name] = FakeTable(list(rows), 1)
        return self.tables[name]


def test_dims_mismatch_is_rejected_even_without_stamp():
    db = FakeDB(dims=1024)
    problem = index_meta.check_index(db, "cards_ollama", model="text-embedding-3-small", dims=1536)
    assert problem and "1024" in problem and "1536" in problem


def test_unstamped_table_with_matching_dims_passes():
    db = FakeDB(dims=1024)
    assert index_meta.check_index(db, "cards_ollama", model="bge-m3", dims=1024) is None


def test_stamped_table_rejects_a_different_model_with_same_dims():
    db = FakeDB(dims=1024)
    index_meta.write_index_meta(db, "cards_ollama", "ollama", "bge-m3", 1024)
    assert index_meta.check_index(db, "cards_ollama", "bge-m3", 1024) is None
    problem = index_meta.check_index(db, "cards_ollama", "nomic-embed-text", 1024)
    assert problem and "bge-m3" in problem


def test_restamping_replaces_the_previous_row():
    db = FakeDB(dims=1024)
    index_meta.write_index_meta(db, "cards_ollama", "ollama", "bge-m3", 1024)
    index_meta.write_index_meta(db, "cards_ollama", "ollama", "other", 1024)
    rows = db.tables[index_meta.META_TABLE].rows
    assert [r["model"] for r in rows] == ["other"]


# --- the two fields ADR-024 added, against a real LanceDB --------------------

def test_a_stamp_carries_the_chunker_and_the_schema_version(tmp_path):
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                chunker="sentence-pack-1")
    row = index_meta.read_index_meta(db, "transcripts_ollama")
    assert row["chunker"] == "sentence-pack-1"
    assert row["schema_version"] == index_meta.SCHEMA_VERSION
    assert row["model"] == "bge-m3" and row["dims"] == 1024


def test_a_fingerprint_table_written_before_the_two_fields_is_widened_not_narrowed(tmp_path):
    """A `_index_meta` from an older ingest has five columns, and LanceDB will
    not take a wider row into it. Dropping the new fields to fit would make the
    stamp lie about itself, so the (tiny, vectorless) table is rewritten."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    db.create_table(index_meta.META_TABLE, [
        {"table": "cards_ollama", "backend": "ollama", "model": "bge-m3", "dims": 1024,
         "created": "2026-01-01T00:00:00"}])

    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                chunker="sentence-pack-1")

    new = index_meta.read_index_meta(db, "transcripts_ollama")
    assert new["chunker"] == "sentence-pack-1" and new["schema_version"] == 2
    # the older row survived, and says what is true of it: nothing recorded
    # which chunker wrote that table
    old = index_meta.read_index_meta(db, "cards_ollama")
    assert old["model"] == "bge-m3" and old["created"] == "2026-01-01T00:00:00"
    assert old["chunker"] == "" and old["schema_version"] == 1


def test_readers_tolerate_a_stamp_without_the_new_fields(tmp_path):
    """No refusal in this release: the policy for a chunker mismatch is warn on
    read, refuse on write (#27), and neither is implemented yet."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama", [{"vector": [0.0] * 4, "text": "t"}])
    db.create_table(index_meta.META_TABLE, [
        {"table": "transcripts_ollama", "backend": "ollama", "model": "bge-m3", "dims": 4,
         "created": "2026-01-01T00:00:00"}])
    assert index_meta.check_index(db, "transcripts_ollama", "bge-m3", 4) is None
    assert "chunker" not in index_meta.read_index_meta(db, "transcripts_ollama")
