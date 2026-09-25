"""AYL_HOME: the reader's own folder, outside any checkout (#58, ADR-026).

What is never shared is written there and nowhere inside a repository —
`.gitignore` is not a boundary — so the guard is a check on the resolved path,
tested here against a git directory, a linked worktree's `.git` file, a folder
that does not exist yet and a symlink that points into a checkout — for the
local cards and, since ADR-026, for the default index, whose refusal names the
variable that puts it elsewhere.
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


def test_the_default_index_is_in_the_home_folder_and_not_the_working_directory(tmp_path):
    """Read in a fresh interpreter with neither AYL_HOME nor LIBRARY_DB_PATH
    set: config.py's own answer, `~/AskYourLibrary/index`."""
    env = {key: value for key, value in os.environ.items()
           if key not in ("AYL_HOME", "LIBRARY_DB_PATH")}
    env["HOME"] = str(tmp_path / "reader")
    out = subprocess.run([sys.executable, "-c",
                          "from ask_your_library import config; print(config.DB_PATH)"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == str((tmp_path / "reader").resolve() / "AskYourLibrary" / "index")


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


@pytest.mark.parametrize("git_marker", ["dir", "file"])
def test_the_index_inside_a_git_work_tree_is_refused_naming_its_variable(tmp_path, monkeypatch,
                                                                        git_marker):
    """The index holds the full text of what it was built from. Refused like a
    card, and the refusal names LIBRARY_DB_PATH — the one-line way to put an
    index elsewhere without moving everything else AYL_HOME holds."""
    repo = tmp_path / "repo"
    repo.mkdir()
    if git_marker == "dir":
        (repo / ".git").mkdir()
    else:
        (repo / ".git").write_text("gitdir: /somewhere/else\n", encoding="utf-8")
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    with pytest.raises(RuntimeError, match="inside the git work tree") as refused:
        home.private_dir("index")
    assert "Set LIBRARY_DB_PATH to put the index somewhere else, or set AYL_HOME" in str(
        refused.value)


def test_a_folder_that_alone_links_into_a_checkout_is_named_not_ayl_home(tmp_path, monkeypatch):
    """AYL_HOME outside any repository, and only `$AYL_HOME/index` a symlink
    into one: the refusal says which path lands in the checkout, and does not
    claim AYL_HOME does."""
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "inside").mkdir()
    ayl = tmp_path / "ayl"
    ayl.mkdir()
    (ayl / "index").symlink_to(repo / "inside")
    monkeypatch.setattr(config, "AYL_HOME", ayl)
    with pytest.raises(RuntimeError) as refused:
        home.private_dir("index")
    message = str(refused.value)
    assert message.startswith(f"{ayl.resolve() / 'index'} resolves to "
                              f"{(repo / 'inside').resolve()}, inside the git work tree "
                              f"{repo.resolve()}")
    assert "AYL_HOME resolves to" not in message
    assert "Set LIBRARY_DB_PATH" in message


def test_ayl_home_inside_a_checkout_is_named_as_such(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    with pytest.raises(RuntimeError) as refused:
        home.private_dir("index")
    assert str(refused.value).startswith(f"AYL_HOME resolves to {(repo / 'ayl').resolve()}, "
                                         f"inside the git work tree {repo.resolve()}")


def test_a_card_refusal_names_no_variable_it_does_not_have(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    with pytest.raises(RuntimeError) as refused:
        home.private_dir("cards", "tech")
    assert "LIBRARY_DB_PATH" not in str(refused.value)
    assert "Set AYL_HOME to a folder outside any repository" in str(refused.value)


def test_the_index_outside_any_repository_is_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AYL_HOME", tmp_path / "ayl")
    assert home.private_dir("index") == (tmp_path / "ayl" / "index").resolve()


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
@pytest.mark.parametrize("parts", [("cards", "tech"), ("index",)])
def test_this_checkout_is_refused(monkeypatch, parts):
    monkeypatch.setattr(config, "AYL_HOME", REPO / "private")
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        home.private_dir(*parts)


def test_a_file_that_is_a_symlink_is_refused(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    folder = tmp_path / "ayl"
    folder.mkdir()
    (folder / "card.md").symlink_to(repo / "card.md")
    with pytest.raises(RuntimeError, match="symlink"):
        home.private_file(folder / "card.md")
    assert home.private_file(folder / "other.md") == folder / "other.md"
