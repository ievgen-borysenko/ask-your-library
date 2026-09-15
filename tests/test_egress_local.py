"""Nothing leaves the machine in the fully local configuration.

The shipped default answers on a local model through Ollama and embeds through
Ollama, so a reader's question, their books and the passages retrieved from them
are supposed to stay on their laptop. Every test in this suite so far proved
that by construction — the model is faked, the library is in memory, the
credentials are blanked — and construction is exactly the wrong evidence for
this claim: a fake model makes no connection whether or not the real one would
have made a hosted one, and an import, an SDK's background thread or a tracing
client can open a socket that no assertion in this suite would see.

So these tests instrument the PROCESS instead of the application (see
tests/egress_guard.py) and then run the real thing: the real `llm` and
`embeddings` modules, the real preflight, the real compiled graph through
`runner.run_question`, with Ollama NOT running. Every outbound connection
attempt is recorded at three layers (socket, DNS, httpx) and refused unless the
target is this machine, and the assertions are about the whole recorded list:
loopback on the configured Ollama port, and nothing else — no OpenRouter, no
LangSmith, not even a name lookup for one.

SCOPE, and it is a narrow one. This is what ONE Python process did — the
interpreter that runs the CLI, the eval and the Chainlit server's Python half.
It is not a claim about the machine:

  * Ollama is a separate process. What it does with a prompt once it has it —
    a model pulled on demand, a telemetry ping, a remote inference backend
    someone configured — is outside this interpreter and outside this test.
  * Chainlit serves a browser and ships a JavaScript bundle; the browser's own
    requests, and anything the node-side tooling does, are not seen here.
  * A process started by this one (an `ollama pull`, a subprocess in a script)
    has its own sockets and is not instrumented.

The honest reading is therefore: "the application's own Python process opens no
connection to anything but the local Ollama endpoint it is configured with",
which is the part of the privacy claim this repository can actually own. The
rest is documented in docs/privacy-and-threat-model.md.

The configuration is set per test and per child process, never inherited: CI
runs this whole suite twice with LLM_BACKEND exported (`test (ollama)` and
`test (openrouter)`), and `config` resolves the backend once, at import time.
The runs that need a resolved configuration therefore go through
`conftest.run_fresh`, which scrubs every pinned name and starts a child with the
one this test names — so both CI legs run the same thing.
"""
import json
import socket

import httpx
import pytest
from conftest import run_fresh as _run

from egress_guard import EgressBlocked, closed_loopback_port, is_loopback, record_egress

# A host that cannot resolve even if the guard let it through: .invalid is
# reserved by RFC 2606 and has no DNS delegation anywhere.
OFF_MACHINE = "example.invalid"


# --------------------------------------------------------------- the guard
def test_the_guard_refuses_an_outbound_request_before_any_lookup():
    """The guard catching a deliberate attempt, which is what makes the silence
    in the tests below mean something. httpx is the layer the OpenAI SDK (and
    therefore every orchestrator call) goes through, so it is blocked there,
    with the host and port still intact and no name lookup attempted at all."""
    with record_egress() as guard:
        with pytest.raises(EgressBlocked) as blocked:
            httpx.get(f"https://{OFF_MACHINE}/v1/chat/completions", timeout=5)
    assert OFF_MACHINE in str(blocked.value)
    assert guard.off_machine() == {(OFF_MACHINE, 443)}
    # Refused at httpx and never handed to the resolver: a DNS query is itself a
    # packet leaving the machine, carrying the name of who was about to be called.
    assert guard.layers_for(OFF_MACHINE) == ["httpx"]


def test_the_guard_refuses_a_bare_socket_too():
    """Not every client is httpx: `requests` (embeddings, preflight) reaches the
    network through urllib3, which brings its own `create_connection` and calls
    `socket.getaddrinfo` itself. The floor has to hold on its own."""
    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            socket.create_connection((OFF_MACHINE, 443), timeout=5)
        with pytest.raises(EgressBlocked):
            socket.getaddrinfo(OFF_MACHINE, 443)
        with pytest.raises(EgressBlocked):
            socket.socket().connect(("93.184.216.34", 443))
    assert guard.off_machine() == {(OFF_MACHINE, 443), ("93.184.216.34", 443)}


def test_loopback_is_allowed_and_still_recorded():
    """The allow-list is an assertion only because loopback is recorded too: a
    guard that logged nothing when it let something through could not tell
    "talked to the local Ollama" from "talked to nobody at all"."""
    port = closed_loopback_port()
    with record_egress() as guard:
        with pytest.raises(OSError) as refused:       # nothing listens there
            socket.create_connection(("127.0.0.1", port), timeout=5)
    assert not isinstance(refused.value, EgressBlocked)
    assert guard.off_machine() == set()
    assert guard.targets() == {("127.0.0.1", port)}


def test_only_this_machine_counts_as_loopback():
    """The rule the whole file rests on, spelled out. A NAME that is not a known
    loopback name is off-machine without being resolved — the lookup would be
    the egress. And the check is on the whole host, not a prefix of it:
    `127.0.0.1.evil.example` is somebody else's server."""
    assert all(is_loopback(h) for h in ("127.0.0.1", "127.0.0.53", "::1", "[::1]",
                                        "localhost", "LOCALHOST", "::1%lo0"))
    assert not any(is_loopback(h) for h in ("openrouter.ai", "api.smith.langchain.com",
                                            "127.0.0.1.evil.example", "localhost.evil.example",
                                            "10.0.0.5", "0.0.0.0", ""))


# ------------------------------------------------ the local configuration
# The child that does the real work: the guard goes on, then the actual
# preflight, the actual embedder and the actual compiled graph run against an
# Ollama that is not there. Imports happen BEFORE the guard so that what is
# recorded is the application running, not the import of a dependency.
LOCAL_RUN = """
import json, os, tempfile
from pathlib import Path

from conftest import pin_environment
pin_environment()
%(extra_env)s

from ask_your_library import config, embeddings, preflight
from ask_your_library.graph import build_graph
from ask_your_library.runner import run_question
from egress_guard import record_egress

report = {"backend": config.LLM_BACKEND, "embed_backend": config.EMBED_BACKEND,
          "llm_base_url": config.LLM_BASE_URL, "ollama_url": config.OLLAMA_URL,
          "openrouter_base_url": config.OPENROUTER_BASE_URL}

with record_egress() as guard:
    result = preflight.check_environment()
    report["preflight_kinds"] = list(result.kinds)
    report["preflight_exit"] = preflight.exit_code(result)
    report["preflight_text"] = " | ".join(result)[:400]

    try:
        embeddings.get_embedder(config.EMBED_BACKEND).embed_query("who narrates Moby Dick?")
        report["embed"] = "no error"
    except BaseException as error:
        report["embed"] = type(error).__name__

    with tempfile.TemporaryDirectory() as scratch:
        try:
            answer = run_question(build_graph(), "Who narrates Moby Dick?", [], Path(scratch),
                                  on_event=lambda name, update: None,
                                  on_clarify=lambda question: "")
            report["run"] = {"raised": "", "answer": answer[:200]}
        except BaseException as error:
            report["run"] = {"raised": type(error).__name__, "message": str(error)[:300]}

report["attempts"] = [a.as_tuple() for a in guard.attempts]
report["targets"] = sorted(guard.targets(), key=repr)
report["off_machine"] = sorted(guard.off_machine(), key=repr)
print(json.dumps(report))
"""


def local_run(extra_env: str = "", **env) -> dict:
    """The child above, in a fresh interpreter with `env` pinned, as JSON."""
    result = _run(LOCAL_RUN % {"extra_env": extra_env}, **env)
    return json.loads(result.stdout)


def test_the_local_configuration_talks_only_to_loopback():
    """A full pass of the real graph in the fully local configuration, with
    Ollama not running: preflight, an embedding call and the orchestrator's own
    calls all go to loopback on the configured Ollama port, and nothing else is
    contacted — not OpenRouter, not LangSmith, and no resolver is asked about
    either of them.

    The port is a free loopback port rather than 11434 so that a developer with
    Ollama actually running does not have this test make a model call; what is
    asserted is unchanged, since the assertion is that traffic went to the
    CONFIGURED endpoint and to nothing else."""
    port = closed_loopback_port()
    report = local_run(LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
                       OLLAMA_URL=f"http://127.0.0.1:{port}")

    # The configuration the child actually resolved, so a misfired pin cannot
    # make the silence below mean nothing.
    assert report["backend"] == "ollama" and report["embed_backend"] == "ollama"
    assert report["llm_base_url"] == f"http://127.0.0.1:{port}/v1"

    # The whole allow-list, as one equality: one host, one port.
    assert report["targets"] == [["127.0.0.1", port]]
    assert report["off_machine"] == []
    # And the guard was not merely silent — it watched a real amount of traffic
    # (preflight's /api/tags, the embedder's /api/embed, the planner's call and
    # its retries), each seen at several layers. Both doors were used: the model
    # client goes out through httpx, `requests` through the socket floor, so a
    # guard watching only one of them would have had a blind side here.
    layers = {layer for layer, *_ in report["attempts"]}
    assert len(report["attempts"]) > 5
    assert "httpx" in layers and {"socket", "getaddrinfo"} <= layers

    # Named explicitly, because a missing assertion here is the whole bug class:
    # no hosted provider and no tracing endpoint was contacted OR looked up.
    contacted = {host for host, _ in report["targets"]}
    for host in ("openrouter.ai", "api.smith.langchain.com", "api.openai.com",
                 "smith.langchain.com"):
        assert host not in contacted

    # The run failed on the unreachable local runtime, and failed as a run of
    # the local configuration: preflight names Ollama and exits 5 for it, and
    # the question itself ended in a connection error to that endpoint — never
    # in a hosted call standing in for the local one.
    assert report["preflight_exit"] == 5 and "no_ollama" in report["preflight_kinds"]
    assert report["embed"] == "ConnectionError"
    # The connection to the local endpoint was refused, and the run ended on
    # that. The class name is matched by its tail: langchain wraps the SDK's
    # `APIConnectionError` in a subclass of its own (`OpenAIConnectionError`),
    # which is exactly the wrapping llm.py's `CallTimeout` comment describes.
    assert report["run"]["raised"].endswith("ConnectionError")
    assert "openrouter" not in report["run"]["message"].lower()


def test_the_shipped_defaults_point_at_this_machine():
    """The test above configures its own endpoint, so on its own it proves
    nothing about what a fresh clone does. This one reads the DEFAULTS — a child
    with every name scrubbed and an empty working directory — and asserts the
    two endpoints the local configuration uses are loopback. No connection is
    made: resolving a hostname is the claim, and `is_loopback` answers it
    without asking the network."""
    code = ("import json\n"
            "from urllib.parse import urlsplit\n"
            "from ask_your_library import config\n"
            "from egress_guard import is_loopback\n"
            "print(json.dumps({'llm': config.LLM_BASE_URL, 'ollama': config.OLLAMA_URL,\n"
            "                  'llm_loopback': is_loopback(urlsplit(config.LLM_BASE_URL).hostname),\n"
            "                  'ollama_loopback': is_loopback(urlsplit(config.OLLAMA_URL).hostname),\n"
            "                  'needs_key': config.OPENROUTER_NEEDS_KEY}))")
    report = json.loads(_run(code).stdout)
    assert report["llm_loopback"] and report["ollama_loopback"]
    assert report["llm"] == "http://localhost:11434/v1" and report["ollama"] == "http://localhost:11434"
    assert report["needs_key"] is False


# -------------------------------------------------- the hosted configuration
def test_the_hosted_backend_would_leave_the_machine_and_the_guard_sees_it():
    """The control for everything above: the same guard, the same graph, the one
    knob moved. LLM_BACKEND=openrouter with a key present aims the very first
    orchestrator call at openrouter.ai — the guard records that attempt and
    refuses it, so the assertion is about what WOULD have left and nothing
    actually does. Without this, "no off-machine attempt was recorded" would be
    consistent with a guard that cannot see one.

    The key is a placeholder that is not a key; the request never reaches a
    transport, so nothing is ever sent anywhere with it."""
    report = local_run(extra_env='os.environ["OPENROUTER_API_KEY"] = "not-a-key"',
                       LLM_BACKEND="openrouter", EMBED_BACKEND="openrouter")

    assert report["backend"] == "openrouter"
    assert report["llm_base_url"] == "https://openrouter.ai/api/v1"
    # What would have left: the hosted endpoint, at 443, and refused.
    assert ["openrouter.ai", 443] in report["off_machine"]
    assert report["targets"] == [["openrouter.ai", 443]]
    # Refused at httpx for the orchestrator call and at the DNS/socket floor for
    # the `requests`-based embedder: both doors, one guard. Both matter — the
    # OpenAI SDK's client is not built on the httpx the application imports, so
    # for a while the floor was the only layer that saw a model call at all.
    layers = {layer for layer, host, _, _ in report["attempts"] if host == "openrouter.ai"}
    assert "httpx" in layers and layers & {"getaddrinfo", "create_connection", "socket"}
    # Nothing was sent: every attempt for that host was refused.
    assert all(not allowed for _, host, _, allowed in report["attempts"]
               if host == "openrouter.ai")


def test_the_hosted_backend_without_a_key_opens_no_connection_at_all():
    """The configuration CI's second leg exports, run as the suite runs it: no
    key (conftest blanks it), so the client refuses before it is built. Nothing
    is attempted — not even a lookup — which is why the openrouter leg of CI
    sees the same silence the ollama leg does."""
    report = local_run(LLM_BACKEND="openrouter", EMBED_BACKEND="openrouter")
    assert report["preflight_exit"] == 4 and "no_key" in report["preflight_kinds"]
    assert report["attempts"] == []
    assert report["run"]["raised"] == "RuntimeError"
    assert "OPENROUTER_API_KEY" in report["run"]["message"]
