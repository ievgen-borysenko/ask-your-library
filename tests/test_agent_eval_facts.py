"""The facts row of the agent eval: expected_facts against the answer text.

A fourth deterministic row beside titles, behaviour and provenance, and
deliberately not a fourth term in the behaviour verdict — ADR-010 rejected a
composite score, and presence of a string is not correctness. What is pinned
here: the matching rule (folded, whitespace-normalised substring, nothing
fuzzy), the empty case, and the invariant that behavior_ok does not move when
the facts do.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("run_agent_eval", REPO / "eval" / "run_agent_eval.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


def run(answer="", clarify=False, checked=1, chapters=None, catalog=None, steps=0, book_filter=""):
    return {"answer": answer, "clarify_asked": clarify, "provenance": {"checked": checked},
            "read_chapters": chapters or [], "catalog": catalog or {}, "steps_taken": steps,
            "book_filter": book_filter}


def test_every_expected_fact_present_is_ok():
    item = {"type": "answer", "expected_books": ["Ivanhoe"], "expected_facts": ["Cedric", "Richard"]}
    sc = harness.score(item, run("Ivanhoe: Cedric disinherits him, and King Richard returns."))
    assert (sc["facts_found"], sc["facts_expected"], sc["facts_ok"]) == (2, 2, True)


def test_a_missing_fact_is_counted_and_not_ok():
    item = {"type": "answer", "expected_books": ["Ivanhoe"], "expected_facts": ["Cedric", "Richard"]}
    sc = harness.score(item, run("Ivanhoe. Cedric is his father."))
    assert (sc["facts_found"], sc["facts_expected"], sc["facts_ok"]) == (1, 2, False)


def test_no_expected_facts_scores_zero_of_zero_and_ok():
    """A refusal carries no facts; the row must not invent a failure for it, and
    the totals count only items that name at least one fact."""
    item = {"type": "refusal", "expected_books": [], "expected_facts": []}
    sc = harness.score(item, run("That book is not in the library.", checked=0))
    assert (sc["facts_found"], sc["facts_expected"], sc["facts_ok"]) == (0, 0, True)
    missing_key = harness.score({"type": "answer", "expected_books": ["Ivanhoe"]}, run("Ivanhoe"))
    assert (missing_key["facts_found"], missing_key["facts_expected"], missing_key["facts_ok"]) == (0, 0, True)


def test_matching_is_case_insensitive():
    item = {"type": "answer", "expected_books": ["Treasure Island"],
            "expected_facts": ["black spot", "Billy Bones"]}
    sc = harness.score(item, run("Treasure Island: the BLACK SPOT handed to billy bones."))
    assert sc["facts_ok"] and sc["facts_found"] == 2


def test_matching_normalises_whitespace_on_both_sides():
    """A fact wrapped across a line break in the answer is the same fact, and a
    fact written with a double space in the golden file is too."""
    item = {"type": "answer", "expected_books": ["Moby Dick"],
            "expected_facts": ["harpoon  line"]}
    sc = harness.score(item, run("Moby Dick: the harpoon\n   line catches Ahab round the neck."))
    assert sc["facts_ok"] and sc["facts_found"] == 1


def test_matching_is_substring_only_never_fuzzy():
    """No stemming, no synonyms, no edit distance: a red facts row means exactly
    'this string is not in the answer', which is what makes it readable."""
    item = {"type": "answer", "expected_books": ["Frankenstein"], "expected_facts": ["female companion"]}
    assert not harness.score(item, run("Frankenstein: he began a second creature, a mate."))["facts_ok"]
    assert not harness.score(item, run("Frankenstein: a companion, female, was begun."))["facts_ok"]
    assert harness.score(item, run("Frankenstein: the female companion he destroyed."))["facts_ok"]
    # and it is a substring rule, not a word rule — stated here rather than left
    # to be discovered: a longer word containing the fact counts as present
    assert harness.score(item, run("Frankenstein: the female companionship"))["facts_ok"]


CATALOG_OK = {"op": "count", "count": 2, "total": 2,
              "books": ["Ivanhoe — Walter Scott", "Dracula — Bram Stoker"]}
CATALOG_ITEM = {"type": "catalog", "expected_op": "count", "expected_count": 2, "expected_total": 2,
                "expected_books": ["Ivanhoe — Walter Scott", "Dracula — Bram Stoker"]}

# Every branch of score(), each in the shape that passes and the shape that
# fails: (name, item, result, expected behavior_ok).
BRANCHES = [
    ("answer pass", {"type": "answer", "expected_books": ["Ivanhoe"]},
     run("Ivanhoe is the book."), True),
    ("answer fail", {"type": "answer", "expected_books": ["Ivanhoe"]},
     run("Some other book entirely."), False),
    ("aggregation fail on one missing title",
     {"type": "aggregation", "expected_books": ["Ivanhoe", "Dracula"]}, run("Ivanhoe alone."), False),
    ("refusal pass", {"type": "refusal", "expected_books": []},
     run("That book is not in the library.", checked=0), True),
    ("refusal fail, narrated from memory", {"type": "refusal", "expected_books": []},
     run("Tom whitewashed the fence and sold the privilege to every boy who passed.", checked=0), False),
    ("research pass", {"type": "answer", "expected_books": [], "expected_behavior": "research"},
     run("Several books mention London.", steps=2), True),
    ("research fail, no search", {"type": "answer", "expected_books": [], "expected_behavior": "research"},
     run("Several books mention London.", steps=0), False),
    ("clarify pass", {"type": "identify", "expected_books": ["Ivanhoe"], "expected_behavior": "clarify"},
     run("", clarify=True), True),
    ("clarify fail, answered instead",
     {"type": "identify", "expected_books": ["Ivanhoe"], "expected_behavior": "clarify"},
     run("Ivanhoe."), False),
    ("clarify_or_answer pass by answering",
     {"type": "identify", "expected_books": ["Ivanhoe"], "expected_behavior": "clarify_or_answer"},
     run("Ivanhoe."), True),
    ("clarify_or_answer fail",
     {"type": "identify", "expected_books": ["Ivanhoe"], "expected_behavior": "clarify_or_answer"},
     run("No idea."), False),
    ("drill-down yes", {"type": "answer", "expected_books": ["Moby Dick"], "expects_chapter_read": True},
     run("Moby Dick.", chapters=["Moby Dick — Herman Melville|CHAPTER 135"]), True),
    ("drill-down no", {"type": "answer", "expected_books": ["Moby Dick"], "expects_chapter_read": True},
     run("Moby Dick."), False),
    ("book filter expected", {"type": "answer", "expected_books": ["Dracula"], "expected_book_filter": "Dracula"},
     run("Dracula.", book_filter="Dracula — Bram Stoker"), True),
    ("book filter wrong book", {"type": "answer", "expected_books": ["Dracula"], "expected_book_filter": "Dracula"},
     run("Dracula.", book_filter="Ivanhoe — Walter Scott"), False),
    ("catalogue pass", CATALOG_ITEM, run("You have 2 books.", catalog=CATALOG_OK), True),
    ("catalogue fail on the count", CATALOG_ITEM,
     run("You have 2 books.", catalog={**CATALOG_OK, "count": 3}), False),
    ("catalogue misroute of a content question", {"type": "answer", "expected_books": ["Ivanhoe"]},
     run("Ivanhoe.", catalog=CATALOG_OK), False),
]


@pytest.mark.parametrize("name,item_,result,expected", BRANCHES, ids=[b[0] for b in BRANCHES])
@pytest.mark.parametrize("facts", ["absent", "satisfied", "unsatisfied"])
def test_behavior_ok_is_unchanged_by_the_facts_row(name, item_, result, expected, facts):
    """ADR-010: rows that cannot be confused. Over every branch of score() and
    every state of the facts row, the verdict is the same one the item would get
    with no expected_facts at all — the row is reported beside it, never in it."""
    word = result["answer"].split()[0] if result["answer"].split() else None
    variants = {"absent": None, "satisfied": [word] if word else [], "unsatisfied": ["Thibermesnil"]}
    scored = harness.score({**item_, "expected_facts": variants[facts]} if variants[facts] is not None
                           else dict(item_), result)
    assert scored["behavior_ok"] is expected, f"{name}: behaviour moved with facts {facts}"
    assert scored["behavior_ok"] == harness.score(dict(item_), result)["behavior_ok"]
    if facts == "unsatisfied":
        assert scored["facts_ok"] is False
    if facts == "satisfied" and word:
        assert scored["facts_ok"] is True


def test_the_catalog_branch_carries_the_facts_row_too():
    """catalog items return early from score(); the row must still be there, and
    still not touch the structured verdict."""
    item = {"type": "catalog", "expected_op": "count", "expected_count": 2, "expected_total": 2,
            "expected_books": ["Ivanhoe — Walter Scott", "Dracula — Bram Stoker"],
            "expected_facts": ["2"]}
    listing = {"op": "count", "count": 2, "total": 2,
               "books": ["Ivanhoe — Walter Scott", "Dracula — Bram Stoker"]}
    sc = harness.score(item, run("You have 2 books.", catalog=listing))
    assert sc["behavior_ok"] and sc["facts_ok"] and sc["facts_expected"] == 1
    missed = harness.score({**item, "expected_facts": ["33"]}, run("You have 2 books.", catalog=listing))
    assert missed["behavior_ok"] and not missed["facts_ok"]


def item(**over) -> dict:
    """A golden item the guard accepts, to be spoiled one key at a time."""
    return {"id": "c01-ivanhoe", "type": "answer", "question": "Which book?",
            "expected_books": ["Ivanhoe"], "expected_facts": ["Cedric"], **over}


def test_the_guard_accepts_a_well_formed_file():
    harness.check_golden([item(), item(id="c08-refusal", type="refusal", expected_books=[],
                                       expected_facts=[]),
                          item(id="k01-count", type="catalog", expected_facts=["33"],
                               expected_op="count", expected_count=33, expected_total=33)])


def test_a_bad_expected_facts_value_is_refused_by_name():
    """The value is matched as a substring per fact, so int, bare string and
    empty string each break the row in a different silent way."""
    for bad in ([item(id="unquoted-number", expected_facts=[33])],
                [item(id="bare-string", expected_facts="Cedric")],
                [item(id="blank-fact", expected_facts=["Cedric", "   "])]):
        with pytest.raises(ValueError) as error:
            harness.check_golden(bad)
        assert bad[0]["id"] in str(error.value)


def test_a_missing_expected_facts_key_is_refused():
    """It used to be read as an empty list: a typo like `expected_fact:` would
    turn the row off for that item and the run would end with a green 0/0 that
    measured nothing. A refusal says it has no facts by carrying an empty list."""
    with pytest.raises(ValueError) as error:
        harness.check_golden([{"id": "no-facts-key", "type": "answer", "question": "q",
                               "expected_books": ["Ivanhoe"]}])
    assert "no-facts-key" in str(error.value) and "expected_facts" in str(error.value)


def test_a_misspelled_key_is_refused_rather_than_ignored():
    """The whole class the guard exists for: score() reads items with .get(), so
    a typo is not an error, it is a different (green) measurement."""
    spoiled = {"expected_fact": ["Cedric"], "expected_behaviour": "clarify",
               "expects_chapter_reads": True, "expected_totals": 33}
    for key, value in spoiled.items():
        bad = item(id=f"typo-{key}")
        bad[key] = value
        with pytest.raises(ValueError) as error:
            harness.check_golden([bad])
        assert key in str(error.value) and f"typo-{key}" in str(error.value)


def test_an_unknown_type_and_an_out_of_enum_value_are_refused():
    with pytest.raises(ValueError, match="type 'Answer'"):
        harness.check_golden([item(type="Answer")])
    with pytest.raises(ValueError, match="expected_behavior"):
        harness.check_golden([item(expected_behavior="clarify_or_ask")])
    with pytest.raises(ValueError, match="expected_op"):
        harness.check_golden([item(id="k99", type="catalog", expected_total=33, expected_op="counts")])
    with pytest.raises(ValueError, match="expected_total"):
        harness.check_golden([item(id="k98", type="catalog")])


def test_every_problem_in_the_file_is_reported_at_once():
    """Fixing a golden file one failed run at a time is the cost this avoids."""
    with pytest.raises(ValueError) as error:
        harness.check_golden([item(id="first", expected_facts=[33]), item(id="second", type="nonsense")])
    assert "first" in str(error.value) and "second" in str(error.value)


def test_a_bad_golden_file_fails_before_the_graph_is_built(tmp_path, monkeypatch):
    """GOLDEN_PATH points wherever the caller says. The refusal has to come
    before the first model call, not from the scorer of item 27."""
    golden = tmp_path / "golden.yaml"
    golden.write_text("questions:\n- id: unquoted-number\n  type: answer\n  question: q\n"
                      "  expected_books: []\n  expected_facts:\n  - 33\n", encoding="utf-8")

    def never():
        raise AssertionError("the graph was built: the run would have been billed")

    monkeypatch.setattr(harness, "build_graph", never)
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py"])
    with pytest.raises(ValueError, match="unquoted-number"):
        harness.main()


def load_summarizer():
    spec = importlib.util.spec_from_file_location(
        "summarize_report", REPO / "eval" / "summarize_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_report_the_harness_writes_is_the_report_the_summary_reads(tmp_path, capsys, monkeypatch):
    """End to end over the two files that must agree: the harness writes the facts
    onto the question line and into the totals block, and summarize_report finds
    both. Written as one test because a format change on either side that the
    other does not follow is silent — the summary would simply stop mentioning
    the row."""
    golden = tmp_path / "golden.yaml"
    golden.write_text("questions:\n"
                      "- id: full\n  type: answer\n  question: q1\n  expected_books:\n  - Ivanhoe\n"
                      "  expected_facts:\n  - Cedric\n"
                      "- id: partial\n  type: answer\n  question: q2\n  expected_books:\n  - Ivanhoe\n"
                      "  expected_facts:\n  - Cedric\n  - Saturday\n", encoding="utf-8")

    def fake_run_one(graph, item, attempt=1):   # the harness passes the attempt since --repeat
        answer = ("Ivanhoe: Cedric disinherited him." if item["id"] == "full"
                  else "Ivanhoe: Cedric, and then Monday.")
        result = {"id": item["id"], "type": item["type"], "question": item["question"], "answer": answer,
                  "verification": "v", "provenance": {}, "steps_taken": 1, "read_chapters": [],
                  "evidence_items": 0, "clarify_asked": False, "clarify_candidates": [],
                  "clarify_unresolved": False, "clarify_chosen": "", "seconds": 1, "steps_log": [],
                  "cost_usd": 0.0, "llm_calls": 0, "tokens_in": 0, "tokens_out": 0}
        result["score"] = harness.score(item, result)
        return result

    monkeypatch.setattr(harness, "run_one", fake_run_one)
    monkeypatch.setattr(harness, "build_graph", lambda: object())
    monkeypatch.setattr(harness, "run_fingerprint", lambda: "code test")
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)
    monkeypatch.setattr(harness, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(sys, "argv", ["run_agent_eval.py"])
    harness.main()
    path = next(tmp_path.glob("answers-*.md"))
    report = path.read_text(encoding="utf-8")
    assert "— PASS: titles 1/1, facts 1/1\n" in report
    assert "— PASS: titles 1/1, facts 1/2 NO\n" in report
    # the tail contract summarize_report parses: one "\n---\n" before the totals
    totals = report[report.rindex("\n---\n") + 5:]
    assert "expected facts found 2/3; answers carrying every expected fact 1/2" in totals
    assert totals.rstrip().endswith("manual correctness: not scored — tick the checkboxes above")

    monkeypatch.setattr(sys, "argv", ["summarize_report.py", str(path)])
    capsys.readouterr()
    load_summarizer().main()
    out = capsys.readouterr().out
    assert "expected facts found 2/3" in out
    assert "`partial`: PASS on behaviour but only 1/2 expected facts are present" in out


def test_summary_carries_the_facts_totals_and_names_incomplete_answers(tmp_path, capsys, monkeypatch):
    """The totals block after the last '\\n---\\n' is what summarize_report prints
    verbatim, so the facts row travels with it; a PASS missing facts is listed
    rather than silently green."""
    report = tmp_path / "answers-3.md"
    report.write_text(
        "# Agent eval — x\n\nrun: code abc\n\n"
        "## c06-fogg (answer, 3 steps, 9s, $0.01, 4 calls, 10 in / 5 out tokens) — "
        "PASS: titles 1/1, facts 1/3 NO\n\ntext\n\n"
        "## c02-huck (answer, 2 steps, 5s) — PASS: titles 1/1, facts 3/3\n\ntext\n\n"
        "---\n2 completed, 0 errors, 0 clarify interrupts; quotes verified 4/4; evidence items 6\n"
        "behavior PASS 2/2 (answer 2/2); expected titles mentioned 2/2\n"
        "expected facts found 4/6; answers carrying every expected fact 1/2 "
        "(substring presence, not correctness; not part of behaviour PASS)\n"
        "manual correctness: not scored — tick the checkboxes above\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_report.py", str(report)])
    load_summarizer().main()
    out = capsys.readouterr().out
    assert "expected facts found 4/6" in out
    assert "answers carrying every expected fact 1/2" in out
    assert "`c06-fogg`: PASS on behaviour but only 1/3 expected facts are present" in out
    assert "`c02-huck`" not in out
    assert "- none" not in out


def test_a_report_written_before_this_row_existed_still_summarises(tmp_path, capsys, monkeypatch):
    """Every report under docs/eval-results/ was written without a facts column;
    the summary must still read them, and say nothing about facts."""
    report = tmp_path / "answers-old.md"
    report.write_text("# Agent eval — x\n\nrun: code abc\n\n"
                      "## c01-a (identify, 1 steps, 3s) — PASS: titles 1/1\n\ntext\n\n"
                      "---\n1 completed, 0 errors, 0 clarify interrupts; quotes verified 1/1; evidence items 1\n"
                      "behavior PASS 1/1 (identify 1/1); expected titles mentioned 1/1\n"
                      "manual correctness: not scored — tick the checkboxes above\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_report.py", str(report)])
    load_summarizer().main()
    out = capsys.readouterr().out
    assert "behavior PASS 1/1" in out and "- none" in out and "facts" not in out.split("## Failures")[0]
