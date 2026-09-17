"""The chat database's schema version and the startup column check (#27).

`ui.py` creates its tables with `CREATE TABLE IF NOT EXISTS`, which by design
leaves an existing table exactly as it is. So a `chat.db` written by an older
release keeps its old columns, looks healthy, and fails on the first insert
naming a column it does not have — in the middle of somebody's question.

These tests run against plain SQLite and the schema string itself: no Chainlit,
no server, no `ui.py` import (which needs the optional `ui` extra).
"""
import re
import sqlite3
from pathlib import Path

import pytest

from ask_your_library.chat_db import (SCHEMA_VERSION, VERSION_TABLE, actual_columns,
                                      check_chat_db, declared_columns, record_version,
                                      stored_version)

# A miniature of `ui.py`'s schema: the two shapes that matter are a plain
# column list and a table with a constraint line after it.
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT NOT NULL,
    "command" TEXT,
    "defaultOpen" BOOLEAN,
    FOREIGN KEY ("threadId") REFERENCES users("id") ON DELETE CASCADE
);
"""

# The same, as an older release wrote it: `steps` without the two newest columns.
OLDER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT NOT NULL,
    FOREIGN KEY ("threadId") REFERENCES users("id") ON DELETE CASCADE
);
"""


@pytest.fixture
def connection(tmp_path):
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        yield conn
    conn.close()


def test_the_declared_columns_are_read_from_the_schema_not_a_second_list():
    """Written out again here, a column added to `ui.py` would be checked for
    only if somebody remembered to add it twice."""
    declared = declared_columns(SCHEMA)
    assert declared["users"] == {"id", "identifier", "metadata"}
    # the FOREIGN KEY line is not a column, and no keyword list says so
    assert declared["steps"] == {"id", "threadId", "command", "defaultOpen"}


def test_a_database_this_code_wrote_has_nothing_to_report(connection):
    connection.executescript(SCHEMA)
    assert check_chat_db(connection, SCHEMA) == []


def test_an_older_database_keeps_its_shape_and_is_named_for_it(connection):
    """The real failure: `IF NOT EXISTS` runs, changes nothing, and the
    database passes every other check until an insert names `command`."""
    connection.executescript(OLDER_SCHEMA)
    connection.executescript(SCHEMA)                    # what startup does
    assert actual_columns(connection, "steps") == {"id", "threadId"}

    problems = check_chat_db(connection, SCHEMA, path="chat.db")

    assert len(problems) == 1
    assert "steps" in problems[0] and "command" in problems[0] and "defaultOpen" in problems[0]
    assert "Move the file aside" in problems[0] and "--backup" in problems[0]


def test_a_missing_table_is_a_different_problem_from_a_missing_column(connection):
    connection.executescript('CREATE TABLE users ("id" TEXT, "identifier" TEXT, '
                             '"metadata" TEXT);')
    problems = check_chat_db(connection, SCHEMA)
    assert len(problems) == 1 and "'steps' is missing" in problems[0]


def test_a_version_newer_than_this_code_is_reported(connection):
    connection.executescript(SCHEMA)
    record_version(connection, SCHEMA_VERSION + 1)

    problems = check_chat_db(connection, SCHEMA)

    assert any("newer ask-your-library" in problem for problem in problems)


def test_the_version_is_recorded_and_read_back(connection):
    assert stored_version(connection) is None           # every db written before this
    record_version(connection)
    assert stored_version(connection) == SCHEMA_VERSION
    record_version(connection)                          # idempotent: one row, replaced
    assert connection.execute(f'SELECT COUNT(*) FROM {VERSION_TABLE}').fetchone()[0] == 1


def test_an_unreadable_database_is_a_line_and_not_a_traceback(tmp_path):
    """Handed a live connection at startup: a traceback here is a UI that does
    not start, over a check whose worst news is a warning."""
    (tmp_path / "not.db").write_bytes(b"this is not a database")
    with sqlite3.connect(tmp_path / "not.db") as conn:
        problems = check_chat_db(conn, SCHEMA)
    assert len(problems) == 1 and "could not be checked" in problems[0]


def shipped_schema() -> str:
    """`ui.py`'s own CHAT_DB_SCHEMA, read out of the file rather than imported:
    importing `ui.py` pulls in Chainlit, which is an optional extra this suite
    runs without."""
    source = (Path(__file__).resolve().parents[1] / "ui.py").read_text(encoding="utf-8")
    return re.search(r'CHAT_DB_SCHEMA = """(.*?)"""', source, re.S).group(1)


def test_the_shipped_schema_parses_and_checks_clean_against_itself(tmp_path):
    declared = declared_columns(shipped_schema())
    assert {"users", "threads", "steps", "elements", "feedbacks"} <= set(declared)
    assert "defaultOpen" in declared["steps"]           # one of the newest columns

    with sqlite3.connect(tmp_path / "chat.db") as conn:
        conn.executescript(shipped_schema())
        assert check_chat_db(conn, shipped_schema()) == []
    conn.close()


def test_a_chat_db_from_before_the_steps_table_grew_is_caught(tmp_path):
    """The shipped schema against a `steps` table as an older release left it:
    the columns Chainlit's data layer writes today are named, one line."""
    with sqlite3.connect(tmp_path / "chat.db") as conn:
        conn.executescript('CREATE TABLE steps ("id" TEXT PRIMARY KEY, "name" TEXT, '
                           '"type" TEXT, "threadId" TEXT);')
        conn.executescript(shipped_schema())            # changes nothing: IF NOT EXISTS
        problems = check_chat_db(conn, shipped_schema(), path="chat.db")
    conn.close()
    assert len(problems) == 1 and "\'steps\'" in problems[0] and "defaultOpen" in problems[0]
