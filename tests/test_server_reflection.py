"""Text a server sends back is never printed as it came (F4-reflected-error).

A server reached through `OLLAMA_URL=http://user:password@host` receives that
credential (requests sends it as Basic auth) and can put it into anything it
answers: an `error` field in a pull stream, an HTTP error body, a progress
stage, a reason phrase. Every such string goes through one sanitiser,
`dataflow.server_text`, or is not printed at all.

The end-to-end half runs a real loopback server that decodes the Basic
credential it receives and reflects it, raw and as the Base64 it arrived in,
in each of those places, and asserts neither appears in anything `ayl init`,
`ayl init --dry-run` or `ayl doctor` prints.
"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from ask_your_library import dataflow, embeddings, ollama
from conftest import run_fresh

USER, PASSWORD = "reader", "s3cret-not-a-real-password"
B64 = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
SPELLINGS = (PASSWORD, B64, B64.rstrip("="))


def assert_clean(text):
    for secret in SPELLINGS:
        assert secret not in text, text


# --- the sanitiser ------------------------------------------------------------------

def test_server_text_removes_every_spelling_of_the_credential():
    url = "http://reader:s3cret%2Dpw@127.0.0.1:1"
    decoded = "reader:s3cret-pw"
    text = (f"raw s3cret%2Dpw decoded s3cret-pw basic {base64.b64encode(decoded.encode()).decode()}"
            f" urlsafe {base64.urlsafe_b64encode(decoded.encode()).decode().rstrip('=')}"
            "\x1b[2J‮ end")
    clean = dataflow.server_text(text, url)
    for secret in ("s3cret%2Dpw", "s3cret-pw", "reader"):
        assert secret not in clean
    assert "\x1b" not in clean and "‮" not in clean
    assert clean.endswith("end") and clean.count("<credentials>") == 4


def test_server_text_caps_the_length_and_folds_whitespace():
    assert dataflow.server_text("a\n\n  b" + "x" * 500) .startswith("a b")
    assert len(dataflow.server_text("x" * 500)) == dataflow.SERVER_TEXT_LIMIT


def test_a_credential_too_short_to_replace_withholds_the_whole_text():
    assert dataflow.server_text("my answer is ab", "http://ab:cd@h") == dataflow.WITHHELD


def test_a_configured_credential_is_scrubbed_even_when_the_url_is_not_named(monkeypatch):
    from ask_your_library import config
    monkeypatch.setattr(config, "OLLAMA_URL", f"http://{USER}:{PASSWORD}@127.0.0.1:1")
    assert_clean(dataflow.scrub_credentials(f"echo {PASSWORD} {B64}"))


# --- each place a response's text could reach a message ---------------------------------

class Stream:
    def __init__(self, lines, status=200, text=""):
        self.lines, self.status_code, self.text = lines, status, text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        for line in self.lines:
            yield line if isinstance(line, bytes) else json.dumps(line).encode()


URL = f"http://{USER}:{PASSWORD}@127.0.0.1:11434"


@pytest.mark.parametrize("response", [
    Stream([{"status": "pulling manifest"}, {"error": f"{PASSWORD} Basic {B64}"}]),
    Stream([], status=500, text=json.dumps({"error": f"{PASSWORD} Basic {B64}"})),
    Stream([f"<html>{PASSWORD} {B64}".encode()]),
], ids=["stream error line", "HTTP error body", "malformed line"])
def test_a_pull_error_never_carries_the_credential(monkeypatch, response):
    monkeypatch.setattr(ollama, "requests", type("R", (), {"post": lambda *a, **k: response})())
    with pytest.raises(ollama.PullError) as failed:
        ollama.pull("some-model", url=URL)
    assert_clean(str(failed.value))


def test_a_progress_stage_is_sanitised_before_it_is_printed(monkeypatch):
    seen = []
    monkeypatch.setattr(ollama, "requests", type("R", (), {"post": lambda *a, **k: Stream([
        {"status": f"pulling {PASSWORD} {B64}", "total": "lots", "completed": True},
        {"status": "success"}])})())
    ollama.pull("some-model", lambda *args: seen.append(args), url=URL)
    assert_clean(repr(seen))
    assert seen[0][1:] == (None, None), "a byte count that is not a number is not printed"


@pytest.mark.parametrize("embedder", ["ollama", "openrouter"])
def test_an_embedding_http_error_carries_neither_the_url_s_credential_nor_the_reason(
        monkeypatch, embedder):
    class Response:
        status_code = 502
        url = f"{URL}/api/embed"
        reason = f"Bad {PASSWORD} {B64}"

        def raise_for_status(self):
            raise requests.HTTPError(f"502 Server Error: {self.reason} for url: {self.url}")
    monkeypatch.setattr(embeddings, "requests", type("R", (), {"post": lambda *a, **k: Response()})())
    target = (embeddings.OllamaEmbedder(URL) if embedder == "ollama" else
              object.__new__(embeddings.OpenRouterEmbedder))
    if embedder == "openrouter":
        target.key = "not-a-real-key"
    with pytest.raises(requests.HTTPError) as failed:
        target._embed(["text"])
    assert_clean(str(failed.value))
    assert "Bad" not in str(failed.value) and "HTTP 502" in str(failed.value)


# --- end to end: a server that reflects what it was sent ---------------------------------

class Reflector(BaseHTTPRequestHandler):
    mode = "stream"

    def log_message(self, *args):
        pass

    def _echo(self):
        auth = self.headers.get("Authorization", "")
        sent = base64.b64decode(auth.split(" ", 1)[1]).decode() if auth.startswith("Basic ") else ""
        return f"{sent.split(':', 1)[-1]} {auth}"

    def _send(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.mode == "tags":
            return self._send(200, f"<html>{self._echo()}</html>")
        if self.mode == "tags-error":
            return self._send(500, json.dumps({"error": self._echo()}))
        self._send(200, json.dumps({"models": [{"name": "bge-m3:latest"}]}))

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        echo = self._echo()
        if self.mode == "http":
            return self._send(500, json.dumps({"error": echo}))
        if self.mode == "garbage":
            return self._send(200, f"not json {echo}\n")
        if self.mode == "status":
            return self._send(200, json.dumps({"status": echo, "total": 10, "completed": 5})
                              + "\n" + json.dumps({"status": "success"}) + "\n")
        self._send(200, json.dumps({"status": "pulling manifest"}) + "\n"
                   + json.dumps({"error": echo}) + "\n")


@pytest.fixture
def reflector():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Reflector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


@pytest.mark.parametrize("mode", ["stream", "http", "garbage", "status", "tags", "tags-error"])
@pytest.mark.parametrize("argv", [["init", "--no-demo", "--yes"],
                                  ["init", "--dry-run", "--no-demo"],
                                  ["doctor"]])
def test_nothing_a_reflecting_server_sends_reaches_the_terminal(reflector, tmp_path, mode, argv):
    Reflector.mode = mode
    url = f"http://{USER}:{PASSWORD}@127.0.0.1:{reflector.server_address[1]}"
    work = tmp_path / "work"
    work.mkdir()
    result = run_fresh("import sys\nfrom ask_your_library import ayl\n"
                       f"sys.exit(ayl.main({argv!r}))\n", cwd=work, check=False,
                       AYL_HOME=str(tmp_path / "home"), OLLAMA_URL=url)
    printed = result.stdout + result.stderr
    assert "Traceback" not in printed, printed
    assert_clean(printed)
