# `src/ask_your_library/ui/translations/`

`en-US.json` in this directory is not written by this project. It is Chainlit
2.12.0's own `en-US.json`, taken from the installed package
(`chainlit/translations/en-US.json`) and copied byte for byte, with four values
changed — one on 2026-09-10, three on 2026-09-16. It is package data:
`launcher.py` copies it into the app root's `.chainlit/translations/` before
the server starts, because Chainlit seeds that directory with its own copy of
every language it ships and skips a name that is already there. Chainlit is licensed under the Apache License,
Version 2.0, and `NOTICE` in the repository root carries the attribution and
the record of this modification, as Apache-2.0 asks of a changed third-party
file. A whole copy rather than a one-key override is what the loader requires:
`chainlit.config.ChainlitConfig.load_translation` serves the file for the
effective language WHOLE, out of this directory alone, with no per-key merge
against the package's copy — a key missing here is a label missing from the
page. Every other language Chainlit ships lands in the app root unversioned on
startup; `init_config()` skips a file that already exists, so the copy made from
here survives a start, a `chainlit init` and a `chainlit lint-translations`.

The changed values are these four, and each is a claim `app.py` cannot make for
itself — the strings belong to Chainlit's own chrome, which takes no arguments
from the application.

- `navigation.newChat.dialog.description`. Chainlit's wording — "This will clear
  your current chat history. Are you sure you want to continue?" — describes an
  app without a data layer. This one has: every chat is written to
  the app root's `.chainlit/chat.db` and stays in the sidebar, so the New Chat button destroys
  nothing and the stock confirmation warns about a loss that does not happen. It
  now reads "This starts a new chat. The current chat stays in your history."
- `chat.messages.status.used` and `chat.messages.status.using`, both emptied.
  Chainlit renders an agent step as this word followed by the step's name, so
  the label read "Used act #1" — the framework's log, not what the application
  did. With the prefix gone, the name `app.py` writes is the whole label:
  "searched the library #1", "decided what to do next".
- `chat.watermark`, replaced with "Evidence provenance is checked in code. The
  reasoning is not." The stock line, "LLMs can make mistakes. Check important
  info.", sits directly under a badge reporting a code-only check and says both
  less and something else than this application knows. The replacement claims
  exactly what `validate` does and no more: it checks the provenance of the
  distilled EVIDENCE items against the passages they were copied from, not the
  quotation marks inside the answer the model then wrote.

Only `en-US` is forked. Every other locale falls back to Chainlit's own copy, so
the Ukrainian interface still prints upstream's step prefix in front of the
step's name.

`tests/test_ui.py` pins all of it: the key set against the installed package's
file, so a Chainlit bump that adds or renames a key fails the suite instead of
blanking a label; the exact set of strings that differ and what each one says,
so a fifth cannot be added in silence; that the startup seeding leaves the file
alone; and that `NOTICE` names every changed key.
