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
