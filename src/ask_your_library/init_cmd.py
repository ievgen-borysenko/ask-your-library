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

from . import config, home, ollama, preflight
from .cli import say
from .i18n import t
from .ingest.ledger import INDEXED, open_ledger
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
                       "embeddings stay on this machine"}

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
# question, a passage or a trace goes, and where the data is kept.
RESOLVED = ("LLM_BACKEND", "EMBED_BACKEND", "OLLAMA_URL", "OLLAMA_LLM_MODEL",
            "OLLAMA_EMBED_MODEL", "OPENROUTER_BASE_URL", "ORCHESTRATOR_MODEL",
            "OPENROUTER_API_KEY", "LIBRARY_DB_PATH", "AYL_HOME", "LANGSMITH_TRACING_V2",
            "LANGCHAIN_TRACING_V2", "LANGCHAIN_API_KEY")
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
                             "Ollama, no file written, no index created")
    parser.add_argument("--print-env-resolution", action="store_true",
                        help="print each setting that decides where your data goes, its value "
                             "(credentials as <set, N chars>) and where it came from — "
                             "exported, a .env, $AYL_HOME/config.env or the default — and exit")
    return parser


# --- step 2: the mode -----------------------------------------------------------

def existing_configuration() -> Path | None:
    """The file that already configures this machine, or None: the working
    directory's `.env` (or a parent's) first, then `$AYL_HOME/config.env`."""
    if config.PROJECT_ENV is not None:
        return config.PROJECT_ENV
    return config.HOME_CONFIG if config.HOME_CONFIG.is_file() else None


def mode_of(llm_backend: str, embed_backend: str) -> str | None:
    for name, values in MODES.items():
        if (values["LLM_BACKEND"], values["EMBED_BACKEND"]) == (llm_backend, embed_backend):
            return name
    return None


def contradictions(mode: str) -> list[str]:
    """Exported switches that would override the file this run writes:
    python-dotenv never overrides an exported name, so the file would say one
    mode and every command would run another."""
    wanted = MODES[mode]
    loaded = {"LLM_BACKEND": config.LLM_BACKEND, "EMBED_BACKEND": config.EMBED_BACKEND}
    return [f"{name}={loaded[name]}" for name in SWITCHES
            if name in config.EXPORTED and loaded[name] != wanted[name]]


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


def manifest_ids(full: bool) -> list[str]:
    """The manifest entries a demo build covers: the starter subset, or every
    entry (books and canaries) for `--full` — what the script builds for the
    same flag."""
    manifest = yaml.safe_load((Path(REPO_ROOT) / "corpus" / "manifest.yaml")
                              .read_text(encoding="utf-8"))
    entries = manifest["books"] + manifest["canaries"]
    return [entry["id"] for entry in entries if full or entry.get("starter") is True]


def demo_state(path: Path, backend: str, wanted: set[str]) -> tuple[str, str]:
    """(state, detail) of the index at `path` as a demo library for
    `wanted` manifest ids. Reads only an index that exists; never creates one.

    `absent` nothing is built; `complete` every wanted book is indexed;
    `partial` a demo library holding fewer (a starter one, asked for --full);
    `other_backend` an index whose transcripts another embedding backend built
    — building beside it would be a second index in one folder; `foreign` an
    index holding a book no manifest entry built, or none that a ledger
    describes — rebuilding the table would replace them."""
    table = f"transcripts_{backend}"
    if not (path / f"{table}.lance").is_dir():
        others = sorted(p.name[:-len(".lance")] for p in path.glob("transcripts_*.lance")) \
            if path.is_dir() else []
        if others:
            return "other_backend", ", ".join(others)
        return "absent", ""
    rows = open_ledger(lancedb.connect(path)).all_rows()
    refs = [str(row.get("source_ref") or "") for row in rows]
    if not rows or any(not ref.startswith("manifest:") for ref in refs):
        return "foreign", ("no ledger describes its books" if not rows
                           else "it holds books that are not the demo corpus's")
    indexed = {str(row["source_ref"]).split(":", 1)[1] for row in rows
               if row.get("status") == INDEXED}
    if wanted <= indexed:
        return "complete", f"{len(wanted)} of {len(wanted)} books indexed"
    return "partial", f"{len(wanted & indexed)} of {len(wanted)} books indexed"


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
    say("Where each setting comes from, highest first: exported, then "
        f"{config.PROJECT_ENV or 'a .env in the working directory (none found)'}, then "
        f"{config.HOME_CONFIG}{'' if config.HOME_CONFIG.is_file() else ' (absent)'}, "
        f"then the default.")
    for name in RESOLVED:
        value = os.environ.get(name)
        if value is None:
            shown = "(unset)"
        elif any(part in name for part in SECRET_PARTS):
            shown = f"<set, {len(value)} chars>" if value else "(blank)"
        else:
            shown = value
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


def build_demo(path: Path, backend: str, full: bool) -> int:
    """The demo library, built by the script that has always built it, with
    its own stages, checksums, staging tables and ingest lock: run as that
    script, with `LIBRARY_DB_PATH` naming `path` (clause 1, so no notice and
    no second resolution)."""
    script = Path(REPO_ROOT) / "scripts" / "ingest_demo_corpus.py"
    argv = [sys.executable, str(script), "--backend", backend, *([] if full else ["--starter"])]
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

    # Step 2 is decided first, silently: step 1 needs to know whether this
    # configuration uses Ollama at all.
    existing = existing_configuration()
    if existing is not None:
        llm, embed = config.LLM_BACKEND, config.EMBED_BACKEND
        mode = mode_of(llm, embed)
    else:
        mode = args.mode or "local"
        clash = contradictions(mode)
        if clash:
            problem(f"{', '.join(clash)} is exported in this shell, and an exported variable "
                    f"wins over the file this run would write: every command would run that, "
                    f"not the {mode} mode. Unset it (or choose the mode it names with --mode) "
                    f"and run `ayl init` again. Nothing was changed.")
            return 2
        llm, embed = MODES[mode]["LLM_BACKEND"], MODES[mode]["EMBED_BACKEND"]

    # --- 1 ---
    url = config.OLLAMA_URL
    needs_ollama = "ollama" in (llm, embed)
    step(1, f"Model server: Ollama at {url}")
    pulled: frozenset = frozenset()
    if not needs_ollama:
        note("not needed: this configuration answers and embeds on OpenRouter")
    elif dry:
        plan(f"ask {url}/api/tags whether Ollama answers, and what it has pulled")
    else:
        reply = preflight.ollama_tags(url)
        if reply.kind == "no_ollama":
            problem(t("pf_no_ollama", url=url,
                      pulls=", ".join(f"`ollama pull {m}`"
                                      for m in preflight.pull_models(llm, embed))))
            return preflight.EXIT_NO_LOCAL_RUNTIME
        if reply.kind == "ollama_bad_reply":
            problem(t("pf_ollama_bad_reply", url=url, status=reply.status))
            return preflight.EXIT_NO_LOCAL_RUNTIME
        pulled = reply.names
        note(f"answering; {len(pulled)} model(s) pulled")

    # --- 2 ---
    step(2, f"Mode: {MODE_LINE.get(mode, f'LLM_BACKEND={llm}, EMBED_BACKEND={embed}')}")
    if existing is not None:
        note(f"read from {existing}, which already configures this machine")
        if args.mode and args.mode != mode:
            note(f"--mode {args.mode} was NOT applied: an existing configuration decides, and "
                 f"`ayl init` never rewrites one. Edit it (or move it aside) and run again.")
    else:
        note("chosen with --mode" if args.mode else "the default (--mode hosted for OpenRouter)")
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
        note(f"{existing} exists and is never rewritten; nothing was changed")
    else:
        target = home.ayl_home() / "config.env"
        text = config_text(mode)
        if dry:
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
        if mode == "hosted":
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
            problem(str(error))
    legacy = legacy_indexes()
    for path, notice in legacy:
        note(notice)
        if path.name == "lancedb" and demo_state(path, embed, set())[0] == "complete":
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
    if not want_demo:
        note(f"demo library: not built. `{command('ayl init --demo')}` builds six classics in "
             f"{ESTIMATE['starter']}, kept apart from your index")
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
            wanted = set(manifest_ids(full))
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
                plan(f"build {label} ({len(wanted)} books, {ESTIMATE[which]}) into {target}: "
                     f"{command('scripts/ingest_demo_corpus.py' if full else 'scripts/ingest_demo_corpus.py --starter')}"
                     f" --backend {embed}, with LIBRARY_DB_PATH={quoted(target)}")
            else:
                note(f"demo library: building {label} into {target}"
                     + (f" ({detail} so far)" if state == "partial" else "")
                     + f" — {ESTIMATE[which]}; safe to interrupt and resume")
                status = build_demo(target, embed, full)
                if status != 0:
                    problem(f"the demo build stopped (status {status}). Every stage is cached: "
                            f"`{command('ayl init --demo' + (' --full' if full else ''))}` "
                            f"resumes it.")
                    return preflight.EXIT_NOT_READY
                demo_index = target
                changed = True

    say("")
    if dry:
        say("Dry run finished. Nothing was pulled, written or built.")
        return 0

    if not changed:
        say("Nothing to do: every step was already done, and nothing was changed.")
    # --- the closing check ---
    say("Check: `ayl doctor` " + ("over the demo library" if demo_index else
                                  "(with no books added yet, a missing index is expected)"))
    status = closing_check(demo_index)
    leftover = []
    if status == preflight.EXIT_NO_INDEX and demo_index is None:
        leftover.append(f"your index is empty until you add books: `{command('ayl add <folder>')}`")
    elif status == preflight.EXIT_NO_KEY and llm == "openrouter":
        leftover.append("the hosted mode needs OPENROUTER_API_KEY, which is yours to set")
    say("")
    for line in leftover:
        say(f"Left to you: {line}.")
    next_steps(demo_index, llm, reader_index)
    if demo_missed:
        return preflight.EXIT_NOT_READY
    return 0 if leftover or status == 0 else status


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
