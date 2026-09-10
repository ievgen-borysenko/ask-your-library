"""Environment checks that run BEFORE the first LLM call.

The three typical first-run failures (no API key, no database, embedding
backend down) used to surface as long tracebacks — and only after plan had
already made a billed LLM call. Interfaces call check_environment() first and
show the problems as plain text instead.

Besides fatal problems there are non-fatal notices: the environment works, but
in a degraded shape the user should know about (an index without book cards).
They ride along on the result, which is still the list of problems it always
was, so an interface that only iterates it keeps working unchanged.

Each problem is also recorded by KIND, on `.kinds`. The shipped default answers
on a local model, so the first run of a fresh clone fails in one of two ways
that are not the caller's mistake and are not each other: Ollama is not there
yet, or there is no index yet. A script that wraps the CLI needs to tell them
apart without matching on translated prose, so `exit_code()` turns the kinds
into the distinct status the CLI exits with.
"""
import lancedb
import requests
# Bound here so the except clauses survive a stubbed `requests`. HTTPError is a
# RequestException, so it must be caught first where both are handled.
from requests import HTTPError, RequestException

from .config import (DB_PATH, EMBED_BACKEND, LLM_BACKEND, OLLAMA_EMBED_MODEL, OLLAMA_URL, OPENROUTER_NEEDS_KEY,
                     ORCHESTRATOR_MODEL, TABLES)
from .embeddings import get_embedder, openrouter_api_key
from .i18n import t
from .index_meta import check_index


# The exit status an interface gives the shell for each class of first-run
# problem. 1 stays what it always was — "the environment is not ready" — so a
# caller that only tests for non-zero is unaffected; the three below are the
# named cases a first run actually hits. 2 is skipped: argparse already exits
# with it on a bad command line, and the two must not be confused. The numbers
# match the ones scripts/install-mac.sh's own verification step uses for the
# same two conditions, so one table covers the installer and the CLI.
EXIT_OK = 0
EXIT_NOT_READY = 1        # something else, including an index/embedder mismatch
EXIT_NO_INDEX = 3         # no database, or one without the transcripts table
EXIT_NO_KEY = 4           # a hosted backend is configured and has no key
EXIT_NO_LOCAL_RUNTIME = 5 # Ollama is unreachable, answers badly, or lacks a model

# Which kinds belong to which code. Ollama comes first: with the default local
# backend nothing else can be attempted until there is a model to answer with,
# and a run with no Ollama usually has no index either — reporting the index
# would send the reader to a 30-minute build they cannot finish anyway.
_LOCAL_RUNTIME_KINDS = frozenset({"no_ollama", "ollama_bad_reply", "no_local_model", "no_embed_model"})
_INDEX_KINDS = frozenset({"no_db", "no_tables"})


class PreflightResult(list):
    """The list of fatal problems (as before), plus `.notices`: non-fatal,
    user-visible degradations, and `.kinds`: the stable identifier of each
    problem, in the order the problems appear. `bool()`, iteration and `== []`
    are unchanged."""

    def __init__(self, problems=(), notices=(), kinds=()):
        super().__init__(problems)
        self.notices: list[str] = list(notices)
        self.kinds: list[str] = list(kinds)


def exit_code(result: PreflightResult) -> int:
    """The status an interface exits with for `result`.

    Not a subset test but an order of precedence: a fresh clone typically has
    several problems at once, and the code names the one to fix FIRST. Every
    problem is still printed — the code only says which remedy leads.
    """
    kinds = set(getattr(result, "kinds", ()))
    if not result:
        return EXIT_OK
    if kinds & _LOCAL_RUNTIME_KINDS:
        return EXIT_NO_LOCAL_RUNTIME
    if "no_key" in kinds:
        return EXIT_NO_KEY
    if kinds & _INDEX_KINDS:
        return EXIT_NO_INDEX
    return EXIT_NOT_READY


def _pulled(model: str, names: set[str]) -> bool:
    """`ollama pull qwen3.6` lists the model as `qwen3.6:latest`, so a
    configured name without a tag is satisfied by the `:latest` entry too."""
    return model in names or f"{model}:latest" in names


def check_api_key() -> str | None:
    """The key half of check_environment alone: no database, no embedding
    backend, no network. Returns a human-readable problem, or None when a key
    is available. Interfaces that must refuse *before* a user is in front of
    them (ui.py's startup gate) use this; the full check still runs later."""
    if not OPENROUTER_NEEDS_KEY:
        return None          # local model AND local embeddings: no key by design
    try:
        openrouter_api_key()
    except RuntimeError:
        return t("pf_no_key")
    return None


def pull_commands() -> str:
    """The `ollama pull` lines THIS configuration needs, in the order they are
    wanted: the answering model first, then the embedding one.

    Naming the configured models instead of a hard-coded pair is what keeps the
    remedy true when OLLAMA_LLM_MODEL or OLLAMA_EMBED_MODEL is something else —
    a message that says `ollama pull bge-m3` to somebody running nomic-embed-text
    sends them to fetch a model their run will never open."""
    models = []
    if LLM_BACKEND == "ollama":
        models.append(ORCHESTRATOR_MODEL)   # = OLLAMA_LLM_MODEL in this mode
    if EMBED_BACKEND == "ollama":
        models.append(OLLAMA_EMBED_MODEL)
    return ", ".join(f"`ollama pull {model}`" for model in models)


def check_environment() -> PreflightResult:
    """Human-readable problems (empty = good to go), with `.notices` for
    non-fatal degradations and `.kinds` for what each problem was."""
    problems = []
    notices = []
    kinds = []

    def problem(kind: str, message: str) -> None:
        """One problem, recorded twice: the sentence a reader gets, and the
        identifier `exit_code` classifies it by. Appending to one list without
        the other is what would make the exit status disagree with the text, so
        both go through here."""
        problems.append(message)
        kinds.append(kind)

    if OPENROUTER_NEEDS_KEY:
        try:
            openrouter_api_key()
        except RuntimeError:
            problem("no_key", t("pf_no_key"))

    if EMBED_BACKEND == "ollama" or LLM_BACKEND == "ollama":
        tags = None
        try:
            tags = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
            tags.raise_for_status()
        except HTTPError:
            # A server DID answer, with 4xx/5xx: `ollama serve` is not the remedy
            # (something else may hold that port, or this Ollama is unwell), so
            # this is a bad reply, and the status code is the useful part of it.
            problem("ollama_bad_reply", t("pf_ollama_bad_reply", url=OLLAMA_URL,
                                          status=getattr(tags, "status_code", "?")))
        except RequestException:
            # Nothing answered at all: the endpoint is the problem, and
            # installing and starting Ollama is the fix. A reply we cannot read
            # is a different problem and must not be reported as this one. This
            # is the first-run failure of the shipped default, so the message
            # carries the whole remedy: install, start, pull, or the one command
            # that does all three.
            problem("no_ollama", t("pf_no_ollama", url=OLLAMA_URL, pulls=pull_commands()))
        else:
            try:
                # Not JSON, no "models" key, or entries that are not objects:
                # something answers on that URL, but it is not Ollama's /api/tags.
                # An empty list is a valid reply — nothing is pulled yet; so is a
                # `null`, which is what Go encodes an empty slice as and what
                # older Ollama builds return. Read in BOTH modes: local embeddings
                # call the same server, so a 200 that is not Ollama would otherwise
                # pass preflight and fail on the first embedding request, deep
                # inside retrieval.
                names = {m.get("name", "") for m in (tags.json()["models"] or [])}
            except (ValueError, TypeError, KeyError, AttributeError):
                problem("ollama_bad_reply", t("pf_ollama_bad_reply", url=OLLAMA_URL,
                                              status=getattr(tags, "status_code", "?")))
            else:
                if LLM_BACKEND == "ollama" and not _pulled(ORCHESTRATOR_MODEL, names):
                    # The local model must be pulled: a missing one fails on the
                    # first (planner) call with a 404, after the user typed a question.
                    # ORCHESTRATOR_MODEL is OLLAMA_LLM_MODEL in this mode (config), so the
                    # model checked here is the model the client will call. Only this
                    # half is conditional: with a hosted LLM nothing is pulled locally.
                    problem("no_local_model", t("pf_no_local_model", model=ORCHESTRATOR_MODEL))
                if EMBED_BACKEND == "ollama" and not _pulled(OLLAMA_EMBED_MODEL, names):
                    # The same for the embedding model: a reachable Ollama without
                    # it passes every other check and then fails on the first
                    # search, which is the least legible place to learn about it.
                    problem("no_embed_model", t("pf_no_embed_model", model=OLLAMA_EMBED_MODEL))

    if not DB_PATH.exists():
        problem("no_db", t("pf_no_db", path=DB_PATH))
    else:
        # Full text is the corpus the agent cannot work without; book cards are
        # optional, because `ayl-add` builds an index without them (they need an
        # LLM per book). library.search skips a corpus whose table is absent.
        required = {TABLES["transcripts"]}
        try:
            present = set(lancedb.connect(DB_PATH).table_names())
        except Exception:
            present = set()
        missing = required - present
        if missing:
            problem("no_tables", t("pf_no_tables", path=DB_PATH,
                                   tables=", ".join(sorted(missing))))
        else:
            # Degraded, not broken: search runs over full text alone. Said here
            # because library.has_table only logs it, which in the web UI is a
            # server log the person asking the question never sees.
            if TABLES["cards"] not in present:
                notices.append(t("pf_no_cards", table=TABLES["cards"]))
            try:
                emb = get_embedder(EMBED_BACKEND)
                db = lancedb.connect(DB_PATH)
                for name in sorted(set(TABLES.values()) & present):
                    mismatch = check_index(db, name, emb.model, emb.dims)
                    if mismatch:
                        problem("index_mismatch", t("pf_index_mismatch", detail=mismatch))
            except Exception as error:  # a key error for openrouter etc. is reported above
                if not problems:
                    problem("index_mismatch",
                            t("pf_index_mismatch", detail=f"{type(error).__name__}: {error}"))

    return PreflightResult(problems, notices, kinds)
