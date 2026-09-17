"""One marker that says an ingest is writing this index.

A LanceDB index is a directory, and a backup of it is a file copy. A copy taken
while an ingest is in flight is a copy of a half-written index: `ayl-add`
deletes a book's rows and appends the new ones as two operations, a staged
rebuild drops a table and copies the staging one over, and the FTS index is
rebuilt whole after every run. None of that is atomic, and none of it is
visible from the outside — the directory looks exactly the same while it is
being rewritten.

So the writers say so. `ayl-add` and the demo ingest hold this lock for the
length of a run; `--backup` takes it too, which does double duty: it refuses to
copy an index somebody is writing, and it stops an ingest from starting while
the copy is being taken.

The lock is a file BESIDE the index directory, named after it
(`.ayl-ingest-<name>.lock`), and it is beside rather than inside for one
reason: `--restore` publishes by renaming the directory, and a lock living
inside it would travel with the rename and leave the name it guards unguarded
exactly while it is being swapped. It is written by hard-linking a complete
temporary file into place, so the name never exists with a partial body.

It is NOT a distributed lock and does not pretend to be one: this is one user,
one machine, and the failure it is built for is the ordinary one — a second
`ayl-add` in another terminal, or a backup taken while the first is running.

**A crash leaves the file behind**, so the file names the process that holds
it. One case and one only is cleared automatically: this host, a pid that is
not running. Anything else is refused by name — another host cannot be
judged from here, and a lock this process cannot READ is most likely another
account's (the file is 0600), where clearing it would let two ingests write one
index.
"""
import contextlib
import json
import logging
import os
import socket
import time
from pathlib import Path

log = logging.getLogger(__name__)

# BESIDE the index directory, keyed by its name, not inside it. Inside was the
# obvious place and it is wrong for the one operation that most needs a lock: a
# restore publishes by RENAMING the directory, and a lock that lives inside it
# travels with the rename, leaving the name it was guarding unguarded for the
# length of the swap. A sibling file survives a rename of its neighbour, is
# never copied into a backup by construction, and is still invisible to LanceDB
# (a dotfile, not a `.lance` directory).
#
# The name is derived from the RESOLVED path, so `~/index`, `./index` and a
# symlink pointing at it are one lock and not three.
LOCK_PREFIX = ".ayl-ingest-"
LOCK_SUFFIX = ".lock"
# Where the lock used to live, for one release: skipped when copying a backup
# and removed after a restore, so a copy taken by the previous version is not
# restored as a lock held by a pid from another era.
LEGACY_LOCK_NAME = ".ayl-ingest.lock"


class IngestBusy(RuntimeError):
    """Something else is writing this index. One readable line, not a traceback."""


def lock_path(db_path: Path | str) -> Path:
    """The lock that guards this index, beside it.

    `resolve()` and not the path as typed: two spellings of one directory must
    be one lock, or `ayl-add ~/books --db data/lancedb` and a restore through
    the symlink that `data/lancedb` is would not exclude each other at all. It
    is called on paths that do not exist yet (an ingest creates its index), and
    a non-strict resolve normalizes those too."""
    real = Path(db_path).resolve()
    return real.parent / f"{LOCK_PREFIX}{real.name}{LOCK_SUFFIX}"


def read_lock(db_path: Path | str) -> dict | None:
    """What the lock file says, or None when there is none.

    A file that is there but unreadable or not JSON returns an empty dict, not
    None: "held by something I cannot identify" and "not held" are different
    answers, and only the first of them may be taken over by `_is_stale`."""
    path = lock_path(db_path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        return {}


def _alive(pid: int) -> bool:
    """Is this pid running? `kill(pid, 0)` signals nothing and only asks.

    PermissionError means it exists and belongs to somebody else — alive. Only
    ProcessLookupError is evidence of absence."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True         # unknown: err towards "held"
    return True


def _is_stale(info: dict) -> bool:
    """A lock left behind by a process that is gone — and ONLY that.

    Exactly one thing makes a lock stale: it names this host and a pid that is
    not running. Everything else is refused, including the cases an earlier
    version cleared automatically, and the reason is the file's own mode. The
    lock is written 0600, so on a directory two accounts share, the OTHER
    account cannot read it — it sees a file it cannot parse. Treating that as
    stale would have one user silently unlink the live lock of another and
    start a second ingest into the same index, which is the single thing this
    file exists to prevent. An index that will not be written to until somebody
    deletes a named file is a much better failure, and the message names it.

    An unreadable lock also cannot be an artefact of this program's own
    writing: the payload is hard-linked into place complete (`acquire`), so the
    name never exists with an empty or partial body. If one is ever seen, it
    was not written here.

    A lock from another host cannot be judged from this one at all."""
    if not info:
        return False        # unreadable: not ours to clear — see above
    host, pid = info.get("host"), info.get("pid")
    if not host or not isinstance(pid, int):
        return False        # nothing to validate it by
    if host != socket.gethostname():
        return False        # another machine: not ours to judge
    return not _alive(pid)


def describe(info: dict) -> str:
    """The holder of a lock, as a reader should see it."""
    if not info:
        return "an unreadable lock file"
    return (f"pid {info.get('pid', '?')} on {info.get('host', '?')}, started "
            f"{info.get('started', 'at an unrecorded time')}"
            + (f", `{info['command']}`" if info.get("command") else ""))


def busy_message(db_path: Path | str, info: dict, doing: str) -> str:
    """The one refusal text, so the ingest, the backup and the restore refuse
    in the same words and point at the same file.

    A lock that cannot be read gets its own sentence. "An ingest is writing it
    (an unreadable lock file)" invites the reader to wait for something that
    may not exist; what is true is that there is a lock here, this process
    cannot tell whose it is — most likely another account's, since the file is
    0600 — and only its owner can clear it."""
    if not info or not info.get("host") or not isinstance(info.get("pid"), int):
        return (f"refusing to {doing} {db_path}: there is a lock at {lock_path(db_path)} that "
                f"cannot be read — it is another account's (the file is owner-only), or it was "
                f"not written by this program. It is not cleared automatically, because doing "
                f"that would let two ingests write one index. If you own it and nothing is "
                f"running, delete it and try again.")
    return (f"refusing to {doing} {db_path}: an ingest is writing it "
            f"({describe(info)}). Wait for it to finish — or, if you are certain nothing "
            f"is running, delete {lock_path(db_path)} and try again.")


def acquire(db_path: Path | str, command: str = "", doing: str = "write") -> Path:
    """Take the lock, or raise `IngestBusy`.

    The lock is written to a private temporary file FIRST and then hard-linked
    into place. `os.link` fails with `FileExistsError` if the name is taken, so
    it is as exclusive as `O_CREAT | O_EXCL` — and unlike it, the file is
    COMPLETE from the instant the name exists. Creating an empty file and then
    writing the payload leaves a window in which a competitor reads `{}`,
    concludes "a lock nobody can be identified from" and takes it over; the
    window is short, and two ingests writing one index is exactly the thing
    this file exists to prevent, so it is closed rather than made unlikely.

    One retry after clearing a stale lock, and no more: a second failure means
    a real race with a process that has just taken it, and waiting in a loop
    for a half-hour ingest is not what a caller wants."""
    path = lock_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                          "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "command": command}).encode("utf-8")
    # Same directory, so the link below is within one filesystem; the pid makes
    # it this process's own even if two race here.
    staging = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(staging, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        for attempt in (1, 2):
            try:
                os.link(staging, path)
            except FileExistsError:
                info = read_lock(db_path)
                if info is None:
                    continue                  # it vanished between the two calls
                if attempt == 2 or not _is_stale(info):
                    raise IngestBusy(busy_message(db_path, info, doing)) from None
                log.warning("%s: clearing a lock left behind by %s (that process is gone)",
                            path, describe(info))
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            else:
                return path
        raise IngestBusy(busy_message(db_path, read_lock(db_path) or {}, doing))
    finally:
        with contextlib.suppress(FileNotFoundError):
            staging.unlink()


def release(db_path: Path | str) -> None:
    """Drop the lock. Missing is fine: the point is that it is not there."""
    with contextlib.suppress(FileNotFoundError):
        lock_path(db_path).unlink()


@contextlib.contextmanager
def ingest_lock(db_path: Path | str, command: str = "", doing: str = "write"):
    """Hold the lock for the length of a write, and drop it however the write
    ends. A crash that bypasses this (a power cut, SIGKILL) leaves the file, and
    the next run clears it as stale — which is why the file records a pid."""
    acquire(db_path, command=command, doing=doing)
    try:
        yield
    finally:
        release(db_path)
