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

The lock is a file inside the index directory (`.ayl-ingest.lock`), created
with `O_CREAT | O_EXCL` so that taking it is one atomic syscall rather than a
check followed by a write. It is NOT a distributed lock and does not pretend to
be one: this is one user, one machine, and the failure it is built for is the
ordinary one — a second `ayl-add` in another terminal, or a backup taken while
the first is running.

**A crash leaves the file behind**, so the file names the process that holds
it. A lock whose pid is not running ON THIS HOST is stale and is taken over,
with a warning. A lock from another host cannot be judged from here — a network
share is the only way that happens — so it is refused, and the message names
the file to delete.
"""
import contextlib
import json
import logging
import os
import socket
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Inside the index directory rather than beside it: the index is the thing
# being protected, a directory is what gets moved and copied as a unit, and a
# sibling file is left behind by every `mv`. It starts with a dot and is not a
# `.lance` directory, so nothing in LanceDB lists it — and `--backup` excludes
# it by name, because a lock copied into a backup would be restored as a lock
# held by a pid from another era.
LOCK_NAME = ".ayl-ingest.lock"


class IngestBusy(RuntimeError):
    """Something else is writing this index. One readable line, not a traceback."""


def lock_path(db_path: Path | str) -> Path:
    return Path(db_path) / LOCK_NAME


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
    """A lock left behind by a process that is gone.

    Judged only where it can be: the same host, a pid that is not running. A
    lock with no pid or no host recorded (a truncated write, a file somebody
    created by hand) is stale too — nothing can ever clear it otherwise, and
    the alternative is an index that refuses every write until a human deletes
    a file they have never heard of. The takeover is logged either way."""
    if not info:
        return True
    host, pid = info.get("host"), info.get("pid")
    if not host or not isinstance(pid, int):
        return True
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
    """The one refusal text, so the ingest and the backup refuse in the same
    words and point at the same file."""
    return (f"refusing to {doing} {db_path}: an ingest is writing it "
            f"({describe(info)}). Wait for it to finish — or, if you are certain nothing "
            f"is running, delete {lock_path(db_path)} and try again.")


def acquire(db_path: Path | str, command: str = "", doing: str = "write") -> Path:
    """Take the lock, or raise `IngestBusy`.

    `O_CREAT | O_EXCL` is the whole exclusion: the file is created or the call
    fails, with no window between asking and taking. One retry after clearing a
    stale lock, and no more — a second failure means a real race with another
    process that has just taken it, and waiting in a loop for a half-hour ingest
    is not what a caller wants."""
    path = lock_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                          "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                          "command": command}).encode("utf-8")
    for attempt in (1, 2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            info = read_lock(db_path)
            if info is None:
                continue                      # it vanished between the two calls
            if attempt == 2 or not _is_stale(info):
                raise IngestBusy(busy_message(db_path, info, doing)) from None
            log.warning("%s: clearing a lock left behind by %s (that process is gone)",
                        path, describe(info))
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
        else:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
            return path
    raise IngestBusy(busy_message(db_path, read_lock(db_path) or {}, doing))


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
