"""The web chat and what it takes to start one.

`app.py` is the Chainlit application itself — the module `chainlit run` loads —
and `launcher.py` is what `ayl ui` calls: it prepares the app root Chainlit
reads its configuration from, then starts the server against `app.py`.

Nothing is imported here. `app.py` needs the `ui` extra (Chainlit, SQLAlchemy,
aiosqlite), and importing this package must stay free for a plain install —
`launcher.py` is reached from `ayl.py`, which is on every `ayl` command's
import path, and the launcher itself starts Chainlit as a subprocess rather
than importing it."""
