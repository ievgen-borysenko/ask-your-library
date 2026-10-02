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
import re
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


# What a URL-valued setting may be printed as: rebuilt from a scheme, a host
# and a port that this pattern extracted from the WHOLE value — an allowlist,
# not a redaction. Parsing a credential out of a value failed three ways (the
# first delimiter, a / ? or # inside a password, a "://" inside a scheme-less
# value); nothing is taken out here, only the three parts that cannot hold one
# are put back together. The path, query and fragment are never printed: they
# can hold a token. scripts/install-mac.sh's `shown_url` is the same rule.
PLAIN_URL = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*)://([A-Za-z0-9.-]+|\[[0-9A-Fa-f:.]+\])"
                       r"(:[0-9]{1,5})?([/?#].*)?", re.DOTALL)
NOT_SHOWN = "<not shown: the value carries a credential or is not a plain URL>"
PATH_NOT_SHOWN = " (path not shown)"


def shown_url(value: str) -> str:
    """`value` as it may be printed: `scheme://host[:port]`, plus
    "(path not shown)" when a path, query or fragment followed — or, for a
    value with an `@` anywhere or one the pattern does not match whole (no
    scheme, an odd character, an empty host), the fixed words NOT_SHOWN and
    nothing of the value. Printing only: requests and the loopback check use
    the real value."""
    value = str(value)
    match = None if "@" in value else PLAIN_URL.fullmatch(value)
    if match is None:
        return NOT_SHOWN
    scheme, host, port, rest = match.groups()
    return f"{scheme}://{host}{port or ''}{PATH_NOT_SHOWN if rest else ''}"


# --- whether a URL may go to a child whose errors are not ours to word ---------
# The demo build `ayl init --demo` starts is a child process whose error output
# can print the URL it requested (the embedders' HTTP errors, issue #107). It is
# started only for URLs that cannot carry anything secret: plain ones whose path
# is one of these. Deciding by what a value looks like failed for an `@`, for a
# query and for a path; this is a short list of what is known to be safe, and
# everything else counts. scripts/install-mac.sh's SAFE_URL_PATHS is the same
# list (the empty path is always safe there), and a test holds the two equal.
SAFE_URL_PATHS = ("", "/", "/v1", "/v1/", "/api/v1", "/api/v1/")


def carries_credential(value: str) -> bool:
    """True unless `value` is a plain URL (`shown_url` can print it) whose
    path part is one of SAFE_URL_PATHS — so any other path, any query, any
    fragment, any `@` and any value the strict pattern does not match count.
    Decides only whether the demo build may start (and the installer's
    `--yes` refusal). scripts/install-mac.sh's `carries_credential` is the
    same rule."""
    if shown_url(value) == NOT_SHOWN:
        return True
    return (PLAIN_URL.fullmatch(str(value)).group(4) or "") not in SAFE_URL_PATHS


# The settings a request is sent to. OLLAMA_HOST is not one of them, by
# decision: it is printed through `shown_url` like every URL-valued setting,
# and NOT counted in `credential_configured`. It is the Ollama server's own
# bind address, `host[:port]` without a scheme, which this project never
# requests — counting it would call every machine that sets it to
# 127.0.0.1:11434 credential-bearing.
REQUEST_URL_VARS = ("OLLAMA_URL", "OPENROUTER_BASE_URL", "LANGCHAIN_ENDPOINT",
                    "LANGSMITH_ENDPOINT")


def credential_configured(*urls: str) -> bool:
    """Whether `urls`, or any URL a request of this process may go to
    (REQUEST_URL_VARS, as configured), carries one (`carries_credential`)."""
    from . import config      # here, not at the top: config is loaded lazily by its users
    every = (*urls, config.OLLAMA_URL, config.OPENROUTER_BASE_URL,
             *(os.environ.get(name, "") for name in REQUEST_URL_VARS[2:]))
    return any(carries_credential(url) for url in every if url)
