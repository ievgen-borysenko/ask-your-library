"""Runtime settings, all overridable through environment variables.

Defaults target the demo corpus built by scripts/ingest_demo_corpus.py and a
local Ollama. Point LIBRARY_DB_PATH at any LanceDB with the same table layout
(cards_<backend> / transcripts_<backend>) to run the agent over a private
library instead.
"""
import os
import shlex
import sys
from pathlib import Path
from typing import NamedTuple

from dotenv import load_dotenv

# Exported variables win over .env; .env (cwd or parents) makes `cp .env.example .env` work.
load_dotenv()

# --- storage ---------------------------------------------------------------
# The reader's own folder, OUTSIDE any checkout (ADR-026): the home of what this
# machine builds for the reader. The index defaults to $AYL_HOME/index (below),
# the scratchpads to $AYL_HOME/scratch and the web chat's state to $AYL_HOME/ui
# (`ask_your_library.home`), the engineer's shelf's local cards live in
# $AYL_HOME/cards/tech, and the private shelf of the reader's own books will.
# `ask_your_library.home` refuses to write what may never be shared there when
# it resolves inside a git work tree — .gitignore is not a boundary.
# Blank or whitespace-only means the default, as for LIBRARY_DB_PATH below: a
# folder named " " in the working directory is nobody's home.
_ayl_home = os.environ.get("AYL_HOME") or ""
AYL_HOME = Path(_ayl_home if _ayl_home.strip() else "~/AskYourLibrary").expanduser()

# --- embeddings ------------------------------------------------------------
# Backend selects both the embedder and the table suffix, so query and document
# vectors always come from the same model.
EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "ollama")   # ollama | openrouter
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
OPENROUTER_EMBED_MODEL = os.environ.get("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small")

def tables_for(backend: str) -> dict[str, str]:
    """The two table names of an index built by `backend`.

    A function and not only the pair below, because a command may be pointed at
    ANOTHER index than the configured one — `--db <dir> --backend <name>` — and
    the checks over it must ask for that index's tables, not this process's."""
    return {
        "cards": f"cards_{backend}",              # distilled book cards (plot / characters / takeaways)
        "transcripts": f"transcripts_{backend}",  # full book text, chapter-aware chunks
    }


TABLES = tables_for(EMBED_BACKEND)

# --- where the index is (ADR-026) ---------------------------------------------
# The index used to default to `data/lancedb`, relative, i.e. wherever the
# command was typed. Its default is now $AYL_HOME/index. An index already built
# at the old place is not moved, copied or deleted by anything here: it is
# READ where it is, with one line saying so, until LEGACY_DB_SUNSET, when that
# clause becomes an error naming the same two commands.
LEGACY_DB_PATH = Path("data") / "lancedb"
LEGACY_DB_SUNSET = "0.5.0"


class DbPathChoice(NamedTuple):
    """Which index a process opens when no `--db` names one, and why.

    `clause` is the rule that decided it: 1 `LIBRARY_DB_PATH` is set, 2 an index
    built before the move is in the working directory's `data/lancedb`, 3 the
    default under `AYL_HOME`. `reason` is the sentence `ayl doctor` prints."""
    path: Path
    clause: int
    reason: str


def resolve_db_path(named: str | None = None, cwd: Path | None = None,
                    backend: str | None = None, home: Path | None = None) -> DbPathChoice:
    """The three-clause rule, in order. Pure: it reads, and prints and creates
    nothing, so it can run at import — `--help` and `--version` included.

    1. `LIBRARY_DB_PATH` set (and not blank) -> that path, always, as written:
       no `AYL_HOME`, no git-work-tree check, no notice. The developer's and
       CI's escape hatch, and every test's (tests/conftest.py pins it).
    2. Unset, and `<cwd>/data/lancedb` holds a `transcripts_<backend>` table ->
       that index, where it is. A `data/lancedb` without that table is not an
       index this configuration could answer from, and does not count.
    3. Otherwise -> `$AYL_HOME/index`, absolute, created by the first write.

    A blank `LIBRARY_DB_PATH` (a copied `.env` line with nothing after the
    `=`) is unset: `Path("")` is the working directory itself, which is no
    index anybody meant.

    `named` is the variable's value; None reads it from the environment. The
    others default to the working directory, `EMBED_BACKEND` and `AYL_HOME`."""
    if named is None:
        named = os.environ.get("LIBRARY_DB_PATH") or ""
    if named.strip():
        return DbPathChoice(Path(named), 1, "LIBRARY_DB_PATH is set, and an explicit path is "
                                            "always obeyed")
    table = tables_for(EMBED_BACKEND if backend is None else backend)["transcripts"]
    legacy = (Path.cwd() if cwd is None else Path(cwd)).absolute() / LEGACY_DB_PATH
    if (legacy / f"{table}.lance").is_dir():
        return DbPathChoice(legacy, 2, (
            f"LIBRARY_DB_PATH is unset and the working directory holds an index at the old "
            f"default, {LEGACY_DB_PATH} (it has a {table} table): it is read where it is "
            f"until {LEGACY_DB_SUNSET}, and nothing is moved"))
    default = Path(AYL_HOME if home is None else home).expanduser().resolve() / "index"
    why = (f"{LEGACY_DB_PATH} here has no {table} table" if legacy.is_dir()
           else f"there is no {LEGACY_DB_PATH} in the working directory")
    return DbPathChoice(default, 3, f"LIBRARY_DB_PATH is unset and {why}, so the default "
                                    f"under AYL_HOME")


def legacy_db_notice(choice: DbPathChoice, home: Path | None = None) -> str:
    """The one line a clause-2 process prints: the new default, the path being
    read, and the move, as commands. The move names both targets, the index
    and the chat database, so it lands in the same place whichever of the two
    is still at its old default — and it says to move the checkout's chat.db
    away too, because while that file is there the web chat keeps reading it
    and never the restored copy (`ui.launcher.chainlit_dir`).

    Every path that lands in a command or an assignment is shell-quoted: the
    reader copies these lines into a terminal, and an `AYL_HOME` with a space
    in it would split the argument, one with a `$` or a backtick would run."""
    base = Path(AYL_HOME if home is None else home).expanduser().resolve()
    index, chat = shlex.quote(str(base / "index")), shlex.quote(str(base / "ui" / ".chainlit" /
                                                                  "chat.db"))
    return (f"note: reading the index at {choice.path}, the old default. The default is now "
            f"{base / 'index'} ($AYL_HOME/index); the old place is read until "
            f"{LEGACY_DB_SUNSET}, when it becomes an error. Nothing is moved for you. To move "
            f"it: `ayl backup <dir>`, then `ayl restore <dir>/<timestamp> --db {index} "
            f"--chat-db {chat}`, then move "
            f"{LEGACY_DB_PATH} out of this directory, and the checkout's .chainlit/chat.db "
            f"(with its -wal/-shm) if there is one; or set "
            f"LIBRARY_DB_PATH={shlex.quote(str(choice.path))} to keep the index where it is.")


DB_CHOICE = resolve_db_path()
# The name every module imports. Decided once, at import, like every other knob
# here; what is NOT done at import is saying anything about it (`confirm_db_path`).
DB_PATH = DB_CHOICE.path

_db_confirmed = False


def confirm_db_path() -> Path:
    """Called where a command is about to use the configured index — never at
    import, so `--help` and `--version` stay silent. Once per process:

    - clause 2 prints the notice (stderr, once);
    - clause 3 checks `DB_PATH` itself — the path resolved at import, the one
      that will be opened, not `AYL_HOME` read again — and refuses it inside a
      git work tree, naming LIBRARY_DB_PATH as the way out (RuntimeError).
      The index holds the full text of the books it was built from, and the
      reader's own books are what may never be committed.

    Clause 1 is obeyed without a word. Returns `DB_PATH`."""
    global _db_confirmed
    if _db_confirmed:
        return DB_PATH
    if DB_CHOICE.clause == 2:
        print(legacy_db_notice(DB_CHOICE), file=sys.stderr)
    elif DB_CHOICE.clause == 3:
        from .home import refuse_in_work_tree      # home imports this module
        refuse_in_work_tree(DB_PATH, "index")
    _db_confirmed = True
    return DB_PATH

# --- orchestrator LLM (OpenAI-compatible endpoint; local Ollama by default) --
# The shipped default is LLM_BACKEND=ollama: every agent node runs on a local
# model through Ollama's OpenAI-compatible endpoint, so a fresh clone answers
# with no account, no key and nothing to pay. LLM_BACKEND=openrouter sends the
# question and the retrieved passages to OpenRouter instead and needs a key.
# The measured numbers in docs/eval-results/ were produced in that hosted
# configuration; a local model is a different system, and every eval report
# names the backend it ran with in its fingerprint.
def _env(name: str, default: str) -> str:
    """An empty or blank variable (a copied .env.example, an unset shell line)
    means the default, never an empty value."""
    value = os.environ.get(name, "")
    return value if value.strip() else default


LLM_BACKEND = _env("LLM_BACKEND", "ollama")   # ollama | openrouter
if LLM_BACKEND not in ("openrouter", "ollama"):
    # A typo ("ollma") must not silently fall back to either backend. Falling
    # back to the hosted one would send the question and passages outside while
    # the user believes the run is local; falling back to the local one would
    # leave a run that was meant to be hosted asking Ollama for a model nobody
    # pulled. The value is named in the error, so the typo is visible.
    raise ValueError(f"LLM_BACKEND must be 'openrouter' or 'ollama', got {LLM_BACKEND!r}")
# qwen2.5:14b (9.0 GB) over qwen2.5:7b (4.7 GB): the local mini-eval in
# docs/eval-results/2026-09-10-local-models.md is where the two were compared,
# and 14b answers a multi-part question whole where 7b answers one half of it.
OLLAMA_LLM_MODEL = _env("OLLAMA_LLM_MODEL", "qwen2.5:14b")
# OPENROUTER_BASE_URL stays the OpenRouter endpoint in both modes: the
# embeddings backend (EMBED_BACKEND=openrouter) uses it independently of where
# the answering model runs. The answering model's endpoint is LLM_BASE_URL.
OPENROUTER_BASE_URL = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
if LLM_BACKEND == "ollama":
    # The local mode is configured by the OLLAMA_* variables only (model:
    # OLLAMA_LLM_MODEL, endpoint: OLLAMA_URL). ORCHESTRATOR_MODEL and the
    # OpenRouter prices in a .env copied from the example are OpenRouter
    # settings and are not applied here, so a copied .env cannot route the
    # local mode to the hosted provider.
    ORCHESTRATOR_MODEL = OLLAMA_LLM_MODEL
    LLM_BASE_URL = f"{OLLAMA_URL.rstrip('/')}/v1"
else:
    ORCHESTRATOR_MODEL = _env("ORCHESTRATOR_MODEL", "deepseek/deepseek-v4-flash-0731")
    LLM_BASE_URL = OPENROUTER_BASE_URL
LLM_NEEDS_KEY = LLM_BACKEND != "ollama"
# Thinking on the hosted backend. `off` sends OpenRouter's
# `reasoning: {"enabled": false}`, which turns a hybrid model's thinking off;
# the default hosted model was measured that way, and the same family with its
# thinking on answered about three times slower (2.8x on the core set,
# docs/eval-results/2026-09-19-hosted-default-quality.md). `provider` sends nothing and
# leaves the model's own default. Not applied to the local backend, which has
# its own switch in llm.py. Anything else refuses to start.
LLM_REASONING = _env("LLM_REASONING", "off")
if LLM_REASONING not in ("off", "provider"):
    raise ValueError(f"LLM_REASONING must be 'off' or 'provider', got {LLM_REASONING!r}")
# The key is also needed when the embeddings come from OpenRouter, whatever
# runs the answering model; preflight and the UI gate check this one.
OPENROUTER_NEEDS_KEY = LLM_NEEDS_KEY or EMBED_BACKEND == "openrouter"
# Opt-in fallback: a file scanned for OPENROUTER_API_KEY=... ONLY when this
# variable is set — the app must not silently read dotfiles by default.
_env_file = os.environ.get("OPENROUTER_ENV_FILE", "")
OPENROUTER_ENV_FILE = Path(_env_file).expanduser() if _env_file else None

# Hard cap on output tokens per call. Every node returns short JSON or a
# short answer; without a cap the provider pre-authorizes its model maximum
# (65k tokens for the default model), which is an unbounded cost ceiling and
# fails with 402 on a low balance.
MAX_OUTPUT_TOKENS = int(_env("MAX_OUTPUT_TOKENS", "2048"))

# What observe sees of each retrieved passage (ADR-025, superseding ADR-012).
# SEARCH_HIT_CHARS caps a search hit (several per step); CHAPTER_HIT_CHARS caps
# a chapter read (one hit). The provenance check compares quotes against the
# same cut, so the cut is applied once, in act, and read from here everywhere
# else.
#
# SEARCH_HIT_CHARS is no longer a knob over a chunk it cannot reach: the
# chunker packs transcript chunks to 2,400 characters
# (`ingest.chunking.TRANSCRIPT_TARGET_CHARS`), so a hit arrives whole and the
# window is the chunk. RAISING this value now buys nothing — there is no chunk
# tail behind it to reveal — and LOWERING it cuts real text out of a chunk the
# retriever ranked whole. Either way the pair is one decision, and the index
# records which chunker built it (`ingest.chunking.CHUNKER_VERSION`).
def _positive_int(name: str, default: str, unit: str = "characters", at_most: int | None = None,
                  why_at_most: str = "") -> int:
    value = int(_env(name, default))      # a blank line in a copied .env means the default
    if value <= 0:
        raise ValueError(f"{name} must be a positive number of {unit}, got {value}")
    if at_most is not None and value > at_most:
        raise ValueError(f"{name} must be at most {at_most} {unit}, got {value}{why_at_most}")
    return value


SEARCH_HIT_CHARS = _positive_int("SEARCH_HIT_CHARS", "2500")     # 1,200 until 0.1.0; measured 05.09, see CHANGELOG
CHAPTER_HIT_CHARS = _positive_int("CHAPTER_HIT_CHARS", "12000")
# How much of a chapter a read may CHOOSE its window from, when the request
# says what it is looking for (ADR-025). The chapter is read this far, the
# window is cut around the best lexical match inside it, and what the model
# sees is still CHAPTER_HIT_CHARS — so this is a scan budget, not an
# observation budget: no more text reaches a prompt because of it. 120,000
# characters covers 1,242 of the 1,245 sections of the demo corpus whole
# (median 14,804, the longest 245,244; measured 24.09, after #80 and #82 moved
# the boundaries and Don Quixote's front matter stopped being a section). A
# read that names no query never scans: it takes the head, as it always did.
CHAPTER_SCAN_CHARS = _positive_int("CHAPTER_SCAN_CHARS", "120000")
if CHAPTER_SCAN_CHARS < CHAPTER_HIT_CHARS:
    # A scan narrower than the window is not a window at all: it would cut the
    # chapter before the match could be found in it, and then hand the cut text
    # on as if it had been chosen. Refused with both numbers named, like every
    # other misconfiguration here.
    raise ValueError(f"CHAPTER_SCAN_CHARS ({CHAPTER_SCAN_CHARS}) must be at least "
                     f"CHAPTER_HIT_CHARS ({CHAPTER_HIT_CHARS}): a window cannot be chosen "
                     f"from less text than it shows")

# --- loop budgets -------------------------------------------------------------
# The measured numbers in the README are for the defaults; a change here is a
# different system and shows up in the eval fingerprint.
MAX_STEPS = _positive_int("MAX_STEPS", "4", unit="steps")                 # search / chapter-read steps per question
MAX_EMPTY_STREAK = _positive_int("MAX_EMPTY_STREAK", "2", unit="steps")   # CRAG gate: stop after this many dry steps in a row
# The bound on a model that retrieves passages and never quotes them (#29). A
# step whose every quote the provenance gate refused is still not a dry step —
# the passages were there — but a run of them proves the model cannot copy, not
# that the library has more to give, and each one costs a search plus two model
# calls. After this many in a row such a step counts as dry, so the CRAG gate
# above can end the run instead of spending the whole step budget on it.
MAX_DROPPED_STREAK = _positive_int("MAX_DROPPED_STREAK", "2", unit="steps")
# A list the reader can actually read (hits_log may name more books). At most 5: the clarify
# resolver understands the ordinals 1..5 (first..fifth, перший..п'ятий); a sixth candidate
# could be shown but never chosen by number.
MAX_CLARIFY_CANDIDATES = _positive_int("MAX_CLARIFY_CANDIDATES", "5", unit="books", at_most=5,
                                       why_at_most=" (the clarify reply resolver knows the ordinals 1..5)")

# --- time budgets ---------------------------------------------------------------
# MAX_STEPS is a step budget, not a time budget. One model call is bounded by the
# client: LLM_TIMEOUT_S per attempt (read/write; the connect timeout stays the
# SDK's 5 s), LLM_MAX_RETRIES more attempts on a timeout or a transient provider
# error, plus a backoff between attempts (0.5 s doubling to 8 s, or the server's
# own Retry-After up to 2 min). The SDK's own defaults were 600 s and 2 retries;
# this tightens the per-attempt time and makes the retry count explicit. The
# retries are llm.llm_invoke's loop, not the SDK's, so a call the deadline caps
# is re-bounded before each attempt instead of reusing the first one's number
# (see llm.call_timeout_s). A node that asks for JSON may call twice (one retry
# on malformed JSON), so a step in flight can take about twice one call's bound.
# The question is bounded by QUESTION_DEADLINE_S, checked by the loop before each
# next decision (a step in flight finishes; the answer is then written from what
# was found, with an honest stop reason). 0 = no deadline. Time spent waiting for
# the reader's clarify reply does not count. A local model is slower and may load
# cold, hence the longer per-call timeout in LLM_BACKEND=ollama.
def _non_negative_int(name: str, default: str) -> int:
    value = int(_env(name, default))      # a blank line in a copied .env means the default
    if value < 0:
        raise ValueError(f"{name} must be 0 or a positive number of seconds, got {value}")
    return value


LLM_TIMEOUT_S = _positive_int("LLM_TIMEOUT_S", "600" if LLM_BACKEND == "ollama" else "120", unit="seconds")
LLM_MAX_RETRIES = _non_negative_int("LLM_MAX_RETRIES", "2")
# Per backend, like LLM_TIMEOUT_S and for the same reason: 300 s is a hosted
# model's whole wall clock for four steps, and a local model that loads cold can
# spend it inside the first one. It used to be one flat 300 s, which no
# recommended path ever ran with — .env.example and scripts/install-mac.sh both
# write 1200 for the local mode, and a value in a copied .env wins over this
# default — so the only configuration that got 300 was the bare clone-and-ask
# path this project advertises as equivalent. A flat 300 also capped the local
# read timeout at what was left of it and never the 600 s LLM_TIMEOUT_S names.
QUESTION_DEADLINE_S = _non_negative_int("QUESTION_DEADLINE_S", "1200" if LLM_BACKEND == "ollama" else "300")

# Prices in USD per 1M tokens for the cost estimate; override when changing the model.
# A local model costs nothing per token, so the default configuration's cost
# lines read $0.0000 — that is the arithmetic, not a rounded-down estimate.
# OLLAMA_PRICE_* exist for people who want to book electricity; the OpenRouter
# prices in a copied .env are not applied to the local mode.
if LLM_BACKEND == "ollama":
    PRICE_IN_PER_MTOK = float(_env("OLLAMA_PRICE_IN_PER_MTOK", "0"))
    PRICE_OUT_PER_MTOK = float(_env("OLLAMA_PRICE_OUT_PER_MTOK", "0"))
else:
    PRICE_IN_PER_MTOK = float(_env("PRICE_IN_PER_MTOK", "0.06"))
    PRICE_OUT_PER_MTOK = float(_env("PRICE_OUT_PER_MTOK", "0.12"))

# --- UI language -----------------------------------------------------------
# "ua" is this project's code for Ukrainian (kept distinct from the UK country code).
SUPPORTED_LANGS = ("en", "ua")
DEFAULT_LANG = os.environ.get("ASK_LANG", "en")
if DEFAULT_LANG not in SUPPORTED_LANGS:
    DEFAULT_LANG = "en"
