"""The chat database's schema version, and the check that it still holds.

The index has a fingerprint and a policy (`index_meta`); the web UI's SQLite
chat database had neither, and it has exactly the failure that argument was
about. `ui.py` creates its tables with `CREATE TABLE IF NOT EXISTS`, which by
design does nothing to a table that is already there — so a `chat.db` written
by an older release keeps its old columns for ever, and the data layer's first
`INSERT` naming a column that table does not have fails in the middle of
somebody's question, as an SQLite error in a server log.

So the same two things the index has: a **version**, written into the database
itself, and a **check at startup** of the columns the schema declares against
the columns that are actually there. The check is a WARNING, not a refusal, for
the same reason a chunker mismatch is: the UI still works for everything that
does not touch the missing column, refusing to start would lose the reader
their history over a schema drift, and the remedy (move the file aside, let it
be recreated) throws away every past conversation and must be the reader's
decision, not a startup assertion.

This module holds no SQL of its own beyond the version table: the schema is
`ui.py`'s, because that is what the data layer was configured against, and a
second copy here would be a second thing to keep true. What is checked is the
schema it is HANDED.
"""
import logging
import re
import time

log = logging.getLogger(__name__)

# The shape of the chat database as `ui.py` declares it. 1 is that schema as it
# has stood since the UI shipped; bump it whenever a column is added, removed
# or retyped, so that a database written by a newer release is recognisable as
# one rather than discovered column by column.
SCHEMA_VERSION = 1

# One row per component, so this table can outlive the one thing in it.
VERSION_TABLE = "ayl_schema"
CHAT_COMPONENT = "chat"
VERSION_DDL = f"""
CREATE TABLE IF NOT EXISTS {VERSION_TABLE} (
    "component" TEXT PRIMARY KEY,
    "version" INTEGER NOT NULL,
    "updated" TEXT NOT NULL
);
"""

_CREATE_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"?(\w+)"?\s*\((.*?)\);', re.S | re.I)
# A column line in this schema is a quoted name at the start of it. The
# constraint lines (FOREIGN KEY, PRIMARY KEY (...)) begin with a bare keyword
# and are skipped by the same rule, without a list of keywords to keep current.
_COLUMN = re.compile(r'^\s*"(\w+)"\s+\S', re.M)


def declared_columns(ddl: str) -> dict[str, set[str]]:
    """`table -> column names`, read from the CREATE TABLE statements of `ddl`.

    Read from the schema rather than written out again here, so that a column
    added to `ui.py` is checked for from the moment it is added and cannot be
    forgotten in a second list."""
    return {name: set(_COLUMN.findall(body)) for name, body in _CREATE_TABLE.findall(ddl)}


def actual_columns(connection, table: str) -> set[str]:
    """What the database really has. Empty for a table that is not there —
    which the caller distinguishes, because a missing table and a table missing
    every column are not the same news."""
    rows = connection.execute(f'PRAGMA table_info("{table}")').fetchall()
    return {row[1] for row in rows}


def table_exists(connection, table: str) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone())


def stored_version(connection) -> int | None:
    """The version recorded in the database, or None when nothing recorded one
    — which is every chat database written before this check existed."""
    if not table_exists(connection, VERSION_TABLE):
        return None
    row = connection.execute(
        f'SELECT "version" FROM {VERSION_TABLE} WHERE "component" = ?',
        (CHAT_COMPONENT,)).fetchone()
    return int(row[0]) if row else None


def record_version(connection, version: int = SCHEMA_VERSION) -> bool:
    """Write the version this code's schema is, unless that would LOWER what is
    already recorded. Returns whether it wrote.

    A version only ever goes up. Running an older release against a database a
    newer one wrote must not restamp it downwards: the stamp would then say the
    file is something this code can fully write, the next start of the newer
    release would find its own version missing, and the one piece of evidence
    about which release shaped the file would be gone — overwritten by the
    release that knows least about it.

    Called after the column check and only when it passed, never before it:
    stamping a database that is missing columns as current makes the stamp a
    claim about a shape the file does not have."""
    connection.executescript(VERSION_DDL)
    recorded = stored_version(connection)
    if recorded is not None and recorded >= int(version):
        return False
    connection.execute(
        f'INSERT INTO {VERSION_TABLE} ("component", "version", "updated") VALUES (?, ?, ?) '
        f'ON CONFLICT("component") DO UPDATE SET "version" = excluded."version", '
        f'"updated" = excluded."updated"',
        (CHAT_COMPONENT, int(version), time.strftime("%Y-%m-%dT%H:%M:%S")))
    return True


def check_and_record(connection, ddl: str, path: str = "the chat database",
                     version: int = SCHEMA_VERSION) -> list[str]:
    """The startup sequence, in one call so the ORDER is a property of this
    module and not of its caller: check first, stamp only when there is nothing
    to report. Returns the problems, for the caller to log.

    A database that is missing columns, or was written by a newer release, is
    left exactly as it is — including its stamp, which is what the next start
    reads."""
    problems = check_chat_db(connection, ddl, path=path, version=version)
    if not problems:
        record_version(connection, version)
    return problems


def check_chat_db(connection, ddl: str, path: str = "the chat database",
                  version: int = SCHEMA_VERSION) -> list[str]:
    """Problems with this chat database, as lines a person can act on. Empty
    when it is the database this code writes.

    Three shapes, and they are not the same problem:

    **A table that is not there** — nothing wrote it, or the file is not a chat
    database at all. `CREATE TABLE IF NOT EXISTS` has just run, so this means
    the creation itself failed.

    **A table missing columns this code writes** — the real one. `IF NOT
    EXISTS` leaves an older table exactly as it was, so the database looks
    healthy until the data layer inserts into a column that is not there, in
    the middle of a question.

    **A version newer than this code's** — the file was written by a later
    release, and the columns it has are not the columns this code knows about
    even where the names agree.

    Never raises: it is handed a live connection at startup and a traceback
    there is a UI that does not start."""
    problems: list[str] = []
    try:
        recorded = stored_version(connection)
        if recorded is not None and recorded > version:
            problems.append(
                f"{path} is stamped chat-schema version {recorded}, this code writes version "
                f"{version} — it was written by a newer ask-your-library. The web UI will read "
                f"and write what it knows; anything that release added is invisible here.")
        for table, columns in sorted(declared_columns(ddl).items()):
            if not table_exists(connection, table):
                problems.append(f"{path}: the table {table!r} is missing and could not be "
                                f"created — the web UI will fail on its first write to it.")
                continue
            missing = sorted(columns - actual_columns(connection, table))
            if missing:
                problems.append(
                    f"{path}: the table {table!r} has no column(s) {', '.join(missing)}, which "
                    f"this version writes. SQLite leaves an existing table alone, so an older "
                    f"chat database keeps its old shape and fails on the first insert that names "
                    f"one of them. Move the file aside and let the UI create a new one (the "
                    f"conversation history in it is lost — back it up first with "
                    f"`uv run ayl backup <dir>`), or add the column(s) by hand.")
    except Exception as error:                # a file that is not SQLite at all
        problems.append(f"{path} could not be checked ({type(error).__name__}: {error})")
    return problems
