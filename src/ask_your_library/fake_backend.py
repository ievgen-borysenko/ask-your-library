"""The scripted-backend seam: how a UI test replaces the model and the library.

`tests/ui/test_ui_smoke.py` drives the REAL Chainlit server in a real browser.
A server that needs Ollama, an OpenRouter key and a built LanceDB cannot run in
CI and would not answer the same way twice, so that test starts the server with
a SCRIPT where the backend goes: the same substitution `tests/test_graph_e2e.py`
makes in-process — a scripted model behind `llm.llm`, the two library readers
`nodes` imports, `list_books`, and the preflight that would otherwise report the
missing index — made inside a server process, by the server itself, before the
graph is built.

The seam is one call, `install_fake_backend()`, near the top of `ui/app.py`. It is
inert unless BOTH of these are set:

    AYL_UI_FAKE_BACKEND          path of a Python file that defines install()
    AYL_UI_FAKE_BACKEND_CONFIRM  exactly CONFIRM_PHRASE

Two variables, because one is too easy to inherit. A path without the phrase is
an error at startup — the server refuses to come up rather than serve answers
that look real and came out of a script — and the phrase without a path does
nothing. With neither set, which is every production start, this module reads
two environment variables, finds nothing, and returns before it imports or
patches anything: the process that follows is the process that ran before this
file existed.

Loading the script EXECUTES it. That is what it is for, and it is also why the
gate is what it is: anything able to set these variables in the server's
environment can already run code as the server. Neither variable belongs in a
`.env`, a shell profile or a deployment unit; see docs/configuration.md and
SECURITY.md.

A `.env` is not merely bad practice here, it is a live path: `chainlit`'s own
`__init__` calls `load_dotenv(os.getcwd() + "/.env")` at import, i.e. before
this module is even imported, so by the time `install_fake_backend()` reads the
environment, a `.env` in the directory the server was started from has already
put both names into it. Hence the dotenv check below: when either name is a KEY
in such a file, the seam refuses outright, whatever the value there and whatever
the process environment says. The rule is "these names are exported by the
person starting the server, or not set at all" — no guessing where a value came
from, and the refusal is the same shape as every other one here. The check runs
whenever either name is PRESENT in the environment, blank or not: a bare
`AYL_UI_FAKE_BACKEND=` line, or the confirmation on its own, is exactly the
shape a `.env` takes, and those must reach the refusal rather than the quiet
return they name nothing for.
"""
import importlib.util
import os
import sys
from pathlib import Path

ENABLE_VAR = "AYL_UI_FAKE_BACKEND"
CONFIRM_VAR = "AYL_UI_FAKE_BACKEND_CONFIRM"
# Spelled out rather than "1": a person who types this has read what it does.
CONFIRM_PHRASE = "this-server-answers-from-a-script"
# The name the loaded file gets in sys.modules. Under the package's namespace
# and with a leading underscore, so it cannot shadow a real module and reads as
# private in a traceback.
MODULE_NAME = "ask_your_library._ui_fake_backend"

BANNER = ("FAKE BACKEND: this server answers from a script, not from a model or an index "
          "({path}). Never serve this to anyone.")


def _dotenv_files() -> list[Path]:
    """The `.env` files whose contents are already in `os.environ` by the time
    this runs. Exactly two candidates, both cheap, and neither is guessed:

      * `<cwd>/.env` — what `chainlit/__init__.py` loads, by that literal path;
      * whatever `find_dotenv(usecwd=True)` finds walking up from the working
        directory — what `config.load_dotenv()` reads under any other entry
        point.

    `dotenv` is a declared dependency of this project, but it is imported HERE
    and not at module level: the unarmed path must stay two environment reads
    and nothing else.
    """
    from dotenv import find_dotenv

    found = find_dotenv(usecwd=True)
    candidates = [Path.cwd() / ".env"] + ([Path(found)] if found else [])
    seen, files = set(), []
    for candidate in candidates:
        resolved = candidate.expanduser()
        if resolved.is_file() and str(resolved) not in seen:
            seen.add(str(resolved))
            files.append(resolved)
    return files


def _named_in_a_dotenv() -> tuple[Path, str] | None:
    """The first (file, name) where one of the two variables is a KEY, or None.

    A file that cannot be parsed is treated as naming nothing: `dotenv` itself
    skips what it cannot read, and a refusal nobody can explain would be worse
    than the sentence in SECURITY.md.
    """
    from dotenv import dotenv_values

    for path in _dotenv_files():
        try:
            keys = set(dotenv_values(path))
        except Exception:
            continue
        for name in (ENABLE_VAR, CONFIRM_VAR):
            if name in keys:
                return path, name
    return None


def install_fake_backend() -> str | None:
    """Run the scripted backend named by the environment, or nothing at all.

    Returns the path of the script that was installed, or None when the seam is
    off (the normal case). Raises SystemExit when the seam is asked for and
    cannot be honoured: a half-installed backend is the one outcome that must
    not reach a reader, because it looks exactly like a working one.
    """
    # PRESENT, not usable: `AYL_UI_FAKE_BACKEND=` with nothing after it, or the
    # confirmation on its own, are the shapes a `.env` line most easily takes,
    # and a seam that returned quietly on those would leave the refusal
    # SECURITY.md promises unenforced for exactly the cases that promise is
    # about. Anything in the environment under either name earns the file check.
    present = [name for name in (ENABLE_VAR, CONFIRM_VAR) if name in os.environ]
    if not present:
        # The ordinary start: two lookups, no file opened, nothing patched.
        return None
    # Before the path or the confirmation is read: a `.env` that names either
    # variable is how this gets armed without anyone deciding to arm it, and
    # chainlit has already loaded that file into os.environ by the time this
    # runs (see the module docstring).
    planted = _named_in_a_dotenv()
    if planted:
        path, name = planted
        raise SystemExit(
            f"{name} is set in {path}. This server answers from a script only when the person "
            f"starting it says so in its environment, and a file that is read at import — "
            f"chainlit loads <cwd>/.env before anything here runs — is not that. Remove the "
            f"line and export the two variables for the command instead.")

    requested = os.environ.get(ENABLE_VAR, "").strip()
    if not requested:
        # The confirmation without a script names nothing to install; a blank
        # path is the same. Neither is an error — only the file above is.
        return None
    if os.environ.get(CONFIRM_VAR, "").strip() != CONFIRM_PHRASE:
        raise SystemExit(
            f"{ENABLE_VAR} is set, so this server would answer from a script instead of "
            f"a model and an index. That needs saying twice: export "
            f"{CONFIRM_VAR}={CONFIRM_PHRASE} as well, or unset {ENABLE_VAR}.")

    path = Path(requested).expanduser()
    if not path.is_file():
        raise SystemExit(f"{ENABLE_VAR}={requested}: no such file")

    spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{ENABLE_VAR}={requested}: not an importable Python file")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)

    install = getattr(module, "install", None)
    if not callable(install):
        raise SystemExit(f"{ENABLE_VAR}={requested}: the file defines no install() to call")
    install()

    # stderr, not a chat message: the operator who started the process is the
    # one who has to know, and the rendering path stays exactly as it ships.
    print(BANNER.format(path=path), file=sys.stderr, flush=True)
    return str(path)
