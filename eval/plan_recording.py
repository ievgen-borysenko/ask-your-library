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


class SecretInRecording(RuntimeError):
    """Something token-shaped reached a line of a file that is meant to be
    committed. The recording is not finalised and the offending line is named."""


class RecordingIncomplete(RuntimeError):
    """A line of this recording could not be written — a full disk, a read-only
    directory, a descriptor that went away.

    The observer swallows its own exceptions on purpose: a recorder must never
    turn a paid run into a failed one. But the swallow left no state anywhere, so
    a recording that lost half its lines was finalised, named and committed as if
    it were complete. The failure is latched here instead, and the file does not
    get its final name."""


# --- what must never reach a committed file -----------------------------------
# A recording is committed, so the cost of a leak is a push and not a file on one
# machine. Two defences, both fail-closed: absolute paths of ANY platform are
# replaced (the repo/home substitution of the main harness only knows this
# machine's two prefixes, and a payload can carry /Volumes/backup/..., /tmp/...,
# a colleague's /Users/..., or a Windows drive), and anything token-shaped stops
# the recording from being finalised at all rather than being quietly masked —
# masking a secret still means one was there, and that is worth a person's
# attention.
# The lookbehind matters: `redact` has already turned this machine's home into
# `~` and its checkout into `<repo>`, and those two substitutions are the
# informative ones — `~/private/library/notes.txt` must stay readable as a path
# under the reader's home and not collapse to `~<path>`. So a run only counts as
# an absolute path when nothing precedes its leading slash.
ABSOLUTE_PATH_RE = re.compile(
    # A POSIX absolute path: a leading slash that begins something, followed by
    # two or more segments. Generic rather than a list of roots — the roots a
    # payload can carry are not enumerable, and /etc/hosts, /usr/local/bin/x and
    # /data/index are exactly the ones a list forgets.
    #
    # The lookbehind is what keeps URLs and the two informative stand-ins whole:
    # a slash preceded by a word character ("London/Paris"), by a colon or
    # another slash ("https://example.com/a/b" — both slashes of the scheme, and
    # the path after the host is preceded by a word character), by "~" or by ">"
    # ("~/private/notes.txt" and "<repo>/eval/golden/x.yaml", which `redact`
    # has already made readable) does not start an absolute path.
    r"(?<![\w~:>/])/[^\s\"'<>|/\\]+(?:/[^\s\"'<>|\\]*)+"
    # C:\Users\... and C:/Users/..., but not the "s:" inside "https://"
    r"|(?<!\w)[A-Za-z]:[\\/][^\s\"'<>|]*"
    # \\server\share\file
    r"|\\\\[^\s\"'<>|\\]+\\[^\s\"'<>|]*")

SECRET_PATTERNS = (
    ("an OpenRouter/OpenAI-style key", re.compile(r"sk-(?:or-)?[A-Za-z0-9._-]{8,}")),
    ("an Authorization header", re.compile(r"Bearer\s+[A-Za-z0-9._\-/+=]{8,}")),
    # header.payload.signature, base64url; the signature may be empty ("alg":"none")
    ("a JSON web token", re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]*")),
    ("a Slack token", re.compile(r"xox[abposr]-[A-Za-z0-9-]{8,}")),
    ("a GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}")),
    ("a Google API key", re.compile(r"AIza[A-Za-z0-9_-]{8,}")),
    ("an AWS access key id", re.compile(r"A[KS]IA[0-9A-Z]{8,}")),
    ("an api key assignment", re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S{16,}")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("a long value beside the word key/token/secret",
     re.compile(r"(?i)(?:key|token|secret)[^A-Za-z0-9]{0,4}[A-Za-z0-9+/=_-]{32,}")),
)


def environment_secrets() -> set:
    """The literal values of every *_KEY / *_TOKEN / *_SECRET in this process.

    A pattern catches a shape; this catches the actual credential of the machine
    making the recording, whatever shape it has. Short values are skipped: a
    `..._KEY=1` would otherwise match every line."""
    names = ("_KEY", "_TOKEN", "_SECRET", "_PASSWORD")
    return {value for name, value in os.environ.items()
            if name.upper().endswith(names) and len(value.strip()) >= 8}


def exact_cost(tokens_in: int, tokens_out: int) -> float:
    """What those tokens cost at the configured rates, UNROUNDED.

    `llm._cost` rounds to four decimals, which is right for a report line and
    wrong for a record: a planner call is often under $0.0001 and would be
    written down as zero, and a run's worth of such zeros is a free run that
    was not. Rounding is left to whoever displays it."""
    from ask_your_library.config import PRICE_IN_PER_MTOK, PRICE_OUT_PER_MTOK
    return (tokens_in * PRICE_IN_PER_MTOK + tokens_out * PRICE_OUT_PER_MTOK) / 1_000_000


def sanitise(text: str, redact=lambda t: t) -> str:
    """`redact` first — it names the repository and the home directory, which
    are the informative substitutions — then every remaining absolute path,
    whatever platform wrote it."""
    return ABSOLUTE_PATH_RE.sub("<path>", redact(text))


def secrets_in(text: str, literals=()) -> list:
    """Why this text must not be written, or []."""
    found = [what for what, pattern in SECRET_PATTERNS if pattern.search(text)]
    if any(literal in text for literal in literals):
        found.append("the literal value of a *_KEY / *_TOKEN / *_SECRET in this environment")
    return found


class MissingRecording(RuntimeError):
    """This item was never recorded; there is nothing to replay for it."""


def sha12(text: str) -> str:
    """The short checksum this project uses everywhere: sha256, first 12 hex."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def prompt_hash(rules: str = PLAN_RULES) -> str:
    """The identity of the planner's prompt. A recording made under a different
    one answers a question that is no longer being asked."""
    return sha12(rules)


def retry_hash() -> str:
    """The identity of the RETRY wording. The second payload of a call is the
    first plus these words, so a change to them changes what the model was
    asked on the retry exactly as a change to PLAN_RULES changes the first
    ask — and it would otherwise be invisible, because the prompt hash does not
    cover it."""
    return sha12(llm.RETRY_RULE)


def model_slug(model: str) -> str:
    """`anthropic/claude-sonnet-4.6` as a file-name component. A model id
    carries a slash and the file name has to survive it; nothing else is
    changed, so the slug is still readable as the model."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model).strip("-") or "unknown"


def recording_name(golden_name: str, golden_sha12: str, model: str,
                   subset: tuple | None = None) -> str:
    """`<golden-stem>.<golden-sha12>.<model>.jsonl`, or
    `...<model>.subset-<k>of<n>.jsonl` when only some ids were run.

    The checksum is IN THE NAME so that two recordings of the same set under
    different golden files cannot overwrite each other, and so a stale one is
    visible in a directory listing and not only on opening it. The subset marker
    is there for the same reason and a sharper one: a run of three ids records
    three items, and writing that over the complete recording of a paid run
    would destroy the artefact and leave a file whose name still claims the
    whole set."""
    part = f".subset-{subset[0]}of{subset[1]}" if subset else ""
    return f"{Path(golden_name).stem}.{golden_sha12}.{model_slug(model)}{part}.jsonl"


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
            "retry_rule_sha256_12": retry_hash(),
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
        recorded_retry = self.header.get("retry_rule_sha256_12", "")
        if recorded_retry != retry_hash():
            reasons.append(f"retry wording checksum: recording has {recorded_retry or '?'}, "
                           f"this tree has {retry_hash()} — the SECOND payload of a call is the "
                           "first plus those words, so a recorded retry answers a different ask")
        return reasons

    def subset(self) -> str:
        """"" for a recording of a whole golden set; a sentence for one that
        holds only some of its ids, so a report cannot present a partial replay
        as a run over the set."""
        if not self.header.get("subset"):
            return ""
        return (f"a SUBSET recording: {self.header.get('subset_items', '?')} of "
                f"{self.header.get('golden_items', '?')} items of "
                f"{self.header.get('golden_name', '?')} were recorded")


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
        if not isinstance(record.get("call_index"), int):
            raise StaleRecording(f"{path.name}: line {number} carries no call_index; the order of "
                                 "the calls of one item is data, not a property of the file")
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

    def __init__(self, path: Path, facts: dict, redact=lambda text: text, knobs: dict | None = None,
                 header: dict | None = None):
        self.path = Path(path)
        self.partial = self.path.with_suffix(self.path.suffix + ".partial")
        self.facts = facts
        self.redact = redact
        self.knobs = knobs or {}
        self.header = header or {}
        self.lines = 0
        self.refused: list = []         # lines a secret kept out of the file
        self.failure = None             # (line number, reason) of the first write that failed
        self._literals = environment_secrets()
        self._file = None
        self._previous_observer = None
        self._current = None            # (id, attempt) or None
        self._call_index = 0
        self._usage_mark = None

    # -- the file -----------------------------------------------------------
    def __enter__(self) -> "PlanRecorder":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.partial.open("w", encoding="utf-8")
        self._write(header_record(self.facts, **self.knobs, **self.header))
        self._previous_observer = llm.JSON_CALL_OBSERVER
        llm.JSON_CALL_OBSERVER = self._observe
        return self

    def __exit__(self, *exc) -> bool:
        self.close(failed=exc[0] is not None)
        return False

    def close(self, failed: bool = False) -> None:
        """Disarm, close the file, and give it its final name — or refuse to,
        and say why.

        Idempotent, and called twice on purpose: the harness calls it where it
        can put the refusal into the report it is still writing, and the context
        manager calls it again on the way out so a crash still disarms the
        observer."""
        if self._file is None:
            return
        llm.JSON_CALL_OBSERVER = self._previous_observer
        self._file.close()
        self._file = None
        if failed:
            # A crash leaves the .partial where it is: the calls it holds were
            # paid for, and losing them to a failed last item would be the
            # expensive half of this change undone.
            return
        if self.refused:
            # Fail closed, and loudly. The lines never reached the file, so
            # nothing secret is on disk — but a recording that had one in it is
            # not a file to commit without a person reading why, so it is not
            # given its final name either.
            raise SecretInRecording(
                f"{len(self.refused)} line(s) of this recording held something token-shaped and "
                f"were not written; the recording was NOT finalised (it stays at "
                f"{self.partial.name}). "
                + "; ".join(f"line {number} ({item}): {', '.join(why)}"
                            for number, item, why in self.refused))
        if self.failure is not None:
            number, reason = self.failure
            raise RecordingIncomplete(
                f"line {number} of this recording could not be written ({reason}); it is short by "
                f"at least one call and was NOT finalised (it stays at {self.partial.name})")
        os.replace(self.partial, self.path)

    def _write(self, record: dict) -> None:
        try:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()      # a long paid run must not hold its record in a buffer
        except Exception as error:
            # Latched, then re-raised into the observer, which logs and swallows
            # it so the paid run goes on. The latch is the part that matters:
            # without it the run ends with a short file wearing the name of a
            # complete one.
            if self.failure is None:
                self.failure = (self.lines + 1, f"{type(error).__name__}: {error}")
            raise
        self.lines += 1

    # -- what the calls belong to -------------------------------------------
    @contextlib.contextmanager
    def item(self, item_id: str, attempt: int = 1):
        """The next plan calls belong to this golden id and this attempt."""
        self._current = (item_id, attempt)
        self._call_index = 0
        # NOT a reading of the accumulator: see _spent. The block opens BEFORE
        # run_one resets it, so a mark taken here would be the previous item's
        # totals and every delta from the second item on would be negative.
        self._usage_mark = None
        try:
            yield self
        finally:
            self._current = None

    @staticmethod
    def _usage() -> tuple:
        """The PLANNER's own running totals, not the run's.

        `llm_invoke` accounts per node role, and the plan calls of one question
        are separated by observe and reflect calls, so a difference of the
        WHOLE-run counters would charge a planner call with whatever the loop
        spent between it and the previous one. Tokens only: the cost is computed
        from them below, because the snapshot's own cost is already rounded to
        four decimals and a difference of two rounded numbers is a rounding
        error twice over — and a local call, priced at zero, is exactly the
        case where that shows."""
        role = llm.usage_snapshot().get("by_role", {}).get(PLAN_ROLE) or {}
        return (role.get("calls", 0), role.get("input_tokens", 0), role.get("output_tokens", 0))

    def _spent(self) -> dict:
        """What THIS call cost, as the difference between two readings of the
        run accumulator. The accumulator is per question (the harness resets it
        in `run_one`), so a difference is the only honest per-call figure
        available without a second accounting path.

        The FIRST reading of an item is taken at its first observed call, not
        when the item block opens, and it is zero rather than a snapshot: the
        harness enters the block and only then calls `run_one`, which resets the
        accumulator — so a snapshot taken at the block would be the PREVIOUS
        item's totals, and from the second item on every recorded call would
        carry a negative cost and negative tokens. After the reset the
        accumulator holds this item's spend only, which at its first call is
        that call's."""
        now = self._usage()
        before, self._usage_mark = self._usage_mark or (0, 0, 0), now
        calls, tokens_in, tokens_out = (n - b for n, b in zip(now, before))
        return {"cost_usd": round(exact_cost(tokens_in, tokens_out), 10),
                "llm_calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out}

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
        clean = lambda text: sanitise(text or "", self.redact)      # noqa: E731
        record = {
            "schema_version": SCHEMA_VERSION, "kind": "call",
            "id": item_id, "attempt": attempt, "call_index": self._call_index,
            "role": PLAN_ROLE, "json_attempt": json_attempt,
            # the prompt is identified, never copied: it is in prompts.py, and a
            # recording that carried it would go stale by being read
            "system_sha256_12": sha12(call.get("system", "")),
            "user": clean(call.get("user")),
            "raw": clean(call.get("raw")),
            "error": clean(call.get("error")),
            "model": self.facts.get("model", ""), "backend": self.facts.get("backend", ""),
            **self.knobs,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **self._spent(),
        }
        # The last gate before a committed file: a token-shaped value is not
        # masked and written, it is refused. Masking would leave a recording
        # that looks clean while a credential really did pass through, which is
        # the one thing nobody would go back and check.
        why = secrets_in(json.dumps(record, ensure_ascii=False), self._literals)
        if why:
            self.refused.append((self.lines + 1, f"{item_id} call {self._call_index}", why))
            return
        self._write(record)


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

    Faithful to `ask_json`, not to its happy path. The recorded lines of an item
    are grouped by `call_index` — one group is one `ask_json` call, its retry
    beside it — and inside a group each raw reply is parsed by `llm.json_object`,
    the very function that parsed it live. So a reply that was malformed twice
    raises the same `ValueError`, a call that timed out raises the same
    `CallTimeout`, and `plan()` takes the branch it took on the paid run.

    ONE call per item is replayed, and that is a limit rather than an oversight:
    a second `plan()` of the same question only happens after a clarify, and it
    is a function of the graph state at that moment — the evidence collected,
    the candidates offered, the reader's reply — which the observer never saw
    and the recording therefore does not hold. Replaying it would mean inventing
    that state. The recorded-versus-replayed count is reported instead, and the
    harness makes an unreplayed call a non-zero exit."""

    def __init__(self, recording: Recording, redact=lambda text: text):
        self.recording = recording
        self.redact = redact
        self.calls = 0
        self.missing: list = []
        self.drift: dict = {}          # (id, attempt) -> [reason, ...]
        self.accounting: dict = {}     # (id, attempt) -> {"recorded": n, "replayed": k}
        self._groups = None
        self._key = None

    @staticmethod
    def _grouped(records: list) -> list:
        """The lines of one item as `ask_json` calls: a group per `call_index`,
        in the order they were made."""
        groups: dict = {}
        for record in records:
            groups.setdefault(record.get("call_index", 1), []).append(record)
        return [groups[index] for index in sorted(groups)]

    @contextlib.contextmanager
    def item(self, item_id: str, attempt: int = 1):
        key = (item_id, attempt)
        self._key = key
        self._groups = self._grouped(self.recording.calls.get(key, []))
        recorded = len(self._groups)
        try:
            yield self
        finally:
            self.accounting[key] = {"recorded": recorded, "replayed": recorded - len(self._groups)}
            self._groups = self._key = None

    def _check_request(self, system: str, user: str, record: dict, order: int) -> None:
        """Is this the call that was recorded, or only the call in its place?

        The reply is replayed whatever the question was, so a change to how the
        payload is BUILT — a new data block, a different history window, a
        rewording of the clarification note, a rewording of the RETRY — would be
        measured against a reply the planner gave to the old payload, and the
        run would look clean. That is the one silent failure of a replay, so the
        request is compared as well as the response, on EVERY attempt of a call:
        the user payload verbatim (sanitised the way it was written, including
        the retry payload, which is rebuilt by `llm.retry_payload` rather than
        by a copy of its words), the system prompt by its hash, and the order of
        the attempts.

        Recorded, not raised: the item still replays, and the harness decides
        what a drifted item does to its exit code."""
        reasons = []
        if sanitise(user, self.redact) != record.get("user", ""):
            reasons.append(f"attempt {order}: the payload plan() builds now is not the one that "
                           "was recorded")
        recorded_system = record.get("system_sha256_12", "")
        if recorded_system and sha12(system) != recorded_system:
            reasons.append(f"attempt {order}: system prompt {sha12(system)}, "
                           f"recorded {recorded_system}")
        if record.get("json_attempt") != order:
            reasons.append(f"attempt {order}: recorded out of order as json_attempt "
                           f"{record.get('json_attempt')!r}")
        if reasons:
            self.drift.setdefault(self._key, []).extend(reasons)

    def __call__(self, system: str, user: str, role: str) -> dict:
        if role != PLAN_ROLE:
            # Only the planner is recorded. A replay that silently answered
            # another role would be inventing evidence.
            raise MissingRecording(f"only {PLAN_ROLE!r} calls are recorded; this run asked for "
                                   f"{role!r}")
        if not self._groups:
            self.missing.append(self._key)
            raise MissingRecording(f"no recorded plan call left for {self._key}")
        group = self._groups.pop(0)
        self.calls += 1
        attempt_user = user
        last_error = None
        for order, record in enumerate(group, start=1):
            self._check_request(system, attempt_user, record, order)
            timeout = timeout_of(record)
            if timeout is not None:
                # The call never came back on the paid run either; `plan()` has
                # a branch for exactly this and must take it here too.
                raise timeout
            parsed, why = llm.json_object(record.get("raw", ""))
            if why:
                last_error = why
            if parsed is not None:
                return parsed
            attempt_user = llm.retry_payload(user, last_error)
        raise ValueError(f"model failed to produce valid JSON twice: {last_error}")


# A recorded line whose call never returned: `ask_json` notes the exception and
# re-raises it, so the record carries "<ExceptionName>: <message>" and an empty
# reply. Only a timeout is reconstructed — it is the one the nodes catch by name
# and the one a long local run really produces; any other failure is replayed as
# what it was, an unusable reply.
TIMEOUT_NAMES = tuple(sorted({cls.__name__ for cls in llm.CallTimeout}))


def timeout_of(record: dict):
    """The exception to raise for this recorded line, or None."""
    error = record.get("error", "") or ""
    if record.get("raw"):
        return None
    name, _, message = error.partition(": ")
    if name in TIMEOUT_NAMES:
        # the first member of llm.CallTimeout that carries this name, so a node
        # catching `llm.CallTimeout` catches this exactly as it did live
        cls = next(c for c in llm.CallTimeout if c.__name__ == name)
        return cls(message or "the call ran out of time")
    return None


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
