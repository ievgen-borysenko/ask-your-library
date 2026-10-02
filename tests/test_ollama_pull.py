"""The pull helper `ayl init` uses, against a recorded `/api/pull` stream: no
network, no Ollama. And the two preflight functions it shares with the
preflight — which models a configuration needs, and what `/api/tags` said —
so `ayl init` and `ayl ask` cannot disagree about either."""
import json

import pytest
import requests

from ask_your_library import ollama, preflight

# What Ollama streams for a pull, abridged from a real `POST /api/pull`.
TRANSCRIPT = [
    {"status": "pulling manifest"},
    {"status": "pulling 0a1b2c", "digest": "sha256:0a1b2c", "total": 1000, "completed": 0},
    {"status": "pulling 0a1b2c", "digest": "sha256:0a1b2c", "total": 1000, "completed": 500},
    {"status": "pulling 0a1b2c", "digest": "sha256:0a1b2c", "total": 1000, "completed": 1000},
    {"status": "verifying sha256 digest"},
    {"status": "writing manifest"},
    {"status": "success"},
]


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


class FakeRequests:
    """`requests` as `ollama` uses it: one POST, answered from a transcript."""
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def post(self, url, json=None, stream=False, timeout=None):
        self.calls.append({"url": url, "json": json, "stream": stream, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


def test_a_pull_streams_its_progress_and_ends_on_success(monkeypatch):
    fake = FakeRequests(Stream(TRANSCRIPT))
    monkeypatch.setattr(ollama, "requests", fake)
    seen = []
    ollama.pull("some-model:7b", lambda status, done, total: seen.append((status, done, total)),
                url="http://localhost:11434/")
    assert fake.calls == [{"url": "http://localhost:11434/api/pull",
                           "json": {"model": "some-model:7b", "name": "some-model:7b",
                                    "stream": True},
                           "stream": True, "timeout": (ollama.CONNECT_TIMEOUT_S,
                                                       ollama.READ_TIMEOUT_S)}]
    assert seen[0] == ("pulling manifest", None, None)
    assert ("pulling 0a1b2c", 500, 1000) in seen
    assert seen[-1] == ("success", None, None)


def test_an_error_line_inside_a_200_stream_is_a_failure(monkeypatch):
    """How a model name Ollama does not know is reported: the stream starts
    with 200, then says `error`."""
    monkeypatch.setattr(ollama, "requests", FakeRequests(Stream(
        [{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}])))
    with pytest.raises(ollama.PullError, match="file does not exist"):
        ollama.pull("no-such-model")


def test_a_stream_that_never_says_success_is_a_failure(monkeypatch):
    monkeypatch.setattr(ollama, "requests", FakeRequests(Stream(TRANSCRIPT[:3])))
    with pytest.raises(ollama.PullError, match="without saying it succeeded"):
        ollama.pull("some-model")


def test_an_http_error_names_the_status_and_ollama_s_reason(monkeypatch):
    monkeypatch.setattr(ollama, "requests", FakeRequests(Stream(
        [], status=500, text='{"error": "disk full"}')))
    with pytest.raises(ollama.PullError, match="HTTP 500 — disk full"):
        ollama.pull("some-model")


def test_a_reply_that_is_not_ollama_s_is_a_failure_not_a_crash(monkeypatch):
    monkeypatch.setattr(ollama, "requests", FakeRequests(Stream([b"<html>"])))
    with pytest.raises(ollama.PullError, match="not a pull progress line"):
        ollama.pull("some-model")


def test_a_lost_connection_is_a_failure_with_the_endpoint_named(monkeypatch):
    monkeypatch.setattr(ollama, "requests", FakeRequests(
        error=requests.ConnectionError("refused")))
    monkeypatch.setattr(ollama, "RequestException", requests.RequestException)
    with pytest.raises(ollama.PullError, match="connection to Ollama at http://x:1 failed"):
        ollama.pull("some-model", url="http://x:1")


# --- what the preflight and init share ----------------------------------------

def test_the_models_to_pull_follow_the_pair_asked_about(monkeypatch):
    monkeypatch.setattr(preflight, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(preflight, "EMBED_BACKEND", "ollama")
    monkeypatch.setattr(preflight, "ORCHESTRATOR_MODEL", "local-answers")
    monkeypatch.setattr(preflight, "OLLAMA_LLM_MODEL", "local-answers")
    monkeypatch.setattr(preflight, "OLLAMA_EMBED_MODEL", "local-embeds")
    assert preflight.pull_models() == ["local-answers", "local-embeds"]
    assert preflight.pull_models("openrouter", "ollama") == ["local-embeds"]
    assert preflight.pull_commands() == "`ollama pull local-answers`, `ollama pull local-embeds`"


def test_a_local_mode_asked_about_from_a_hosted_process_names_the_local_model(monkeypatch):
    """`ayl init --mode local` in a process whose configuration is hosted:
    ORCHESTRATOR_MODEL is then the hosted model's name, which Ollama cannot pull."""
    monkeypatch.setattr(preflight, "LLM_BACKEND", "openrouter")
    monkeypatch.setattr(preflight, "ORCHESTRATOR_MODEL", "vendor/hosted-model")
    monkeypatch.setattr(preflight, "OLLAMA_LLM_MODEL", "local-answers")
    monkeypatch.setattr(preflight, "OLLAMA_EMBED_MODEL", "local-embeds")
    assert preflight.pull_models("ollama", "ollama") == ["local-answers", "local-embeds"]


class Tags:
    def __init__(self, reply=None, error=None):
        self.reply, self.error = reply, error

    def get(self, url, timeout=None):
        if self.error:
            raise self.error
        return self.reply


class Reply:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


@pytest.mark.parametrize("fake, kind, names", [
    (Tags(Reply({"models": [{"name": "a:latest"}, {"name": "b"}]})), None, {"a:latest", "b"}),
    (Tags(Reply({"models": None})), None, set()),
    (Tags(error=requests.ConnectionError("down")), "no_ollama", set()),
    (Tags(Reply({}, status=503)), "ollama_bad_reply", set()),
    (Tags(Reply(ValueError("not json"))), "ollama_bad_reply", set()),
])
def test_what_the_tags_reply_is_classified_as(monkeypatch, fake, kind, names):
    monkeypatch.setattr(preflight, "requests", fake)
    reply = preflight.ollama_tags()
    assert reply.kind == kind and set(reply.names) == names
