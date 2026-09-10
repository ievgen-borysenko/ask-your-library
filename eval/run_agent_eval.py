"""Agent eval: run golden questions through the FULL agentic loop and score
the observable behaviour against the golden set.

Clarify interrupts are answered automatically, so the run is non-interactive.
Scored per question (no LLM judge; heuristics, not proof):
  titles_mentioned  every expected book title occurs in the answer text (type catalog:
                    the expected KEYS "Title — Author" the code listed; strict set equality
                    against them, and the catalogue's own total, are the verdict)
                    (accent-folded substring) - NOT a citation check
  behavior  refusal -> the answer carries an explicit refusal marker
            ("not in the library", "cannot answer", "не знаю", ...) AND ends
            there, at most REFUSAL_TAIL_WORDS words after it; an answer
            without evidence that still tells a story from model knowledge FAILS,
            and so does one that declines and then narrates anyway;
            expected_behavior "clarify" -> a clarify interrupt happened;
            "clarify_or_answer" -> clarify OR all titles mentioned;
            otherwise -> all titles mentioned
  drilldown when the golden item sets expects_chapter_read, a full chapter of
            an expected book was read; part of the behaviour verdict
Answer CORRECTNESS is not scored: a verbatim quote of a character's false claim
passes provenance and titles and can still be wrong, and a green run can be
incomplete when the answering passage was never retrieved (see the c06 trace in
docs/examples). The report leaves a manual-correctness checkbox per question.

  uv run eval/run_agent_eval.py [id ...]     # no ids = every question
  GOLDEN_PATH=... LIBRARY_DB_PATH=... uv run eval/run_agent_eval.py [ids...]
      [--min-pass N] [--clarify-pick second] [--require-clean]
"""
import hashlib
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import yaml
from langgraph.types import Command

from ask_your_library.graph import build_graph
from ask_your_library.library import title_of
from ask_your_library.i18n import t
from ask_your_library.config import (CHAPTER_HIT_CHARS, MAX_CLARIFY_CANDIDATES, MAX_EMPTY_STREAK, MAX_STEPS,
                                     PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK, QUESTION_DEADLINE_S, SEARCH_HIT_CHARS)
from ask_your_library.llm import reset_usage, usage_snapshot
from ask_your_library.provenance import HIT_ID_STRICT
from ask_your_library.runner import initial_state

GOLDEN_PATH = Path(os.environ.get("GOLDEN_PATH", Path(__file__).parent / "golden" / "en-demo.yaml"))


def git_code_stamp() -> str:
    """Three states, never conflated: '<short sha>' = verified clean (HEAD
    resolved, no modified tracked files, no un-ignored untracked files);
    '<short sha>+dirty(<12 hex>)' = the tree differs from HEAD, the hash covers
    the tracked diff AND the contents of un-ignored untracked files (a new
    module the app already imports is a difference); 'unknown' = git failed
    or is absent. --require-clean accepts only the first."""
    cwd = Path(__file__).parent

    def git(*args: str):
        proc = subprocess.run(["git", *args], capture_output=True, text=True, cwd=cwd)
        if proc.returncode != 0:
            raise RuntimeError(f"git {args[0]} failed: {proc.stderr.strip()[:80]}")
        return proc.stdout

    try:
        sha = git("rev-parse", "--short", "HEAD").strip()
        if not sha:
            return "unknown"
        status = git("status", "--porcelain")          # untracked, un-ignored files included
        if not status.strip():
            return sha
        h = hashlib.sha256(git("diff", "HEAD").encode())
        root = Path(git("rev-parse", "--show-toplevel").strip())
        for line in status.splitlines():
            if line.startswith("??"):
                path = root / line[3:].strip()
                h.update(line.encode())
                if path.is_file():
                    h.update(path.read_bytes())
        return f"{sha}+dirty({h.hexdigest()[:12]})"
    except (OSError, RuntimeError):
        return "unknown"


def run_fingerprint() -> str:
    """What exactly produced this report: code SHA, golden checksum, model,
    index stamps — a number without these is not attributable."""
    sha = git_code_stamp()
    golden_sha = hashlib.sha256(GOLDEN_PATH.read_bytes()).hexdigest()[:12]
    repo = Path(__file__).resolve().parents[1]

    def digest_of(paths) -> str:
        h = hashlib.sha256()
        for p in sorted(paths):
            h.update(p.name.encode()); h.update(p.read_bytes())
        return h.hexdigest()[:12]

    manifest = repo / "corpus" / "manifest.yaml"
    corpus_sha = digest_of([manifest]) if manifest.exists() else "?"
    toc_sha = digest_of((repo / "corpus" / "toc").glob("*.json")) if (repo / "corpus" / "toc").exists() else "?"
    from ask_your_library.config import DB_PATH, ORCHESTRATOR_MODEL, TABLES
    stamps = []
    try:
        import lancedb
        from ask_your_library.index_meta import read_index_meta
        db = lancedb.connect(DB_PATH)
        for name in TABLES.values():
            meta = read_index_meta(db, name) or {}
            table = db.open_table(name)
            stamps.append(f"{name}={meta.get('model', '?')}/{meta.get('dims', '?')}d "
                          f"rows={table.count_rows()} v{getattr(table, 'version', '?')} "
                          f"built={meta.get('created', '?')}")
    except Exception as error:  # the report must not fail on fingerprinting
        stamps.append(f"index=unavailable ({type(error).__name__})")
    return (f"code {sha} | golden {GOLDEN_PATH.name}@{golden_sha} | manifest@{corpus_sha} | "
            f"toc@{toc_sha} | model {ORCHESTRATOR_MODEL} | {' | '.join(stamps)} | "
            f"strict_hit_id={'on' if HIT_ID_STRICT else 'off'} | clarify_pick={CLARIFY_PICK or 'default'} | "
            f"hit_chars={SEARCH_HIT_CHARS}/{CHAPTER_HIT_CHARS} | steps={MAX_STEPS}/{MAX_EMPTY_STREAK} | "
            f"candidates={MAX_CLARIFY_CANDIDATES} | "
            f"deadline={QUESTION_DEADLINE_S}s | "
            f"single run")
RESULTS_DIR = Path(os.environ.get("EVAL_RESULTS_DIR", Path(__file__).parent / "results"))


# --clarify-pick second: instead of "pick the most likely yourself", the
# auto-reply names the SECOND expected book, so the run tests that a concrete
# choice is applied (answer about that book, not the other candidates).
CLARIFY_PICK = None


def auto_clarify_reply(item: dict) -> str:
    expected = item.get("expected_books") or []
    if CLARIFY_PICK == "second" and len(expected) >= 2:
        return expected[1]
    return t("eval_auto_clarify_reply")


def usage_fields() -> dict:
    """Cost, calls and tokens of the current question (the accumulator reset
    at the start of run_one)."""
    usage = usage_snapshot()
    return {"cost_usd": round(usage.get("cost_usd", 0.0), 4), "llm_calls": usage.get("llm_calls", 0),
            "tokens_in": usage.get("input_tokens", 0), "tokens_out": usage.get("output_tokens", 0)}


def run_one(graph, item: dict) -> dict:
    scratchpad = RESULTS_DIR / f"scratch-{item['id']}.md"
    scratchpad.write_text("")
    config = {"configurable": {"thread_id": item["id"]}}

    started = time.time()
    reset_usage()               # cost and tokens are per question, as in the runner
    steps_log = []
    clarify_asked = False
    run_input = initial_state(item["question"], history=[], scratchpad=scratchpad)
    try:
        while True:
            interrupted = False
            for step in graph.stream(run_input, config):
                if "__interrupt__" in step:
                    clarify_asked = True
                    steps_log.append(f"clarify: {step['__interrupt__'][0].value}")
                    run_input = Command(resume=auto_clarify_reply(item))
                    interrupted = True
                    break
                for node_name, update in step.items():
                    if node_name == "reflect" and update.get("current_query"):
                        steps_log.append(f"reflect -> {update['current_query'][:80]}")
                    elif node_name == "reflect" and update.get("stop_reason"):
                        # a stop is a step too: deadline, CRAG gate and "enough"
                        # must be tellable apart in the report
                        steps_log.append(f"reflect -> stop: {update['stop_reason']}")
            if not interrupted:
                break
        final = graph.get_state(config).values
    finally:
        # Every item is a thread in the in-memory checkpointer; drop it (also
        # when the item errored), or a 42-item run keeps every passage of every
        # question until the process exits.
        checkpointer = getattr(graph, "checkpointer", None)
        if checkpointer is not None and hasattr(checkpointer, "delete_thread"):
            checkpointer.delete_thread(config["configurable"]["thread_id"])
    result = {
        "id": item["id"], "type": item["type"],
        "question": item["question"],
        "answer": final.get("answer", ""),
        "verification": final.get("verification", ""),
        "provenance": final.get("provenance", {}),
        "steps_taken": final.get("steps_taken", 0),
        "read_chapters": final.get("read_chapters", []),
        "evidence_items": len(final.get("evidence") or []),
        "clarify_asked": clarify_asked,
        "clarify_candidates": final.get("clarify_candidates") or [],
        "clarify_unresolved": bool(final.get("clarify_unresolved")),
        "clarify_chosen": final.get("clarify_chosen") or "",
        # the planner gave no usable plan and the raw question was searched: the
        # run completes as an ordinary row, so the report must say it (local models)
        "plan_fallback": bool(final.get("plan_fallback")),
        # why the loop stopped (enough / CRAG gate / step limit / deadline / fallback):
        # an answer cut by the deadline and one written after "enough" must not
        # read the same in the report
        "stop_reason": final.get("stop_reason", "") or "",
        # the catalogue path (ADR-016): op, count (= len(books)), total, books, resolved;
        # empty for every run that went through the research loop
        "catalog": final.get("catalog") or {},
        # the hybrid and its fallbacks (ADR-016): a book the question named, resolved to
        # a retrieval filter; a name that matched nothing; a catalogue request that
        # took the research loop — each visible in the report row
        "book_filter": final.get("book_filter") or "",
        "book_unresolved": final.get("book_unresolved") or "",
        "catalog_fallback": final.get("catalog_fallback") or "",
        "seconds": round(time.time() - started),
        "steps_log": steps_log,
    }
    result.update(usage_fields())
    result["score"] = score(item, result)
    return result


def group_of(item: dict) -> str:
    """Behaviour PASS is reported per question type; id prefixes carry no meaning."""
    return item["type"]


# Phrases an honest refusal uses in either UI language; a heuristic stand-in for
# an LLM judge, so refusals that cite evidence to say "this is not here" still pass.
# The second block is the "the evidence does not hold it" family: local models
# phrase c08 as "the evidence provided does not contain information about ..." or
# "the provided evidence does not cover how ...", which is a refusal by any reading
# and used to score FAIL for want of a marker. Three verbs — contain, include,
# cover — in both voices and both numbers, so which one a model reaches for and
# whether it writes it actively is not what decides the score. Kept to shapes whose
# subject can only be the evidence or the library: "does not mention" is
# deliberately absent, because an answer that answers can still say that one
# chapter does not mention some detail.
REFUSAL_MARKERS = ("not included", "not in this", "not in the library", "not in my library",
                   "cannot answer", "can't answer", "cannot provide", "don't know", "do not have",
                   "not available", "no evidence", "not part of",
                   "does not contain", "do not contain", "is not contained", "are not contained",
                   "does not include", "do not include", "does not cover", "do not cover",
                   "is not covered", "are not covered", "не містить", "не містять",
                   "не знаю", "немає", "нема ", "не входить", "не можу відповісти", "доказів")

# A marker is where a refusal ENDS, so how much text may follow it is the second
# half of the rule. Without it, "The library does not contain this, but in the
# novel the captain ..." scores PASS: a marker, and then the episode told from
# the model's own memory, which is the exact failure a refusal item measures.
# The wider list above makes that shape likelier, because it now covers hedges
# models emit constantly ("the evidence does not include the exact wording,
# but ..."), so the two changes belong together.
#
# The budget separates two measured populations, not one sample from a guess.
# Every real refusal in docs/eval-results/2026-09-10-local-models.md, counted as
# prose after the first marker (labels stripped, see below): 11 words after "no
# evidence" in the qwen3.6 probe, 36 after "does not cover" (qwen2.5:14b), 37
# after "does not contain" (7b), and 42 in Run 8, where the same 7b refusal also
# says what the evidence holds instead — in each case a marker sentence that
# restates the question plus one or two more about the evidence. The control is
# the failure shape this half of the rule exists to catch: the same refusal that
# then retells the fence scene from model memory runs 82 words after its marker.
# 60 lies between the two with margin on both sides — 18 words above the longest
# honest refusal, 22 below the narration — so a refusal is not failed for being
# thorough and a retold episode still does not fit. Deliberately NOT part of the
# rule: the provenance count. An honest refusal quotes the card that says the
# thing is not in this edition, and c08 confirmed 3 quotes on 7b and 4 on 14b
# while declining, so "no confirmed quote" would fail the very answers this must
# keep passing. The heuristic's remaining limit, stated: a model that declines
# and then narrates in a dozen words still passes, which is what the
# manual-correctness checkbox in the report is for.
REFUSAL_TAIL_WORDS = 60

# Citations do not count against that budget. The rule forbids NARRATION after
# the marker, and a bracketed citation is the opposite of narration: it says
# which passages the refusal looked at, which the marker list above was widened
# to keep passing. Since the evidence block began carrying a filled label per
# line, a refusal that ends by naming what it read pays seven to nine whitespace
# tokens per label — the two that end Run 8's c08 are 18 of its 60 raw tail
# tokens, spent on being MORE accountable, and a refusal naming all four
# chapters it read would pay 36. So labels are stripped before the words are
# counted and the budget stays a budget for prose. (A markdown link's text would
# be stripped too; prose does not live in brackets.) Stripping alone did not
# rescue that answer: its prose is 42 words, which is the measurement the budget
# above was then read off.
CITATION_RE = re.compile(r"\[[^\[\]]*\]")


def is_refusal(answer: str) -> bool:
    """Does this (already folded) answer refuse — an explicit marker, and the
    answer ending there rather than carrying on with the story?"""
    hits = [(answer.find(m), len(m)) for m in REFUSAL_MARKERS if m in answer]
    if not hits:
        return False
    # the earliest marker, and the longest one starting there
    start, length = min(hits, key=lambda h: (h[0], -h[1]))
    tail = CITATION_RE.sub(" ", answer[start + length:])
    return len(tail.split()) <= REFUSAL_TAIL_WORDS


def fold(text: str) -> str:
    """Lower-case, accent-stripped text: 'Arsène' and 'Arsene' must match."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower())
                   if not unicodedata.combining(c))


def score(item: dict, r: dict) -> dict:
    """Behavioural score of one run against its golden item (pure function)."""
    expected = item.get("expected_books") or []
    answer = fold(r["answer"])
    mentioned = [b for b in expected if fold(b) in answer]
    behavior = item.get("expected_behavior")
    if item["type"] == "catalog":
        # The catalogue path is scored on its structured result, not on wording:
        # the set of books the code listed must EQUAL the expected set (strict,
        # by the full index key "Title — Author": one book too many fails, and
        # so does the right title under the wrong author), the count carried in
        # the state must be the length of that list, the catalogue must hold the
        # whole corpus, and "has"/"by_author" must resolve as expected. A
        # catalogue question that took the research loop has no result here and
        # fails.
        listing = r.get("catalog") or {}
        listed = {fold(k) for k in listing.get("books") or []}
        wanted = {fold(b) for b in expected}
        # expected_total: an item that expects nothing to be found ("is War and
        # Peace in my library?") passes over an EMPTY index otherwise, and a
        # targeted run of k03-k05 passes over a half-built one — the honest "no"
        # of a library with three books is not the answer being measured. An
        # item that names no total can therefore not pass at all.
        expected_total = item.get("expected_total")
        ok = (bool(listing) and listed == wanted
              and listing.get("count") == len(listing.get("books") or [])
              and expected_total is not None and listing.get("total") == expected_total)
        if "expected_op" in item:
            # Which operation code ran, not only what it returned: "has" and
            # "count" can both come back with an empty list on an empty question.
            ok = ok and listing.get("op") == item["expected_op"]
        if "expected_count" in item:
            ok = ok and listing.get("count") == item["expected_count"]
        if "expected_resolved" in item:
            ok = ok and bool(listing.get("resolved")) == bool(item["expected_resolved"])
        return {"titles_mentioned": len(listed & wanted), "titles_expected": len(wanted),
                "catalog_listed": len(listed), "behavior_ok": ok}
    if item["type"] == "refusal":
        # Evidence-free answers are NOT automatically refusals: the model may
        # have answered from its own knowledge. Only an explicit refusal passes,
        # and a marker with the story told after it is not one (see is_refusal).
        ok = is_refusal(answer)
    elif behavior == "research":
        # Routing only: a question that reads like a listing but needs the books'
        # content must take the research loop (at least one search, no catalogue
        # result); which books it names is not scored. The planner has to route
        # it there itself: a run where the planner produced nothing usable
        # (plan_fallback) or where code had to rescue a misroute
        # (catalog_fallback) searched for a different reason, and counting it as
        # a pass would measure the guards instead of the routing.
        ok = (not r.get("catalog") and r.get("steps_taken", 0) >= 1
              and not r.get("plan_fallback") and not r.get("catalog_fallback"))
    elif behavior == "clarify":
        ok = r["clarify_asked"]
    elif behavior == "clarify_or_answer":
        ok = r["clarify_asked"] or len(mentioned) == len(expected)
    else:
        ok = bool(expected) and len(mentioned) == len(expected)
    out = {"titles_mentioned": len(mentioned), "titles_expected": len(expected)}
    if CLARIFY_PICK == "second" and r.get("clarify_asked") and len(expected) >= 2:
        # Diagnostic, not part of PASS: was the user's concrete choice honoured?
        chosen = expected[1]
        candidates = r.get("clarify_candidates") or []
        offered = any(fold(chosen) in fold(c) for c in candidates)
        if not offered:
            out["choice"] = "candidate_missing"
        elif r.get("clarify_unresolved") or fold(chosen) not in fold(r.get("clarify_chosen") or ""):
            # Deterministic state first: the resolver itself says the choice
            # did not land; a title mention in the answer cannot override that.
            out["choice"] = "unresolved" if r.get("clarify_unresolved") else "resolver_mismatch"
        else:
            # applied = the answer is about the chosen book; naming the others
            # to contrast them is legitimate and only counted, not penalised
            others = [c for c in candidates if fold(chosen) not in fold(c)]
            out["others_mentioned"] = sum(fold(c.rsplit(" — ", 1)[0]) in answer for c in others)
            affirmed = bool(re.search(rf"(?<!\w)(?:not|no|never|isn't|wasn't|rather than)\W+(?:the\W+)?(?:\w+\W+){{0,2}}{re.escape(fold(chosen))}", answer)) is False
            out["choice"] = "applied" if fold(chosen) in answer and affirmed else "violated"
    if item.get("expects_chapter_read"):
        read = r.get("read_chapters") or []

        def counts(entry: str) -> bool:
            # "book|section|status"; an "empty" read (chapter not in the index)
            # is an attempt, not a drill-down. The status is the LAST part and
            # only when it is a known value: section names may contain "|",
            # and older reports carry no status (counted as complete).
            return entry.rpartition("|")[2] != "empty"

        out["drilldown_ok"] = any(fold(b) in fold(c.split("|", 1)[0])
                                  for c in read if counts(c) for b in expected)
        ok = ok and out["drilldown_ok"]
    if r.get("catalog"):
        # A content question sent down the catalogue path is the wrong kind of
        # answer whatever it lists (a full listing names every expected title).
        ok = False
        out["catalog_misroute"] = True
    if item.get("expected_book_filter"):
        # The hybrid: the named book must have been resolved to exactly that
        # book's key and retrieval limited to it (a wrong single resolve is the
        # silent failure this catches).
        out["book_filter_ok"] = fold(title_of(r.get("book_filter") or "")) == fold(item["expected_book_filter"])
        ok = ok and out["book_filter_ok"]
    out["behavior_ok"] = ok
    return out


def main() -> None:
    golden = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    # optional acceptance threshold: --min-pass N makes the run exit 1 below N behaviour PASSes
    argv = sys.argv[1:]
    min_pass = None
    if "--min-pass" in argv:
        i = argv.index("--min-pass")
        min_pass = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    global CLARIFY_PICK
    if "--clarify-pick" in argv:
        i = argv.index("--clarify-pick")
        CLARIFY_PICK = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if "--require-clean" in argv:
        # Published numbers come from a committed tree only: refuse dirty AND
        # unknown (git failed), never let "could not tell" pass as clean.
        argv.remove("--require-clean")
        stamp = git_code_stamp()
        if stamp == "unknown" or "+dirty(" in stamp:
            print(f"refusing to run: code state is {stamp!r}, not a verified clean commit "
                  "(--require-clean)", file=sys.stderr)
            sys.exit(2)
    wanted_ids = argv
    known = {q["id"] for q in golden["questions"]}
    unknown = [i for i in wanted_ids if i not in known]
    if unknown:
        # A typo must not turn into "0 completed, exit 0".
        print(f"unknown golden ids: {unknown}", file=sys.stderr)
        sys.exit(2)
    items = [q for q in golden["questions"] if not wanted_ids or q["id"] in wanted_ids]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / f"answers-{int(time.time())}.md"

    graph = build_graph()
    totals = {"run": 0, "errors": 0, "clarify": 0, "checked": 0, "confirmed": 0, "evidence": 0,
              "unattributed": 0, "broken": 0,
              "behavior_ok": 0, "titles_mentioned": 0, "titles_expected": 0,
              "drill_expected": 0, "drill_ok": 0, "cost_usd": 0.0, "llm_calls": 0,
              "tokens_in": 0, "tokens_out": 0}
    per_group = {}   # group -> [pass, total]
    with open(out_path, "w", encoding="utf-8") as out:
        fingerprint = run_fingerprint()
        out.write(f"# Agent eval — {time.strftime('%Y-%m-%d %H:%M')} — {GOLDEN_PATH.name}\n\n"
                  f"run: {fingerprint}\n")
        for item in items:
            print(f"=== {item['id']} ...", flush=True)
            try:
                r = run_one(graph, item)
            except Exception as error:
                # The calls made before the failure were billed all the same:
                # they count in the totals, and the mean is per attempted question.
                totals["errors"] += 1
                spent = usage_fields()
                for key in ("cost_usd", "llm_calls", "tokens_in", "tokens_out"):
                    totals[key] += spent[key]
                out.write(f"\n## {item['id']} — ERROR\n{error}\n"
                          f"(spent before the error: ${spent['cost_usd']:.4f}, {spent['llm_calls']} calls)\n")
                print(f"    ERROR: {error}", flush=True)
                continue
            totals["run"] += 1
            totals["clarify"] += int(r["clarify_asked"])
            totals["checked"] += r["provenance"].get("checked", 0)
            totals["confirmed"] += r["provenance"].get("confirmed", 0)
            totals["unattributed"] += r["provenance"].get("unattributed", 0)
            totals["broken"] += r["provenance"].get("broken", 0)
            totals["evidence"] += r["evidence_items"]
            for key in ("cost_usd", "llm_calls", "tokens_in", "tokens_out"):
                totals[key] += r[key]
            sc = r["score"]
            totals["behavior_ok"] += int(sc["behavior_ok"])
            totals["titles_mentioned"] += sc["titles_mentioned"]
            totals["titles_expected"] += sc["titles_expected"]
            grp = per_group.setdefault(group_of(r), [0, 0])
            grp[0] += int(sc["behavior_ok"]); grp[1] += 1
            if "drilldown_ok" in sc:
                totals["drill_expected"] += 1
                totals["drill_ok"] += int(sc["drilldown_ok"])
            verdict = "PASS" if sc["behavior_ok"] else "FAIL"
            drill = f", drilldown {'yes' if sc.get('drilldown_ok') else 'NO'}" if "drilldown_ok" in sc else ""
            if "choice" in sc:
                drill += f", clarify choice {sc['choice']}"
            if r.get("clarify_unresolved"):
                drill += ", clarify reply unresolved"
            if r.get("plan_fallback"):
                drill += ", planner fallback (raw question searched)"
            if r.get("catalog"):
                drill += (f", catalog {r['catalog']['op']}: {r['catalog']['count']} of {r['catalog']['total']}"
                          + (" — MISROUTED content question" if sc.get("catalog_misroute") else ""))
            if r.get("book_filter"):
                drill += f", named book -> retrieval filter {r['book_filter']}"
                if "book_filter_ok" in sc:
                    drill += f" ({'expected' if sc['book_filter_ok'] else 'NOT the expected book'})"
            if r.get("book_unresolved"):
                drill += f", named book not in the catalogue: {r['book_unresolved']}"
            if r.get("catalog_fallback"):
                drill += f", catalogue fallback ({r['catalog_fallback']})"
            if r.get("stop_reason"):
                drill += f", stop: {r['stop_reason']}"
            out.write(f"\n## {r['id']} ({r['type']}, {r['steps_taken']} steps, "
                      f"{r['seconds']}s, ${r['cost_usd']:.4f}, {r['llm_calls']} calls, "
                      f"{r['tokens_in']} in / {r['tokens_out']} out tokens"
                      f"{', clarify' if r['clarify_asked'] else ''}) — "
                      f"{verdict}: titles {sc['titles_mentioned']}/{sc['titles_expected']}{drill}\n\n"
                      f"- [ ] manual correctness (facts match the golden notes?)\n\n")
            out.write(f"**Question:** {r['question']}\n\n")
            for line in r["steps_log"]:
                out.write(f"- {line}\n")
            out.write(f"\n{r['answer']}\n\n> quote provenance: {r['verification']}\n")
            out.flush()
            print(f"    {r['steps_taken']} steps, {r['seconds']}s — {verdict}", flush=True)

        attempted = totals["run"] + totals["errors"]
        summary = (f"\n---\n{totals['run']} completed, {totals['errors']} errors, "
                   f"{totals['clarify']} clarify interrupts; quotes verified "
                   f"{totals['confirmed']}/{totals['checked']} (confirmed / unattributed / broken = "
                   f"{totals['confirmed']} / {totals['unattributed']} / {totals['broken']}); "
                   f"evidence items {totals['evidence']}\n"
                   f"behavior PASS {totals['behavior_ok']}/{totals['run']} ("
                   + ", ".join(f"{g} {p}/{n}" for g, (p, n) in sorted(per_group.items()))
                   + f"); expected titles mentioned {totals['titles_mentioned']}/{totals['titles_expected']}"
                   + (f"; chapter drill-down {totals['drill_ok']}/{totals['drill_expected']}"
                      if totals["drill_expected"] else "")
                   + (f"\ncost ${totals['cost_usd']:.4f} total, ${totals['cost_usd'] / attempted:.4f} mean per "
                      f"attempted question ({totals['llm_calls']} LLM calls, {totals['tokens_in']} in / "
                      f"{totals['tokens_out']} out tokens; configured rates ${PRICE_IN_PER_MTOK}/M in, "
                      f"${PRICE_OUT_PER_MTOK}/M out, cache reads not discounted)"
                      if attempted else "")
                   + "\nmanual correctness: not scored — tick the checkboxes above\n")
        out.write(summary)
    print(summary)
    print(f"run: {fingerprint}")
    print(f"Report: {out_path}")
    if totals["errors"] or (min_pass is not None and totals["behavior_ok"] < min_pass):
        sys.exit(1)


if __name__ == "__main__":
    main()
