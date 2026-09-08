"""Build the open demo corpus: download -> prepare chapters -> embed -> LanceDB.

Sources come from corpus/manifest.yaml (public-domain books + 2 synthetic
canaries). Text books arrive as plain text; two books arrive as per-chapter
mp3s and go through local Whisper transcription, so the audio path of the
pipeline is exercised for real.

Chunking, embedding and the FTS index come from ask_your_library.ingest — the
same code that serves the agent, so every corpus is processed identically.

Stages (all cached in data/, safe to re-run):
  uv run scripts/ingest_demo_corpus.py                     # everything
  uv run scripts/ingest_demo_corpus.py --stage prepare-text
  uv run scripts/ingest_demo_corpus.py --stage prepare-audio   # slow: Whisper
  uv run scripts/ingest_demo_corpus.py --stage prepare-canaries
  uv run scripts/ingest_demo_corpus.py --stage ingest      # transcripts table
  uv run scripts/ingest_demo_corpus.py --stage cards       # cards table
  uv run scripts/ingest_demo_corpus.py --book alice        # filter by substring
  uv run scripts/ingest_demo_corpus.py --stage stamp-meta  # fingerprint pre-existing tables
  uv run scripts/ingest_demo_corpus.py --stage checksums   # pin source sha256 into the manifest

Rebuilds go through a staging table (old index stays queryable until the new
one is complete); --book re-ingests replace that book's rows instead of
appending. Sources are checksum-pinned in the manifest (--no-verify to skip).

The LanceDB lives in data/lancedb by default (LIBRARY_DB_PATH overrides, the
same variable the agent reads). Table names: cards_<backend> / transcripts_<backend>.
"""
import argparse
import hashlib
import json
import logging
import platform
import re
import subprocess
import sys
import time
from pathlib import Path

import lancedb
import requests
import yaml

from ask_your_library.config import DB_PATH, EMBED_BACKEND
from ask_your_library.embeddings import get_embedder
from ask_your_library.index_meta import check_index, read_index_meta, write_index_meta
from ask_your_library.ingest import (Chunk, build_fts_index, chunk_card, embedding_text,
                                     pack_sentences, rows_for, split_sentences)
# Chapter splitting lives in the package so every ingest path (this script and
# the generic `ayl-add`) cuts books into sections identically.
from ask_your_library.ingest.chapters import (DEFAULT_CHAPTER_RE, MIN_CHAPTER_CHARS,  # noqa: F401
                                              split_chapters, with_parts)
from ask_your_library.ingest.publish import (rebuild_table, recover_staging, table_names,
                                             upsert_book_rows)

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "corpus" / "manifest.yaml"
CANARIES_DIR = REPO / "corpus" / "canaries"
CARDS_DIR = REPO / "corpus" / "cards"
# Transcripts of the LibriVox books, committed so the full corpus builds on any
# OS: transcription itself needs macOS (MLX Whisper).
PREPARED_AUDIO_DIR = REPO / "corpus" / "prepared-audio"
# Chapter titles per book, committed: lets CI check that cards only quote works
# that exist in the edition without needing the (gitignored) prepared texts.
TOC_DIR = REPO / "corpus" / "toc"
DATA = REPO / "data"
RAW_DIR = DATA / "raw"            # downloaded texts / mp3s, as fetched
PREPARED_DIR = DATA / "prepared"  # one json per book: {note, book, chapters}

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"


def load_manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


VERIFY_CHECKSUMS = True


def verify_checksum(entry: dict, path: Path, key: str = "sha256") -> None:
    """Sources are fetched from mirrors that do re-release files; the manifest
    pins what the eval numbers were produced from."""
    expected = entry.get(key)
    if not expected or not VERIFY_CHECKSUMS:
        return
    actual = sha256_of(path)
    if actual != expected:
        sys.exit(f"checksum mismatch for {entry['id']} ({path.name}): manifest {expected[:12]}..., "
                 f"got {actual[:12]}... — the source changed upstream; re-pin with "
                 f"--stage checksums or run with --no-verify")


def write_checksums() -> None:
    """Pin sha256 of every fetched/committed source into the manifest."""
    text = MANIFEST.read_text(encoding="utf-8")
    manifest = yaml.safe_load(text)
    for entry in all_entries(manifest):
        if entry["source"] == "gutenberg":
            path = RAW_DIR / f"pg{entry['pg_id']}.txt"
        elif entry["source"] == "librivox":
            path = PREPARED_AUDIO_DIR / f"{entry['id']}.json"
        else:
            continue
        if not path.exists():
            print(f"  {entry['id']}: source not present, skipped")
            continue
        digest = sha256_of(path)
        import re as _re
        block = _re.compile(rf"(  - id: {_re.escape(entry['id'])}\n(?:    .*\n)*?)(    sha256: .*\n)?")
        m = block.search(text)
        assert m, entry["id"]
        head = m.group(1)
        text = text[:m.start()] + head + f"    sha256: {digest}\n" + text[m.end():]
        print(f"  {entry['id']}: {digest[:12]}...")
    MANIFEST.write_text(text, encoding="utf-8")


def all_entries(manifest: dict) -> list[dict]:
    return manifest["books"] + manifest["canaries"]


# --- text preparation -------------------------------------------------------

def strip_boilerplate(raw: str) -> str:
    """Keep only the text between the '*** START OF ...' / '*** END OF ...'
    markers, so no publisher boilerplate or trademarks enter the corpus."""
    start = re.search(r"^\*\*\* ?START OF[^\n]*$", raw, re.M)
    if start:
        raw = raw[start.end():]
    end = re.search(r"^\*\*\* ?END OF[^\n]*$", raw, re.M)
    if end:
        raw = raw[: end.start()]
    return raw.strip()


# split_chapters / with_parts moved to ask_your_library.ingest.chapters (imported
# above and re-exported here so the manifest-driven path is unchanged).


def prepared_path(entry: dict) -> Path:
    return PREPARED_DIR / f"{entry['id']}.json"


def save_prepared(entry: dict, chapters: list[tuple[str, str]], provenance: str) -> None:
    titles = [t for t, _ in chapters]
    dupes = sorted({t for t in titles if titles.count(t) > 1})
    if dupes:
        # Repeated titles collide in chunk_id (the RRF dedupe key) and in the
        # get_chapter lookup. The fix is structural, not cosmetic: give the
        # book a part_regex in the manifest so sections carry their part.
        sys.exit(f"{entry['id']}: {len(dupes)} repeated chapter titles (e.g. {dupes[:3]}). "
                 f"Add a part_regex for this book in corpus/manifest.yaml.")
    PREPARED_DIR.mkdir(parents=True, exist_ok=True)
    prepared_path(entry).write_text(json.dumps({
        "note": entry["id"],
        # "Title — Author", matching the cards' H1 form — so the book field is
        # consistent across both tables and stays unambiguous as the corpus grows
        "book": f"{entry['title']} — {entry['author']}",
        "source": provenance,
        "chapters": [{"title": t, "text": b} for t, b in chapters],
    }, ensure_ascii=False), encoding="utf-8")
    TOC_DIR.mkdir(parents=True, exist_ok=True)
    (TOC_DIR / f"{entry['id']}.json").write_text(
        json.dumps([t for t, _ in chapters], ensure_ascii=False, indent=0), encoding="utf-8")
    total = sum(len(b) for _, b in chapters)
    print(f"  {entry['id']}: {len(chapters)} chapters, {total:,} chars")


def prepare_text(entries: list[dict]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        if entry["source"] != "gutenberg":
            continue
        raw_file = RAW_DIR / f"pg{entry['pg_id']}.txt"
        if not raw_file.exists():
            url = f"https://www.gutenberg.org/cache/epub/{entry['pg_id']}/pg{entry['pg_id']}.txt"
            print(f"  downloading {entry['id']} ...")
            response = requests.get(url, timeout=120)
            response.raise_for_status()
            raw_file.write_text(response.text, encoding="utf-8")
        verify_checksum(entry, raw_file)
        text = strip_boilerplate(raw_file.read_text(encoding="utf-8"))
        chapters = split_chapters(text, entry.get("chapter_regex", DEFAULT_CHAPTER_RE),
                                  entry.get("part_regex"))
        save_prepared(entry, chapters, f"pg:{entry['pg_id']}")


def prepare_canaries(entries: list[dict]) -> None:
    for entry in entries:
        if entry["source"] != "canary":
            continue
        text = (CANARIES_DIR / entry["file"]).read_text(encoding="utf-8")
        chapters = split_chapters(text, entry.get("chapter_regex", DEFAULT_CHAPTER_RE))
        save_prepared(entry, chapters, "canary")


# --- audio preparation (LibriVox items on archive.org) ----------------------

def chapter_mp3s(ia_item: str) -> list[tuple[int, str]]:
    """[(chapter_number, filename)] — one file per chapter; when an item has
    several takes of the same chapter (different readers), the first wins."""
    response = requests.get(f"https://archive.org/metadata/{ia_item}/files", timeout=60)
    response.raise_for_status()
    by_number: dict[int, str] = {}
    for f in response.json()["result"]:
        name = f["name"]
        if not name.endswith("_64kb.mp3"):
            continue
        m = re.search(r"_(\d{2})_", name)
        if m:
            by_number.setdefault(int(m.group(1)), name)
    return sorted(by_number.items())


def transcribe(mp3: Path, out_txt: Path) -> None:
    work = out_txt.parent
    subprocess.run(
        ["caffeinate", "-i", "uvx", "--from", "mlx-whisper==0.4.3", "mlx_whisper",
         str(mp3), "--model", WHISPER_MODEL, "--output-format", "txt",
         "--output-dir", str(work), "--output-name", out_txt.stem,
         "--condition-on-previous-text", "False", "--verbose", "False"],
        check=True, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if not out_txt.exists() or out_txt.stat().st_size == 0:
        raise RuntimeError(f"empty transcript for {mp3.name}")


def prepare_audio(entries: list[dict], retranscribe: bool = False) -> None:
    for entry in entries:
        if entry["source"] != "librivox":
            continue
        shipped = PREPARED_AUDIO_DIR / f"{entry['id']}.json"
        if shipped.exists() and not retranscribe:
            verify_checksum(entry, shipped)
            doc = json.loads(shipped.read_text(encoding="utf-8"))
            save_prepared(entry, [(c["title"], c["text"]) for c in doc["chapters"]], doc["source"])
            print(f"  {entry['id']}: using shipped transcript {shipped.relative_to(REPO)}")
            continue
        if platform.system() != "Darwin":
            sys.exit(f"{entry['id']}: no shipped transcript and transcription needs macOS "
                     f"(MLX Whisper). Restore {shipped.relative_to(REPO)} or run on a Mac.")
        item_dir = RAW_DIR / entry["ia_item"]
        item_dir.mkdir(parents=True, exist_ok=True)
        chapters = []
        for number, name in chapter_mp3s(entry["ia_item"]):
            mp3 = item_dir / name
            txt = item_dir / f"ch{number:02d}.txt"
            if not txt.exists():
                if not mp3.exists():
                    print(f"  downloading {name} ...")
                    url = f"https://archive.org/download/{entry['ia_item']}/{name}"
                    with requests.get(url, timeout=600, stream=True) as r:
                        r.raise_for_status()
                        with open(mp3, "wb") as fh:
                            for block in r.iter_content(1 << 20):
                                fh.write(block)
                print(f"  transcribing ch{number:02d} ({entry['id']}) ...", flush=True)
                transcribe(mp3, txt)
            chapters.append((f"Chapter {number}", txt.read_text(encoding="utf-8").strip()))
        save_prepared(entry, chapters, f"ia:{entry['ia_item']}")


# --- ingest into LanceDB ----------------------------------------------------

def chunk_prepared(doc: dict) -> list[Chunk]:
    """Chunks for one prepared book; chunk_id must be unique (it is the RRF
    dedupe key and the ordering key inside a chapter)."""
    chunks: list[Chunk] = []
    for chapter in doc["chapters"]:
        packed = pack_sentences(split_sentences(chapter["text"]))
        for j, text in enumerate(packed, 1):
            title = chapter["title"]
            chunks.append(Chunk(
                chunk_id=f"{doc['note']}#{title or 'full'}/{j}",
                note=doc["note"],
                book=doc["book"],
                source=doc["source"],
                section=title,
                text=text,
            ))
    ids = [c.chunk_id for c in chunks]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})[:3]
        raise ValueError(f"{doc['note']}: duplicate chunk_id (repeated chapter titles?) e.g. {dup}")
    return chunks


def prepared_docs(entry_ids: list[str]) -> list[dict]:
    """Prepared documents for exactly the manifest entries — a prepared file
    that no longer has a manifest entry would silently contaminate a corpus
    whose sources are supposed to be pinned."""
    expected = {f"{i}.json" for i in entry_ids}
    present = {p.name for p in PREPARED_DIR.glob("*.json")}
    stale = sorted(present - expected)
    if stale:
        sys.exit(f"prepared files without a manifest entry: {stale} — delete them "
                 f"(or restore the entries) before ingesting")
    missing = sorted(expected - present)
    if missing:
        print(f"  WARNING: not prepared yet, skipped: {missing}")
    return [json.loads((PREPARED_DIR / f"{i}.json").read_text(encoding="utf-8"))
            for i in entry_ids if f"{i}.json" in present]


def refuse_unsafe_partial_reingest(db, name: str, embedder) -> None:
    """Guard for `--book`: an in-place upsert must go into a table this exact
    embedder built, or it leaves a table of mixed vectors that is then stamped
    as if it were uniform.

    check_index alone is not enough: it lets a table with NO fingerprint pass on
    matching dims, and dims prove nothing about the model — two 1024-dim models
    look identical to it. So an unstamped table is refused here too, exactly as
    `ayl-add` refuses it; a full rebuild (no --book) or --stage stamp-meta is
    the way out."""
    problem = check_index(db, name, embedder.model, embedder.dims)
    if problem:
        sys.exit(f"refusing partial re-ingest of {name}: {problem}")
    if read_index_meta(db, name) is None:
        sys.exit(
            f"refusing partial re-ingest of {name}: it has no embedding fingerprint, so "
            f"the model that built it is unknown — the dims match {embedder.model!r}, but "
            f"so would another model of the same size, and mixing two models in one table "
            f"degrades retrieval silently.\n"
            f"Stamp it if you know it was built with {embedder.model!r} "
            f"(--stage stamp-meta), or re-ingest the whole corpus without --book.")


def ingest_transcripts_table(backend: str, book_filter: str | None, entry_ids: list[str]) -> None:
    docs = prepared_docs(entry_ids)
    if book_filter:
        docs = [d for d in docs if book_filter.lower() in d["book"].lower()]
    if not docs:
        sys.exit("nothing prepared — run the prepare stages first")

    embedder = get_embedder(backend)
    db = lancedb.connect(DB_PATH)
    name = f"transcripts_{backend}"
    recover_staging(db, name)
    started = time.time()
    progress = {"total": 0}

    def batches():
        for i, doc in enumerate(docs, 1):
            chunks = chunk_prepared(doc)
            vectors = embedder.embed_docs([embedding_text(c) for c in chunks])
            progress["total"] += len(chunks)
            print(f"  [{i}/{len(docs)}] {doc['book']}: {len(chunks)} chunks "
                  f"(total {progress['total']})", flush=True)
            yield doc["note"], rows_for(chunks, vectors)

    if book_filter and name in table_names(db):
        # Re-ingest selected books in place: replace their rows, never append.
        # One table, one embedding model: an upsert with a different embedder
        # would leave a table of mixed vectors and re-stamp it as if it were not.
        refuse_unsafe_partial_reingest(db, name, embedder)
        table = db.open_table(name)
        for note, rows in batches():
            upsert_book_rows(table, note, rows)
    else:
        # Full rebuild through a staging table: the old index stays queryable
        # until the new one is complete.
        rebuild_table(db, name, (rows for _note, rows in batches()))
    total = progress["total"]
    build_fts_index(db, name)
    write_index_meta(db, name, backend, embedder.model, embedder.dims)
    print(f"transcripts done: {total} chunks in {(time.time() - started) / 60:.1f} min")


def ingest_cards_table(backend: str) -> None:
    cards = sorted(CARDS_DIR.glob("*.md"))
    if not cards:
        sys.exit(f"no cards in {CARDS_DIR} — generate them first")
    embedder = get_embedder(backend)
    db = lancedb.connect(DB_PATH)
    name = f"cards_{backend}"
    recover_staging(db, name)

    chunks: list[Chunk] = []
    for path in cards:
        chunks += chunk_card(path)
    vectors = embedder.embed_docs([embedding_text(c) for c in chunks])
    table = rebuild_table(db, name, [rows_for(chunks, vectors)])
    build_fts_index(db, name)
    write_index_meta(db, name, backend, embedder.model, embedder.dims)
    print(f"cards done: {len(cards)} cards -> {table.count_rows()} chunks")


def stamp_existing_tables(backend: str) -> None:
    """Fingerprint tables built before stamps existed. Assumes they were built
    with the embedder configured right now — only run this when that is true."""
    embedder = get_embedder(backend)
    db = lancedb.connect(DB_PATH)
    for name in (f"cards_{backend}", f"transcripts_{backend}"):
        if name not in table_names(db):
            print(f"  {name}: not found, skipped")
            continue
        write_index_meta(db, name, backend, embedder.model, embedder.dims)
        print(f"  {name}: stamped {embedder.model} / {embedder.dims}d")


# --- main -------------------------------------------------------------------

STAGES = ("prepare-text", "prepare-audio", "prepare-canaries", "ingest", "cards",
          "stamp-meta", "checksums")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stage", choices=("all",) + STAGES, default="all")
    ap.add_argument("--backend", default=EMBED_BACKEND, choices=("ollama", "openrouter"))
    ap.add_argument("--book", help="substring filter (ingest stage only)")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip manifest checksum verification of sources")
    ap.add_argument("--retranscribe", action="store_true",
                    help="ignore shipped audio transcripts and run Whisper (macOS)")
    args = ap.parse_args()
    global VERIFY_CHECKSUMS
    VERIFY_CHECKSUMS = not args.no_verify

    manifest = load_manifest()
    entries = all_entries(manifest)
    if args.book and args.stage.startswith("prepare"):
        entries = [e for e in entries if args.book.lower() in e["title"].lower()]

    if args.stage in ("all", "prepare-text"):
        print("== prepare-text ==")
        prepare_text(entries)
    if args.stage in ("all", "prepare-canaries"):
        print("== prepare-canaries ==")
        prepare_canaries(entries)
    if args.stage in ("all", "prepare-audio"):
        print("== prepare-audio ==")
        prepare_audio(entries, retranscribe=args.retranscribe)
    if args.stage in ("all", "ingest"):
        print("== ingest transcripts ==")
        ingest_transcripts_table(args.backend, args.book, [e["id"] for e in entries])
    if args.stage in ("all", "cards"):
        print("== ingest cards ==")
        ingest_cards_table(args.backend)
    if args.stage == "checksums":
        print("== pin source checksums into the manifest ==")
        write_checksums()
    if args.stage == "stamp-meta":
        print("== stamp existing tables with the configured embedding model ==")
        stamp_existing_tables(args.backend)


if __name__ == "__main__":
    main()
