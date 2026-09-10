"""Retriever eval (no LLM, free): does the retriever window for the RAW golden
question contain the expected book(s)?

The window mirrors `search_both(query, k=4)`: top-4 card chunks followed by
top-4 transcript chunks (8 hits, per-corpus order, no fusion across corpora).
This is a component baseline, not agent quality: the agent's planner rewrites
the question into its own English queries, and clarify / drill-down / answer
correctness are measured by eval/run_agent_eval.py. This harness measures:

- single-book questions: is the book present in the window (presence@8)?
- multi-book questions (aggregation / guaranteed clarify): coverage = how many
  of the expected books are present, and whether ALL of them are.

Per-corpus ranks to depth 8 are printed as a diagnostic: a rank <= 4 in either
corpus is what puts a book into the window. hit@2/hit@4 per corpus and MRR
(best-of-two) are kept for comparability with earlier runs but are NOT agent
metrics — do not publish them as such.

  uv run eval/run_retrieval_eval.py
  GOLDEN_PATH=... LIBRARY_DB_PATH=... uv run eval/run_retrieval_eval.py
"""
import os
from pathlib import Path

import yaml

from ask_your_library.library import search

GOLDEN_PATH = Path(os.environ.get("GOLDEN_PATH", Path(__file__).parent / "golden" / "en-demo.yaml"))
DIAG_K = 8          # per-corpus diagnostic depth
WINDOW_PER_CORPUS = 4   # must equal the k the agent passes to search_both


def best_rank(hits: list[dict], expected_books: list[str]) -> int | None:
    """1-based rank of the first hit whose book matches any expected title."""
    for rank, hit in enumerate(hits, 1):
        if any(exp.lower() in hit["book"].lower() for exp in expected_books):
            return rank
    return None


def books_in_window(window: list[dict], expected_books: list[str]) -> list[str]:
    """Expected titles present anywhere in the agent's window."""
    found = []
    for expected in expected_books:
        if any(expected.lower() in hit["book"].lower() for hit in window):
            found.append(expected)
    return found


def main() -> None:
    golden = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    rows = []
    for item in golden["questions"]:
        expected = item["expected_books"]
        if not expected:
            continue  # refusal / judgment questions are not about retrieval
        cards = search("cards", item["question"], DIAG_K)
        transcripts = search("transcripts", item["question"], DIAG_K)
        # Identical to search_both(question, k=4): top-k of the same fused lists.
        window = cards[:WINDOW_PER_CORPUS] + transcripts[:WINDOW_PER_CORPUS]
        rows.append({
            "id": item["id"],
            "expected": expected,
            "found": books_in_window(window, expected),
            "cards_rank": best_rank(cards, expected),
            "transcripts_rank": best_rank(transcripts, expected),
        })

    print("| question | expected | in agent window | cards rank | transcripts rank |")
    print("|---|---|---|---|---|")
    for r in rows:
        status = f"{len(r['found'])}/{len(r['expected'])}"
        flag = "" if len(r["found"]) == len(r["expected"]) else " MISS"
        print(f"| {r['id']} | {len(r['expected'])} | {status}{flag} | "
              f"{r['cards_rank'] or '-'} | {r['transcripts_rank'] or '-'} |")

    single = [r for r in rows if len(r["expected"]) == 1]
    multi = [r for r in rows if len(r["expected"]) > 1]
    single_hits = sum(1 for r in single if r["found"])
    multi_full = sum(1 for r in multi if len(r["found"]) == len(r["expected"]))
    multi_cov = (sum(len(r["found"]) / len(r["expected"]) for r in multi) / len(multi)) if multi else None

    # This harness never calls an answering model, so LLM_BACKEND says nothing
    # about its numbers — the embedder does, and it produced both the query
    # vectors and the indexed ones. Named for the reason the agent eval names
    # its backend: a published number should not need its configuration
    # inferred by the reader.
    from ask_your_library.config import EMBED_BACKEND, OLLAMA_EMBED_MODEL, OPENROUTER_EMBED_MODEL
    embed_model = OLLAMA_EMBED_MODEL if EMBED_BACKEND == "ollama" else OPENROUTER_EMBED_MODEL
    print(f"\nEmbeddings: {embed_model} via {EMBED_BACKEND} (no answering model is called here)")
    print("\nRetriever-window metrics (raw question as query; window = top-4 cards + top-4 transcripts):")
    print(f"  single-book presence: {single_hits}/{len(single)}"
          + (f" = {single_hits / len(single):.0%}" if single else ""))
    if multi:
        print(f"  multi-book full coverage: {multi_full}/{len(multi)}; "
              f"mean coverage {multi_cov:.0%}")

    # Diagnostics only (per-corpus, depth 8, any-expected-book match).
    bests = [min(x for x in (r["cards_rank"], r["transcripts_rank"]) if x) if
             (r["cards_rank"] or r["transcripts_rank"]) else None for r in rows]
    parts = []
    for k in (2, 4, DIAG_K):
        parts.append(f"hit@{k}: {sum(1 for b in bests if b and b <= k)}/{len(rows)}")
    mrr = sum(1 / b for b in bests if b) / len(rows)
    print(f"Per-corpus diagnostics (not agent metrics): {'   '.join(parts)}   MRR(best-of-two): {mrr:.3f}")


if __name__ == "__main__":
    main()
