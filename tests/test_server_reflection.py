"""Nothing a server sends back is printed (F4-reflected-error, F5-fragment,
F9-server-text-never).

A server can put anything into what it answers — an error, an error body, a
progress stage — including what it was sent: a credential in the URL's
userinfo (requests sends it as Basic auth), a token in its path or query.
Deciding which URLs make that dangerous failed three times, so the rule is
unconditional: `ollama.pull` and everything `ayl init` or the preflight shows
from a reply is our own words plus integers we parsed (an HTTP status, byte
counts), credential or no credential.

The end-to-end half runs a loopback server that puts a MARKER at both ends
of every reply, and between them reflects what it was sent (the userinfo,
the path, the query — whole and in fragments) or arbitrary text (control
characters, 10 kB). `ayl init`, its dry run and `ayl doctor` are run against
it with and without a credential-shaped URL: neither the marker nor any
four-character slice of what was planted appears in what they print.

Planted values are low-entropy placeholders, so no secret scanner mistakes a
test for a leak.
"""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ask_your_library import ollama
from conftest import run_fresh

MARKER = "qzqzmarkerqzqz"
USER, PASSWORD = "xvxvuser", "zqzqxvxvzqzq"
PATH_TOKEN, QUERY_TOKEN = "vxvxpathvxvx", "zqzqxvxvqueryzq"
PLANTED = (USER, PASSWORD, PATH_TOKEN, QUERY_TOKEN)


def slices(secret, width=4):
    return {secret[at:at + width] for at in range(len(secret) - width + 1)}


def assert_clean(text):
    assert MARKER not in text, text
    found = sorted({piece for secret in PLANTED for piece in slices(secret)
                    if piece in text} - {"user", "path", "quer", "uery"})
    assert not found, (found, text)


# --- the pull, unit by unit ------------------------------------------------------------

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


def answering(monkeypatch, response):
    monkeypatch.setattr(ollama, "requests", type("R", (), {"post": lambda *a, **k: response})())


URLS = [f"http://{USER}:{PASSWORD}@127.0.0.1:11434", f"http://127.0.0.1:11434/{PATH_TOKEN}",
        f"http://127.0.0.1:11434/?key={QUERY_TOKEN}", "http://127.0.0.1:11434"]
SENT = f"{MARKER} {PASSWORD} {PASSWORD[:4]} {PATH_TOKEN[-4:]} {QUERY_TOKEN[3:9]} {MARKER}"


@pytest.mark.parametrize("url", URLS)
@pytest.mark.parametrize("shape", ["stream error line", "HTTP error body"])
def test_a_pull_error_is_our_own_words_with_or_without_a_credential(monkeypatch, shape, url):
    answering(monkeypatch, Stream([{"error": SENT}]) if shape == "stream error line"
              else Stream([], status=500, text=json.dumps({"error": SENT})))
    with pytest.raises(ollama.PullError) as failed:
        ollama.pull("some-model", url=url)
    assert_clean(str(failed.value))
    assert "its own text is not printed: see Ollama's own log" in str(failed.value)


@pytest.mark.parametrize("url", URLS)
def test_a_progress_stage_is_our_own_word_with_or_without_a_credential(monkeypatch, url):
    seen = []
    answering(monkeypatch, Stream([{"status": SENT, "total": 10, "completed": 5},
                                   {"status": SENT + "\x1b[2J"}, {"status": "success"}]))
    ollama.pull("some-model", lambda *args: seen.append(args), url=url)
    assert seen == [("downloading", 5, 10), ("working", None, None), ("success", None, None)]


# --- end to end: a server that reflects what it was sent, or anything at all ----------------

class Reflector(BaseHTTPRequestHandler):
    mode, payload = "stream", "reflect"

    def log_message(self, *args):
        pass

    def _said(self):
        if self.payload == "control":
            body = "\x1b[2J\x1b]0;title\x07‮\x00 arbitrary text"
        elif self.payload == "long":
            body = "x" * 10_000
        else:
            auth = self.headers.get("Authorization", "")
            sent = (base64.b64decode(auth.split(" ", 1)[1]).decode()
                    if auth.startswith("Basic ") else "")
            echo = f"{sent} {self.path}"
            body = " ".join([echo] + [piece for word in echo.replace("/", " ").replace(
                "?", " ").replace("=", " ").replace(":", " ").split()
                                      for piece in (word[:4], word[-4:], word[2:8])])
        return f"{MARKER} {body} {MARKER}"

    def _send(self, code, body):
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.mode == "tags":
            return self._send(200, f"<html>{self._said()}</html>")
        if self.mode == "tags-error":
            return self._send(500, json.dumps({"error": self._said()}))
        self._send(200, json.dumps({"models": [{"name": "bge-m3:latest"}]}))

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        said = self._said()
        if self.mode == "http":
            return self._send(500, json.dumps({"error": said}))
        if self.mode == "garbage":
            return self._send(200, f"not json {said}\n")
        if self.mode == "status":
            return self._send(200, json.dumps({"status": said, "total": 10, "completed": 5})
                              + "\n" + json.dumps({"status": "success"}) + "\n")
        self._send(200, json.dumps({"status": "pulling manifest"}) + "\n"
                   + json.dumps({"error": said}) + "\n")


@pytest.fixture
def reflector():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Reflector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


def _url(kind, port):
    return {"userinfo": f"http://{USER}:{PASSWORD}@127.0.0.1:{port}",
            "path": f"http://127.0.0.1:{port}/{PATH_TOKEN}",
            "query": f"http://127.0.0.1:{port}/?key={QUERY_TOKEN}",
            "plain": f"http://127.0.0.1:{port}"}[kind]


def _run(argv, url, tmp_path):
    work = tmp_path / "work"
    work.mkdir(exist_ok=True)
    result = run_fresh("import sys\nfrom ask_your_library import ayl\n"
                       f"sys.exit(ayl.main({argv!r}))\n", cwd=work, check=False,
                       AYL_HOME=str(tmp_path / "home"), OLLAMA_URL=url)
    printed = result.stdout + result.stderr
    assert "Traceback" not in printed, printed
    assert_clean(printed)
    return printed


@pytest.mark.parametrize("url", ["userinfo", "path", "query", "plain"])
@pytest.mark.parametrize("payload", ["reflect", "control", "long"])
@pytest.mark.parametrize("mode", ["stream", "http", "garbage", "status", "tags", "tags-error"])
def test_nothing_the_server_sent_reaches_ayl_init(reflector, tmp_path, mode, payload, url):
    Reflector.mode, Reflector.payload = mode, payload
    _run(["init", "--no-demo", "--yes"], _url(url, reflector.server_address[1]), tmp_path)


@pytest.mark.parametrize("url", ["userinfo", "path", "query", "plain"])
@pytest.mark.parametrize("payload", ["reflect", "control", "long"])
@pytest.mark.parametrize("mode", ["tags", "tags-error"])
def test_nothing_the_server_sent_reaches_ayl_doctor(reflector, tmp_path, mode, payload, url):
    """The doctor asks only /api/tags."""
    Reflector.mode, Reflector.payload = mode, payload
    _run(["doctor"], _url(url, reflector.server_address[1]), tmp_path)


@pytest.mark.parametrize("url", ["userinfo", "path", "query", "plain"])
def test_the_dry_run_sends_nothing_and_prints_nothing_of_the_url(reflector, tmp_path, url):
    Reflector.mode, Reflector.payload = "stream", "reflect"
    _run(["init", "--dry-run", "--no-demo"], _url(url, reflector.server_address[1]), tmp_path)
