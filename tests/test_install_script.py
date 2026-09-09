"""The macOS installer's dry run: ordered, honest about what it would do, inert.

`bash scripts/install-mac.sh --dry-run` is what a reader inspects before letting
a script touch their machine, so two things have to hold. The plan names every
step, in the order the script performs it. And the dry run itself does nothing:
`brew`, `ollama`, `uv` and `curl` are replaced here by recorders, on a PATH that
cannot reach the real ones, and every record has to come back empty.

Some tests here are not dry runs: what the script does when a tool fails, when
the endpoint it is asked to reach is somebody else's machine, what it will and
will not start a server on, and what it leaves behind when writing `.env` fails,
is only visible in a real run. They use the same recorders — so a "real" run
still installs, downloads and starts nothing — and each either stops at a
refusal, before anything is installed, or walks the whole script with every
tool stubbed out.

Step 12 is a Python program embedded in the script, and its classification of
this run's own leftovers is tested separately, on the snippet alone: it needs
neither macOS nor the eleven steps in front of it.

The steps that install, download or write are only reachable on macOS (the
script refuses anywhere else), so those tests run on macOS and the refusal
itself is what CI on Linux checks — the `install-script` job in `ci.yml` is
where they actually run. `--help` and a bad flag are parsed before the platform
check, so they are tested everywhere.
"""
import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO, SCRUBBED, fresh_output

SCRIPT = REPO / "scripts" / "install-mac.sh"
BASH = shutil.which("bash")
# Everything the script could invoke that installs, downloads or starts something.
RECORDED = ("brew", "ollama", "uv", "curl")
# The plan, in the order the script prints it.
PLAN = [
    "[1/12] macOS",
    "[2/12] Repository root",
    "[3/12] Homebrew",
    "[4/12] Git",
    "[5/12] uv",
    "[6/12] Python",
    "[7/12] Ollama",
    "[8/12] Models",
    "[9/12] Dependencies",
    "[10/12] Configuration",
    "[11/12] Demo corpus",
    "[12/12] Verification",
    "Next steps:",
]

pytestmark = pytest.mark.skipif(BASH is None, reason="no bash on this system")
mac_only = pytest.mark.skipif(platform.system() != "Darwin",
                              reason="the installer runs on macOS only")


@pytest.fixture
def sandbox(tmp_path):
    """A clone holding exactly the files the script reads, plus a PATH that
    cannot reach the real brew / ollama / uv / curl and records every call to
    the stubs standing in for them.

    The copy is what makes the run deterministic: a developer's own `.env` or
    `data/lancedb` in the repository would send steps 10 and 11 down their other
    branch. The files themselves are the real ones, so the plan is built from
    the project's actual pyproject.toml, .env.example and config.py."""
    root = tmp_path / "clone"
    (root / "scripts").mkdir(parents=True)
    (root / "src" / "ask_your_library").mkdir(parents=True)
    for name in ("pyproject.toml", ".env.example", "scripts/install-mac.sh",
                 "src/ask_your_library/config.py"):
        shutil.copy(REPO / name, root / name)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    records = tmp_path / "records"
    records.mkdir()
    for name in RECORDED:
        stub = bindir / name
        stub.write_text(f'#!/bin/sh\necho "$@" >> "{records}/{name}"\nexit 0\n')
        stub.chmod(0o755)

    # The Ollama knobs are dropped so the script has to read its model names and
    # endpoint from config.py, which is where the app reads them from.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("OLLAMA_") and k != "LIBRARY_DB_PATH"}
    # Stubs first, then the system directories only: no /opt/homebrew, no
    # ~/.local/bin, so `uv` and friends cannot resolve to the real binaries.
    env["PATH"] = os.pathsep.join([str(bindir), "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    return root, records, env


def dry_run(sandbox, *flags):
    root, _, env = sandbox
    # Exactly the documented invocation: from the clone root, through bash.
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--dry-run", *flags],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def reaches_the_start_path(sandbox):
    """Make the run take the branch that starts Ollama — where the OLLAMA_HOST
    gate is — and then let it finish. `curl` answers only once something has
    started a server, which here means once `brew` has been called: before that
    /api/tags is unreachable and the script has to start one, after it the server
    is up and the wait loop ends on its first check instead of after a minute."""
    _, records, env = sandbox
    curl = Path(env["PATH"].split(os.pathsep)[0]) / "curl"
    curl.write_text(f'#!/bin/sh\necho "$@" >> "{records}/curl"\n'
                    f'[ -e "{records}/brew" ] && exit 0\nexit 7\n')
    curl.chmod(0o755)


def real_run(sandbox, *flags, **environment):
    """Not a dry run: the steps themselves, against the recorders."""
    root, _, env = sandbox
    return subprocess.run([BASH, "scripts/install-mac.sh", *flags], cwd=root,
                          env={**env, **environment}, capture_output=True, text=True)


def config_models():
    """The two model names as the package resolves them with nothing exported —
    i.e. the defaults in config.py, which are what the script must pull."""
    return fresh_output("from ask_your_library import config;"
                        "print(config.OLLAMA_EMBED_MODEL, config.OLLAMA_LLM_MODEL)").split()


@mac_only
def test_dry_run_names_every_step_in_order(sandbox):
    out = dry_run(sandbox)
    at = -1
    for marker in PLAN:
        found = out.find(marker, at + 1)
        assert found > at, f"{marker!r} is missing or out of order in:\n{out}"
        at = found


@mac_only
def test_dry_run_runs_nothing_and_writes_nothing(sandbox):
    root, records, _ = sandbox
    out = dry_run(sandbox)
    called = sorted(path.name for path in records.iterdir())
    assert called == [], f"the dry run invoked {called}"
    assert not (root / ".env").exists()
    assert not (root / "data").exists()
    assert "Nothing is installed, downloaded or written" in out


@mac_only
def test_dry_run_pulls_the_models_the_code_asks_for(sandbox):
    """The names come from config.py, not from a literal in the script: change
    the default and the plan pulls the new model."""
    embed_model, llm_model = config_models()
    out = dry_run(sandbox)
    assert f"ollama pull {embed_model}" in out
    assert f"ollama pull {llm_model}" in out
    assert "approximate" in out          # the sizes are stated as approximate


@mac_only
def test_local_mode_configures_both_backends_on_ollama(sandbox):
    out = dry_run(sandbox)
    assert "LLM_BACKEND=ollama" in out
    assert "EMBED_BACKEND=ollama" in out
    # config.py's own default for the local backend. A .env copied from the
    # example is an environment value and would otherwise pin the hosted 120 s.
    assert "LLM_TIMEOUT_S=600" in out
    # The per-question wall clock has no per-backend default: 300 s is the whole
    # budget for four steps, which a cold local model can spend in the first one.
    assert "QUESTION_DEADLINE_S=1200" in out
    # This is the mode where nothing leaves the machine, so the two tracing flags
    # the SDK reads are written off rather than left to the inherited shell.
    assert "LANGSMITH_TRACING_V2=false" in out
    assert "LANGCHAIN_TRACING_V2=false" in out
    # Nothing that could carry a key is ever echoed, in either mode.
    assert "OPENROUTER_API_KEY=" not in out


@mac_only
def test_hosted_mode_keeps_the_hosted_model_and_never_asks_for_a_key(sandbox):
    embed_model, llm_model = config_models()
    out = dry_run(sandbox, "--hosted")
    assert "LLM_BACKEND=openrouter" in out
    assert f"ollama pull {embed_model}" in out          # embeddings stay local
    assert f"ollama pull {llm_model}" not in out
    assert "never takes a key as an argument" in out
    assert "OPENROUTER_API_KEY=" not in out


@mac_only
def test_demo_build_is_confirmed_once_and_says_how_long_it_takes(sandbox):
    out = dry_run(sandbox)
    assert "about 30 minutes" in out
    assert "ask once for confirmation" in out
    assert "uv run scripts/ingest_demo_corpus.py" in out


@mac_only
def test_no_demo_points_at_ayl_add_instead(sandbox):
    out = dry_run(sandbox, "--no-demo")
    assert "skipped (--no-demo)" in out
    assert "uv run ayl-add ~/books" in out
    assert "ingest_demo_corpus.py" not in out


@mac_only
def test_a_failing_tool_exits_1_and_names_the_command(sandbox, tmp_path):
    """A refusal has to arrive as one of the documented codes. `run` invokes the
    tool directly, so without a status check `set -e` ends the script with that
    tool's own status — 17 here — and nothing of the script's own printed."""
    root, _, env = sandbox
    bindir = tmp_path / "failing-bin"
    bindir.mkdir()
    stub = bindir / "brew"          # and no uv on this PATH, so step 5 installs it
    stub.write_text("#!/bin/sh\nexit 17\n")
    stub.chmod(0o755)
    env = {**env, "PATH": os.pathsep.join([str(bindir), "/usr/bin", "/bin"])}
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--no-demo"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert "brew install uv failed with status 17" in result.stderr


@mac_only
def test_refuses_to_start_a_server_that_is_not_on_this_machine(sandbox):
    """Nothing answers on OLLAMA_URL, and the address is not one this machine
    could be serving: starting a local Ollama would not be the server that was
    asked for, so the script says so and stops."""
    root, _, env = sandbox
    bindir = Path(env["PATH"].split(os.pathsep)[0])      # the stubs, first on PATH
    curl = bindir / "curl"
    curl.write_text("#!/bin/sh\nexit 7\n")               # /api/tags answers nowhere
    curl.chmod(0o755)
    env = {**env, "OLLAMA_URL": "http://ollama.example.com"}
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--no-demo"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert "not an address on this machine" in result.stderr


@mac_only
@pytest.mark.parametrize("bind", ["0.0.0.0:11434", ":11434", "0", "11434", "999999",
                                  "example.com:11434"])
def test_a_non_loopback_ollama_host_is_refused(sandbox, bind):
    """OLLAMA_HOST, not OLLAMA_URL, is what a server started here binds, so the
    gate is on it and it is closed by default. A bare port is refused with the
    rest: ':11434' is a host/port pair whose empty host is every interface, and
    '0' is 0.0.0.0 — the two spellings that read most like loopback and are not."""
    _, records, _ = sandbox
    reaches_the_start_path(sandbox)
    result = real_run(sandbox, "--no-demo", OLLAMA_HOST=bind)
    assert result.returncode == 1, result.stdout
    assert f"OLLAMA_HOST={bind}" in result.stderr
    assert "unset OLLAMA_HOST" in result.stderr           # the fix is named
    assert not (records / "brew").exists(), "the gate let a server be started"


@mac_only
@pytest.mark.parametrize("bind", ["", "localhost", "127.0.0.1:11434", "[::1]:11434",
                                  "http://127.0.0.1:11434", "https://localhost"])
def test_a_loopback_ollama_host_passes_the_gate(sandbox, bind):
    """The forms that mean this machine — with or without a port, with or without
    a scheme — are the ones a server may be started on, and 'http://127.0.0.1:11434'
    is among them: it was refused before, which is the wrong half to fail closed."""
    _, records, _ = sandbox
    reaches_the_start_path(sandbox)
    result = real_run(sandbox, "--no-demo", OLLAMA_HOST=bind)
    assert result.returncode == 0, result.stderr
    assert "OLLAMA_HOST" not in result.stderr
    # Past the gate is `brew services run` — the session-only form, no login item.
    assert "services run ollama" in (records / "brew").read_text()
    assert "brew services start ollama" in result.stdout   # how to make it permanent


@mac_only
@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a chmod 000 file anyway")
def test_a_failed_env_write_leaves_no_env_behind(sandbox):
    """`local_env > .env` truncated the file into existence before sed produced a
    byte, so a sed that failed left an empty .env — which the next run refuses to
    overwrite and config.py resolves to the hosted defaults. The fully local run
    became a hosted one, silently. Now the write lands beside it and only a
    complete file is moved into place."""
    root, _, _ = sandbox
    reaches_the_start_path(sandbox)
    (root / ".env.example").chmod(0o000)
    try:
        result = real_run(sandbox, "--no-demo")
    finally:
        (root / ".env.example").chmod(0o644)
    assert result.returncode == 1, result.stdout
    assert "no usable .env" in result.stderr
    assert not (root / ".env").exists(), "a .env was left behind by a failed write"
    assert [p.name for p in root.glob(".env.tmp.*")] == []


@mac_only
def test_an_existing_env_decides_the_mode_and_says_so(sandbox):
    """A .env is never overwritten, so it — not the flag — is what the run is
    setting up. Without --hosted the banner still says fully local, so the step
    that finds the file has to say plainly that the mode was not applied, and
    the answering model that mode would pull must not be pulled."""
    root, records, _ = sandbox
    embed_model, llm_model = config_models()
    reaches_the_start_path(sandbox)
    (root / ".env").write_text("LLM_BACKEND=openrouter\nOPENROUTER_API_KEY=k\n")
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 0, result.stderr
    assert "it sets LLM_BACKEND=openrouter" in result.stdout
    assert "was NOT applied" in result.stdout
    pulled = (records / "ollama").read_text()
    assert f"pull {embed_model}" in pulled          # embeddings are local either way
    assert f"pull {llm_model}" not in pulled


@mac_only
def test_refuses_outside_the_repository_root(tmp_path):
    # Steps 1 and 2 only read; nothing is stubbed here because nothing runs.
    result = subprocess.run([BASH, str(SCRIPT), "--dry-run"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "pyproject.toml" in result.stderr


@pytest.mark.skipif(platform.system() == "Darwin", reason="this machine is macOS")
def test_refuses_to_run_anywhere_but_macos(tmp_path):
    result = subprocess.run([BASH, str(SCRIPT), "--dry-run"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert "macOS only" in result.stderr
    assert "README.md" in result.stderr


# --- the preflight snippet, on its own ---------------------------------------
# Step 12 is a Python program embedded in the script, and its exit codes are what
# turn "something is wrong" into "this run's own leftovers". That classification
# is the part worth testing, and it needs neither macOS nor the eleven steps in
# front of it: the snippet is lifted out of the script by the same shape the
# script writes it in, and run against the installed package.
PREFLIGHT_RE = re.compile(r"^preflight_code='\n(.*?)\n'$", re.M | re.S)
have_package = importlib.util.find_spec("ask_your_library") is not None


def preflight_snippet():
    match = PREFLIGHT_RE.search(SCRIPT.read_text(encoding="utf-8"))
    assert match, "preflight_code='...' is no longer in the script in that shape"
    return match.group(1)


def run_preflight(expected, tmp_path):
    """The snippet in a fresh interpreter that has an OpenRouter key and no
    index: the key half of check_environment passes and no Ollama is contacted,
    so the missing index is the only problem — the condition being classified."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    env["PYTHONPATH"] = str(REPO)
    env.update(LLM_BACKEND="openrouter", EMBED_BACKEND="openrouter",
               OPENROUTER_API_KEY="not-a-real-key",
               LIBRARY_DB_PATH=str(tmp_path / "nothing-here"))
    return subprocess.run([sys.executable, "-c", preflight_snippet(), expected],
                          cwd=tmp_path, env=env, capture_output=True, text=True)


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_classifies_a_missing_index(tmp_path):
    result = run_preflight("no-index", tmp_path)
    assert result.returncode == 3, result.stdout + result.stderr
    assert str(tmp_path / "nothing-here") in result.stdout      # and still reports it


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_fails_a_problem_this_run_did_not_leave(tmp_path):
    """The same missing index, with nothing declared expected: an unclassified
    problem is exit 1, which is what ends the run."""
    result = run_preflight("", tmp_path)
    assert result.returncode == 1, result.stdout + result.stderr


def test_help_lists_every_flag(tmp_path):
    # Parsed before the platform and repository checks, so it answers anywhere.
    result = subprocess.run([BASH, str(SCRIPT), "--help"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0
    for flag in ("--dry-run", "--yes", "--no-demo", "--hosted", "--help"):
        assert flag in result.stdout


def test_unknown_flag_is_a_usage_error(tmp_path):
    result = subprocess.run([BASH, str(SCRIPT), "--nope"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "unknown option: --nope" in result.stderr
