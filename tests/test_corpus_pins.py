"""CI guards for the demo manifest's pins, and for the recipe that re-pins them.

`verify_checksum` can only compare against what the manifest holds, so a
`sha256:` line removed by hand — or never added when a book was appended —
used to be the quietest possible change: nothing failed, the download went
ahead, and that book was simply no longer verified against anything while the
eval reports kept naming the manifest fingerprint as their provenance. The
stages now exit on a missing pin (see `verify_checksum`), and this says the
same thing without a network round trip, on every pull request rather than
only on the ones the corpus job runs for.

Canaries are the manifest's own exception, stated in corpus/README.md: their
text is committed to this repository, so there is no fetched file to pin.

The last test covers the other half of the same workflow: `--refetch`, which
sets the drifted copy aside so it can be diffed. Nothing downloads there — the
fetch is a stub — because what is under test is which file survives.
"""
import importlib.util
import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "corpus" / "manifest.yaml"

SHA256 = re.compile(r"[0-9a-f]{64}")

spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", REPO / "scripts" / "ingest_demo_corpus.py")
ingest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ingest)


def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_every_fetched_source_carries_a_sha256():
    """A Gutenberg entry pins the downloaded text, a LibriVox entry pins the
    transcript committed under prepared-audio/ — both are entries of `books`,
    and both are what a build reads. `isinstance(str)`, because an all-digit
    digest would come back from YAML as an int and never match anything."""
    problems = []
    for entry in manifest()["books"]:
        pin = entry.get("sha256")
        if not isinstance(pin, str) or not SHA256.fullmatch(pin):
            problems.append(f"  {entry['id']} ({entry['source']}): {pin!r}")
    assert not problems, (
        "manifest entries without a 64-hex sha256 — an unpinned source is not verified "
        "against anything:\n" + "\n".join(problems)
        + "\npin them with `uv run scripts/ingest_demo_corpus.py --stage checksums`")


def test_canaries_carry_no_sha256():
    """The other half of the rule, so "pin everything" is not read as licence to
    pin a file this repository writes itself: a canary checksum would only ever
    restate the working tree, and corpus/README.md says they carry none."""
    pinned = [e["id"] for e in manifest().get("canaries", []) if e.get("sha256")]
    assert not pinned, (f"canaries are committed text, not fetched sources, and pin nothing: "
                        f"{pinned}")


ENTRY = {"id": "demo-book", "source": "gutenberg", "pg_id": 4242,
         "title": "A Demo Book", "author": "A. Nonymous"}


def book_text(marker: str) -> str:
    """A minimal Gutenberg-shaped file: boilerplate markers around one chapter
    whose body clears MIN_CHAPTER_CHARS, so the real prepare path runs."""
    return ("front matter that the ingest strips\n"
            "*** START OF THE PROJECT GUTENBERG EBOOK A DEMO BOOK ***\n"
            f"CHAPTER I.\n{marker}. " + "Lorem ipsum dolor sit amet. " * 12 + "\n"
            "*** END OF THE PROJECT GUTENBERG EBOOK A DEMO BOOK ***\nlicence text\n")


def test_a_second_refetch_refuses_and_leaves_the_first_backup_byte_identical(tmp_path, monkeypatch):
    """`--refetch` exists to preserve the edition the manifest pinned: it moves
    the cached copy to `pg<id>.txt.prev` so the drift can be diffed. Run twice,
    it used to destroy exactly that — the second run parked the FIRST run's
    download on top of the backup, and since the Gutenberg texts are not
    committed and the mirror serves only the new file, the pinned edition was
    then gone. Worse than losing it quietly: the diff still ran, now comparing
    one fresh download against another, and came back clean.

    So the rerun stops before it downloads or moves anything, and the original
    is still there afterwards, byte for byte."""
    monkeypatch.setattr(ingest, "REPO", tmp_path)
    monkeypatch.setattr(ingest, "RAW_DIR", tmp_path / "data" / "raw")
    monkeypatch.setattr(ingest, "PREPARED_DIR", tmp_path / "data" / "prepared")
    monkeypatch.setattr(ingest, "TOC_DIR", tmp_path / "corpus" / "toc")
    monkeypatch.setattr(ingest, "VERIFY_CHECKSUMS", False)   # the pin is the thing under suspicion
    monkeypatch.setattr(ingest, "DOWNLOAD_PAUSE_S", 0)
    fetched = []

    def fake_fetch(url, attempts=ingest.DOWNLOAD_ATTEMPTS):
        fetched.append(url)
        return book_text(f"upstream revision {len(fetched) + 1}")

    monkeypatch.setattr(ingest, "fetch_text", fake_fetch)

    raw = ingest.RAW_DIR / "pg4242.txt"
    raw.parent.mkdir(parents=True)
    pinned = book_text("the edition the manifest pinned")
    raw.write_text(pinned, encoding="utf-8")

    ingest.prepare_text([ENTRY], refetch=True)
    backup = raw.with_name("pg4242.txt.prev")
    assert backup.read_text(encoding="utf-8") == pinned
    assert len(fetched) == 1
    after_first = raw.read_bytes()

    with pytest.raises(SystemExit) as exit_info:
        ingest.prepare_text([ENTRY], refetch=True)

    assert exit_info.value.code != 0
    message = str(exit_info.value)
    assert "pg4242.txt.prev" in message          # names the file it refuses to overwrite
    assert "diff " in message and "by hand" in message   # and both ways out
    assert backup.read_bytes() == pinned.encode()        # the point: still the pinned edition
    assert raw.read_bytes() == after_first               # and nothing was re-downloaded over it
    assert len(fetched) == 1
