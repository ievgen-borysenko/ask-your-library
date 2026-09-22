"""Ask Your Library — what `ayl ui` does before Chainlit starts.

Chainlit reads its settings from `<app root>/.chainlit/config.toml`, and the
app root is `CHAINLIT_APP_ROOT` or the working directory
(`chainlit/config.py`). Where it finds no config it WRITES ITS OWN DEFAULT
(`chainlit.config.init_config`) and where it finds no `chainlit.md` it writes a
placeholder (`chainlit.markdown.init_markdown`) — silently, and then serves
from it. Chainlit's default is not this app's configuration. Its
`allow_origins` is `["*"]`, where ours names the two loopback origins at the
serving port; its `unsafe_allow_html` is false, where the provenance badge and
the metrics footer are HTML; its `auto_tag_thread` is true, and with it on
SQLite refuses the tag list and the insert that carries a chat's title is lost.
Its `[features.mcp] enabled` happens to agree with ours in 2.12.0 — which is
Chainlit's decision to revisit at any release, not ours to lose track of, and
SECURITY.md names that line as what keeps MCP off.

That is why the web chat used to be startable only from the checkout: the
committed `.chainlit/config.toml` was the app root's only because the command
was run there. It is now this package's own file, and this module writes it
into the app root on EVERY start — so the configuration a server runs under is
the one shipped with the code that reads it, wherever the package is
installed, and a hand-edited copy in the app root cannot quietly put MCP back.

What is NOT decided here: the chat database and the auth secret, which
`app.py` still resolves from `AYL_CHAINLIT_DIR` (else the checkout, as before).
Moving that default under `AYL_HOME` is one decision with the index and the
scratch directory, and it is made in one place, not here.
"""
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .. import home

PACKAGE = Path(__file__).resolve().parent
APP = PACKAGE / "app.py"
CONFIG_TEMPLATE = PACKAGE / "chainlit_config.toml"
TRANSLATION = PACKAGE / "translations" / "en-US.json"
WELCOME = PACKAGE / "welcome.md"

# Chainlit's own (chainlit/config.py); repeated rather than imported, because
# `ayl ui --help` must answer on an installation without the `ui` extra.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

# The one line of the template that is not shipped as written: the port a
# server was started on is not knowable when the template is packaged.
ALLOW_ORIGINS = re.compile(r"^allow_origins\s*=.*$", re.M)

# A bind address is not an origin: no browser sends `Origin: http://0.0.0.0:…`.
# `0` and `::0` are the same wildcard written shorter, and `inet_aton` accepts
# both where a server binds.
WILDCARD_HOSTS = {"", "0.0.0.0", "0", "::", "::0", "*"}

# A DNS hostname, label by label: letters, digits and inner hyphens, 63 octets
# a label and 253 in total, with one optional trailing dot. Deliberately not a
# superset of what a resolver would take — what this admits is written into a
# TOML file and into a command line.
HOSTNAME = re.compile(r"(?!-)[A-Za-z0-9-]{1,63}(?<!-)(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?")


def default_host() -> str:
    """`CHAINLIT_HOST`, else loopback. Chainlit's CLI reads the same name when
    no `--host` is written; it is read here as well because `ayl ui` always
    passes the flag, and a variable a reader set that the command silently
    overrode would be worse than not supporting it."""
    return os.environ.get("CHAINLIT_HOST", "").strip() or DEFAULT_HOST


def checked_port(raw, named: str = "--port") -> int:
    """`raw` as a port number, or a refusal naming where it came from.

    Digits only, anything else refused rather than rounded — the rule `app.py`
    applies to its own numeric knob. One function for the variable and for the
    flag, because they end in the same two places: the command line of the
    server, and the `allow_origins` line of the file that decides its CORS
    list. `argparse`'s `type=int` would take `-1`, `+8000` and `0x1f90`."""
    text = str(raw).strip()
    if not re.fullmatch(r"[0-9]+", text) or not 0 < int(text) < 65536:
        raise SystemExit(f"{named} must be digits only, a port number between 1 and 65535")
    return int(text)


def default_port() -> int:
    """`CHAINLIT_PORT`, else 8000, on the same reasoning as `default_host`.
    Blank means unset, as blank does for every other knob here."""
    raw = os.environ.get("CHAINLIT_PORT", "").strip()
    return checked_port(raw, "CHAINLIT_PORT") if raw else DEFAULT_PORT


def app_root() -> Path:
    """The directory Chainlit is pointed at: `AYL_CHAINLIT_DIR`'s parent when
    that is set, else `$AYL_HOME/ui`.

    `AYL_CHAINLIT_DIR` names the `.chainlit/` directory itself — `app.py` reads
    it for the chat database and the auth secret — and Chainlit derives its own
    `.chainlit/` from the root above it, so taking the parent is what puts the
    config, the translations, the chat db and the secret in one directory
    rather than two.

    Unset, this is also where the chat database and the auth secret land when
    there is no checkout to hold them (`app.py`): a wheel's web chat writes
    under `AYL_HOME` and never into the working directory, which is a place
    anyone can prepare in advance. In a checkout the two part company by
    design — the app root is here, the chat db stays in the checkout's
    `.chainlit/` — until that default moves with the index and the scratch
    directory.

    `home.ayl_home()`, deliberately not `home.private_dir()`. That refusal
    guards what may never leave the machine — a model-written card of a work
    whose licence withholds an adaptation, the reader's own books, their index
    — from being written inside a checkout, where one `git add` would commit
    it. Nothing written here is any of that: a `config.toml` rendered from a
    template in this package, Chainlit's own `en-US.json`, and a welcome page
    that is already in the repository. Refusing to START THE WEB CHAT because
    the reader keeps their books folder under version control would be that
    rule applied where it has nothing to protect."""
    named = os.environ.get("AYL_CHAINLIT_DIR")
    if named:
        return Path(named).expanduser().resolve().parent
    return home.ayl_home() / "ui"


def checked_host(host: str) -> str:
    """`host` if it is an address a server could bind and a browser could be
    pointed at — an IPv4 or IPv6 literal, or a DNS hostname — else a refusal.

    Validated because of where it goes: `render_config` writes it into a TOML
    file, and the value can arrive from a `.env` that Chainlit loads before
    anything here runs. `CHAINLIT_HOST=evil"]` would close the `allow_origins`
    array and let whatever follows it be read as further TOML — new keys, in
    the file that decides this server's CORS list, its HTML policy and whether
    MCP is on. Quoting alone (`json.dumps`, below) closes the injection; this
    refuses the value as well, because a host nobody can reach is not a thing
    to start a server on quietly."""
    name = (host or "").strip()
    try:
        ipaddress.ip_address(name)
        return name
    except ValueError:
        pass
    if len(name) > 253 or not HOSTNAME.fullmatch(name):
        raise SystemExit(f"{name!r} is not a host: --host / CHAINLIT_HOST takes an IPv4 or "
                         f"IPv6 address, or a DNS name")
    return name


def _origin(host: str, port: int) -> str:
    """`http://host:port`, with an IPv6 address in the brackets a URL needs."""
    return f"http://[{host}]:{port}" if ":" in host else f"http://{host}:{port}"


def allow_origins(host: str, port: int) -> list[str]:
    """The CORS list the written config carries: the two loopback origins at
    the port this server is actually starting on, plus the host it was given
    when that is a name a browser could be pointed at.

    A page this server served is same-origin and needs no entry here at all;
    the list matters the other way round. A port is not part of an origin's
    site, so an entry naming a port the server is NOT on is a page on that port
    allowed to read the thread endpoints with the (SameSite) login cookie —
    which is what a `:8000` hard-coded into the shipped file became the moment
    anyone passed `--port`."""
    origins = [_origin("localhost", port), _origin("127.0.0.1", port)]
    name = (host or "").strip()
    if name in WILDCARD_HOSTS:
        return origins
    name = checked_host(name)
    if _origin(name, port) not in origins:
        origins.append(_origin(name, port))
    return origins


def render_config(host: str, port: int) -> str:
    """The packaged template with `allow_origins` rewritten for this start.

    The template is valid TOML as it ships — it is the file the tests read as
    the configuration this project makes — so the substitution is a line
    rewrite rather than a placeholder. Exactly one line must match: the day the
    template loses that key or grows a second one, this is a refusal to start
    and not a server running on origins nobody wrote.

    The list is built with `json.dumps` and the host is checked before it gets
    here: a TOML array of basic strings is JSON's array of strings, and the
    value being interpolated can come from a `.env` (`CHAINLIT_HOST=evil"]`
    would otherwise close the array and write keys of its own into this
    file)."""
    line = "allow_origins = " + json.dumps(allow_origins(host, port))
    rendered, replaced = ALLOW_ORIGINS.subn(lambda _: line,
                                            CONFIG_TEMPLATE.read_text(encoding="utf-8"))
    if replaced != 1:
        raise RuntimeError(f"{CONFIG_TEMPLATE} has {replaced} allow_origins lines, expected 1: "
                           f"the port this server serves on could not be written into the "
                           f"Chainlit configuration")
    return rendered


def prepare(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Path:
    """Make the app root what Chainlit is about to read, and return it.

    The config is written on every start, overwriting whatever is there: it is
    generated output, the security-relevant half of it (`allow_origins`,
    `[features.mcp]`, `unsafe_allow_html`) has to match the code that ships
    with it, and a copy left behind by an older version — or edited by hand —
    is a server running on decisions nobody made in this release, MCP among
    them.

    `write_text`, not `home.write_private`: that writer is the one rule for
    what may never be shared, and it refuses a path inside a git work tree —
    which is not this file. What it also buys, an atomic rename, this does not
    need: a half-written `config.toml` is not valid TOML, and Chainlit refuses
    to start on it rather than serving half a policy. The next start rewrites
    it from the template either way.

    The translation and the welcome page are copied only when they are absent:
    neither carries a decision the code depends on, and Chainlit itself would
    otherwise seed the directory with its own `en-US.json` (the copy step
    skips a file that already exists, which is the whole reason ours has to be
    there first)."""
    root = app_root()
    (root / ".chainlit" / "translations").mkdir(parents=True, exist_ok=True)
    (root / ".chainlit" / "config.toml").write_text(render_config(host, port), encoding="utf-8")
    for source, target in ((TRANSLATION, root / ".chainlit" / "translations" / "en-US.json"),
                           (WELCOME, root / "chainlit.md")):
        if not target.exists():
            shutil.copyfile(source, target)
    return root


def chainlit_command() -> str:
    """The `chainlit` console script beside the interpreter that is running
    this, or the bare name for PATH to resolve.

    The installation this package was imported from is the one whose Chainlit
    matches it, and it is not always the one on PATH: a test, a cron line or an
    editor that calls the interpreter by its absolute path gets an environment
    where `chainlit` resolves to nothing at all. The bare name is kept as the
    fallback for an installation that put the script somewhere else; `ayl ui`
    turns the FileNotFoundError from it into the sentence naming the extra."""
    beside = Path(sys.executable).parent / "chainlit"
    return str(beside) if beside.exists() else "chainlit"


def start(root: Path, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          extra: list[str] | None = None) -> int:
    """`chainlit run` against the packaged app, in the app root `root`.

    `CHAINLIT_APP_ROOT` is set for the child rather than exported here or
    leaned on through a working directory: it is the one name that decides
    which `.chainlit/` Chainlit reads, and the child is the only process that
    should be affected by it.

    Apart from `prepare` so that a caller can tell the two failures apart: the
    only FileNotFoundError this raises is the `chainlit` executable, which
    `ayl ui` answers by naming the extra."""
    environment = {**os.environ, "CHAINLIT_APP_ROOT": str(root)}
    return subprocess.call([chainlit_command(), "run", str(APP), "--host", host,
                            "--port", str(port), *(extra or [])], env=environment)


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, extra: list[str] | None = None) -> int:
    """The whole of what `ayl ui` does: prepare the app root, then serve."""
    return start(prepare(host, port), host, port, extra)
