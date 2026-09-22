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
attempt is recorded — at CPython's own socket audit events, which the C layer
raises for every socket whatever its class or import path, plus an httpx
transport layer above them — and refused unless the target is this machine. The
assertions are about the whole recorded list: loopback on the configured Ollama
port, and nothing else — no OpenRouter, no LangSmith, not even a name lookup
for one.

WHAT IS SEEN. Every network call made through Python's socket module: that is
the standard library, `requests`, urllib3, httpx, httpcore, asyncio and the
model client's SDK — every client this project has. What is NOT seen is a call
that reaches libc without passing through CPython: a native extension with its
own C sockets, or a `ctypes` call straight into `getaddrinfo` or `connect`. The
audit events come from CPython's socket module, so code that skips it skips
them. `test_a_ctypes_call_into_libc_is_the_known_blind_spot` pins that as an
xfail rather than leaving it as a sentence, and two tests close the practical
half — a blind spot nothing installed can reach is a different thing from an
open door. They ask two questions that do not have the same answer everywhere:
`test_no_native_networking_in_the_interpreter` is about the process running this
file, and `test_no_native_networking_in_the_locked_runtime` about the
application's own locked closure, read from the lockfile.

SCOPE, and it is a narrow one. This is what ONE Python process did, on ONE path
through the package: `runner.run_question` over the compiled graph, with the
real `preflight` and the real `embeddings` beside it. That path is the one the
CLI and the eval harness run and the one the web UI's Python half calls into.
It is not a claim about the machine, and not even a claim about every way this
repository can be started:

  * **Chainlit is not exercised here.** The `ui` extra is not installed in the
    legs that run this file, so the web chat is not imported and its server, its
    SQLite persistence and its own HTTP stack are outside these assertions. And
    it is not only that they are untested: that extra's dependency tree brings
    `grpcio` and `opentelemetry-exporter-otlp-proto-grpc`, which do their own
    networking in C, so a Chainlit process is exactly the process this guard
    could not speak for. That is also why the two tests above are two:
    an interpreter WITH the extra — a developer's own, or the `ui-smoke` job's —
    was never inside this claim, so `..._in_the_interpreter` skips itself there
    and says so, while `..._in_the_locked_runtime` runs everywhere and must
    pass. The first still fails where such a package arrives for any other
    reason, which is the separation it exists to keep honest.
  * **Ollama is a separate process.** What it does with a prompt once it has
    it — a model pulled on demand, a telemetry ping, a remote inference backend
    someone configured — is outside this interpreter and outside this test.
  * **The browser is not in it.** Chainlit ships a JavaScript bundle; what a
    page fetches is not a socket of this process.
  * **A subprocess is not in it.** An audit hook is per interpreter: an
    `ollama pull`, an installer script, anything this process spawns has its own
    sockets and is not instrumented.
  * **`scripts/` is not in it.** `ingest_demo_corpus.py` downloads a corpus on
    purpose; it is a different path with a different claim.

The honest reading is therefore: "on the package's own runner path, the
application's Python process opens no connection to anything but the local
Ollama endpoint it is configured with". The rest is documented in
docs/privacy-and-threat-model.md.

The configuration is set per test and per child process, never inherited: CI
runs this whole suite twice with LLM_BACKEND exported (`test (ollama)` and
`test (openrouter)`), and `config` resolves the backend once, at import time.
The runs that need a resolved configuration therefore go through
`conftest.run_fresh`, which scrubs every pinned name and starts a child with the
one this test names — so both CI legs run the same thing.
"""
import asyncio
import ctypes
import ctypes.util
import importlib.util
import json
import socket
import ssl
import subprocess
import tempfile
import _socket
from pathlib import Path

import httpx
import pytest
from conftest import run_fresh as _run

from egress_guard import (EgressBlocked, EgressGuard, is_loopback, record_egress,
                          reserved_loopback_port)

# Captured BY VALUE, at the import of this module and before any guard is armed.
# A module that did this could not be reached by a monkeypatch on `socket`; the
# audit hook underneath still sees the call.
from socket import getaddrinfo as getaddrinfo_by_value       # noqa: E402

# A host that cannot resolve even if the guard let it through: .invalid is
# reserved by RFC 2606 and has no DNS delegation anywhere.
OFF_MACHINE = "example.invalid"
# A literal off this machine, for the cases that must not involve a name at all
# (a UDP datagram, a raw connect): documentation address space, RFC 5737.
OFF_MACHINE_IP = "203.0.113.7"


# --------------------------------------------------------------- the guard
def test_the_guard_refuses_an_outbound_request_before_any_lookup():
    """The guard catching a deliberate attempt, which is what makes the silence
    in the tests below mean something. httpx is the layer a model client goes
    through, so it is blocked there, with the host and port still intact and no
    name lookup attempted at all."""
    with record_egress() as guard:
        with pytest.raises(EgressBlocked) as blocked:
            httpx.get(f"https://{OFF_MACHINE}/v1/chat/completions", timeout=5)
    assert OFF_MACHINE in str(blocked.value)
    assert guard.off_machine() == {(OFF_MACHINE, 443)}
    # Refused at httpx and never handed to the resolver: a DNS query is itself a
    # packet leaving the machine, carrying the name of who was about to be called.
    assert guard.layers_for(OFF_MACHINE) == ["httpx"]


def test_both_httpx_distributions_are_watched():
    """There are two of them installed, and the model client's SDK uses the one
    the application does not import. A guard that knew only the first name would
    have watched the wrong door for every model call in this project."""
    httpx2 = pytest.importorskip("httpx2")
    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            httpx2.get(f"https://{OFF_MACHINE}/v1/models", timeout=5)
    assert guard.layers_for(OFF_MACHINE) == ["httpx"]
    assert guard.off_machine() == {(OFF_MACHINE, 443)}


# The floor is an audit hook rather than a set of monkeypatches because a socket
# can be opened without touching the names a patch can reach. Each control below
# is one of those ways.
def test_the_floor_sees_a_socket_that_never_touches_the_python_class():
    """`_socket.socket` is the C type `socket.socket` inherits from. An instance
    of it has its own `connect`, so a patch on the Python subclass never runs."""
    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            _socket.socket().connect((OFF_MACHINE_IP, 443))
    assert guard.off_machine() == {(OFF_MACHINE_IP, 443)}
    assert guard.layers_for(OFF_MACHINE_IP) == ["socket.connect"]


def test_the_floor_sees_a_resolver_captured_before_the_guard():
    """`from socket import getaddrinfo` binds the function BY VALUE. A module
    that did that before the guard went on would keep calling the real one past
    any patch on the `socket` module."""
    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            getaddrinfo_by_value(OFF_MACHINE, 443)
    assert guard.off_machine() == {(OFF_MACHINE, 443)}
    assert guard.layers_for(OFF_MACHINE) == ["socket.getaddrinfo"]


def test_the_floor_sees_udp_which_never_connects_at_all():
    """UDP needs no `connect`: `sendto` and `sendmsg` carry the address, and a
    resolver query or a telemetry ping is exactly that shape."""
    with record_egress() as guard:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as datagram:
            with pytest.raises(EgressBlocked):
                datagram.sendto(b"ping", (OFF_MACHINE_IP, 53))
            with pytest.raises(EgressBlocked):
                datagram.sendmsg([b"ping"], [], 0, (OFF_MACHINE_IP, 53))
    assert guard.off_machine() == {(OFF_MACHINE_IP, 53)}
    assert guard.layers_for(OFF_MACHINE_IP) == ["socket.sendto", "socket.sendmsg"]


def test_the_floor_sees_a_tls_socket():
    """TLS is a wrapper around the same socket, so the connect underneath it is
    the same audited event — and it is refused before any handshake."""
    context = ssl.create_default_context()
    # No handshake ever happens here, but a context that would accept TLS 1.0 is
    # a finding wherever it is written, and a test file is not an exemption.
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            with context.wrap_socket(socket.socket(),
                                     server_hostname=OFF_MACHINE) as secure:
                secure.connect((OFF_MACHINE_IP, 443))
    assert guard.off_machine() == {(OFF_MACHINE_IP, 443)}


def test_the_floor_sees_an_asyncio_connection():
    """asyncio resolves in a worker thread and connects from the loop. The hook
    is process-wide, so the thread is covered and the failure comes back through
    the awaited call."""
    async def connect():
        await asyncio.open_connection(OFF_MACHINE, 443)

    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            asyncio.run(connect())
    assert guard.off_machine() == {(OFF_MACHINE, 443)}


@pytest.mark.skipif(importlib.util.find_spec("aiohttp") is None,
                    reason="aiohttp is not installed in this environment")
def test_the_floor_sees_aiohttp():
    """Not a dependency here; covered anyway, because the guard's claim is about
    the process and not about the clients this project happens to use."""
    import aiohttp

    async def fetch():
        async with aiohttp.ClientSession() as session:
            await session.get(f"https://{OFF_MACHINE}/")

    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            asyncio.run(fetch())
    assert guard.off_machine() == {(OFF_MACHINE, 443)}


# `getaddrinfo` is the resolver door httpx and urllib3 use, and it is not the
# only one. Each of these is a separate call into the same resolver, and one of
# them is on a path this project loads: langsmith's `_is_localhost()` calls
# `gethostbyname` on the endpoint host. A guard that watched `getaddrinfo` alone
# would have let that lookup — the name of a tracing endpoint, put on the
# wire — out unseen, while the file claimed no name leaves.
# `gethostbyname_ex` raises the `socket.gethostbyname` event, not one of its
# own, which is why it shares a layer name here.
NAME_LOOKUPS = [
    ("socket.getaddrinfo", 443, lambda host: socket.getaddrinfo(host, 443)),
    ("socket.gethostbyname", None, lambda host: socket.gethostbyname(host)),
    ("socket.gethostbyname", None, lambda host: socket.gethostbyname_ex(host)),
    ("socket.gethostbyaddr", None, lambda host: socket.gethostbyaddr(host)),
]
LOOKUP_IDS = ["getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr"]


@pytest.mark.parametrize("layer,port,lookup", NAME_LOOKUPS, ids=LOOKUP_IDS)
def test_every_resolver_door_is_watched(layer, port, lookup):
    """Each one refuses an off-machine name and records which door was used."""
    host = OFF_MACHINE_IP if layer == "socket.gethostbyaddr" else OFF_MACHINE
    with record_egress() as guard:
        with pytest.raises(EgressBlocked):
            lookup(host)
    assert guard.layers_for(host) == [layer]
    assert guard.off_machine() == {(host, port)}


@pytest.mark.parametrize("layer,port,lookup", NAME_LOOKUPS, ids=LOOKUP_IDS)
def test_every_resolver_door_still_answers_for_this_machine(layer, port, lookup):
    """And each one still works for loopback, recorded rather than refused —
    `gethostbyaddr` needs an address, so it gets one."""
    host = "127.0.0.1" if layer == "socket.gethostbyaddr" else "localhost"
    with record_egress() as guard:
        assert lookup(host)
    assert guard.layers_for(host) == [layer] and guard.off_machine() == set()


def test_the_reverse_lookup_is_watched_too():
    """`getnameinfo` is the fifth resolver door: an address off this machine is
    a question about somebody else's host, asked of a resolver over the wire."""
    with record_egress() as guard:
        assert socket.getnameinfo(("127.0.0.1", 11434), 0)
        with pytest.raises(EgressBlocked):
            socket.getnameinfo((OFF_MACHINE_IP, 443), 0)
    assert guard.off_machine() == {(OFF_MACHINE_IP, 443)}
    assert guard.layers_for("127.0.0.1") == ["socket.getnameinfo"]


def test_a_bind_is_recorded_and_kept_out_of_the_targets():
    """A bind is the other direction. It is recorded — so a test can say this
    process opened no listening socket on a public interface — and it is kept
    out of `targets()`, which answers "who was talked to"."""
    with record_egress() as guard:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            bound_port = listener.getsockname()[1]
    assert bound_port                                   # the bind really happened
    assert guard.off_machine() == set()
    assert guard.binds() == {("127.0.0.1", 0)} and guard.targets() == set()


def test_a_bind_off_this_machine_is_recorded_and_still_not_refused():
    """The policy half, exercised on the guard directly rather than by opening a
    socket on every interface: refusing a bind would break a library that opens
    a local socket for its own reasons, so a wildcard bind is recorded and
    allowed — and it is visible afterwards, which is what a test needs to say it
    did not happen during a real run."""
    guard = EgressGuard()
    guard.check("socket.bind", "0.0.0.0", 8000)          # does not raise
    assert guard.off_machine() == set()
    assert guard.binds() == {("0.0.0.0", 8000)} and guard.targets() == set()
    # And the same address through any other door is refused, so "never refused"
    # is a property of the bind event and not of the address.
    with pytest.raises(EgressBlocked):
        guard.check("socket.connect", "0.0.0.0", 8000)


def test_loopback_is_allowed_and_still_recorded():
    """The allow-list is an assertion only because loopback is recorded too: a
    guard that logged nothing when it let something through could not tell
    "talked to the local Ollama" from "talked to nobody at all"."""
    with reserved_loopback_port() as port:
        with record_egress() as guard:
            # Refused, not timed out: the reserved port is held on UDP and free
            # on TCP exactly so that "nothing is there" is immediate.
            with pytest.raises(ConnectionRefusedError) as refused:
                socket.create_connection(("127.0.0.1", port), timeout=5)
    assert not isinstance(refused.value, EgressBlocked)
    assert guard.off_machine() == set()
    assert guard.targets() == {("127.0.0.1", port)}


# ------------------------------------------------------------ the blind spot
# The known native-networking packages: each one opens sockets from C, or moves
# asyncio's sockets into C, and would therefore be outside every assertion in
# this file. `uvloop` is the sharpest of them — it replaces asyncio's event loop
# wholesale, so every asyncio socket in the process would stop passing through
# CPython's socket module. `httptools` is deliberately NOT here: it is a parser,
# it owns no socket. Names are matched against distribution names, lowercased,
# with `-`/`_`/`.` normalised, so `grpcio-status` and `psycopg-binary` count too.
NATIVE_NETWORKING = ("grpcio", "pycurl", "pycares", "aiodns", "uvloop", "pyzmq",
                     "zmq", "psycopg", "psycopg2", "pymongo", "redis", "hiredis")


def _normalised_distributions() -> set[str]:
    from importlib.metadata import distributions

    return {(dist.metadata["Name"] or "").lower().replace("_", "-").replace(".", "-")
            for dist in distributions()}


def _native_hits(names) -> set[str]:
    return {name for name in names
            if any(name == bad or name.startswith(bad + "-") for bad in NATIVE_NETWORKING)}


# Distributions that only ever arrive with the `ui` extra, and are therefore how
# this interpreter says "I am a UI environment, not the application's own". The
# extra's tree carries `grpcio` (through literalai -> traceloop-sdk -> the OTLP
# gRPC exporter), which is exactly the kind of native socket the guard cannot
# see — which is why the Chainlit process is excluded from the egress claim
# rather than merely untested (docs/privacy-and-threat-model.md).
UI_EXTRA_MARKERS = ("chainlit", "literalai")


def test_no_native_networking_in_the_interpreter():
    """The practical half of the blind spot below, question one: nothing in the
    INTERPRETER running this file networks from C.

    The guard sees every network call made through Python's socket module and
    none made by a native extension with its own C sockets. That limit is only
    theoretical while no such extension is here.

    Skipped, rather than failed, where the `ui` extra is installed — a developer
    following docs/quick-start.md has it, and so does the `ui-smoke` job. The
    claim was never about that environment: a process holding `grpcio` is one
    this guard cannot speak for, which is the documented reason Chainlit is
    outside the scope. What must not be skipped is the locked closure below:
    that is the question the extra cannot excuse.
    """
    installed_names = _normalised_distributions()
    ui_extra = sorted(name for name in UI_EXTRA_MARKERS if name in installed_names)
    if ui_extra:
        pytest.skip(
            f"the ui extra is installed here ({', '.join(ui_extra)}), and its tree carries "
            "grpcio, which networks from C: this interpreter is outside the egress claim by "
            "design, and the Chainlit process it can start is the process that claim excludes. "
            "test_no_native_networking_in_the_locked_runtime still covers the application's own "
            "closure.")
    installed = _native_hits(installed_names)
    assert installed == set(), (
        f"{sorted(installed)} is installed here and does its own networking in C, "
        "which no assertion in this file can see")


def test_no_native_networking_in_the_locked_runtime():
    """Question two, and the one no environment can excuse: nothing in the
    APPLICATION's own runtime closure networks from C.

    Read from the lockfile rather than from whatever happens to be installed, so
    the claim survives a fresh environment and a dependency bump that pulled one
    in fails here instead of quietly widening the blind spot. `--no-dev` and the
    absence of any `--extra`: this is the tree a plain `uv sync` gives the CLI
    and the eval harness, which is what the claim is about.
    """
    exported = subprocess.run(
        ["uv", "export", "--no-dev", "--frozen", "--no-hashes", "--no-emit-project"],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    if exported.returncode != 0:                 # no uv on PATH: nothing to read the lockfile with
        pytest.skip(f"uv export is unavailable here: {exported.stderr.strip()[:200]}")
    locked = {line.split("==")[0].lower().replace("_", "-").replace(".", "-")
              for line in exported.stdout.splitlines()
              if "==" in line and not line.startswith((" ", "#"))}
    assert locked, "uv export produced no requirements; the check below would be vacuous"
    assert _native_hits(locked) == set()


@pytest.mark.xfail(strict=True, reason="known blind spot: a ctypes call reaches libc "
                                       "without passing through CPython's socket module, "
                                       "which is where the audit events are raised")
def test_a_ctypes_call_into_libc_is_the_known_blind_spot():
    """The limit, pinned instead of merely written down.

    This test asserts what the file would LIKE to be true — that a resolver call
    is seen however it is made — and it is expected to fail, because `ctypes`
    calls libc's `getaddrinfo` directly and CPython raises its audit events from
    its own socket module. `strict=True` is the point: if some future
    interpreter, sandbox or seccomp layer closes this door, the test passes, the
    strict xfail turns that pass into a failure, and whoever sees it has to come
    here and rewrite the scope paragraphs that currently say the door is open.

    The name resolved is `localhost`, from `/etc/hosts`: demonstrating that the
    guard cannot see the call does not require making an unguarded query about a
    public name leave the machine."""
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    result = ctypes.c_void_p()
    with record_egress() as guard:
        code = libc.getaddrinfo(b"localhost", None, None, ctypes.byref(result))
    if code == 0:
        libc.freeaddrinfo(result)
    assert code == 0, "the probe did not resolve, so it proves nothing either way"
    assert guard.attempts, "a ctypes call into libc was seen by the audit hook"


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
# The child that does the real work. The guard is armed as the FIRST statement,
# before the package, before its dependencies and before the guard module itself
# imports httpx — so an import-time lookup, a connection made while a dependency
# loads, or a worker started during import is inside the recording. It is never
# disarmed: the report is emitted from an atexit handler registered first, which
# therefore runs last, after every other handler and after the interpreter has
# joined its non-daemon threads.
LOCAL_RUN = """
import os                                  # stdlib only, for the stream path

from egress_guard import arm_guard
guard = arm_guard(stream_path=os.environ["AYL_EGRESS_STREAM"])

import atexit, json, tempfile

report = {}


def emit():
    # The SECONDARY record. The stream is the primary one: it is written as each
    # attempt happens, so it survives whatever this process does next, and the
    # parent derives its assertions from it. This snapshot is a cross-check —
    # the parent requires it to be a prefix of the stream, which it can only be
    # if the two agree about everything up to the moment it was taken.
    report["snapshot"] = [a.as_tuple() for a in guard.attempts]
    print(json.dumps(report))


# First registration, so atexit (which is LIFO) runs it LAST. Non-daemon threads
# are joined by the interpreter before atexit callbacks run, so by the time this
# prints, everything this process was going to do has been done under the guard.
atexit.register(emit)

from conftest import pin_environment
pin_environment()
%(extra_env)s

from pathlib import Path

from ask_your_library import config, embeddings, preflight
from ask_your_library.graph import build_graph
from ask_your_library.runner import run_question

report.update(backend=config.LLM_BACKEND, embed_backend=config.EMBED_BACKEND,
              llm_base_url=config.LLM_BASE_URL, ollama_url=config.OLLAMA_URL,
              openrouter_base_url=config.OPENROUTER_BASE_URL)

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
        # A failure inside the run comes back ON the result (the runner keeps the
        # metrics of what it spent); anything raised around it still raises here.
        result = run_question(build_graph(), "Who narrates Moby Dick?", [], Path(scratch),
                              on_event=lambda name, update: None,
                              on_clarify=lambda question: "")
        report["run"] = {"raised": result.failure.type if result.failure else "",
                         "message": result.failure.message[:300] if result.failure else "",
                         "answer": result.answer[:200]}
    except BaseException as error:
        report["run"] = {"raised": type(error).__name__, "message": str(error)[:300]}
"""


def local_run(extra_env: str = "", **env) -> dict:
    """The child above, in a fresh interpreter with `env` pinned.

    The returned report's `attempts`, `targets`, `off_machine` and `binds` come
    from the STREAM the child appended to as each attempt happened, not from the
    summary it printed on the way out. A summary is evidence about a process
    that lived long enough to write one; a stream is evidence either way, and it
    keeps the records of attempts made after the summary was taken.

    Several things are checked about the child itself first, because the summary
    is written during shutdown and a shutdown is a place where failures go
    quiet."""
    with tempfile.TemporaryDirectory() as home:
        stream_path = Path(home) / "egress.jsonl"
        stream_path.touch()
        result = _run(LOCAL_RUN % {"extra_env": extra_env}, check=False,
                      AYL_EGRESS_STREAM=str(stream_path), **env)
        records = [json.loads(line) for line in
                   stream_path.read_text().splitlines() if line.strip()]

    assert result.returncode == 0, result.stderr[-3000:]
    # An exception raised inside an atexit handler is printed and swallowed: the
    # exit code stays 0 and the summary is already on stdout. So the one place a
    # late connection attempt would show is stderr.
    assert "Error in atexit._run_exitfuncs" not in result.stderr, result.stderr[-3000:]
    assert "EgressBlocked" not in result.stderr, result.stderr[-3000:]
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, f"the child printed no report; stderr: {result.stderr[-2000:]}"
    report = json.loads(lines[-1])      # the atexit emission is the last line

    attempts = [[r["layer"], r["host"], r["port"], r["allowed"]] for r in records]
    # The summary must be a PREFIX of the stream. The stream may be longer — an
    # attempt made after the summary was taken is exactly what it exists to
    # catch — but it can never disagree with it or be shorter.
    snapshot = report.pop("snapshot")
    assert attempts[:len(snapshot)] == snapshot, (
        f"the stream and the child's own summary disagree:\n{attempts}\n{snapshot}")

    def as_pairs(chosen) -> list:
        return sorted(({(r["host"], r["port"]) for r in records if chosen(r)}), key=repr)

    report["records"] = records
    report["attempts"] = attempts
    report["targets"] = [list(t) for t in
                         as_pairs(lambda r: r["layer"] not in ("local", "socket.bind"))]
    report["off_machine"] = [list(t) for t in as_pairs(lambda r: not r["allowed"])]
    report["binds"] = [list(t) for t in as_pairs(lambda r: r["layer"] == "socket.bind")]
    return report


def test_the_guard_is_armed_before_the_first_import():
    """The control for the child's shape: a module that opens a connection while
    it is being imported is recorded, so "nothing was attempted" in the runs
    below is a statement about import time as well as run time.

    A monkeypatch installed after the application's imports could not say that,
    and neither could a guard armed one line later than this one."""
    code = """
from egress_guard import arm_guard
guard = arm_guard()

import json, pathlib, sys, tempfile

probe = pathlib.Path(tempfile.mkdtemp())
(probe / "egress_import_probe.py").write_text(
    "import socket\\nsocket.socket().connect(('%s', 443))\\n")
sys.path.insert(0, str(probe))
try:
    import egress_import_probe
    raised = ""
except BaseException as error:
    raised = type(error).__name__
print(json.dumps({"raised": raised,
                  "attempts": [a.as_tuple() for a in guard.attempts]}))
""" % OFF_MACHINE_IP
    report = json.loads(_run(code).stdout.strip().splitlines()[-1])
    assert report["raised"] == "EgressBlocked"
    assert [OFF_MACHINE_IP, 443] in [[host, port] for _, host, port, _ in report["attempts"]]
    assert all(not allowed for _, host, _, allowed in report["attempts"]
               if host == OFF_MACHINE_IP)


def test_the_local_configuration_talks_only_to_loopback():
    """A full pass of the real graph in the fully local configuration, with
    Ollama not running: preflight, an embedding call and the orchestrator's own
    calls all go to loopback on the configured Ollama port, and nothing else is
    contacted — not OpenRouter, not LangSmith, and no resolver is asked about
    either of them.

    The port is a reserved loopback port rather than 11434 so that a developer
    with Ollama actually running does not have this test make a model call; what
    is asserted is unchanged, since the assertion is that traffic went to the
    CONFIGURED endpoint and to nothing else. It is bound and held for the whole
    run, not bound and released, so "nothing is listening there" is deterministic
    rather than a race with whatever else the machine is doing."""
    with reserved_loopback_port() as port:
        report = local_run(LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
                           OLLAMA_URL=f"http://127.0.0.1:{port}")

    # The configuration the child actually resolved, so a misfired pin cannot
    # make the silence below mean nothing.
    assert report["backend"] == "ollama" and report["embed_backend"] == "ollama"
    assert report["llm_base_url"] == f"http://127.0.0.1:{port}/v1"

    # The whole allow-list, as one equality: one host, one port.
    assert report["targets"] == [["127.0.0.1", port]]
    assert report["off_machine"] == []
    # And at the level of the stream itself: not one refused record was written,
    # which is a stronger statement than "none survived into the summary" — a
    # refusal is streamed before it is raised, so an `except Exception:` inside
    # the application cannot hide one.
    assert [r for r in report["records"] if not r["allowed"]] == []
    # And no listening socket on a public interface either, which the bind
    # events would show.
    assert all(is_loopback(host) for host, _ in report["binds"])
    # The guard was not merely silent — it watched a real amount of traffic
    # (preflight's /api/tags, the embedder's /api/embed, the planner's call and
    # its retries), each seen at more than one layer. Both doors were used: the
    # model client goes out through httpx, `requests` through the socket floor.
    layers = {layer for layer, *_ in report["attempts"]}
    assert len(report["attempts"]) > 5
    assert "httpx" in layers and {"socket.connect", "socket.getaddrinfo"} <= layers

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
    # `APIConnectionError` in a subclass of its own, which is exactly the
    # wrapping llm.py's `CallTimeout` comment describes.
    assert report["run"]["raised"].endswith("ConnectionError")
    assert "openrouter" not in report["run"]["message"].lower()


def test_a_usable_hosted_key_does_not_move_the_local_run_off_the_machine():
    """The same local run with a usable-looking `OPENROUTER_API_KEY` in the
    environment.

    The test above runs with the key blanked, so a silent hosted fallback in it
    would have been caught by the MISSING KEY — an error about a credential,
    which is a weaker statement than the one this file makes. Here the key is
    present and the credential excuse is gone: if anything in the local
    configuration reached for the hosted provider, it would be able to build a
    client and the guard, not a `RuntimeError`, is what stops it. `off_machine`
    staying empty is therefore the load-bearing assertion, and the allow-list is
    still exactly the configured loopback endpoint.

    The key is a placeholder that is not a key, and nothing carrying it ever
    reaches a transport."""
    with reserved_loopback_port() as port:
        report = local_run(extra_env='os.environ["OPENROUTER_API_KEY"] = "not-a-key"',
                           LLM_BACKEND="ollama", EMBED_BACKEND="ollama",
                           OLLAMA_URL=f"http://127.0.0.1:{port}")

    assert report["off_machine"] == []
    assert [r for r in report["records"] if not r["allowed"]] == []
    assert report["targets"] == [["127.0.0.1", port]]
    # The same failure as without the key: the local runtime, not a credential.
    assert report["preflight_exit"] == 5 and "no_ollama" in report["preflight_kinds"]
    assert report["run"]["raised"].endswith("ConnectionError")


def test_the_shipped_defaults_point_at_this_machine():
    """The tests above configure their own endpoint, so on their own they prove
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
    # Refused at httpx for the orchestrator call and at the resolver for the
    # `requests`-based embedder: both doors, one guard.
    layers = {layer for layer, host, _, _ in report["attempts"] if host == "openrouter.ai"}
    assert "httpx" in layers and "socket.getaddrinfo" in layers
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
    assert report["targets"] == [] and report["off_machine"] == []
    assert report["run"]["raised"] == "RuntimeError"
    assert "OPENROUTER_API_KEY" in report["run"]["message"]
