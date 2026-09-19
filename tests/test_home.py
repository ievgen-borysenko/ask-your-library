"""AYL_HOME: the reader's own folder, outside any checkout (#58, ADR-026 later).

What is never shared is written there and nowhere inside a repository —
`.gitignore` is not a boundary — so the guard is a check on the resolved path,
tested here against a git directory, a linked worktree's `.git` file, a folder
that does not exist yet and a symlink that points into a checkout.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ask_your_library import config, home

REPO = Path(__file__).resolve().parents[1]


def test_the_default_is_askyourlibrary_in_the_home_directory(tmp_path):
    """Read in a fresh interpreter, so the value is config.py's own default and
    not whatever this test session set. Run from an empty folder, so no `.env`
    is found either."""
    env = {key: value for key, value in os.environ.items() if key != "AYL_HOME"}
    env["HOME"] = str(tmp_path / "reader")
    out = subprocess.run([sys.executable, "-c",
                          "from ask_your_library import config; print(config.AYL_HOME)"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == str(tmp_path / "reader" / "AskYourLibrary")


def test_the_variable_overrides_the_default_and_a_tilde_is_expanded(tmp_path):
    env = dict(os.environ, AYL_HOME="~/elsewhere", HOME=str(tmp_path / "reader"))
    out = subprocess.run([sys.executable, "-c",
                          "from ask_your_library import config; print(config.AYL_HOME)"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == str(tmp_path / "reader" / "elsewhere")


def test_a_folder_outside_any_repository_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AYL_HOME", tmp_path / "ayl")
    folder = home.private_dir("cards", "tech")
    assert folder == (tmp_path / "ayl" / "cards" / "tech").resolve()
    assert not folder.exists(), "the path is returned; the writer creates it"


@pytest.mark.parametrize("git_marker", ["dir", "file"])
def test_a_folder_inside_a_git_work_tree_is_refused(tmp_path, monkeypatch, git_marker):
    """A `.git` directory, or the `.git` file of a linked worktree or submodule,
    anywhere above the folder — even when the folder itself does not exist yet."""
    repo = tmp_path / "repo"
    repo.mkdir()
    if git_marker == "dir":
        (repo / ".git").mkdir()
    else:
        (repo / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    monkeypatch.setattr(config, "AYL_HOME", repo / "not" / "yet" / "there")
    assert home.git_work_tree_of(repo / "not" / "yet") == repo.resolve()
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        home.private_dir("cards", "tech")


def test_a_real_git_repository_is_refused(tmp_path, monkeypatch):
    repo = tmp_path / "real"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        home.private_dir("cards", "tech")


def test_a_symlink_into_a_repository_is_refused(tmp_path, monkeypatch):
    """Resolved before it is checked: a link from outside that lands in a
    checkout is inside it."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "inside").mkdir()
    link = tmp_path / "outside-looking"
    link.symlink_to(repo / "inside")
    monkeypatch.setattr(config, "AYL_HOME", link)
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        home.private_dir("cards")


@pytest.mark.skipif(not (REPO / ".git").exists(), reason="not a git checkout")
def test_this_checkout_is_refused(monkeypatch):
    monkeypatch.setattr(config, "AYL_HOME", REPO / "private")
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        home.private_dir("cards", "tech")
