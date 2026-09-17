"""`ayl-add --backup <dir>` / `--restore <dir>`: a copy of the index, and the
statement of when a copy is safe.

The index is a directory and the chat history is a SQLite file, so a backup is
a file copy and nothing cleverer is needed. What IS needed is the part a plain
`cp -r` cannot supply: the answer to "was this copy taken at a moment when the
index was whole". That answer is the product here, and it has three parts.

**No ingest was running.** The write paths hold `lock.ingest_lock` for the
length of a run, and this takes the same lock. So a backup cannot start while
an ingest is writing, and an ingest cannot start while a backup is being taken.

**A staged rebuild was finished, not caught mid-swap.** LanceDB OSS has no
rename, so a rebuild goes through `<table>__staging` and there is a window in
which the live table is gone and the staged one is not yet promoted. A copy
taken in that window restores to an index missing a table. `recover_staging`
closes the window — it is a WRITE, which is exactly why it belongs here, on a
path that already holds the lock, and not in any reader (ADR-024).

**Every file is digested.** The manifest records the sha256 of each file copied
and one digest over the whole set, and `--restore` recomputes both before it
copies anything back. A backup that rotted on the disk it was sitting on is
found before it replaces a working index, not after.

The manifest also records what the copy IS: the `_index_meta` rows (embedder,
dims, chunker, row-schema version, per table), the row count of each table, the
number of ledger rows, and the code version that took it. After an upgrade that
requires a rebuild — a new chunker, a new embedding model — this backup is the
only way back to the index you had, and those fields are how you know which
index that was.

What is NOT backed up: `.scratch/` (the passages as a model saw them, deleted
per run by design) and `.env` (secrets; a backup is a second copy of them).
"""
import hashlib
import json
import logging
import os
import shutil
import time
from pathlib import Path

import lancedb

from ..index_meta import CHUNKER_VERSION, META_TABLE, SCHEMA_VERSION
from ..paths import redact_paths
from .ledger import open_ledger
from .lock import LOCK_NAME, ingest_lock, lock_path
from .publish import STAGING_SUFFIX, recover_staging, table_names

log = logging.getLogger(__name__)

MANIFEST_NAME = "MANIFEST.json"
# Inside the backup: the index under its own name, the chat database beside it.
# Named rather than "whatever directory is in there", so a restore reads a
# layout and not a guess.
INDEX_DIR = "lancedb"
CHAT_DB_NAME = "chat.db"
MANIFEST_FORMAT = 1

# Read in chunks: an index directory is hundreds of megabytes of vectors, and
# the digest must not be a function of how much memory the machine has.
_HASH_BLOCK = 1 << 20


class BackupError(Exception):
    """A problem the user can act on, reported as one line."""


def default_chat_db() -> Path:
    """Where the web UI keeps its chat database.

    The same rule `ui.py` applies (`AYL_CHAINLIT_DIR`, else `.chainlit/` in the
    checkout), re-derived here rather than imported: importing `ui.py` pulls in
    Chainlit, which is an optional extra, and `ayl-add` must run without it.
    Resolved at CALL time, not at import, because `ui.py` resolves it at import
    and the tests set that variable per test.

    An absent file is not an error anywhere below — plenty of installations
    never start the web UI."""
    from ..paths import REPO_ROOT
    named = os.environ.get("AYL_CHAINLIT_DIR")
    base = Path(named) if named else (Path(REPO_ROOT) if REPO_ROOT else Path.cwd()) / ".chainlit"
    return base / "chat.db"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(_HASH_BLOCK), b""):
            digest.update(block)
    return digest.hexdigest()


def _files_under(root: Path) -> list[Path]:
    """Every regular file under `root`, sorted, as paths relative to it.

    Sorted because the directory digest is built from this order, and an
    unsorted walk would give the same tree two different digests on two
    machines. Symlinks are not followed and not copied: an index directory
    contains none, and following one would copy whatever it points at into a
    backup."""
    return sorted(p.relative_to(root) for p in root.rglob("*")
                  if p.is_file() and not p.is_symlink())


def _directory_digest(entries: list[dict]) -> str:
    """One digest over the whole copy: the sha256 of `<sha> <path>` lines in
    path order. Comparing this alone catches a file added or removed since the
    backup was written, which per-file digests on their own do not."""
    joined = "\n".join(f"{entry['sha256']}  {entry['path']}" for entry in entries)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _copy_tree(source: Path, target: Path, skip: set[str] = frozenset()) -> None:
    shutil.copytree(source, target, symlinks=False,
                    ignore=shutil.ignore_patterns(*skip) if skip else None)


def _index_state(db_path: Path) -> dict:
    """What this index is, for the manifest: the fingerprint rows, the row
    count per table, and how many books the ledger holds.

    Read after `recover_staging`, so the counts describe the copy that is about
    to be taken rather than a table mid-rebuild. Every step is tolerant of an
    absent table: an index with no ledger, or none stamped, is a legitimate
    thing to back up — and a backup that refused such an index would refuse
    exactly the ones an upgrade is about to change."""
    db = lancedb.connect(db_path)
    state: dict = {"tables": {}, "index_meta": [], "ledger_rows": 0}
    for name in sorted(table_names(db)):
        if name.startswith("_") or name.endswith(STAGING_SUFFIX):
            continue
        try:
            state["tables"][name] = db.open_table(name).count_rows()
        except Exception as error:                      # a table we cannot open is news
            state["tables"][name] = f"unreadable: {type(error).__name__}"
    if META_TABLE in table_names(db):
        meta = db.open_table(META_TABLE)
        state["index_meta"] = meta.search().limit(max(meta.count_rows(), 1)).to_list()
    ledger = open_ledger(db)
    if ledger.exists():
        state["ledger_rows"] = len(ledger.all_rows())
    return state


def _recover_all(db_path: Path) -> list[str]:
    """Finish or discard every interrupted staged rebuild in this index, and
    say which. This is the write that makes the copy meaningful."""
    db = lancedb.connect(db_path)
    interrupted = [name[:-len(STAGING_SUFFIX)] for name in table_names(db)
                   if name.endswith(STAGING_SUFFIX)]
    for base in sorted(interrupted):
        recover_staging(db, base)
    return sorted(interrupted)


def backup(db_path: Path, dest: Path, chat_db: Path | None = None,
           now: str | None = None) -> Path:
    """Copy the index and the chat database into `<dest>/<timestamp>/`, with a
    manifest. Returns the directory written.

    The order is the point: take the lock, finish any interrupted rebuild, read
    what the index is, copy, digest, write the manifest — and only then release
    the lock. Nothing may write the index between the recovery and the last
    digest, or the manifest describes something other than what was copied."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise BackupError(f"no index at {db_path} — nothing to back up")
    dest = Path(dest)
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    target = dest / stamp
    if target.exists():
        raise BackupError(f"{target} already exists — give --backup another directory, or "
                          f"wait a second and run it again")
    chat_db = Path(chat_db) if chat_db is not None else default_chat_db()

    with ingest_lock(db_path, command="ayl-add --backup", doing="back up"):
        recovered = _recover_all(db_path)
        state = _index_state(db_path)
        target.mkdir(parents=True)
        # The lock is ours and is in the directory being copied; a restored
        # lock would be one held by a pid from another era.
        _copy_tree(db_path, target / INDEX_DIR, skip={LOCK_NAME})
        copied_chat = False
        if chat_db.is_file():
            # The WAL and shm sidecars too, when they are there: a chat.db
            # copied without its -wal is a database missing its last writes.
            for suffix in ("", "-wal", "-shm"):
                sidecar = Path(str(chat_db) + suffix)
                if sidecar.is_file():
                    shutil.copy2(sidecar, target / (CHAT_DB_NAME + suffix))
            copied_chat = True

        entries = [{"path": str(relative), "bytes": (target / relative).stat().st_size,
                    "sha256": _sha256(target / relative)}
                   for relative in _files_under(target)]
        manifest = {
            "format": MANIFEST_FORMAT,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "code_version": code_version(),
            # What the code that took this backup expects of an index. After an
            # upgrade these two are how a reader knows whether the copy predates
            # it — which is the whole reason the backup exists.
            "expects": {"chunker": CHUNKER_VERSION, "schema_version": SCHEMA_VERSION},
            "source": {"index": redact_paths(str(db_path.resolve())),
                       "chat_db": redact_paths(str(chat_db)) if copied_chat else None},
            "recovered_staging": recovered,
            "index_meta": state["index_meta"],
            "tables": state["tables"],
            "ledger_rows": state["ledger_rows"],
            "files": entries,
            "digest": _directory_digest(entries),
        }
        (target / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8")
    return target


def code_version() -> str:
    try:
        from importlib.metadata import version
        return version("ask-your-library")
    except Exception:
        return "unknown"


def read_manifest(backup_dir: Path) -> dict:
    path = Path(backup_dir) / MANIFEST_NAME
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BackupError(f"{path} is not there — {backup_dir} is not a backup taken by "
                          f"`ayl-add --backup` (each backup is one timestamped directory "
                          f"inside the one you named)") from None
    except ValueError as error:
        raise BackupError(f"{path} is not readable JSON ({error})") from None


def verify(backup_dir: Path) -> list[str]:
    """Recompute every digest in the manifest. Returns the problems found, empty
    when the copy is exactly what was written.

    Both directions are checked, because they fail differently: a file whose
    contents changed is corruption, a file that is no longer there is a
    truncated copy, and a file that is there and unlisted means the manifest
    describes a different backup than the one in this directory."""
    backup_dir = Path(backup_dir)
    manifest = read_manifest(backup_dir)
    problems: list[str] = []
    listed = {entry["path"]: entry for entry in manifest.get("files", [])}
    for relative, entry in sorted(listed.items()):
        path = backup_dir / relative
        if not path.is_file():
            problems.append(f"missing: {relative}")
            continue
        if _sha256(path) != entry["sha256"]:
            problems.append(f"changed since the backup was taken: {relative}")
    on_disk = {str(p) for p in _files_under(backup_dir)} - {MANIFEST_NAME}
    for extra in sorted(on_disk - set(listed)):
        problems.append(f"in the directory but not in the manifest: {extra}")
    if not problems and manifest.get("digest") != _directory_digest(
            [listed[name] for name in sorted(listed)]):
        problems.append("the manifest's own directory digest does not match the files it lists")
    return problems


def restore(backup_dir: Path, db_path: Path, chat_db: Path | None = None,
            force: bool = False) -> list[str]:
    """Put a verified backup back. Returns the lines to report.

    Refuses on three counts, and none of them is overridden by `--force`
    except the second: a manifest that does not verify, a live index in the
    way, and an ingest in flight. `--force` is about the second alone — the
    first is corruption and the third is a race, and no flag makes either of
    them safe.

    The index that is replaced is MOVED ASIDE, not deleted: `<index>.replaced-<timestamp>`
    stays where it was, and the report names it. A restore is what somebody
    reaches for when something has already gone wrong, and deleting the only
    other copy of an index at that moment is the last thing this should do."""
    backup_dir, db_path = Path(backup_dir), Path(db_path)
    manifest = read_manifest(backup_dir)
    problems = verify(backup_dir)
    if problems:
        shown = "\n  ".join(problems[:5])
        more = f"\n  ... and {len(problems) - 5} more" if len(problems) > 5 else ""
        raise BackupError(
            f"refusing to restore {backup_dir}: it does not match its own manifest, so it is "
            f"not the index that was backed up:\n  {shown}{more}\n"
            f"Nothing was touched. Use another backup.")

    source_index = backup_dir / INDEX_DIR
    if not source_index.is_dir():
        raise BackupError(f"refusing to restore {backup_dir}: it holds no {INDEX_DIR}/ directory")

    existing = db_path.exists()
    if existing and not force:
        raise BackupError(
            f"refusing to restore over {db_path}: an index is already there "
            f"({_describe_live(db_path)}). Point --db somewhere else, or pass --force to move "
            f"the current one aside (it is kept, not deleted) and put the backup in its place.")
    report = [f"backup {backup_dir} verified: {len(manifest.get('files', []))} file(s), "
              f"digest {str(manifest.get('digest'))[:16]}",
              f"taken {manifest.get('created')} by ask-your-library {manifest.get('code_version')}"]
    if existing:
        # The live index is about to be moved out from under anything reading
        # or writing it: the lock is held ACROSS the move, not merely tested
        # before it. It travels with the directory (it is a file inside it), so
        # it is dropped from the copy that is kept — an index nobody can write
        # to is not much of a fallback.
        with ingest_lock(db_path, command="ayl-add --restore", doing="restore over"):
            aside = db_path.with_name(f"{db_path.name}.replaced-{time.strftime('%Y%m%d-%H%M%S')}")
            db_path.rename(aside)
            lock_path(aside).unlink(missing_ok=True)
        report.append(f"the index that was there is kept at {aside} — delete it yourself once "
                      f"you are satisfied with the restore")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _copy_tree(source_index, db_path, skip={LOCK_NAME})
    # A lock restored or left over would refuse every later ingest.
    lock_path(db_path).unlink(missing_ok=True)
    report.append(f"index restored to {db_path}")

    source_chat = backup_dir / CHAT_DB_NAME
    if source_chat.is_file():
        target_chat = Path(chat_db) if chat_db is not None else default_chat_db()
        if target_chat.exists() and not force:
            report.append(f"chat database NOT restored: {target_chat} already exists "
                          f"(--force replaces it)")
        else:
            target_chat.parent.mkdir(parents=True, exist_ok=True)
            for suffix in ("", "-wal", "-shm"):
                sidecar = backup_dir / (CHAT_DB_NAME + suffix)
                out = Path(str(target_chat) + suffix)
                if sidecar.is_file():
                    shutil.copy2(sidecar, out)
                    out.chmod(0o600)          # as ui.py keeps it: owner only
                elif out.exists():
                    # A stale sidecar of the database being replaced would be
                    # read as this one's journal.
                    out.unlink()
            report.append(f"chat database restored to {target_chat}")
    return report


def _describe_live(db_path: Path) -> str:
    try:
        names = sorted(table_names(lancedb.connect(db_path)))
    except Exception:
        return "unreadable as a LanceDB index"
    return f"{len(names)} table(s): {', '.join(names) or 'none'}"


def manifest_lines(target: Path, manifest: dict) -> list[str]:
    """The backup report: what was copied, and what it holds."""
    lines = [f"backup written to {target}",
             f"  {len(manifest['files'])} file(s), digest {manifest['digest'][:16]}"]
    for name, count in sorted(manifest["tables"].items()):
        lines.append(f"  {name}: {count} rows")
    lines.append(f"  books ledger: {manifest['ledger_rows']} row(s)")
    for row in manifest["index_meta"]:
        lines.append(f"  stamp {row.get('table')}: {row.get('model')} / {row.get('dims')}d, "
                     f"chunker {row.get('chunker') or '(none recorded)'}, "
                     f"row schema {row.get('schema_version')}")
    if manifest["source"].get("chat_db"):
        lines.append(f"  chat database from {manifest['source']['chat_db']}")
    else:
        lines.append("  no chat database found (the web UI has not been used, or it keeps "
                     "one elsewhere: --chat-db names it)")
    if manifest["recovered_staging"]:
        lines.append(f"  finished an interrupted rebuild of "
                     f"{', '.join(manifest['recovered_staging'])} before copying")
    return lines
