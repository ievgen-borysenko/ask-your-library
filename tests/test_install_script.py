"""The macOS installer's dry run: ordered, honest about what it would do, inert.

`bash scripts/install-mac.sh --dry-run` is what a reader inspects before letting
a script touch their machine, so two things have to hold. The plan names every
step, in the order the script performs it. And the dry run itself does nothing:
`brew`, `ollama`, `uv` and `curl` are replaced here by recorders, on a PATH that
cannot reach the real ones, and every record has to come back empty.

The steps that install, download or write are only reachable on macOS (the
script refuses anywhere else), so those tests run on macOS and the refusal
itself is what CI on Linux checks. `--help` and a bad flag are parsed before
the platform check, so they are tested everywhere.
"""
import os
import platform
import shutil
import subprocess

import pytest

from conftest import REPO, fresh_output

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
