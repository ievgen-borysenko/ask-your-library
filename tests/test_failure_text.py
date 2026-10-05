"""A credential in an endpoint's URL never reaches a failure line (#107).

`requests` words an HTTP error with the URL it sent, `user:password@` included,
and a refused connection with the path, where a token can sit. That text used
to become the line `ayl ask` prints, the web chat's message and its stored
history, the books ledger's `error` and the eval reports. These tests plant a
credential and look for it in every one of those strings. No model, no Ollama,
no network: the HTTP error is a `Response` built the way `requests`' adapter
builds one, and the refused connection is a real connect to a loopback port
nothing answers on.
"""
import importlib.util
import sys
from pathlib import Path

import lancedb
import pytest
import requests

from ask_your_library import config, dataflow, embeddings
from ask_your_library.dataflow import (MAX_FAILURE_CHARS, PATH_NOT_SHOWN, WITHHELD, failure_text,
                                       redact_urls)
from ask_your_library.ingest import add_folder
from ask_your_library.ingest.ledger import open_ledger
from ask_your_library.runner import _failure, failed_result
from egress_guard import reserved_loopback_port
from test_add_folder import PARA, write

REPO = Path(__file__).resolve().parents[1]
SECRET = "s3cretPW"
TOKEN = "tok-example-token"


@pytest.fixture
def no_credential_configured(monkeypatch):
    monkeypatch.setattr(config, "OLLAMA_URL", "http://localhost:11434")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    for name in dataflow.REQUEST_URL_VARS[2:]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def credential_configured(monkeypatch, no_credential_configured):
    monkeypatch.setattr(config, "OLLAMA_URL", f"http://user:{SECRET}@127.0.0.1:9")


def answering(status: int):
    """`requests.post` replaced by one that returns what the adapter returns
    for `status` (`response.url = request.url`, requests/adapters.py), so
    `raise_for_status` words the error from the real URL. No socket opens."""
    def post(url, **kwargs):
        response = requests.Response()
        response.status_code = status
        response.reason = "Internal Server Error"
        response.url = url
        response._content = b'{"error": "out of memory"}'
        return response
    return post


def raised(call) -> BaseException:
    with pytest.raises(Exception) as caught:
        call()
    return caught.value


# --- the embedders word their own failures ----------------------------------

def test_an_http_500_from_a_url_with_userinfo_names_the_status_not_the_secret(
        monkeypatch, credential_configured):
    monkeypatch.setattr(embeddings.requests, "post", answering(500))
    error = raised(lambda: embeddings.OllamaEmbedder(
        f"http://user:{SECRET}@127.0.0.1:9")._embed(["x"]))

    # the class is kept: callers and the egress tests match on it
    assert isinstance(error, requests.HTTPError)
    failure = _failure(error)
    assert SECRET not in str(failure) and "user:" not in str(failure)
    assert failure.type == "HTTPError"
    assert "HTTP 500" in failure.message and "OLLAMA_URL" in failure.message
    # and nothing of the original rides along for a traceback to print
    assert error.__cause__ is None and error.__suppress_context__


def test_an_http_error_from_a_plain_url_names_host_port_and_status(monkeypatch,
                                                                   no_credential_configured):
    monkeypatch.setattr(embeddings.requests, "post", answering(503))
    error = raised(lambda: embeddings.OllamaEmbedder("http://127.0.0.1:9")._embed(["x"]))
    assert failure_text(error) == "the embedding endpoint at http://127.0.0.1:9 answered HTTP 503"


def test_a_refused_connection_with_a_token_in_the_path_does_not_print_the_token(
        no_credential_configured):
    """The case a substring replacement of the configured value cannot close:
    urllib3 names only the path (`with url: /<token>/api/embed`), so the full
    value never appears. Caught at the source instead."""
    with reserved_loopback_port() as port:
        error = raised(lambda: embeddings.OllamaEmbedder(
            f"http://127.0.0.1:{port}/{TOKEN}")._embed(["x"]))
    assert isinstance(error, requests.ConnectionError)
    failure = _failure(error)
    assert TOKEN not in str(failure)
    assert failure.type == "ConnectionError"
    assert failure.message == (f"the request to the embedding endpoint at "
                               f"http://127.0.0.1:{port}{PATH_NOT_SHOWN} failed: ConnectionError")


def test_the_openrouter_embedder_words_its_failures_the_same_way(monkeypatch,
                                                                 no_credential_configured):
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-key")
    monkeypatch.setattr(embeddings, "OPENROUTER_BASE_URL", f"https://proxy.example/{TOKEN}/v1")
    monkeypatch.setattr(embeddings.requests, "post", answering(500))
    error = raised(lambda: embeddings.OpenRouterEmbedder()._embed(["x"]))
    text = str(_failure(error))
    assert TOKEN not in text and "not-a-key" not in text
    assert "https://proxy.example (path not shown) answered HTTP 500" in text


# --- the one helper, on text nobody worded ------------------------------------

def test_a_raw_http_error_keeps_status_and_host_and_loses_the_userinfo(no_credential_configured):
    error = requests.HTTPError("500 Server Error: Internal Server Error for url: "
                               f"http://user:{SECRET}@ollama.example:11434/api/embed")
    text = failure_text(error)
    assert SECRET not in text and "user" not in text
    assert text.startswith("500 Server Error: Internal Server Error for url: ")


def test_a_raw_connection_error_loses_the_path_it_names(no_credential_configured):
    error = requests.ConnectionError(
        "HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded with url: "
        f"/{TOKEN}/api/embed?key={TOKEN} (Caused by NewConnectionError('refused'))")
    text = failure_text(error)
    assert TOKEN not in text
    assert "host='127.0.0.1', port=9" in text and "<path not shown>" in text


@pytest.mark.parametrize("url, shown", [
    (f"https://h.example:8443/{TOKEN}?k={TOKEN}#{TOKEN}", "https://h.example:8443" + PATH_NOT_SHOWN),
    (f"http://u:{SECRET}@h.example/x", dataflow.URL_NOT_SHOWN),
    (f"http://h.example/a@{SECRET}", dataflow.URL_NOT_SHOWN),
    ("http://h.example:11434", "http://h.example:11434"),
])
def test_every_url_in_a_text_is_rebuilt_from_scheme_host_and_port(url, shown):
    assert redact_urls(f"failed for url: {url} today") == f"failed for url: {shown} today"


def test_a_plain_error_is_unchanged(no_credential_configured):
    message = "table transcripts_ollama has 1024-dim vectors, the embedder produces 1536"
    assert failure_text(RuntimeError(message)) == message
    assert _failure(RuntimeError(message)).message == message


def test_a_providers_text_is_withheld_while_a_configured_url_carries_a_credential(
        credential_configured):
    """A server can echo a fragment of the credential in a form no URL pattern
    recognises; while one is configured, the text of an HTTP library's or a
    model SDK's error is not shown at all (the rule #104 set for `ayl init`)."""
    echo = requests.HTTPError(f"401 Client Error: bad password {SECRET[:5]}")
    assert failure_text(echo) == WITHHELD
    assert _failure(echo).type == "HTTPError"
    # an error raised FROM one is withheld too, unless this project worded it
    try:
        try:
            raise echo
        except requests.HTTPError as inner:
            raise RuntimeError(f"wrapped: {inner}") from inner
    except RuntimeError as wrapped:
        assert failure_text(wrapped) == WITHHELD
    # errors that are not a provider's keep their text
    assert failure_text(KeyError("transcripts_ollama")) == "'transcripts_ollama'"


def test_the_same_provider_text_is_shown_redacted_when_no_credential_is_configured(
        no_credential_configured):
    echo = requests.HTTPError("401 Client Error: Unauthorized for url: http://h.example/v1/x")
    assert failure_text(echo) == ("401 Client Error: Unauthorized for url: "
                                  f"http://h.example{PATH_NOT_SHOWN}")


def test_control_characters_and_length_are_bounded(no_credential_configured):
    text = failure_text(RuntimeError("bad\x1b[2Jreply\r\nsecond line" + "x" * 2000))
    assert "\x1b" not in text and "\r" not in text and "\n" not in text
    assert text.startswith("bad[2Jreply second line")
    assert len(text) == MAX_FAILURE_CHARS and text.endswith("…")


# --- every place the text goes ------------------------------------------------

def test_the_web_chat_and_cli_record_carries_no_credential(monkeypatch, credential_configured):
    """`failed_result` is what the web chat and the CLI build when a run raises
    around the graph; its message is what the chat shows and stores."""
    monkeypatch.setattr(embeddings.requests, "post", answering(500))
    error = raised(lambda: embeddings.OllamaEmbedder(config.OLLAMA_URL).embed_query("q"))
    result = failed_result("q", error)
    assert SECRET not in str(result.failure)
    assert SECRET not in f"{result.failure.type}: {result.failure.message[:200]}"


def test_the_books_ledger_stores_no_credential(tmp_path, monkeypatch, credential_configured):
    """The ledger row of a book whose embedding failed records the reason; the
    ledger is part of the index and of every backup of it."""
    class Leaky:
        name, model, dims = "ollama", "fake-embed", 4

        def embed_docs(self, texts):
            raise requests.HTTPError("500 Server Error: x for url: "
                                     f"http://user:{SECRET}@127.0.0.1:9/api/embed")

    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: Leaky())
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", PARA * 4)
    with pytest.raises(requests.HTTPError):
        add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db", folder)
    rows = open_ledger(lancedb.connect(tmp_path / "db")).all_rows()
    assert rows and all(SECRET not in (row.get("error") or "") for row in rows)
    assert any((row.get("error") or "").startswith("HTTPError: ") for row in rows)


def load_summarize_report():
    spec = importlib.util.spec_from_file_location("summarize_report",
                                                  REPO / "eval" / "summarize_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_an_eval_summary_of_an_old_report_does_not_copy_a_credential(tmp_path, capsys,
                                                                     monkeypatch):
    """A report written before the fix carries the provider's text as it was;
    the committed summary is redacted again on its way out."""
    report = tmp_path / "answers-1.md"
    report.write_text(
        "# Agent eval — x\n\nrun: code abc\n\n"
        "## q02-b — ERROR\nHTTPError: 500 Server Error: Internal Server Error for url: "
        f"http://user:{SECRET}@127.0.0.1:9/api/embed\n\n"
        "---\n0 completed, 1 errors\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["summarize_report.py", str(report)])
    load_summarize_report().main()
    out = capsys.readouterr().out
    assert SECRET not in out
    assert "`q02-b`: ERROR, not completed: HTTPError: 500 Server Error" in out
