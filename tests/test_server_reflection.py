"""Text a server sends back is never printed while a credential is configured
(F4-reflected-error, F5-fragment).

A server reached through `OLLAMA_URL=http://user:password@host` receives that
credential (requests sends it as Basic auth) and can put it — or any fragment
of it — into anything it answers: an `error` field in a pull stream, an HTTP
error body, a progress stage. Removing what it sent back cannot be made
complete, so it is not tried: while any configured URL carries a credential,
the server's text is withheld and the message is our own words only. With no
credential configured, the server's text is shown through
`dataflow.server_text` (control characters stripped, whitespace folded, the
length capped).

The end-to-end half runs a real loopback server that reflects fragments of
the credential it receives — the first four characters, the last four, a
middle slice, the user name, each bare and inside a sentence — and asserts
that no slice of four characters or more of the user name or the password
appears in anything `ayl init`, `ayl init --dry-run` or `ayl doctor` prints.
"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from ask_your_library import config, dataflow, embeddings, ollama
from conftest import run_fresh

# Not words, so a slice of either cannot turn up in ordinary output by chance.
USER, PASSWORD = "uQ7zK9x2", "Zq8Lr2Vx7Wn4Tg5Jp"


def slices(secret, width=4):
    return {secret[at:at + width] for at in range(len(secret) - width + 1)}


def assert_clean(text):
    found = sorted(piece for piece in slices(USER) | slices(PASSWORD) if piece in text)
    assert not found, (found, text)


FRAGMENTS = {
    "first four": lambda user, pw: pw[:4],
    "last four": lambda user, pw: pw[-4:],
    "middle": lambda user, pw: pw[5:11],
    "user name": lambda user, pw: user,
    "in a sentence": lambda user, pw: f"pull model manifest: {pw[:4]} and {pw[-4:]} for {user}",
}


# --- the rule ---------------------------------------------------------------------

def test_with_a_credential_configured_server_text_is_withheld(monkeypatch):
    assert dataflow.server_text("disk full", f"http://{USER}:{PASSWORD}@h:1") is None
    monkeypatch.setattr(config, "OLLAMA_URL", f"http://{USER}:{PASSWORD}@h:1")
    assert dataflow.server_text("disk full") is None


def test_with_no_credential_server_text_is_shown_sanitised():
    shown = dataflow.server_text("disk\n\n full \x1b[2J‮" + "x" * 500, "http://h:1")
    assert shown.startswith("disk full [2J") and "\x1b" not in shown and "‮" not in shown
    assert len(shown) == dataflow.SERVER_TEXT_LIMIT


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


def answering(monkeypatch, response):
    monkeypatch.setattr(ollama, "requests", type("R", (), {"post": lambda *a, **k: response})())


@pytest.mark.parametrize("fragment", list(FRAGMENTS))
@pytest.mark.parametrize("shape", ["stream error line", "HTTP error body"])
def test_a_pull_error_with_a_credential_is_our_own_words(monkeypatch, shape, fragment):
    reflected = FRAGMENTS[fragment](USER, PASSWORD)
    answering(monkeypatch, Stream([{"error": reflected}]) if shape == "stream error line"
              else Stream([], status=500, text=json.dumps({"error": reflected})))
    with pytest.raises(ollama.PullError) as failed:
        ollama.pull("some-model", url=URL)
    assert_clean(str(failed.value))
    assert "withheld because the configured URL carries a credential" in str(failed.value)


def test_without_a_credential_the_server_s_reason_is_shown_sanitised(monkeypatch):
    answering(monkeypatch, Stream([], status=500, text=json.dumps({"error": "disk\x1b[2J full"})))
    with pytest.raises(ollama.PullError, match=r"HTTP 500 — it said: disk\[2J full"):
        ollama.pull("some-model", url="http://127.0.0.1:11434")


def test_a_progress_stage_with_a_credential_is_our_own_word(monkeypatch):
    seen = []
    answering(monkeypatch, Stream([{"status": f"pulling {PASSWORD[:4]}", "total": 10,
                                    "completed": 5},
                                   {"status": PASSWORD[-4:]}, {"status": "success"}]))
    ollama.pull("some-model", lambda *args: seen.append(args), url=URL)
    assert seen == [("downloading", 5, 10), ("working", None, None), ("success", None, None)]


def test_a_progress_stage_without_a_credential_is_the_server_s_sanitised(monkeypatch):
    seen = []
    answering(monkeypatch, Stream([{"status": "pulling manifest\x1b[2J"}, {"status": "success"}]))
    ollama.pull("some-model", lambda *args: seen.append(args), url="http://127.0.0.1:11434")
    assert seen[0] == ("pulling manifest[2J", None, None)


@pytest.mark.parametrize("embedder", ["ollama", "openrouter"])
def test_an_embedding_http_error_is_our_own_words(monkeypatch, embedder):
    """The demo build `ayl init` starts prints it (a traceback): status as an
    integer and the URL with its credential taken out, never the server's
    reason phrase — whether or not a credential is configured."""
    class Response:
        status_code = 502
        url = f"{URL}/api/embed"
        reason = f"Bad {PASSWORD[:4]}"

        def raise_for_status(self):
            raise requests.HTTPError(f"502 Server Error: {self.reason} for url: {self.url}")
    monkeypatch.setattr(embeddings, "requests",
                        type("R", (), {"post": lambda *a, **k: Response()})())
    target = (embeddings.OllamaEmbedder(URL) if embedder == "ollama" else
              object.__new__(embeddings.OpenRouterEmbedder))
    if embedder == "openrouter":
        target.key = "not-a-real-key"
    with pytest.raises(requests.HTTPError) as failed:
        target._embed(["text"])
    assert_clean(str(failed.value))
    assert "Bad" not in str(failed.value) and "HTTP 502" in str(failed.value)


# --- end to end: a server that reflects fragments of what it was sent ---------------------

class Reflector(BaseHTTPRequestHandler):
    mode, fragment = "stream", "first four"

    def log_message(self, *args):
        pass

    def _echo(self):
        auth = self.headers.get("Authorization", "")
        sent = base64.b64decode(auth.split(" ", 1)[1]).decode() if auth.startswith("Basic ") else ":"
        user, _, password = sent.partition(":")
        return FRAGMENTS[self.fragment](user, password)

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


@pytest.mark.parametrize("fragment", list(FRAGMENTS))
@pytest.mark.parametrize("mode", ["stream", "http", "garbage", "status", "tags", "tags-error"])
@pytest.mark.parametrize("argv", [["init", "--no-demo", "--yes"],
                                  ["init", "--dry-run", "--no-demo"],
                                  ["doctor"]])
def test_no_fragment_a_reflecting_server_sends_reaches_the_terminal(reflector, tmp_path,
                                                                  mode, argv, fragment):
    Reflector.mode, Reflector.fragment = mode, fragment
    url = f"http://{USER}:{PASSWORD}@127.0.0.1:{reflector.server_address[1]}"
    work = tmp_path / "work"
    work.mkdir()
    result = run_fresh("import sys\nfrom ask_your_library import ayl\n"
                       f"sys.exit(ayl.main({argv!r}))\n", cwd=work, check=False,
                       AYL_HOME=str(tmp_path / "home"), OLLAMA_URL=url)
    printed = result.stdout + result.stderr
    assert "Traceback" not in printed, printed
    assert_clean(printed)
