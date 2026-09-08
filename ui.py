"""Ask Your Library — web chat (Chainlit) over the same core as cli.py.

  uv run --extra ui chainlit run ui.py -w --host 127.0.0.1

Login: env CHAINLIT_USERNAME / CHAINLIT_PASSWORD (defaults admin / change-me;
override them for anything beyond local use).

Language switch: chat profile at the top of the chat (English / Ukrainian).
Language is a property of the conversation, not the process: picking a profile
starts a new chat, and resumed threads keep the language they were created
with. set_lang() writes to a ContextVar (ask_your_library.i18n) that
cl.make_async copies into the worker thread, so concurrent tabs in different
languages don't clobber each other. ASK_LANG remains the process default and
the fallback when a thread's profile can't be determined.

Requires the same as the CLI: an embedding backend, a LanceDB built by
scripts/ingest_demo_corpus.py or pointed to by LIBRARY_DB_PATH, and
OPENROUTER_API_KEY when the answering model or the embeddings come from OpenRouter
(not with LLM_BACKEND=ollama and local embeddings). The key is checked at startup (before anyone can log in);
the rest is checked per session, because a login page for a server that cannot
answer anything is worse than a refusal in the terminal.
"""
import functools
import hmac
import html
import json
import os
import re
import secrets
import sqlite3
import stat
from pathlib import Path

import chainlit as cl
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer

from ask_your_library.graph import build_graph
from ask_your_library.i18n import LANG, set_lang, status_word, t
from ask_your_library.preflight import check_api_key, check_environment
from ask_your_library.runner import run_question

PROFILE_EN = "English"
PROFILE_UA = "Українська"

SCRATCH_DIR = Path(os.environ.get("ASK_SCRATCH_DIR", ".scratch"))
# AYL_CHAINLIT_DIR exists so tests can import this module without touching the
# repo's .chainlit/ (the import creates the chat db and the auth secret there).
CHAINLIT_DIR = Path(os.environ.get("AYL_CHAINLIT_DIR", Path(__file__).parent / ".chainlit"))
CHAT_DB_PATH = CHAINLIT_DIR / "chat.db"
CLARIFY_TIMEOUT_SECONDS = 300

GREEN = "#16a34a"
YELLOW = "#ca8a04"
GRAY = "#6b7280"

# Login tokens need a stable secret, or every server restart logs everyone
# out. Generated once and persisted to a file (gitignored).
_secret_file = CHAINLIT_DIR / "auth-secret"
if not os.environ.get("CHAINLIT_AUTH_SECRET"):   # unset OR empty (a copied .env.example)
    if not _secret_file.exists():
        # 0600 from the first byte: no world-readable window before a chmod
        _fd = os.open(_secret_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(_fd, "w") as _f:
            _f.write(secrets.token_hex(32))
    _secret_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # the secret signs login tokens
    os.environ["CHAINLIT_AUTH_SECRET"] = _secret_file.read_text().strip()

# Refuse to serve with the placeholder password: a "local" demo has a habit of
# ending up port-forwarded. AYL_ALLOW_DEFAULT_LOGIN=1 acknowledges the risk.
_password = os.environ.get("CHAINLIT_PASSWORD", "change-me")
if not _password.strip():
    # An empty value would make compare_digest(b"", b"") succeed for anyone.
    raise SystemExit("CHAINLIT_PASSWORD is empty: set a real password (or unset it and export "
                     "AYL_ALLOW_DEFAULT_LOGIN=1 for the demo login)")
if (_password == "change-me"
        and os.environ.get("AYL_ALLOW_DEFAULT_LOGIN") != "1"):
    raise SystemExit(
        "Refusing to start with the default password: set CHAINLIT_PASSWORD "
        "(and CHAINLIT_USERNAME), or export AYL_ALLOW_DEFAULT_LOGIN=1 for a "
        "throwaway local demo.")

# A missing key is otherwise only discovered by on_chat_start, i.e. after
# someone has logged in — the operator starting the server sees nothing wrong.
# Chainlit's login page cannot carry custom text, so the refusal happens here,
# at startup, next to the password guard. Only the key is checked: the index and
# the embedding backend can legitimately come up later, and this must not touch
# them. AYL_ALLOW_START_WITHOUT_KEY=1 is for importing ui.py as a module
# (tests, the injection canary's UI stage), not for serving.
if os.environ.get("AYL_ALLOW_START_WITHOUT_KEY") != "1":
    _key_problem = check_api_key()
    if _key_problem:
        raise SystemExit(
            "Refusing to start without an OpenRouter key: export OPENROUTER_API_KEY "
            "(or put it in .env, or point OPENROUTER_ENV_FILE at a file containing "
            "it); export AYL_ALLOW_START_WITHOUT_KEY=1 to start anyway.")

# Compiled once per process: run_question gives every question its own
# thread_id, so one compiled graph is safe to share across sessions.
GRAPH = build_graph()


# --- persistence ---
# Schema from Chainlit's SQLAlchemy data layer docs, with UUID/JSONB
# simplified to TEXT for SQLite. Created once at startup.
CHAT_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    "id" TEXT PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" TEXT NOT NULL,
    "createdAt" TEXT
);
CREATE TABLE IF NOT EXISTS threads (
    "id" TEXT PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" TEXT,
    "userIdentifier" TEXT,
    "tags" TEXT,
    "metadata" TEXT,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS steps (
    "id" TEXT PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "parentId" TEXT,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" TEXT,
    "tags" TEXT,
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" TEXT,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    "autoCollapse" BOOLEAN,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS elements (
    "id" TEXT PRIMARY KEY,
    "threadId" TEXT,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" TEXT,
    "mime" TEXT,
    "props" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS feedbacks (
    "id" TEXT PRIMARY KEY,
    "forId" TEXT NOT NULL,
    "threadId" TEXT NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);
"""

CHAINLIT_DIR.mkdir(exist_ok=True)
with sqlite3.connect(CHAT_DB_PATH) as _connection:
    _connection.executescript(CHAT_DB_SCHEMA)


@cl.data_layer
def data_layer():
    return SQLAlchemyDataLayer(conninfo=f"sqlite+aiosqlite:///{CHAT_DB_PATH}")


@cl.password_auth_callback
def password_auth(username: str, password: str):
    """Login exists only because Chainlit hides the thread sidebar without
    an auth callback; there are no real user accounts."""
    expected_username = os.environ.get("CHAINLIT_USERNAME", "admin")
    expected_password = os.environ.get("CHAINLIT_PASSWORD", "change-me")
    # compare_digest on both fields: no timing side channel on the username either
    user_ok = hmac.compare_digest(username.encode(), expected_username.encode())
    pass_ok = hmac.compare_digest(password.encode(), expected_password.encode())
    if user_ok and pass_ok:
        return cl.User(identifier=username)
    return None


# --- agent steps ---
MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def neutralize_markdown(text: str) -> str:
    """Model- and corpus-derived text is rendered as Markdown by Chainlit even
    after html.escape; an image would make the browser fetch a third-party URL
    on render (a zero-click exfiltration channel). Inline images are replaced;
    every other image construct (reference style, nested or escaped alt text)
    is demoted to a plain link by dropping the "!", so nothing renders as an
    image and links still need a click."""
    text = MARKDOWN_IMAGE_RE.sub("[image removed]", text)
    return text.replace("![", "[")


async def show_step(step_name: str, step_output: str) -> None:
    # Step text mixes our labels with corpus/model-derived strings (book
    # titles, queries); with unsafe_allow_html enabled for our own badges,
    # everything third-party must be neutralized (quote=False keeps markdown readable).
    async with cl.Step(name=step_name, type="tool") as step:
        step.output = neutralize_markdown(html.escape(step_output, quote=False))


def verification_badge(update: dict) -> str:
    """Quote-provenance badge. The numbers come from update["provenance"];
    the verification text is only a fallback headline and tooltip when
    numbers are absent."""
    verification = update.get("verification", "")
    numbers = update.get("provenance") or {}
    tooltip = html.escape(verification, quote=True)
    title = t("ui_badge_title")

    if numbers.get("catalog"):
        # The catalogue path (ADR-016): a list computed by code from the index
        # tables, nothing to trace; the badge says what it is instead of "0/0".
        listing = numbers["catalog"]
        color = GREEN
        title = t("ui_badge_catalog_title")
        headline = t("ui_badge_catalog", n=listing["count"], total=listing["total"])
        details = ""
    elif not numbers:
        # Event without numbers (shouldn't happen with the current runner):
        # neutral badge, no locale-bound text sniffing.
        color = GRAY
        headline = html.escape(verification).replace("\n", "<br>")
        details = ""
    elif numbers.get("checked", 0) == 0:
        # no evidence: the answer is itself an honest refusal, nothing to verify
        color = GRAY
        headline = html.escape(verification)
        details = ""
    elif numbers.get("broken", 0) == 0 and numbers.get("unattributed", 0) == 0:
        color = GREEN
        headline = t("ui_badge_ok", ok=numbers["confirmed"], all=numbers["checked"])
        details = ""
    elif numbers.get("broken", 0) == 0:
        # Text found, book not: honest amber, not green.
        color = YELLOW
        headline = t("ui_badge_unattributed", ok=numbers["confirmed"], all=numbers["checked"],
                     n=numbers["unattributed"])
        details = ""
    else:
        color = YELLOW
        headline = t("ui_badge_warn", broken=numbers["broken"], all=numbers["checked"])
        items_html = ""
        for item in numbers.get("broken_items", []):
            quote_preview = item.get("quote", "")[:160]
            items_html += (f"<li>{safe_html(item.get('book', '?'))} — "
                           f"{safe_html(item.get('section', '?'))}: "
                           f"\"{safe_html(quote_preview)}\"</li>")
        details = (f"<details><summary>{t('ui_badge_which')}</summary>"
                   f"<ul>{items_html}</ul></details>")

    unused = numbers.get("unused", 0)
    unused_note = t("ui_badge_unused", n=unused) if unused else ""

    return (f'<div title="{tooltip}" style="border-left: 4px solid {color}; '
            f'background: {color}1a; padding: 8px 12px; border-radius: 4px;">'
            f'<b>{title}</b><br>{headline}{unused_note}{details}</div>')


class RunView:
    """What one question's rendering needs to remember across events: the
    passages of the run by hit_id (from the act events), so the evidence list
    after the badge can open each quote on the text it was checked against.
    One per question; render_event gets it through functools.partial."""

    def __init__(self):
        self.passages: dict[str, str] = {}


def safe_html(text: str) -> str:
    """Corpus- or model-derived text inside our HTML: escaped, image-free, and
    without line breaks. The whole message is ONE CommonMark HTML block, and a
    blank line ends such a block: a card passage with paragraphs would spill
    out of its <details> and render as chat markdown. <br> keeps the layout."""
    return neutralize_markdown(html.escape(text, quote=False)).replace("\n", "<br>")


def evidence_passages(items: list[dict], passages: dict[str, str]) -> str:
    """One <details> per PASSAGE (hit id), in evidence order: book, section, hit
    id and the verdict count in the summary; inside, every quote checked against
    that passage with its verdict, then the passage as observe saw it. Several
    items often share one hit, so the passage is rendered once, not per item."""
    by_hit: dict[str, list[dict]] = {}
    for item in items:
        by_hit.setdefault(item.get("hit_id", ""), []).append(item)
    blocks = []
    for hit_id, group in by_hit.items():
        first = group[0]
        passage = passages.get(hit_id)
        body = (f'<pre style="white-space: pre-wrap; font-size: 0.85em;">{safe_html(passage)}</pre>'
                if passage is not None else f"<i>{t('ui_passage_missing')}</i>")
        verdicts = " · ".join(f"{safe_html(status_word(s))} {sum(1 for i in group if i.get('status') == s)}"
                              for s in ("confirmed", "unattributed", "broken")
                              if any(i.get("status") == s for i in group))
        quotes = "".join(f"<li><b>{safe_html(status_word(i.get('status', '')))}</b>: "
                         f"<q>{safe_html(i.get('quote', ''))}</q></li>" for i in group)
        blocks.append(
            f"<details><summary>{safe_html(first.get('book', '?'))} — {safe_html(first.get('section', '?'))} · "
            f"<code>{safe_html(hit_id)}</code> · {verdicts}</summary>"
            f"<ul>{quotes}</ul>{body}</details>")
    return (f'<div style="font-size: 0.9em;"><b>{t("ui_evidence_title", n=len(items), p=len(by_hit))}</b>'
            f'{"".join(blocks)}</div>')


async def show_metrics(metrics: dict) -> None:
    # Session cost is accumulated here because the metrics event only ever
    # describes one question (see runner.run_question). A partial event (the
    # run paused at a clarify) is shown, not added: the final event covers it.
    partial = bool(metrics.get("partial"))
    session_cost = (cl.user_session.get("session_cost") or 0.0) + (0.0 if partial else metrics.get("cost_usd", 0.0))
    if not partial:
        cl.user_session.set("session_cost", session_cost)

    if partial:
        summary = t("ui_m_partial", model=metrics.get("model", "?"),
                    cost=metrics.get("cost_usd", 0), sec=metrics.get("seconds", "?"),
                    steps=metrics.get("steps_taken", 0))
    else:
        summary = t("ui_m_summary", model=metrics.get("model", "?"),
                    cost=metrics.get("cost_usd", 0), scost=session_cost,
                    sec=metrics.get("seconds", "?"), steps=metrics.get("steps_taken", 0),
                    stop=metrics.get("stop_reason") or "?")

    role_rows = ""
    for role, usage in (metrics.get("by_role") or {}).items():
        role_rows += (f"<tr><td>{html.escape(role)}</td><td>{usage['calls']}</td>"
                      f"<td>{usage['input_tokens']}</td><td>{usage['output_tokens']}</td>"
                      f"<td>${usage['cost_usd']:.4f}</td></tr>")

    details = (
        f"<details><summary>{t('ui_m_details')}</summary>"
        f"<table><tr>{t('ui_m_th')}</tr>"
        f"{role_rows}</table>"
        f"<div>{t('ui_m_tokens', calls=metrics.get('llm_calls', 0), tin=metrics.get('input_tokens', 0), tout=metrics.get('output_tokens', 0), cache=metrics.get('cache_read_tokens', 0))}</div>"
        f"<div>{t('ui_m_retrieval', hits=metrics.get('hits_seen', 0), ev=metrics.get('evidence_distilled', 0))}</div>"
        f"<div>{t('ui_m_injection', n=metrics.get('redacted_lines', 0))}</div>"
        "</details>")

    await cl.Message(content=(f'<div style="color:{GRAY}; font-size:0.85em;">'
                              f'{html.escape(summary)}{details}</div>')).send()


def render_event(node_name: str, update: dict, view: RunView | None = None) -> None:
    """Called from a worker thread; cl.make_async copies the Chainlit
    context into it, which is why cl.run_sync works here. `view` is this
    question's memory (on_message makes one per question)."""
    view = view if view is not None else RunView()
    if node_name == "plan":
        if update["mode"] == "catalog":
            lines = [t("ui_plan_catalog", op=update["catalog_request"]["op"])]
        else:
            queries = [update["current_query"]] + update["queries"]
            lines = [t("ui_mode", mode=update["mode"]), t("ui_queries")]
            for query in queries:
                lines.append(f"- {query}")
        if update.get("catalog_fallback"):
            lines.append(t("ui_catalog_fallback"))
        if update.get("book_filter"):
            lines.append(t("ui_book_filter", book=update["book_filter"]))
        if update.get("book_unresolved"):
            lines.append(t("ui_book_unresolved", q=update["book_unresolved"]))
        if update.get("clarify_unresolved"):
            lines.append(t("ui_clarify_unresolved"))
        if update.get("plan_fallback"):
            lines.append(t("ui_plan_fallback"))
        cl.run_sync(show_step("plan", "\n".join(lines)))

    elif node_name == "act":
        lines = [t("ui_hits", n=len(update["hits"]))]
        for hit in update["hits"]:
            lines.append(f"- [{hit['corpus']}] {hit['book']} — {hit['section']}")
        for h in update.get("hits_log", []):
            view.passages[h["hit_id"]] = h["text"]
        cl.run_sync(show_step(f"act #{update['steps_taken']}", "\n".join(lines)))

    elif node_name == "observe":
        text = t("ui_evidence", n=len(update["evidence"]))
        if update["empty_streak"]:
            text += t("ui_streak", n=update["empty_streak"])
        cl.run_sync(show_step("observe", text))

    elif node_name == "reflect":
        next_query = update.get("current_query")
        if next_query == "__clarify__":
            text = t("ui_clarify_step")
        elif next_query and next_query.startswith("__chapter__|"):
            _, book, section = next_query.split("|", 2)
            text = t("ui_chapter", book=book, section=section)
        elif next_query and next_query.startswith("__book__|"):
            _, book, _ = next_query.split("|", 2)
            text = t("ui_probe", book=book)
        elif next_query:
            text = t("ui_search_more", q=next_query)
        elif update.get("stop_reason"):
            # "enough evidence" and "step limit" are different outcomes; show the
            # real one instead of a generic "enough".
            text = t("ui_stopped", r=update["stop_reason"])
        else:
            text = t("ui_enough")
        cl.run_sync(show_step("reflect", text))

    elif node_name == "clarify":
        cl.run_sync(show_step("clarify",
                              t("ui_user_clarified", a=update["clarification"])))

    elif node_name == "catalog":
        listing = update["catalog"]
        cl.run_sync(show_step("catalog", t("ui_catalog_step", op=listing["op"], n=listing["count"],
                                           total=listing["total"])))
        # Titles are index metadata, i.e. data: rendered as text like a model answer.
        cl.run_sync(cl.Message(content=neutralize_markdown(html.escape(update["answer"], quote=False))).send())

    elif node_name == "synthesize":
        # The answer is model output over corpus text: poisoned corpus HTML
        # must render as text, not DOM (unsafe_allow_html is on for badges).
        cl.run_sync(cl.Message(content=neutralize_markdown(html.escape(update["answer"], quote=False))).send())

    elif node_name == "validate":
        cl.run_sync(cl.Message(content=verification_badge(update)).send())
        items = (update.get("provenance") or {}).get("items") or []
        if items:
            # The badge is a count; this is the openable evidence: each quote on
            # the passage it was checked against (the audits' first ask).
            cl.run_sync(cl.Message(content=evidence_passages(items, view.passages)).send())

    elif node_name == "metrics":
        cl.run_sync(show_metrics(update))


# --- clarify (HITL) ---
def ask_user_in_chat(question_to_user: str) -> str:
    """on_clarify for the web UI; called from a worker thread, hence
    cl.run_sync (see render_event)."""
    reply = cl.run_sync(
        cl.AskUserMessage(content=neutralize_markdown(html.escape(question_to_user, quote=False)),
                          timeout=CLARIFY_TIMEOUT_SECONDS).send())
    if reply is None:
        # on timeout, the agent proceeds without the clarification
        return ""
    return reply["output"].strip()


# --- language / chat ---
@cl.set_chat_profiles
async def chat_profiles():
    """Chat profile doubles as the language switch: picking a profile
    starts a new chat, and existing threads keep the profile they were
    created with."""
    return [
        cl.ChatProfile(
            name=PROFILE_EN,
            markdown_description="Interface and agent answers in **English**."),
        cl.ChatProfile(
            name=PROFILE_UA,
            markdown_description="Інтерфейс і відповіді агента **українською**."),
    ]


def session_lang(chat_profile: str | None) -> str:
    """Session language from the chat profile name, falling back to the
    process default (ASK_LANG) when no profile is set."""
    if chat_profile == PROFILE_EN:
        return "en"
    if chat_profile == PROFILE_UA:
        return "ua"
    return LANG


@cl.on_chat_start
async def on_chat_start() -> None:
    lang = session_lang(cl.user_session.get("chat_profile"))
    cl.user_session.set("lang", lang)
    set_lang(lang)  # before the welcome message, so t() speaks the profile language
    cl.user_session.set("history", [])
    cl.user_session.set("session_cost", 0.0)
    # Environment problems as a readable message instead of a traceback on the
    # first question (which would also bill an LLM call before failing).
    problems = await cl.make_async(check_environment)()
    cl.user_session.set("ready", not problems)
    if problems:
        text = t("pf_header") + "\n" + "\n".join(f"- {p}" for p in problems)
        await cl.Message(content=html.escape(text, quote=False)).send()
        return
    # Non-fatal notices (a degraded index, e.g. no cards table): the session
    # works, but the user is told in the chat, not only in the server log.
    notices = getattr(problems, "notices", [])
    if notices:
        text = t("pf_notice_header") + "\n" + "\n".join(f"- {n}" for n in notices)
        await cl.Message(content=html.escape(text, quote=False)).send()
    await cl.Message(content=t("ui_welcome")).send()


@cl.on_chat_resume
async def on_chat_resume(thread) -> None:
    """Restore the resumed thread's language and rebuild the runner's
    history format from the thread's persisted steps."""
    # Chainlit puts the thread's chat_profile into the session before this
    # callback runs; fall back to thread metadata (SQLite returns it as a
    # JSON string).
    chat_profile = cl.user_session.get("chat_profile")
    if not chat_profile:
        metadata = thread.get("metadata") or {}
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except ValueError:
                metadata = {}
        chat_profile = metadata.get("chat_profile")
    lang = session_lang(chat_profile)
    cl.user_session.set("lang", lang)
    set_lang(lang)

    history = []
    last_question = ""
    for step in thread.get("steps", []):
        step_output = (step.get("output") or "").strip()
        if not step_output:
            continue
        if step.get("type") == "user_message":
            last_question = step_output
        elif step.get("type") == "assistant_message":
            # badges/metrics (HTML) and the welcome message are not agent answers
            if step_output.startswith("<div") or step_output.startswith("Ask Your Library —"):
                continue
            if last_question:
                history.append(f"Q: {last_question}\nA: {step_output[:500]}")
                last_question = ""
    cl.user_session.set("history", history)
    cl.user_session.set("session_cost", 0.0)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    # Language first: this ContextVar write travels with the context into
    # the worker thread via cl.make_async, so the agent's own generated
    # text follows it too.
    set_lang(cl.user_session.get("lang") or LANG)
    if not cl.user_session.get("ready"):
        # A failed preflight must not let a question reach the (billed) planner.
        problems = await cl.make_async(check_environment)()
        if problems:
            text = t("pf_header") + "\n" + "\n".join(f"- {p}" for p in problems)
            await cl.Message(content=html.escape(text, quote=False)).send()
            return
        cl.user_session.set("ready", True)
    history = cl.user_session.get("history")
    try:
        answer = await cl.make_async(run_question)(
            GRAPH, message.content, history, SCRATCH_DIR,
            on_event=functools.partial(render_event, view=RunView()), on_clarify=ask_user_in_chat)
    except Exception as error:
        # Class + short message only: a raw exception can leak paths and
        # provider details into the chat.
        short = f"{type(error).__name__}: {str(error)[:200]}"
        await cl.Message(content=html.escape(t("ui_error", e=short), quote=False)).send()
        return

    # Conversation memory: the question plus a truncated answer.
    history.append(f"Q: {message.content}\nA: {answer[:500]}")
