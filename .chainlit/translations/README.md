# `.chainlit/translations/`

`en-US.json` in this directory is not written by this project. It is Chainlit
2.12.0's own `en-US.json`, taken from the installed package
(`chainlit/translations/en-US.json`) and copied byte for byte, with a single
value changed on 2026-09-10. Chainlit is licensed under the Apache License,
Version 2.0, and `NOTICE` in the repository root carries the attribution and
the record of this modification, as Apache-2.0 asks of a changed third-party
file. A whole copy rather than a one-key override is what the loader requires:
`chainlit.config.ChainlitConfig.load_translation` serves the file for the
effective language WHOLE, out of this directory alone, with no per-key merge
against the package's copy — a key missing here is a label missing from the
page. Every other language Chainlit ships lands here unversioned on startup and
is ignored by `.gitignore`; `init_config()` skips a file that already exists, so
this one survives a start, a `chainlit init` and a `chainlit lint-translations`.

The one changed value is `navigation.newChat.dialog.description`. Chainlit's
wording — "This will clear your current chat history. Are you sure you want to
continue?" — describes an app without a data layer. This one has: every chat is
written to `.chainlit/chat.db` and stays in the sidebar, so the New Chat button
destroys nothing and the stock confirmation warns about a loss that does not
happen. It now reads "This starts a new chat. The current chat stays in your
history." `tests/test_ui.py` pins all of it: the key set against the installed
package's file, so a Chainlit bump that adds or renames a key fails the suite
instead of blanking a label; the fact that this is the only string that differs;
that the startup seeding leaves it alone; and that `NOTICE` still names the file.
