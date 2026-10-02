"""`ayl init`: the first run, in five steps, each safe to repeat.

  1. Model server  — is Ollama answering, and what has it pulled
                     (`preflight.ollama_tags`, the preflight's own question).
                     Nothing answers: exit 5, with the preflight's remedy.
  2. Mode          — `local` (Ollama answers and embeds, no key) or `hosted`
                     (OpenRouter answers, embeddings stay local); an existing
                     configuration decides instead and is never rewritten.
  3. Models        — `POST /api/pull` for what the mode needs and Ollama does
                     not have (`preflight.pull_models`), progress streamed.
  4. Configuration — `$AYL_HOME/config.env` (ADR-027), through
                     `home.write_private`, unless a `.env` in the working
                     directory or that file already exists.
  5. Libraries     — where the reader's own index is and what `ayl add` puts in
                     it; an index or chat database from before ADR-026, with the
                     documented move printed (never performed); and, only when
                     asked for, the demo library (ADR-028).

Then `ayl doctor` runs in a fresh interpreter — one that reads the
configuration this run may just have written — and the next commands are
printed.

The demo library is opt-in: `--demo` (the starter subset, a few minutes),
`--demo --full` (the whole corpus, about half an hour), or one question on a
terminal, defaulting to no. It is built by `scripts/ingest_demo_corpus.py` —
the same code path, run as that script with `LIBRARY_DB_PATH` naming
`$AYL_HOME/demo/index` — so it never lands in the reader's own index, and the
reader's library never starts mixed with the classics. The script and the
corpus it reads ship with the clone, not with the package: outside a checkout
the demo step refuses, and says so, while steps 1-4 work anywhere.

`--dry-run` prints every step and touches nothing: no request to Ollama, no
file written, no index opened that does not already exist.
"""
import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

import lancedb
import yaml
from dotenv import dotenv_values

from . import config, dataflow, home, ollama, preflight
from .bookkey import book_key
from .cli import say
from .embeddings import OllamaEmbedder, OpenRouterEmbedder
from .i18n import t
from .index_meta import expected_chunker, read_index_meta, rows_by_book
from .ingest.doctor import check_ledger
from .ingest.foreign import foreign_books
from .ingest.ledger import INDEXED, open_ledger
from .ingest.publish import STAGING_SUFFIX, table_names
from .paths import REPO_ROOT
from .ui import launcher

STEPS = 5

# The owner's decision of 2026-10-02: the demo library is built only when
# asked for. Flipping this one constant makes it the default again — the
# question's default answer and what `--yes` means both follow it — which is
# what the 22.09 plan had; `--demo` and `--no-demo` win either way.
BUILD_DEMO_BY_DEFAULT = False

# What `ayl init` writes, per mode: the two switches (which must not be
# collapsed into one, `config.py`), and the timeouts `scripts/install-mac.sh`
# writes for the same mode, because a value in a file outlives a default that
# depends on the backend. No model name: the code's defaults stay in force
# until the reader names another one here.
MODES = {
    "local": {"LLM_BACKEND": "ollama", "EMBED_BACKEND": "ollama",
              "LLM_TIMEOUT_S": "600", "QUESTION_DEADLINE_S": "1200",
              # The mode in which nothing leaves the machine: a tracing flag
              # another project's shell exported must not upload from here.
              "LANGSMITH_TRACING_V2": "false", "LANGCHAIN_TRACING_V2": "false"},
    "hosted": {"LLM_BACKEND": "openrouter", "EMBED_BACKEND": "ollama",
               "LLM_TIMEOUT_S": "120", "QUESTION_DEADLINE_S": "300"},
}
SWITCHES = ("LLM_BACKEND", "EMBED_BACKEND")
MODE_LINE = {"local": "local — Ollama answers and embeds on this machine; no account, no key",
             "hosted": "hosted — OpenRouter answers (a key, billed per question); "
                       "embeddings stay on this machine",
             # The two valid pairs `ayl init` never writes but an existing
             # configuration may hold. Named, so no path leaves the mode
             # undecided: both embed on OpenRouter, which is where every
             # passage of the library goes.
             "custom": "neither mode `ayl init` writes — {llm} answers, OpenRouter embeds: "
                       "every passage of the library is sent there (a key, billed)"}
# The values config.py accepts for each switch, and whether a blank value means
# the default there: LLM_BACKEND is read through `_env` (blank is the default),
# EMBED_BACKEND with `os.environ.get` (blank is a blank backend, which no
# embedder answers to). Checked before any step, like config.py's own refusal
# of a bad LLM_BACKEND — which stops the import before `ayl init` can run —
# because a typo in EMBED_BACKEND passes the import and fails only at the
# first `ayl add` or question.
BACKENDS = ("ollama", "openrouter")
BLANK_IS_DEFAULT = {"LLM_BACKEND": True, "EMBED_BACKEND": False}

# How long the demo build takes, said before the question. The whole corpus is
# the figure the project has always stated (about 30 minutes for 33 books and
# two canaries, dominated by embedding 11,282 chunks). The starter subset holds
# about 2.1 million of the corpus's 27 million prepared characters, so its
# embedding is a few minutes, plus five downloads from gutenberg.org.
ESTIMATE = {"starter": "a few minutes", "full": "about 30 minutes"}

# The question the README and the quick start open with; its book is in the
# starter subset (tests/test_starter_subset.py holds both ends of that).
FIRST_QUESTION = "What does Marcus Aurelius say about anger?"

# Printed by --print-env-resolution: the settings that decide where a
# question, a passage or a trace goes (`dataflow.DATA_FLOW_VARS`, the list the
# installer reports too), the models and the key that go with them, and where
# the data is kept.
RESOLVED = (*dataflow.DATA_FLOW_VARS, "OLLAMA_LLM_MODEL", "OLLAMA_EMBED_MODEL",
            "ORCHESTRATOR_MODEL", "OPENROUTER_API_KEY", "OPENROUTER_ENV_FILE",
            "LIBRARY_DB_PATH", "AYL_HOME")
SECRET_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


# --- printing -------------------------------------------------------------------

def step(number: int, title: str) -> None:
    say(f"[{number}/{STEPS}] {title}")


def note(text: str) -> None:
    say(f"       {text}")


def plan(text: str) -> None:
    say(f"       would {text}")


def problem(text: str) -> None:
    say(f"error: {text}", error=True)


def command(text: str) -> str:
    """A command line as the reader types it here: through `uv run` in a
    clone, where `ayl` lives in the project's environment, bare elsewhere."""
    return f"uv run {text}" if REPO_ROOT else text


def quoted(path: Path) -> str:
    return shlex.quote(str(path))


# --- the parser -----------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ayl init",
        description="Set this machine up to answer: check the local model server, choose the "
                    "mode, pull the models it needs, write $AYL_HOME/config.env, and say where "
                    "your own books go. Every step is skipped when it is already done, so a "
                    "second run changes nothing. The demo library of public-domain classics "
                    "is built only when asked for, and apart from your own index.",
        epilog="Exit status: 0 set up (your library may still be empty, and a hosted mode may "
               "still need its key: both are left to you and printed), 1 a step failed, 2 a "
               "bad command line or an exported variable that contradicts the mode, 3 or 4 "
               "what the closing `ayl doctor` found, 5 no usable Ollama, 130 interrupted.")
    parser.add_argument("--mode", choices=tuple(MODES),
                        help="local (the default: no account, no key) or hosted (OpenRouter "
                             "answers; you set OPENROUTER_API_KEY yourself). Ignored, with a "
                             "note, when a configuration already exists")
    demo = parser.add_mutually_exclusive_group()
    demo.add_argument("--demo", action="store_true",
                      help="also build the demo library: six public-domain classics in a few "
                           "minutes, into $AYL_HOME/demo/index (never your own index)")
    demo.add_argument("--no-demo", action="store_true",
                      help="do not build the demo library and do not ask about it")
    parser.add_argument("--full", action="store_true",
                        help="with --demo: the whole demo corpus (33 books, about 30 minutes) "
                             "instead of the starter subset")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="ask nothing; the demo library is then built only with --demo")
    parser.add_argument("--dry-run", action="store_true",
                        help="print what each step would do and change nothing: no request to "
                             "Ollama, no file written, no index created. Ends on the status the "
                             "real run would, wherever that can be told without a request, and "
                             "names what it did not check")
    parser.add_argument("--print-env-resolution", action="store_true",
                        help="print each setting that decides where your data goes, its value "
                             "(credentials as <set, N chars>) and where it came from — "
                             "exported, a .env, $AYL_HOME/config.env or the default — and exit")
    return parser


# --- step 2: the mode -----------------------------------------------------------

def existing_configuration() -> Path | None:
    """The file that already configures this machine, or None: a `.env` that
    sets one of the two mode switches first, then `$AYL_HOME/config.env`.

    A `.env` that sets neither (an endpoint, a model name, a scratch folder)
    does not choose a mode, so it does not stop `ayl init` from writing the
    file that does; it is still read above that file, as ADR-027 says."""
    if config.PROJECT_ENV is not None and config.PROJECT_ENV.is_file():
        values = dotenv_values(config.PROJECT_ENV)
        if any((values.get(name) or "").strip() for name in SWITCHES):
            return config.PROJECT_ENV
    return config.HOME_CONFIG if config.HOME_CONFIG.is_file() else None


def described(path: Path) -> str:
    """A configuration file, named — and said to be outside this checkout when
    it is a `.env` that is: a `.env` the reader did not expect to be read is
    the one worth pointing at."""
    if path == config.HOME_CONFIG:
        return str(path)
    if REPO_ROOT and Path(path).resolve().is_relative_to(Path(REPO_ROOT).resolve()):
        return str(path)
    return f"{path} (a .env outside this checkout)" if REPO_ROOT else f"{path} (a .env)"


def mode_of(llm_backend: str, embed_backend: str) -> str:
    """The name of a valid pair: one `ayl init` writes, or `custom` for the
    two it does not (hosted embeddings). `switch_problems` has refused every
    other value before this is asked."""
    for name, values in MODES.items():
        if (values["LLM_BACKEND"], values["EMBED_BACKEND"]) == (llm_backend, embed_backend):
            return name
    return "custom"


def switch_problems() -> list[str]:
    """Each mode switch whose value config.py would not run with, named with
    its value, where it came from and what it may be."""
    found = []
    for name in SWITCHES:
        raw = os.environ.get(name)
        if raw is None or (BLANK_IS_DEFAULT[name] and not raw.strip()):
            continue
        if raw not in BACKENDS:
            found.append(f"{name}={raw!r} [{config.setting_source(name)}] is not a backend: "
                         f"it must be one of {', '.join(BACKENDS)}"
                         + ("" if BLANK_IS_DEFAULT[name] else " (blank is not the default "
                            "for this one)"))
    return found


def contradictions(mode: str) -> list[str]:
    """Exported switches that contradict the local mode this run would write,
    each as the sentence that says what to do about it: python-dotenv never
    overrides an exported name, so the file would say local and every command
    would send something elsewhere. Asked only of the local mode — the hosted
    one lets an export decide and names it, as the installer's --hosted does."""
    wanted = MODES[mode]
    loaded = {"LLM_BACKEND": config.LLM_BACKEND, "EMBED_BACKEND": config.EMBED_BACKEND}
    return [f"{name}={loaded[name]} is exported in this shell and would decide every command "
            f"instead of the {mode} mode this run writes; unset it, or run "
            f"`ayl init --mode hosted`, in which an exported switch decides and is named"
            for name in SWITCHES
            if name in config.EXPORTED and loaded[name] != wanted[name]]


def local_mode_problems(writing: bool) -> list[str]:
    """What stops a run from being the fully local one it is called: an
    Ollama that is not on this machine, a tracing flag that uploads, a v1
    flag langchain_core counts as set, and a LangSmith key with no flag — the
    rule `scripts/install-mac.sh` holds its local mode to (`dataflow`), each
    named with where its value came from. A key alone turns tracing on
    (`graph.enable_tracing_if_key_present`) only while LANGCHAIN_TRACING_V2 is
    unset, which the file this run writes (`writing`) is not."""
    found = []
    if not dataflow.is_loopback(config.OLLAMA_URL):
        # The real value decides; only what is printed is the allowlisted form.
        shown = dataflow.shown_url(config.OLLAMA_URL)
        found.append(f"OLLAMA_URL [{config.setting_source('OLLAMA_URL')}] is not this machine"
                     + (" (its value is not shown: it carries a credential or is not a plain "
                        "URL)" if shown == dataflow.NOT_SHOWN else f": {shown}"))
    on = dataflow.tracing_on()
    found += [f"{name}={os.environ.get(name, '')} [{config.setting_source(name)}] uploads traces"
              for name in on]
    found += [f"{name} [{config.setting_source(name)}] is set as langchain_core reads it"
              for name in dataflow.v1_tracing_set() if name not in on]
    if (not writing and os.environ.get("LANGCHAIN_API_KEY", "").strip()
            and "LANGCHAIN_TRACING_V2" not in os.environ):
        found.append(f"LANGCHAIN_API_KEY [{config.setting_source('LANGCHAIN_API_KEY')}] is set "
                     f"and LANGCHAIN_TRACING_V2 is not, which turns tracing on")
    return found


def config_text(mode: str) -> str:
    lines = [f"# Written by `ayl init` ({mode} mode). Read beneath exported variables and a",
             "# .env in the working directory (docs/configuration.md); edit it freely, a",
             "# second `ayl init` never rewrites it.",
             *(f"{name}={value}" for name, value in MODES[mode].items())]
    if mode == "hosted":
        lines += ["# The key is yours to set; `ayl init` never takes one. ORCHESTRATOR_MODEL,",
                  "# PRICE_IN_PER_MTOK and PRICE_OUT_PER_MTOK keep the code's defaults unless",
                  "# set here (.env.example has them with what they cost).",
                  "OPENROUTER_API_KEY="]
    else:
        lines += ["# Unset LIBRARY_DB_PATH: your index is $AYL_HOME/index (ADR-026)."]
    return "\n".join(lines) + "\n"


# --- step 5: the indexes --------------------------------------------------------

def demo_path() -> Path:
    """Where the demo library goes: under `AYL_HOME`, beside the reader's own
    index and never inside it. Refused inside a git work tree like the index
    (it holds the full text of the books it was built from)."""
    return home.private_dir("demo", "index")


def manifest_books(full: bool | None) -> dict[str, str]:
    """{manifest id: book key} for the entries a demo build covers: the starter
    subset, or every entry (books and canaries) for `--full` — what the script
    builds for the same flag; None, every entry. The key is what the index
    rows carry (`bookkey.book_key`, the function the ingest mints it with)."""
    manifest = yaml.safe_load((Path(REPO_ROOT) / "corpus" / "manifest.yaml")
                              .read_text(encoding="utf-8"))
    entries = manifest["books"] + manifest["canaries"]
    return {entry["id"]: book_key(entry["title"], entry["author"]) for entry in entries
            if full is not False or entry.get("starter") is True}


def card_ids() -> set[str]:
    """The manifest ids with a committed card: the books a demo cards table
    must hold (the canaries have none)."""
    return {path.stem for path in (Path(REPO_ROOT) / "corpus" / "cards").glob("*.md")}


def _has_fts(db, name: str) -> bool:
    """A full-text index over `text` covering every row: LanceDB drops it with
    the table, so a table published and not yet re-indexed has none."""
    try:
        indices = db.open_table(name).list_indices()
    except Exception:
        return False
    return any(getattr(index, "index_type", "") == "FTS" and "text" in index.columns
               and not getattr(index, "num_unindexed_rows", 0) for index in indices)


def _stamped(db, name: str, backend: str) -> bool:
    """`_index_meta` has a row for `name` naming the embedder this backend
    uses and the chunker this code stamps that table with."""
    meta = read_index_meta(db, name)
    embedder = OllamaEmbedder if backend == "ollama" else OpenRouterEmbedder
    return bool(meta) and meta.get("model") == embedder.model \
        and meta.get("chunker") == expected_chunker(name)


def demo_state(path: Path, backend: str, wanted: dict[str, str]) -> tuple[str, str]:
    """(state, detail) of the index at `path` as a demo library for `wanted`
    ({manifest id: book key}). Reads only an index that exists; never creates
    one.

    `complete` is one state, reached only at the end of the script's run, and
    every interruption between two of its publish points leaves something it
    checks out of place — so a folder an interrupted build left is never
    taken for a built one:

    - no staging table (`<table>__staging`, transcripts, cards or the meta
      table): one is what an interrupted rebuild leaves, and the script's
      `recover_staging` finishes or drops it;
    - the transcripts hold every wanted book, and only books the manifest
      produces (else `foreign`);
    - the cards hold exactly the carded books of what the transcripts hold:
      a card of a book absent from the transcripts (a `--starter` rebuild
      interrupted before its cards stage, over a full library) is a search hit
      no chapter read can open, and a missing card is a library half-built;
    - both tables carry their full-text index and a stamp of this embedder
      and chunker;
    - the ledger says `indexed` for exactly the books in the transcripts —
      not `requested` (an ingest stopped before its commit), and no row of a
      book the table no longer holds (one stopped before its reconcile).

    What the transcripts hold beyond `wanted` is kept, not shrunk: a full
    library asked for the starter subset is complete, with its own cards.

    `absent` nothing is built; `partial` anything else a build finishes;
    `other_backend` an index whose transcripts another embedding backend
    built — building beside it would be a second index in one folder;
    `foreign` an index holding a book no manifest entry built, by its rows or
    its ledger (`ingest.foreign`, the demo script's own rule) — rebuilding
    the table would replace them."""
    table = f"transcripts_{backend}"
    if not (path / f"{table}.lance").is_dir():
        built = (p.name[:-len(".lance")] for p in path.glob("transcripts_*.lance")) \
            if path.is_dir() else ()
        others = sorted(name for name in built if not name.endswith(STAGING_SUFFIX))
        if others:
            return "other_backend", ", ".join(others)
        return "absent", ""
    db = lancedb.connect(path)
    # The demo script's own rule (`ingest.foreign`), so the two cannot
    # disagree about whose books a folder holds.
    if REPO_ROOT and foreign_books(db, set(manifest_books(None).values())):
        return "foreign", "it holds books that are not the demo corpus's"
    rows = open_ledger(db).all_rows()
    present = set(rows_by_book(db, table))

    there = sum(1 for key in wanted.values() if key in present)
    detail = f"{there} of {len(wanted)} books in the index"
    cards_table = f"cards_{backend}"
    names = set(table_names(db))
    if any(name.endswith(STAGING_SUFFIX) for name in names):
        return "partial", detail + "; an interrupted rebuild left a staging table"
    if there < len(wanted):
        return "partial", detail
    keys = manifest_books(None) if REPO_ROOT else {}
    carded = {keys[note] for note in card_ids() if note in keys} & present if REPO_ROOT \
        else set()
    cards = set(rows_by_book(db, cards_table)) if cards_table in names else set()
    if cards != carded:
        return "partial", detail + (f"; its cards are not its books' "
                                    f"({len(cards - present)} of books it does not hold, "
                                    f"{len(carded - cards)} missing)")
    for name in (table, cards_table):
        if name in names and not (_has_fts(db, name) and _stamped(db, name, backend)):
            return "partial", detail + f"; {name} has no full-text index or stamp yet"
    indexed = {str(row.get("key") or "") for row in rows if row.get("status") == INDEXED}
    if indexed != present or len(indexed) != len(rows):
        return "partial", detail + "; its ledger does not describe its rows yet"
    return "complete", detail


def legacy_indexes() -> list[tuple[Path, str]]:
    """Every index or chat database from before ADR-026 this run can see,
    with the notice that names the move as commands. Nothing is moved."""
    found = []
    if config.DB_CHOICE.clause == 2:
        found.append((config.DB_CHOICE.path, config.legacy_db_notice(config.DB_CHOICE)))
    elif REPO_ROOT:
        # Clause 2 is the working directory's, by design; run from elsewhere,
        # the clone's own old index is not read — and a demo build here would
        # be the second index the reader did not ask for.
        old = Path(REPO_ROOT) / config.LEGACY_DB_PATH
        if (old / f"{config.TABLES['transcripts']}.lance").is_dir():
            choice = config.DbPathChoice(old, 2, "")
            found.append((old, f"note: the clone at {REPO_ROOT} holds an index at the old "
                               f"default, read only by a command run in the clone. "
                               + config.legacy_db_notice(choice).removeprefix("note: ")))
    chat = launcher.legacy_chat_db()
    if chat is not None:
        found.append((chat, launcher.legacy_chat_db_notice(chat)))
    return found


def ask(question: str) -> bool:
    """The one question `ayl init` asks; an empty answer is the default."""
    try:
        reply = input(f"       {question} [{'Y/n' if BUILD_DEMO_BY_DEFAULT else 'y/N'}] ")
    except EOFError:
        reply = ""
    reply = reply.strip().lower()
    if not reply:
        return BUILD_DEMO_BY_DEFAULT
    return reply in ("y", "yes")


# --- --print-env-resolution -----------------------------------------------------

def print_env_resolution() -> int:
    project = (described(config.PROJECT_ENV) if config.PROJECT_ENV is not None
               else "the project's .env (none found)")
    say("Where each setting comes from, highest first: exported, then "
        f"{project}, then "
        f"{config.HOME_CONFIG}{'' if config.HOME_CONFIG.is_file() else ' (absent)'}, "
        f"then the default.")
    for name in RESOLVED:
        value = os.environ.get(name)
        if value is None:
            shown = "(unset)"
        elif any(part in name for part in SECRET_PARTS):
            shown = f"<set, {len(value)} chars>" if value else "(blank)"
        elif name in dataflow.ENDPOINT_VARS:
            shown = dataflow.shown_url(value) if value else "(blank)"
        else:
            # Not a URL (a model name, a path, a flag): as it is, unless it
            # holds an @, which no value of these needs.
            shown = dataflow.NOT_SHOWN if "@" in value else value
        say(f"  {name}={shown}  [{config.setting_source(name)}]")
    say(f"  -> answering: {config.LLM_BACKEND}, embeddings: {config.EMBED_BACKEND}, "
        f"index: {config.DB_PATH} ({config.DB_CHOICE.reason})")
    return 0


# --- the run --------------------------------------------------------------------

def closing_check(db: Path | None) -> int:
    """`ayl doctor` in a fresh interpreter: this process imported its
    configuration before step 4 may have written one, and a check run here
    would judge the old one. `db` points it at the demo library."""
    sys.stdout.flush()      # this run's lines before the child's
    env = dict(os.environ)
    if db is not None:
        env["LIBRARY_DB_PATH"] = str(db)
    return subprocess.call([sys.executable, "-m", "ask_your_library.ayl", "doctor"], env=env)


def demo_cache() -> Path:
    """Where a demo build `ayl init` starts keeps its downloads and prepared
    texts: under AYL_HOME, beside the demo library, never in the checkout. The
    same work-tree refusal as the demo library itself (`demo_path`), which it
    is only ever used with: one check, not a second with other semantics."""
    return home.private_dir("demo", "cache")


def build_demo(path: Path, backend: str, full: bool, cache: Path) -> int:
    """The demo library, built by the script that has always built it, with
    its own stages, checksums, staging tables and ingest lock: run as that
    script, with `LIBRARY_DB_PATH` naming `path` (clause 1, so no notice and
    no second resolution) and `--cache-dir` naming `cache`, so the run writes
    nothing under the checkout — not its data/, not the committed
    corpus/toc/ — and a read-only clone builds as well as any."""
    script = Path(REPO_ROOT) / "scripts" / "ingest_demo_corpus.py"
    argv = [sys.executable, str(script), "--backend", backend, "--cache-dir", str(cache),
            *([] if full else ["--starter"])]
    sys.stdout.flush()
    return subprocess.call(argv, env={**os.environ, "LIBRARY_DB_PATH": str(path)})


def run(rest: list[str]) -> int:
    args = build_parser().parse_args(rest)
    if args.full and not args.demo:
        build_parser().error("--full says how much of the demo library to build: it needs --demo")
    if args.print_env_resolution:
        return print_env_resolution()
    try:
        return _run(args)
    except KeyboardInterrupt:
        problem("interrupted. Run `ayl init` again: what was pulled is kept, and every stage "
                "of a demo build is cached, so it resumes rather than starts over.")
        return 130


def _run(args) -> int:
    dry = args.dry_run
    say("Ask Your Library — first run")
    if dry:
        say("Dry run: the plan only. Nothing is pulled, written or built.")
    say("")

    bad = switch_problems()
    if bad:
        for sentence in bad:
            problem(f"{sentence}.")
        problem("Every command would refuse this configuration (`ayl add` and `ayl ask` with "
                "\"unknown embedding backend\"). Fix the value where it came from and run "
                "`ayl init` again. Nothing was changed.")
        return 2

    # Step 2 is decided first, silently: step 1 needs to know whether this
    # configuration uses Ollama at all.
    existing = existing_configuration()
    written = None          # the mode of the file this run writes, if it writes one
    if existing is not None:
        llm, embed = config.LLM_BACKEND, config.EMBED_BACKEND
        mode = mode_of(llm, embed)
    else:
        written = args.mode or "local"
        if written == "local":
            # The local mode promises that nothing leaves this machine, so an
            # exported switch that would send something elsewhere is refused —
            # the rule scripts/install-mac.sh holds its local mode to.
            clash = contradictions(written)
            if clash:
                for sentence in clash:
                    problem(f"{sentence}.")
                problem("Nothing was changed.")
                return 2
        # The hosted mode, like the installer's --hosted, is not refused over
        # an exported switch: the export decides (it wins over the file), the
        # run follows it — pulls, checks, the local rule when it is local —
        # and step 2 says so.
        llm = config.LLM_BACKEND if "LLM_BACKEND" in config.EXPORTED \
            else MODES[written]["LLM_BACKEND"]
        embed = config.EMBED_BACKEND if "EMBED_BACKEND" in config.EXPORTED \
            else MODES[written]["EMBED_BACKEND"]
        mode = mode_of(llm, embed)
    if mode == "local":
        # "Nothing leaves this machine" is what the local mode is, so a run
        # that would send something elsewhere is not one, whatever file says so.
        leaks = local_mode_problems(writing=written == "local")
        if leaks:
            for leak in leaks:
                problem(f"{leak}.")
            problem("The local mode is the one in which nothing leaves this machine, and these "
                    "would. Unset them (or point OLLAMA_URL at this machine), or choose "
                    "`--mode hosted` if sending the question elsewhere is what you want. Nothing "
                    "was changed.")
            return 2

    # --- 1 ---
    # `url` goes to the requests and nowhere else; `shown` is what is printed
    # (`dataflow.shown_url`: scheme, host and port, or fixed words).
    url = config.OLLAMA_URL
    shown = dataflow.shown_url(url)
    needs_ollama = "ollama" in (llm, embed)
    step(1, f"Model server: Ollama at {shown}")
    pulled: frozenset = frozenset()
    if not needs_ollama:
        note("not needed: this configuration answers and embeds on OpenRouter")
    elif dry:
        plan(f"ask Ollama's /api/tags at {shown} whether it answers, and what it has pulled")
    else:
        reply = preflight.ollama_tags(url)
        if reply.kind == "no_ollama":
            problem(t("pf_no_ollama", url=shown,
                      pulls=", ".join(f"`ollama pull {m}`"
                                      for m in preflight.pull_models(llm, embed))))
            return preflight.EXIT_NO_LOCAL_RUNTIME
        if reply.kind == "ollama_bad_reply":
            problem(t("pf_ollama_bad_reply", url=shown, status=reply.status))
            return preflight.EXIT_NO_LOCAL_RUNTIME
        pulled = reply.names
        note(f"answering; {len(pulled)} model(s) pulled")

    # --- 2 ---
    step(2, f"Mode: {MODE_LINE[mode].format(llm='Ollama' if llm == 'ollama' else 'OpenRouter')}")
    if existing is not None:
        note(f"read from {described(existing)}, which already configures this machine")
        for name, value in (("LLM_BACKEND", llm), ("EMBED_BACKEND", embed)):
            source = config.setting_source(name)
            if source != str(existing):
                note(f"{name}={value} comes from "
                     + ("a variable exported in this shell, which wins over that file" if
                        source == "exported" else source))
        if args.mode and args.mode != mode:
            note(f"--mode {args.mode} was NOT applied: an existing configuration decides, and "
                 f"`ayl init` never rewrites one. Edit it (or move it aside) and run again.")
    else:
        note("chosen with --mode" if args.mode else "the default (--mode hosted for OpenRouter)")
        if mode != written:
            note(f"the file this run writes says {written}; "
                 + ", ".join(f"{name}={value} is exported in this shell and wins over it"
                             for name, value in (("LLM_BACKEND", llm), ("EMBED_BACKEND", embed))
                             if name in config.EXPORTED and value != MODES[written][name]))
    if embed != "ollama":
        note("embeddings run on OpenRouter: a demo build would be billed per token")

    # The one question, asked here — before minutes of downloads, with the
    # estimate in front of it — and only on a terminal, only when no flag
    # answered it already.
    full = args.full
    which = "full" if full else "starter"
    if args.demo or args.no_demo:
        want_demo = args.demo
    elif args.yes or dry or not sys.stdin.isatty():
        want_demo = BUILD_DEMO_BY_DEFAULT
    elif dataflow.credential_configured():
        # Not offered when it could not be built (step 5 says why): a yes
        # here would only end the run on a refusal the reader was led into.
        want_demo = False
    else:
        say("")
        note(f"The demo library: six public-domain classics, built in {ESTIMATE[which]} after "
             f"the models, into its own index under AYL_HOME — never into yours. It downloads "
             f"five checksum-pinned texts from gutenberg.org; every stage is cached, so it is "
             f"safe to interrupt and resume. Your own books need no demo: `ayl add <folder>`.")
        want_demo = ask("Build the demo library too?")
    say("")

    # Whether this run changed anything at all: a second run over a ready
    # machine has to say that it did nothing, not leave it to be inferred.
    changed = False
    # Failures a step could tell without a write or a request: each ends the
    # run, real or dry, on EXIT_NOT_READY (see `final_status`).
    refused: list[str] = []
    will_build = False

    # --- 3 ---
    step(3, "Models: pull what Ollama does not have yet")
    wanted_models = preflight.pull_models(llm, embed)
    if not wanted_models:
        note("none: nothing in this configuration runs on Ollama")
    for model in wanted_models:
        if dry:
            plan(f"pull {model} (skipped when it is already pulled)")
        elif preflight._pulled(model, pulled):
            note(f"{model}: already pulled")
        else:
            try:
                ollama.pull(model, Progress(model), url=url)
            except ollama.PullError as error:
                say("")
                problem(f"{error}. Nothing else was changed; run `ayl init` again once that is "
                        f"fixed.")
                return preflight.EXIT_NO_LOCAL_RUNTIME
            say("")
            note(f"{model}: pulled")
            changed = True

    # --- 4 ---
    step(4, "Configuration")
    if existing is not None:
        note(f"{described(existing)} exists and is never rewritten; nothing was changed")
    else:
        target = home.ayl_home() / "config.env"
        text = config_text(written)
        if dry:
            # What the write would be refused for is knowable without writing:
            # the folder or the file inside a git work tree, or a link at the
            # file's name. The real run stops here on it with status 1.
            try:
                home.private_dir()
                home.private_file(target)
            except RuntimeError as error:
                problem(f"{error}")
                refused.append("the configuration file would be refused")
            plan(f"write {target} (mode 0600):")
            for line in text.splitlines():
                if not line.startswith("#"):
                    note(f"  {line}")
        else:
            try:
                home.private_dir().mkdir(parents=True, exist_ok=True)
                home.write_private(target, text)
            except (RuntimeError, OSError) as error:
                problem(f"{error}")
                return preflight.EXIT_NOT_READY
            note(f"wrote {target}")
            changed = True
            for line in text.splitlines():
                if not line.startswith("#"):
                    note(f"  {line}")
        if written == "hosted":
            note(f"OPENROUTER_API_KEY is left empty on purpose: set it in {target} (or export "
                 f"it) before the first question. `ayl init` never takes a key.")

    # --- 5 ---
    step(5, "Libraries")
    reader_index = config.DB_PATH
    note(f"your index: {reader_index} — {config.DB_CHOICE.reason}")
    if config.DB_CHOICE.clause == 3:
        try:
            home.refuse_in_work_tree(reader_index, "index")
        except RuntimeError as error:
            # An error state, not a remark: every command that opens this index
            # refuses it, so the run is not set up — and says so in its status,
            # the dry run's included, even when a demo library is built.
            problem(str(error))
            refused.append("your index's folder is refused")
    legacy = legacy_indexes()
    for path, notice in legacy:
        note(notice)
        if path.name == "lancedb" and demo_state(path, embed, {})[0] == "complete":
            # Every book in it came from the manifest: it IS a demo library,
            # and restoring it there keeps the reader's own index empty.
            note(f"it holds only the demo corpus, so `--db "
                 f"{quoted(home.ayl_home() / 'demo' / 'index')}` in that restore puts it where "
                 f"`ayl init --demo` would have built it, apart from your own index")
    demo_index: Path | None = None
    # A demo library asked for and not built is this run's failure even when
    # the reason is a good one: the status says so, after the check and the
    # next steps have still been printed.
    demo_missed = False
    demo_blocked = False        # refused over configuration: exit 2, like every such refusal
    if not want_demo:
        note(f"demo library: not built. `{command('ayl init --demo')}` builds six classics in "
             f"{ESTIMATE['starter']}, kept apart from your index")
    elif dataflow.credential_configured():
        # The demo build is a child process whose error output this PR does
        # not control (the embedders' HTTP errors print the URL they were
        # sent to, user:password@ included — #107). Until that is safe, a
        # demo build is not started with a credential in any URL-valued
        # setting: the reader moves it out of the URL first. Steps 1-4 ran.
        problem("the demo library is not built while a URL-valued setting (OLLAMA_URL, "
                "OPENROUTER_BASE_URL or a trace endpoint) carries a credential: the demo build's "
                "error output is not yet safe for one (issue #107) and could print it. Move the "
                "credential out of the URL, then run `ayl init --demo` again.")
        demo_blocked = True
    elif legacy and any(path.name == "lancedb" for path, _ in legacy):
        note("demo library: NOT built — an index from an earlier version is there (above). Move "
             "it with the commands printed rather than build a second one beside it.")
        demo_missed = True
    elif not REPO_ROOT or not (Path(REPO_ROOT) / "scripts" / "ingest_demo_corpus.py").is_file():
        problem("the demo library is built by scripts/ingest_demo_corpus.py from corpus/, and "
                "both ship with the clone, not with the installed package. Run `ayl init "
                "--demo` from a clone (git clone https://github.com/ievgen-borysenko/"
                "ask-your-library), or index your own books with `ayl add <folder>`.")
        demo_missed = True
    else:
        try:
            target = demo_path()
        except RuntimeError as error:
            problem(str(error))
            target = None
            demo_missed = True
        if target is not None:
            wanted = manifest_books(full)
            state, detail = demo_state(target, embed, wanted)
            label = "the whole demo corpus" if full else "the starter demo library"
            if state == "complete":
                note(f"demo library: {target} — already built ({detail}); nothing to do")
                demo_index = target
            elif state in ("foreign", "other_backend"):
                why = (f"its transcripts were embedded by another backend ({detail}), and a "
                       f"second index beside them would not be this one" if state ==
                       "other_backend" else detail)
                problem(f"{target} is not built over: {why}. Move it aside to build "
                        f"{label} there.")
                demo_missed = True
            elif dry:
                will_build = True
                plan(f"build {label} ({len(wanted)} books, {ESTIMATE[which]}) into {target}: "
                     f"{command('scripts/ingest_demo_corpus.py' if full else 'scripts/ingest_demo_corpus.py --starter')}"
                     f" --backend {embed} --cache-dir {quoted(demo_cache())}, with "
                     f"LIBRARY_DB_PATH={quoted(target)}")
            else:
                note(f"demo library: building {label} into {target}"
                     + (f" ({detail} so far)" if state == "partial" else "")
                     + f" — {ESTIMATE[which]}; safe to interrupt and resume")
                status = build_demo(target, embed, full, demo_cache())
                if status != 0:
                    problem(f"the demo build stopped (status {status}). Every stage is cached: "
                            f"`{command('ayl init --demo' + (' --full' if full else ''))}` "
                            f"resumes it.")
                    return preflight.EXIT_NOT_READY
                demo_index = target
                changed = True

    if demo_missed:
        refused.append("the demo library asked for would not be built")
    # The closing check's index and ledger halves read files only, so they
    # are judged here for the dry run and the real run alike — over the demo
    # library when that is what the closing `ayl doctor` reads, else over the
    # reader's index; not over a demo library this run has yet to build.
    reads = demo_index if demo_index is not None else (None if will_build else reader_index)
    known, known_lines = (knowable_closing(reads, reads == reader_index, embed)
                          if reads is not None else (0, []))
    say("")
    if dry:
        for line in known_lines:
            problem(line)
        say("Dry run finished. Nothing was pulled, written or built.")
        unknown = []
        if "ollama" in (llm, embed):
            unknown.append("whether Ollama answers and has the models, and the pulls")
        if will_build:
            unknown.append("the demo build and the check over it")
        if unknown:
            say("Not checked without a request, so not part of this status: "
                + "; ".join(unknown) + ".")
        return 2 if demo_blocked else final_status(refused, known, None, demo_index, llm, embed)

    if not changed:
        say("Nothing to do: every step was already done, and nothing was changed.")
    # --- the closing check ---
    say("Check: `ayl doctor` " + ("over the demo library" if demo_index else
                                  "(with no books added yet, a missing index is expected)"))
    status = closing_check(demo_index)
    leftover = leftovers(status, demo_index, llm, embed)
    say("")
    for line in leftover:
        say(f"Left to you: {line}.")
    next_steps(demo_index, llm, reader_index)
    return 2 if demo_blocked else final_status(refused, known, status, demo_index, llm, embed)


def knowable_closing(index: Path, reader: bool, embed: str) -> tuple[int, list[str]]:
    """(status, problems) of the closing `ayl doctor`'s two halves that read
    files only: the index half of the preflight (no Ollama, no key) and the
    ledger reconciled against the tables. What needs a request is not here.
    An absent index of the reader's is what a first run leaves (0); a key
    a hosted configuration needs is the reader's to set (not a problem)."""
    problems = preflight.check_environment(index_only=True, db_path=index, backend=embed)
    kinds = set(problems.kinds) - {"no_key"}
    if kinds & {"no_db", "no_tables"}:
        return (0 if reader else preflight.EXIT_NO_INDEX), []
    if kinds:
        return preflight.EXIT_NOT_READY, [p for p, k in zip(problems, problems.kinds)
                                          if k != "no_key"]
    report = check_ledger(lancedb.connect(index), [f"transcripts_{embed}", f"cards_{embed}"])
    if not report.ok:
        return preflight.EXIT_NOT_READY, [f"the ledger and the index at {index} disagree "
                                          f"(`ayl doctor` lists where)"]
    return 0, []


def leftovers(status: int, demo_index: Path | None, llm: str, embed: str) -> list[str]:
    """What the closing check found that is the reader's to do, not a failure."""
    if status == preflight.EXIT_NO_INDEX and demo_index is None:
        return [f"your index is empty until you add books: `{command('ayl add <folder>')}`"]
    if status == preflight.EXIT_NO_KEY and "openrouter" in (llm, embed):
        return ["this configuration needs OPENROUTER_API_KEY, which is yours to set"]
    return []


def final_status(refused: list[str], known: int, doctor: int | None,
                 demo_index: Path | None, llm: str, embed: str) -> int:
    """One rule for the status of a run and of its dry run. A failure a step
    could tell without a write or a request is EXIT_NOT_READY in both; so is
    what the closing check's file-only halves find; the dry run stops there
    (`doctor` None), the real run adds what the doctor's request-bound half
    found, less what is the reader's to do (`leftovers`)."""
    if refused or known:
        return preflight.EXIT_NOT_READY if refused or known != preflight.EXIT_NO_INDEX \
            else known
    if doctor is None or doctor == 0 or leftovers(doctor, demo_index, llm, embed):
        return 0
    return doctor


def next_steps(demo_index: Path | None, llm: str, reader_index: Path) -> None:
    say("Next steps:")
    say(f"  {command('ayl add ~/books')}")
    say(f"      index your own .txt / .md books into {reader_index}, then ask:")
    say(f"      {command('ayl ask')} \"...\"")
    if demo_index is not None:
        say(f"  LIBRARY_DB_PATH={quoted(demo_index)} {command('ayl ask')} \"{FIRST_QUESTION}\"")
        say("      the demo library, asked by naming its index; `ayl books` and `ayl ui` take")
        say("      the same LIBRARY_DB_PATH")
    if llm == "openrouter":
        say("      the hosted answering model needs OPENROUTER_API_KEY first, and is billed per")
        say("      question (docs/cost.md)")
    else:
        say("      no account, no key, nothing to pay: the answer is written on this machine")
    say(f"  AYL_ALLOW_DEFAULT_LOGIN=1 {command('--extra ui ayl ui') if REPO_ROOT else 'ayl ui'}")
    say("      the web chat on 127.0.0.1, login admin / change-me; set CHAINLIT_USERNAME and")
    say("      CHAINLIT_PASSWORD for a real one and drop the variable")


class Progress:
    """One pull's progress, on one line that rewrites itself on a terminal
    and as one line per stage elsewhere (a log has no carriage returns)."""

    def __init__(self, model: str):
        self.model, self.last = model, None
        self.live = sys.stdout.isatty()

    def __call__(self, status: str, completed: int | None, total: int | None) -> None:
        if total and self.live:
            share = 100 * (completed or 0) // total
            sys.stdout.write(f"\r       {self.model}: {status} {share}% of "
                             f"{total / 1e9:.1f} GB   ")
            sys.stdout.flush()
        elif status != self.last:
            if self.live:
                sys.stdout.write("\r")
            note(f"{self.model}: {status}")
        self.last = status
