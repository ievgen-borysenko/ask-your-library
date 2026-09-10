"""Runtime settings, all overridable through environment variables.

Defaults target the demo corpus built by scripts/ingest_demo_corpus.py and a
local Ollama. Point LIBRARY_DB_PATH at any LanceDB with the same table layout
(cards_<backend> / transcripts_<backend>) to run the agent over a private
library instead.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# Exported variables win over .env; .env (cwd or parents) makes `cp .env.example .env` work.
load_dotenv()

# --- storage ---------------------------------------------------------------
# Relative default resolves against the working directory (repo root under `uv run`).
DB_PATH = Path(os.environ.get("LIBRARY_DB_PATH", "data/lancedb"))

# --- embeddings ------------------------------------------------------------
# Backend selects both the embedder and the table suffix, so query and document
# vectors always come from the same model.
EMBED_BACKEND = os.environ.get("EMBED_BACKEND", "ollama")   # ollama | openrouter
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
OPENROUTER_EMBED_MODEL = os.environ.get("OPENROUTER_EMBED_MODEL", "openai/text-embedding-3-small")

TABLES = {
    "cards": f"cards_{EMBED_BACKEND}",              # distilled book cards (plot / characters / takeaways)
    "transcripts": f"transcripts_{EMBED_BACKEND}",  # full book text, chapter-aware chunks
}

# --- orchestrator LLM (OpenAI-compatible endpoint; OpenRouter by default) ---
# LLM_BACKEND=ollama runs every agent node on a local model through Ollama's
# OpenAI-compatible endpoint: no account, no key, no cost. The measured numbers
# in the README are for the OpenRouter default; a local model is a different
# system and is fingerprinted as such in every eval report.
def _env(name: str, default: str) -> str:
    """An empty or blank variable (a copied .env.example, an unset shell line)
    means the default, never an empty value."""
    value = os.environ.get(name, "")
    return value if value.strip() else default


LLM_BACKEND = _env("LLM_BACKEND", "openrouter")   # openrouter | ollama
if LLM_BACKEND not in ("openrouter", "ollama"):
    # A typo ("ollma") must not silently fall back to the hosted provider: with
    # a key present that would send the question and passages outside while
    # the user believes the run is local.
    raise ValueError(f"LLM_BACKEND must be 'openrouter' or 'ollama', got {LLM_BACKEND!r}")
OLLAMA_LLM_MODEL = _env("OLLAMA_LLM_MODEL", "qwen3.6")
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
    ORCHESTRATOR_MODEL = _env("ORCHESTRATOR_MODEL", "anthropic/claude-sonnet-4.6")
    LLM_BASE_URL = OPENROUTER_BASE_URL
LLM_NEEDS_KEY = LLM_BACKEND != "ollama"
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
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "2048"))

# What observe sees of each retrieved passage (ADR-012). SEARCH_HIT_CHARS caps a
# search hit (several per step); CHAPTER_HIT_CHARS caps a chapter read (one
# hit). The provenance check compares quotes against the same cut, so the cut
# is applied once, in act, and read from here everywhere else.
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

# --- loop budgets -------------------------------------------------------------
# The measured numbers in the README are for the defaults; a change here is a
# different system and shows up in the eval fingerprint.
MAX_STEPS = _positive_int("MAX_STEPS", "4", unit="steps")                 # search / chapter-read steps per question
MAX_EMPTY_STREAK = _positive_int("MAX_EMPTY_STREAK", "2", unit="steps")   # CRAG gate: stop after this many dry steps in a row
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
    value = int(os.environ.get(name, default))
    if value < 0:
        raise ValueError(f"{name} must be 0 or a positive number of seconds, got {value}")
    return value


LLM_TIMEOUT_S = _positive_int("LLM_TIMEOUT_S", "600" if LLM_BACKEND == "ollama" else "120", unit="seconds")
LLM_MAX_RETRIES = _non_negative_int("LLM_MAX_RETRIES", "2")
QUESTION_DEADLINE_S = _non_negative_int("QUESTION_DEADLINE_S", "300")

# Prices in USD per 1M tokens for the cost estimate; override when changing the model.
# A local model costs nothing per token; the cost lines then read $0.0000.
# OLLAMA_PRICE_* exist for people who want to book electricity; the OpenRouter
# prices in a copied .env are not applied to the local mode.
if LLM_BACKEND == "ollama":
    PRICE_IN_PER_MTOK = float(_env("OLLAMA_PRICE_IN_PER_MTOK", "0"))
    PRICE_OUT_PER_MTOK = float(_env("OLLAMA_PRICE_OUT_PER_MTOK", "0"))
else:
    PRICE_IN_PER_MTOK = float(_env("PRICE_IN_PER_MTOK", "3.0"))
    PRICE_OUT_PER_MTOK = float(_env("PRICE_OUT_PER_MTOK", "15.0"))

# --- UI language -----------------------------------------------------------
# "ua" is this project's code for Ukrainian (kept distinct from the UK country code).
SUPPORTED_LANGS = ("en", "ua")
DEFAULT_LANG = os.environ.get("ASK_LANG", "en")
if DEFAULT_LANG not in SUPPORTED_LANGS:
    DEFAULT_LANG = "en"
