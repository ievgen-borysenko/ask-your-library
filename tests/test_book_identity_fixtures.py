"""The byte-compatibility gate for book identity.

Every string in this file is a row key or a chunk id that is already written
into somebody's index. `note` is the row key a re-ingest deletes by, and
`chunk_id` is the retrieval dedupe key and the ordering key inside a chapter —
so a change of one character in `book_key`, `slug` or the id format does not
break a test somewhere else, it silently orphans rows: the delete matches
nothing, the old rows stay, and the book is in the index twice.

The fixture under `tests/fixtures/book_identity.json` was generated from the
code as it stood before book identity moved into `ask_your_library.bookkey`
(`main` = b2157cb) and is frozen. Regenerate it ONLY when a change to those
strings is the deliberate decision, and then say in the commit message which
indexes have to be rebuilt:

    AYL_FREEZE_BOOK_IDENTITY=1 uv run --group dev pytest -q \\
        tests/test_book_identity_fixtures.py

Two ingest paths are covered, because they mint keys differently:

* the demo corpus (`scripts/ingest_demo_corpus.py`), whose `note` is the
  manifest id and whose chunk ids open with `note#<chapter title>` — the
  chapter titles come from the committed `corpus/toc/`, so this half needs no
  prepared texts and runs in CI;
* `ayl-add` (`ask_your_library.ingest.add_folder`), whose `note` is
  `slug(book_key(...))` and whose chunk ids carry the section ordinal, over the
  three key sources (front matter, a first title line, the file name) and the
  cases that made the current rules what they are.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest
import yaml

from ask_your_library.bookkey import book_key
from ask_your_library.ingest import add_folder

REPO = Path(__file__).resolve().parents[1]
# The demo ingest is a script, not a module of the package; both halves of this
# gate have to run the code that actually writes the index.
_spec = importlib.util.spec_from_file_location(
    "ingest_demo_corpus", REPO / "scripts" / "ingest_demo_corpus.py")
demo = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("ingest_demo_corpus", demo)
_spec.loader.exec_module(demo)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "book_identity.json"
MANIFEST = REPO / "corpus" / "manifest.yaml"
TOC_DIR = REPO / "corpus" / "toc"

# Body text shared by every ayl-add case, so what differs between two cases is
# the key rule under test and never the chunking. Long enough to pack into more
# than one chunk, so the trailing "/N" of a chunk id is exercised.
BODY = ("The lighthouse keeper counted the ships that passed the headland. "
        "He wrote each name in a ledger bound in green cloth. ") * 40

# (case name, file name, file text). The cases are the documented key sources
# and the corrections the review rounds of ADR-015 added.
ADD_FOLDER_CASES = [
    ("front matter, title and author",
     "anything.txt", f"---\ntitle: The Green Ledger\nauthor: A. Keeper\n---\n\n{BODY}"),
    ("front matter, no author",
     "anything2.txt", f"---\ntitle: The Green Ledger\n---\n\n{BODY}"),
    ("first line, em dash",
     "first-line-dash.txt", f"The Green Ledger — A. Keeper\n\n{BODY}"),
    ("first line, markdown heading with 'by'",
     "first-line-by.md", f"# The Green Ledger by A. Keeper\n\n{BODY}"),
    ("file name, hyphen separator",
     "The Green Ledger - A. Keeper.txt", BODY),
    ("file name, no author",
     "The Green Ledger.txt", BODY),
    ("file name, double hyphen separator",
     "The Green Ledger -- A. Keeper.md", BODY),
    ("a title that itself contains a dash",
     "The Ledger - Green - A. Keeper.txt", BODY),
    ("non-ASCII title, which reduces to the bare slug",
     "Книга А.txt", BODY),
    ("another non-ASCII title with the same ASCII reduction",
     "Книга Б.txt", BODY),
    ("markdown sections",
     "Sectioned - A. Keeper.md", f"## One\n\n{BODY}\n\n## Two\n\n{BODY}\n"),
    ("a section literally named 'full', beside an untitled preamble",
     "Preamble - A. Keeper.md", f"{BODY}\n\n## full\n\n{BODY}\n"),
]


def demo_identity() -> list[dict]:
    """Book key, row key and chunk-id opening for every manifest entry.

    The prepared texts are not in the repository, so the chunk ids are pinned
    down to the chapter (`note#<title>`) rather than to the final `/N`: the
    ordinal is the chunker's, and this gate is about identity, not packing."""
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    out = []
    # The canaries are indexed exactly like the books (their rows are excluded
    # from the catalogue by `source`, not by key), so their identity is pinned too.
    for entry in manifest["books"] + manifest["canaries"]:
        toc_path = TOC_DIR / f"{entry['id']}.json"
        titles = json.loads(toc_path.read_text(encoding="utf-8")) if toc_path.exists() else []
        out.append({
            "id": entry["id"],
            "title": entry["title"],
            "author": entry["author"],
            # Through `book_key`, which is what `save_prepared()` now calls and
            # therefore what this half has to exercise: the frozen value was
            # produced by the f-string the demo ingest used before the refactor,
            # so a `book_key` that drifts by one character fails here.
            "book": book_key(entry["title"], entry["author"]),
            "note": entry["id"],
            # Through `chunk_prepared`, the demo ingest's own chunker, so the
            # frozen ids gate the production function and not a copy of its
            # format string. One short sentence per chapter packs to exactly one
            # chunk, and the id is cut back to `note#<chapter>`: the trailing
            # "/N" is the packer's business, and the packer is not what moved.
            "chunk_id_prefixes": [
                c.chunk_id.rsplit("/", 1)[0]
                for c in demo.chunk_prepared({
                    "note": entry["id"],
                    "book": book_key(entry["title"], entry["author"]),
                    "source": "fixture",
                    "chapters": [{"title": title, "text": "One sentence of text."}
                                 for title in titles]})],
        })
    return out


def add_folder_identity(tmp_path: Path) -> list[dict]:
    """Book key, row key and every chunk id `ayl-add` produces per case."""
    out = []
    for name, filename, text in ADD_FOLDER_CASES:
        folder = tmp_path / name.replace(" ", "_").replace(",", "")
        folder.mkdir(parents=True, exist_ok=True)
        (folder / filename).write_text(text, encoding="utf-8")
        book = add_folder.read_book(folder / filename, folder)
        assert book is not None, name
        out.append({
            "case": name,
            "file": filename,
            "book": book.book,
            "note": book.note,
            "chunk_ids": [c.chunk_id for c in add_folder.chunks_for(book)],
        })
    return out


def current(tmp_path: Path) -> dict:
    return {"demo_manifest": demo_identity(), "add_folder": add_folder_identity(tmp_path)}


def test_book_keys_row_keys_and_chunk_ids_are_byte_for_byte_what_the_index_holds(tmp_path):
    produced = current(tmp_path)
    if os.environ.get("AYL_FREEZE_BOOK_IDENTITY"):
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(produced, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
        pytest.skip(f"froze {FIXTURE.relative_to(REPO)} — unset AYL_FREEZE_BOOK_IDENTITY to check it")
    frozen = json.loads(FIXTURE.read_text(encoding="utf-8"))

    # Compared entry by entry so a failure names the book or the rule, not a
    # diff of the whole file.
    frozen_demo = {e["id"]: e for e in frozen["demo_manifest"]}
    produced_demo = {e["id"]: e for e in produced["demo_manifest"]}
    assert sorted(produced_demo) == sorted(frozen_demo)
    for book_id, entry in produced_demo.items():
        assert entry == frozen_demo[book_id], f"demo corpus identity changed for {book_id}"

    frozen_add = {e["case"]: e for e in frozen["add_folder"]}
    produced_add = {e["case"]: e for e in produced["add_folder"]}
    assert sorted(produced_add) == sorted(frozen_add)
    for case, entry in produced_add.items():
        assert entry == frozen_add[case], f"ayl-add identity changed for: {case}"


def test_the_two_non_ascii_titles_stay_two_row_keys(tmp_path):
    """The reason the row key carries a digest (ADR-015's review round): both
    titles reduce to the ASCII slug "book", and one row key for two books means
    the second add deletes the first book's rows."""
    produced = {e["case"]: e for e in add_folder_identity(tmp_path)}
    a = produced["non-ASCII title, which reduces to the bare slug"]
    b = produced["another non-ASCII title with the same ASCII reduction"]
    assert a["note"] != b["note"]
    # Nothing of either title survives the ASCII reduction: the readable part of
    # both row keys is the "Unknown" the file name rule supplied, and only the
    # digest of the full key tells them apart.
    assert a["note"].rsplit("-", 1)[0] == b["note"].rsplit("-", 1)[0] == "unknown"
