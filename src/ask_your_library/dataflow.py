"""The settings that decide where data goes, and the rule for "fully local".

One definition for the Python side: `ayl init` judges its local mode with it,
and the verification step of `scripts/install-mac.sh` imports it. The
installer's own guard runs before any Python is installed and keeps a bash
copy of the same names (`BACKEND_VARS` ... `KEY_VARS` there); a name added
here is a name to add there.

Tracing is read by two libraries with two truth tables. langsmith reads the
four v2 names for "is tracing on" and uploads on the exact string "true" —
every value outside TRACING_OFF is treated as on here, the fail-closed side.
langchain_core reads the two v1 names and counts a name as SET unless its
value is "", "0", "false" or "False"; set, with v2 tracing off, it makes the
first model call raise. LANGCHAIN_TRACING is in both lists on purpose.
"""
import base64
import os
import re
from urllib.parse import unquote, urlsplit

from .sanitize import strip_control_chars

BACKEND_VARS = ("LLM_BACKEND", "EMBED_BACKEND")
ENDPOINT_VARS = ("OLLAMA_URL", "OLLAMA_HOST", "OPENROUTER_BASE_URL", "LANGCHAIN_ENDPOINT",
                 "LANGSMITH_ENDPOINT")
TRACING_V2_VARS = ("LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING",
                   "LANGCHAIN_TRACING")
TRACING_V1_VARS = ("LANGCHAIN_TRACING", "LANGCHAIN_HANDLER")
TRACING_VARS = ("LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING",
                "LANGCHAIN_TRACING", "LANGCHAIN_HANDLER")
TRACING_OFF = ("", "false", "0", "no", "off")
# LANGCHAIN_API_KEY is judged: `graph.enable_tracing_if_key_present` turns a key
# with no LANGCHAIN_TRACING_V2 set into tracing. LANGSMITH_API_KEY is reported
# beside it; nothing in this project reads it.
KEY_VARS = ("LANGCHAIN_API_KEY", "LANGSMITH_API_KEY")
DATA_FLOW_VARS = BACKEND_VARS + ENDPOINT_VARS + TRACING_VARS + KEY_VARS
LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")


def is_loopback(url: str) -> bool:
    return urlsplit(url).hostname in LOOPBACK_HOSTS


def tracing_on(environ=None) -> list[str]:
    """The v2 names whose value is not a spelling of off."""
    environ = os.environ if environ is None else environ
    return [name for name in TRACING_V2_VARS
            if environ.get(name, "").strip().lower() not in TRACING_OFF]


def v1_tracing_set() -> list[str]:
    """The v1 names langchain_core counts as set, by its own function rather
    than a copy of its rule (it reads `os.environ`)."""
    from langchain_core.utils.env import env_var_is_set
    return [name for name in TRACING_V1_VARS if env_var_is_set(name)]


def without_credentials(value: str) -> str:
    """A value with any `user:password@` in front of its host replaced by
    `<credentials>@`, so a printed endpoint never carries the credential
    written into it. The host and everything after it are kept.

    Read as text, not through `urlsplit`, and the same way with or without a
    scheme: `user:secret@host:11434` written without `http://` is still a
    credential, and a value that is not a URL at all (a model name, a path)
    has no `@` before its first `/` and comes back unchanged. The installer's
    bash `shown_url` applies the same rule."""
    scheme, rest = value.split("://", 1) if "://" in value else ("", value)
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" not in authority:
        return value
    return (f"{scheme + '://' if scheme else ''}<credentials>@"
            f"{authority.rsplit('@', 1)[1]}{rest[len(authority):]}")


# --- text a server sent back -----------------------------------------------------
# A server reached through a URL with `user:password@` in it receives that
# credential (requests sends it as Basic auth) and can put it into anything it
# answers. So no text from a response is printed as it came: it goes through
# `server_text`, and a message that does not need it does not carry it.
SERVER_TEXT_LIMIT = 160
WITHHELD = "(the server's own text is withheld: it carries part of a credential)"


def credentials_of(url: str) -> list[str]:
    """Every spelling of the credential written into `url` that a server
    could send back: the user name and the password as written and
    percent-decoded, the whole `user:password`, and its Base64 (standard and
    URL-safe, with and without padding) — the Authorization header requests
    built from it. Longest first; empty when the URL carries none."""
    rest = url.split("://", 1)[1] if "://" in url else url
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" not in authority:
        return []
    userinfo = authority.rsplit("@", 1)[0]
    user, _, password = userinfo.partition(":")
    found = {userinfo, user, password, unquote(userinfo), unquote(user), unquote(password)}
    for pair in {userinfo, f"{unquote(user)}:{unquote(password)}"}:
        raw = pair.encode("utf-8")
        for encoded in (base64.b64encode(raw), base64.urlsafe_b64encode(raw)):
            text = encoded.decode("ascii")
            found |= {text, text.rstrip("=")}
    return sorted((value for value in found if value), key=len, reverse=True)


def configured_credentials(*urls: str) -> list[str]:
    """Every spelling (`credentials_of`) of the credentials in `urls` and in
    every URL-valued setting this process is configured with: OLLAMA_URL,
    OPENROUTER_BASE_URL and the endpoints in ENDPOINT_VARS. Longest first."""
    from . import config      # here, not at the top: config is loaded lazily by its users
    every = [*urls, config.OLLAMA_URL, config.OPENROUTER_BASE_URL,
             *(os.environ.get(name, "") for name in ENDPOINT_VARS)]
    return sorted({secret for url in every for secret in credentials_of(url)},
                  key=len, reverse=True)


def scrub_credentials(text: str, *urls: str) -> str:
    """`text` with every spelling of a configured credential (and of the
    credentials in `urls`) replaced by `<credentials>`. A part shorter than
    four characters cannot be replaced without garbling the text around it (a
    one-letter user name is in every word), so when one occurs the whole text
    is withheld instead. For an exception's message, which may carry a
    server's reply, before it is printed, logged or recorded."""
    text = str(text)
    for secret in configured_credentials(*urls):
        if secret in text:
            if len(secret) < 4:
                return WITHHELD
            text = text.replace(secret, "<credentials>")
    return text


def server_text(text, url: str = "", limit: int = SERVER_TEXT_LIMIT) -> str:
    """`text` from a server's response, made fit to print: every spelling of a
    credential replaced (`scrub_credentials`, including `url`'s), control
    characters stripped, whitespace folded to single spaces, and the length
    capped. The one sanitiser every server-provided string goes through."""
    text = scrub_credentials(str(text), url)
    if text == WITHHELD:
        return text
    text = re.sub(r"\s+", " ", strip_control_chars(text)).strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"
