"""Embedding-index fingerprint checks with an in-memory fake LanceDB."""
import pyarrow as pa
import pytest

from ask_your_library import index_meta


class FakeTable:
    def __init__(self, rows, dims, columns=()):
        self.rows = rows
        # The columns matter now: `write_index_meta` reads the fingerprint
        # table's own schema to decide whether a row fits it, rather than
        # finding out by attempting the write.
        self.schema = pa.schema([("vector", pa.list_(pa.float32(), dims))]
                                + [(name, pa.string()) for name in columns])

    def search(self):
        return self

    def where(self, expr):
        key = expr.split("'")[1]
        self._filtered = [r for r in self.rows if r["table"] == key]
        return self

    def limit(self, n):
        return self

    def to_list(self):
        return getattr(self, "_filtered", self.rows)

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
        rows = list(rows)
        self.tables[name] = FakeTable(rows, 1, columns=tuple(rows[0]) if rows else ())
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

def _table_with_ledger_columns(db, name, dims=1024):
    return db.create_table(name, [{"chunk_id": "a/1", "note": "a", "book": "A — B",
                                   "source": "local:a", "section": "One", "text": "t",
                                   "vector": [0.0] * dims, "book_id": "id", "book_rev": "rev"}])


def _legacy_table(db, name, dims=1024):
    return db.create_table(name, [{"chunk_id": "a/1", "note": "a", "book": "A — B",
                                   "source": "local:a", "section": "One", "text": "t",
                                   "vector": [0.0] * dims}])


def test_a_stamp_carries_the_chunker_and_the_schema_version(tmp_path):
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _table_with_ledger_columns(db, "transcripts_ollama")
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
    _table_with_ledger_columns(db, "transcripts_ollama")

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
    """A five-column fingerprint row — every index built before ADR-024 — is
    read without a word: the embedder check passes on it, and the chunker
    policy has nothing to compare (see the `absent` tests below)."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama", [{"vector": [0.0] * 4, "text": "t"}])
    db.create_table(index_meta.META_TABLE, [
        {"table": "transcripts_ollama", "backend": "ollama", "model": "bge-m3", "dims": 4,
         "created": "2026-01-01T00:00:00"}])
    assert index_meta.check_index(db, "transcripts_ollama", "bge-m3", 4) is None
    assert "chunker" not in index_meta.read_index_meta(db, "transcripts_ollama")


def _mid_widening(tmp_path):
    """An index whose fingerprint table is mid-rebuild: the staged copy is
    complete, the live table is already gone."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    db.create_table(index_meta.META_TABLE + "__staging", [
        {"table": "cards_ollama", "backend": "ollama", "model": "bge-m3", "dims": 1024,
         "created": "2026-01-01T00:00:00", "chunker": "", "schema_version": 1},
        {"table": "transcripts_ollama", "backend": "ollama", "model": "bge-m3", "dims": 1024,
         "created": "2026-01-02T00:00:00", "chunker": "sentence-pack-1", "schema_version": 2}])
    return db


def test_a_reader_reads_an_interrupted_widening_without_touching_it(tmp_path):
    """A reader never recovers. Recovery drops or promotes a table, every search
    goes through `read_index_meta`, and a reader that recovered would race the
    `ayl-add` that is mid-widening — dropping the staging table it is filling,
    and leaving the index unstamped, which is the state `ayl-add` then refuses
    to write to."""
    from ask_your_library.ingest.publish import table_names

    db = _mid_widening(tmp_path)
    row = index_meta.read_index_meta(db, "transcripts_ollama")
    assert row is not None and row["chunker"] == "sentence-pack-1"
    assert index_meta.read_index_meta(db, "cards_ollama")["model"] == "bge-m3"
    # neither dropped nor promoted: the staging table is exactly as it was
    assert index_meta.META_TABLE + "__staging" in table_names(db)
    assert index_meta.META_TABLE not in table_names(db)


def test_the_live_table_wins_over_a_staging_table_left_behind(tmp_path):
    db = _mid_widening(tmp_path)
    db.create_table(index_meta.META_TABLE, [
        {"table": "transcripts_ollama", "backend": "ollama", "model": "current-model",
         "dims": 1024, "created": "2026-02-02T00:00:00", "chunker": "sentence-pack-1",
         "schema_version": 2}])
    assert index_meta.read_index_meta(db, "transcripts_ollama")["model"] == "current-model"


def test_the_write_path_is_what_finishes_an_interrupted_widening(tmp_path):
    from ask_your_library.ingest.publish import table_names

    db = _mid_widening(tmp_path)
    _table_with_ledger_columns(db, "transcripts_ollama")
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                chunker="sentence-pack-1")
    assert index_meta.META_TABLE + "__staging" not in table_names(db)
    assert index_meta.read_index_meta(db, "cards_ollama")["created"] == "2026-01-01T00:00:00"
    assert index_meta.read_index_meta(db, "transcripts_ollama")["schema_version"] == 2


def test_the_widening_keeps_every_other_row_when_it_rewrites_the_table(tmp_path):
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    db.create_table(index_meta.META_TABLE, [
        {"table": "cards_ollama", "backend": "ollama", "model": "bge-m3", "dims": 1024,
         "created": "2026-01-01T00:00:00"},
        {"table": "transcripts_openrouter", "backend": "openrouter", "model": "te3", "dims": 1536,
         "created": "2026-01-02T00:00:00"}])
    _table_with_ledger_columns(db, "transcripts_ollama")

    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                chunker="sentence-pack-1")

    assert index_meta.read_index_meta(db, "cards_ollama")["created"] == "2026-01-01T00:00:00"
    assert index_meta.read_index_meta(db, "transcripts_openrouter")["dims"] == 1536
    assert index_meta.read_index_meta(db, "transcripts_ollama")["schema_version"] == 2


def test_the_check_before_a_search_does_not_recover_either(tmp_path):
    """`check_index` is what `library.open_table` runs before the first search
    of a process, and what `preflight` runs before an interface starts. Both are
    readers."""
    import lancedb

    from ask_your_library.ingest.publish import table_names

    db = _mid_widening(tmp_path)
    db.create_table("transcripts_ollama", [{"vector": [0.0] * 1024, "text": "t"}])
    assert index_meta.check_index(db, "transcripts_ollama", "bge-m3", 1024) is None
    assert index_meta.META_TABLE + "__staging" in table_names(db)


# --- the version is a claim about the rows, so it is read from them ----------

def test_a_legacy_table_is_stamped_version_1_not_the_current_shape(tmp_path):
    """The version says what a reader must know to read the rows. Stamping an
    unmigrated table with the current number is worse than not stamping it: it
    claims columns the rows do not have, and the claim is what a later refusal
    (#27) would act on."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _legacy_table(db, "transcripts_ollama")
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                chunker="legacy")
    assert index_meta.read_index_meta(db, "transcripts_ollama")["schema_version"] == 1


def test_the_cards_table_is_stamped_version_1_because_it_never_gains_the_columns(tmp_path):
    """A card is a distillate of a book and the ledger's unit is the book, so no
    card row carries a `book_id` — by design, not by omission."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _legacy_table(db, "cards_ollama")
    index_meta.write_index_meta(db, "cards_ollama", "ollama", "bge-m3", 1024,
                                chunker="sentence-pack-1")
    assert index_meta.read_index_meta(db, "cards_ollama")["schema_version"] == 1


def test_a_migrated_table_is_stamped_the_current_version(tmp_path):
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _table_with_ledger_columns(db, "transcripts_ollama")
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024)
    assert index_meta.read_index_meta(db, "transcripts_ollama")["schema_version"] == \
        index_meta.SCHEMA_VERSION


def test_a_caller_may_still_name_the_version(tmp_path):
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _legacy_table(db, "transcripts_ollama")
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                schema_version=7)
    assert index_meta.read_index_meta(db, "transcripts_ollama")["schema_version"] == 7


def test_a_failure_while_staging_the_widening_leaves_the_live_table_intact(tmp_path,
                                                                           monkeypatch):
    """The window the review named: the live fingerprint table must not be
    touched until a complete replacement exists, or a failure there leaves an
    index that looks unstamped — which `ayl-add` then refuses to write to."""
    import lancedb

    from ask_your_library.ingest.publish import table_names

    db = lancedb.connect(tmp_path / "db")
    before = [
        {"table": "cards_ollama", "backend": "ollama", "model": "bge-m3", "dims": 1024,
         "created": "2026-01-01T00:00:00"},
        {"table": "transcripts_openrouter", "backend": "openrouter", "model": "te3",
         "dims": 1536, "created": "2026-01-02T00:00:00"}]
    db.create_table(index_meta.META_TABLE, before)      # the narrow, pre-ADR-024 shape
    _table_with_ledger_columns(db, "transcripts_ollama")

    real_create = type(db).create_table

    def fail_on_staging(self, name, *args, **kwargs):
        if name.endswith("__staging"):
            raise RuntimeError("disk full")
        return real_create(self, name, *args, **kwargs)

    monkeypatch.setattr(type(db), "create_table", fail_on_staging)
    with pytest.raises(RuntimeError, match="disk full"):
        index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                    chunker="sentence-pack-1")

    monkeypatch.undo()
    # every row still there, still readable, and no staging table left behind
    assert index_meta.META_TABLE in table_names(db)
    assert index_meta.META_TABLE + "__staging" not in table_names(db)
    assert index_meta.read_index_meta(db, "cards_ollama")["created"] == "2026-01-01T00:00:00"
    assert index_meta.read_index_meta(db, "transcripts_openrouter")["dims"] == 1536
    # and the writer can simply try again
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", 1024,
                                chunker="sentence-pack-1")
    assert index_meta.read_index_meta(db, "transcripts_ollama")["chunker"] == "sentence-pack-1"
    assert index_meta.read_index_meta(db, "cards_ollama")["created"] == "2026-01-01T00:00:00"


# --- the mismatch policy: warn on read, refuse on write (#27) ----------------
#
# Four combinations are exercised — read x write against a chunker and against
# a row schema — plus the two absences, because "nothing recorded it" must
# behave differently from "it disagrees" or the first upgrade after this warns
# every reader of every index built before it.

def _stamped(tmp_path, chunker="sentence-pack-1", schema_version=None, dims=1024):
    """An index with one transcripts table and a fingerprint that says what the
    test needs it to say."""
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _table_with_ledger_columns(db, "transcripts_ollama", dims=dims)
    index_meta.write_index_meta(db, "transcripts_ollama", "ollama", "bge-m3", dims,
                                chunker=chunker, schema_version=schema_version)
    return db


def test_a_foreign_chunker_warns_on_read_and_the_index_still_opens(tmp_path, caplog):
    """The asymmetry this whole policy is: a chunker mismatch is a degradation,
    not a broken index, and refusing to READ it would throw away a build that
    takes about half an hour — which is the thing an upgrade must never do."""
    db = _stamped(tmp_path, chunker="sentence-pack-2")
    with caplog.at_level("WARNING"):
        line = index_meta.warn_version_mismatch(db, "transcripts_ollama")
    assert line and "sentence-pack-2" in line and "sentence-pack-1" in line
    assert "ayl-add --backup" in line and "ayl-add <folder>" in line
    assert any("sentence-pack-2" in record.message for record in caplog.records)
    # and the embedder check, which IS fatal on read, still says nothing
    assert index_meta.check_index(db, "transcripts_ollama", "bge-m3", 1024) is None


def test_a_foreign_chunker_refuses_a_write(tmp_path):
    db = _stamped(tmp_path, chunker="sentence-pack-2")
    refusal = index_meta.refuse_version_mismatch(db, "transcripts_ollama")
    assert refusal and refusal.startswith("refusing to write transcripts_ollama")
    assert "sentence-pack-2" in refusal and "sentence-pack-1" in refusal
    # the reason a write is treated differently from a read, in the text itself
    assert "two chunkers" in refusal and "ayl-add --backup" in refusal


def test_an_index_written_by_a_newer_release_warns_on_read(tmp_path):
    db = _stamped(tmp_path, schema_version=index_meta.SCHEMA_VERSION + 1)
    line = index_meta.warn_version_mismatch(db, "transcripts_ollama")
    assert line and str(index_meta.SCHEMA_VERSION + 1) in line
    assert str(index_meta.SCHEMA_VERSION) in line and "newer" in line


def test_an_index_written_by_a_newer_release_refuses_a_write(tmp_path):
    db = _stamped(tmp_path, schema_version=index_meta.SCHEMA_VERSION + 1)
    refusal = index_meta.refuse_version_mismatch(db, "transcripts_ollama")
    assert refusal and str(index_meta.SCHEMA_VERSION + 1) in refusal
    assert refusal.startswith("refusing to write transcripts_ollama")


def test_an_absent_chunker_stamp_is_neither_warned_about_nor_refused(tmp_path):
    """The state of every index built before the field existed, and of every
    table `--stage stamp-meta` fingerprints without `--chunker`. Inventing a
    disagreement out of an absence is what would make an upgrade noisy for
    everyone who has one of these."""
    db = _stamped(tmp_path, chunker="")
    assert index_meta.warn_version_mismatch(db, "transcripts_ollama") is None
    assert index_meta.refuse_version_mismatch(db, "transcripts_ollama") is None


def test_the_ledgers_legacy_marker_is_an_absence_too(tmp_path):
    """`legacy` is what a backfill writes: "indexed before anything recorded
    which chunker did it". Comparing it to a version would turn every
    pre-ledger index into a permanent mismatch."""
    db = _stamped(tmp_path, chunker=index_meta.LEGACY_CHUNKER)
    assert index_meta.warn_version_mismatch(db, "transcripts_ollama") is None
    assert index_meta.refuse_version_mismatch(db, "transcripts_ollama") is None


def test_a_table_with_no_fingerprint_at_all_is_not_a_mismatch(tmp_path):
    import lancedb

    db = lancedb.connect(tmp_path / "db")
    _table_with_ledger_columns(db, "transcripts_ollama")
    assert index_meta.version_mismatch(db, "transcripts_ollama") is None


def test_an_older_row_schema_is_the_upgrade_path_and_not_a_mismatch(tmp_path):
    """#67 added `book_id` and `book_rev` to existing tables IN PLACE, without
    re-embedding a row, and `ayl-add` re-stamps as it goes. Calling that a
    mismatch would warn every reader about something the next ingest fixes —
    and the cards table, which never gains those columns, would warn for ever."""
    db = _stamped(tmp_path, schema_version=index_meta.SCHEMA_VERSION - 1)
    assert index_meta.warn_version_mismatch(db, "transcripts_ollama") is None
    assert index_meta.refuse_version_mismatch(db, "transcripts_ollama") is None


def test_the_matching_stamp_says_nothing(tmp_path):
    db = _stamped(tmp_path)
    assert index_meta.version_mismatch(db, "transcripts_ollama") is None
