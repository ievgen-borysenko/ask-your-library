"""The scripted-backend seam: how a UI test replaces the model and the library.

`tests/ui/test_ui_smoke.py` drives the REAL Chainlit server in a real browser.
A server that needs Ollama, an OpenRouter key and a built LanceDB cannot run in
CI and would not answer the same way twice, so that test starts the server with
a SCRIPT where the backend goes: the same substitution `tests/test_graph_e2e.py`
makes in-process — a scripted model behind `llm.llm`, the two library readers
`nodes` imports, `list_books`, and the preflight that would otherwise report the
missing index — made inside a server process, by the server itself, before the
graph is built.

The seam is one call, `install_fake_backend()`, near the top of `ui.py`. It is
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


def install_fake_backend() -> str | None:
    """Run the scripted backend named by the environment, or nothing at all.

    Returns the path of the script that was installed, or None when the seam is
    off (the normal case). Raises SystemExit when the seam is asked for and
    cannot be honoured: a half-installed backend is the one outcome that must
    not reach a reader, because it looks exactly like a working one.
    """
    requested = os.environ.get(ENABLE_VAR, "").strip()
    if not requested:
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
