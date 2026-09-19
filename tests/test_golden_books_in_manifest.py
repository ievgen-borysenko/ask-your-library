"""CI guard: golden questions may only reference books from their shelf's manifest.

An expected_books entry that does not match a manifest title means either a
typo or — worse — a leak of a private-library book name into the public repo.
Free text (notes, questions) is not checked here: that is the job of the
allowlist-based public flip and the secret/path scan.

There are two shelves, each indexed on its own (LIBRARY_DB_PATH) and each with a
manifest of its own: the classics of corpus/manifest.yaml and the engineer's
shelf of corpus-tech/manifest.yaml (#58). A golden file belongs to exactly one
of them — the books of the other shelf are not in the index its run queries, so
a question that named one would be measured against a library that cannot hold
it. SHELVES below is that mapping, and it is also what keeps the catalogue
totals apart: a catalogue item is scored against the size of ITS shelf.
"""
import unicodedata
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "corpus" / "manifest.yaml"
TECH_MANIFEST = REPO / "corpus-tech" / "manifest.yaml"
GOLDEN_DIR = REPO / "eval" / "golden"

# Which shelf each golden file is measured over: the manifest, and the key its
# works are listed under. Anything not named here is a classics set — the
# default, because that is what every set written before the second shelf is.
SHELVES = {"en-tech.yaml": (TECH_MANIFEST, "works")}
CLASSICS = (MANIFEST, "books")


def shelf_of(path: Path) -> tuple[Path, str]:
    return SHELVES.get(path.name, CLASSICS)


def manifest_entries(shelf: tuple[Path, str]) -> list[dict]:
    """Every work of one shelf, canaries included where there are any: they are
    books of the classics library and a golden question may name one."""
    manifest_path, key = shelf
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return manifest[key] + manifest.get("canaries", [])


def manifest_titles(shelf: tuple[Path, str] = CLASSICS) -> list[str]:
    return [entry["title"] for entry in manifest_entries(shelf)]


def manifest_keys(shelf: tuple[Path, str] = CLASSICS) -> list[str]:
    """The book keys the index carries, "title — author" exactly as
    scripts/ingest_demo_corpus.py builds them from the manifest (and as the
    front matter written by scripts/fetch_tech_shelf.py has `ayl-add` build them
    for the second shelf). Canaries are left out: they are fixtures, and
    list_books drops them by their source column, so a catalogue item could
    never list one."""
    manifest_path, key = shelf
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    return [f"{entry['title']} — {entry['author']}" for entry in manifest[key]]


def golden_files() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.yaml"))


def test_manifest_exists_and_has_books():
    titles = manifest_titles()
    assert len(titles) >= 14, f"manifest unexpectedly small: {len(titles)} titles"


def test_every_shelf_named_here_has_a_manifest_with_works_in_it():
    """A mapping that pointed at a file which is not there, or at the wrong key
    inside it, would send every golden file of that shelf back to the classics
    default — where its books do not exist and the failure reads as a typo in
    the golden set rather than as a broken mapping."""
    for name, shelf in SHELVES.items():
        assert (GOLDEN_DIR / name).exists(), f"{name} is mapped to a shelf but does not exist"
        assert manifest_titles(shelf), f"{shelf[0]} holds no {shelf[1]}"


def test_golden_dir_not_empty():
    assert golden_files(), f"no golden files in {GOLDEN_DIR}"


def fold(text: str) -> str:
    """The eval harness's folding (run_agent_eval.fold), copied rather than
    imported so this guard needs nothing but yaml."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def test_every_expected_book_is_in_manifest():
    def known(expected: str, names: list[str]) -> bool:
        # same matching rule as the eval harness: case-insensitive substring of a
        # manifest title, or of the key a catalog item names it by
        return any(expected.lower() in name.lower() for name in names)

    problems = []
    for path in golden_files():
        shelf = shelf_of(path)
        names = manifest_titles(shelf) + manifest_keys(shelf)
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            for expected in item.get("expected_books") or []:
                if not known(expected, names):
                    problems.append(f"{path.name}:{item['id']}: {expected!r}")
    assert not problems, "expected_books outside the demo manifest:\n" + "\n".join(problems)


def test_catalog_items_name_manifest_keys_exactly():
    """A `catalog` item is scored on set EQUALITY against the KEYS the code
    listed, folded (run_agent_eval.score): a substring of a manifest title,
    which is all the check above asks for, can never equal one, and a bare
    title never equals the key "Title — Author" the index carries — so such an
    item could only ever fail. The stricter rule belongs where the typo is
    made."""
    problems = []
    for path in golden_files():
        folded = {fold(key) for key in manifest_keys(shelf_of(path))}
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            if item["type"] != "catalog":
                continue
            for expected in item.get("expected_books") or []:
                if fold(expected) not in folded:
                    problems.append(f"{path.name}:{item['id']}: {expected!r} is no manifest key")
    assert not problems, ("catalog expected_books that are not manifest keys:\n"
                          + "\n".join(problems))


def test_catalog_items_expect_the_whole_corpus_as_the_total():
    """expected_total is the catalogue's own size, not the item's answer: it is
    what stops a targeted run (k03-k05 alone) from passing over a partial index,
    where a "no" and a short list are honest answers about the wrong library.
    The scorer fails an item that names no total; this says which number it is."""
    problems = []
    for path in golden_files():
        total = len(manifest_keys(shelf_of(path)))
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            if item["type"] != "catalog":
                continue
            if item.get("expected_total") != total:
                problems.append(f"{path.name}:{item['id']}: expected_total "
                                f"{item.get('expected_total')!r}, the manifest has {total} books")
    assert not problems, "\n".join(problems)


def test_a_catalog_item_counts_the_books_it_lists():
    """expected_count and expected_books are scored separately and must agree,
    or the item asks for a count that its own list contradicts."""
    problems = []
    for path in golden_files():
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            if item["type"] != "catalog" or not {"expected_count", "expected_books"} <= set(item):
                continue
            if item["expected_count"] != len(item["expected_books"]):
                problems.append(f"{path.name}:{item['id']}: expected_count "
                                f"{item['expected_count']} but "
                                f"{len(item['expected_books'])} expected_books")
    assert not problems, "\n".join(problems)


def test_refusal_questions_have_no_expected_books():
    for path in golden_files():
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            if item["type"] == "refusal":
                assert not item.get("expected_books"), \
                    f"{path.name}:{item['id']}: refusal must have empty expected_books"


def test_manifest_ids_and_titles_unique():
    """A duplicate id silently overwrites prepared/<id>.json and cards/<id>.md;
    a duplicate (title, author) pair collides in the DB's book field (editions/
    translations must carry a qualifier, e.g. kobzar-hunter-tr). Fail loudly."""
    entries = manifest_entries(CLASSICS)
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), f"duplicate ids: {sorted(set(i for i in ids if ids.count(i) > 1))}"
    pairs = [(e["title"], e["author"]) for e in entries]
    assert len(pairs) == len(set(pairs)), "duplicate (title, author) — add an edition/translation qualifier"
