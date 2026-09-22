"""The Chainlit configuration a start actually runs under.

Chainlit writes its OWN default config.toml into an app root that has none and
then serves from it, silently. That default is not this application's:
`allow_origins = ["*"]` against our two loopback origins at the serving port,
`unsafe_allow_html` false where the provenance badge and the metrics footer are
HTML, `auto_tag_thread` true where it loses every chat title on SQLite. Its
`[features.mcp] enabled` agrees with ours in 2.12.0, and that is Chainlit's
decision to revisit rather than one this project would learn about — SECURITY.md
names that line as what keeps MCP off, so it is asserted here like the rest. The
tests read the file on disk after a start has prepared the root (the loaded
object would agree with itself either way), and the last ones open the built
wheel, because a template that is not in the distribution is Chainlit's default
on every machine that installed one.

No Chainlit import: the launcher writes files and starts a subprocess, and
this file must run on a clone without the `ui` extra.
"""
import importlib
import os
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from ask_your_library.ingest import backup
from ask_your_library.ui import launcher

REPO = Path(__file__).resolve().parents[1]
PACKAGE_DATA = ("ask_your_library/ui/chainlit_config.toml",
                "ask_your_library/ui/translations/en-US.json",
                "ask_your_library/ui/welcome.md")


def written_config(root: Path) -> dict:
    return tomllib.loads((root / ".chainlit" / "config.toml").read_text(encoding="utf-8"))


# --- which directory is prepared ---------------------------------------------

def test_the_app_root_is_the_home_folder_when_nothing_says_otherwise(monkeypatch, tmp_path):
    monkeypatch.delenv("AYL_CHAINLIT_DIR", raising=False)
    monkeypatch.setattr("ask_your_library.config.AYL_HOME", tmp_path / "AskYourLibrary")
    assert launcher.app_root() == (tmp_path / "AskYourLibrary" / "ui").resolve()


def test_the_app_root_is_the_directory_above_ayl_chainlit_dir(monkeypatch, tmp_path):
    """`AYL_CHAINLIT_DIR` names the `.chainlit/` itself — app.py reads it for
    the chat db and the auth secret — and Chainlit derives its own from the
    root above it. Taking the parent is what keeps one directory instead of
    two."""
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "state" / ".chainlit"))
    assert launcher.app_root() == (tmp_path / "state").resolve()


def test_a_home_inside_a_checkout_still_starts_the_web_chat(monkeypatch, tmp_path):
    """`home.private_dir` refuses a folder inside a git work tree, and rightly:
    it guards what may never be shared. Nothing written here is that — a
    config rendered from this package, Chainlit's own en-US.json, a welcome
    page that is in the repository — so a reader whose AYL_HOME happens to sit
    in a checkout gets a web chat, not a refusal."""
    (tmp_path / ".git").mkdir()
    monkeypatch.delenv("AYL_CHAINLIT_DIR", raising=False)
    monkeypatch.setattr("ask_your_library.config.AYL_HOME", tmp_path / "home")
    root = launcher.prepare("127.0.0.1", 8000)
    assert root == (tmp_path / "home" / "ui").resolve()
    assert written_config(root)["features"]["unsafe_allow_html"] is True


# --- the config a fresh app root gets ----------------------------------------

@pytest.fixture
def root(monkeypatch, tmp_path):
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "root" / ".chainlit"))
    return (tmp_path / "root").resolve()


def test_a_fresh_app_root_gets_our_config_and_not_chainlits_default(root):
    """The decisive one. Every key here is a decision this project made, and
    every one of them is a line Chainlit's generated default either reverses or
    is free to change without this project hearing about it."""
    launcher.prepare("127.0.0.1", 8123)
    config = written_config(root)

    assert config["features"]["unsafe_allow_html"] is True
    assert config["features"]["auto_tag_thread"] is False
    assert config["features"]["mcp"]["enabled"] is False
    assert config["features"]["mcp"]["user_servers"]["enabled"] is False
    assert config["project"]["allow_origins"] == ["http://localhost:8123",
                                                  "http://127.0.0.1:8123"]


def test_the_port_the_server_is_on_is_the_port_the_cors_list_names(root):
    """`allow_origins` shipped with `:8000` written into it, so any other port
    left a page on :8000 allowed to read this server's thread endpoints with
    the login cookie. The list follows the command line now."""
    launcher.prepare("127.0.0.1", 9001)
    assert written_config(root)["project"]["allow_origins"] == ["http://localhost:9001",
                                                                "http://127.0.0.1:9001"]
    assert "8000" not in (root / ".chainlit" / "config.toml").read_text(encoding="utf-8")


def test_a_host_a_browser_could_be_pointed_at_is_added_and_a_bind_address_is_not(root):
    """A server told to serve on a name is reachable under it; `0.0.0.0` is a
    bind address and no browser ever sends it as an Origin."""
    launcher.prepare("books.local", 8000)
    assert written_config(root)["project"]["allow_origins"] == [
        "http://localhost:8000", "http://127.0.0.1:8000", "http://books.local:8000"]

    launcher.prepare("0.0.0.0", 8000)
    assert written_config(root)["project"]["allow_origins"] == ["http://localhost:8000",
                                                                "http://127.0.0.1:8000"]


def test_an_ipv6_host_is_written_as_a_url_and_not_as_three_colons(root):
    launcher.prepare("::1", 8000)
    assert "http://[::1]:8000" in written_config(root)["project"]["allow_origins"]


def test_a_hand_edited_config_is_overwritten_on_the_next_start(root):
    """Decided and pinned: overwritten. The config is generated output whose
    security-relevant half has to match the code that ships with it, and a
    stale copy — an older version's, or one somebody edited — is a server
    running on decisions nobody made in this release. The file written here is
    the shape that costs the most: MCP on, HTML off, every origin allowed."""
    launcher.prepare("127.0.0.1", 8000)
    config_file = root / ".chainlit" / "config.toml"
    config_file.write_text("[project]\nallow_origins = [\"*\"]\n\n"
                           "[features]\nunsafe_allow_html = false\n\n"
                           "[features.mcp]\nenabled = true\n", encoding="utf-8")

    launcher.prepare("127.0.0.1", 8000)

    config = written_config(root)
    assert config["features"]["mcp"]["enabled"] is False
    assert config["features"]["unsafe_allow_html"] is True
    assert config["project"]["allow_origins"] == ["http://localhost:8000",
                                                  "http://127.0.0.1:8000"]


def test_the_translation_and_the_welcome_page_are_put_there_and_then_left_alone(root):
    """Chainlit seeds the app root with its own copy of every language it
    ships and skips a name that is already there, so ours has to arrive first.
    Neither file carries a decision the code depends on, and the welcome page
    is a reader's to edit — so, unlike the config, they are copied only when
    they are absent."""
    launcher.prepare("127.0.0.1", 8000)
    translation = root / ".chainlit" / "translations" / "en-US.json"
    welcome = root / "chainlit.md"
    assert "This starts a new chat" in translation.read_text(encoding="utf-8")
    assert welcome.read_text(encoding="utf-8") == launcher.WELCOME.read_text(encoding="utf-8")

    translation.write_text("{}", encoding="utf-8")
    welcome.write_text("mine", encoding="utf-8")
    launcher.prepare("127.0.0.1", 8000)
    assert translation.read_text(encoding="utf-8") == "{}"
    assert welcome.read_text(encoding="utf-8") == "mine"


def test_a_template_that_lost_its_origins_line_is_a_refusal_and_not_a_guess(root, monkeypatch):
    """The substitution is a line rewrite over a template that is valid TOML as
    it ships. If that line is ever renamed or duplicated, the start stops here
    rather than serving on origins nobody wrote."""
    stripped = root / "template.toml"
    stripped.parent.mkdir(parents=True, exist_ok=True)
    stripped.write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "CONFIG_TEMPLATE", stripped)
    with pytest.raises(RuntimeError, match="allow_origins"):
        launcher.prepare("127.0.0.1", 8000)


# --- and it is the app root the server is actually pointed at -----------------

def test_a_host_that_is_not_a_host_is_refused_before_it_reaches_the_file(root):
    """`render_config` interpolates the host into TOML, and the host can come
    from a `.env` Chainlit loads before anything of ours runs: `evil"]` would
    close the `allow_origins` array and write keys of its own into the file
    that decides this server's CORS list, its HTML policy and whether MCP is
    on. Refused, and — the second half — quoted even so."""
    for hostile in ('evil"]', 'x"]\n[features.mcp]\nenabled = true\n#', "a b", "-lead",
                    "e" * 254, "http://books.local", "books.local:8000"):
        with pytest.raises(SystemExit, match="host"):
            launcher.render_config(hostile, 8000)

    # A name and an address still land, and a blank host is "none named" (the
    # wildcard branch), not a refusal: `ayl ui` always passes a host.
    launcher.prepare("books.example.com", 8000)
    assert "http://books.example.com:8000" in written_config(root)["project"]["allow_origins"]
    launcher.prepare("192.168.1.9", 8000)
    assert "http://192.168.1.9:8000" in written_config(root)["project"]["allow_origins"]
    launcher.prepare("", 8000)
    assert written_config(root)["project"]["allow_origins"] == ["http://localhost:8000",
                                                                "http://127.0.0.1:8000"]


def test_a_host_with_a_quote_in_it_could_not_write_a_key_even_if_it_got_through(root,
                                                                                monkeypatch):
    """Belt and braces: with the check disabled, the quoting alone still has to
    leave one `allow_origins` string and no new key."""
    monkeypatch.setattr(launcher, "checked_host", lambda host: host)
    launcher.prepare('evil"]\n[features.mcp]\nenabled = true\n#', 8000)
    config = written_config(root)
    assert config["features"]["mcp"]["enabled"] is False
    assert len(config["project"]["allow_origins"]) == 3


def test_the_prepared_root_is_the_one_chainlit_is_told_to_read(root, monkeypatch):
    seen = {}
    monkeypatch.setattr(launcher.subprocess, "call",
                        lambda command, env=None: seen.update(command=command, env=env) or 0)

    assert launcher.run("127.0.0.1", 8123, ["-w"]) == 0
    assert seen["command"] == [launcher.chainlit_command(), "run", str(launcher.APP),
                               "--host", "127.0.0.1", "--port", "8123", "-w"]
    assert seen["env"]["CHAINLIT_APP_ROOT"] == str(root)
    assert written_config(root)["project"]["allow_origins"][0] == "http://localhost:8123"


def test_the_chainlit_beside_this_interpreter_is_the_one_that_runs(monkeypatch, tmp_path):
    """The installation this package was imported from is the one whose
    Chainlit matches it, and PATH does not always name it: an absolute-path
    call to the interpreter (a test, a cron line, an editor) resolves
    `chainlit` to nothing at all."""
    (tmp_path / "bin").mkdir()
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "bin" / "python"))
    assert launcher.chainlit_command() == "chainlit"          # no script beside it

    (tmp_path / "bin" / "chainlit").write_text("")
    assert launcher.chainlit_command() == str(tmp_path / "bin" / "chainlit")


# --- the three files have to be IN the distribution ---------------------------

def test_the_packaged_files_are_in_the_built_wheel(tmp_path):
    """A wheel without them is an `ayl ui` that serves Chainlit's default
    configuration on every machine that installed one — and nothing else in
    this suite would notice, because a source checkout has the files whatever
    the build says."""
    build = subprocess.run(["uv", "build", "--wheel", "--offline", "--out-dir", str(tmp_path)],
                           cwd=REPO, capture_output=True, text=True)
    if build.returncode != 0:
        pytest.skip(f"uv build --wheel did not run here: {build.stderr.strip()[-200:]}")
    wheel = next(tmp_path.glob("*.whl"))
    names = set(zipfile.ZipFile(wheel).namelist())
    assert set(PACKAGE_DATA) <= names, sorted(set(PACKAGE_DATA) - names)
    assert "ask_your_library/ui/app.py" in names and "ask_your_library/ui/launcher.py" in names


def test_every_packaged_file_the_launcher_reads_is_named_in_pyproject():
    """The wheel test above needs a build; this one needs nothing, so the pair
    still says something on a machine where `uv build` cannot run. The three
    paths the launcher reads at runtime are the three pyproject names as
    artifacts, and each one is on disk."""
    artifacts = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    artifacts = artifacts["tool"]["hatch"]["build"]["targets"]["wheel"]["artifacts"]
    assert sorted(artifacts) == sorted(f"src/{name}" for name in PACKAGE_DATA)
    for source in (launcher.CONFIG_TEMPLATE, launcher.TRANSLATION, launcher.WELCOME):
        assert source.is_file(), source


def test_the_chat_db_and_the_auth_secret_never_default_to_the_working_directory(tmp_path):
    """The wheel this slice makes possible, started anywhere: `<cwd>/.chainlit`
    is a directory anyone can create first, and an `auth-secret` planted there
    would be the signing key of every login token the server issues. So with no
    checkout the fallback is the app root under AYL_HOME, and the working
    directory is never consulted.

    Asked in a child, because both modules resolve this at import, and from a
    COPY of the package with no pyproject.toml above it — which is what makes
    `paths.REPO_ROOT` empty exactly as it is in a wheel. `ingest/backup.py` is
    asked in the same child: `ayl backup` copies that file and `ayl restore`
    writes it, so the two must not disagree about which file it is."""
    import shutil

    package = Path(launcher.__file__).resolve().parents[1]
    staged = tmp_path / "site-packages"
    shutil.copytree(package, staged / "ask_your_library",
                    ignore=shutil.ignore_patterns("__pycache__"))
    cwd = tmp_path / "started-here"
    cwd.mkdir()
    home = tmp_path / "AskYourLibrary"

    code = ("from ask_your_library import paths\n"
            "from ask_your_library.ui import launcher\n"
            "from ask_your_library.ingest.backup import default_chat_db\n"
            "assert paths.REPO_ROOT == '', paths.REPO_ROOT\n"
            "print(launcher.app_root())\n"
            "print(default_chat_db())\n")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          cwd=str(cwd),
                          env={**os.environ, "PYTHONPATH": str(staged),
                               "AYL_HOME": str(home), "AYL_CHAINLIT_DIR": ""})
    assert done.returncode == 0, done.stderr

    app_root, chat_db = (Path(line) for line in done.stdout.split())
    assert app_root == (home / "ui").resolve()
    assert chat_db == (home / "ui" / ".chainlit" / "chat.db").resolve()
    assert not (cwd / ".chainlit").exists()


def test_a_tilde_in_the_variable_is_expanded_everywhere_it_is_read(tmp_path, monkeypatch):
    """`.env.example` recommends `AYL_CHAINLIT_DIR=~/AskYourLibrary/ui/.chainlit`,
    and no shell expands a value read out of a file. `Path("~/x")` is a
    directory literally named `~` under the working directory, so the server
    would have minted its auth secret in one `~` folder and `ayl backup` looked
    for the chat database in another. Three readers, one answer: the launcher's
    app root, the web chat's state directory and the backup command's default.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("AYL_CHAINLIT_DIR", "~/AskYourLibrary/ui/.chainlit")
    wanted = tmp_path / "AskYourLibrary" / "ui" / ".chainlit"

    assert launcher.chainlit_dir() == wanted
    assert launcher.app_root() == wanted.parent
    assert backup.default_chat_db() == wanted / "chat.db"
    assert "~" not in str(launcher.chainlit_dir())

    # and the app reads the same directory at its own import
    chainlit = pytest.importorskip("chainlit") and None          # noqa: F841
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("AYL_ALLOW_DEFAULT_LOGIN", "1")
    monkeypatch.setenv("AYL_ALLOW_START_WITHOUT_KEY", "1")
    sys.modules.pop("ask_your_library.ui.app", None)
    try:
        app = importlib.import_module("ask_your_library.ui.app")
        assert app.CHAINLIT_DIR == wanted
        # the import really wrote there, under the expanded path
        assert (wanted / "chat.db").exists()
    finally:
        sys.modules.pop("ask_your_library.ui.app", None)


def test_the_scratch_directory_is_absolute_and_not_beside_the_caller(tmp_path, monkeypatch):
    """`config`'s default is the relative `.scratch`, which was right while the
    web chat could only be started from the checkout. From a wheel the first
    answered question would have dropped retrieved passages in a `.scratch/`
    wherever the terminal happened to be. `$AYL_HOME/scratch` is where the
    index and the CLI's own scratch go when they move."""
    monkeypatch.delenv("ASK_SCRATCH_DIR", raising=False)
    monkeypatch.setattr("ask_your_library.config.AYL_HOME", tmp_path / "AskYourLibrary")
    assert launcher.scratch_dir() == (tmp_path / "AskYourLibrary" / "scratch").resolve()

    # and it is what the child is told, unless the reader said otherwise
    monkeypatch.setenv("AYL_CHAINLIT_DIR", str(tmp_path / "root" / ".chainlit"))
    seen = {}
    monkeypatch.setattr(launcher.subprocess, "call",
                        lambda command, env=None: seen.update(env=env) or 0)
    launcher.run("127.0.0.1", 8000)
    assert seen["env"]["ASK_SCRATCH_DIR"] == str((tmp_path / "AskYourLibrary" / "scratch")
                                                 .resolve())

    monkeypatch.setenv("ASK_SCRATCH_DIR", "~/elsewhere")
    monkeypatch.setenv("HOME", str(tmp_path))
    launcher.run("127.0.0.1", 8000)
    assert seen["env"]["ASK_SCRATCH_DIR"] == str(tmp_path / "elsewhere")


def test_chainlits_own_host_and_port_are_read_and_a_nonsense_port_refused(monkeypatch):
    """`ayl ui` always passes `--host` and `--port`, so Chainlit's CLI never
    gets to read these itself; a variable a reader set that the command
    silently overrode would be worse than not supporting it. A port that is
    not a port is refused rather than rounded — it goes into `allow_origins`
    as well as onto the command line."""
    monkeypatch.delenv("CHAINLIT_HOST", raising=False)
    monkeypatch.delenv("CHAINLIT_PORT", raising=False)
    assert (launcher.default_host(), launcher.default_port()) == ("127.0.0.1", 8000)

    monkeypatch.setenv("CHAINLIT_HOST", "0.0.0.0")
    monkeypatch.setenv("CHAINLIT_PORT", "9100")
    assert (launcher.default_host(), launcher.default_port()) == ("0.0.0.0", 9100)

    for nonsense in ("8_000", "+8000", "0", "99999", "eight"):
        monkeypatch.setenv("CHAINLIT_PORT", nonsense)
        with pytest.raises(SystemExit, match="CHAINLIT_PORT"):
            launcher.default_port()
        # `ayl ui --port` is the same rule under its own name; argparse's
        # type=int would have taken every one of these but "eight".
        with pytest.raises(SystemExit, match="--port"):
            launcher.checked_port(nonsense)


def test_the_launcher_does_not_need_the_ui_extra_to_be_imported():
    """`ayl` imports it on every command, including on a plain install: the
    launcher starts `chainlit` as a subprocess and must not import it."""
    done = subprocess.run([sys.executable, "-c",
                           "import sys\n"
                           "sys.modules['chainlit'] = None\n"
                           "from ask_your_library.ui import launcher\n"
                           "import ask_your_library.ayl\n"
                           "print(launcher.DEFAULT_PORT)\n"],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "8000"
