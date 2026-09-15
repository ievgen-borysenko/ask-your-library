"""An egress guard: every outbound connection attempt this process makes, seen
and decided before it leaves.

The claim the local configuration makes — "nothing leaves the machine" — is a
claim about connection attempts, and nothing in the suite could see one. A test
that patches `llm.llm` proves the nodes never build a hosted client; it cannot
prove that no other import, SDK or background thread opens a socket of its own.
This module is the seam that makes the claim testable without touching `src/`:
the application is left exactly as it ships, and the process it runs in is
instrumented instead.

The floor is an AUDIT HOOK, not a set of monkeypatches
-----------------------------------------------------
The first version of this file patched `socket.socket.connect`,
`socket.create_connection` and the five resolver functions on the `socket`
module. That watches one class and one set of module attributes, and a socket
can be opened without touching either:

  * `_socket.socket` is the C type `socket.socket` inherits from. An instance of
    it has its own `connect` and never passes through the Python subclass.
  * `_socket.getaddrinfo`, `_socket.gethostbyname` and friends are the C
    functions the `socket` module re-exports; anything that imports them from
    `_socket` bypasses a patch on `socket`.
  * `from socket import getaddrinfo` binds the function BY VALUE. A module that
    did that before the guard went on keeps calling the real one.
  * UDP needs no `connect` at all: `sendto` and `sendmsg` carry the address, and
    a DNS resolver or a telemetry ping is exactly that shape.

CPython raises audit events from the C layer for all of it, whatever the class
or the import path, so `sys.addaudithook` sees what a patch cannot. The events
used here, each verified against the installed interpreter (CPython 3.12.13) by
a probe rather than taken from the documentation:

  socket.connect      (sock, address)   — also what `connect_ex` raises
  socket.sendto       (sock, address)   — unconnected UDP
  socket.sendmsg      (sock, address)   — unconnected UDP, scatter/gather form
  socket.bind         (sock, address)   — recorded only, see below
  socket.getaddrinfo  (host, port, family, type, proto)
  socket.gethostbyname(hostname)        — raised by `gethostbyname_ex` too, so
                                          there is no separate event for it
  socket.gethostbyaddr(address)
  socket.getnameinfo  (sockaddr,)

`socket.bind` is RECORDED and never refused. A bind is not egress: it is the
other direction, and refusing one would break a library that opens a local
socket for its own reasons. It is recorded because a bind to something that is
not loopback is a listening socket on a public interface, which a test about
this process's network behaviour should be able to say did not happen.

An audit hook cannot be removed once installed, so this module installs exactly
one, at import, and arms it through a module-level flag under a lock. Disarmed,
the hook is a single global read and a return. Armed, it is process-wide and
therefore also covers background threads — which is the point: a batching
exporter uploads from a thread nobody in the test is looking at.

One layer sits ON TOP of the floor, and only because it says something the floor
cannot: `HTTPTransport.handle_request` (and its async twin) is where a client
still holds a URL, so a hosted call is refused there with its host and port
intact and no lookup attempted at all. BOTH httpx distributions installed here
are patched — the model client's SDK does not use the `httpx` the application
imports, it uses `httpx2` — and a request that slipped past both would still
meet the audit hook underneath.

Everything is RECORDED, loopback included: a guard that only recorded what it
refused could not tell "talked to Ollama on loopback" from "talked to nothing",
and the interesting assertion is the allow-list, not the block list. Records are
also STREAMED, one JSON line per attempt written to an unbuffered file
descriptor as it happens and before a refusal raises, so a child's evidence does
not depend on the child surviving to summarise itself.

What this guard sees, and what it does not
------------------------------------------
It sees **every network call made through Python's socket module**, which is
every network call the standard library, `requests`, urllib3, httpx, httpcore,
asyncio and the model client's SDK make.

It does NOT see a call that reaches libc without passing through CPython: a
native extension with its own C sockets, or a `ctypes` call into
`getaddrinfo` / `connect`. The audit events are raised by CPython's own socket
module, so code that skips it skips them. That limit is pinned by an xfail
control in tests/test_egress_local.py rather than only written down here, and
the environment is checked for the known native-networking packages by a test of
its own — because the honest form of this limit is not "it could be bypassed in
principle" but "nothing installed here can bypass it".

Not in scope, and deliberately: this is one Python process. Ollama, Chainlit's
node bundle and the browser are their own processes with their own sockets, and
nothing here can see them.
"""
import contextlib
import importlib
import ipaddress
import json
import os
import socket
import sys
import threading
from dataclasses import dataclass

# Every httpx distribution in the environment, because there is more than one:
# `httpx` is what the application imports (llm.py's timeouts, CallTimeout) and
# `httpx2` is what the model client's SDK is built on. A name that is not
# installed is simply not patched.
HTTPX_MODULES = ("httpx", "httpx2")

# Hostnames that mean "this machine" without a lookup. Any other NAME is
# off-machine by definition here: resolving it is itself the egress.
LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain",
                            "ip6-localhost", "ip6-loopback"})

# The one event that is recorded and never refused; see the module docstring.
BIND_EVENT = "socket.bind"


class EgressBlocked(RuntimeError):
    """A connection attempt to something that is not this machine. Raised at
    whichever layer saw it first, so the caller fails where a firewall would."""


@dataclass(frozen=True)
class Attempt:
    """One outbound attempt, as one layer saw it. `layer` is the audit event
    name (or `httpx` / `httpx-async` for the URL layer above it), so a test can
    say which door was used."""
    layer: str
    host: str
    port: int | None
    allowed: bool

    def as_tuple(self) -> tuple:
        return (self.layer, self.host, self.port, self.allowed)


def is_loopback(host: str) -> bool:
    """Is `host` this machine, decided without asking the network?

    A literal address is judged by the standard library (127.0.0.0/8 and ::1,
    not just 127.0.0.1); a name is judged by the short list above. An unknown
    name is NOT resolved to find out — that lookup is the very thing an egress
    test is watching for."""
    name = (host or "").strip().strip("[]").lower()
    if name in LOOPBACK_NAMES:
        return True
    # A scoped IPv6 literal ("::1%lo0") carries its interface after a percent.
    try:
        return ipaddress.ip_address(name.split("%")[0]).is_loopback
    except ValueError:
        return False


class EgressGuard:
    """The recorder. `attempts` is every outbound attempt in order, at every
    layer that saw it; the helpers below reduce it to the sets a test asserts on."""

    def __init__(self, allow_loopback: bool = True, stream_fd: int | None = None):
        self.allow_loopback = allow_loopback
        self.attempts: list[Attempt] = []
        # An open file descriptor, written with os.write (no buffer to lose) one
        # JSON line per attempt, at the moment the attempt is seen. The in-memory
        # list is a summary of a process that lived to produce it; this is the
        # record of a process whether or not it did.
        self._stream_fd = stream_fd

    # -- what the test asks -------------------------------------------------
    def targets(self) -> set[tuple[str, int | None]]:
        """Every (host, port) an EGRESS attempt named, once each. One connection
        shows up at more than one layer; this is the question "who was talked
        to". Binds and local sockets are not targets and are not in it."""
        return {(a.host, a.port) for a in self.attempts
                if a.layer not in ("local", BIND_EVENT)}

    def off_machine(self) -> set[tuple[str, int | None]]:
        """The attempts that were not loopback — the ones that would have left."""
        return {(a.host, a.port) for a in self.attempts if not a.allowed}

    def binds(self) -> set[tuple[str, int | None]]:
        """Every address this process bound a socket to. Recorded, never
        refused; a non-loopback one would be a listening socket on a public
        interface, which is the other direction and its own question."""
        return {(a.host, a.port) for a in self.attempts if a.layer == BIND_EVENT}

    def layers_for(self, host: str) -> list[str]:
        """Which layers saw an attempt for `host`, in order."""
        return [a.layer for a in self.attempts if a.host == host]

    # -- the decision -------------------------------------------------------
    def _record(self, attempt: Attempt) -> None:
        """Append, and stream. `os.write` on a raw descriptor: no buffer that a
        crash, a `os._exit` or a killed interpreter could swallow, and no audit
        event of its own (CPython audits `open`, not `write`), so this cannot
        re-enter the hook that called it."""
        self.attempts.append(attempt)
        if self._stream_fd is not None:
            os.write(self._stream_fd, (json.dumps({
                "layer": attempt.layer, "host": attempt.host,
                "port": attempt.port, "allowed": attempt.allowed}) + "\n").encode())

    def check(self, layer: str, host: str, port: int | None):
        allowed = layer == BIND_EVENT or (self.allow_loopback and is_loopback(host))
        # Recorded BEFORE the refusal is raised: a caller that catches
        # EgressBlocked — and the application catches broad exceptions in
        # several places — must not be able to erase the fact that it tried.
        self._record(Attempt(layer, host, port, allowed))
        if not allowed:
            raise EgressBlocked(
                f"egress blocked at the {layer} layer: {host}:{port} is not this machine")

    def note_local(self, address) -> None:
        """A socket that cannot leave the machine (a Unix domain socket, a
        connected UDP send with no address of its own): recorded so nothing is
        invisible, never blocked."""
        self._record(Attempt("local", str(address), None, True))


# --------------------------------------------------------------- the floor
_LOCK = threading.Lock()
_ACTIVE: EgressGuard | None = None    # read by the hook on every audited event
_HOOK_INSTALLED = False


def _text(value) -> str:
    """An audit event's host may arrive as bytes (the C layer passes through
    what it was given)."""
    return value.decode("utf-8", "replace") if isinstance(value, (bytes, bytearray)) else str(value)


def _address(guard: EgressGuard, layer: str, address) -> None:
    """A sockaddr as `connect` / `sendto` / `sendmsg` / `bind` carry it."""
    if address is None:
        # A connected UDP socket sends with no address: the `connect` that set
        # it was audited already.
        guard.note_local(f"{layer}(None)")
    elif isinstance(address, (tuple, list)) and address:
        guard.check(layer, _text(address[0]), address[1] if len(address) > 1 else None)
    else:
        # AF_UNIX (a path), AF_NETLINK (an int), anything else that cannot route.
        guard.note_local(address)


def _audit(event: str, args: tuple) -> None:
    """The audit hook. Installed once per interpreter and never removed, so the
    disarmed path — a global read and a return — is what the rest of the test
    suite pays, and it must stay that cheap."""
    guard = _ACTIVE
    if guard is None:
        return
    if event == "socket.connect" or event == "socket.sendto" or event == "socket.sendmsg" \
            or event == BIND_EVENT:
        _address(guard, event, args[1] if len(args) > 1 else None)
    elif event == "socket.getaddrinfo":
        host = args[0] if args else None
        if host is None:
            guard.note_local("getaddrinfo(None)")     # a local bind, not egress
        else:
            port = args[1] if len(args) > 1 and isinstance(args[1], int) else None
            guard.check(event, _text(host), port)
    elif event == "socket.gethostbyname" or event == "socket.gethostbyaddr":
        guard.check(event, _text(args[0]), None)
    elif event == "socket.getnameinfo":
        _address(guard, event, args[0] if args else None)


def install_audit_hook() -> None:
    """Install the hook, once. Idempotent, and irreversible by design: CPython
    offers no way to remove an audit hook, which is exactly why arming is a flag
    and not an installation."""
    global _HOOK_INSTALLED
    with _LOCK:
        if _HOOK_INSTALLED:
            return
        sys.addaudithook(_audit)
        _HOOK_INSTALLED = True


install_audit_hook()          # at import: one hook per interpreter, disarmed


def _port_of(url) -> int:
    """The port a request is actually for: httpx leaves `.port` None when the
    URL carries the scheme's default."""
    return url.port or (443 if url.scheme in ("https", "wss") else 80)


def _httpx_modules() -> list:
    modules = []
    for name in HTTPX_MODULES:
        try:
            modules.append(importlib.import_module(name))
        except ImportError:
            continue
    return modules


def _patch_transports(guard: EgressGuard) -> list:
    """The URL layer on top of the floor. Returns what to restore."""
    def sync_transport(original):
        def handle_request(self, request):
            guard.check("httpx", request.url.host, _port_of(request.url))
            return original(self, request)
        return handle_request

    def async_transport(original):
        async def handle_async_request(self, request):
            guard.check("httpx-async", request.url.host, _port_of(request.url))
            return await original(self, request)
        return handle_async_request

    patched = []
    for module in _httpx_modules():
        for cls, attribute, wrap in ((module.HTTPTransport, "handle_request", sync_transport),
                                     (module.AsyncHTTPTransport, "handle_async_request",
                                      async_transport)):
            original = getattr(cls, attribute)
            patched.append((cls, attribute, original))
            setattr(cls, attribute, wrap(original))
    return patched


def arm(guard: EgressGuard) -> EgressGuard:
    """Arm the process-wide hook with `guard`. Not nestable on purpose: two
    guards would each see half of what happened."""
    global _ACTIVE
    with _LOCK:
        if _ACTIVE is not None:
            raise RuntimeError("an egress guard is already armed in this process")
        _ACTIVE = guard
    return guard


def disarm() -> None:
    global _ACTIVE
    with _LOCK:
        _ACTIVE = None


def _open_stream(stream_path: str | None) -> int | None:
    """Append-only, created if missing. Opened here rather than handed in, so a
    caller only has to know a path."""
    if not stream_path:
        return None
    return os.open(stream_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)


def arm_guard(allow_loopback: bool = True, stream_path: str | None = None) -> EgressGuard:
    """Arm the guard for the REST OF THIS PROCESS and never disarm it.

    For a child interpreter whose whole life is the thing under test. Called as
    the first statement, before the application or any dependency is imported,
    it also covers import-time lookups and connections, background workers
    started during import, and — because nothing ever disarms it — everything
    that still runs during interpreter shutdown: an atexit handler, a batching
    exporter's last upload, a thread joined on the way out.

    The hook goes on BEFORE the httpx modules are imported, so even the import
    of the layer above the floor happens under the floor.

    `stream_path` is where each attempt is appended as a JSON line as it
    happens. The descriptor is deliberately never closed: this guard has no end,
    and a close would be one more thing that could happen before the last
    write."""
    guard = arm(EgressGuard(allow_loopback, _open_stream(stream_path)))
    _patch_transports(guard)
    return guard


@contextlib.contextmanager
def record_egress(allow_loopback: bool = True, stream_path: str | None = None):
    """Arm the guard for the duration of the block, for an in-process test.

    The audit hook itself is never removed — it was installed at import of this
    module — so what this restores is the arming flag and the httpx patches."""
    stream_fd = _open_stream(stream_path)
    guard = arm(EgressGuard(allow_loopback, stream_fd))
    patched = _patch_transports(guard)
    try:
        yield guard
    finally:
        disarm()
        for cls, attribute, original in patched:
            setattr(cls, attribute, original)
        if stream_fd is not None:
            os.close(stream_fd)


@contextlib.contextmanager
def reserved_loopback_port(attempts: int = 20):
    """A loopback port that nothing answers on, reserved for the whole block.

    Used instead of Ollama's real 11434 so that a developer who happens to be
    running Ollama does not have a test make a model call; what the tests assert
    is unchanged, because they assert that traffic went to the CONFIGURED
    endpoint and to nothing else.

    The port is held on UDP and left free on TCP, which is not the obvious
    arrangement, so: the tests want two things from this port, and holding a
    bound TCP socket gives only one of them.

      * No race. Bind, read the port, close, hand the number out — and in the
        window before the child connects, the kernel can hand the same number to
        anything else on the machine. That is the thing to avoid.
      * A fast, deterministic "nothing is there". The child is standing in for
        "Ollama is not running", and what that looks like is ECONNREFUSED,
        immediately.

    A TCP socket bound and not listening does not give the second on macOS.
    Measured here (Darwin 25.6, CPython 3.12): a connect to a bound,
    non-listening loopback port TIMES OUT — the SYN is dropped, 4.00 s to a
    4 s deadline — while the same port after the socket is closed refuses in
    0.00 s. Linux answers RST in both cases, but a test that is only fast on the
    CI leg is not a test anyone runs. Worse than slow, it changes what is under
    test: with every connect stalling for its full connect timeout the run stops
    failing on an unreachable endpoint and starts degrading into an answer, so
    the assertions would be describing a different path.

    Holding a UDP socket on the number gives the first without costing the
    second. TCP and UDP are separate port spaces: the TCP side is genuinely
    free, so a connect gets RST at once, while the kernel will not hand this
    number out as an ephemeral port to anything else for the life of the block.
    What is left is not a race but a deliberate collision — something choosing
    to bind this exact TCP port in the ephemeral range — and if it happened, it
    would have to answer Ollama's `/api/tags` on loopback for a test to pass
    wrongly; every assertion here is about WHERE the traffic went, and loopback
    is where it went either way."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    for _ in range(attempts):
        reserved = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            reserved.bind(("127.0.0.1", port))
        except OSError:
            # Taken between the probe and here; ask the kernel for another one.
            reserved.close()
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = int(probe.getsockname()[1])
            continue
        try:
            yield port
        finally:
            reserved.close()
        return
    raise RuntimeError("could not reserve a free loopback port")
