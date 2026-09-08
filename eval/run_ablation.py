"""Ablation on the core golden set (ADR-014): where does the quality come from?

Five conditions, the same twelve core questions, one run each:

  no-context        the orchestrator model answers from its own memory: the
                    question only, through the same llm_invoke path, with a
                    system rule that says "answer from what you know, say when
                    you are unsure". No retrieval, no library, no provenance.
  retrieve-answer   one search_both(question, k=4) call; the hits, sanitized
                    through sanitize_context and cut to SEARCH_HIT_CHARS
                    exactly as observe would see them, go straight into a
                    single synthesize-style prompt. No plan/observe/reflect
                    loop, no clarify, no validate (see PROVENANCE_NOTE).
  cards-only        the full agent loop with search_both restricted to the
                    cards corpus. The restriction is a monkeypatch of the
                    `search_both` NAME inside ask_your_library.nodes (nodes.py
                    imports it by name); nodes.py itself is never modified.
  transcripts-only  the same, restricted to the transcripts corpus.
  agent             the full loop as shipped — identical to eval/run_agent_eval.py.

Behaviour scoring (`score`), the per-question run (`run_one`) and the run
fingerprint (`run_fingerprint`) are imported from eval/run_agent_eval.py; that
harness is reused, never changed, and its own report format is untouched.

  uv run eval/run_ablation.py
  uv run eval/run_ablation.py --conditions no-context,retrieve-answer --ids c02-huck-go-to-hell

Writes the full answers of every condition to
eval/results/ablation-<ts>-<condition>.md (gitignored, like every other eval
run), the per-question scratchpads of every condition to
eval/results/<condition>/scratch-<id>.md (the harness writes them under its own
RESULTS_DIR, which is repointed per condition so the conditions do not overwrite
each other's windows) and ONE markdown artifact to
docs/eval-results/<date>-ablation-core.md.
The artifact is only written for a full 5 x 12 run unless --force-artifact:
a partial run must not look like the published ablation.

The "AI pre-check" cells are written as `pending`. They are the reading of
every answer against the golden notes by the session that ran the ablation,
filled in by hand afterwards and labelled in the artifact as an AI pre-check,
not a human verdict.
"""
import argparse
import importlib.util
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import yaml

from ask_your_library import llm as llm_mod
from ask_your_library import nodes as nodes_mod
from ask_your_library.prompts import SYNTHESIZE_RULES
from ask_your_library.i18n import t
from ask_your_library.library import search as corpus_search
from ask_your_library.library import search_both as library_search_both
from ask_your_library.sanitize import sanitize_context

REPO = Path(__file__).resolve().parents[1]


def load_harness():
    """The agent-eval harness as an importable module (it is a script, so it is
    loaded by path — the same way tests/test_agent_eval_scoring.py loads it)."""
    spec = importlib.util.spec_from_file_location(
        "run_agent_eval", Path(__file__).resolve().parent / "run_agent_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load_harness()

# condition -> corpus the agent loop is restricted to (None = no restriction)
AGENT_CONDITIONS = {"cards-only": "cards", "transcripts-only": "transcripts", "agent": None}
CONDITIONS = ("no-context", "retrieve-answer", "cards-only", "transcripts-only", "agent")

SEARCH_K = 4   # what search_both gives the agent per corpus

NO_CONTEXT_RULES = (
    "Answer the user's question from what you already know. There is no library, "
    "no search results and no evidence available: rely only on your own knowledge. "
    "Say plainly when you are unsure or do not know something, and never invent a "
    "source. Plain text and markdown only — NO emoji."
)

PROVENANCE_NOTE = (
    "`no-context` has no retrieval at all. `retrieve-answer` has no distilled quotes: "
    "its \"evidence\" is the raw retrieved passage, so running `validate` over it would "
    "compare each passage against itself and confirm 100% by construction. Provenance is "
    "therefore reported as n/a for both, not as a score."
)


# ---------------------------------------------------------------- conditions
@contextmanager
def corpus_restriction(corpus: str | None):
    """Restrict the agent's retrieval to ONE corpus by rebinding the
    `search_both` name inside ask_your_library.nodes (nodes.py imports the
    function by name at import time). k stays 4, so the condition removes a
    corpus from the window rather than substituting it: the window is 4 hits
    per step instead of 8."""
    if corpus is None:
        yield
        return
    original = nodes_mod.search_both

    def restricted(query: str, k: int = SEARCH_K, book: str | None = None) -> list[dict]:
        # act passes `book` on every search since ADR-013 (None outside a
        # resolved clarify or a coverage probe); the restriction must accept
        # and forward it, or every act() call in this condition raises.
        return corpus_search(corpus, query, k, book=book)

    nodes_mod.search_both = restricted
    try:
        yield
    finally:
        nodes_mod.search_both = original


@contextmanager
def condition_results_dir(base: Path, condition: str):
    """Point the harness at a per-condition results directory while one
    condition runs. `harness.run_one` writes its scratchpad to
    `RESULTS_DIR/scratch-<id>.md`, and every condition runs the same ids one
    after another: on a shared directory each condition overwrites the previous
    one's scratchpads and only the last condition's windows survive the run."""
    original = harness.RESULTS_DIR
    target = base / condition
    target.mkdir(parents=True, exist_ok=True)
    harness.RESULTS_DIR = target
    try:
        yield target
    finally:
        harness.RESULTS_DIR = original


def _blank_result(item: dict) -> dict:
    """The fields harness.score() and the report reader expect, with the loop's
    own observables set to their "did not happen" values."""
    return {"id": item["id"], "type": item["type"], "question": item["question"],
            "answer": "", "verification": "n/a", "provenance": {},
            "steps_taken": 0, "read_chapters": [], "evidence_items": 0,
            "clarify_asked": False, "clarify_candidates": [], "clarify_unresolved": False,
            "clarify_chosen": "", "seconds": 0, "steps_log": []}


def run_no_context(item: dict) -> dict:
    """Condition 1: the same orchestrator model, the same llm_invoke path, the
    question and nothing else."""
    started = time.time()
    user = llm_mod.data_block("question", item["question"])
    system = f"{NO_CONTEXT_RULES} {t('answer_lang_instruction')}"
    answer = llm_mod.llm_invoke(system, user, role="no_context").content
    result = _blank_result(item)
    result.update({"answer": answer, "seconds": round(time.time() - started),
                   "verification": "n/a — no retrieval, nothing to attribute",
                   "steps_log": ["no-context: one llm_invoke, no search"]})
    return result


def retrieved_passages(question: str, k: int = SEARCH_K) -> tuple[list[dict], int]:
    """One search_both call, then exactly what act/observe do to the text:
    sanitize_context first, then cut to the per-hit budget, with a stable hit
    id per passage. Returns (passages, redacted line count)."""
    hits = library_search_both(question, k=k)
    limit = nodes_mod.per_hit_limit(len(hits))
    passages, redacted = [], 0
    for i, h in enumerate(hits, 1):
        clean, n = sanitize_context(h["text"])
        redacted += n
        passages.append({"hit_id": f"s1h{i}", "corpus": h["corpus"], "book": h["book"],
                         "section": h["section"], "text": clean[:limit]})
    return passages, redacted


def run_retrieve_answer(item: dict) -> dict:
    """Condition 2: retrieve once, answer once. No loop, no distillation."""
    started = time.time()
    passages, redacted = retrieved_passages(item["question"])
    result = _blank_result(item)
    if not passages:
        answer = t("refusal_answer")
    else:
        evidence_text = "\n".join(f"- {p['book']} — {p['section']}: \"{p['text']}\""
                                  for p in passages)
        data = [llm_mod.data_block("question", item["question"]),
                llm_mod.data_block("evidence", evidence_text)]
        answer = llm_mod.llm_invoke(
            SYNTHESIZE_RULES.format(lang=t("answer_lang_instruction")),
            "\n".join(data), role="synthesize").content
    result.update({"answer": answer, "seconds": round(time.time() - started),
                   "steps_taken": 1, "evidence_items": len(passages),
                   "verification": "n/a — raw passages, no distilled quotes to check",
                   "steps_log": [f"retrieve-answer: {len(passages)} passages "
                                 f"({redacted} redacted lines), one synthesize call"]})
    return result


def run_item(condition: str, item: dict, graph) -> dict:
    """One question under one condition, with per-question usage accounting.

    The agent conditions go through `harness.run_one`, which resets the usage
    accumulator itself and attaches `cost_usd` / `llm_calls` / `tokens_in` /
    `tokens_out` (and the score) to the record — it is not reset again here, or
    the reset would land in the middle of nothing and the question's own spend
    would be read twice. The two loop-free conditions do not go through
    `run_one`, so they reset here and read the same fields through the same
    `harness.usage_fields()` helper."""
    if condition in AGENT_CONDITIONS:
        with corpus_restriction(AGENT_CONDITIONS[condition]):
            result = harness.run_one(graph, item)
    else:
        llm_mod.reset_usage()
        result = run_no_context(item) if condition == "no-context" else run_retrieve_answer(item)
        result.update(harness.usage_fields())
    if "score" not in result:
        result["score"] = harness.score(item, result)
    return result


# ---------------------------------------------------------------- aggregation
def empty_totals() -> dict:
    return {"run": 0, "errors": 0, "clarify": 0, "behavior_ok": 0, "behavior_ok_no_clarify": 0,
            "no_clarify_items": 0, "titles_mentioned": 0, "titles_expected": 0,
            "checked": 0, "confirmed": 0, "unattributed": 0, "broken": 0,
            "llm_calls": 0, "tokens_in": 0, "tokens_out": 0,
            "cost_usd": 0.0, "seconds": 0}


def accumulate(totals: dict, item: dict, r: dict) -> None:
    """One completed question into the condition's totals. The usage fields are
    the flat ones `harness.usage_fields()` produces."""
    sc = r["score"]
    prov = r.get("provenance") or {}
    totals["run"] += 1
    totals["clarify"] += int(r.get("clarify_asked", False))
    totals["behavior_ok"] += int(sc["behavior_ok"])
    if item.get("expected_behavior") != "clarify":
        totals["no_clarify_items"] += 1
        totals["behavior_ok_no_clarify"] += int(sc["behavior_ok"])
    totals["titles_mentioned"] += sc["titles_mentioned"]
    totals["titles_expected"] += sc["titles_expected"]
    for key in ("checked", "confirmed", "unattributed", "broken"):
        totals[key] += prov.get(key, 0)
    for key in ("llm_calls", "tokens_in", "tokens_out"):
        totals[key] += r.get(key, 0)
    totals["cost_usd"] = round(totals["cost_usd"] + r.get("cost_usd", 0.0), 4)
    totals["seconds"] += r.get("seconds", 0)


def add_spend(totals: dict, spent: dict) -> None:
    """The calls a failed question already made were billed all the same
    (`eval/run_agent_eval.py` counts them the same way): they belong in the
    condition's cost, and the mean is per ATTEMPTED question."""
    for key in ("llm_calls", "tokens_in", "tokens_out"):
        totals[key] += spent.get(key, 0)
    totals["cost_usd"] = round(totals["cost_usd"] + spent.get("cost_usd", 0.0), 4)


# ---------------------------------------------------------------- reports
def write_condition_report(path: Path, condition: str, fingerprint: str,
                           records: list[dict], totals: dict) -> None:
    """Full answers of one condition — the file a reader checks the artifact
    against. Not committed (eval/results/ is gitignored)."""
    with open(path, "w", encoding="utf-8") as out:
        out.write(f"# Ablation — {condition} — {time.strftime('%Y-%m-%d %H:%M')}\n\n"
                  f"run: {fingerprint}\n"
                  f"condition: {condition}\n\n")
        for r in records:
            if r.get("error"):
                out.write(f"\n## {r['id']} — ERROR\n{r['error']}\n"
                          f"(spent before the error: ${r.get('cost_usd', 0):.4f}, "
                          f"{r.get('llm_calls', 0)} calls)\n")
                continue
            sc = r["score"]
            verdict = "PASS" if sc["behavior_ok"] else "FAIL"
            out.write(f"\n## {r['id']} ({r['type']}, {r['steps_taken']} steps, {r['seconds']}s, "
                      f"${r.get('cost_usd', 0):.4f}, {r.get('llm_calls', 0)} calls, "
                      f"{r.get('tokens_in', 0)} in / {r.get('tokens_out', 0)} out tokens"
                      f"{', clarify' if r['clarify_asked'] else ''}) — {verdict}: "
                      f"titles {sc['titles_mentioned']}/{sc['titles_expected']}\n\n"
                      f"- [ ] AI pre-check (facts against the golden notes): "
                      f"correct / incorrect / incomplete\n\n"
                      f"**Question:** {r['question']}\n\n")
            for line in r.get("steps_log") or []:
                out.write(f"- {line}\n")
            if r.get("read_chapters"):
                out.write(f"- chapters read: {', '.join(r['read_chapters'])}\n")
            out.write(f"\n{r['answer']}\n\n"
                      f"> quote provenance: {r.get('verification', 'n/a')}\n")
        attempted = totals["run"] + totals["errors"]
        out.write(f"\n---\n{totals['run']} completed, {totals['errors']} errors; "
                  f"behaviour PASS {totals['behavior_ok']}/{totals['run']}; "
                  f"titles {totals['titles_mentioned']}/{totals['titles_expected']}; "
                  f"provenance {totals['confirmed']}/{totals['unattributed']}/{totals['broken']} "
                  f"of {totals['checked']} checked; ${totals['cost_usd']:.4f} total, "
                  f"${totals['cost_usd'] / max(attempted, 1):.4f} mean per attempted question; "
                  f"{totals['llm_calls']} llm calls, {totals['tokens_in']} in / "
                  f"{totals['tokens_out']} out tokens, {totals['seconds']}s\n")


CONDITION_BLURB = {
    "no-context": "the orchestrator model answers from memory: the question only, same "
                  "`llm_invoke` path, a system rule to answer from what it knows and say "
                  "when it is unsure. No retrieval.",
    "retrieve-answer": "one `search_both(question, k=4)` call; the 8 hits, sanitized and cut "
                       "to `SEARCH_HIT_CHARS` (1,200) as observe would see them, go straight "
                       "into one synthesize-style prompt. No plan/observe/reflect, no clarify, "
                       "no validate.",
    "cards-only": "the full agent loop, `search_both` restricted to the cards corpus "
                  "(4 hits per step instead of 8).",
    "transcripts-only": "the full agent loop, `search_both` restricted to the transcripts "
                        "corpus (4 hits per step instead of 8).",
    "agent": "the full loop as shipped — identical to `eval/run_agent_eval.py`.",
}


def fmt_provenance(condition: str, totals: dict) -> str:
    if condition in ("no-context", "retrieve-answer"):
        return "n/a"
    return (f"{totals['confirmed']} / {totals['unattributed']} / {totals['broken']} "
            f"of {totals['checked']}")


def render_artifact(fingerprint: str, order: list[str], results: dict,
                    items: list[dict], report_names: dict) -> str:
    """The committed comparison table. Numbers only; the AI pre-check cells and
    the reading paragraph are filled in by the session afterwards."""
    clarify_ids = [i["id"] for i in items if i.get("expected_behavior") == "clarify"]
    lines = [
        "# Ablation on the core set (ADR-014)",
        "",
        f"- run: `{fingerprint}`",
        f"- questions: {len(items)} core golden questions "
        f"(`{harness.GOLDEN_PATH.name}`), one run per condition, "
        f"{len(order)} condition{'s' if len(order) != 1 else ''}",
        "- full answers per condition: "
        + ", ".join(f"`eval/results/{name}`" for name in
                    (report_names[c] for c in order))
        + " (not committed)",
        "",
        "## What each condition is",
        "",
    ]
    for condition in order:
        lines.append(f"- **`{condition}`** — {CONDITION_BLURB[condition]}")
    lines += [
        "",
        "Behaviour scoring, the per-question run and the fingerprint come from "
        "`eval/run_agent_eval.py`, imported unchanged. Cost, calls and tokens are the same "
        "per-question accounting that harness uses — the accumulator is reset at the start of "
        "every question and read back with `usage_fields()` — so the numbers here and there "
        "are the same measurement. The mean is per ATTEMPTED question: a question that errored "
        "still spent what it spent before failing.",
        "",
        "## Comparison",
        "",
        "| condition | behaviour PASS | expected titles | provenance conf/unatt/broken | "
        "AI pre-check corr/incorr/incompl | llm calls | total cost | mean cost/question | seconds |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for condition in order:
        totals = results[condition]["totals"]
        n = max(totals["run"] + totals["errors"], 1)
        lines.append(
            f"| `{condition}` | {totals['behavior_ok']}/{totals['run']} | "
            f"{totals['titles_mentioned']}/{totals['titles_expected']} | "
            f"{fmt_provenance(condition, totals)} | pending | {totals['llm_calls']} | "
            f"${totals['cost_usd']:.4f} | ${totals['cost_usd'] / n:.4f} | {totals['seconds']} |")
    lines += ["", "Errors (question did not complete): "
              + ", ".join(f"`{c}` {results[c]['totals']['errors']}" for c in order) + ".", ""]
    if clarify_ids:
        no_loop = [c for c in order if c in ("no-context", "retrieve-answer")]
        if no_loop:
            lines += [
                f"Clarify caveat: {', '.join('`' + i + '`' for i in clarify_ids)} in the golden "
                f"set requires a clarify interrupt, which {' and '.join('`' + c + '`' for c in no_loop)} "
                "cannot produce by construction — those conditions fail it whatever they answer. "
                "Behaviour PASS on the remaining questions only: "
                + ", ".join(f"`{c}` {results[c]['totals']['behavior_ok_no_clarify']}/"
                            f"{results[c]['totals']['no_clarify_items']}" for c in order) + ".",
                "",
            ]
    lines += [PROVENANCE_NOTE, "",
              "## AI pre-check, per question",
              "",
              "**This is an AI pre-check by the session that produced this artifact, not a human "
              "verdict.** Each cell is that session's reading of the answer in "
              "`eval/results/ablation-*.md` against the golden notes: `correct`, `incorrect` or "
              "`incomplete`. A reader's verdict, when it exists, overrides it: the last column "
              "is an unticked box per question, ticked by the reader who has checked that row.",
              ""]
    header = "| id | " + " | ".join(f"`{c}`" for c in order) + " | reader's verdict |"
    lines += [header, "|" + "---|" * (len(order) + 2)]
    for item in items:
        lines.append(f"| {item['id'].split('-')[0]} | "
                     + " | ".join("pending" for _ in order) + " | [ ] |")
    lines += [
        "",
        "## Reading",
        "",
        "_To be written by the session after reading every answer: what the numbers show, "
        "including the case where a cheaper condition matches or beats the full loop._",
        "",
        "## Limits of this table",
        "",
        "- One run per condition per question, hosted model, temperature 0 but output still "
        "varies between runs; a difference of one or two questions is not a measured effect.",
        "- Behaviour PASS is the heuristic scorer (titles mentioned, refusal marker, clarify, "
        "drill-down), not correctness. The AI pre-check column is a reading, not a judge.",
        "- `cards-only` and `transcripts-only` restrict `search_both` only. A chapter "
        "drill-down (`get_chapter`) still reads the transcripts table, so a `cards-only` run "
        "that drills into a chapter is not corpus-pure; the per-condition report lists the "
        "chapter reads.",
        "- Cost is the orchestrator's own token cost at the configured prices; embeddings run "
        "locally and are not priced here.",
        "",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- main
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADR-014 ablation on the core golden set")
    parser.add_argument("--conditions", default=",".join(CONDITIONS),
                        help="comma-separated subset of: " + ", ".join(CONDITIONS))
    parser.add_argument("--ids", nargs="*", default=[], help="golden ids (default: all)")
    parser.add_argument("--force-artifact", action="store_true",
                        help="write the docs/ artifact even for a partial run")
    parser.add_argument("--no-artifact", action="store_true",
                        help="skip the docs/ artifact entirely (smoke runs)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    order = [c.strip() for c in args.conditions.split(",") if c.strip()]
    unknown_conditions = [c for c in order if c not in CONDITIONS]
    if unknown_conditions:
        print(f"unknown conditions: {unknown_conditions}", file=sys.stderr)
        sys.exit(2)

    golden = yaml.safe_load(harness.GOLDEN_PATH.read_text(encoding="utf-8"))
    known = {q["id"] for q in golden["questions"]}
    unknown_ids = [i for i in args.ids if i not in known]
    if unknown_ids:
        print(f"unknown golden ids: {unknown_ids}", file=sys.stderr)
        sys.exit(2)
    items = [q for q in golden["questions"] if not args.ids or q["id"] in args.ids]

    results_dir = harness.RESULTS_DIR
    results_dir.mkdir(parents=True, exist_ok=True)
    fingerprint = harness.run_fingerprint()
    stamp = int(time.time())

    results, report_names = {}, {}
    for condition in order:
        print(f"=== condition {condition} ({len(items)} questions)", flush=True)
        graph = None
        if condition in AGENT_CONDITIONS:
            from ask_your_library.graph import build_graph
            graph = build_graph()
        records, totals = [], empty_totals()
        with condition_results_dir(results_dir, condition) as scratch_dir:
            for item in items:
                print(f"  --- {item['id']} ...", flush=True)
                try:
                    r = run_item(condition, item, graph)
                except Exception as error:   # one failed question must not lose the run
                    totals["errors"] += 1
                    spent = harness.usage_fields()
                    add_spend(totals, spent)
                    records.append({"id": item["id"], "error": f"{type(error).__name__}: {error}",
                                    **spent})
                    print(f"      ERROR: {type(error).__name__}: {error} "
                          f"(spent ${spent['cost_usd']:.4f})", flush=True)
                    continue
                records.append(r)
                accumulate(totals, item, r)
                print(f"      {'PASS' if r['score']['behavior_ok'] else 'FAIL'}, "
                      f"{r['seconds']}s, ${r.get('cost_usd', 0):.4f}", flush=True)
        report_names[condition] = f"ablation-{stamp}-{condition}.md"
        write_condition_report(results_dir / report_names[condition], condition,
                               fingerprint, records, totals)
        results[condition] = {"records": records, "totals": totals}
        print(f"    -> {results_dir / report_names[condition]}\n"
              f"       scratchpads: {scratch_dir}", flush=True)

    print("\n=== summary")
    for condition in order:
        totals = results[condition]["totals"]
        n = max(totals["run"] + totals["errors"], 1)
        print(f"{condition:<18} PASS {totals['behavior_ok']}/{totals['run']}, "
              f"titles {totals['titles_mentioned']}/{totals['titles_expected']}, "
              f"provenance {fmt_provenance(condition, totals)}, "
              f"${totals['cost_usd']:.4f} total / ${totals['cost_usd'] / n:.4f} per question, "
              f"{totals['seconds']}s, {totals['errors']} errors")
    print(f"run: {fingerprint}")

    full_run = len(order) == len(CONDITIONS) and len(items) == len(golden["questions"])
    if args.no_artifact or not (full_run or args.force_artifact):
        print("\nno docs/ artifact written "
              f"({'--no-artifact' if args.no_artifact else 'partial run; use --force-artifact'})")
        return
    artifact = REPO / "docs" / "eval-results" / f"{time.strftime('%Y-%m-%d')}-ablation-core.md"
    artifact.write_text(render_artifact(fingerprint, order, results, items, report_names),
                        encoding="utf-8")
    print(f"\nArtifact: {artifact}\n"
          "Fill the AI pre-check cells and the Reading section after reading every answer.")


if __name__ == "__main__":
    main()
