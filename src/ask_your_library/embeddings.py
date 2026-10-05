"""Embedding backends behind one interface: local Ollama or the OpenRouter API.

The same embedder serves ingest (documents) and the agent (queries) — mixing
models between the two would silently break vector search.
"""
import os
import re

import requests
# Bound here, as in preflight.py, so the except clauses survive a stubbed
# `requests`. HTTPError is a RequestException, so it is caught first.
from requests import HTTPError, RequestException

from .config import (OLLAMA_EMBED_MODEL, OLLAMA_URL, OPENROUTER_BASE_URL,
                     OPENROUTER_EMBED_MODEL, OPENROUTER_ENV_FILE)
from .dataflow import NOT_SHOWN, mark_worded_here, shown_url


def openrouter_api_key() -> str:
    """OPENROUTER_API_KEY from the environment, else from the opt-in
    OPENROUTER_ENV_FILE (never a silently-read dotfile)."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and OPENROUTER_ENV_FILE and OPENROUTER_ENV_FILE.exists():
        match = re.search(r'OPENROUTER_API_KEY=["\']?([^"\'\s]+)', OPENROUTER_ENV_FILE.read_text())
        if match:
            key = match.group(1)
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not set (export it, put it in .env, or point "
            "OPENROUTER_ENV_FILE at a file containing it)")
    return key


def _post(base: str, path: str, setting: str, **kwargs) -> requests.Response:
    """POST to `path` under the configured `base` (the value of `setting`); a
    failure is re-raised in our own words.

    `requests` words an HTTP error with the URL it sent, `user:password@`
    included, and a refused connection with the path and query, where a token
    can sit (#107). The error raised instead keeps the class (callers and tests
    match on it), names the endpoint the way `dataflow.shown_url` prints a
    setting, and carries the integer status or the class of the transport
    failure, and nothing the server or the request said: not its reason
    phrase, its body or its redirect target. Raised `from None`, so a
    traceback does not print the original either."""
    shown = shown_url(base)
    if shown == NOT_SHOWN:
        shown = f"{setting} (not shown: it carries a credential)"
    try:
        response = requests.post(f"{base}{path}", **kwargs)
        response.raise_for_status()
    except HTTPError as error:
        status = getattr(error.response, "status_code", None)
        status = f"HTTP {int(status)}" if isinstance(status, int) else "an HTTP error"
        raise _worded(error, f"the embedding endpoint at {shown} answered {status}") from None
    except RequestException as error:
        raise _worded(error, f"the request to the embedding endpoint at {shown} failed: "
                             f"{type(error).__name__}") from None
    return response


def _worded(error: RequestException, message: str) -> BaseException:
    """`message` in an exception of `error`'s own class where that class takes
    one, else a plain RequestException; marked as worded here."""
    try:
        worded = type(error)(message)
    except Exception:                    # a subclass with a constructor of its own
        worded = RequestException(message)
    return mark_worded_here(worded)


def _check_dims(vectors: list[list[float]], dims: int, model: str) -> list[list[float]]:
    """The declared dims feed the index fingerprint; a model that returns a
    different width must fail here, not as a LanceDB schema error later."""
    if vectors and len(vectors[0]) != dims:
        raise RuntimeError(f"embedding model {model!r} returned {len(vectors[0])}-dim vectors, "
                           f"expected {dims} — update the embedder's dims")
    return vectors


class OllamaEmbedder:
    """bge-m3 via local Ollama: multilingual, so non-English questions retrieve
    from an English corpus without translation."""
    name = "ollama"
    model = OLLAMA_EMBED_MODEL
    dims = 1024
    batch_size = 32

    def __init__(self, url: str = OLLAMA_URL):
        self.url = url

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = _post(self.url, "/api/embed", "OLLAMA_URL",
                         json={"model": self.model, "input": texts}, timeout=300)
        return _check_dims(response.json()["embeddings"], self.dims, self.model)

    def embed_docs(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            vectors += self._embed(texts[start:start + self.batch_size])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


class OpenRouterEmbedder:
    """OpenAI-compatible embeddings via OpenRouter (no local model needed)."""
    name = "openrouter"
    model = OPENROUTER_EMBED_MODEL
    dims = 1536
    batch_size = 64

    def __init__(self):
        self.key = openrouter_api_key()

    def _embed(self, texts: list[str]) -> list[list[float]]:
        # Same base URL as the orchestrator: pointing the app at another
        # OpenAI-compatible endpoint must redirect corpus text too.
        response = _post(
            OPENROUTER_BASE_URL.rstrip('/'), "/embeddings", "OPENROUTER_BASE_URL",
            headers={"Authorization": f"Bearer {self.key}"},
            json={"model": self.model, "input": texts}, timeout=120)
        data = sorted(response.json()["data"], key=lambda d: d["index"])
        return _check_dims([d["embedding"] for d in data], self.dims, self.model)

    def embed_docs(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            vectors += self._embed(texts[start:start + self.batch_size])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


def get_embedder(backend: str):
    if backend == "ollama":
        return OllamaEmbedder()
    if backend == "openrouter":
        return OpenRouterEmbedder()
    raise ValueError(f"unknown embedding backend: {backend!r} (expected ollama or openrouter)")
