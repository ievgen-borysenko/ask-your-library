"""Schema guard over the golden files: shape, not content.

The golden sets are read by the eval harness with `item.get(...)` throughout, so
a misspelled key is silently ignored — `expected_behaviour` instead of
`expected_behavior` turns a clarify item into an ordinary one and the run still
prints a green row, and `expected_fact:` disables the facts row while the report
says 0/0. The contract is therefore not written here: it lives in
`eval/run_agent_eval.py` (`ALLOWED_KEYS` per item type, `REQUIRED_KEYS`,
`FIELD_CHECKS`) next to the code that reads it, where a run of ANY golden file
is refused before the graph is built. This file checks the three files in the
repository against that same table, and adds the rules that only make sense
across a set: ids unique across files, no question asked twice, no fact the
question already contains.

What this file does NOT check: whether the expected books exist in the manifest
(`tests/test_golden_books_in_manifest.py`) or whether a fact is true (a reader).
"""
import importlib.util
import unicodedata
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
GOLDEN_DIR = REPO / "eval" / "golden"

spec = importlib.util.spec_from_file_location("run_agent_eval", REPO / "eval" / "run_agent_eval.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def golden_files() -> list[Path]:
    return sorted(GOLDEN_DIR.glob("*.yaml"))


def items_of(path: Path) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["questions"]


def fold(text: str) -> str:
    """The harness's folding (run_agent_eval.fold), copied rather than imported
    so this guard needs nothing but yaml — as in test_golden_books_in_manifest."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def test_the_harness_guard_accepts_every_golden_file():
    """The same check a run makes, over the files in the repository: allowed keys
    for the item's type, required keys (expected_facts among them, and
    expected_total for a catalogue item), and the type of every field."""
    for path in golden_files():
        try:
            harness.check_golden(items_of(path))
        except ValueError as error:
            pytest.fail(f"{path.name}: {error}")


# Every allowed field, with values its rule must accept and values it must
# refuse. The table is the readable half of the contract: the harness enforces
# it, this says what it means.
FIELD_SAMPLES = {
    "id": (["c01-ivanhoe"], ["", "   ", None, 1]),
    "question": (["Which book?"], ["", None, 1]),
    "type": (["identify", "answer", "aggregation", "refusal", "catalog"], ["Answer", "", None]),
    "notes": (["Reader-verified 2026-09-05."], ["", None, 1]),
    "expected_books": ([[], ["Ivanhoe"]], [["  "], "Ivanhoe", None, [7]]),
    "expected_facts": ([[], ["Cedric"]], [[33], "Cedric", None, ["  "]]),
    "expected_behavior": (["clarify", "clarify_or_answer", "research"], ["clarify_or_ask", "", None, True]),
    "expects_chapter_read": ([True, False], ["true", 1, None]),
    "expected_book_filter": (["Dracula"], ["", "   ", None, 7]),
    "expected_op": (["count", "list", "has", "by_author"], ["counts", "", None, True]),
    "expected_count": ([0, 33], [True, "33", 3.5, None]),
    "expected_total": ([0, 33], [True, "33", 3.5, None]),
    "expected_resolved": ([True, False], ["false", 0, None]),
}


def test_every_allowed_key_has_a_rule_and_the_rule_is_the_one_it_should_be():
    """A key allowed for some item type but typed by nothing would be free text
    the scorer reads as if it meant something, so the two tables must cover each
    other exactly — and each rule is exercised, not just present."""
    allowed = set().union(*harness.ALLOWED_KEYS.values())
    assert allowed == set(harness.FIELD_CHECKS) == set(FIELD_SAMPLES), (
        "keys allowed in an item, keys with a type rule and keys sampled here must be the same set")
    for key, (good, bad) in FIELD_SAMPLES.items():
        check = harness.FIELD_CHECKS[key][0]
        for value in good:
            assert check(value), f"{key} should accept {value!r}"
        for value in bad:
            assert not check(value), f"{key} should refuse {value!r}"


def test_a_catalog_item_may_not_carry_research_keys_or_the_reverse():
    """The two key sets are not interchangeable: expects_chapter_read on a
    catalogue item is never read, and expected_op on a research item is not
    either — both are scoring mistakes that would pass silently."""
    assert "expects_chapter_read" not in harness.ALLOWED_KEYS["catalog"]
    assert "expected_op" not in harness.ALLOWED_KEYS["answer"]
    with pytest.raises(ValueError, match="unknown keys"):
        harness.check_golden([{"id": "k99", "type": "catalog", "question": "how many?",
                               "expected_books": [], "expected_facts": [], "expected_total": 33,
                               "expects_chapter_read": True}])


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
