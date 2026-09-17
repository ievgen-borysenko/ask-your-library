"""Agent eval: run golden questions through the FULL agentic loop and score
the observable behaviour against the golden set.

The loop is the shipped one and nothing here re-implements it: every question
goes through `runner.run_question`, the entry point the CLI and the web UI call
(ADR-009, amended 16.09). This file supplies the two callbacks — an event
collector for the steps log, and the automatic clarify reply — and reads the run
off the RunResult it gets back. Clarify interrupts are answered automatically,
so the run is non-interactive.
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
  facts     every string in the item's expected_facts occurs in the answer
            (folded, whitespace-normalised substring; no fuzzy matching), reported
            as facts_found/facts_expected and facts_ok — a FOURTH row, deliberately
            NOT part of behavior_ok: ADR-010 rejected a composite score, and a fact
            can be present in a sentence that says the wrong thing about it
Answer CORRECTNESS is not scored: a verbatim quote of a character's false claim
passes provenance and titles and can still be wrong, and a green run can be
incomplete when the answering passage was never retrieved (see the c06 trace in
docs/examples). The report leaves a manual-correctness checkbox per question.

Every run writes TWO files side by side: the Markdown report a reader reads
(answers-<ts>.md) and a JSON sidecar (answers-<ts>.json), the machine-readable
record of the same run — the fingerprint as fields rather than one string, and
every attempt of every question with its score. --repeat N runs each item N
times and both files then carry the spread, because one sample of a
non-deterministic system is not a number anyone can publish.

  uv run eval/run_agent_eval.py [id ...]     # no ids = every question
  GOLDEN_PATH=... LIBRARY_DB_PATH=... uv run eval/run_agent_eval.py [ids...]
      [--min-pass N] [--clarify-pick second] [--require-clean]
      [--repeat N] [--no-json] [--record-plans]

--record-plans keeps every planner request/response of the run in
eval/recordings/, so a later change to the deterministic half of plan() can be
replayed for free by eval/run_plan_eval.py. It costs nothing extra: the calls
are made either way.
"""
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import statistics
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import yaml

from ask_your_library.catalog import CATALOG_OPS
from ask_your_library.graph import build_graph
from ask_your_library.bookkey import title_of
from ask_your_library.i18n import t
from ask_your_library import library
from ask_your_library.config import (CHAPTER_HIT_CHARS, MAX_CLARIFY_CANDIDATES, MAX_EMPTY_STREAK, MAX_STEPS,
                                     PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK, QUESTION_DEADLINE_S, SEARCH_HIT_CHARS)
from ask_your_library.llm import usage_snapshot
# The one home of the rule (it used to live here and in the runner, with the
# repo root derived two different ways); re-exported because the recorder, the
# plan replay and the tests reach for it as `harness.redact_paths`.
from ask_your_library.paths import redact_paths
from ask_your_library.provenance import HIT_ID_STRICT
from ask_your_library.runner import run_question

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


def golden_location(repo: Path) -> str:
    """Where the golden file is, said without naming the machine it is on.

    `eval/golden/en-demo.yaml` inside the repository, the bare file name for a
    GOLDEN_PATH that points anywhere else — a private set under someone's home
    directory is a path that identifies the reader, not the measurement."""
    try:
        return str(GOLDEN_PATH.resolve().relative_to(repo))
    except (OSError, ValueError):
        return GOLDEN_PATH.name


def run_facts(repeat: int = 1) -> dict:
    """The fingerprint as FIELDS: one reading of the code stamp, the checksums,
    the backend, the model, the index stamps and every knob that changes the
    answer.

    It exists so the one-line fingerprint in the Markdown report and the JSON
    sidecar cannot say different things about the same run: the line below is
    rendered from this dict, and the sidecar stores the dict. Adding a knob here
    puts it in both, or in neither."""
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
    from ask_your_library.config import DB_PATH, LLM_BACKEND, ORCHESTRATOR_MODEL, TABLES
    stamps = []
    try:
        import lancedb
        from ask_your_library.index_meta import read_index_meta
        db = lancedb.connect(DB_PATH)
        for name in TABLES.values():
            meta = read_index_meta(db, name) or {}
            table = db.open_table(name)
            # The chunker is in the stamp because it decides what a row IS: a
            # re-chunk changes what is retrieved for every question, so two
            # reports from two chunkers are not comparable however alike their
            # other fields look (#28, ADR-025). An index built before the stamp
            # existed records nothing, and prints as "?" rather than a guess.
            stamps.append(f"{name}={meta.get('model', '?')}/{meta.get('dims', '?')}d "
                          f"chunker={meta.get('chunker') or '?'} "
                          f"rows={table.count_rows()} v{getattr(table, 'version', '?')} "
                          f"built={meta.get('created', '?')}")
    except Exception as error:  # the report must not fail on fingerprinting
        stamps.append(f"index=unavailable ({type(error).__name__})")
    return {
        "code": sha,
        # a stamp is a verified clean commit only when it is a bare sha (see git_code_stamp)
        "code_clean": sha != "unknown" and "+dirty(" not in sha,
        # repo-relative, never the absolute path: GOLDEN_PATH sits under a home
        # directory that names whoever ran it, and this file is meant to be
        # committed beside a published number. The name and the checksum below
        # identify the file; the leading path identifies nothing but a machine.
        "golden_path": golden_location(repo),
        "golden_name": GOLDEN_PATH.name,
        "golden_sha256_12": golden_sha,
        "manifest_sha256_12": corpus_sha,
        "toc_sha256_12": toc_sha,
        "model": ORCHESTRATOR_MODEL,
        "backend": LLM_BACKEND,
        "index": stamps,
        "strict_hit_id": bool(HIT_ID_STRICT),
        "clarify_pick": CLARIFY_PICK,
        "search_hit_chars": SEARCH_HIT_CHARS,
        "chapter_hit_chars": CHAPTER_HIT_CHARS,
        "max_steps": MAX_STEPS,
        "max_empty_streak": MAX_EMPTY_STREAK,
        "max_clarify_candidates": MAX_CLARIFY_CANDIDATES,
        "question_deadline_s": QUESTION_DEADLINE_S,
        "price_in_per_mtok": PRICE_IN_PER_MTOK,
        "price_out_per_mtok": PRICE_OUT_PER_MTOK,
        "repeat": repeat,
    }


def render_fingerprint(f: dict) -> str:
    """What exactly produced this report: code SHA, golden checksum, model AND
    the backend that served it, index stamps — a number without these is not
    attributable.

    The backend used to be silent, and silence meant the hosted default. That
    default is the local backend now, so an unnamed backend would leave the
    reports in docs/eval-results/ — every one of them measured on the hosted
    configuration — indistinguishable from a free local run. It is named.

    The tail used to read "single run" and nothing else; it still does at
    --repeat 1, and names the number of attempts above it."""
    repeat = f["repeat"]
    return (f"code {f['code']} | golden {f['golden_name']}@{f['golden_sha256_12']} | "
            f"manifest@{f['manifest_sha256_12']} | "
            f"toc@{f['toc_sha256_12']} | model {f['model']} via {f['backend']} | "
            f"{' | '.join(f['index'])} | "
            f"strict_hit_id={'on' if f['strict_hit_id'] else 'off'} | "
            f"clarify_pick={f['clarify_pick'] or 'default'} | "
            f"hit_chars={f['search_hit_chars']}/{f['chapter_hit_chars']} | "
            f"steps={f['max_steps']}/{f['max_empty_streak']} | "
            f"candidates={f['max_clarify_candidates']} | "
            f"deadline={f['question_deadline_s']}s | "
            + ("single run" if repeat == 1 else f"{repeat} attempts per item"))


def run_fingerprint(repeat: int = 1) -> str:
    """The one-line fingerprint, read off the facts (eval/run_ablation.py calls
    this; nothing else needs the two steps apart)."""
    return render_fingerprint(run_facts(repeat))


def load_plan_recording():
    """eval/plan_recording.py as a module.

    `eval/` is a directory of scripts and not a package: running this file puts
    its own directory on sys.path, but eval/run_ablation.py and the tests load
    it BY PATH and then it is not there. So the sibling is loaded by path too —
    the same way run_ablation.py loads this harness — and only when
    --record-plans asks for it, so a run that records nothing imports nothing."""
    spec = importlib.util.spec_from_file_location(
        "plan_recording", Path(__file__).resolve().parent / "plan_recording.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


def usage_fields(usage: dict | None = None) -> dict:
    """Cost, calls and tokens of one question, flat, as the report and the
    sidecar carry them.

    `usage` is the snapshot the runner took at the end of the run (the one the
    metrics event reported). Without it the current accumulator is read
    instead — the two conditions in eval/run_ablation.py that answer without
    the graph, and the error path in main(), have no result to read."""
    usage = usage_snapshot() if usage is None else usage
    return {"cost_usd": round(usage.get("cost_usd", 0.0), 4), "llm_calls": usage.get("llm_calls", 0),
            "tokens_in": usage.get("input_tokens", 0), "tokens_out": usage.get("output_tokens", 0),
            # The chapter-read window (#28), three counts that only mean
            # something together: reads, reads that said what they were looking
            # for, and reads whose window moved off the head of the chapter.
            # `steps_log` cannot answer the middle one — it prints the marker
            # cut to 80 characters — and it is the one number that says whether
            # the model uses the field at all. Plus the times a chapter query
            # came back at the row cap, which is a ceiling the re-chunk moved.
            # `.get` throughout: a record written before these existed reads
            # back as the run it was, one that never opened a window.
            "chapter_reads": usage.get("chapter_reads", 0),
            "chapter_reads_aimed": usage.get("chapter_reads_aimed", 0),
            "chapter_windows_opened": usage.get("chapter_windows_opened", 0),
            "chapter_row_cap_hits": usage.get("chapter_row_cap_hits", 0)}


def role_seconds(usage: dict) -> dict:
    """Wall clock per node role, rounded as the metrics event carries it.

    Locally the cost of a question is $0 and the only currency is seconds, so
    a latency budget can only be argued per node (#32). Empty for a run whose
    usage carries no roles — the fake results the harness's own tests feed it,
    and any run that spent no call at all — which is what keeps the report of
    such a run byte-identical to the reports written before this existed."""
    return {role: r["seconds"] for role, r in (usage.get("by_role") or {}).items()
            if "seconds" in r}


def run_one(graph, item: dict, attempt: int = 1) -> dict:
    """One question through the same runner the CLI and the web UI use.

    The harness is a consumer of `runner.run_question` and not a second
    execution path (ADR-009, amended 16.09.2026): the stream loop, the clarify
    interrupt, the per-question usage reset and the scratchpad all belong to
    the runner, and what this function keeps is what is its own — the
    auto-reply policy (--clarify-pick), the steps log the report prints, and
    the flat fields `score()` and the report row read.

    A run that failed comes back as a result with a `failure` rather than as an
    exception, because the calls it spent still have to be accounted for; the
    exception is re-raised here so that main() writes the ERROR row and the
    spend exactly as it did before.
    """
    # Under --repeat every attempt of an item would otherwise write the same
    # scratchpad and only the last one's window would survive the run; the first
    # attempt keeps the name it has always had.
    suffix = "" if attempt == 1 else f"-{attempt}"
    steps_log = []

    def on_event(node_name: str, update: dict) -> None:
        if node_name == "reflect" and update.get("current_query"):
            steps_log.append(f"reflect -> {update['current_query'][:80]}")
        elif node_name == "reflect" and update.get("stop_reason"):
            # a stop is a step too: deadline, CRAG gate and "enough"
            # must be tellable apart in the report
            steps_log.append(f"reflect -> stop: {update['stop_reason']}")

    def on_clarify(question_to_user: str) -> str:
        # The harness's own clarify policy, as the runner's reply callback.
        steps_log.append(f"clarify: {question_to_user}")
        return auto_clarify_reply(item)

    result = run_question(graph, item["question"], history=[], scratch_dir=RESULTS_DIR,
                          on_event=on_event, on_clarify=on_clarify,
                          scratchpad_name=f"scratch-{item['id']}{suffix}.md")
    if result.failure is not None:
        # `is not None`, not truthiness: an exception class may define __bool__
        # or __len__, and a falsy one would be replaced here by a stand-in that
        # is not the error that happened.
        if result.failure.error is not None:
            raise result.failure.error
        raise RuntimeError(str(result.failure))
    record = {
        "id": item["id"], "type": item["type"],
        "question": item["question"],
        "answer": result.answer,
        "verification": result.verification,
        "provenance": result.provenance,
        "steps_taken": result.steps_taken,
        "read_chapters": result.read_chapters,
        "evidence_items": len(result.evidence),
        # the observe gate (#29): quotes that never reached the answer because
        # no retrieved passage of their step held them, and quotes re-pinned to
        # the passage that did. A question that ends with no evidence at all
        # still carries them, which is often the only account of why it refused
        "dropped_unverified": result.dropped_unverified,
        # the same number split by the rule that refused each quote — no_hit,
        # cross_book, short, not_found — because they call for different fixes
        "dropped_by_reason": result.dropped_by_reason,
        "repinned": result.repinned,
        "clarify_asked": result.clarify_asked,
        "clarify_candidates": result.clarify_candidates,
        "clarify_unresolved": result.clarify_unresolved,
        "clarify_chosen": result.clarify_chosen,
        # the planner gave no usable plan and the raw question was searched: the
        # run completes as an ordinary row, so the report must say it (local models)
        "plan_fallback": result.plan_fallback,
        # why the loop stopped (enough / CRAG gate / step limit / deadline / fallback):
        # an answer cut by the deadline and one written after "enough" must not
        # read the same in the report
        "stop_reason": result.stop_reason,
        # the catalogue path (ADR-016): op, count (= len(books)), total, books, resolved;
        # empty for every run that went through the research loop
        "catalog": result.catalog,
        # the hybrid and its fallbacks (ADR-016): a book the question named, resolved to
        # a retrieval filter; a name that matched nothing; a catalogue request that
        # took the research loop — each visible in the report row
        "book_filter": result.book_filter,
        "book_unresolved": result.book_unresolved,
        "catalog_fallback": result.catalog_fallback,
        "seconds": round(result.seconds),
        "steps_log": steps_log,
        # wall clock per node role: the report line and the sidecar carry it so a
        # local latency budget can be argued per node (#32)
        "by_role_seconds": role_seconds(result.usage),
    }
    record.update(usage_fields(result.usage))
    record["score"] = score(item, record)
    return record


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


def flat(text: str) -> str:
    """Folded text with every run of whitespace collapsed to one space: a fact
    written as two words must still be found when the answer wrapped it across
    a line break."""
    return " ".join(fold(text).split())


def facts_score(item: dict, answer: str) -> dict:
    """The fourth row: which of the item's expected_facts occur in the answer.

    Presence of a short, checkable string — a name, a number, a place — folded
    and whitespace-normalised, nothing fuzzy: no stemming, no synonyms, no
    edit distance, so a red row is read as "this string is not in the answer",
    never as "the answer is wrong". Deliberately kept OUT of behavior_ok
    (ADR-010: three rows that cannot be confused, no composite score). An item
    with no expected_facts scores 0/0 and ok — a refusal has no facts to carry."""
    facts = item.get("expected_facts") or []
    haystack = flat(answer)
    found = [f for f in facts if flat(f) in haystack]
    return {"facts_found": len(found), "facts_expected": len(facts),
            "facts_ok": len(found) == len(facts)}


# --- the golden item contract -------------------------------------------------
# One table, read by the load-time guard below AND by tests/test_golden_schema.py,
# so the harness and the guard over the repository's own files cannot drift apart.
# Every key here is a key score() or the report reads; anything else in an item is
# a typo, and a typo is silent: score() reads items with .get() throughout, so
# `expected_behaviour` turns a clarify item into an ordinary one and the run still
# prints a green row. Keys are allowed per TYPE, not per file: a catalogue item has
# no use for expects_chapter_read, and expected_op on a research item would never
# be read.
COMMON_KEYS = {"id", "question", "type", "expected_books", "expected_facts", "notes"}
RESEARCH_KEYS = COMMON_KEYS | {"expected_behavior", "expects_chapter_read", "expected_book_filter"}
CATALOG_KEYS = COMMON_KEYS | {"expected_op", "expected_count", "expected_total", "expected_resolved"}
ALLOWED_KEYS = {"identify": RESEARCH_KEYS, "answer": RESEARCH_KEYS, "aggregation": RESEARCH_KEYS,
                "refusal": RESEARCH_KEYS, "catalog": CATALOG_KEYS}
# expected_facts is required, not optional: a missing key would score 0/0 and ok,
# so a run could end with a green facts row that measured nothing. A refusal says
# so by carrying an empty list.
REQUIRED_KEYS = {"id", "question", "type", "expected_books", "expected_facts"}
# expected_total is the one catalogue key score() cannot pass without.
REQUIRED_BY_TYPE = {"catalog": REQUIRED_KEYS | {"expected_total"}}
# The values the branches of score() actually read; anything else falls through to
# the default branch, which is exactly the silent misscoring this guard is for.
BEHAVIORS = {"research", "clarify", "clarify_or_answer"}


def _is_text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_text_list(value) -> bool:
    return isinstance(value, list) and all(_is_text(v) for v in value)


def _is_whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


# key -> (predicate, what it must be). Every allowed key has an entry; a new key
# without one is caught by tests/test_golden_schema.py.
FIELD_CHECKS = {
    "id": (_is_text, "a non-empty string"),
    "question": (_is_text, "a non-empty string"),
    "type": (lambda v: v in ALLOWED_KEYS, f"one of {sorted(ALLOWED_KEYS)}"),
    "notes": (_is_text, "a non-empty string"),
    "expected_books": (_is_text_list, "a list of non-empty strings"),
    "expected_facts": (_is_text_list, 'a list of non-empty strings (a number needs quoting: - "33")'),
    "expected_behavior": (lambda v: v in BEHAVIORS, f"one of {sorted(BEHAVIORS)}"),
    "expects_chapter_read": (lambda v: isinstance(v, bool), "true or false"),
    "expected_book_filter": (_is_text, "a non-empty string"),
    "expected_op": (lambda v: v in CATALOG_OPS, f"one of {sorted(CATALOG_OPS)}"),
    "expected_count": (_is_whole, "a whole number"),
    "expected_total": (_is_whole, "a whole number"),
    "expected_resolved": (lambda v: isinstance(v, bool), "true or false"),
}


def check_golden(items: list[dict]) -> None:
    """Refuse an unusable golden file BEFORE the graph is built and before the
    first billed call.

    GOLDEN_PATH points wherever the caller says, and every failure here is
    silent at run time rather than loud: a misspelled `expected_fact:` disables
    the facts row and the run ends with a misleading 0/0; `expected_behaviour`
    scores a clarify item as an ordinary one; an unquoted `- 33` is an int and
    raises inside the scorer, after every earlier item has been billed; a bare
    string (`expected_facts: Cedric`) is matched per character; an empty fact is
    contained in every answer. Every problem in the file is reported at once —
    fixing them one run at a time is the cost this guard exists to avoid."""
    problems = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"item #{index}: {item!r} is not a mapping")
            continue
        where = item.get("id") if _is_text(item.get("id")) else f"item #{index}"
        kind = item.get("type")
        if kind not in ALLOWED_KEYS:
            # every other rule depends on the type; nothing more can be said
            problems.append(f"{where}: type {kind!r} is not one of {sorted(ALLOWED_KEYS)}")
            continue
        missing = sorted(REQUIRED_BY_TYPE.get(kind, REQUIRED_KEYS) - set(item))
        if missing:
            problems.append(f"{where}: missing {missing}")
        unknown = sorted(set(item) - ALLOWED_KEYS[kind])
        if unknown:
            problems.append(f"{where}: unknown keys {unknown} for type {kind!r} "
                            f"(allowed: {sorted(ALLOWED_KEYS[kind])})")
        for key, value in item.items():
            check = FIELD_CHECKS.get(key)
            if check and not check[0](value):
                problems.append(f"{where}: {key} must be {check[1]}, got {value!r}")
    if problems:
        raise ValueError("this golden file cannot be scored as written:\n  " + "\n  ".join(problems))


def score(item: dict, r: dict) -> dict:
    """Behavioural score of one run against its golden item (pure function)."""
    expected = item.get("expected_books") or []
    answer = fold(r["answer"])
    facts = facts_score(item, r["answer"])
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
                "catalog_listed": len(listed), **facts, "behavior_ok": ok}
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
    out = {"titles_mentioned": len(mentioned), "titles_expected": len(expected), **facts}
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


# --- the spread of N attempts -------------------------------------------------
# One run is one sample of a system that is not deterministic, and a single
# sample published as a number is the limitation ADR-010 recorded rather than
# solved. --repeat N takes N samples per item. Scoring stays per attempt — the
# scorer never sees more than one run — and the aggregation is here.
#
# Booleans are COUNTED, never averaged: "behaviour held in 2 of 3 attempts" is a
# statement a reader can act on, where a mean of true and false is not. Money,
# seconds and tokens get min / median / max, because their interesting property
# is the range, and the median rather than the mean because three attempts of
# which one hit the deadline have a mean nobody spent.
BOOLEAN_ROWS = (("behavior_ok", "behavior PASS"), ("facts_ok", "facts_ok"),
                ("drilldown_ok", "drilldown"))
NUMBER_ROWS = (("cost_usd", "cost", "${:.4f}"), ("seconds", "seconds", "{:g}"),
               ("llm_calls", "llm calls", "{:g}"), ("tokens_in", "tokens in", "{:g}"),
               ("tokens_out", "tokens out", "{:g}"))


def spread_of(values: list, digits: int | None = None) -> dict | None:
    """min / median / max of one numeric column, or None when nothing completed.

    `digits` rounds the three, for money: the median of an even number of
    attempts is a mean of two floats, and a cost is four decimals everywhere
    else in this harness."""
    if not values:
        return None
    measured = {"min": min(values), "median": statistics.median(values), "max": max(values)}
    return measured if digits is None else {k: round(v, digits) for k, v in measured.items()}


def expected_of(items: list[dict]) -> dict:
    """What ONE attempt over this set is expected to produce, read off the
    golden items themselves.

    Denominators must not be counted up from the results: a row is only added
    when an attempt completed, so an item that errored disappears from the
    denominator it belongs to and an item that errored every time takes its
    whole row with it — a set of eleven where three failed would report
    "8 of 8". These numbers are the same for every attempt by construction, so
    reading them from the file is both simpler and impossible to lose."""
    groups = {}
    for item in items:
        groups[group_of(item)] = groups.get(group_of(item), 0) + 1
    return {"items": len(items),
            "titles": sum(len(i.get("expected_books") or []) for i in items),
            "facts": sum(len(i.get("expected_facts") or []) for i in items),
            "facts_items": sum(1 for i in items if i.get("expected_facts")),
            "drill_items": sum(1 for i in items if i.get("expects_chapter_read")),
            "groups": dict(sorted(groups.items()))}


def item_spread(item: dict, attempts: list[dict], repeat: int) -> dict:
    """The per-item block both files carry under --repeat.

    Every boolean count is out of the attempts ASKED for, not out of the ones
    that completed: an attempt that errored did not pass, and shrinking the
    denominator to hide it is how a flaky item comes to look green. Which rows
    exist is read from the GOLDEN ITEM, not from the results — an item whose
    every attempt errored still owes a facts row and a drill-down row, as 0 of
    N, where deriving them from the completed attempts would silently omit
    them. The numeric columns are over the attempts that produced a number."""
    done = [a for a in attempts if not a.get("error")]
    out = {"attempts": repeat, "completed": len(done), "errors": len(attempts) - len(done),
           "behavior_ok": sum(int(a["score"]["behavior_ok"]) for a in done)}
    if item.get("expected_facts"):
        out["facts_ok"] = sum(int(a["score"].get("facts_ok", False)) for a in done)
    if item.get("expects_chapter_read"):
        out["drilldown_ok"] = sum(int(a["score"].get("drilldown_ok", False)) for a in done)
    for key, _label, _fmt in NUMBER_ROWS:
        measured = spread_of([a[key] for a in done if key in a],
                             digits=4 if key == "cost_usd" else None)
        if measured:
            out[key] = measured
    return out


def render_item_spread(item_id: str, sp: dict) -> str:
    """The per-item spread as the Markdown block that follows its attempts."""
    n = sp["attempts"]
    head = f"\n### {item_id} — spread over {n} attempts"
    if sp["errors"]:
        head += f" ({sp['errors']} errored)"
    lines = [head, ""]
    for key, label in BOOLEAN_ROWS:
        if key in sp:
            lines.append(f"- {label} {sp[key]}/{n}")
    for key, label, fmt in NUMBER_ROWS:
        if key in sp:
            lines.append(f"- {label} min / median / max: "
                         + " / ".join(fmt.format(sp[key][part]) for part in ("min", "median", "max")))
    return "\n".join(lines) + "\n"


def spread_line(label: str, values: list, of=None, fmt="{:g}") -> str:
    """One totals aggregate as a range over the attempts, with the per-attempt
    mean beside it — never the sum alone, which reads like a single run."""
    of_text = f"/{of}" if of is not None else ""
    # counts are whole at the ends and fractional in the middle; two decimals,
    # so "1.67 of 2" cannot be misread as a count that was actually measured
    mean_fmt = fmt if fmt != "{:g}" else "{:.2f}"
    return (f"- {label} {fmt.format(min(values))}–{fmt.format(max(values))}{of_text} "
            f"over {len(values)} attempts "
            f"(mean {mean_fmt.format(sum(values) / len(values))} per attempt)")


def empty_totals() -> dict:
    """One attempt's totals: --repeat keeps one of these per attempt index, and
    the report's own block is their sum."""
    return {"run": 0, "errors": 0, "clarify": 0, "checked": 0, "checked_book_text": 0,
            "confirmed": 0, "evidence": 0,
            "unattributed": 0, "broken": 0, "card_only": 0,
            "dropped_unverified": 0, "dropped_cross_book": 0, "repinned": 0,
            "behavior_ok": 0, "titles_mentioned": 0, "titles_expected": 0,
            "facts_found": 0, "facts_expected": 0, "facts_items": 0, "facts_items_ok": 0,
            "drill_expected": 0, "drill_ok": 0, "cost_usd": 0.0, "llm_calls": 0,
            "tokens_in": 0, "tokens_out": 0,
            "chapter_reads": 0, "chapter_reads_aimed": 0, "chapter_windows_opened": 0,
            "chapter_row_cap_hits": 0}


def render_summary(totals: dict, per_group: dict, repeat: int, attempt_totals: list[dict],
                   attempt_groups: list[dict], expected: dict) -> str:
    """The `\\n---\\n` tail.

    At --repeat 1 this is byte for byte the block the harness has always
    written, and that is a contract: eval/summarize_report.py copies it into
    every committed summary, and every artifact under docs/eval-results/ was
    produced by it.

    At N > 1 it is a different block on purpose. NOT ONE FIGURE IN IT IS A SUM
    ACROSS ATTEMPTS: a set of two items run three times has six passes and six
    titles, and "behavior PASS 5/6, expected titles mentioned 5/5" describes a
    six-question set nobody ran. Every line is per attempt — min–max over the N
    attempts with the mean beside it — and the one figure that IS summed, the
    money actually spent, says so in words."""
    attempted = totals["run"] + totals["errors"]
    if repeat == 1:
        headline = ("behavior PASS "
                    f"{totals['behavior_ok']}/{totals['run']} ("
                    + ", ".join(f"{g} {p}/{n}" for g, (p, n) in sorted(per_group.items())) + ")")
        return (f"\n---\n{totals['run']} completed, {totals['errors']} errors, "
                f"{totals['clarify']} clarify interrupts; quotes verified "
                f"{totals['confirmed']}/{totals['checked_book_text']} "
                f"(confirmed / unattributed / broken = "
                f"{totals['confirmed']} / {totals['unattributed']} / {totals['broken']})"
                # Only when there are any: a run with no card match writes the
                # line it has always written, which is the byte-compat contract
                # with eval/summarize_report.py and docs/eval-results/.
                + (f"; {totals['card_only']} quotes matched only a book card, "
                   f"not the book text" if totals["card_only"] else "")
                # The observe gate (#29), on the same rule as the card line: a
                # run that dropped and re-pinned nothing writes the line it has
                # always written, which is the byte-compat contract with
                # eval/summarize_report.py and docs/eval-results/.
                + (f"; {totals['dropped_unverified']} quotes dropped before the answer "
                   f"(not in the passage they cited"
                   + (f", {totals['dropped_cross_book']} of them held only by another book"
                      if totals["dropped_cross_book"] else "") + ")"
                   if totals["dropped_unverified"] else "")
                + (f"; {totals['repinned']} quotes re-pinned to the passage that holds them"
                   if totals["repinned"] else "")
                # The chapter-read window (#28), on the same rule again: a run
                # that read no chapter writes the line it always wrote.
                + (f"; chapter reads {totals['chapter_reads']} "
                   f"({totals['chapter_reads_aimed']} named what they were looking for, "
                   f"{totals['chapter_windows_opened']} opened a window off the head of the "
                   f"chapter)" if totals["chapter_reads"] else "")
                + (f"; {totals['chapter_row_cap_hits']} chapter query(ies) hit the "
                   f"{library.CHAPTER_ROW_CAP}-row cap"
                   if totals["chapter_row_cap_hits"] else "")
                + f"; evidence items {totals['evidence']}\n"
                + headline
                + f"; expected titles mentioned {totals['titles_mentioned']}/{totals['titles_expected']}"
                + (f"; chapter drill-down {totals['drill_ok']}/{totals['drill_expected']}"
                   if totals["drill_expected"] else "")
                + (f"\nexpected facts found {totals['facts_found']}/{totals['facts_expected']}; "
                   f"answers carrying every expected fact {totals['facts_items_ok']}/{totals['facts_items']} "
                   f"(substring presence, not correctness; not part of behaviour PASS)"
                   if totals["facts_expected"] else "")
                + (f"\ncost ${totals['cost_usd']:.4f} total, ${totals['cost_usd'] / attempted:.4f} mean per "
                   f"attempted question ({totals['llm_calls']} LLM calls, {totals['tokens_in']} in / "
                   f"{totals['tokens_out']} out tokens; configured rates ${PRICE_IN_PER_MTOK}/M in, "
                   f"${PRICE_OUT_PER_MTOK}/M out, cache reads not discounted)"
                   if attempted else "")
                + "\nmanual correctness: not scored — tick the checkboxes above\n")

    def column(key: str) -> list:
        return [t[key] for t in attempt_totals]

    # Denominators come from the golden items, never from the results: a row is
    # only added to a totals dict when an attempt completed, so an item that
    # errored would drop out of the denominator it belongs to.
    per_pass = expected["items"]

    def group_range(g: str, of: int) -> str:
        passes = [a.get(g, [0, 0])[0] for a in attempt_groups]
        return f"{g} {min(passes)}–{max(passes)}/{of}"

    lines = [f"\n---\nrun of {repeat} attempts per item, {per_pass} items; every figure below is "
             f"PER ATTEMPT (min–max over the {repeat} attempts, with the mean), never a sum "
             f"across them",
             spread_line("behavior PASS", column("behavior_ok"), of=per_pass)
             + " [" + ", ".join(group_range(g, of) for g, of in expected["groups"].items()) + "]",
             spread_line("completed", column("run"), of=per_pass),
             spread_line("errors", column("errors")),
             spread_line("clarify interrupts", column("clarify")),
             # Paired per attempt, never min(confirmed)–max(confirmed) over
             # max(checked): attempts of 3/3 and 4/10 would print "3–4/10", a
             # ratio no attempt produced and the best-looking one available.
             "- quotes confirmed / checked, per attempt: "
             + ", ".join(f"{t['confirmed']}/{t['checked_book_text']}" for t in attempt_totals),
             spread_line("quotes unattributed", column("unattributed")),
             spread_line("quotes broken", column("broken")),
             spread_line("evidence items", column("evidence")),
             spread_line("expected titles mentioned", column("titles_mentioned"),
                         of=expected["titles"])]
    if any(column("card_only")):
        # Added only where it happened: a set answered entirely from book text
        # keeps the block it had, and a reader who sees the line knows the run
        # quoted something a model wrote.
        lines.insert(-1, spread_line("quotes matched only a book card", column("card_only")))
    if any(column("dropped_unverified")) or any(column("repinned")):
        # Same rule for the observe gate (#29). Both lines together or neither,
        # so the reader sees the whole of what the gate did at this repeat.
        lines.insert(-1, spread_line("quotes dropped before the answer",
                                     column("dropped_unverified")))
        if any(column("dropped_cross_book")):
            lines.insert(-1, spread_line("of those, held only by another book",
                                         column("dropped_cross_book")))
        lines.insert(-1, spread_line("quotes re-pinned to the passage that holds them",
                                     column("repinned")))
    if expected["drill_items"]:
        lines.append(spread_line("chapter drill-down", column("drill_ok"),
                                 of=expected["drill_items"]))
    if expected["facts"]:
        lines.append(spread_line("expected facts found", column("facts_found"),
                                 of=expected["facts"]))
        lines.append(spread_line("answers carrying every expected fact", column("facts_items_ok"),
                                 of=expected["facts_items"])
                     + " (substring presence, not correctness; not part of behaviour PASS)")
    lines.append(spread_line("cost", column("cost_usd"), fmt="${:.4f}"))
    lines.append(spread_line("llm calls", column("llm_calls")))
    lines.append(spread_line("tokens in", column("tokens_in")))
    lines.append(spread_line("tokens out", column("tokens_out")))
    if attempted:
        # the one honest sum: what the whole run actually cost, labelled as such
        lines.append(f"- spent in total across all {repeat} attempts: ${totals['cost_usd']:.4f}, "
                     f"{totals['llm_calls']} LLM calls, {totals['tokens_in']} in / "
                     f"{totals['tokens_out']} out tokens; configured rates "
                     f"${PRICE_IN_PER_MTOK}/M in, ${PRICE_OUT_PER_MTOK}/M out, cache reads not "
                     f"discounted")
    return "\n".join(lines) + "\nmanual correctness: not scored — tick the checkboxes above\n"


def write_sidecar(path: Path, report_path: Path, facts: dict, fingerprint: str, repeat: int,
                  requested_ids: list[str], started: float, ended: float, totals: dict,
                  attempt_totals: list[dict], attempt_groups: list[dict], expected: dict,
                  records: list[dict]) -> None:
    """The same run as data, beside the Markdown a reader reads.

    The report's shape is a contract with eval/summarize_report.py, so nothing
    can be added to it without re-reading that parser, and every number in it
    has to be scraped back out of prose by anyone who wants to plot it or
    compare two runs. This file is the record instead: the fingerprint as
    fields, the totals, and every attempt of every question with its full answer
    and the score dict computed from it — the answer included on purpose, so the
    sidecar is complete on its own rather than a pointer into the Markdown.

    NOTHING HERE IS SUMMED ACROSS ATTEMPTS either, at any N: `totals.per_attempt`
    carries each aggregate as the list of its per-attempt values with min /
    median / max beside them, `totals.expected_per_attempt` the denominators
    read off the golden items, and the only summed figures are under
    `totals.spent_total`, which is money and calls that really were spent once
    each. The shape does not change with N — at --repeat 1 every list holds one
    value — so a consumer written against one run reads a repeated one.

    Keys are written in a fixed order and text is left as text
    (ensure_ascii=False), so two runs of the same set diff line by line."""
    def clock(when: float) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(when))

    def per_attempt(key: str) -> dict:
        values = [t[key] for t in attempt_totals]
        digits = 4 if key == "cost_usd" else None
        return {"values": [round(v, 4) if digits else v for v in values],
                **spread_of(values, digits=digits)}

    sidecar = {
        "schema": "ask-your-library/agent-eval-run",
        "schema_version": 1,
        "report": report_path.name,
        "fingerprint": fingerprint,
        "run": facts,
        "started": clock(started),
        "ended": clock(ended),
        "seconds": round(ended - started),
        "repeat": repeat,
        "requested_ids": list(requested_ids),
        "items": len(records),
        "totals": {
            "per_attempt": {key: per_attempt(key) for key in sorted(empty_totals())},
            # denominators from the golden items, so an item that errored every
            # time still counts against the row it belongs to
            "expected_per_attempt": expected,
            # the one honest sum: spent once each, whatever N was
            "spent_total": {"cost_usd": round(totals["cost_usd"], 4),
                            "llm_calls": totals["llm_calls"],
                            "tokens_in": totals["tokens_in"],
                            "tokens_out": totals["tokens_out"]},
        },
        # per group, the passes of each attempt against the group's size in the
        # golden set — never a sum, and never a denominator counted up from the
        # attempts that happened to complete
        "per_group": {group: {"of": of,
                              "behavior_ok_per_attempt": [a.get(group, [0, 0])[0]
                                                          for a in attempt_groups]}
                      for group, of in expected["groups"].items()},
        "attempt_totals": attempt_totals,
        "attempt_groups": [{group: {"behavior_ok": groups.get(group, [0, 0])[0], "of": of}
                            for group, of in expected["groups"].items()}
                           for groups in attempt_groups],
        "questions": records,
    }
    # written to a neighbour and renamed: json.dumps walks the whole record
    # after the Markdown is already closed, and a Ctrl-C or a full disk halfway
    # through must leave no half file claiming to be the record of this run
    scratch = path.with_suffix(".json.tmp")
    scratch.write_text(json.dumps(sidecar, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    scratch.replace(path)


def recording_item(recorder, item_id: str, attempt: int):
    """The recorder's per-item block, or nothing at all when this run is not
    recording. One line at the call site, so the run loop reads the same with
    --record-plans and without it."""
    return recorder.item(item_id, attempt) if recorder is not None else contextlib.nullcontext()


def parse_args(argv: list[str]) -> argparse.Namespace:
    """The flags this harness has always had, now declared rather than sliced
    out of sys.argv by hand: every one of them keeps its exact behaviour, and
    the ids stay positional."""
    parser = argparse.ArgumentParser(
        description="Run the golden questions through the full agentic loop, score the observable "
                    "behaviour, and write a Markdown report with a JSON sidecar beside it.")
    parser.add_argument("ids", nargs="*", metavar="id",
                        help="golden ids to run; no ids at all = every question in the file")
    parser.add_argument("--min-pass", type=int, default=None, metavar="N",
                        help="exit 1 when behaviour PASS is below N; under --repeat the WEAKEST "
                             "attempt has to reach it, so the threshold is a floor and not an average")
    parser.add_argument("--clarify-pick", default=None, metavar="WHICH",
                        help='"second": answer a clarify interrupt by naming the second expected '
                             'book, so the run tests that a concrete choice is applied')
    parser.add_argument("--require-clean", action="store_true",
                        help="refuse to run unless the tree is a verified clean commit; a published "
                             "number comes from a committed tree or from nowhere")
    parser.add_argument("--repeat", type=int, default=1, metavar="N",
                        help="run every item N times (default 1). The report and the sidecar then "
                             "carry the spread: how many attempts of N passed each boolean row, "
                             "and min/median/max of cost, seconds and tokens")
    parser.add_argument("--json", action=argparse.BooleanOptionalAction, default=True,
                        help="write the JSON sidecar answers-<ts>.json beside the report (default: on)")
    parser.add_argument("--record-plans", action="store_true",
                        help="record every planner request/response of this run into "
                             "eval/recordings/<golden>.<sha>.<model>.jsonl, so that a later change "
                             "to plan()'s deterministic half can be replayed for free by "
                             "eval/run_plan_eval.py. Costs nothing extra: it rides on the run "
                             "that is happening anyway. A run of selected ids writes a "
                             ".subset-<k>of<n>.jsonl of its own instead")
    parser.add_argument("--overwrite", action="store_true",
                        help="let --record-plans replace a recording that is already there. "
                             "Refused by default: that file is the artefact of a run somebody "
                             "paid for")
    # parse_intermixed_args, not parse_args: the hand-rolled slicing this
    # replaced cut the flags out wherever they stood and kept everything else as
    # ids, so `c01 --min-pass 11 c02` meant two ids. Plain argparse stops
    # collecting the positional at the first flag and rejects `c02` as
    # unrecognised — a silent change of meaning for anyone with that command in
    # their shell history.
    args = parser.parse_intermixed_args(argv)
    if args.repeat < 1:
        # zero attempts is not a run, and a negative one is a typo that would
        # otherwise produce an empty report with a green exit code
        parser.error(f"--repeat must be at least 1, got {args.repeat}")
    return args


def main(argv: list[str] | None = None) -> None:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    repeat = args.repeat
    min_pass = args.min_pass
    golden = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    # the whole file, not only the requested ids: a bad item must fail the run
    # before the graph is built and before anything is billed
    check_golden(golden["questions"])
    global CLARIFY_PICK
    if args.clarify_pick is not None:
        CLARIFY_PICK = args.clarify_pick
    if args.require_clean:
        # Published numbers come from a committed tree only: refuse dirty AND
        # unknown (git failed), never let "could not tell" pass as clean.
        stamp = git_code_stamp()
        if stamp == "unknown" or "+dirty(" in stamp:
            print(f"refusing to run: code state is {stamp!r}, not a verified clean commit "
                  "(--require-clean)", file=sys.stderr)
            sys.exit(2)
    wanted_ids = args.ids
    known = {q["id"] for q in golden["questions"]}
    unknown = [i for i in wanted_ids if i not in known]
    if unknown:
        # A typo must not turn into "0 completed, exit 0".
        print(f"unknown golden ids: {unknown}", file=sys.stderr)
        sys.exit(2)
    items = [q for q in golden["questions"] if not wanted_ids or q["id"] in wanted_ids]

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    out_path = RESULTS_DIR / f"answers-{stamp}.md"
    json_path = RESULTS_DIR / f"answers-{stamp}.json"

    # what ONE attempt over this set owes, read off the golden items: every
    # denominator in the repeated-run report and in the sidecar comes from here
    expected = expected_of(items)

    graph = build_graph()
    # One totals dict and one group table PER ATTEMPT INDEX; the report's own
    # block is their sum, and the spread is read across them. At --repeat 1 the
    # lists hold one element each and the sum is that element.
    attempt_totals = [empty_totals() for _ in range(repeat)]
    attempt_groups = [{} for _ in range(repeat)]    # group -> [pass, total]
    records = []                                    # the sidecar's per-question rows
    started = time.time()
    # Read before the report is opened and before anything is billed: a run that
    # is going to refuse to write its recording must refuse now, not after the
    # money is spent (--record-plans below).
    facts_of_run = run_facts(repeat)
    fingerprint = render_fingerprint(facts_of_run)
    recording_path = plan_recording = recording_header = None
    if args.record_plans:
        plan_recording = load_plan_recording()
        # A run of selected ids records those ids and no others. Under the name
        # of the whole set it would overwrite the complete recording of a paid
        # run with three items and leave a file whose name still claims 42, so
        # it gets a name and a header flag of its own.
        subset = (len(items), len(golden["questions"])) if wanted_ids else None
        recording_path = plan_recording.RECORDINGS_DIR / plan_recording.recording_name(
            facts_of_run["golden_name"], facts_of_run["golden_sha256_12"],
            facts_of_run["model"], subset=subset)
        recording_header = {"subset": bool(subset), "subset_items": len(items),
                            "golden_items": len(golden["questions"]),
                            "requested_ids": list(wanted_ids)}
        if recording_path.exists() and not args.overwrite:
            print(f"refusing to record over {redact_paths(str(recording_path))}: that file is the "
                  "artefact of a run somebody paid for, and this run would replace it. "
                  "--overwrite replaces it on purpose; moving it aside keeps both",
                  file=sys.stderr)
            sys.exit(2)

    with open(out_path, "w", encoding="utf-8") as out, contextlib.ExitStack() as recording:
        out.write(f"# Agent eval — {time.strftime('%Y-%m-%d %H:%M')} — {GOLDEN_PATH.name}\n\n"
                  f"run: {fingerprint}\n")
        recorder = None
        if args.record_plans:
            # Rides on the run that is happening anyway: the planner's calls are
            # made either way, and this only keeps what came back, so that the
            # deterministic half of plan() can be re-measured for free later
            # (eval/run_plan_eval.py).
            recorder = recording.enter_context(plan_recording.PlanRecorder(
                recording_path, facts_of_run, redact=redact_paths,
                knobs=plan_recording.model_knobs(), header=recording_header))
            out.write(f"planner calls recorded into: {recording_path.name}\n")
            print(f"recording planner calls into {recording_path}", flush=True)
        for item in items:
            record = {"id": item["id"], "type": item["type"], "group": group_of(item),
                      "question": item["question"], "attempts": []}
            records.append(record)
            for attempt in range(1, repeat + 1):
                totals = attempt_totals[attempt - 1]
                per_group = attempt_groups[attempt - 1]
                # the marker is empty at --repeat 1, which is what keeps the
                # report of a single run byte-identical to every earlier one
                marker = "" if repeat == 1 else f", attempt {attempt}/{repeat}"
                print(f"=== {item['id']}{marker} ...", flush=True)
                try:
                    with recording_item(recorder, item["id"], attempt):
                        r = run_one(graph, item, attempt)
                except Exception as error:
                    # The calls made before the failure were billed all the same:
                    # they count in the totals, and the mean is per attempted question.
                    totals["errors"] += 1
                    spent = usage_fields()
                    for key in ("cost_usd", "llm_calls", "tokens_in", "tokens_out"):
                        totals[key] += spent[key]
                    # the message goes into the report AND the sidecar, and
                    # summarize_report.py copies the report's ERROR lines into
                    # the committed summary: an absolute path in it is the
                    # reader's home directory, so it is redacted in both
                    said = redact_paths(f"{error}")
                    record["attempts"].append({"attempt": attempt,
                                               "error": f"{type(error).__name__}: {said}", **spent})
                    out.write(f"\n## {item['id']} — ERROR\n{said}\n"
                              f"({f'attempt {attempt}/{repeat}, ' if repeat > 1 else ''}"
                              f"spent before the error: ${spent['cost_usd']:.4f}, "
                              f"{spent['llm_calls']} calls)\n")
                    print(f"    ERROR: {error}", flush=True)
                    continue
                record["attempts"].append({"attempt": attempt,
                                           **{k: v for k, v in r.items() if k != "score"},
                                           "score": r["score"]})
                totals["run"] += 1
                totals["clarify"] += int(r["clarify_asked"])
                totals["checked"] += r["provenance"].get("checked", 0)
                totals["confirmed"] += r["provenance"].get("confirmed", 0)
                totals["unattributed"] += r["provenance"].get("unattributed", 0)
                totals["broken"] += r["provenance"].get("broken", 0)
                # A quote matched only inside a book card is not traced to the
                # book (provenance.validate); it is counted apart and it is not
                # in the denominator of the confirmed ratio. `.get` with the old
                # meaning as the default: a sidecar written before 16.09 has
                # neither key, and reads back as a run with no cards in it.
                totals["card_only"] += r["provenance"].get("card_only", 0)
                totals["checked_book_text"] += r["provenance"].get(
                    "checked_book_text", r["provenance"].get("checked", 0))
                # The gate's own numbers (#29). They are NOT part of `checked`:
                # a dropped quote never became evidence, so it is not in any
                # denominator above — it is what the answer was refused. `.get`
                # defaults to 0, so a record written before the gate reads back
                # as the run it was, one that dropped nothing.
                totals["dropped_unverified"] += r.get("dropped_unverified", 0)
                totals["dropped_cross_book"] += (r.get("dropped_by_reason") or {}).get("cross_book", 0)
                totals["repinned"] += r.get("repinned", 0)
                totals["evidence"] += r["evidence_items"]
                for key in ("cost_usd", "llm_calls", "tokens_in", "tokens_out"):
                    totals[key] += r[key]
                for key in ("chapter_reads", "chapter_reads_aimed",
                            "chapter_windows_opened", "chapter_row_cap_hits"):
                    totals[key] += r.get(key, 0)
                sc = r["score"]
                totals["behavior_ok"] += int(sc["behavior_ok"])
                totals["titles_mentioned"] += sc["titles_mentioned"]
                totals["titles_expected"] += sc["titles_expected"]
                totals["facts_found"] += sc["facts_found"]
                totals["facts_expected"] += sc["facts_expected"]
                if sc["facts_expected"]:
                    # items that carry no expected_facts (refusals, the clarify items
                    # whose two candidates contradict each other) are not counted as
                    # green: they are not measured by this row at all
                    totals["facts_items"] += 1
                    totals["facts_items_ok"] += int(sc["facts_ok"])
                grp = per_group.setdefault(group_of(r), [0, 0])
                grp[0] += int(sc["behavior_ok"]); grp[1] += 1
                if "drilldown_ok" in sc:
                    totals["drill_expected"] += 1
                    totals["drill_ok"] += int(sc["drilldown_ok"])
                verdict = "PASS" if sc["behavior_ok"] else "FAIL"
                # The facts row rides beside the verdict, never inside it: "facts 2/3 NO"
                # on a PASS line is the report saying "behaviour held, read this answer".
                facts = (f", facts {sc['facts_found']}/{sc['facts_expected']}"
                         + ("" if sc["facts_ok"] else " NO")) if sc["facts_expected"] else ""
                drill = f", drilldown {'yes' if sc.get('drilldown_ok') else 'NO'}" if "drilldown_ok" in sc else ""
                if "choice" in sc:
                    drill += f", clarify choice {sc['choice']}"
                if r.get("clarify_unresolved"):
                    drill += ", clarify reply unresolved"
                if r.get("plan_fallback"):
                    drill += ", planner fallback (raw question searched)"
                if r.get("dropped_unverified"):
                    drill += (f", {r['dropped_unverified']} quotes dropped before the answer "
                              f"(not in the passage they cited)")
                if (r.get("dropped_by_reason") or {}).get("cross_book"):
                    drill += (f", {r['dropped_by_reason']['cross_book']} of them held only by "
                              f"another book")
                if r.get("repinned"):
                    drill += f", {r['repinned']} quotes re-pinned"
                if r.get("chapter_reads"):
                    # Only on a question that read a chapter at all, so every
                    # other row is the row it has always been.
                    drill += (f", chapter reads {r['chapter_reads']} "
                              f"({r.get('chapter_reads_aimed', 0)} named what they were looking "
                              f"for, {r.get('chapter_windows_opened', 0)} opened a window off the "
                              f"head)")
                if r.get("chapter_row_cap_hits"):
                    drill += (f", {r['chapter_row_cap_hits']} chapter query(ies) hit the "
                              f"{library.CHAPTER_ROW_CAP}-row cap")
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
                          f"{', clarify' if r['clarify_asked'] else ''}{marker}) — "
                          f"{verdict}: titles {sc['titles_mentioned']}/{sc['titles_expected']}{facts}{drill}\n\n"
                          f"- [ ] manual correctness (facts match the golden notes?)\n\n")
                out.write(f"**Question:** {r['question']}\n\n")
                for line in r["steps_log"]:
                    out.write(f"- {line}\n")
                if r.get("by_role_seconds"):
                    # only when the run really spent calls: a run that spent none
                    # writes the line it always wrote
                    out.write("- seconds by role: " + ", ".join(
                        f"{role} {seconds:g}" for role, seconds in r["by_role_seconds"].items()) + "\n")
                out.write(f"\n{r['answer']}\n\n> quote provenance: {r['verification']}\n")
                out.flush()
                print(f"    {r['steps_taken']} steps, {r['seconds']}s — {verdict}", flush=True)
            # the sidecar carries the per-item spread at every N (at 1 it is the
            # one attempt stated as such); the report prints it only when there
            # is a spread to print, so a single run's Markdown is unchanged
            record["spread"] = item_spread(item, record["attempts"], repeat)
            if repeat > 1:
                out.write(render_item_spread(item["id"], record["spread"]))
                out.flush()

        # Closed HERE, not on the way out of the ExitStack: a recording that
        # refuses to finalise — a line that held something token-shaped, a write
        # that failed — has to say so in the report this run is still writing,
        # and turn its exit code, rather than raise past a finished report.
        recording_problem = ""
        if recorder is not None:
            try:
                recorder.close()
            except (plan_recording.SecretInRecording,
                    plan_recording.RecordingIncomplete) as error:
                recording_problem = redact_paths(f"{type(error).__name__}: {error}")
                print(recording_problem, file=sys.stderr)

        totals = empty_totals()
        for one in attempt_totals:
            for key, value in one.items():
                totals[key] += value
        per_group = {}
        for groups in attempt_groups:
            for group, (passed, of) in groups.items():
                row = per_group.setdefault(group, [0, 0])
                row[0] += passed; row[1] += of
        summary = render_summary(totals, per_group, repeat, attempt_totals, attempt_groups,
                                 expected)
        if recording_problem:
            summary += f"{recording_problem}\n"
        out.write(summary)
        ended = time.time()
        sidecar_written = False
        if args.json:
            try:
                write_sidecar(json_path, out_path, facts_of_run, fingerprint, repeat, wanted_ids,
                              started, ended, totals, attempt_totals, attempt_groups, expected,
                              records)
                sidecar_written = True
            except Exception as error:
                # The questions were run and the report is on disk: a record
                # that could not be serialised must not turn a measured run into
                # a failed one, and must not be silent about itself either. The
                # note goes into the tail, which is what summarize_report.py
                # copies into the committed summary.
                note = f"JSON sidecar NOT written: {type(error).__name__}: {error}"
                out.write(f"{note}\n")
                summary += f"{note}\n"
                print(note, file=sys.stderr)
    print(summary)
    print(f"run: {fingerprint}")
    print(f"Report: {out_path}")
    if sidecar_written:
        print(f"Sidecar: {json_path}")
    if recording_path is not None:
        print(f"Plan recording: {recording_path}")
    # Under --repeat the threshold is a floor on every attempt, not on their sum:
    # a set that passes 11/11 twice and 7/11 once has not met a --min-pass of 11.
    weakest = min(t["behavior_ok"] for t in attempt_totals)
    if totals["errors"] or recording_problem or (min_pass is not None and weakest < min_pass):
        sys.exit(1)


if __name__ == "__main__":
    main()
