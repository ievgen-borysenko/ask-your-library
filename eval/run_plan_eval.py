"""Plan-only evaluation: the REAL planner node, replayed from a recording, for
nothing.

What it does. For every item of a golden set it builds the state the graph
would have built, replaces `llm.ask_json` with a replayer that hands back the
reply the model gave on a recorded paid run, and calls
`ask_your_library.nodes.plan()` — the real node: the real mode validation, the
real catalogue-request parsing, the real mixed-intent gate, the real query
filter, the real named-book resolution, the real two fallbacks — and then the
real `route_after_plan` over the state that comes out. No model is called and
nothing is billed, so a change to any of that is measured in seconds instead of
in dollars.

WHAT IT CANNOT MEASURE, said once and repeated in every report it writes: a
change to `PLAN_RULES`. The recorded reply answers the prompt that was in the
tree when it was recorded, and replaying it under a new prompt measures the
post-processing of an answer to a question nobody asked. The recording carries
the prompt's checksum; this harness refuses to run when it no longer matches
and only goes on under `--allow-stale`, which stamps every report it writes.
A prompt change needs a NEW recording, which needs a paid run.

  uv run eval/run_agent_eval.py --record-plans        # once, paid: make the recording
  uv run eval/run_plan_eval.py                        # then, free, as often as you like
  uv run eval/run_plan_eval.py --recording eval/recordings/<file>.jsonl [id ...]
      [--check] [--allow-missing] [--allow-stale] [--allow-drift] [--allow-unreplayed]
      [--min-pass N] [--no-json]

Scored per item and per recorded attempt (every row is deterministic, and the
mapping from a golden item to what the planner owes it is spelled out in
`PLAN_SCORES` below):

  mode_ok         the ROUTE the golden set actually pins — the catalogue path
                  for a `catalog` item, the research loop for every other type —
                  AND a planner that made that choice: a `plan_fallback` decided
                  nothing and is not a correct route
  op_ok           `catalog_request.op` is the item's `expected_op`
  book_filter_ok  the named book resolved to the item's `expected_book_filter`
  fallback_ok     `plan_fallback` is false: the planner produced a usable plan
  queries_ok      at least one non-blank query survived the filter
  queries_range   as many queries as PLAN_RULES asks for (2-4)
  mode_exact      DIAGNOSTIC, never part of the verdict: the planner's own
                  `identify` / `answer` reading against the item's type

Two files beside every run, the shape family of the main harness:
`eval/results/plan-replay-<ts>.md` and `plan-replay-<ts>.json`.
"""
import argparse
import contextlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import yaml

from ask_your_library import nodes
from ask_your_library.bookkey import TITLE_SEPARATOR, title_of
from ask_your_library.library import BookEntry
# the conditional edge graph.py wires after plan, called here over the state the
# node produced: a routing change is measured by this harness too
from ask_your_library.nodes import route_after_plan
from ask_your_library.runner import initial_state

REPO = Path(__file__).resolve().parents[1]


def load_by_path(name: str):
    """A sibling in eval/ as a module. These are scripts, not a package;
    eval/run_ablation.py loads the agent harness the same way, and so do the
    tests."""
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parent / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


harness = load_by_path("run_agent_eval")
plan_recording = load_by_path("plan_recording")

RESULTS_DIR = Path(os.environ.get("EVAL_RESULTS_DIR", Path(__file__).parent / "results"))

# PLAN_RULES asks for "2-4 ENGLISH search queries". The numbers are here and not
# read out of the prompt because a regex over prose is a second thing that can
# be wrong; what keeps them honest is the prompt checksum, which refuses a
# replay the moment those rules change at all.
QUERIES_MIN, QUERIES_MAX = 2, 4

# --- the mapping, stated once -------------------------------------------------
# A golden item says what the ANSWER must look like; the planner's decision is
# one step before that, so the mapping from one to the other is written here
# rather than inferred per item, and it is deliberately CONSERVATIVE: a row is
# part of the verdict only where the golden set really pins the planner, which
# is exactly where `score()` in eval/run_agent_eval.py already fails a run.
#
#   type: catalog        -> the catalogue path: mode "catalog" WITH a validated
#                           catalog_request (a "catalog" the parser rejected is
#                           not the catalogue path), and route_after_plan says
#                           "catalog". `expected_op` is checked when the item
#                           carries one. This is pinned: the item is scored on
#                           the structured catalogue result, which only exists
#                           on that path.
#   every other type     -> the research loop: NOT the catalogue path. Pinned
#                           just as hard, from the other side: the main harness
#                           fails any non-catalogue item whose run produced a
#                           catalogue result (`catalog_misroute`), whatever it
#                           listed.
#   expected_behavior:
#     research           -> the research loop AND reached by the planner's own
#                           reading: no `catalog_fallback`, because a rescue by
#                           code is the guard working, not the routing. This
#                           mirrors the `research` branch of `score()` exactly.
#     clarify,
#     clarify_or_answer  -> nothing extra. A clarify is `reflect`'s decision
#                           several steps later; `plan` cannot be graded on it,
#                           and pretending otherwise would fail c09 and q06 for
#                           something they never do here.
#
# What is NOT in the verdict, on purpose: whether the planner said "identify"
# or "answer". The golden `type` labels the QUESTION, and the two readings are
# a judgement the set never settled — an "identify" question whose book is
# obvious is legitimately answered, and the shipped loop treats the two the
# same after a clarify settles a book. It is reported as `mode_exact`, beside
# the verdict and never inside it, because a change that moves it is worth
# reading about.
MODE_BY_TYPE = {"identify": "identify", "answer": "answer", "aggregation": "answer",
                "refusal": "answer", "catalog": "catalog"}
# the rows that make up the per-attempt verdict, in report order
PLAN_SCORES = ("mode_ok", "op_ok", "book_filter_ok", "fallback_ok", "queries_ok", "queries_range")


# --- the catalogue plan() resolves names against ------------------------------
def catalogue_from_index() -> list:
    """What the index holds, through the shipped reader. None when there is no
    readable index — which is the normal case on a machine that only wants to
    replay."""
    try:
        from ask_your_library.library import list_books
        return list_books()
    except Exception:
        return None


def catalogue_from_manifest(path: Path = REPO / "corpus" / "manifest.yaml") -> list:
    """The documented fallback: the demo corpus manifest read as a catalogue.

    `plan()` resolves a named book against `library.list_books()`, which needs a
    built index. Without one the resolver would answer "no such book" to every
    name and `book_filter_ok` would be red across the set for a reason that has
    nothing to do with the planner. The manifest is the file the index is BUILT
    from — the same `Title — Author` keys, the same canary exclusion — so it
    stands in for a fully built demo index and the report says which of the two
    was used. It is not the same thing: a half-built index holds fewer books
    than its manifest, and a replay against the manifest would not notice."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = []
    for book in data.get("books") or []:
        if book.get("source") == "canary":      # library.list_books drops these too
            continue
        title, author = (book.get("title") or "").strip(), (book.get("author") or "").strip()
        if not title:
            continue
        key = f"{title}{TITLE_SEPARATOR}{author}" if author else title
        entries.append(BookEntry(key=key, title=title, author=author,
                                 has_cards=True, has_text=True))
    return sorted(entries, key=lambda e: e.title)


@contextlib.contextmanager
def catalogue(entries: list):
    """`plan()` reading `entries` instead of the index.

    The `list_books` NAME inside `ask_your_library.nodes`, which is how the node
    reaches it — the seam eval/run_ablation.py uses for `search_both`, and the
    reason nothing in src/ had to change for this harness either."""
    original = nodes.list_books
    nodes.list_books = lambda: list(entries)
    try:
        yield entries
    finally:
        nodes.list_books = original


# --- scoring ------------------------------------------------------------------
def queries_of(update: dict) -> list:
    """Every query the plan produced, in order: the one act would run next, and
    the queue behind it."""
    first = update.get("current_query") or ""
    return ([first] if first else []) + list(update.get("queries") or [])


def score_plan(item: dict, update: dict, route: str) -> dict:
    """The planner's decision against one golden item (a pure function of the
    two, like `score()` next door). See the mapping above for every rule."""
    request = update.get("catalog_request") or {}
    took_catalog = update.get("mode") == "catalog" and bool(request) and route == "catalog"
    kind = item["type"]
    out = {"mode": update.get("mode") or "", "route": route,
           "op": request.get("op", ""), "book_filter": update.get("book_filter") or "",
           "book_unresolved": update.get("book_unresolved") or "",
           "catalog_fallback": update.get("catalog_fallback") or "",
           "plan_fallback": bool(update.get("plan_fallback")),
           "mode_exact": update.get("mode") == MODE_BY_TYPE[kind]}
    if kind == "catalog":
        out["mode_ok"] = took_catalog
        if "expected_op" in item:
            out["op_ok"] = request.get("op") == item["expected_op"]
    else:
        out["mode_ok"] = not took_catalog
        if item.get("expected_behavior") == "research":
            # the research controls: routed there by the planner's own reading,
            # not rescued by the catalogue gate (the `research` branch of score())
            out["mode_ok"] = out["mode_ok"] and not update.get("catalog_fallback")
    out["fallback_ok"] = not out["plan_fallback"]
    # A fallback made NO routing decision: the planner produced nothing usable
    # and code searched the raw question. "not the catalogue path" is true of it
    # only because there was no path to take, and counting that as a correct
    # route would mark every failed planner green on the row that matters most.
    out["mode_ok"] = out["mode_ok"] and out["fallback_ok"]
    if not took_catalog:
        # A catalogue decision carries no queries by contract, so these two rows
        # do not exist for it — an absent row is not a failed one.
        queries = queries_of(update)
        out["queries"] = len(queries)
        out["queries_ok"] = bool(queries) and all(q.strip() for q in queries)
        out["queries_range"] = QUERIES_MIN <= len(queries) <= QUERIES_MAX
    if item.get("expected_book_filter"):
        out["book_filter_ok"] = (harness.fold(title_of(out["book_filter"]))
                                 == harness.fold(item["expected_book_filter"]))
    out["plan_ok"] = all(out[row] for row in PLAN_SCORES if row in out)
    return out


def replay_one(item: dict, replayer, attempt: int) -> dict:
    """One item, one recorded attempt: the real `plan()` over the recorded
    reply, then the real routing over what it produced."""
    started = time.time()
    state = initial_state(item["question"], history=[],
                          # plan() never opens it; the state field is required
                          scratchpad=Path(os.devnull))
    with replayer.item(item["id"], attempt):
        update = nodes.plan(state)
    route = route_after_plan({**state, **update})
    score = score_plan(item, update, route)
    # The request the node built this time against the one that was recorded:
    # a reply is replayed whatever it answers, so a change to how the payload is
    # assembled would otherwise be graded against a reply to the old payload.
    # Reported per item and never part of plan_ok — it says the REPLAY is
    # questionable, not that the planner decided wrongly — and it decides the
    # exit code unless --allow-drift.
    drift = replayer.drift.get((item["id"], attempt), [])
    score["payload_drift"] = list(drift)
    # How many planner calls this item recorded and how many were replayed. They
    # differ exactly when a clarify sent the run back through plan(): that
    # second decision is a function of graph state the observer never saw, so it
    # is accounted for and not invented. See PlanReplayer.
    account = replayer.accounting.get((item["id"], attempt), {"recorded": 0, "replayed": 0})
    score["calls_recorded"] = account["recorded"]
    score["calls_replayed"] = account["replayed"]
    return {"id": item["id"], "type": item["type"], "attempt": attempt,
            "question": item["question"],
            "queries": queries_of(update),
            "seconds": round(time.time() - started, 3),
            "score": score}


# --- the report ---------------------------------------------------------------
def render_row(record: dict) -> str:
    """One replayed attempt as the report's heading line."""
    s = record["score"]
    bits = [f"mode {s['mode'] or '-'} -> {s['route']}"]
    if s.get("op"):
        bits.append(f"op {s['op']}" + ("" if s.get("op_ok", True) else " NOT the expected op"))
    if "queries" in s:
        bits.append(f"queries {s['queries']}"
                    + ("" if s.get("queries_range", True) else f" OUTSIDE {QUERIES_MIN}-{QUERIES_MAX}"))
    if s["book_filter"]:
        bits.append(f"book filter {s['book_filter']}"
                    + ("" if s.get("book_filter_ok", True) else " NOT the expected book"))
    elif "book_filter_ok" in s:
        bits.append("book filter none NOT the expected book")
    if s["book_unresolved"]:
        bits.append(f"named book not in the catalogue: {s['book_unresolved']}")
    if s["catalog_fallback"]:
        bits.append(f"catalogue fallback ({s['catalog_fallback']})")
    if s["plan_fallback"]:
        bits.append("planner fallback (raw question searched)")
    if s.get("calls_recorded", 1) > s.get("calls_replayed", 1):
        bits.append(f"calls replayed {s['calls_replayed']}/{s['calls_recorded']} "
                    "(only the first planner call of an item is replayed)")
    for reason in s.get("payload_drift") or []:
        bits.append(f"PAYLOAD DRIFT: {reason}")
    if not s["mode_exact"]:
        bits.append(f"mode not the type's own reading ({MODE_BY_TYPE[record['type']]}) — diagnostic")
    return ("PASS" if s["plan_ok"] else "FAIL") + ": " + ", ".join(bits)


def render_report(out, facts: dict, recording, records: list, missing: list,
                  catalogue_source: str, stale: list) -> str:
    """The Markdown a reader reads. The header says where the numbers came from
    in the first two lines, because the one thing a reader must not have to
    work out is whether a model was involved."""
    out.write(f"# Plan-only replay — {time.strftime('%Y-%m-%d %H:%M')} — "
              f"{facts['golden_name']}\n\n")
    out.write(f"**Replayed from recording {recording.identity()}; NO MODEL WAS CALLED** "
              "— this measures the deterministic half of `plan()` (mode, catalogue request, "
              "query filter, named-book resolution, fallbacks, routing) and nothing else. "
              "It CANNOT measure a change to `PLAN_RULES`: the recorded replies answer the "
              "prompt of the tree they were recorded on, and a prompt change needs a new "
              "recording from a paid run. Only the FIRST planner call of each item is replayed: "
              "a second `plan()` happens after a clarify and is a function of graph state — the "
              "evidence collected, the candidates offered, the reply — that the recording does "
              "not hold, so replaying it would mean inventing that state. Recorded and replayed "
              "call counts are reported per item.\n\n")
    if recording.subset():
        out.write(f"> **{recording.subset()}.** The rows below are that subset, not the set.\n\n")
    if stale:
        out.write("> **STALE RECORDING, replayed anyway under `--allow-stale`. Nothing below "
                  "is a measurement of this tree:**\n"
                  + "".join(f"> - {reason}\n" for reason in stale) + "\n")
    out.write(f"run: {harness.render_fingerprint(facts)}\n\n")
    out.write(f"catalogue resolved against: {catalogue_source}\n")
    for record in records:
        out.write(f"\n## {record['id']} ({record['type']}, attempt {record['attempt']}) — "
                  f"{render_row(record)}\n\n")
        out.write(f"**Question:** {record['question']}\n\n")
        for query in record["queries"]:
            out.write(f"- query: {query}\n")
    for item_id in missing:
        out.write(f"\n## {item_id} — NOT IN THE RECORDING\n"
                  "nothing was replayed for this item; it counts in no row below.\n")
    return render_summary(out, records, missing)


def render_summary(out, records: list, missing: list) -> str:
    """The `\\n---\\n` tail: every row as a count over the attempts replayed.

    Counted, never averaged, for the reason the main harness gives: "the mode
    held in 9 of 10" is a statement a reader can act on and a mean of true and
    false is not."""
    total = len(records)
    lines = [f"\n---\n{total} attempts replayed from the recording, "
             f"{len(missing)} items not in it; no model was called, $0.0000 spent"]
    lines.append(f"- plan PASS {sum(r['score']['plan_ok'] for r in records)}/{total}")
    unreplayed = {r["id"]: (r["score"]["calls_replayed"], r["score"]["calls_recorded"])
                  for r in records if r["score"]["calls_replayed"] < r["score"]["calls_recorded"]}
    if unreplayed:
        lines.append("- **recorded planner calls not replayed on "
                     f"{len(unreplayed)} of {total} attempts** ("
                     + ", ".join(f"{i} {k}/{n}" for i, (k, n) in sorted(unreplayed.items()))
                     + "): only the first call of an item is replayed, because a re-plan after a "
                     "clarify depends on graph state the recording does not hold")
    drifted = [r["id"] for r in records if r["score"].get("payload_drift")]
    if drifted:
        lines.append(f"- **payload drift on {len(drifted)} of {total} attempts** "
                     f"({', '.join(sorted(set(drifted)))}): the request plan() builds now is not "
                     "the one that was recorded, so these replies answer a payload this tree no "
                     "longer sends. Not part of PASS, and not a number to publish.")
    for row in (*PLAN_SCORES, "mode_exact"):
        measured = [r for r in records if row in r["score"]]
        if measured:
            note = " (diagnostic, not part of PASS)" if row == "mode_exact" else ""
            lines.append(f"- {row} {sum(r['score'][row] for r in measured)}/{len(measured)}{note}")
    lines.append("- what this run did NOT measure: the planner's prompt, retrieval, the answer, "
                 "quote provenance, cost")
    summary = "\n".join(lines) + "\n"
    out.write(summary)
    return summary


def write_sidecar(path: Path, report_path: Path, facts: dict, recording, records: list,
                  missing: list, catalogue_source: str, stale: list, started: float,
                  ended: float) -> None:
    """The same run as data, in the sidecar's shape family: the schema and its
    version, the fingerprint as fields, the recording's own header as fields,
    and every replayed attempt with the score dict computed from it."""
    sidecar = {
        "schema": "ask-your-library/plan-replay-run", "schema_version": 1,
        "report": report_path.name,
        "model_called": False, "cost_usd": 0.0,
        "fingerprint": harness.render_fingerprint(facts),
        "run": facts,
        "recording": {"file": recording.path.name, "identity": recording.identity(),
                      **recording.header},
        "stale": stale,
        "catalogue_source": catalogue_source,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
        "ended": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ended)),
        "seconds": round(ended - started, 3),
        "replayed": len(records), "missing": list(missing),
        "payload_drift": {r["id"]: r["score"]["payload_drift"] for r in records
                          if r["score"].get("payload_drift")},
        "subset": recording.subset(),
        "calls": {r["id"]: {"recorded": r["score"]["calls_recorded"],
                            "replayed": r["score"]["calls_replayed"]} for r in records},
        "totals": {"plan_ok": sum(r["score"]["plan_ok"] for r in records),
                   "attempts": len(records),
                   **{row: {"ok": sum(r["score"][row] for r in records if row in r["score"]),
                            "of": sum(1 for r in records if row in r["score"])}
                      for row in (*PLAN_SCORES, "mode_exact")}},
        "attempts": records,
    }
    scratch = path.with_suffix(".json.tmp")
    scratch.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scratch.replace(path)


# --- the front end ------------------------------------------------------------
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay a recording of the planner's decisions through the real plan() node "
                    "and score them. No model is called and nothing is billed.")
    parser.add_argument("ids", nargs="*", metavar="id",
                        help="golden ids to replay; no ids at all = every question in the file")
    parser.add_argument("--recording", default=None, metavar="PATH",
                        help="the recording to replay (default: the one eval/recordings/ holds "
                             "for this golden file and the configured model)")
    parser.add_argument("--check", action="store_true",
                        help="verify the recording against this tree's golden file and PLAN_RULES "
                             "and exit, replaying nothing: exit 0 when a replay would measure "
                             "this tree, 2 when it would not")
    parser.add_argument("--allow-missing", action="store_true",
                        help="report items the recording does not hold instead of exiting 1")
    parser.add_argument("--allow-stale", action="store_true",
                        help="replay a recording whose golden or PLAN_RULES checksum no longer "
                             "matches. The report then opens with a block saying that nothing in "
                             "it measures this tree; there is no quiet way to do this")
    parser.add_argument("--allow-unreplayed", action="store_true",
                        help="report recorded planner calls that were not replayed instead of "
                             "exiting 1. Only the first call of an item is replayed; a clarify "
                             "item records two, and the second cannot be replayed from a "
                             "recording alone")
    parser.add_argument("--allow-drift", action="store_true",
                        help="report a payload drift instead of exiting 1. Drift means the request "
                             "plan() builds today is not the one the recorded reply answered, so "
                             "the replay is measuring a question that is no longer asked")
    parser.add_argument("--min-pass", type=int, default=None, metavar="N",
                        help="exit 1 when fewer than N replayed attempts pass")
    parser.add_argument("--json", action=argparse.BooleanOptionalAction, default=True,
                        help="write the JSON sidecar beside the report (default: on)")
    return parser.parse_intermixed_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    golden_file = harness.GOLDEN_PATH
    golden = yaml.safe_load(golden_file.read_text(encoding="utf-8"))
    harness.check_golden(golden["questions"])
    facts = harness.run_facts(1)

    path = (Path(args.recording) if args.recording
            else plan_recording.RECORDINGS_DIR / plan_recording.recording_name(
                facts["golden_name"], facts["golden_sha256_12"], facts["model"]))
    if not path.exists():
        print(f"no recording at {harness.redact_paths(str(path))}\n"
              "make one with: uv run eval/run_agent_eval.py --record-plans", file=sys.stderr)
        sys.exit(2)
    try:
        recording = plan_recording.load_recording(path)
    except plan_recording.StaleRecording as error:
        print(f"unusable recording: {harness.redact_paths(f'{error}')}", file=sys.stderr)
        sys.exit(2)

    stale = recording.stale_against(facts["golden_sha256_12"])
    if args.check:
        # The separate mode: answer the one question a replayed number depends
        # on — would this recording measure THIS tree — and replay nothing.
        print(f"recording {recording.identity()}\n"
              + ("measures this tree: golden and PLAN_RULES checksums both match"
                 if not stale else "does NOT measure this tree:\n  " + "\n  ".join(stale)))
        sys.exit(2 if stale else 0)
    if stale and not args.allow_stale:
        print("refusing to replay: this recording does not describe this tree\n  "
              + "\n  ".join(stale)
              + "\n--allow-stale replays it anyway and stamps the report; a prompt change needs "
                "a new recording (uv run eval/run_agent_eval.py --record-plans)", file=sys.stderr)
        sys.exit(2)

    known = {q["id"] for q in golden["questions"]}
    unknown = [i for i in args.ids if i not in known]
    if unknown:
        print(f"unknown golden ids: {unknown}", file=sys.stderr)
        sys.exit(2)
    items = [q for q in golden["questions"] if not args.ids or q["id"] in args.ids]

    entries = catalogue_from_index()
    if not entries:
        # None (no readable index) and an index that lists nothing are the same
        # thing to a resolver, and both are the normal case on a machine that
        # only wants to replay
        entries = catalogue_from_manifest()
        source = (f"corpus/manifest.yaml, {len(entries)} books — the documented fallback: this "
                  "machine has no readable index, so a fully built demo index is stood in for")
    else:
        source = f"the index, {len(entries)} books"

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    out_path = RESULTS_DIR / f"plan-replay-{stamp}.md"
    json_path = RESULTS_DIR / f"plan-replay-{stamp}.json"

    replayer = plan_recording.PlanReplayer(recording, redact=harness.redact_paths)
    records, missing = [], []
    started = time.time()
    with catalogue(entries), plan_recording.replaying(replayer):
        for item in items:
            attempts = sorted(attempt for (item_id, attempt) in recording.calls
                              if item_id == item["id"])
            if not attempts:
                missing.append(item["id"])
                print(f"=== {item['id']} — not in the recording", flush=True)
                continue
            for attempt in attempts:
                record = replay_one(item, replayer, attempt)
                records.append(record)
                print(f"=== {item['id']} (attempt {attempt}) — {render_row(record)}", flush=True)
    ended = time.time()

    with open(out_path, "w", encoding="utf-8") as out:
        summary = render_report(out, facts, recording, records, missing, source, stale)
    if args.json:
        write_sidecar(json_path, out_path, facts, recording, records, missing, source, stale,
                      started, ended)
    print(summary)
    print(f"replayed from: {recording.identity()}")
    print(f"Report: {out_path}")
    if args.json:
        print(f"Sidecar: {json_path}")
    passed = sum(r["score"]["plan_ok"] for r in records)
    drifted = sorted({r["id"] for r in records if r["score"].get("payload_drift")})
    unreplayed = sorted({r["id"] for r in records
                         if r["score"]["calls_replayed"] < r["score"]["calls_recorded"]})
    unmet = missing and not args.allow_missing
    undrifted = drifted and not args.allow_drift
    unplayed = unreplayed and not args.allow_unreplayed
    if unmet:
        print(f"items the recording does not hold: {missing} (--allow-missing accepts this)",
              file=sys.stderr)
    if undrifted:
        print(f"payload drift on {drifted}: the request plan() builds now is not the one the "
              "recorded reply answered, so this replay does not measure what it looks like it "
              "measures (--allow-drift accepts this; a new recording removes it)", file=sys.stderr)
    if unplayed:
        print(f"recorded planner calls not replayed on {unreplayed}: only the first call of an "
              "item is replayed, and these items recorded more (a clarify re-plans). The extra "
              "calls are NOT measured by this report (--allow-unreplayed accepts this)",
              file=sys.stderr)
    if unmet or undrifted or unplayed or (args.min_pass is not None and passed < args.min_pass):
        sys.exit(1)


if __name__ == "__main__":
    main()
