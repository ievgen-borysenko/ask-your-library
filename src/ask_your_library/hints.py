"""How a printed hint names a command, for the install it is printed on.

There are two installs, and they type the same command differently. From a
clone, `ayl` lives in the project's environment and is reached through
`uv run ayl ...`. Installed as a tool (`uv tool install git+...`) or from a
wheel, `ayl` is on PATH and `uv run` would run it in whatever project the
reader's shell happens to be in. `paths.REPO_ROOT` tells the two apart: it is
the checkout the package runs from, and empty when it runs from site-packages.

Every line printed to the reader that names a command goes through here, so a
hint can never tell a tool install to type `uv run`. Module docstrings written
for contributors may keep showing the clone's form; they are not printed.

`paths.REPO_ROOT` is read at call time, not imported by value, so a test that
stands in for either install patches that one name.
"""
from . import paths

REPO_URL = "https://github.com/ievgen-borysenko/ask-your-library"
# The configuration reference, as a URL: a tool install has no docs/ folder
# and no .env.example beside it, and a clone can open the same page.
CONFIG_DOCS = f"{REPO_URL}/blob/main/docs/configuration.md"


def from_clone() -> bool:
    """True when the package runs from a checkout of the repository."""
    return bool(paths.REPO_ROOT)


def command(text: str) -> str:
    """A command line as the reader types it here: through `uv run` in a
    clone, where `ayl` lives in the project's environment, bare elsewhere."""
    return f"uv run {text}" if from_clone() else text


def script(text: str) -> str:
    """A repository script (`scripts/...`), in backticks. It ships with the
    clone and not with the package, so outside a clone the hint says where
    to run it instead of pretending it is there."""
    line = f"`uv run {text}`"
    return line if from_clone() else f"{line} from a clone of the repository"


def ui_extra(version: str) -> str:
    """How to get the web chat's `ui` extra on this install, in backticks.

    A tool install is re-installed with the extra: uv takes a git source with
    an extra in the PEP 508 form `name[extra] @ git+URL@tag`. `version` is
    the installed one, so the line names the release already installed."""
    if from_clone():
        return "`uv run --extra ui ayl ui`, or `uv sync --extra ui` once"
    tag = f"@v{version}" if version and version != "unknown" else ""
    return f"`uv tool install --force 'ask-your-library[ui] @ git+{REPO_URL}{tag}'`"
