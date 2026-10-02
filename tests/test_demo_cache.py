"""A demo build started with --cache-dir — the one `ayl init --demo` starts —
treats the checkout as read-only input (F-demo-writes-checkout).

The script used to stage its downloads and prepared texts in the checkout's
data/ and regenerate the committed contents pages in corpus/toc/ on every
prepare: a first `ayl init --demo` wrote outside AYL_HOME, could fail in a
read-only clone after the earlier steps had succeeded, and could rewrite
repository files. Here the whole starter pipeline runs (prepare-text,
prepare-canaries, prepare-audio, ingest, cards) over a two-book manifest
with the network and the embedder faked, and every write this process
attempts is watched by an audit hook: nothing may be opened for writing,
created, renamed or removed under the repository. The sources are still
checked against the manifest's pins.
"""
import hashlib
import importlib.util
import os
import sys
import threading
from pathlib import Path

import lancedb
import pytest

from conftest import REPO

_spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus_cache", REPO / "scripts" / "ingest_demo_corpus.py")
demo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo)

CHAPTER = ("The narrator wrote a long letter about the cold and the sea, and the ship, "
           "and what the captain said to the crew before the ice closed in. ") * 6
TEXT = ("Header lines of the mirror.\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n\n"
        + "".join(f"CHAPTER {n}\n\n{CHAPTER}\n\n" for n in ("I", "II", "III"))
        + "*** END OF THE PROJECT GUTENBERG EBOOK X ***\nFooter.\n")
PIN = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
REAL_MANIFEST = demo.load_manifest()
ALICE = next(e for e in REAL_MANIFEST["books"] if e["id"] == "alice-in-wonderland")
MANIFEST = {"books": [{"id": "frankenstein", "title": "Frankenstein", "author": "Mary Shelley",
                       "source": "gutenberg", "pg_id": 84, "sha256": PIN, "starter": True},
                      ALICE],
            "canaries": []}

# --- watching every write -----------------------------------------------------------
_armed = threading.Event()
_writes: list[tuple[str, str]] = []
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _hook(event, args):
    if not _armed.is_set():
        return
    if event == "open":
        path, mode, flags = args
        writing = (any(c in str(mode or "") for c in "wax+")
                   or (mode is None and isinstance(flags, int) and flags & _WRITE_FLAGS))
        if writing and isinstance(path, (str, bytes, os.PathLike)):
            _writes.append((event, os.fsdecode(path)))
    elif event in ("os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir",
                   "os.truncate", "shutil.rmtree", "shutil.copyfile"):
        for value in args:
            if isinstance(value, (str, bytes, os.PathLike)):
                _writes.append((event, os.fsdecode(value)))


sys.addaudithook(_hook)


class Embedder:
    model, dims = "fake-embed", 4

    def embed_docs(self, texts):
        return [[float(len(text) % 7), 1.0, 0.5, 0.25] for text in texts]


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    home = tmp_path / "AskYourLibrary"
    monkeypatch.setattr(demo, "load_manifest", lambda: MANIFEST)
    monkeypatch.setattr(demo, "fetch_text", lambda url, attempts=3: TEXT)
    monkeypatch.setattr(demo, "DOWNLOAD_PAUSE_S", 0)
    monkeypatch.setattr(demo, "get_embedder", lambda backend: Embedder())
    monkeypatch.setattr(demo, "DB_PATH", home / "demo" / "index")
    # main() rebinds these globals from --cache-dir; put the defaults back after
    for name in ("RAW_DIR", "PREPARED_DIR", "WRITE_TOC", "VERIFY_CHECKSUMS"):
        monkeypatch.setattr(demo, name, getattr(demo, name))
    return home


def resolved(path: str) -> Path:
    return Path(os.path.abspath(path)).resolve()


def test_a_cache_dir_starter_build_writes_only_under_ayl_home(isolated):
    home = isolated
    cache = home / "demo" / "cache"
    _writes.clear()
    _armed.set()
    try:
        demo.main(["--starter", "--backend", "ollama", "--cache-dir", str(cache)])
    finally:
        _armed.clear()
    targets = [(event, resolved(path)) for event, path in _writes]
    assert targets, "the audit hook saw no write at all: it is not watching"
    in_repo = [(event, str(path)) for event, path in targets if path.is_relative_to(REPO)]
    assert in_repo == [], in_repo
    assert any(path.is_relative_to(home.resolve()) for _event, path in targets)
    assert (cache / "raw" / "pg84.txt").is_file()
    assert {p.name for p in (cache / "prepared").glob("*.json")} == {
        "frankenstein.json", "alice-in-wonderland.json"}
    table = lancedb.connect(home / "demo" / "index").open_table("transcripts_ollama")
    assert {row["book"] for row in table.to_arrow().to_pylist()} == {
        "Frankenstein — Mary Shelley", "Alice's Adventures in Wonderland — Lewis Carroll"}


def test_the_hook_sees_a_write_and_where_it_went(tmp_path):
    """The watcher itself: an armed write is recorded with its path, so an
    empty list of writes under the repository means none happened."""
    _writes.clear()
    _armed.set()
    try:
        (tmp_path / "probe.txt").write_text("x")
        (tmp_path / "dir").mkdir()
    finally:
        _armed.clear()
    seen = {(event, resolved(path)) for event, path in _writes}
    assert ("open", (tmp_path / "probe.txt").resolve()) in seen
    assert ("os.mkdir", (tmp_path / "dir").resolve()) in seen


def test_a_cache_dir_run_still_verifies_the_pins(isolated, monkeypatch):
    monkeypatch.setattr(demo, "fetch_text", lambda url, attempts=3: TEXT + "a re-release\n")
    with pytest.raises(SystemExit, match="checksum mismatch for frankenstein"):
        demo.main(["--starter", "--stage", "prepare-text", "--cache-dir",
                   str(isolated / "demo" / "cache")])


def test_a_cache_dir_run_does_not_rewrite_the_manifest(isolated, capsys):
    with pytest.raises(SystemExit) as refused:
        demo.main(["--stage", "checksums", "--cache-dir", str(isolated / "cache")])
    assert refused.value.code == 2
    assert "--cache-dir keeps the checkout read-only" in capsys.readouterr().err


def test_without_a_cache_dir_the_developer_s_run_keeps_its_layout():
    """The default the CI pin job and a developer's direct run rely on."""
    assert demo.RAW_DIR == REPO / "data" / "raw"
    assert demo.PREPARED_DIR == REPO / "data" / "prepared"
    assert demo.WRITE_TOC is True
