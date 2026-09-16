"""One rule for taking this machine out of a piece of text.

An absolute path travels further than the code that produced it: a failure
message reaches the CLI's error line, the web chat, an eval report, its JSON
sidecar and the committed summary `eval/summarize_report.py` writes; a planner
recording is committed as it stands. A `FileNotFoundError` names the file it
could not open, and under a home directory that name is the reader's login. The
message stays whole — only the part that identifies a machine is replaced.

It lived in two places (the runner and the eval harness) with a repo root
derived two different ways; this is the one home, so the two cannot drift.
"""
from pathlib import Path


def _repo_root() -> str:
    """The checkout this package is being run from, or "" when it is not being
    run from one.

    `src/ask_your_library/paths.py` -> the directory above `src/`, which is the
    repository when the package is used from a source tree (every eval run, the
    tests, a `uv run` from the clone). Installed as a wheel the same walk lands
    inside `site-packages`, which is not a repository and whose name tells a
    reader nothing: `pyproject.toml` is what decides, and without it there is no
    repo prefix at all — the home directory below still covers what matters.
    """
    root = Path(__file__).resolve().parents[2]
    return str(root) if (root / "pyproject.toml").is_file() else ""


REPO_ROOT = _repo_root()


def redact_paths(text: str) -> str:
    """The same text with this machine's absolute paths replaced by `<repo>`
    or `~`."""
    home = str(Path.home())
    # the repo first: it usually LIVES under the home directory, and the longer
    # prefix is the informative one
    for prefix, stand_in in ((REPO_ROOT, "<repo>"), (home, "~")):
        if prefix and prefix != "/":
            text = text.replace(prefix, stand_in)
    return text
