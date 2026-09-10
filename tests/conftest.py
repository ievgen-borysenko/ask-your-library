"""What every test in this directory runs against: a fixed environment, clean
run state, and one way to start a fresh interpreter.

The suite used to inherit whatever the developer's shell (or a repo-root .env,
which `config.load_dotenv()` reads at import) happened to hold. `ASK_LANG=ua`
failed eight tests, and a LangSmith key made the end-to-end tests upload trace
batches while staying green, because the tracing client swallows the connection
error. Both are the same defect: `config` resolves every knob once, at import
time, so a variable set before the first import of the package silently decides
what the tests measure.

So `pin_environment()` runs here, at module level, BEFORE anything imports the
package (pytest imports conftest first). `setdefault`, not assignment: CI runs
the whole suite twice with an exported LLM_BACKEND, and that matrix has to keep
working. `load_dotenv` never overrides a variable that is already present, so
pinning also neutralises a .env in the repository root — but only for names it
can see, which is why the credentials are pinned BLANK instead of removed:
a removed name is a free name, and dotenv fills a free name in.
"""
import os
import tempfile

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
    # answer a test question without anyone noticing — and `lancedb.connect()`
    # CREATES the path it is given, so a relative one left an empty directory in
    # the repository root after every run. Absolute, under the system temp dir,
    # and per-process so two suites at once cannot meet in it.
    "LIBRARY_DB_PATH": os.path.join(tempfile.gettempdir(),
                                    f"ayl-tests-have-no-index-{os.getpid()}"),
}

# Tracing is switched off outright, not defaulted: an inherited flag is exactly
# the shape that traced whole test runs to LangSmith. Both prefixes, because the
# SDK reads both (see test_tracing_recipe.py, which manages these itself), and
# the older names too: langchain_core still reads LANGCHAIN_TRACING and
# LANGCHAIN_HANDLER, and RAISES when either is set while v2 is off, so a shell
# carrying the v1 flag failed the end-to-end tests instead of being ignored.
TRACING_OFF = {"LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING_V2": "false",
               "LANGCHAIN_TRACING": "false", "LANGSMITH_TRACING": "false",
               "LANGCHAIN_HANDLER": ""}

# Credentials and the opt-in key file: pinned BLANK, so no test can reach a
# provider or a tracing endpoint even by accident, whatever the shell holds.
BLANKED = ("OPENROUTER_API_KEY", "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY", "OPENROUTER_ENV_FILE")


def pin_environment() -> None:
    """Pin every configuration input this suite depends on, in a process that
    has not imported the package yet. Called at the import of this file, and by
    the child of test_preflight.py's planted-.env test — the same code, so what
    that test proves is what the whole suite runs under."""
    for name, value in DEFAULTS.items():
        os.environ.setdefault(name, value)
    # The one default that depends on another knob (a local model is slower and
    # may load cold), kept in step with config.py rather than pinned to a number.
    local = os.environ["LLM_BACKEND"] == "ollama"
    os.environ.setdefault("LLM_TIMEOUT_S", "600" if local else "120")
    os.environ.update(TRACING_OFF)
    # Assignment, not pop: `config.load_dotenv()` runs at the first package
    # import and fills any name that is ABSENT from a .env in the working
    # directory or its parents, so popping a key leaves the door open for the
    # repository's own .env to put it back. A blank value holds the name, and
    # every reader here treats blank as absent: `config._env`, the key lookup in
    # `embeddings.openrouter_api_key`, the LangSmith client, and the opt-in file
    # path, which config resolves to None when the value is empty.
    for name in BLANKED:
        os.environ[name] = ""


pin_environment()

import subprocess  # noqa: E402  (nothing above may import the package)
import sys  # noqa: E402
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
SCRUBBED = frozenset(DEFAULTS) | frozenset(TRACING_OFF) | frozenset(BLANKED) | {
    "LLM_TIMEOUT_S", "LANGCHAIN_TRACING", "LANGSMITH_TRACING", "LANGCHAIN_PROJECT",
    # The tracing destination, under both prefixes. Nothing here sets it, but a
    # child that reports where traces would go must not name the developer's own
    # LangSmith region instead of the default the SDK falls back to.
    "LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT",
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
    check=True: an import-time SystemExit in the child fails the test.

    The empty directory is half of what makes a child's reading a default and
    not the developer's: scrubbing a name from the environment FREES it, and a
    .env in the checkout then fills it in. The macOS installer writes such a
    .env (LLM_TIMEOUT_S=600, QUESTION_DEADLINE_S=1200), and the documented
    `uv run --group dev pytest -q` runs right after it — so every child that
    reads configuration goes through here, never a subprocess.run of its own."""
    base = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    # REPO for `import ui` (the package itself is installed); this directory so a
    # child can `from conftest import pin_environment` and start from exactly the
    # environment the suite starts from.
    base["PYTHONPATH"] = os.pathsep.join([str(REPO), str(Path(__file__).resolve().parent)])
    with tempfile.TemporaryDirectory() as empty:
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              check=check, env={**base, **env}, cwd=cwd or empty)


def fresh_output(code: str, cwd=None, **env) -> str:
    """run_fresh, reduced to the child's stdout."""
    return run_fresh(code, cwd=cwd, **env).stdout.strip()
