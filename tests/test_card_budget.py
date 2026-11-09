"""The card budget of a search step: what `observe` is shown.

`observe`'s time is its input, and on every search step it was shown four book
cards and four transcript chunks, cards first. Cards at rank 3-4 were a large
share of that input and almost never the evidence the step kept. So the agent
asks for `CARD_SLOTS` cards and four transcripts, on a search step and on a
coverage probe alike, and the retrieval eval measures the same window.

No model, no network, no index: the library is a fake table under the real
`search_both`, or `search_both` itself is a fake that records what it was
asked for.
"""
import importlib.util
from pathlib import Path

import pytest

from ask_your_library import library, llm, nodes
from ask_your_library.library import CARD_SLOTS

BOOK = "Some Book — An Author"


# ---------------------------------------------------------------- a fake index under the real search_both
class FakeTable:
    """One corpus: `n` rows, the vector list and the FTS list in the same order,
    so the fused ranking is the row order and the top-k is its first k rows."""

    def __init__(self, corpus: str, n: int):
        self.rows = [{"book": f"Book {corpus} {i} — A", "section": "Chapter 1",
                      "text": f"{corpus} passage {i}", "chunk_id": f"{corpus}/{i}", "_distance": 0.1 * i}
                     for i in range(1, n + 1)]

    def search(self, query, query_type=None):
        rows = self.rows

        class Query:
            def where(self, clause):
                return self

            def limit(self, n):
                return self

            def to_list(self):
                return [dict(row) for row in rows]

        return Query()


@pytest.fixture
def six_per_corpus(monkeypatch):
    """Six rows in each corpus, so any budget below six is visible in the result."""
    tables = {library.TABLES[c]: FakeTable(c, 6) for c in ("cards", "transcripts")}

    class DB:
        def table_names(self):
            return list(tables)
        list_tables = table_names

    monkeypatch.setattr(library.lancedb, "connect", lambda path: DB())
    monkeypatch.setattr(library, "open_table", lambda db, name: tables[name])
    monkeypatch.setattr(library, "embed_query", lambda text: [0.0])
    monkeypatch.setattr(library, "_reported_missing", set())
    return tables


def test_search_both_asks_for_two_cards_and_four_transcripts_by_default(six_per_corpus):
    """The agent's arguments give the agent's window: CARD_SLOTS cards, then
    four transcripts, each corpus in its retriever order."""
    assert CARD_SLOTS == 2
    hits = library.search_both("q", k=4, cards_k=CARD_SLOTS)
    assert [(h["corpus"], h["text"]) for h in hits] == [
        ("cards", "cards passage 1"), ("cards", "cards passage 2"),
        ("transcripts", "transcripts passage 1"), ("transcripts", "transcripts passage 2"),
        ("transcripts", "transcripts passage 3"), ("transcripts", "transcripts passage 4")]


def test_a_caller_may_still_ask_for_four_cards(six_per_corpus):
    """`cards_k=None` (the default) is the old window, `k` per corpus, and an
    explicit four is the same thing: the ablation and the tests that want four
    cards keep getting them."""
    old = library.search_both("q", k=4)
    assert library.search_both("q", k=4, cards_k=4) == old
    assert [h["corpus"] for h in old] == ["cards"] * 4 + ["transcripts"] * 4


# ---------------------------------------------------------------- act asks for the budget
def test_act_asks_the_library_for_the_card_budget_on_a_search_and_on_a_probe(monkeypatch, tmp_path):
    asked = []
    monkeypatch.setattr(nodes, "search_both",
                        lambda query, **kwargs: asked.append((query, kwargs)) or [])
    llm.reset_usage()
    scratchpad = tmp_path / "s.md"
    scratchpad.write_text("")
    base = {"steps_taken": 0, "read_chapters": [], "scratchpad_path": str(scratchpad)}

    nodes.act({**base, "current_query": "white whale"})
    nodes.act({**base, "current_query": f"__book__|{BOOK}|the white whale"})

    assert asked == [("white whale", {"k": 4, "cards_k": CARD_SLOTS, "book": None}),
                     ("the white whale", {"k": 4, "cards_k": CARD_SLOTS, "book": BOOK})]


# ---------------------------------------------------------------- the retrieval eval measures the same window
def _retrieval_harness():
    spec = importlib.util.spec_from_file_location(
        "run_retrieval_eval_card_budget",
        Path(__file__).resolve().parents[1] / "eval" / "run_retrieval_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_retrieval_eval_window_is_the_agent_window(monkeypatch, tmp_path, capsys):
    """The harness imports the budget instead of restating it, and a book at
    cards rank 3 is outside its window while a book at transcripts rank 4 is
    inside: presence over 2 + 4, not 4 + 4."""
    harness = _retrieval_harness()
    assert harness.CARD_SLOTS is library.CARD_SLOTS
    assert harness.WINDOW_PER_CORPUS == 4

    ranked = {"cards": ["C1", "C2", "Card Three", "C4"],
              "transcripts": ["T1", "T2", "T3", "Text Four", "T5"]}
    monkeypatch.setattr(harness, "search", lambda corpus, question, k: [
        {"corpus": corpus, "book": f"{title} — A", "section": "S", "text": "t"}
        for title in ranked[corpus][:k]])
    golden = tmp_path / "golden.yaml"
    golden.write_text("questions:\n"
                      "  - {id: q-card3, question: a, expected_books: [Card Three]}\n"
                      "  - {id: q-text4, question: b, expected_books: [Text Four]}\n", encoding="utf-8")
    monkeypatch.setattr(harness, "GOLDEN_PATH", golden)

    harness.main()
    out = capsys.readouterr().out
    assert "| q-card3 | 1 | 0/1 MISS | 3 | - |" in out
    assert "| q-text4 | 1 | 1/1 | - | 4 |" in out
    assert "window = top-2 cards + top-4 transcripts, presence@6" in out
    assert "single-book presence: 1/2" in out
