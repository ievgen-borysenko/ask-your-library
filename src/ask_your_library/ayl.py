"""Ask Your Library — `ayl`, the one command the rest hang off.

  uv run ayl ask "What does Marcus Aurelius say about anger?"
  uv run ayl add ~/books          # index a folder of .txt / .md books
  uv run ayl doctor               # the environment and the index, both halves
  uv run ayl books                # what the index holds, without a model call
  uv run ayl ui                   # the Chainlit web chat

This is a router, not a second implementation. `ayl ask` is `cli.main`; `ayl
add`, `doctor`, `backup` and `restore` are `ingest.add_folder.main`, which is
one parser with a flag per verb. Each subcommand hands that parser the
arguments written after the command name, unread, so every flag those two
accept keeps working verbatim under the new name and their exit codes are this
command's exit codes. `books` is the only new code here, and `ui` is a
`chainlit run` of the repository's ui.py.

`ask-library` and `ayl-add` are still installed and still run the same code;
each prints one deprecation line to stderr and goes at 0.6.0.
"""
import argparse
import subprocess
import sys
from pathlib import Path

from . import cli
from .catalog import render_catalog, run_catalog
from .config import DB_PATH, EMBED_BACKEND
from .i18n import t
from .ingest import add_folder
from .paths import REPO_ROOT
from .preflight import PreflightResult, check_environment, exit_code

# The command names, and the one-line summary `ayl --help` lists each under.
SUMMARY = {
    "ask": "ask the library a question, or open the interactive chat",
    "add": "index a folder of .txt / .md books",
    "doctor": "report the environment, then reconcile the ledger against the index",
    "backup": "copy the index and the web UI's chat database into DIR/<timestamp>/",
    "restore": "verify a backup directory against its manifest and put it back",
    "books": "list the books the index holds (no model call)",
    "ui": "run the Chainlit web chat against this library, on loopback",
}


def build_parser() -> argparse.ArgumentParser:
    """`ayl` itself: the command names, `--help` and `--version`, nothing else.

    The subcommands' options are deliberately not re-declared here. Each one's
    parser lives with the code that runs it — that is what makes `ayl add
    --rebuild --backup <dir>` the same command line `ayl-add` always took, and
    what keeps the docs-as-code check of #72 comparing the docs against the
    parser a reader actually meets. The subparsers below carry no arguments;
    they exist so that `ayl --help` lists the commands and an unknown one is
    argparse's own error rather than a sentence of ours."""
    parser = argparse.ArgumentParser(
        prog="ayl",
        description="Agentic RAG over your own book library.",
        epilog="`ayl <command> --help` prints what that command accepts. Everything "
               "else is configured through environment variables; see .env.example.")
    parser.add_argument("--version", action="version",
                        version=f"ayl {cli.package_version()}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for name, summary in SUMMARY.items():
        sub.add_parser(name, help=summary, add_help=False)
    return parser


def split_argv(argv: list[str]) -> tuple[list[str], list[str]]:
    """(what `ayl` parses, what the command is handed) — everything from the
    first command name on belongs to the command, untouched.

    argparse cannot do this split itself: `nargs=REMAINDER` stops at the first
    argument that looks like an option, so `ayl ask --verbose "..."` would lose
    `--verbose` to `ayl`'s own parser and exit 2. When no command name is
    there the whole line is `ayl`'s — `--help`, `--version`, a typo — and
    argparse reports it as it always would.

    This is correct only while `ayl` itself has no option that TAKES A VALUE:
    `ayl --lang ask "..."` would cut at the value and call the `ask` command.
    `--help` and `--version` take none. Anything added here that does must
    either be parsed before this split or be a subcommand's flag instead."""
    for at, token in enumerate(argv):
        if token in SUMMARY:
            return argv[:at + 1], argv[at + 1:]
    return argv, []


def report_environment(index_only: bool = False, db_path: Path | None = None,
                       backend: str | None = None) -> PreflightResult:
    """The preflight block, printed the way `ayl ask` prints it before it
    refuses to run: every problem, then the non-fatal notices. Returns the
    result so the caller can turn it into an exit status; printing is all this
    does.

    `index_only`, `db_path` and `backend` are `preflight.check_environment`'s,
    and mean there what they mean to the command: the half a command that only
    reads the index can fail on, and the index it was pointed at."""
    problems = check_environment(index_only=index_only, db_path=db_path, backend=backend)
    if problems:
        cli.say(t("pf_header"), error=True)
        for problem in problems:
            cli.say(f"  - {problem}", error=True)
    notices = getattr(problems, "notices", [])
    if notices:
        cli.say(t("pf_notice_header"), error=True)
        for notice in notices:
            cli.say(f"  - {notice}", error=True)
    return problems


# --- the subcommands --------------------------------------------------------

def run_ask(rest: list[str]) -> int:
    """`ayl ask` is `ask-library`: the same parser, the same run, the same exit
    codes — which leave `cli.main` as SystemExit and pass straight through."""
    cli.main(rest, prog="ayl ask")
    return 0


def run_add(rest: list[str]) -> int:
    return add_folder.main(rest, prog="ayl add")


# A flag of the ingest parser that decides WHICH command runs. The parser
# answers them in its own order — `--doctor` before `--backup` — so one of them
# written under another verb silently replaces it: `ayl backup <dir> --doctor`
# took no copy, reported a clean index and exited 0. Each is refused under a
# verb that is not its own, naming what to type instead.
VERB_FLAGS = {"--doctor": "ayl doctor", "--backup": "ayl backup",
              "--restore": "ayl restore", "--rebuild": "ayl add <folder> --rebuild"}

# What every verb below says about the two options it forwards. Written for the
# verb rather than copied from the ingest parser, which has to describe what
# `--force` means to `--restore` AND to `--rebuild` — half a paragraph about
# something else under `ayl restore`.
DB_HELP = f"the LanceDB directory to work on (default: LIBRARY_DB_PATH, now {DB_PATH})"
BACKEND_HELP = ("the embedding backend, which selects the table suffix "
                f"(default: EMBED_BACKEND, now {EMBED_BACKEND})")
HATCH = ("Anything after a bare `--` is passed to the ingest command verbatim, "
         "for a flag this verb does not declare; `ayl add --help` lists them all.")


def split_hatch(prog: str, rest: list[str]) -> tuple[list[str], list[str]]:
    """(this verb's arguments, the escape hatch) — everything after a bare `--`
    goes to the ingest command untouched.

    argparse never sees the `--` (it would eat it), and the hatch is screened
    for VERB_FLAGS on the way through: a flag that changes which command runs
    has to be typed as that command."""
    at = rest.index("--") if "--" in rest else len(rest)
    extra = rest[at + 1:]
    for argument in extra:
        verb = VERB_FLAGS.get(argument.split("=")[0])
        if verb:
            cli.say(f"{argument} is a command of its own, not an option of `{prog}`: "
                    f"run `{verb}` instead", error=True)
            # 2 is what argparse gives a bad command line, and this is one.
            raise SystemExit(2)
    return rest[:at], extra


def _db_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=Path, default=None, metavar="DIR", help=DB_HELP)


def _backend_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", default=None, choices=("ollama", "openrouter"),
                        help=BACKEND_HELP)


def _chat_db_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chat-db", type=Path, default=None, metavar="PATH",
                        help="the web UI's chat database (default: AYL_CHAINLIT_DIR, "
                             "else .chainlit/chat.db)")


def _forwarded(args) -> list[str]:
    """The options this verb parsed, back in the spelling the ingest parser
    takes them in. Only what the reader actually typed: an option left out
    means "whatever is configured", which is that parser's own default."""
    argv: list[str] = []
    if getattr(args, "db", None) is not None:
        argv += ["--db", str(args.db.expanduser())]
    if getattr(args, "backend", None) is not None:
        argv += ["--backend", args.backend]
    if getattr(args, "chat_db", None) is not None:
        argv += ["--chat-db", str(args.chat_db.expanduser())]
    if getattr(args, "force", False):
        argv.append("--force")
    return argv


def run_backup(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ayl backup",
        description="Copy the index and the web UI's chat database into DIR/<timestamp>/ "
                    "with a MANIFEST.json (what was copied, the stamps, the row counts, a "
                    "sha256 per file). Refuses while an ingest is running. Take one before "
                    "any upgrade that rebuilds.",
        epilog=HATCH)
    parser.add_argument("dir", type=Path, help="where the timestamped copy is written")
    _db_option(parser)
    _chat_db_option(parser)
    mine, extra = split_hatch("ayl backup", rest)
    args = parser.parse_args(mine)
    return add_folder.main(["--backup", str(args.dir.expanduser()), *_forwarded(args), *extra],
                           prog="ayl backup")


def run_restore(rest: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="ayl restore",
        description="Verify a backup directory against its manifest and put it back. The "
                    "verification is not optional and --force does not skip it.",
        epilog=HATCH)
    parser.add_argument("dir", type=Path, metavar="BACKUP_DIR",
                        help="the timestamped directory `ayl backup` wrote")
    _db_option(parser)
    _chat_db_option(parser)
    parser.add_argument("--force", action="store_true",
                        help="move the index that is there aside (it is kept, not deleted) "
                             "and restore over it, replacing the chat database too; without "
                             "it an existing index is not overwritten")
    mine, extra = split_hatch("ayl restore", rest)
    args = parser.parse_args(mine)
    return add_folder.main(["--restore", str(args.dir.expanduser()), *_forwarded(args), *extra],
                           prog="ayl restore")


def run_doctor(rest: list[str]) -> int:
    """Both halves of "is this thing ready", in one command: the environment
    (the preflight block `ayl ask` prints before it refuses) and the index (the
    ledger reconciled against the tables).

    Both always run — a broken environment must not hide index drift, which is
    the thing a reader came to this command for — and both are aimed at the
    SAME index: a preflight left pointing at LIBRARY_DB_PATH while the doctor
    read `--db` reported the configured database as missing and exited 3 over
    an index it had just found healthy.

    The status is the preflight's classification when the environment is the
    problem, so a wrapper script reads 5 for "no Ollama" and 3 for "no index"
    here exactly as it does from `ayl ask`; otherwise it is the doctor's own 0
    (they agree) or 1."""
    parser = argparse.ArgumentParser(
        prog="ayl doctor",
        description="Report whether this machine is ready: the environment (model server, "
                    "key, index) and then the book ledger reconciled against the index "
                    "tables, with the stamps and the chunk lengths. Writes nothing.",
        epilog=HATCH)
    _db_option(parser)
    _backend_option(parser)
    mine, extra = split_hatch("ayl doctor", rest)
    args = parser.parse_args(mine)

    db = args.db.expanduser() if args.db is not None else None
    problems = report_environment(db_path=db, backend=args.backend)
    status = add_folder.main(["--doctor", *_forwarded(args), *extra], prog="ayl doctor")
    return exit_code(problems) if problems else status


def run_books(rest: list[str]) -> int:
    """The catalogue listing, without the model call it takes to reach it
    today: a question routed to `mode="catalog"` ends in these same two
    functions, and `list_books` is index metadata, so nothing here is worth a
    planner call.

    The preflight still runs, which is what makes a missing index exit 3 and a
    sentence rather than a traceback out of LanceDB — but only its index half:
    this command calls no model and embeds nothing, so an Ollama that is not
    running and an unset key are not its problems and must not be its exit
    status."""
    argparse.ArgumentParser(
        prog="ayl books",
        description="List the books in the index, as the agent's catalogue answer "
                    "lists them: no model call, no key, nothing paid.").parse_args(rest)
    problems = report_environment(index_only=True)
    if problems:
        return exit_code(problems)
    # Titles are index metadata, i.e. data: printed through `say`, as every
    # other line carrying corpus text is.
    cli.say(render_catalog(run_catalog({"op": "list", "title": "", "author": ""})))
    return 0


def ui_script() -> Path | None:
    """`ui.py` of the checkout this package is being run from, or None.

    The walk `paths._repo_root` makes, for the same reason: installed as a
    wheel there is no repository above the package, and the web chat is not in
    the distribution — `src/ask_your_library` is (pyproject). Saying so is more
    use than letting `chainlit` fail on a path that is not there."""
    if not REPO_ROOT:
        return None
    script = Path(REPO_ROOT) / "ui.py"
    return script if script.is_file() else None


def run_ui(rest: list[str]) -> int:
    """`chainlit run <repo>/ui.py --host 127.0.0.1`, which is what the docs
    have told a reader to type by hand.

    Loopback is written into the command rather than left to Chainlit's
    default, because this is a single-user local demo with no authorization
    model behind its login form (SECURITY.md). The arguments a reader adds go
    after it, so exposing the server is still something they have to type out
    themselves.

    It runs IN the checkout, and that is not cosmetic: Chainlit derives its app
    root from `CHAINLIT_APP_ROOT or os.getcwd()` and WRITES a default
    `.chainlit/config.toml` when it finds none there. Started from anywhere
    else, the committed config is not the one that loads — `unsafe_allow_html`
    (the provenance badge and the metrics footer), `auto_tag_thread = false`,
    the narrowed `allow_origins` and the `[features.mcp] enabled = false` that
    SECURITY.md names are all silently back at Chainlit's defaults, and a
    `.chainlit/` appears in whatever directory the reader happened to be in."""
    parser = argparse.ArgumentParser(
        prog="ayl ui",
        description="Run the Chainlit web chat against this library, bound to 127.0.0.1.",
        epilog="Every other argument goes to `chainlit run` verbatim (`-w` to reload "
               "on edit, `--port` for another port). Needs the `ui` extra and a "
               "checkout: the web chat is not in the wheel yet.")
    _, extra = parser.parse_known_args(rest)
    script = ui_script()
    if script is None:
        cli.say("`ayl ui` runs the repository's ui.py, and this installation has none: "
                "the wheel ships src/ask_your_library only. Clone the repository and run "
                "`uv run --extra ui ayl ui` from it.", error=True)
        return 1
    try:
        return subprocess.call(["chainlit", "run", str(script), "--host", "127.0.0.1", *extra],
                               cwd=script.parent)
    except FileNotFoundError:
        cli.say("chainlit is not installed: it is the `ui` extra — "
                "`uv run --extra ui ayl ui`, or `uv sync --extra ui` once.", error=True)
        return 1


DISPATCH = {"ask": run_ask, "add": run_add, "doctor": run_doctor, "backup": run_backup,
            "restore": run_restore, "books": run_books, "ui": run_ui}


def main(argv: list[str] | None = None) -> int:
    head, rest = split_argv(list(sys.argv[1:] if argv is None else argv))
    args = build_parser().parse_args(head)
    return DISPATCH[args.command](rest)


if __name__ == "__main__":
    raise SystemExit(main())
