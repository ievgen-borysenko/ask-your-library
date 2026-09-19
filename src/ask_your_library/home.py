"""The reader's own folder, `AYL_HOME`, and the one rule that guards it.

Some files may be built on the reader's machine for the reader and never shared:
a model-written card of a work whose licence withholds sharing an adaptation
(CC BY-NC-ND 4.0 section 2(a)(1)(B)) is the first, the reader's own books, their
cards and their index (the private shelf, ADR-026) are next. Those files live
under `AYL_HOME` (default `~/AskYourLibrary`), outside any checkout, and never in
a folder inside the repository: a line in `.gitignore` is a convention a
`git add -f` walks through, and a folder that is not in the tree cannot be
committed by anyone.

So the rule is a check, not a default: `private_dir` refuses a folder that
resolves inside a git work tree — this repository's or any other — before
anything is written to it, and `private_file` does the same for the file itself,
so a symlink planted at the file's name cannot carry the write into a checkout.

What is detected is a `.git` directory or file in the path or above it. A
bare-repository setup whose work tree is elsewhere — dotfiles kept with
`git --git-dir=~/.dotfiles --work-tree=~` — leaves no `.git` in the home
directory and is NOT detected: with one, point AYL_HOME at a folder that setup
does not track.
"""
from pathlib import Path

from ask_your_library import config


def git_work_tree_of(path: Path) -> Path | None:
    """The git work tree `path` would be inside, or None.

    Resolved first, so a symlink that points into a checkout counts as inside
    it, and walked up from the nearest ancestor that exists, because the folder
    being checked is usually about to be created. A `.git` directory and a
    `.git` file (a linked worktree, a submodule) both mark a work tree."""
    here = Path(path).expanduser().resolve()
    for folder in (here, *here.parents):
        if (folder / ".git").exists():
            return folder
    return None


def ayl_home() -> Path:
    """`AYL_HOME`, resolved: the reader's own folder for what is never shared."""
    return Path(config.AYL_HOME).expanduser().resolve()


def private_dir(*parts: str) -> Path:
    """A folder under `AYL_HOME`, refused if it lies inside a git work tree.

    Only the path is returned; the caller creates it when it writes."""
    folder = ayl_home().joinpath(*parts)
    tree = git_work_tree_of(folder)
    if tree is not None:
        raise RuntimeError(
            f"AYL_HOME resolves to {ayl_home()}, inside the git work tree {tree}: files "
            f"that may never be shared are not written into a checkout, where one "
            f"`git add` would commit them. Set AYL_HOME to a folder outside any "
            f"repository (the default is ~/AskYourLibrary).")
    return folder


def private_file(path: Path) -> Path:
    """A file about to be written under `AYL_HOME`, refused when it is a symlink
    or when its resolved target lies inside a git work tree. `write_text`
    follows a symlink, so the folder's check alone does not cover the file."""
    path = Path(path).expanduser()
    if path.is_symlink():
        raise RuntimeError(f"{path} is a symlink: a file that may never be shared is not "
                           f"written through a link, which could point into a checkout")
    tree = git_work_tree_of(path)
    if tree is not None:
        raise RuntimeError(f"{path} resolves inside the git work tree {tree}: files that may "
                           f"never be shared are not written into a checkout")
    return path
