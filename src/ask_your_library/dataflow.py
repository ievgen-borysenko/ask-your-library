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
import os
from urllib.parse import urlsplit

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
    """A URL with any `user:password@` replaced, so a printed endpoint never
    carries the credential written into it; anything else unchanged."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not (parts.scheme and parts.netloc) or "@" not in parts.netloc:
        return value
    host = parts.netloc.rsplit("@", 1)[1]
    return parts._replace(netloc=f"<credentials>@{host}").geturl()
