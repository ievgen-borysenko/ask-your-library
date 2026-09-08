"""Pure-function checks for the retrieval harness metrics."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "run_retrieval_eval", Path(__file__).resolve().parents[1] / "eval" / "run_retrieval_eval.py")
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)

WINDOW = [{"book": "Moby Dick — Herman Melville"}, {"book": "Dracula — Bram Stoker"}]


def test_multi_book_coverage_counts_each_expected_book():
    found = harness.books_in_window(WINDOW, ["Moby Dick", "Dracula", "Ivanhoe"])
    assert found == ["Moby Dick", "Dracula"]


def test_best_rank_is_any_expected_book():
    assert harness.best_rank(WINDOW, ["Dracula"]) == 2
    assert harness.best_rank(WINDOW, ["Ivanhoe"]) is None


def test_window_matches_search_both_contract():
    from ask_your_library.nodes import act  # noqa: F401  (import guard only)
    import inspect
    from ask_your_library import nodes
    # the plain search of a step: k=4 per corpus (the book filter after a
    # clarify or in a coverage probe narrows, never widens, the window)
    assert "search_both(state[\"current_query\"], k=4," in inspect.getsource(nodes.act)
    assert harness.WINDOW_PER_CORPUS == 4
