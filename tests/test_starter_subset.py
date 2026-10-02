"""The starter subset `ayl init --demo` builds: which books, why those, and
that marking them did not break what the manifest already guarantees (one
card per book, a pin per source, the checksum writer).

The list lives in one place, `starter: true` in corpus/manifest.yaml, with the
reason for each book beside its flag. What is pinned here is the brief the
list was chosen to: 5 to 8 books, both tables, the README's own question, a
multi-part work, the committed audio transcript, and one author twice so a
question naming only the author reaches the ask-back.
"""
import contextlib
import importlib.util
import re
import sys
from collections import Counter

import pytest
import yaml

from conftest import REPO

_spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus_starter", REPO / "scripts" / "ingest_demo_corpus.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

MANIFEST = yaml.safe_load((REPO / "corpus" / "manifest.yaml").read_text(encoding="utf-8"))
STARTER = demo.starter_entries(MANIFEST)
README_QUESTION = "What does Marcus Aurelius say about anger?"


def test_the_subset_is_five_to_eight_books_and_no_canary():
    assert 5 <= len(STARTER) <= 8, [e["id"] for e in STARTER]
    assert all(entry in MANIFEST["books"] for entry in STARTER)


def test_every_starter_book_has_a_card_so_both_tables_are_built():
    cards = {path.stem for path in (REPO / "corpus" / "cards").glob("*.md")}
    assert {e["id"] for e in STARTER} <= cards


def test_every_starter_source_is_pinned():
    assert all(entry.get("sha256") for entry in STARTER)


def test_the_readme_question_is_answerable_from_the_subset():
    for page in ("README.md", "docs/quick-start.md"):
        assert README_QUESTION in (REPO / page).read_text(encoding="utf-8"), page
    assert "Marcus Aurelius" in {entry["author"] for entry in STARTER}


def test_the_subset_reaches_the_paths_a_first_question_takes():
    assert any(entry.get("part_regex") for entry in STARTER), "a multi-part work"
    audio = [entry for entry in STARTER if entry["source"] == "librivox"]
    assert audio and all((REPO / "corpus" / "prepared-audio" / f"{e['id']}.json").is_file()
                         for e in audio), "a committed audio transcript"
    assert max(Counter(entry["author"] for entry in STARTER).values()) >= 2, "one author twice"


def test_every_starter_flag_carries_its_reason():
    text = (REPO / "corpus" / "manifest.yaml").read_text(encoding="utf-8")
    flags = text.count("\n    starter: true\n")
    reasons = len(re.findall(r"\n    # starter: ", text))
    assert flags == reasons == len(STARTER)


def test_the_checksum_writer_still_pins_a_flagged_entry_once(tmp_path, monkeypatch):
    """`--stage checksums` rewrites the manifest by regex: the flag lines added
    to an entry must neither stop the pin from being found nor get a second
    `sha256:` line written beside the first."""
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text((REPO / "corpus" / "manifest.yaml").read_text(encoding="utf-8"),
                        encoding="utf-8")
    raw = tmp_path / "raw"
    raw.mkdir()
    for entry in STARTER:
        if entry["source"] == "gutenberg":
            (raw / f"pg{entry['pg_id']}.txt").write_text(f"stand-in for {entry['id']}\n")
    monkeypatch.setattr(demo, "MANIFEST", manifest)
    monkeypatch.setattr(demo, "RAW_DIR", raw)
    demo.write_checksums()
    text = manifest.read_text(encoding="utf-8")
    rewritten = yaml.safe_load(text)
    by_id = {e["id"]: e for e in demo.all_entries(rewritten)}
    for entry in STARTER:
        block = re.search(rf"  - id: {re.escape(entry['id'])}\n(?:    .*\n)*", text).group(0)
        assert block.count("sha256:") == 1, entry["id"]
        assert by_id[entry["id"]].get("starter") is True
        if entry["source"] == "gutenberg":
            assert by_id[entry["id"]]["sha256"] == demo.sha256_of(raw / f"pg{entry['pg_id']}.txt")
        else:
            assert by_id[entry["id"]]["sha256"] == entry["sha256"]   # the committed transcript


# --- the script's --starter ----------------------------------------------------

def test_starter_runs_every_stage_over_the_subset_and_its_cards(monkeypatch):
    seen = {}
    for stage in ("prepare_text", "prepare_canaries", "prepare_audio"):
        monkeypatch.setattr(demo, stage, lambda entries, *a, stage=stage, **k:
                            seen.setdefault(stage, [e["id"] for e in entries]))
    monkeypatch.setattr(demo, "ingest_transcripts_table",
                        lambda backend, book, ids, known=None:
                        seen.setdefault("ingest", (backend, book, ids, known)))
    monkeypatch.setattr(demo, "ingest_cards_table",
                        lambda backend, dirs=None, only=None: seen.setdefault("cards", (dirs, only)))
    monkeypatch.setattr(demo, "ingest_lock", lambda *a, **k: contextlib.nullcontext())
    demo.main(["--starter", "--backend", "ollama"])
    ids = [e["id"] for e in STARTER]
    assert seen["prepare_text"] == seen["prepare_audio"] == ids
    assert seen["ingest"] == ("ollama", None, ids,
                              [e["id"] for e in demo.all_entries(MANIFEST)])
    assert seen["cards"] == (None, set(ids))


@pytest.mark.parametrize("extra", [["--book", "alice"], ["--stage", "checksums"],
                                   ["--stage", "cards", "--cards-dir", "corpus-tech/cards"]])
def test_starter_is_a_whole_library_and_refuses_what_would_change_it(extra, capsys):
    with pytest.raises(SystemExit) as raised:
        demo.main(["--starter", *extra])
    assert raised.value.code == 2
    assert "--starter builds the starter subset as a whole" in capsys.readouterr().err


def test_a_book_prepared_by_an_earlier_full_run_is_not_stale_under_starter(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "PREPARED_DIR", tmp_path)
    for note in ("meditations", "moby-dick"):
        (tmp_path / f"{note}.json").write_text(
            '{"note": "%s", "book": "B", "source": "s", "chapters": []}' % note)
    docs = demo.prepared_docs(["meditations"], known=["meditations", "moby-dick"])
    assert [d["note"] for d in docs] == ["meditations"]
    (tmp_path / "not-in-the-manifest.json").write_text("{}")
    with pytest.raises(SystemExit, match="without a manifest entry"):
        demo.prepared_docs(["meditations"], known=["meditations", "moby-dick"])


def test_the_cards_table_of_the_subset_holds_only_the_subset_s_cards(tmp_path, monkeypatch):
    cards = tmp_path / "cards"
    cards.mkdir()
    for note in ("meditations", "moby-dick"):
        (cards / f"{note}.md").write_text(f"# {note}\n\n## Plot\n\n- something happens\n")

    class Embedder:
        model, dims = "fake-embed", 4

        def embed_docs(self, texts):
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]
    monkeypatch.setattr(demo, "DB_PATH", tmp_path / "db")
    monkeypatch.setattr(demo, "get_embedder", lambda backend: Embedder())
    demo.ingest_cards_table("ollama", [cards], {"meditations"})
    import lancedb
    rows = lancedb.connect(tmp_path / "db").open_table("cards_ollama").to_arrow().to_pylist()
    assert rows and {row["note"] for row in rows} == {"meditations"}


if __name__ == "__main__":   # pragma: no cover
    sys.exit(pytest.main([__file__]))
