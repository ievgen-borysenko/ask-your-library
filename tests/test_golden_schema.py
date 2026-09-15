"""Schema guard over the golden files: shape, not content.

The golden sets are read by the eval harness with `item.get(...)` throughout, so
a misspelled key is silently ignored — `expected_behaviour` instead of
`expected_behavior` turns a clarify item into an ordinary one and the run still
prints a green row. The allowed sets below are what the three files use today
plus `expected_facts`; a key outside them is a typo until someone adds it here
on purpose, which is the point.

What this file does NOT check: whether the expected books exist in the manifest
(`tests/test_golden_books_in_manifest.py`) or whether a fact is true (a reader).
"""
from pathlib import Path

import unicodedata

import yaml

REPO = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO / "eval" / "golden"

REQUIRED = {"id", "question", "type", "expected_books", "expected_facts"}

# Per file, because the sets are not interchangeable: the catalogue items are
# scored on a structured result and carry keys no research item may use, and a
# research key on a catalogue item (or the reverse) is a scoring mistake, not a
# style one.
COMMON = REQUIRED | {"notes", "expected_behavior"}
ALLOWED = {
    "en-demo.yaml": COMMON,
    "en-demo-extended.yaml": COMMON | {"expects_chapter_read"},
    "en-demo-catalog.yaml": COMMON | {"expected_op", "expected_count", "expected_total",
                                      "expected_resolved", "expected_book_filter",
                                      "expects_chapter_read"},
}

TYPES = {"identify", "answer", "aggregation", "refusal", "catalog"}


def golden_files() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.yaml"))


def items_of(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def fold(text: str) -> str:
    """The harness's folding (run_agent_eval.fold), copied rather than imported
    so this guard needs nothing but yaml — as in test_golden_books_in_manifest."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def test_every_golden_file_has_a_declared_key_set():
    """A new golden set must state its allowed keys here before it can be run:
    otherwise the guard silently stops covering the file it was written for."""
    undeclared = [p.name for p in golden_files() if p.name not in ALLOWED]
    assert not undeclared, f"golden files with no declared key set: {undeclared}"


def test_no_unknown_keys():
    problems = []
    for path in golden_files():
        for item in items_of(path):
            unknown = set(item) - ALLOWED[path.name]
            if unknown:
                problems.append(f"{path.name}:{item.get('id')}: unknown keys {sorted(unknown)}")
    assert not problems, "\n".join(problems)


def test_required_keys_present():
    problems = []
    for path in golden_files():
        for index, item in enumerate(items_of(path)):
            missing = REQUIRED - set(item)
            if missing:
                problems.append(f"{path.name}:{item.get('id', f'#{index}')}: missing {sorted(missing)}")
    assert not problems, "\n".join(problems)


def test_field_types():
    problems = []
    for path in golden_files():
        for item in items_of(path):
            where = f"{path.name}:{item.get('id')}"
            for key in ("id", "question"):
                if not isinstance(item.get(key), str) or not item.get(key).strip():
                    problems.append(f"{where}: {key} must be a non-empty string")
            if item.get("type") not in TYPES:
                problems.append(f"{where}: type {item.get('type')!r} not in {sorted(TYPES)}")
            books = item.get("expected_books")
            if not isinstance(books, list) or not all(isinstance(b, str) and b.strip() for b in books):
                problems.append(f"{where}: expected_books must be a list of non-empty strings")
    assert not problems, "\n".join(problems)


def test_expected_facts_are_short_non_empty_strings():
    """A fact is matched as a substring of the answer (run_agent_eval.facts_score),
    so an empty string would be found in every answer and a number written as a
    number (33, not "33") would not be a string at all. Refusal items, and the
    clarify items whose candidates contradict each other, carry an empty list —
    which is allowed and means 'this row does not measure this item'."""
    problems = []
    for path in golden_files():
        for item in items_of(path):
            where = f"{path.name}:{item.get('id')}"
            facts = item.get("expected_facts")
            if not isinstance(facts, list):
                problems.append(f"{where}: expected_facts must be a list")
                continue
            for fact in facts:
                if not isinstance(fact, str):
                    problems.append(f"{where}: fact {fact!r} is {type(fact).__name__}, not a string "
                                    "(quote numbers)")
                elif not fact.strip():
                    problems.append(f"{where}: an empty fact matches every answer")
                elif len(fact) > 60:
                    problems.append(f"{where}: fact {fact!r} is a sentence, not a checkable string")
            if len(facts) > 4:
                problems.append(f"{where}: {len(facts)} facts; keep it to the few a reader can check")
    assert not problems, "\n".join(problems)


def test_no_fact_is_already_in_its_own_question():
    """A fact the question itself contains is free: the answer restates the
    question — every answer does, at least partly — and the row goes green
    without measuring anything. "Was he an army doctor back from Afghanistan?"
    was exactly that, and so was asking a catalogue item about Ivanhoe to say
    "Ivanhoe". Folded on both sides, the same rule the scorer matches by."""
    def flat(text: str) -> str:
        return " ".join(fold(text).split())

    problems = []
    for path in golden_files():
        for item in items_of(path):
            question = flat(item["question"])
            for fact in item.get("expected_facts") or []:
                if flat(fact) in question:
                    problems.append(f"{path.name}:{item['id']}: {fact!r} is already in the question")
    assert not problems, "facts an answer scores by echoing the question:\n" + "\n".join(problems)


def test_refusal_items_carry_no_facts():
    """There is nothing for a refusal to say; a fact here would ask the answer to
    narrate the book it must decline to narrate."""
    problems = [f"{path.name}:{item['id']}"
                for path in golden_files() for item in items_of(path)
                if item["type"] == "refusal" and item.get("expected_facts")]
    assert not problems, "refusal items with expected_facts: " + ", ".join(problems)


def test_ids_are_unique_within_and_across_the_files():
    seen = {}
    problems = []
    for path in golden_files():
        for item in items_of(path):
            if item["id"] in seen:
                problems.append(f"{item['id']}: in both {seen[item['id']]} and {path.name}")
            seen[item["id"]] = path.name
    assert not problems, "\n".join(problems)


def test_questions_are_not_duplicated():
    """The same question in two sets (or twice in one) is measured twice and
    reported as two independent results."""
    seen = {}
    problems = []
    for path in golden_files():
        for item in items_of(path):
            key = " ".join(item["question"].lower().split())
            if key in seen:
                problems.append(f"{path.name}:{item['id']} repeats the question of {seen[key]}")
            seen[key] = f"{path.name}:{item['id']}"
    assert not problems, "\n".join(problems)
