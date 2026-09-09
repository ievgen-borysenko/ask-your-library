"""CI guard: golden questions may only reference books from the demo manifest.

An expected_books entry that does not match a manifest title means either a
typo or — worse — a leak of a private-library book name into the public repo.
Free text (notes, questions) is not checked here: that is the job of the
allowlist-based public flip and the secret/path scan.
"""
import unicodedata
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "corpus" / "manifest.yaml"
GOLDEN_DIR = REPO / "eval" / "golden"


def manifest_titles() -> list[str]:
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["books"] + manifest.get("canaries", [])
    return [entry["title"] for entry in entries]


def golden_files() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.yaml"))


def test_manifest_exists_and_has_books():
    titles = manifest_titles()
    assert len(titles) >= 14, f"manifest unexpectedly small: {len(titles)} titles"


def test_golden_dir_not_empty():
    assert golden_files(), f"no golden files in {GOLDEN_DIR}"


def fold(text: str) -> str:
    """The eval harness's folding (run_agent_eval.fold), copied rather than
    imported so this guard needs nothing but yaml."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def test_every_expected_book_is_in_manifest():
    titles = manifest_titles()

    def known(expected: str) -> bool:
        # same matching rule as the eval harness: case-insensitive substring
        return any(expected.lower() in title.lower() for title in titles)

    problems = []
    for path in golden_files():
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            for expected in item.get("expected_books") or []:
                if not known(expected):
                    problems.append(f"{path.name}:{item['id']}: {expected!r}")
    assert not problems, "expected_books outside the demo manifest:\n" + "\n".join(problems)


def test_catalog_items_name_manifest_titles_exactly():
    """A `catalog` item is scored on set EQUALITY against the titles the code
    listed, folded (run_agent_eval.score): a substring of a manifest title,
    which is all the check above asks for, can never equal one, so such an item
    could only ever fail. The stricter rule belongs where the typo is made."""
    folded = {fold(title) for title in manifest_titles()}
    problems = []
    for path in golden_files():
        golden = yaml.safe_load(path.read_text(encoding="utf-8"))
        for item in golden["questions"]:
            if item["type"] != "catalog":
                continue
            for expected in item.get("expected_books") or []:
                if fold(expected) not in folded:
                    problems.append(f"{path.name}:{item['id']}: {expected!r} is no manifest title")
    assert not problems, ("catalog expected_books that are not manifest titles:\n"
                          + "\n".join(problems))


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
    manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["books"] + manifest.get("canaries", [])
    ids = [e["id"] for e in entries]
    assert len(ids) == len(set(ids)), f"duplicate ids: {sorted(set(i for i in ids if ids.count(i) > 1))}"
    pairs = [(e["title"], e["author"]) for e in entries]
    assert len(pairs) == len(set(pairs)), "duplicate (title, author) — add an edition/translation qualifier"
