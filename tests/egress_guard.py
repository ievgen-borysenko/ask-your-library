"""An egress guard: every outbound connection attempt this process makes, seen
and decided before it leaves.

The claim the local configuration makes — "nothing leaves the machine" — is a
claim about connection attempts, and nothing in the suite could see one. A test
that patches `llm.llm` proves the nodes never build a hosted client; it cannot
prove that no other import, SDK or background thread opens a socket of its own.
This module is the seam that makes the claim testable without touching `src/`:
the application is left exactly as it ships, and the process it runs in is
instrumented instead.

Three layers are patched, because three different clients are in play and each
reaches the network through a different door:

  socket      `socket.socket.connect` / `connect_ex` and `socket.create_connection`
              — the floor. urllib3 (which `requests` uses, in `embeddings` and
              `preflight`) brings its own `create_connection`, so the method on
              the class has to be patched too, not only the module function.
  name        the resolver, so a blocked host is refused BEFORE a resolver on
              the network is asked about it. A name is the first thing that
              leaves a machine, and it leaves it over the wire. `getaddrinfo`
              is the door httpx and urllib3 use, and it is NOT the only one:
              `gethostbyname`, `gethostbyname_ex`, `gethostbyaddr` and
              `getnameinfo` are separate calls into the same resolver, and one
              of them is on a path this project actually loads — LangSmith's
              `_is_localhost()` calls `gethostbyname` on its endpoint host to
              decide whether to skip a check. All five are patched, so "no name
              lookup for a hosted endpoint leaves this process" is a statement
              about the resolver and not about one of its five front doors.
  httpx       `HTTPTransport.handle_request` (and its async twin) — where the
              OpenAI SDK's client, and therefore every orchestrator call, is
              still holding a URL. Blocking here fails a hosted call with the
              host and port intact and no lookup attempted at all. BOTH httpx
              distributions installed here are patched: the OpenAI SDK does not
              use the `httpx` the application imports, it uses `httpx2`, and a
              guard that knew only the first name would have watched the wrong
              door for every model call in the project. The socket floor caught
              it anyway, which is the point of having a floor.

Everything is RECORDED, loopback included: a guard that only recorded what it
refused could not tell "talked to Ollama on loopback" from "talked to nothing",
and the interesting assertion is the allow-list, not the block list.

Not in scope, and deliberately: this is one Python process. Ollama, Chainlit's
node bundle and the browser are their own processes with their own sockets, and
nothing here can see them.
"""
import contextlib
import importlib
import ipaddress
import socket
from dataclasses import dataclass

# Every httpx distribution in the environment, because there is more than one:
# `httpx` is what the application imports (llm.py's timeouts, CallTimeout) and
# `httpx2` is what the OpenAI SDK's client is built on. A name that is not
# installed is simply not patched.
HTTPX_MODULES = ("httpx", "httpx2")

# Hostnames that mean "this machine" without a lookup. Any other NAME is
# off-machine by definition here: resolving it is itself the egress.
LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain",
                            "ip6-localhost", "ip6-loopback"})

_MISSING = object()


class EgressBlocked(RuntimeError):
    """A connection attempt to something that is not this machine. Raised at
    whichever layer saw it first, so the caller fails where a firewall would."""


# The five resolver entry points. Each takes its host as the first argument
# except `getnameinfo`, whose first argument is a sockaddr tuple, so that one is
# wrapped separately below.
NAME_LOOKUPS = ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr")


@dataclass(frozen=True)
class Attempt:
    """One outbound attempt, as one layer saw it. `layer` is the name of the
    function that was called, so a test can say which door was used."""
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

    def __init__(self, allow_loopback: bool = True):
        self.allow_loopback = allow_loopback
        self.attempts: list[Attempt] = []

    # -- what the test asks -------------------------------------------------
    def targets(self) -> set[tuple[str, int | None]]:
        """Every (host, port) that was attempted, once each. One connection
        shows up at three layers; this is the question "who was talked to"."""
        return {(a.host, a.port) for a in self.attempts if a.layer != "local"}

    def off_machine(self) -> set[tuple[str, int | None]]:
        """The attempts that were not loopback — the ones that would have left."""
        return {(a.host, a.port) for a in self.attempts if not a.allowed}

    def layers_for(self, host: str) -> list[str]:
        """Which layers saw an attempt for `host`, in order."""
        return [a.layer for a in self.attempts if a.host == host]

    # -- the decision -------------------------------------------------------
    def check(self, layer: str, host: str, port: int | None):
        allowed = self.allow_loopback and is_loopback(host)
        self.attempts.append(Attempt(layer, host, port, allowed))
        if not allowed:
            raise EgressBlocked(
                f"egress blocked at the {layer} layer: {host}:{port} is not this machine")

    def note_local(self, address) -> None:
        """A non-IP socket (a Unix domain socket): recorded so nothing is
        invisible, never blocked — it cannot leave the machine."""
        self.attempts.append(Attempt("local", str(address), None, True))


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


@contextlib.contextmanager
def record_egress(allow_loopback: bool = True):
    """Record (and, off loopback, refuse) every outbound connection attempt made
    inside the block. Yields the `EgressGuard` holding what was seen.

    Everything is restored on the way out, including the case where
    `socket.socket.connect` was only ever inherited from `_socket.socket`:
    assigning the inherited slot back would leave the subclass carrying an
    attribute it never had, so the patch is deleted instead."""
    guard = EgressGuard(allow_loopback)

    inet_families = {socket.AF_INET, socket.AF_INET6}
    originals = {name: vars(socket.socket).get(name, _MISSING)
                 for name in ("connect", "connect_ex")}
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex
    real_create_connection = socket.create_connection
    real_lookups = {name: getattr(socket, name) for name in NAME_LOOKUPS}
    real_getnameinfo = socket.getnameinfo
    transports = [(module.HTTPTransport, "handle_request",
                   module.HTTPTransport.handle_request, False)
                  for module in _httpx_modules()]
    transports += [(module.AsyncHTTPTransport, "handle_async_request",
                    module.AsyncHTTPTransport.handle_async_request, True)
                   for module in _httpx_modules()]

    def _check_address(layer: str, sock, address) -> None:
        if sock.family not in inet_families or not isinstance(address, (tuple, list)):
            guard.note_local(address)
            return
        guard.check(layer, str(address[0]), address[1] if len(address) > 1 else None)

    def connect(self, address):
        _check_address("socket", self, address)
        return real_connect(self, address)

    def connect_ex(self, address):
        _check_address("socket", self, address)
        return real_connect_ex(self, address)

    def create_connection(address, *args, **kwargs):
        host, port = address[0], address[1]
        guard.check("create_connection", str(host), port)
        return real_create_connection(address, *args, **kwargs)

    def name_lookup(name: str, original):
        """One of the four resolver calls whose FIRST argument is the host.

        `getaddrinfo` carries a port as its second argument and the other three
        do not, so the port is read positionally only when it is really one: a
        `gethostbyname_ex` has no second argument at all, and `getaddrinfo`'s
        may be a service name ("https") rather than a number."""
        def lookup(host, *args, **kwargs):
            # host=None is a local bind ("give me my own addresses"), not egress.
            if host is None:
                guard.note_local(f"{name}(None)")
            else:
                port = args[0] if args and isinstance(args[0], int) else None
                guard.check(name, str(host), port)
            return original(host, *args, **kwargs)
        return lookup

    def getnameinfo(sockaddr, flags):
        """The reverse direction, and the one whose host is not the first
        argument: a sockaddr, so the address and its port are both known."""
        if isinstance(sockaddr, (tuple, list)) and sockaddr:
            guard.check("getnameinfo", str(sockaddr[0]),
                        sockaddr[1] if len(sockaddr) > 1 else None)
        else:
            guard.note_local(sockaddr)
        return real_getnameinfo(sockaddr, flags)

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

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    for name, original in real_lookups.items():
        setattr(socket, name, name_lookup(name, original))
    socket.getnameinfo = getnameinfo
    for transport, attribute, original, is_async in transports:
        setattr(transport, attribute,
                (async_transport if is_async else sync_transport)(original))
    try:
        yield guard
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                delattr(socket.socket, name)
            else:
                setattr(socket.socket, name, original)
        socket.create_connection = real_create_connection
        for name, original in real_lookups.items():
            setattr(socket, name, original)
        socket.getnameinfo = real_getnameinfo
        for transport, attribute, original, _ in transports:
            setattr(transport, attribute, original)


def closed_loopback_port() -> int:
    """A loopback port with nothing behind it: bound to 0 so the kernel names a
    free one, then released. Used instead of Ollama's real 11434 so that a
    developer who happens to be running Ollama does not have this test make a
    model call — the port is the configured one either way, and what is asserted
    is that the traffic went to loopback AND to that port and nowhere else.

    Bind-and-release is a race, and an accepted one. Between the release here
    and the child's first connection, something else on this machine could take
    the port; a connection would then succeed instead of being refused. It is
    accepted because nothing the test asserts depends on the refusal: the
    assertions are about WHERE the attempts went (loopback, this port, nothing
    else), and a listener that answered would still be on loopback and would
    still not be a hosted provider — at worst the run's failure mode changes
    from "connection refused" to "not Ollama", which the preflight reports as a
    bad reply and the graph pass as a client error, and the test would say so
    instead of passing quietly. Holding the socket open for the duration would
    trade that for a real listener on the port, which is worse: the child would
    connect to a socket nobody reads and wait out the timeout."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
