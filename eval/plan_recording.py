"""The planner's decisions, on disk: the record format, the recorder that fills
it during a paid run, and the replayer that feeds it back for free.

Why this exists. `plan()` is one model call followed by a hundred lines of
deterministic post-processing: the mode, the validated catalogue operation, the
mixed-intent gate, the query filter, the named-book resolution against the
catalogue, the two fallbacks. Every change to that half used to cost a full
paid run of the golden set to measure, because the only way to reach it was
through the model. It does not have to: the model's part of the decision is a
string, and a string can be kept.

So a normal run records every `role="plan"` request/response pair
(`eval/run_agent_eval.py --record-plans`), and `eval/run_plan_eval.py` then
calls the REAL `plan()` with `llm.ask_json` replaced by a replayer that hands
back the recorded reply. What that measures is the deterministic half; what it
cannot measure is a change to `PLAN_RULES`, because the recorded reply answers
the OLD prompt. The recording carries the prompt's hash for exactly that
reason, and the replay harness refuses to run against a recording whose hash no
longer matches unless it is told to, and says so in its report when it does.

The seams, and why they are not in nodes.py
-------------------------------------------
Recording rides on `llm.JSON_CALL_OBSERVER`, a module-level hook `ask_json`
notifies after every attempt: passive, unable to change what a call returns,
and off unless a harness installs it. Replay replaces the `ask_json` NAME on
the `llm` module, which is how `nodes.py` reaches it (`llm.ask_json(...)`) and
how the unit tests have always scripted the planner. The catalogue is the third
seam: `plan()` calls `list_books` through the name `nodes.py` imported, so the
replay harness rebinds `nodes.list_books` when there is no index to read, the
same way `eval/run_ablation.py` rebinds `nodes.search_both`. `nodes.py` is not
touched by any of it.

The file
--------
`eval/recordings/<golden-stem>.<golden-sha12>.<model>.jsonl`, one JSON object
per line, `ensure_ascii=False` so two recordings diff line by line.

  line 1  the header: the schema, the golden file's name and checksum, the
          PLAN_RULES hash, the model, the backend, the code stamp, the clock.
  line n  one plan CALL: the golden id, the harness attempt it belongs to, the
          call's index within that attempt (a clarify makes `plan` run twice),
          the exact user payload, the raw reply text, the model knobs, the
          clock, and the cost/tokens that call alone spent.

A recording is written to `<name>.jsonl.partial` and renamed on a clean close,
so a file at the final name is a run that finished; a crashed paid run leaves
its `.partial` beside it with everything it managed to record, to be renamed by
hand rather than lost.

Nothing machine-identifying goes in: every free-text field passes through the
harness's `redact_paths`, so an absolute path in a payload or a reply becomes
`<repo>` or `~`. No API key can reach the file — the recorder is handed the
system prompt, the user payload and the reply, and never the client.
"""
import contextlib
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ask_your_library import llm
from ask_your_library.prompts import PLAN_RULES

SCHEMA = "ask-your-library/plan-recording"
SCHEMA_VERSION = 1
PLAN_ROLE = "plan"

# Where recordings live. Committed, unlike eval/results/: a recording is small
# (a few hundred kilobytes for the biggest golden set), it is the artefact that
# makes a replayed number reproducible by someone who did not pay for the run,
# and a number whose input is not in the tree is not attributable.
RECORDINGS_DIR = Path(os.environ.get("AYL_PLAN_RECORDINGS_DIR",
                                     Path(__file__).resolve().parent / "recordings"))


class StaleRecording(RuntimeError):
    """The recording does not describe the tree that is about to be replayed."""


class MissingRecording(RuntimeError):
    """This item was never recorded; there is nothing to replay for it."""


def sha12(text: str) -> str:
    """The short checksum this project uses everywhere: sha256, first 12 hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def prompt_hash(rules: str = PLAN_RULES) -> str:
    """The identity of the planner's prompt. A recording made under a different
    one answers a question that is no longer being asked."""
    return sha12(rules)


def model_slug(model: str) -> str:
    """`anthropic/claude-sonnet-4.6` as a file-name component. A model id
    carries a slash and the file name has to survive it; nothing else is
    changed, so the slug is still readable as the model."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "unknown"


def recording_name(golden_name: str, golden_sha12: str, model: str) -> str:
    """`<golden-stem>.<golden-sha12>.<model>.jsonl`.

    The checksum is IN THE NAME so that two recordings of the same set under
    different golden files cannot overwrite each other, and so a stale one is
    visible in a directory listing and not only on opening it."""
    return f"{Path(golden_name).stem}.{golden_sha12}.{model_slug(model)}.jsonl"


# --- the record -------------------------------------------------------------
def header_record(facts: dict, **extra) -> dict:
    """The recording's first line, read off the main harness's `run_facts()`.

    Only the fields that decide whether a replay is honest are copied here: the
    golden file's identity, the prompt's hash, the model and the backend that
    produced the replies, and the code stamp of the tree they were produced on.
    The rest of the fingerprint belongs to the RUN, and the replay harness reads
    its own."""
    return {"schema": SCHEMA, "schema_version": SCHEMA_VERSION, "kind": "header",
            "golden_name": facts.get("golden_name", ""),
            "golden_path": facts.get("golden_path", ""),
            "golden_sha256_12": facts.get("golden_sha256_12", ""),
            "plan_rules_sha256_12": prompt_hash(),
            "model": facts.get("model", ""), "backend": facts.get("backend", ""),
            "code": facts.get("code", ""), "code_clean": facts.get("code_clean", False),
            "repeat": facts.get("repeat", 1),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **extra}


@dataclass
class Recording:
    """A loaded recording: its header, and the plan calls of each (id, attempt)
    in the order they were made."""
    path: Path
    header: dict
    calls: dict = field(default_factory=dict)      # (id, attempt) -> [call, ...]

    def identity(self) -> str:
        """What a report names when it says where its numbers came from."""
        return (f"{self.path.name} (golden {self.header.get('golden_name', '?')}"
                f"@{self.header.get('golden_sha256_12', '?')}, "
                f"PLAN_RULES@{self.header.get('plan_rules_sha256_12', '?')}, "
                f"model {self.header.get('model', '?')} via "
                f"{self.header.get('backend', '?')}, recorded {self.header.get('created', '?')})")

    def stale_against(self, golden_sha12: str, rules_hash: str | None = None) -> list[str]:
        """Every reason this recording does not describe the current tree.

        Two questions, deliberately answered separately: a golden checksum that
        moved means the QUESTIONS changed, so the recorded replies answer other
        questions; a PLAN_RULES hash that moved means the planner was asked
        something else, so the replies are the old prompt's and a replay
        measures the post-processing only. Both are refusals by default, and
        the second one is the reason this harness cannot be used to grade a
        prompt change at all."""
        reasons = []
        recorded_golden = self.header.get("golden_sha256_12", "")
        if recorded_golden != golden_sha12:
            reasons.append(f"golden checksum: recording has {recorded_golden or '?'}, "
                           f"this file is {golden_sha12} — the questions changed")
        current = prompt_hash() if rules_hash is None else rules_hash
        recorded_rules = self.header.get("plan_rules_sha256_12", "")
        if recorded_rules != current:
            reasons.append(f"PLAN_RULES checksum: recording has {recorded_rules or '?'}, "
                           f"this tree has {current} — a prompt change needs a NEW recording, "
                           "a replay cannot measure it")
        return reasons


def load_recording(path: Path) -> Recording:
    """Read a recording, refusing anything that is not one.

    A malformed file is a hard error, never a silently short replay: a
    recording missing half its lines would report a planner that suddenly
    stopped deciding."""
    path = Path(path)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise StaleRecording(f"{path.name} is empty: it is not a recording")
    try:
        header = json.loads(lines[0])
    except json.JSONDecodeError as error:
        raise StaleRecording(f"{path.name}: the first line is not JSON ({error})") from error
    if not isinstance(header, dict) or header.get("kind") != "header":
        raise StaleRecording(f"{path.name}: the first line is not a recording header")
    if header.get("schema") != SCHEMA:
        raise StaleRecording(f"{path.name}: schema {header.get('schema')!r}, expected {SCHEMA!r}")
    if header.get("schema_version") != SCHEMA_VERSION:
        raise StaleRecording(f"{path.name}: schema_version {header.get('schema_version')!r}, "
                             f"this tree reads {SCHEMA_VERSION}")
    calls: dict = {}
    for number, line in enumerate(lines[1:], start=2):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise StaleRecording(f"{path.name}: line {number} is not JSON ({error})") from error
        if not isinstance(record, dict) or record.get("kind") != "call":
            raise StaleRecording(f"{path.name}: line {number} is not a call record")
        key = (record.get("id"), record.get("attempt", 1))
        if not key[0]:
            raise StaleRecording(f"{path.name}: line {number} names no golden id")
        calls.setdefault(key, []).append(record)
    return Recording(path=path, header=header, calls=calls)


# --- recording --------------------------------------------------------------
class PlanRecorder:
    """Installs the `llm` observer for the length of a run and writes one line
    per plan call.

    It is a context manager twice over: the outer one owns the file and the
    observer, the inner `item()` says which golden id and attempt the next
    calls belong to. Calls made outside an `item()` block, and calls of any
    role but `plan`, are ignored — a run records the planner, not the whole
    loop."""

    def __init__(self, path: Path, facts: dict, redact=lambda text: text, knobs: dict | None = None):
        self.path = Path(path)
        self.partial = self.path.with_suffix(self.path.suffix + ".partial")
        self.facts = facts
        self.redact = redact
        self.knobs = knobs or {}
        self.lines = 0
        self._file = None
        self._previous_observer = None
        self._current = None            # (id, attempt) or None
        self._call_index = 0
        self._usage_mark = (0.0, 0, 0, 0)

    # -- the file -----------------------------------------------------------
    def __enter__(self) -> "PlanRecorder":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.partial.open("w", encoding="utf-8")
        self._write(header_record(self.facts, **self.knobs))
        self._previous_observer = llm.JSON_CALL_OBSERVER
        llm.JSON_CALL_OBSERVER = self._observe
        return self

    def __exit__(self, *exc) -> bool:
        llm.JSON_CALL_OBSERVER = self._previous_observer
        self._file.close()
        self._file = None
        # A crash leaves the .partial where it is: the calls it holds were paid
        # for, and losing them to a failed last item would be the expensive
        # half of this change undone.
        if exc[0] is None:
            os.replace(self.partial, self.path)
        return False

    def _write(self, record: dict) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()          # a long paid run must not hold its record in a buffer
        self.lines += 1

    # -- what the calls belong to -------------------------------------------
    @contextlib.contextmanager
    def item(self, item_id: str, attempt: int = 1):
        """The next plan calls belong to this golden id and this attempt."""
        self._current = (item_id, attempt)
        self._call_index = 0
        self._usage_mark = self._usage()
        try:
            yield self
        finally:
            self._current = None

    @staticmethod
    def _usage() -> tuple:
        usage = llm.usage_snapshot()
        return (usage.get("cost_usd", 0.0), usage.get("llm_calls", 0),
                usage.get("input_tokens", 0), usage.get("output_tokens", 0))

    def _spent(self) -> dict:
        """What THIS call cost, as the difference between two readings of the
        run accumulator. The accumulator is per question (the harness resets it
        in `run_one`), so a difference is the only honest per-call figure
        available without a second accounting path."""
        now = self._usage()
        before, self._usage_mark = self._usage_mark, now
        return {"cost_usd": round(now[0] - before[0], 6), "llm_calls": now[1] - before[1],
                "tokens_in": now[2] - before[2], "tokens_out": now[3] - before[3]}

    # -- the observer -------------------------------------------------------
    def _observe(self, call: dict) -> None:
        if call.get("role") != PLAN_ROLE or self._current is None:
            return
        item_id, attempt = self._current
        json_attempt = call.get("attempt", 1)
        # `call` counts ask_json CALLS (a clarify makes plan run a second time);
        # `json_attempt` counts the model calls inside one of them (the retry
        # after a malformed reply). Two numbers, because the replayer walks the
        # first and re-parses the second exactly as ask_json did.
        if json_attempt == 1:
            self._call_index += 1
        self._write({
            "schema_version": SCHEMA_VERSION, "kind": "call",
            "id": item_id, "attempt": attempt, "call": self._call_index,
            "role": PLAN_ROLE, "json_attempt": json_attempt,
            # the prompt is identified, never copied: it is in prompts.py, and a
            # recording that carried it would go stale by being read
            "system_sha256_12": sha12(call.get("system", "")),
            "user": self.redact(call.get("user", "")),
            "raw": self.redact(call.get("raw", "")),
            "error": self.redact(call.get("error", "") or ""),
            "model": self.facts.get("model", ""), "backend": self.facts.get("backend", ""),
            **self.knobs,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **self._spent(),
        })


def model_knobs() -> dict:
    """Every knob of the planner's own call that could change the reply, read
    off the configuration the run is using. `reasoning_effort` is sent on the
    local backend only (see `llm.llm`), so it is recorded as it was sent."""
    from ask_your_library.config import (LLM_BACKEND, LLM_BASE_URL, LLM_TIMEOUT_S,
                                         MAX_OUTPUT_TOKENS)
    return {"temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS,
            "reasoning_effort": "none" if LLM_BACKEND == "ollama" else "",
            "llm_timeout_s": LLM_TIMEOUT_S,
            # the endpoint's SHAPE, not the endpoint: a local base URL carries a
            # port a reader may have changed, and nothing else about it matters
            "local_endpoint": LLM_BASE_URL.startswith(("http://localhost",
                                                       "http://127.0.0.1"))}


# --- replay -----------------------------------------------------------------
class PlanReplayer:
    """Stands in for `llm.ask_json`, and never calls a model.

    Faithful to `ask_json`, not to its happy path: the recorded calls of an
    item are walked in order and each raw reply is parsed by `llm.json_object`,
    the very function that parsed it live, so a reply that was malformed twice
    raises the same `ValueError` here and `plan()` degrades to its fallback
    exactly as it did on the paid run."""

    def __init__(self, recording: Recording):
        self.recording = recording
        self.calls = 0
        self.missing: list = []
        self._queue = None
        self._key = None

    @contextlib.contextmanager
    def item(self, item_id: str, attempt: int = 1):
        key = (item_id, attempt)
        self._key = key
        self._queue = list(self.recording.calls.get(key, []))
        try:
            yield self
        finally:
            self._queue = self._key = None

    def __call__(self, system: str, user: str, role: str) -> dict:
        if role != PLAN_ROLE:
            # Only the planner is recorded. A replay that silently answered
            # another role would be inventing evidence.
            raise MissingRecording(f"only {PLAN_ROLE!r} calls are recorded; this run asked for "
                                   f"{role!r}")
        if not self._queue:
            self.missing.append(self._key)
            raise MissingRecording(f"no recorded plan call left for {self._key}")
        record = self._queue.pop(0)
        self.calls += 1
        last_error = None
        # one recorded ask_json CALL is one line; its retry is the next line
        for attempt_record in [record, *self._same_call(record)]:
            parsed, why = llm.json_object(attempt_record.get("raw", ""))
            if why:
                last_error = why
            if parsed is not None:
                return parsed
        raise ValueError(f"model failed to produce valid JSON twice: {last_error}")

    def _same_call(self, record: dict) -> list:
        """The retry lines of the same `ask_json` call, taken off the queue.

        `ask_json` makes up to two model calls and the observer records each,
        so one `plan()` call can be two lines; they share the `call` index and
        differ in `json_attempt`."""
        same = []
        while self._queue and self._queue[0].get("call") == record.get("call"):
            same.append(self._queue.pop(0))
        return same


@contextlib.contextmanager
def replaying(replayer: PlanReplayer):
    """`llm.ask_json` replaced by the replayer for the length of the block.

    The NAME on the module, because that is how `nodes.plan` reaches it — the
    same seam the unit tests use to script the planner, and the reason none of
    this needed a line in nodes.py."""
    original = llm.ask_json
    llm.ask_json = replayer
    try:
        yield replayer
    finally:
        llm.ask_json = original
