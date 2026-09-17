"""One marker that says an ingest is writing this index — held by the kernel.

A LanceDB index is a directory, and a backup of it is a file copy. A copy taken
while an ingest is in flight is a copy of a half-written index: `ayl-add`
deletes a book's rows and appends the new ones as two operations, a staged
rebuild drops a table and copies the staging one over, and the FTS index is
rebuilt whole after every run. None of that is atomic, and none of it is
visible from the outside — the directory looks exactly the same while it is
being rewritten.

So the writers say so. `ayl-add` and the demo ingest hold this lock for the
length of a run; `--backup` and `--restore` take it too, which does double
duty: they refuse to touch an index somebody is writing, and they stop an
ingest from starting while a copy is being taken or put back.

**The lock is `flock`, not a file that is created and deleted.** That is the
whole design, and it replaces a home-made scheme that could not be made
correct. A lock whose presence IS the lock has to answer "what if the holder
died", which means reading a recorded pid and deciding the file is stale — and
two contenders that read the same stale lock both decide to clear it: the first
replaces it, the second unlinks the first's *live* lock and starts a second
ingest into the same index. That race has no fix inside the scheme, because
clearing and taking are two steps whatever order they are done in.

`fcntl.flock` has no such gap. The lock is held on an open file descriptor by
the kernel, `LOCK_EX | LOCK_NB` either takes it or fails immediately, and it is
released when the descriptor is closed — including when the process dies, for
any reason, without running any code of ours. There is no stale state, so
there is no stale detection, no pid to validate, and nothing to clear by hand.

The file itself is never deleted. It exists so the kernel has something to lock
and so the holder can write down WHO it is; the JSON payload (pid, host, start
time, command) is written after the lock is taken and truncated away on
release, and it is read only to say who is holding the thing. Nothing decides
anything from it: an unreadable, empty or absent payload has no effect on
whether the lock can be taken.

It sits BESIDE the index directory, keyed by the RESOLVED path, for two
reasons: `--restore` publishes by renaming the directory, and a lock living
inside it would travel with the rename, leaving the name it guards unguarded
exactly while it is swapped; and two spellings of one index (`./index`,
`~/index`, a symlink to either) must be one lock or the lock is decoration.

**What this is not.** `flock` is a local-filesystem lock. On a network share
its semantics belong to the share — some emulate it, some ignore it — so a
refusal that names another host says so rather than implying a guarantee. This
is one user, one machine, and the failure it is built for is the ordinary one:
a second `ayl-add` in another terminal, or a backup taken while the first runs.
"""
import contextlib
import fcntl
import json
import logging
import os
import socket
import time
from pathlib import Path

log = logging.getLogger(__name__)

LOCK_PREFIX = ".ayl-ingest-"
LOCK_SUFFIX = ".lock"
# Where the lock lived for one release: inside the index, as a file whose
# presence was the lock. Skipped when copying a backup and removed on restore,
# so a copy taken by that version cannot come back as a lock nothing holds.
LEGACY_LOCK_NAME = ".ayl-ingest.lock"

# The descriptors this process holds, by lock path. `release(db_path)` closes
# the right one, and closing is what drops the kernel's lock — so this map is
# the difference between releasing and merely forgetting.
_held: dict[Path, int] = {}


class IngestBusy(RuntimeError):
    """Something else is writing this index. One readable line, not a traceback."""


def lock_path(db_path: Path | str) -> Path:
    """The lock that guards this index, beside it.

    `resolve()` and not the path as typed: two spellings of one directory must
    be one lock, or `ayl-add --db data/lancedb` and a restore through the
    symlink that `data/lancedb` is would not exclude each other at all. It is
    called on paths that do not exist yet (an ingest creates its index), and a
    non-strict resolve normalizes those too."""
    real = Path(db_path).resolve()
    return real.parent / f"{LOCK_PREFIX}{real.name}{LOCK_SUFFIX}"


def read_lock(db_path: Path | str) -> dict | None:
    """What the holder wrote about itself, or None when there is no lock file.

    `{}` means the file is there with nothing readable in it: not held (the
    payload is truncated on release), or held by a process that has not yet
    written its line. Either way this is for the MESSAGE — `acquire` never
    consults it."""
    try:
        text = lock_path(db_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return {}
    try:
        return json.loads(text) if text.strip() else {}
    except ValueError:
        return {}


def describe(info: dict) -> str:
    """The holder of a lock, as a reader should see it."""
    if not info or not info.get("pid"):
        return "a process that has not recorded itself"
    return (f"pid {info.get('pid')} on {info.get('host', 'this machine')}, started "
            f"{info.get('started', 'at an unrecorded time')}"
            + (f", `{info['command']}`" if info.get("command") else ""))


def busy_message(db_path: Path | str, info: dict, doing: str) -> str:
    """The one refusal text, so the ingest, the backup and the restore refuse
    in the same words.

    No "delete this file" any more, and that is the point: the lock is the
    kernel's, the file is never deleted, and deleting it would not release
    anything. Waiting is the whole remedy — and if the holder is gone, the lock
    is already gone with it."""
    line = (f"refusing to {doing} {db_path}: an ingest is writing it ({describe(info)}). "
            f"Wait for it to finish. The lock is held by the operating system, so it is "
            f"released the moment that process ends, however it ends — there is no file to "
            f"clear.")
    host = info.get("host") if info else None
    if host and host != socket.gethostname():
        # An honest caveat rather than a promise: flock on a network share is
        # the share's to implement, and some do not.
        line += (f" It is held from {host}, so {lock_path(db_path)} is on a shared volume; "
                 f"whether that volume enforces this lock at all is the volume's own business.")
    return line


def _payload(command: str) -> bytes:
    return json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                       "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
                       "command": command}).encode("utf-8")


def acquire(db_path: Path | str, command: str = "", doing: str = "write") -> Path:
    """Take the lock, or raise `IngestBusy`.

    Open, then `flock(LOCK_EX | LOCK_NB)`. The open creates the file if it is
    not there and changes nothing if it is — the file's existence carries no
    meaning at all, so there is no race between creating it and locking it. The
    payload is written only after the lock is held, which is why nothing can
    read a half-written one and act on it."""
    path = lock_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A fresh descriptor every time, including from a process that already holds
    # this lock: flock is per OPEN FILE DESCRIPTION, so a second `acquire` here
    # is refused exactly as another process would be. That is the honest answer
    # — nothing in this codebase nests one lock inside another — and it is also
    # what lets the contention be exercised without spawning a process.
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # EWOULDBLOCK on every platform this runs on; any other errno means the
        # filesystem will not lock, and a lock that cannot be taken is refused
        # rather than assumed.
        info = read_lock(db_path) or {}
        os.close(fd)
        raise IngestBusy(busy_message(db_path, info, doing)) from None
    try:
        os.ftruncate(fd, 0)
        os.write(fd, _payload(command))
    except OSError as error:                 # a full disk: the lock is still held
        log.warning("%s: could not record who holds the lock (%s); the lock itself is held",
                    path, error)
    _held[path] = fd
    return path


def release(db_path: Path | str) -> None:
    """Drop the lock: truncate the note and close the descriptor.

    Closing is what releases it. The file stays — it is not the lock, it is
    only the thing the lock is held on — and it is left empty so that the next
    reader of a NOT-held lock sees nothing rather than the last holder's line."""
    path = lock_path(db_path)
    fd = _held.pop(path, None)
    if fd is None:
        return
    with contextlib.suppress(OSError):
        os.ftruncate(fd, 0)
    os.close(fd)


@contextlib.contextmanager
def ingest_lock(db_path: Path | str, command: str = "", doing: str = "write"):
    """Hold the lock for the length of a write, and drop it however the write
    ends — including ways no `finally` can catch, since the kernel releases it
    when the process does."""
    acquire(db_path, command=command, doing=doing)
    try:
        yield
    finally:
        release(db_path)
