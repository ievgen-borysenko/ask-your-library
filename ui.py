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
import contextlib
import sqlite3
import stat
from pathlib import Path

import chainlit as cl
import chainlit.auth.cookie as chainlit_cookie
from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
from chainlit.server import app as chainlit_app
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ask_your_library.graph import build_graph
from ask_your_library.i18n import LANG, set_lang, status_word, t
from ask_your_library.preflight import check_api_key, check_environment
from ask_your_library.runner import history_entry, run_question
from ask_your_library.sanitize import LINE_BREAK_RE

# A single-user local app never needs the login cookie on a cross-site request;
# strict keeps it off one, and Chainlit's own default is lax. CHAINLIT_COOKIE_SAMESITE
# cannot deliver that here: chainlit.auth.cookie reads it once, at ITS import
# time, and under `chainlit run ui.py` that has already happened before this
# file is loaded at all — the console script imports chainlit.cli, which reaches
# chainlit.auth.cookie through ensure_jwt_secret, and calls load_module(ui.py)
# afterwards. A .env entry is later still (config.load_dotenv runs on the import
# above). So the two module globals are set directly; they are read at request
# time, where the cookie is written, not captured at import.
# secure stays False, which is what Chainlit computes for strict: a Secure cookie
# is dropped by the browser over plain http, i.e. over the loopback the UI serves.
# These are private names, pinned to Chainlit 2.12.0 — hence the check, and
# test_the_login_cookie_is_really_strict_under_chainlit_run.
if not all(hasattr(chainlit_cookie, name)
           for name in ("_cookie_samesite", "_cookie_secure")):
    raise SystemExit("chainlit.auth.cookie no longer has _cookie_samesite/_cookie_secure: the "
                     "login cookie policy is not being applied, check the Chainlit version")
chainlit_cookie._cookie_samesite = "strict"
chainlit_cookie._cookie_secure = False

PROFILE_EN = "English"
PROFILE_UA = "Українська"

# A page in the reader's browser can send requests to a loopback server; it
# cannot choose the Host header, and a name it controls that resolves to
# 127.0.0.1 (DNS rebinding) arrives here as that name. Refusing every Host but
# the two loopback ones costs nothing locally and closes the browser-side route
# to /login and the thread endpoints. It is the Host check, not allow_origins:
# CORS governs what a page may READ cross-origin, and a login POST does not
# need to be read to have happened.
ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

SCRATCH_DIR = Path(os.environ.get("ASK_SCRATCH_DIR", ".scratch"))
# AYL_CHAINLIT_DIR exists so tests can import this module without touching the
# repo's .chainlit/ (the import creates the chat db and the auth secret there).
CHAINLIT_DIR = Path(os.environ.get("AYL_CHAINLIT_DIR", Path(__file__).parent / ".chainlit"))
CHAT_DB_PATH = CHAINLIT_DIR / "chat.db"
CLARIFY_TIMEOUT_SECONDS = 300

GREEN = "#16a34a"
YELLOW = "#ca8a04"
GRAY = "#6b7280"

# Registered on Chainlit's own Starlette app, at import time: the middleware
# stack is built when the server starts, and adding one afterwards is too late.
# The guard is for a second import of this module in one process (the tests do
# that): chainlit.server keeps the app, so the middleware must not stack up.
if not any(m.cls is TrustedHostMiddleware for m in chainlit_app.user_middleware):
    chainlit_app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

# Before anything is written into it: the repo's .chainlit/ exists (config.toml
# is committed), but AYL_CHAINLIT_DIR points somewhere that usually does not.
CHAINLIT_DIR.mkdir(parents=True, exist_ok=True)

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


def own_read_write_only(path: Path) -> None:
    """0600 for `path` and its SQLite siblings (-wal, -shm, -journal).

    The chat db holds every question, answer and passage of every session, but
    SQLite creates it with the process umask (0644 on a default account) while
    the auth secret next to it is 0600. The mode is set after the schema is
    written, and again on every start, so a db from an older version is
    narrowed too — and once more in on_chat_start, because the siblings only
    appear when the data layer opens the db, i.e. after the startup pass."""
    for candidate in (path, *sorted(path.parent.glob(f"{path.name}-*"))):
        if candidate.is_file():
            candidate.chmod(stat.S_IRUSR | stat.S_IWUSR)


with contextlib.closing(sqlite3.connect(CHAT_DB_PATH)) as _connection:
    # `closing`: a `with` on a sqlite3 connection commits but does not close it
    with _connection:
        _connection.executescript(CHAT_DB_SCHEMA)
own_read_write_only(CHAT_DB_PATH)


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
    # everything third-party must be neutralized. A step is plain markdown, so
    # safe_markdown, not safe_html: its line breaks are the list it prints.
    async with cl.Step(name=step_name, type="tool") as step:
        step.output = safe_markdown(step_output)


def verification_badge(update: dict) -> str:
    """Quote-provenance badge. The numbers come from update["provenance"];
    the verification text is only a fallback headline and tooltip when
    numbers are absent."""
    verification = update.get("verification", "")
    numbers = update.get("provenance") or {}
    # The verification text is built around the quotes that failed, i.e. around
    # corpus text. Escaping alone is not enough here: a blank line in it ends
    # the message's HTML block, and what follows is rendered as chat markdown:
    # an image reference there is fetched with no click. Images are neutralized
    # and every line break becomes a space — every form of one, because
    # CommonMark ends a block on a bare CR and on U+2028/U+0085 too, not only on
    # LF. A <br> inside a title attribute would be shown literally.
    tooltip = LINE_BREAK_RE.sub(" ", neutralize_markdown(html.escape(verification, quote=True)))
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
        headline = safe_html(verification)
        details = ""
    elif numbers.get("checked", 0) == 0:
        # no evidence: the answer is itself an honest refusal, nothing to verify
        color = GRAY
        headline = safe_html(verification)
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
        # the catalogue result when the question took that path: the conversation
        # memory keeps its shape, never the list of titles (runner.history_entry)
        self.catalog: dict | None = None


def safe_markdown(text: str) -> str:
    """Corpus- or model-derived text in a message we send as plain Markdown (the
    answer, the steps, the clarify question, the preflight and error lines):
    escaped and image-free, line breaks left as they are, so a "- item" list
    still renders as a list. For text going INSIDE one of our own HTML blocks
    use safe_html, which turns those breaks into <br>."""
    return neutralize_markdown(html.escape(text, quote=False))


def safe_html(text: str) -> str:
    """Corpus- or model-derived text inside our HTML: escaped, image-free, and
    without line breaks. The whole message is ONE CommonMark HTML block, and a
    blank line ends such a block: a card passage with paragraphs would spill
    out of its <details> and render as chat markdown. <br> keeps the layout.
    Every form of line break, not only LF: CommonMark ends a block on a bare CR
    and on U+2028/U+0085 as well (LINE_BREAK_RE, shared with data_block)."""
    return LINE_BREAK_RE.sub("<br>", safe_markdown(text))


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
        # A div, not a pre: Chainlit renders a <pre> with its code-snippet
        # component ("Raw code" plus a copy button) and the text inside it is
        # dropped, so the passage the badge points at was invisible in the
        # browser. The style keeps the monospaced, wrapped look a pre gave it;
        # safe_html already turns the line breaks into <br>.
        body = (f'<div style="white-space: pre-wrap; font-family: monospace; '
                f'font-size: 0.85em;">{safe_html(passage)}</div>'
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
        role_rows += (f"<tr><td>{safe_html(role)}</td><td>{usage['calls']}</td>"
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

    # safe_html, not html.escape: the summary interpolates the stop reason, which
    # reflect writes from the model's decision. The escape kept the HTML inert
    # but left a blank line able to end this HTML block, and a markdown image
    # after it would be fetched on render.
    await cl.Message(content=(f'<div style="color:{GRAY}; font-size:0.85em;">'
                              f'{safe_html(summary)}{details}</div>')).send()


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
            lines.append(t("ui_catalog_fallback_" + update["catalog_fallback"]))
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
        view.catalog = listing
        cl.run_sync(show_step("catalog", t("ui_catalog_step", op=listing["op"], n=listing["count"],
                                           total=listing["total"])))
        # Titles are index metadata, i.e. data: rendered as text like a model answer.
        # The shape of the result travels with the persisted message, so a resumed
        # chat rebuilds its memory without the list (on_chat_resume).
        shape = {key: listing[key] for key in ("op", "count", "total", "query", "resolved")}
        cl.run_sync(cl.Message(content=neutralize_markdown(html.escape(update["answer"], quote=False)),
                               metadata={"catalog": shape}).send())

    elif node_name == "synthesize":
        # The answer is model output over corpus text: poisoned corpus HTML
        # must render as text, not DOM (unsafe_allow_html is on for badges).
        cl.run_sync(cl.Message(content=safe_markdown(update["answer"])).send())

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
        cl.AskUserMessage(content=safe_markdown(question_to_user),
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
    # Again here, not only at import: the -wal and -journal siblings hold the
    # same questions and answers as the db, and SQLite creates them with the
    # process umask when the data layer opens a session — i.e. after the import
    # narrowed what existed then. Before the preflight, so the path that reports
    # problems and returns narrows them too.
    own_read_write_only(CHAT_DB_PATH)
    # Environment problems as a readable message instead of a traceback on the
    # first question (which would also bill an LLM call before failing).
    problems = await cl.make_async(check_environment)()
    cl.user_session.set("ready", not problems)
    if problems:
        text = t("pf_header") + "\n" + "\n".join(f"- {p}" for p in problems)
        await cl.Message(content=safe_markdown(text)).send()
        return
    # Non-fatal notices (a degraded index, e.g. no cards table): the session
    # works, but the user is told in the chat, not only in the server log.
    notices = getattr(problems, "notices", [])
    if notices:
        text = t("pf_notice_header") + "\n" + "\n".join(f"- {n}" for n in notices)
        await cl.Message(content=safe_markdown(text)).send()
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
                # A catalogue answer is remembered by its shape only (never the
                # titles): the shape rides on the persisted message's metadata.
                meta = step.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except ValueError:
                        meta = {}
                catalog_shape = meta.get("catalog") if isinstance(meta, dict) else None
                # The answer was escaped for rendering (html.escape at write
                # time); escaping is the browser's business, not the model's.
                # Without this the resumed conversation memory carries "&amp;"
                # and "&lt;" into the next planner and synthesize prompt.
                history.append(history_entry(last_question, html.unescape(step_output),
                                             catalog_shape))
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
            await cl.Message(content=safe_markdown(text)).send()
            return
        cl.user_session.set("ready", True)
    history = cl.user_session.get("history")
    view = RunView()
    try:
        answer = await cl.make_async(run_question)(
            GRAPH, message.content, history, SCRATCH_DIR,
            on_event=functools.partial(render_event, view=view), on_clarify=ask_user_in_chat)
    except Exception as error:
        # Class + short message only: a raw exception can leak paths and
        # provider details into the chat.
        short = f"{type(error).__name__}: {str(error)[:200]}"
        # Same treatment as every other message: an exception message can carry
        # corpus text (a book title in a lookup error). Plain markdown, not an
        # HTML block, so the escape and the image neutralization are the whole
        # job and the line breaks stay line breaks.
        await cl.Message(content=safe_markdown(t("ui_error", e=short))).send()
        return

    # Conversation memory: the question plus a truncated answer; a catalogue
    # answer only as its shape, never the list of titles.
    history.append(history_entry(message.content, answer, view.catalog))
