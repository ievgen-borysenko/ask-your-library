"""The reader's own folder, `AYL_HOME`, and the one rule that guards it.

`AYL_HOME` (default `~/AskYourLibrary`) is where everything this machine builds
for the reader has its default (ADR-026): the index (`$AYL_HOME/index`, decided
in `config.resolve_db_path`), the scratchpads (`scratch_dir` below), the web
chat's app root and chat database (`$AYL_HOME/ui`, `ui.launcher`) and the local
cards (`$AYL_HOME/cards/tech`).

Some of those files may be built on the reader's machine for the reader and
never shared: a model-written card of a work whose licence withholds sharing an
adaptation (CC BY-NC-ND 4.0 section 2(a)(1)(B)), and an index, which holds the
full text of the books it was built from — the reader's own among them, and
later the private shelf's. Those never go in a folder inside a repository: a
line in `.gitignore` is a convention a `git add -f` walks through, and a folder
that is not in the tree cannot be committed by anyone.

So the rule is a check, not a default: `private_dir` refuses a folder that
resolves inside a git work tree — this repository's or any other — before
anything is written to it, and `private_file` does the same for the file itself,
so a symlink planted at the file's name cannot carry the write into a checkout.
The check guards the DEFAULT only. A path a reader names explicitly for one kind
of file (`LIBRARY_DB_PATH` for the index) is theirs and is obeyed, and the
refusal names that variable, so a developer who keeps a throwaway index inside a
checkout has one line to write rather than a folder to move. The scratchpads and
the web chat's state go through `ayl_home` and are not refused: they are working
files of a run, and refusing to answer a question — or to start the web chat —
because the reader's home folder is under version control would be the rule
applied where the reader did not ask it to be.

What is detected is a `.git` directory or file in the path or above it. A
bare-repository setup whose work tree is elsewhere — dotfiles kept with
`git --git-dir=~/.dotfiles --work-tree=~` — leaves no `.git` in the home
directory and is NOT detected: with one, point AYL_HOME at a folder that setup
does not track.
"""
import os
import secrets
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


# The variable that puts one kind of file somewhere else without moving
# AYL_HOME, by the first part of its folder under AYL_HOME. A refusal names it,
# because it is the smaller change: the reader who kept AYL_HOME inside a
# checkout on purpose usually wants THAT file elsewhere, not everything.
OVERRIDES = {"index": ("LIBRARY_DB_PATH", "the index")}


def private_dir(*parts: str) -> Path:
    """A folder under `AYL_HOME`, refused if it lies inside a git work tree.

    Only the path is returned; the caller creates it when it writes."""
    folder = ayl_home().joinpath(*parts)
    tree = git_work_tree_of(folder)
    if tree is not None:
        override = OVERRIDES.get(parts[0]) if parts else None
        escape = (f"Set {override[0]} to put {override[1]} somewhere else, or set AYL_HOME "
                  if override else "Set AYL_HOME ")
        raise RuntimeError(
            f"AYL_HOME resolves to {ayl_home()}, inside the git work tree {tree}: files "
            f"that may never be shared are not written into a checkout, where one "
            f"`git add` would commit them. {escape}to a folder outside any "
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


# Called between the temporary file being written and the rename that puts it
# in place — the window a swapped directory would use. None in real runs; the
# tests set it to simulate the swap.
_before_replace = None


def write_private(path: Path, text: str) -> Path:
    """Write `text` to `path` under `AYL_HOME` without ever writing through
    what is already there.

    A fresh file is created in the validated folder (O_CREAT|O_EXCL|O_NOFOLLOW,
    through a descriptor of that folder), written, fsynced, and renamed over the
    name. A rename replaces the NAME and never modifies the old inode, so a
    hard link planted at `path` that shares its inode with a tracked file in a
    checkout is left pointing at an untouched file, and a symlink is replaced
    rather than followed. Right before the rename the folder is checked again:
    if its path no longer resolves to the folder that was validated, or that
    folder now lies inside a git work tree, the write is refused and the
    temporary file removed."""
    path = private_file(path)
    folder = path.parent.resolve()
    if git_work_tree_of(folder) is not None:
        raise RuntimeError(f"{folder} resolves inside a git work tree: nothing that may never "
                           f"be shared is written there")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = os.open(folder, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow)
    temporary = f".{path.name}.{secrets.token_hex(8)}.tmp"
    try:
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600,
                         dir_fd=directory)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                handle = None
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
        finally:
            if handle is not None:
                os.close(handle)
        if _before_replace is not None:
            _before_replace(path)
        held, named = os.fstat(directory), None
        try:
            named = os.stat(path.parent)
        except OSError:
            pass
        moved = (named is None or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                 or path.parent.resolve() != folder)
        if moved or git_work_tree_of(folder) is not None:
            os.unlink(temporary, dir_fd=directory)
            raise RuntimeError(f"{path.parent} changed while {path.name} was being written: "
                               f"it no longer resolves to the folder that was checked, or that "
                               f"folder is now inside a git work tree. Nothing was written.")
        os.replace(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    except BaseException:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        raise
    finally:
        os.close(directory)
    return path
