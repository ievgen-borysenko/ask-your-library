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

What is NOT backed up: the scratchpads (`$AYL_HOME/scratch`, the passages as a
model saw them, a per-run log by design) and `.env` (secrets; a backup is a second copy of them).
"""
import contextlib
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from pathlib import Path

import lancedb

from ..chat_db import SCHEMA_VERSION as CHAT_SCHEMA_VERSION
from ..index_meta import (CARD_CHUNKER_VERSION, CHUNKER_VERSION, META_TABLE,
                          SCHEMA_VERSION)
from ..paths import redact_paths
from .ledger import open_ledger
from .lock import LEGACY_LOCK_NAME, ingest_lock, lock_path
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

    `ui.launcher.chainlit_dir` is THE rule (`AYL_CHAINLIT_DIR` expanded, else
    a checkout's `.chainlit/` that already holds a chat database, else
    `$AYL_HOME/ui/.chainlit/`, ADR-026) and this asks it rather
    than spelling it out a second time — the two spellings disagreed the moment
    one of them learnt to expand a `~`, and this function names the file
    `ayl backup` copies AND the file `ayl restore` writes. Importing the
    launcher is safe where importing the web chat is not: it writes files and
    starts a subprocess, and `ayl-add` must run without the Chainlit extra.

    Asked at CALL time, not at import, because the UI resolves it at ITS import
    and the tests set that variable per test.

    An absent file is not an error anywhere below — plenty of installations
    never start the web UI."""
    from ..ui.launcher import chainlit_dir
    return chainlit_dir() / "chat.db"


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


def symlinks_under(root: Path) -> list[Path]:
    """Every symlink INSIDE `root`, as paths relative to it.

    The root itself is not one of them: `data/lancedb` is a symlink in this
    project's own dev checkout, and following the path you were handed is the
    point. What is refused is a link found inside the tree, and the reason is a
    disagreement that would otherwise be silent. `copytree(symlinks=False)`
    FOLLOWS a link and writes the file it points at, while `_files_under`
    excludes links from the digest — so a linked file would be copied into the
    backup, never hashed, and the manifest would describe a set of files that
    is not the set of files in the directory. Worse, a link pointing outside
    the index would pull whatever it names into the copy: the very thing
    `ayl-add` refuses when it reads a folder of books.

    LanceDB writes no symlinks, so finding one means somebody put it there, and
    the honest answer is to name it and stop."""
    root = Path(root)
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_symlink())


def _refuse_symlinks(root: Path, what: str) -> None:
    found = symlinks_under(root)
    if not found:
        return
    named = ", ".join(str(link) for link in found[:3])
    more = f", and {len(found) - 3} more" if len(found) > 3 else ""
    raise BackupError(
        f"refusing to {what} {root}: it contains symlink(s) — {named}{more}. A copy would "
        f"follow them and write whatever they point at, while the manifest's digests skip "
        f"them, so the backup would not be the directory it claims to be. LanceDB writes no "
        f"symlinks; remove them (or copy the real files in) and try again.")


def copy_chat_db(source: Path, target: Path) -> bool:
    """One consistent snapshot of the chat database, or False when there is
    none to take.

    Through SQLite's OWN backup API (`Connection.backup`), not a file copy.
    A chat database in WAL mode is two files plus a shared-memory index, and
    copying them one after another is three reads at three different moments:
    the result can hold a page the write-ahead log has already superseded, or a
    log that refers to pages the main file does not have yet. `backup()` takes
    the snapshot the database engine itself would call consistent, and produces
    ONE file — which is also what makes a per-file digest meaningful, since the
    thing being hashed is now the whole database rather than one third of it.

    Copied with the same mode the web UI keeps it at: this file holds every
    question, answer and passage of every session."""
    source, target = Path(source), Path(target)
    if not source.is_file():
        return False
    with contextlib.closing(sqlite3.connect(source)) as live, \
            contextlib.closing(sqlite3.connect(target)) as copy:
        live.backup(copy)
    target.chmod(0o600)
    return True


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
    digest, or the manifest describes something other than what was copied.

    A failure anywhere in that sequence removes the half-written directory
    before it propagates. A partial backup is worse than none: it is a
    directory named like a backup, with no manifest to say what it is missing,
    sitting where somebody will one day reach for it."""
    db_path = Path(db_path)
    if not db_path.exists():
        raise BackupError(f"no index at {db_path} — nothing to back up")
    dest = Path(dest)
    # A destination inside the index is a copy of a directory into itself:
    # `copytree` would race its own output, and at best the backup would
    # contain a partial copy of itself. Compared on the RESOLVED paths, so a
    # symlink or a `..` cannot walk into the index by another name.
    resolved_dest, resolved_db = dest.resolve(), db_path.resolve()
    if resolved_dest == resolved_db or resolved_dest.is_relative_to(resolved_db):
        raise BackupError(
            f"refusing to back up {db_path} into {dest}: that is inside the index itself, so the "
            f"copy would contain the copy. Name a directory outside it.")
    stamp = now or time.strftime("%Y%m%d-%H%M%S")
    target = dest / stamp
    if target.exists():
        raise BackupError(f"{target} already exists — give --backup another directory, or "
                          f"wait a second and run it again")
    chat_db = Path(chat_db) if chat_db is not None else default_chat_db()

    with ingest_lock(db_path, command="ayl backup", doing="back up"):
        # Before anything is written: a tree that cannot be copied faithfully
        # must not produce a directory that looks like a backup of it.
        _refuse_symlinks(resolved_db, "back up")
        recovered = _recover_all(db_path)
        state = _index_state(db_path)
        target.mkdir(parents=True)
        try:
            # The lock is ours and is in the directory being copied; a restored
            # lock would be one held by a pid from another era.
            _copy_tree(db_path, target / INDEX_DIR, skip={LEGACY_LOCK_NAME})
            chat_error = None
            try:
                copied_chat = copy_chat_db(chat_db, target / CHAT_DB_NAME)
            except sqlite3.DatabaseError as error:
                # A chat database SQLite cannot open is news, not a reason to
                # abandon the index copy — which is the artefact an upgrade is
                # about to put at risk. Reported in the manifest and on the run,
                # so a backup is never quietly one file short.
                copied_chat, chat_error = False, f"{type(error).__name__}: {error}"
                (target / CHAT_DB_NAME).unlink(missing_ok=True)
                log.warning("%s could not be read as a SQLite database (%s); "
                            "the index was backed up without it", chat_db, chat_error)

            entries = [{"path": str(relative), "bytes": (target / relative).stat().st_size,
                        "sha256": _sha256(target / relative)}
                       for relative in _files_under(target)]
            manifest = {
                "format": MANIFEST_FORMAT,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "code_version": code_version(),
                # What the code that took this backup expects of an index. After
                # an upgrade these are how a reader knows whether the copy
                # predates it — which is the whole reason the backup exists.
                "expects": {"chunker": CHUNKER_VERSION,
                            "card_chunker": CARD_CHUNKER_VERSION,
                            "schema_version": SCHEMA_VERSION,
                            "chat_schema_version": CHAT_SCHEMA_VERSION},
                "source": {"index": redact_paths(str(resolved_db)),
                           "chat_db": redact_paths(str(chat_db)) if copied_chat else None},
                "chat_db_error": chat_error,
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
        except BaseException:
            # BaseException, not Exception: a KeyboardInterrupt in the middle of
            # a long copy is the likeliest way this ends half-done.
            shutil.rmtree(target, ignore_errors=True)
            raise
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
                          f"`ayl backup` (each backup is one timestamped directory "
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
    # A link inside the copy is a file the digests never covered — planted
    # after the backup was written, or by something other than this command.
    for link in symlinks_under(backup_dir):
        problems.append(f"a symlink, which no digest covers: {link}")
    if not problems and manifest.get("digest") != _directory_digest(
            [listed[name] for name in sorted(listed)]):
        problems.append("the manifest's own directory digest does not match the files it lists")
    return problems


def restore(backup_dir: Path, db_path: Path, chat_db: Path | None = None,
            force: bool = False) -> list[str]:
    """Put a verified backup back. Returns the lines to report.

    Refuses on three counts, and `--force` overrides exactly one of them: a
    manifest that does not verify, a live index in the way, and an ingest in
    flight. `--force` is about the second — the first is corruption and the
    third is a race, and no flag makes either of them safe. It covers the CHAT
    DATABASE too: without it a chat.db already at the target is left alone and
    the report says so, with it that file is replaced as well. That is the
    whole of what `--force` means here.

    The index that is replaced is MOVED ASIDE, not deleted: `<index>.replaced-<timestamp>`
    stays where it was, and the report names it. A restore is what somebody
    reaches for when something has already gone wrong, and deleting the only
    other copy of an index at that moment is the last thing this should do.

    The publish is STAGED: the verified copy is built beside the target, and
    only a complete one is swapped in, by rename. A failure while copying
    leaves the index that is there exactly as it was; a failure in the swap
    itself puts the moved-aside index back. And the lock is held across all of
    it, including a restore into a path where no index exists yet — that one
    took no lock at all, so an ingest could start into a half-written directory.

    A SYMLINKED index path is followed, not overwritten. `data/lancedb` is a
    symlink in this project's own dev checkout, and renaming the link would
    move the link, leave the real directory where it was, and write the restored
    index onto the volume the link lives on rather than the one the index does —
    which is at best a surprise about disk space and at worst a restore into a
    directory nothing reads. The real directory is what is moved aside and what
    is written, and the link goes on pointing at it."""
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
    # `verify` reports these as problems and so has already refused above; this
    # is the belt for the case of a backup directory written by something else.
    _refuse_symlinks(source_index, "restore")

    existing = db_path.exists()
    # The place the index really lives. `exists()` follows the link, so a live
    # symlinked path resolves to its target and everything below — the move
    # aside, the lock, the copy — happens there; an absent path is taken as
    # given, because there is nothing to follow.
    target_dir = db_path.resolve() if existing else db_path
    if existing and not force:
        raise BackupError(
            f"refusing to restore over {db_path}: an index is already there "
            f"({_describe_live(db_path)}). Point --db somewhere else, or pass --force to move "
            f"the current one aside (it is kept, not deleted) and put the backup in its place.")
    report = [f"backup {backup_dir} verified: {len(manifest.get('files', []))} file(s), "
              f"digest {str(manifest.get('digest'))[:16]}",
              f"taken {manifest.get('created')} by ask-your-library {manifest.get('code_version')}"]

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    # The lock is held across the WHOLE of it — the copy, the swap and the chat
    # database — and it is held at the target whether or not an index is there
    # yet: restoring into a fresh path and then having an ingest start into it
    # half-written is the same race as any other. The lock lives BESIDE the
    # directory, so it survives the renames below; one that lived inside would
    # travel with the rename and leave the name it guards unguarded exactly
    # while it is being swapped.
    with ingest_lock(target_dir, command="ayl restore", doing="restore over"):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        staged = target_dir.with_name(f"{target_dir.name}.restoring-{stamp}")
        shutil.rmtree(staged, ignore_errors=True)
        aside = None
        try:
            # Built in full BESIDE the target, so a failure here — a full disk,
            # an interrupt, an unreadable backup — leaves the index that is
            # there untouched. Only a complete copy is ever swapped in.
            _copy_tree(source_index, staged, skip={LEGACY_LOCK_NAME})
            (staged / LEGACY_LOCK_NAME).unlink(missing_ok=True)
            if existing:
                aside = target_dir.with_name(f"{target_dir.name}.replaced-{stamp}")
                target_dir.rename(aside)
            try:
                staged.rename(target_dir)
            except BaseException:
                # The swap is two renames and the window between them is the
                # only moment the index is absent. If the second fails, the
                # first is undone rather than left as a missing index.
                if aside is not None and not target_dir.exists():
                    aside.rename(target_dir)
                    aside = None
                raise
        except BaseException:
            shutil.rmtree(staged, ignore_errors=True)
            raise

        if aside is not None:
            report.append(f"the index that was there is kept at {aside} — delete it yourself "
                          f"once you are satisfied with the restore")
        if target_dir != db_path:
            report.append(f"{db_path} is a link to {target_dir}: the link is untouched and "
                          f"still points at the restored index")
        report.append(f"index restored to {db_path}")

        _restore_chat_db(backup_dir, chat_db, force, report)
    return report


def _restore_chat_db(backup_dir: Path, chat_db: Path | None, force: bool,
                     report: list[str]) -> None:
    """The chat database half of a restore, inside the caller's lock."""
    source_chat = backup_dir / CHAT_DB_NAME
    if source_chat.is_file():
        target_chat = Path(chat_db) if chat_db is not None else default_chat_db()
        if target_chat.exists() and not force:
            report.append(f"chat database NOT restored: {target_chat} already exists "
                          f"(--force replaces it)")
        else:
            target_chat.parent.mkdir(parents=True, exist_ok=True)
            # Through the backup API again, so the restored file is one
            # consistent database and never a main file beside somebody else's
            # write-ahead log. The target's own sidecars go: left behind, they
            # would be read as this database's journal.
            # Built beside the live file and moved over it, never deleted
            # first: `Connection.backup()` writes INTO a database, so the old
            # code unlinked the target before it had a replacement — and a
            # failure there (a full disk, an unreadable snapshot, an interrupt)
            # destroyed the reader's history with nothing to put back.
            staged_chat = target_chat.with_name(
                f"{target_chat.name}.restoring-{time.strftime('%Y%m%d-%H%M%S')}")
            staged_chat.unlink(missing_ok=True)
            try:
                copy_chat_db(source_chat, staged_chat)
                os.replace(staged_chat, target_chat)
            except BaseException:
                staged_chat.unlink(missing_ok=True)
                raise
            for suffix in ("-wal", "-shm"):
                # The replaced database's journal, which would otherwise be
                # read as this one's.
                Path(str(target_chat) + suffix).unlink(missing_ok=True)
            report.append(f"chat database restored to {target_chat}")


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
    if manifest.get("chat_db_error"):
        lines.append(f"  chat database NOT copied: it could not be read as a SQLite database "
                     f"({manifest['chat_db_error']})")
    elif manifest["source"].get("chat_db"):
        lines.append(f"  chat database from {manifest['source']['chat_db']} "
                     f"(one consistent snapshot, through SQLite's own backup)")
    else:
        lines.append("  no chat database found (the web UI has not been used, or it keeps "
                     "one elsewhere: --chat-db names it)")
    if manifest["recovered_staging"]:
        lines.append(f"  finished an interrupted rebuild of "
                     f"{', '.join(manifest['recovered_staging'])} before copying")
    return lines
