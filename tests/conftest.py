"""What every test in this directory runs against: a fixed environment, clean
run state, and one way to start a fresh interpreter.

The suite used to inherit whatever the developer's shell (or a repo-root .env,
which `config.load_dotenv()` reads at import) happened to hold. `ASK_LANG=ua`
failed eight tests, and a LangSmith key made the end-to-end tests upload trace
batches while staying green, because the tracing client swallows the connection
error. Both are the same defect: `config` resolves every knob once, at import
time, so a variable set before the first import of the package silently decides
what the tests measure.

So the knobs are pinned here, at module level, BEFORE anything imports the
package (pytest imports conftest first). `setdefault`, not assignment: CI runs
the whole suite twice with an exported LLM_BACKEND, and that matrix has to keep
working. `load_dotenv` never overrides an existing variable, so pinning them
also neutralises a .env in the repository root.
"""
import os

# --- the environment, before the first package import -----------------------
# Every knob config.py reads, with the default documented in .env.example, plus
# the strict-hit-id flag provenance.py reads. A test that describes a different
# value sets it itself (monkeypatch, or a fresh interpreter through run_fresh).
DEFAULTS = {
    "ASK_LANG": "en",
    "LLM_BACKEND": "openrouter",
    "EMBED_BACKEND": "ollama",
    "OLLAMA_URL": "http://localhost:11434",
    "OLLAMA_EMBED_MODEL": "bge-m3",
    "OLLAMA_LLM_MODEL": "qwen3.6",
    "OPENROUTER_BASE_URL": "https://openrouter.ai/api/v1",
    "OPENROUTER_EMBED_MODEL": "openai/text-embedding-3-small",
    "ORCHESTRATOR_MODEL": "anthropic/claude-sonnet-4.6",
    "PRICE_IN_PER_MTOK": "3.0",
    "PRICE_OUT_PER_MTOK": "15.0",
    "OLLAMA_PRICE_IN_PER_MTOK": "0",
    "OLLAMA_PRICE_OUT_PER_MTOK": "0",
    "MAX_OUTPUT_TOKENS": "2048",
    "SEARCH_HIT_CHARS": "2500",
    "CHAPTER_HIT_CHARS": "12000",
    "MAX_STEPS": "4",
    "MAX_EMPTY_STREAK": "2",
    "MAX_CLARIFY_CANDIDATES": "5",
    "LLM_MAX_RETRIES": "2",
    "QUESTION_DEADLINE_S": "300",
    "AYL_STRICT_HIT_ID": "1",
    # No index: a test that needs one builds a LanceDB under tmp_path and points
    # the reader at it. A path that exists would let a developer's real library
    # answer a test question without anyone noticing.
    "LIBRARY_DB_PATH": "tests-have-no-index",
}
for _name, _value in DEFAULTS.items():
    os.environ.setdefault(_name, _value)
# The one default that depends on another knob (a local model is slower and may
# load cold), kept in step with config.py rather than pinned to one number.
os.environ.setdefault("LLM_TIMEOUT_S", "600" if os.environ["LLM_BACKEND"] == "ollama" else "120")

# Tracing is switched off outright, not defaulted: an inherited flag is exactly
# the shape that traced whole test runs to LangSmith. Both prefixes, because the
# SDK reads both (see test_tracing_recipe.py, which manages these itself).
TRACING_OFF = {"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING_V2": "false"}
os.environ.update(TRACING_OFF)

# Credentials and the opt-in key file: removed, so no test can reach a provider
# or a tracing endpoint even by accident, whatever the shell holds.
REMOVED = ("OPENROUTER_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY", "OPENROUTER_ENV_FILE")
for _name in REMOVED:
    os.environ.pop(_name, None)

import subprocess  # noqa: E402  (nothing above may import the package)
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]


# --- run state --------------------------------------------------------------
@pytest.fixture(autouse=True)
def clean_run_state():
    """The state a run leaves behind, reset before every test.

    Token counters and the deadline clock live in a ContextVar per run; the
    language is a ContextVar too; `library` caches the embedder and remembers
    which tables it has already checked or reported missing. None of it is
    per-test by itself, so without this a test reads the previous test's
    numbers, language or cached table."""
    from ask_your_library import i18n, library, llm

    llm.reset_usage()
    i18n.set_lang("en")
    library._checked_tables.clear()
    library._reported_missing.clear()
    library._embedder = None
    yield


# --- a fresh interpreter ----------------------------------------------------
# Import-time configuration can only be tested in a new process. The scrub list
# is the part that must not drift: a variable missing from it is the developer's
# shell, or the pinned defaults above, deciding what the child measures. It is a
# superset of DEFAULTS on purpose: a value pinned here must not reach a child
# that is meant to see a default.
SCRUBBED = frozenset(DEFAULTS) | frozenset(TRACING_OFF) | frozenset(REMOVED) | {
    "LLM_TIMEOUT_S", "LANGCHAIN_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_PROJECT",
    "ASK_SCRATCH_DIR", "ASK_DEBUG",
    "AYL_ALLOW_START_WITHOUT_KEY", "AYL_ALLOW_DEFAULT_LOGIN", "AYL_CHAINLIT_DIR",
    "CHAINLIT_AUTH_SECRET", "CHAINLIT_USERNAME", "CHAINLIT_PASSWORD",
    "CHAINLIT_COOKIE_SAMESITE",
}


def run_fresh(code: str, cwd=None, check=True, **env) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter with every configuration input unset
    and then `env` applied, in an empty working directory (`load_dotenv` reads
    the cwd and its parents, so running in the repository would read its .env).
    `cwd` overrides that for the tests that plant a .env of their own.
    check=True: an import-time SystemExit in the child fails the test."""
    base = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    base["PYTHONPATH"] = str(REPO)          # `import ui`; the package is installed
    with tempfile.TemporaryDirectory() as empty:
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              check=check, env={**base, **env}, cwd=cwd or empty)


def fresh_output(code: str, cwd=None, **env) -> str:
    """run_fresh, reduced to the child's stdout."""
    return run_fresh(code, cwd=cwd, **env).stdout.strip()
