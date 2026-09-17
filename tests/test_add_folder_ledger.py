"""`ayl-add`'s per-book path: the ledger, the crash window and the folder diff.

The chapter and key rules are tested in `test_add_folder.py`; this file is
about what the ledger changed — one book updated in place, an identity that a
corrected author does not break, a crash between the delete and the append that
the next run finds, and a file that vanished from the folder.
"""
import lancedb
import pytest

from ask_your_library.index_meta import SCHEMA_VERSION, read_index_meta
from ask_your_library.ingest.doctor import check_ledger
from ask_your_library.ingest import add_folder, publish
from ask_your_library.ingest.ledger import CHUNKER_VERSION, LEGACY_CHUNKER, open_ledger
from test_add_folder import PARA, FakeEmbedder, fake_embedder, write  # noqa: F401

BODY = PARA * 4


def add(tmp_path, folder, **kwargs):
    return add_folder.add_books(add_folder.read_folder(folder), "ollama",
                                tmp_path / "db", folder, **kwargs)


def rows(tmp_path, table="transcripts_ollama"):
    table = lancedb.connect(tmp_path / "db").open_table(table)
    return table.search().limit(max(table.count_rows(), 1)).to_list()


def ledger_of(tmp_path):
    return open_ledger(lancedb.connect(tmp_path / "db"))


def make_folder(tmp_path):
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", BODY)
    write(folder, "Sea Notes - B. Mate.txt", BODY + " The tide turned at four.")
    return folder


# --- the ledger is written, before and after ---------------------------------

def test_a_first_run_writes_a_ledger_row_per_book(tmp_path, fake_embedder):
    add(tmp_path, make_folder(tmp_path))
    entries = {row["key"]: row for row in ledger_of(tmp_path).all_rows()}
    assert sorted(entries) == ["Sea Notes — B. Mate", "The Green Ledger — A. Keeper"]
    keeper = entries["The Green Ledger — A. Keeper"]
    assert keeper["status"] == "indexed" and keeper["rows"] > 0
    assert keeper["source_ref"].endswith(":The Green Ledger - A. Keeper.txt")
    assert keeper["source_ref"].startswith("local:")
    assert keeper["chunker"] == CHUNKER_VERSION
    assert keeper["embedding_model"] == "fake-embed" and len(keeper["sha256"]) == 64
    assert keeper["indexed_at"] and keeper["requested_at"]


def test_the_rows_carry_the_book_id_beside_the_note(tmp_path, fake_embedder):
    add(tmp_path, make_folder(tmp_path))
    ids = {row["key"]: row["book_id"] for row in ledger_of(tmp_path).all_rows()}
    for row in rows(tmp_path):
        assert row["book_id"] == ids[row["book"]]
        assert row["note"] and row["chunk_id"].startswith(row["note"])


def test_the_fts_rebuild_seconds_are_recorded_on_every_book_of_the_run(tmp_path,
                                                                       fake_embedder):
    counts = add(tmp_path, make_folder(tmp_path))
    assert counts["fts_seconds"] >= 0
    assert all(row["fts_seconds"] == pytest.approx(counts["fts_seconds"])
               for row in ledger_of(tmp_path).all_rows())


def test_the_index_is_stamped_with_the_chunker_and_the_schema_version(tmp_path,
                                                                      fake_embedder):
    add(tmp_path, make_folder(tmp_path))
    meta = read_index_meta(lancedb.connect(tmp_path / "db"), "transcripts_ollama")
    assert meta["chunker"] == CHUNKER_VERSION
    assert meta["schema_version"] == SCHEMA_VERSION


# --- one book at a time ------------------------------------------------------

def test_re_adding_one_book_replaces_only_that_books_rows(tmp_path, fake_embedder):
    folder = make_folder(tmp_path)
    add(tmp_path, folder)
    before = {r["chunk_id"]: r["text"] for r in rows(tmp_path) if r["book"].startswith("Sea")}

    (folder / "The Green Ledger - A. Keeper.txt").write_text(BODY + " And then a storm.",
                                                             encoding="utf-8")
    add(tmp_path, folder)

    after = rows(tmp_path)
    assert {r["chunk_id"]: r["text"] for r in after if r["book"].startswith("Sea")} == before
    ids = [r["chunk_id"] for r in after]
    assert len(ids) == len(set(ids))          # no duplicated chunks


def test_a_corrected_author_in_the_front_matter_renames_the_book(tmp_path, fake_embedder):
    """The claim the documentation makes, tested exactly as the documentation
    describes it: edit `author:` in the file, re-run, one book.

    This is the defect the whole issue exists for. Note what does NOT carry it:
    the key changes (that is what a correction is), and the file's bytes change
    too, so neither the key nor a digest of the FILE can recognise the book. The
    file at the same place in the folder can, and the digest of the book's TEXT
    (taken after the front matter is off it) is unchanged, which is why the
    ledger records that rather than a digest of the file."""
    folder = tmp_path / "books"
    write(folder, "moby.md", "---\ntitle: Moby Dick\nauthor: H. Melville\n---\n\n" + BODY)
    add(tmp_path, folder)
    before = ledger_of(tmp_path).all_rows()[0]["book_id"]

    (folder / "moby.md").write_text(
        "---\ntitle: Moby Dick\nauthor: Herman Melville\n---\n\n" + BODY, encoding="utf-8")
    add(tmp_path, folder)

    entries = ledger_of(tmp_path).all_rows()
    assert len(entries) == 1
    assert entries[0]["book_id"] == before          # minted once, never re-derived
    assert entries[0]["key"] == "Moby Dick — Herman Melville"
    assert {r["book"] for r in rows(tmp_path)} == {"Moby Dick — Herman Melville"}


def test_a_corrected_author_on_the_title_line_renames_the_book_too(tmp_path, fake_embedder):
    folder = tmp_path / "books"
    write(folder, "moby.md", "# Moby Dick by H. Melville\n\n" + BODY)
    add(tmp_path, folder)
    before = ledger_of(tmp_path).all_rows()[0]["book_id"]

    (folder / "moby.md").write_text("# Moby Dick by Herman Melville\n\n" + BODY,
                                    encoding="utf-8")
    add(tmp_path, folder)
    entries = ledger_of(tmp_path).all_rows()
    assert len(entries) == 1 and entries[0]["book_id"] == before
    assert {r["book"] for r in rows(tmp_path)} == {"Moby Dick — Herman Melville"}


def test_editing_a_books_text_does_not_mint_a_second_ledger_row(tmp_path, fake_embedder):
    """`resolve` is handed the title and the author separately. Handed the
    composite key as a title it produced "Title — Author — Unknown", which
    matches no row ever written, so every re-ingest of an edited book minted a
    fresh id and the ledger grew one `indexed` row per edit."""
    folder = tmp_path / "books"
    write(folder, "Moby Dick - Herman Melville.txt", BODY)
    add(tmp_path, folder)
    first = ledger_of(tmp_path).all_rows()[0]["book_id"]

    for edit in range(1, 4):
        (folder / "Moby Dick - Herman Melville.txt").write_text(
            BODY + f" Edit {edit}.", encoding="utf-8")
        add(tmp_path, folder)

    entries = ledger_of(tmp_path).all_rows()
    assert len(entries) == 1 and entries[0]["book_id"] == first
    assert entries[0]["rows"] == len(rows(tmp_path))
    assert check_ledger(lancedb.connect(tmp_path / "db"),
                        ["transcripts_ollama", "cards_ollama"]).ok


def test_a_byte_identical_book_in_another_folder_does_not_replace_the_first(tmp_path,
                                                                            fake_embedder,
                                                                            caplog):
    """A digest match adopts nothing. Both books must survive: the alternative
    is that the second folder's run silently deletes the first folder's rows,
    which the staged rebuild this replaced could not do."""
    one = tmp_path / "one"
    two = tmp_path / "two"
    write(one, "Moby Dick - Herman Melville.txt", BODY)
    write(two, "A Different Title - Someone Else.txt", BODY)
    add_folder.add_books(add_folder.read_folder(one), "ollama", tmp_path / "db", one)
    with caplog.at_level("WARNING"):
        add_folder.add_books(add_folder.read_folder(two), "ollama", tmp_path / "db", two)

    entries = {row["key"]: row for row in ledger_of(tmp_path).all_rows()}
    assert sorted(entries) == ["A Different Title — Someone Else",
                               "Moby Dick — Herman Melville"]
    assert len({row["book_id"] for row in entries.values()}) == 2
    assert {r["book"] for r in rows(tmp_path)} == set(entries)
    assert "SECOND book" in caplog.text


def test_the_books_of_another_folder_are_never_reported_as_vanished_or_pruned(tmp_path,
                                                                              fake_embedder):
    """One index, two folders. Every book of the other folder is missing from
    this one by construction, and `--prune` would have deleted all of them."""
    one = tmp_path / "one"
    two = tmp_path / "two"
    write(one, "The Green Ledger - A. Keeper.txt", BODY)
    write(two, "Sea Notes - B. Mate.txt", BODY + " The tide turned at four.")
    add_folder.add_books(add_folder.read_folder(one), "ollama", tmp_path / "db", one)
    counts = add_folder.add_books(add_folder.read_folder(two), "ollama", tmp_path / "db",
                                  two, prune=True)

    assert counts["vanished"] == [] and counts["pruned"] == 0
    assert {r["book"] for r in rows(tmp_path)} == {"The Green Ledger — A. Keeper",
                                                   "Sea Notes — B. Mate"}


def test_a_renamed_file_of_the_same_book_is_not_a_second_book(tmp_path, fake_embedder):
    folder = tmp_path / "books"
    write(folder, "moby.txt", "---\ntitle: Moby Dick\nauthor: Herman Melville\n---\n\n" + BODY)
    add(tmp_path, folder)
    (folder / "moby.txt").rename(folder / "moby-dick-final.txt")
    add(tmp_path, folder)

    assert len(ledger_of(tmp_path).all_rows()) == 1
    assert ledger_of(tmp_path).all_rows()[0]["source_ref"].endswith(":moby-dick-final.txt")
    assert len({r["book"] for r in rows(tmp_path)}) == 1


def test_renaming_the_FILE_to_change_the_key_is_a_new_book_and_the_old_one_is_reported(
        tmp_path, fake_embedder):
    """The edge the rules cannot resolve, pinned so it stays deliberate. When
    the key comes from the file name, renaming the file changes the key AND the
    path at once, and nothing left distinguishes "I corrected the author" from
    "I added another copy". The second book is indexed and the first is reported
    as vanished, which `--prune` then clears — rather than a silent takeover."""
    folder = tmp_path / "books"
    write(folder, "Moby Dick - H. Melville.txt", BODY)
    add(tmp_path, folder)
    (folder / "Moby Dick - H. Melville.txt").rename(folder / "Moby Dick - Herman Melville.txt")
    counts = add(tmp_path, folder)

    assert [row["key"] for row in counts["vanished"]] == ["Moby Dick — H. Melville"]
    assert len(ledger_of(tmp_path).all_rows()) == 2
    counts = add(tmp_path, folder, prune=True)
    assert counts["pruned"] == 1
    assert {r["book"] for r in rows(tmp_path)} == {"Moby Dick — Herman Melville"}


# --- the crash window --------------------------------------------------------

def test_a_crash_between_the_delete_and_the_append_is_found_and_repaired(tmp_path,
                                                                        monkeypatch):
    """The window the per-book path opens, and the reason the ledger exists:
    the book is out of the index and only its ledger row knows it."""
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder())
    add(tmp_path, folder)
    before = len(rows(tmp_path))

    real_replace = add_folder.replace_book_rows

    def die_after_the_delete(table, book_id, note, book_rows):
        real_replace(table, book_id, note, [])        # the delete half only
        raise RuntimeError("power cut")

    (folder / "Sea Notes - B. Mate.txt").write_text(BODY + " A second edition.",
                                                    encoding="utf-8")
    monkeypatch.setattr(add_folder, "replace_book_rows", die_after_the_delete)
    with pytest.raises(RuntimeError, match="power cut"):
        add(tmp_path, folder)

    # the book really is gone from the index, and the ledger says `requested`
    assert not [r for r in rows(tmp_path) if r["book"].startswith("Sea")]
    missing = ledger_of(tmp_path).missing()
    assert [row["key"] for row in missing] == ["Sea Notes — B. Mate"]

    # the next run reports it and puts it back
    monkeypatch.setattr(add_folder, "replace_book_rows", real_replace)
    counts = add(tmp_path, folder)
    assert any("re-indexing Sea Notes" in line for line in counts["recovered"])
    assert ledger_of(tmp_path).missing() == []
    assert len(rows(tmp_path)) == before
    assert "A second edition." in " ".join(r["text"] for r in rows(tmp_path))


def test_a_crash_between_the_append_and_the_ledger_write_is_repaired_from_the_index(
        tmp_path, monkeypatch):
    """One half of the window. The rows carry the revision that was requested,
    so they ARE the requested text: one book is one `table.add()`, which LanceDB
    commits as a unit, and only the ledger's second write was lost."""
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder())
    add(tmp_path, folder)

    ledger = ledger_of(tmp_path)
    sea = next(r for r in ledger.all_rows() if r["key"].startswith("Sea"))
    ledger.begin(sea["book_id"], key=sea["key"], source_ref=sea["source_ref"],
                 sha256=sea["sha256"])
    assert ledger_of(tmp_path).missing()             # `requested`, with its rows in place

    counts = add(tmp_path, folder)
    assert any("recovered Sea Notes" in line for line in counts["recovered"])
    assert ledger_of(tmp_path).missing() == []


def test_a_crash_while_embedding_never_commits_the_previous_text_as_current(tmp_path,
                                                                            monkeypatch):
    """The other half, and the one that used to be got wrong. `begin` marks a
    book `requested` BEFORE its text is embedded, so at that moment the index
    still holds the previous version — a full set of perfectly good, perfectly
    stale rows. Recovery read presence alone and called that a completed append,
    which marked the old text current with nothing left to notice.

    Here the run that follows does not cover the book (its file has moved out of
    the folder), so re-indexing is not available and the only safe outcome is to
    say so."""
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder())
    add(tmp_path, folder)
    sea_file = folder / "Sea Notes - B. Mate.txt"

    # the crash: the file is edited, the run marks `requested`, and it dies
    # while embedding — the index still holds the version before the edit
    sea_file.write_text(BODY + " A second edition.", encoding="utf-8")
    edited = next(b for b in add_folder.read_folder(folder) if b.book.startswith("Sea"))
    ledger = ledger_of(tmp_path)
    sea = next(r for r in ledger.all_rows() if r["key"].startswith("Sea"))
    ledger.begin(sea["book_id"], key=sea["key"], source_ref=sea["source_ref"],
                 sha256=edited.text_sha256)

    sea_file.rename(tmp_path / "moved-away.txt")     # the next run cannot re-index it
    counts = add(tmp_path, folder)

    assert any(line.startswith("STALE Sea Notes") for line in counts["recovered"])
    # never committed: the ledger still says the book is not indexed
    after = ledger_of(tmp_path).get(sea["book_id"])
    assert after["status"] == "requested"
    assert [r["key"] for r in ledger_of(tmp_path).missing()] == ["Sea Notes — B. Mate"]
    # and the index is honest about what it is still answering from
    assert "A second edition." not in " ".join(r["text"] for r in rows(tmp_path))


def test_a_crash_while_embedding_is_re_indexed_when_the_run_covers_the_book(tmp_path,
                                                                            monkeypatch):
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder())
    add(tmp_path, folder)

    (folder / "Sea Notes - B. Mate.txt").write_text(BODY + " A second edition.",
                                                    encoding="utf-8")
    edited = next(b for b in add_folder.read_folder(folder) if b.book.startswith("Sea"))
    ledger = ledger_of(tmp_path)
    sea = next(r for r in ledger.all_rows() if r["key"].startswith("Sea"))
    ledger.begin(sea["book_id"], key=sea["key"], source_ref=sea["source_ref"],
                 sha256=edited.text_sha256)

    counts = add(tmp_path, folder)
    assert any("older version" in line and "re-indexing Sea Notes" in line
               for line in counts["recovered"])
    assert ledger_of(tmp_path).missing() == []
    assert "A second edition." in " ".join(r["text"] for r in rows(tmp_path))


def test_rows_that_predate_the_revision_column_are_never_taken_for_current(tmp_path,
                                                                           monkeypatch):
    """An index migrated from before the ledger carries an empty revision. Empty
    is not a revision: it matches nothing, so such a book is re-indexed rather
    than assumed to hold what was asked for."""
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder())
    add(tmp_path, folder)

    db = lancedb.connect(tmp_path / "db")
    sea = next(r for r in open_ledger(db).all_rows() if r["key"].startswith("Sea"))
    stripped = [{**row, "book_rev": ""} for row in rows(tmp_path)]
    db.drop_table("transcripts_ollama")
    db.create_table("transcripts_ollama", stripped)
    open_ledger(db).begin(sea["book_id"], key=sea["key"], source_ref=sea["source_ref"],
                          sha256=sea["sha256"])

    counts = add(tmp_path, folder)
    assert any("Sea Notes" in line and ("older version" in line or "STALE" in line)
               for line in counts["recovered"])


def test_a_book_that_failed_is_never_promoted_to_indexed_by_the_recovery_pass(tmp_path,
                                                                              monkeypatch):
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder())
    add(tmp_path, folder)
    ledger = ledger_of(tmp_path)
    sea = next(r for r in ledger.all_rows() if r["key"].startswith("Sea"))
    ledger.fail(sea["book_id"], "embedder down")

    counts = add(tmp_path, folder)
    assert any("failed Sea Notes" in line and "earlier run" in line
               for line in counts["recovered"])


def test_a_book_missing_from_the_index_and_from_this_run_is_reported(tmp_path,
                                                                     fake_embedder):
    folder = make_folder(tmp_path)
    add(tmp_path, folder)
    ledger = ledger_of(tmp_path)
    ghost = ledger.resolve("A Ghost", "Nobody", sha256="ghost")
    ledger.begin(ghost, key="A Ghost — Nobody", source_ref="local:ghost.txt")

    counts = add(tmp_path, folder)
    assert any(line.startswith("MISSING A Ghost — Nobody") for line in counts["recovered"])


# --- a file that vanished ----------------------------------------------------

def test_a_vanished_file_is_reported_and_its_rows_are_kept(tmp_path, fake_embedder):
    folder = make_folder(tmp_path)
    add(tmp_path, folder)
    (folder / "Sea Notes - B. Mate.txt").unlink()

    counts = add(tmp_path, folder)
    assert [row["key"] for row in counts["vanished"]] == ["Sea Notes — B. Mate"]
    assert counts["pruned"] == 0
    assert {r["book"] for r in rows(tmp_path)} == {"Sea Notes — B. Mate",
                                                   "The Green Ledger — A. Keeper"}


def test_prune_deletes_a_vanished_books_rows_and_its_ledger_row(tmp_path, fake_embedder):
    folder = make_folder(tmp_path)
    add(tmp_path, folder)
    (folder / "Sea Notes - B. Mate.txt").unlink()

    counts = add(tmp_path, folder, prune=True)
    assert counts["pruned"] == 1
    assert {r["book"] for r in rows(tmp_path)} == {"The Green Ledger — A. Keeper"}
    assert [row["key"] for row in ledger_of(tmp_path).all_rows()] == \
        ["The Green Ledger — A. Keeper"]


def test_dry_run_prints_the_diff_against_the_ledger(tmp_path, fake_embedder, capsys):
    folder = make_folder(tmp_path)
    add(tmp_path, folder)
    (folder / "Sea Notes - B. Mate.txt").unlink()
    write(folder, "Third Book - C. Writer.txt", BODY)
    capsys.readouterr()

    assert add_folder.main([str(folder), "--db", str(tmp_path / "db"), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "1 new, 1 already indexed" in printed
    assert "new       Third Book - C. Writer.txt" in printed
    assert "replaces  The Green Ledger - A. Keeper.txt" in printed
    assert "VANISHED  Sea Notes — B. Mate" in printed
    # and it is still a dry run
    assert {r["book"] for r in rows(tmp_path)} == {"Sea Notes — B. Mate",
                                                   "The Green Ledger — A. Keeper"}


def test_dry_run_against_no_index_says_every_book_is_new(tmp_path, capsys):
    folder = make_folder(tmp_path)
    assert add_folder.main([str(folder), "--db", str(tmp_path / "db"), "--dry-run"]) == 0
    assert "no book ledger at" in capsys.readouterr().out
    assert not (tmp_path / "db").exists()


# --- the upgrade of an existing index ----------------------------------------

def test_an_index_built_before_the_ledger_is_backfilled_and_then_updated_in_place(
        tmp_path, fake_embedder):
    folder = make_folder(tmp_path)
    add(tmp_path, folder)

    # roll the index back to what a pre-ledger one looks like: no ledger table,
    # no book_id column
    db = lancedb.connect(tmp_path / "db")
    db.drop_table("books")
    old = [{k: v for k, v in row.items() if k != "book_id"} for row in rows(tmp_path)]
    db.drop_table("transcripts_ollama")
    db.create_table("transcripts_ollama", old)
    assert "book_id" not in db.open_table("transcripts_ollama").schema.names

    # this run covers one of the two books; the other stays as the backfill
    # left it, which is what makes `legacy` visible
    (folder / "The Green Ledger - A. Keeper.txt").unlink()
    (folder / "Sea Notes - B. Mate.txt").write_text(BODY + " A postscript.", encoding="utf-8")
    add(tmp_path, folder)

    table = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama")
    assert publish.has_book_id(table)
    entries = {row["key"]: row for row in ledger_of(tmp_path).all_rows()}
    assert sorted(entries) == ["Sea Notes — B. Mate", "The Green Ledger — A. Keeper"]
    # the book this run did not touch kept its backfilled row, `legacy` and all
    assert entries["The Green Ledger — A. Keeper"]["chunker"] == LEGACY_CHUNKER
    assert entries["Sea Notes — B. Mate"]["chunker"] == CHUNKER_VERSION
    # every row of the migrated table carries the id its ledger row holds
    for row in rows(tmp_path):
        assert row["book_id"] == entries[row["book"]]["book_id"]
    assert "A postscript." in " ".join(r["text"] for r in rows(tmp_path))


def test_prune_keeps_a_book_card_and_says_so(tmp_path, fake_embedder, capsys):
    """`ayl-add` never writes the cards table, so `--prune` does not delete from
    it either: a card is a model call per book and usually came from the demo
    corpus. What it costs is said out loud instead, and `--doctor` names the
    card afterwards."""
    folder = make_folder(tmp_path)
    add(tmp_path, folder)
    db = lancedb.connect(tmp_path / "db")
    db.create_table("cards_ollama", [
        {"chunk_id": "sea/1", "note": "sea", "book": "Sea Notes — B. Mate",
         "source": "card", "section": "Plot", "text": "a summary", "vector": [1.0] * 4}])
    (folder / "Sea Notes - B. Mate.txt").unlink()
    capsys.readouterr()

    counts = add(tmp_path, folder, prune=True)
    printed = capsys.readouterr().out
    assert counts["pruned"] == 1
    assert "its book card in cards_ollama is kept" in printed
    assert {r["book"] for r in rows(tmp_path)} == {"The Green Ledger — A. Keeper"}
    assert rows(tmp_path, "cards_ollama")          # the card is still there

    report = check_ledger(lancedb.connect(tmp_path / "db"),
                          ["transcripts_ollama", "cards_ollama"])
    assert report.cards_without_a_book == ["Sea Notes — B. Mate"]
    assert report.in_index_but_not_in_ledger == []      # not "the next ayl-add adopts it"
    assert any("CARD WITHOUT A BOOK" in line for line in report.lines())
