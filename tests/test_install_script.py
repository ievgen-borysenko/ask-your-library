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
    # endpoint from config.py, which is where the app reads them from. The rest
    # of conftest's pinned configuration goes with them: this suite exports
    # LLM_BACKEND=openrouter into every test process, and the script now refuses
    # a fully local run under exactly that, so a scrubbed environment is what
    # "nothing in this shell decides the run" has to mean here. The tests that
    # describe an exported variable put it back themselves.
    env = {k: v for k, v in os.environ.items()
           if k not in SCRUBBED and not k.startswith("OLLAMA_")}
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
    """Make the run take the branch that starts Ollama, and then let it finish.
    `curl` answers only once something has started a server, which here means
    once `brew` has been called: before that /api/tags is unreachable and the
    script has to start one, after it the server is up and the wait loop ends on
    its first check instead of after a minute."""
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


def invoked(records):
    """The recorders this run actually called. A refusal by the guard has to
    come back empty: it is the fail-closed resolution of where the data goes,
    and `brew install uv` (step 5) plus `uv python install` (step 6) sat in
    front of it — a package manager's worth of software downloaded and written
    for a run that was never going to be allowed to happen."""
    return sorted(path.name for path in records.iterdir())


def error_lines(text):
    """The script's own stderr, one whole line per entry, without the `error: `
    prefix. Assertions compare a whole line against it rather than searching the
    stream for a fragment: a substring test against a line that carries a URL
    reads as an allow-list check on that URL and is not one."""
    return [line[len("error: "):].strip() for line in text.splitlines()
            if line.startswith("error: ")]


def printed_lines(text):
    """The same for stdout, where the script indents its own lines by seven
    spaces and step 12 does too."""
    return [line.strip() for line in text.splitlines()]


def env_example_with_local_backend(root):
    """The .env a reader writes by hand: the example, with the one line the
    local mode needs. Its two tracing lines stay commented out, which is how
    .env.example ships them and the state that lets a key decide alone."""
    text = (root / ".env.example").read_text(encoding="utf-8")
    return re.sub(r"^LLM_BACKEND=.*$", "LLM_BACKEND=ollama", text, flags=re.M)


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
    asked for, so the script says so and stops. Under --hosted, because in the
    fully local mode the same URL is refused earlier, by the guard: an endpoint
    off this machine contradicts the mode outright, answering or not."""
    root, _, env = sandbox
    bindir = Path(env["PATH"].split(os.pathsep)[0])      # the stubs, first on PATH
    curl = bindir / "curl"
    curl.write_text("#!/bin/sh\nexit 7\n")               # /api/tags answers nowhere
    curl.chmod(0o755)
    env = {**env, "OLLAMA_URL": "http://ollama.example.com"}
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--no-demo", "--hosted"],
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
    result = real_run(sandbox, "--no-demo", OLLAMA_HOST=bind)
    assert result.returncode == 1, result.stdout
    assert f"OLLAMA_HOST={bind}" in result.stderr
    assert "unset OLLAMA_HOST" in result.stderr           # the fix is named
    # The gate is judged with the rest of the resolution, ahead of step 3, so
    # nothing at all runs in front of it — `uv python find` included.
    assert invoked(records) == [], "the gate let a tool run past it"


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


# --- the shell the script is started from ------------------------------------
# config.py calls load_dotenv() without override, so a variable already exported
# wins over every line step 10 writes. A shell carrying another project's hosted
# settings therefore walked the whole "fully local" install to "Done." while the
# application it configured answered on OpenRouter, embedded on OpenRouter and
# uploaded traces. The .env was right; nothing read it.
HOSTED_SHELL = {"LLM_BACKEND": "openrouter", "EMBED_BACKEND": "openrouter",
                "LANGSMITH_TRACING_V2": "true"}


@mac_only
def test_exported_hosted_settings_stop_the_fully_local_install(sandbox):
    """Exit 2, before anything is pulled or written, naming every variable, where
    the value comes from, and the two ways to drop it."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", **HOSTED_SHELL)
    assert result.returncode == 2, result.stdout
    for name, value in HOSTED_SHELL.items():
        assert f"{name}={value} (exported in this shell)" in result.stderr
    assert "unset LLM_BACKEND EMBED_BACKEND LANGSMITH_TRACING_V2" in result.stderr
    assert "env -u LLM_BACKEND -u EMBED_BACKEND -u LANGSMITH_TRACING_V2" in result.stderr
    assert "--hosted" in result.stderr                    # the mode that means this on purpose
    assert invoked(records) == [], "the refusal ran a tool before deciding"
    assert not (root / ".env").exists(), "a .env was written before the refusal"


@mac_only
def test_an_ollama_url_off_this_machine_stops_the_fully_local_install(sandbox):
    """The endpoint counts too: a remote Ollama that answers is a remote Ollama.
    Step 7 only ever refused one that did not answer, so this one walked
    through — the whole library embedded off the machine under "fully local"."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", OLLAMA_URL="http://ollama.example.com")
    assert result.returncode == 2, result.stdout
    assert "OLLAMA_URL=http://ollama.example.com (exported in this shell)" in result.stderr
    assert "not on this machine" in result.stderr
    assert invoked(records) == []
    assert not (root / ".env").exists()


@mac_only
def test_a_clean_shell_passes_the_guard_and_writes_the_local_env(sandbox):
    """The other half: with nothing exported the guard says so and the run goes
    through to the local .env it was always meant to write."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 0, result.stderr
    assert "Nothing exported in this shell decides where data goes" in result.stdout
    assert "LLM_BACKEND=ollama" in (root / ".env").read_text()


@mac_only
def test_hosted_mode_reports_the_same_shell_instead_of_refusing_it(sandbox):
    """--hosted is the mode those values describe, so they are reported, not
    refused: the run is hosted either way and nothing is being misrepresented."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", "--hosted", **HOSTED_SHELL)
    assert result.returncode == 0, result.stderr
    assert "LLM_BACKEND=openrouter (exported in this shell)" in result.stdout
    assert "reported only" in result.stdout
    assert (root / ".env").exists()


@mac_only
def test_the_dry_run_refuses_the_same_shell_and_says_it_wrote_nothing(sandbox):
    """A dry run that printed a plan it could not carry out would be the same
    lie one step earlier, so the guard runs there too."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--dry-run", "--no-demo", **HOSTED_SHELL)
    assert result.returncode == 2, result.stdout
    assert "LLM_BACKEND=openrouter (exported in this shell)" in result.stderr
    assert "nothing was installed, downloaded or written" in result.stderr
    assert sorted(path.name for path in records.iterdir()) == []
    assert not (root / ".env").exists()


@mac_only
def test_a_tracing_key_alone_stops_the_fully_local_install(sandbox):
    """The key is the switch. graph.py sets LANGCHAIN_TRACING_V2=true whenever
    LANGCHAIN_API_KEY is present and that name is not set AT ALL, so a .env whose
    two tracing lines are still commented out — the shape .env.example ships —
    plus a key inherited from another project traced the whole run while every
    flag this script reads still said off, and step 12 printed "tracing: off".
    The value itself is never printed: it is a credential, and only its presence
    decides anything."""
    root, records, _ = sandbox
    (root / ".env").write_text(env_example_with_local_backend(root))
    result = real_run(sandbox, "--no-demo", LANGCHAIN_API_KEY="lsv2-not-a-real-key")
    assert result.returncode == 2, result.stdout
    assert ("LANGCHAIN_API_KEY=<set> (exported in this shell) — a key with no "
            "LANGCHAIN_TRACING_V2 set turns tracing on by itself: prompts and answers "
            "would be uploaded to https://api.smith.langchain.com (the LangSmith default)"
            ) in error_lines(result.stderr)
    assert "lsv2-not-a-real-key" not in result.stderr + result.stdout
    assert "unset LANGCHAIN_API_KEY" in error_lines(result.stderr)
    # And the other way out, which is the line the local .env already carries.
    assert any("LANGCHAIN_TRACING_V2=false" in line for line in error_lines(result.stderr))
    assert invoked(records) == [], "the refusal ran a tool before deciding"


@mac_only
def test_a_tracing_flag_that_is_set_keeps_the_key_from_deciding(sandbox):
    """The rule graph.py applies is about the NAME being set, not about its
    value: LANGCHAIN_TRACING_V2=false is what stops the key, and that is the line
    the local .env writes. A run with the same key and that line goes through."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", LANGCHAIN_API_KEY="lsv2-not-a-real-key")
    assert result.returncode == 0, result.stderr
    assert "LANGCHAIN_TRACING_V2=false" in (root / ".env").read_text()
    assert "LANGCHAIN_API_KEY=<set> (exported in this shell)" in printed_lines(result.stdout)
    assert "lsv2-not-a-real-key" not in result.stdout + result.stderr


@mac_only
def test_a_userinfo_host_is_not_this_machine(sandbox):
    """The host of http://localhost:11434@ollama.example.com is
    ollama.example.com; everything in front of the @ is userinfo, and it is
    exactly the text a match on a prefix reads as loopback. The application
    resolves the host, so this resolves the host."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--no-demo",
                      OLLAMA_URL="http://localhost:11434@ollama.example.com")
    assert result.returncode == 2, result.stdout
    assert ("OLLAMA_URL=http://localhost:11434@ollama.example.com (exported in this shell)"
            " — that endpoint is not on this machine") in error_lines(result.stderr)
    assert not (root / ".env").exists()
    assert invoked(records) == []


@mac_only
def test_an_uppercase_loopback_host_is_this_machine(sandbox):
    """A host name is case-insensitive. LOCALHOST was refused as if it named
    somebody else's machine, which is the wrong half of the gate to fail."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", OLLAMA_URL="http://LOCALHOST:11434")
    assert result.returncode == 0, result.stderr
    assert "LLM_BACKEND=ollama" in (root / ".env").read_text()


@mac_only
def test_an_ollama_url_without_a_scheme_is_refused_by_name(sandbox):
    """config.py uses the value as it stands, so "localhost:11434" becomes the
    base URL "localhost:11434/v1" — not an address anything can call. It reads
    like the loopback spelling it is not, so it is named here instead of
    arriving eleven steps later as a configuration mismatch."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", OLLAMA_URL="localhost:11434")
    assert result.returncode == 2, result.stdout
    assert ("OLLAMA_URL=localhost:11434 has no scheme, and config.py uses the value as it"
            in error_lines(result.stderr))
    assert not (root / ".env").exists()
    assert invoked(records) == []


@mac_only
def test_an_exported_blank_is_not_an_absent_variable(sandbox):
    """python-dotenv skips a name that is already in the environment, an empty
    value included, so an exported LLM_BACKEND= hides the ollama line this script
    writes — and config.py._env reads that blank as the hosted default. The guard
    read the blank as "nothing exported here" and let the run through."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", LLM_BACKEND="")
    assert result.returncode == 2, result.stdout
    assert ("LLM_BACKEND=openrouter (exported empty in this shell, which config.py reads as "
            "the default) — the answering model would run on OpenRouter, not on Ollama"
            ) in error_lines(result.stderr)
    assert "unset LLM_BACKEND" in error_lines(result.stderr)
    assert not (root / ".env").exists()
    assert invoked(records) == []


@mac_only
def test_an_empty_env_is_a_resolution_and_is_judged_as_one(sandbox):
    """An empty .env is not an unreadable .env.example. Step 10 never overwrites
    a file that exists, and config.py resolves every name in an empty one to its
    own default — which is the hosted backend. The guard skipped the judgement
    whenever the text was empty, so this run said fully local and answered on
    OpenRouter."""
    root, records, _ = sandbox
    (root / ".env").write_text("")
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 2, result.stdout
    assert ("LLM_BACKEND=openrouter (the default in config.py) — the answering model would "
            "run on OpenRouter, not on Ollama") in error_lines(result.stderr)
    assert invoked(records) == []


@mac_only
def test_a_conflict_that_came_from_the_env_says_where_it_came_from(sandbox):
    """Nothing is exported here: the .env itself selects the local backend and a
    hosted embedder. The refusal explained that an exported variable wins over
    the file, which described neither the source nor the fix."""
    root, records, _ = sandbox
    (root / ".env").write_text("LLM_BACKEND=ollama\nEMBED_BACKEND=openrouter\n")
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 2, result.stdout
    lines = error_lines(result.stderr)
    assert ("EMBED_BACKEND=openrouter (the .env already in this clone) — every passage would "
            "be embedded by OpenRouter") in lines
    assert "nothing in this shell exports these — each line above names where its" in lines
    assert not any("wins over every line this script writes" in line for line in lines)
    assert invoked(records) == []


@mac_only
def test_hosted_mode_warns_when_the_embedder_endpoint_is_off_this_machine(sandbox):
    """--hosted moves the answering model and nothing else: the .env it writes
    keeps EMBED_BACKEND=ollama, so OLLAMA_URL is where every passage of the
    library is embedded. Off this machine, that is the whole library leaving it
    — a consequence the flag never asked for, and its own line."""
    result = real_run(sandbox, "--no-demo", "--hosted",
                      OLLAMA_URL="http://ollama.example.com")
    assert result.returncode == 0, result.stderr
    printed = printed_lines(result.stdout)
    assert ("warning: EMBED_BACKEND=ollama with OLLAMA_URL=http://ollama.example.com, which is"
            in printed)
    assert ("not on this machine — every passage of your library would be sent there to be"
            in printed)


@mac_only
def test_a_non_loopback_ollama_host_is_refused_even_when_a_server_answers(sandbox):
    """OLLAMA_HOST is read twice by ollama: a server started here binds it, and
    the CLI reads it as the address of the server it talks to — so it is also
    where step 8's `ollama pull` goes. The gate sat inside the branch that starts
    a server, so with one already answering the run pulled its models onto
    whatever machine the variable named."""
    _, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", OLLAMA_HOST="ollama.example.com:11434")
    assert result.returncode == 1, result.stdout
    assert ("OLLAMA_HOST=ollama.example.com:11434 is not one of the loopback forms this "
            "script will") in error_lines(result.stderr)
    assert invoked(records) == [], "a tool ran past the gate"


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


def run_preflight(expected, tmp_path, mode="", **environment):
    """The snippet in a fresh interpreter that has an OpenRouter key and no
    index: the key half of check_environment passes and no Ollama is contacted,
    so the missing index is the only problem — the condition being classified.
    `mode` is the second argument the script passes: the mode the effective
    resolver settled on, which the loaded configuration is then held to.
    `environment` is applied last, so a test that describes a different backend
    or an absent key overrides the four defaults below instead of colliding
    with them."""
    env = {k: v for k, v in os.environ.items() if k not in SCRUBBED}
    env["PYTHONPATH"] = str(REPO)
    env.update({"LLM_BACKEND": "openrouter", "EMBED_BACKEND": "openrouter",
                "OPENROUTER_API_KEY": "not-a-real-key",
                "LIBRARY_DB_PATH": str(tmp_path / "nothing-here"), **environment})
    return subprocess.run([sys.executable, "-c", preflight_snippet(), expected, mode],
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


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_reports_the_configuration_the_loader_resolves(tmp_path):
    """The last word belongs to the loader, not to the file the script wrote: a
    .env rewrite is no fix while the same shell exports something else. A local
    run whose loaded configuration is hosted ends at exit 6, with the values
    that decided it named."""
    result = run_preflight("no-index", tmp_path, mode="local", LANGSMITH_TRACING_V2="true")
    assert result.returncode == 6, result.stdout + result.stderr
    assert "LLM_BACKEND=openrouter, EMBED_BACKEND=openrouter" in result.stdout
    # The endpoint line whole, not a search for the host inside the output: a
    # substring test against a URL is the shape of an allow-list check and is
    # not one, and here the pair of endpoints is the whole point of the line.
    assert ("LLM_BASE_URL=https://openrouter.ai/api/v1, OLLAMA_URL=http://localhost:11434"
            in printed_lines(result.stdout))
    assert "tracing: LANGSMITH_TRACING_V2" in result.stdout
    assert "not the fully local one" in result.stdout
    for named in ("LLM_BACKEND=openrouter", "EMBED_BACKEND=openrouter", "LANGSMITH_TRACING_V2"):
        assert named in result.stdout.split("not the fully local one")[1]


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_prints_the_configuration_it_agrees_with(tmp_path):
    """The same environment under the hosted mode is the mode that run set up:
    the configuration is still printed, and the run goes on to the ordinary
    classification of what it knowingly left behind."""
    result = run_preflight("no-index", tmp_path, mode="hosted")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "LLM_BACKEND=openrouter, EMBED_BACKEND=openrouter" in result.stdout
    assert ("LLM_BASE_URL=https://openrouter.ai/api/v1, OLLAMA_URL=http://localhost:11434"
            in printed_lines(result.stdout))
    assert "tracing: off" in printed_lines(result.stdout)


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_runs_the_tracing_switch_the_application_runs(tmp_path):
    """The five flags are not the whole rule. build_graph calls
    enable_tracing_if_key_present(), which turns a LANGCHAIN_API_KEY with no
    LANGCHAIN_TRACING_V2 set into LANGCHAIN_TRACING_V2=true — so reading the
    environment without running it reported "off" for a run that traces. The
    snippet runs the same function, and then names the destination; and with the
    name set to false, the key decides nothing."""
    result = run_preflight("no-index", tmp_path, mode="local",
                           LANGCHAIN_API_KEY="lsv2-not-a-real-key")
    assert result.returncode == 6, result.stdout + result.stderr
    assert ("tracing: LANGCHAIN_TRACING_V2 -> https://api.smith.langchain.com "
            "(the LangSmith default)") in printed_lines(result.stdout)
    assert "LANGCHAIN_TRACING_V2" in result.stdout.split("not the fully local one")[1]
    assert "lsv2-not-a-real-key" not in result.stdout + result.stderr

    result = run_preflight("no-index", tmp_path, mode="hosted",
                           LANGCHAIN_API_KEY="lsv2-not-a-real-key",
                           LANGCHAIN_TRACING_V2="false")
    assert result.returncode == 3, result.stdout + result.stderr
    assert "tracing: off" in printed_lines(result.stdout)


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
@pytest.mark.parametrize("name", ["LANGCHAIN_TRACING", "LANGCHAIN_HANDLER"])
def test_the_preflight_snippet_reads_the_v1_names_as_langchain_core_does(tmp_path, name):
    """The app-level truth, checked where the run ends. `off` is not an off value
    for langchain_core: env_var_is_set counts every value but "", "0", "false"
    and "False" as set, and a set v1 name with v2 tracing off makes
    CallbackManager.configure() raise RuntimeError on the first model call. The
    snippet read all five names through one list of spellings, printed
    "tracing: off" and let the run finish. It now imports env_var_is_set — the
    function langchain_core itself calls — rather than keeping a copy of the rule
    that could drift from it."""
    result = run_preflight("no-index", tmp_path, mode="local", LLM_BACKEND="ollama",
                           EMBED_BACKEND="ollama", **{name: "off"})
    assert result.returncode == 6, result.stdout + result.stderr
    printed = printed_lines(result.stdout)
    assert "tracing: off" in printed             # the v2 reading, still true
    assert (f"tracing (v1): {name} is set as langchain_core reads it — the first model "
            "call raises RuntimeError unless v2 tracing is on") in printed
    assert name in result.stdout.split("not the fully local one")[1]


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
@pytest.mark.parametrize("off", ["", "0", "false", "False"])
def test_the_preflight_snippet_keeps_the_v1_off_values_off(tmp_path, off):
    """The four values env_var_is_set does read as off, so the check is not the
    blunt one that would end every run carrying a LANGCHAIN_TRACING=false.

    What is asserted is the mode check, not the exit code: a local run's
    classification is `check_environment()`'s, which contacts Ollama, and there
    is none on a CI runner. So this pins that the run does NOT end at the mode
    mismatch and that the v1 line is not printed — the two things these four
    values decide — and leaves the classification to the tests that describe
    it."""
    result = run_preflight("no-index", tmp_path, mode="local", LLM_BACKEND="ollama",
                           EMBED_BACKEND="ollama", LANGCHAIN_TRACING=off,
                           LANGCHAIN_HANDLER=off)
    assert result.returncode != 6, result.stdout + result.stderr
    assert "not the fully local one" not in result.stdout
    assert "tracing: off" in printed_lines(result.stdout)
    assert "tracing (v1)" not in result.stdout


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_reports_a_v1_name_in_the_hosted_mode_too(tmp_path):
    """The hosted mode does not refuse a configuration it was asked for, so the
    v1 name is reported there rather than ending the run — as the RuntimeError it
    is, not as an upload."""
    result = run_preflight("no-index", tmp_path, mode="hosted", LANGCHAIN_HANDLER="off")
    assert result.returncode == 3, result.stdout + result.stderr
    assert ("tracing (v1): LANGCHAIN_HANDLER is set as langchain_core reads it — the "
            "first model call raises RuntimeError unless v2 tracing is on"
            ) in printed_lines(result.stdout)


def test_help_lists_every_flag(tmp_path):
    # Parsed before the platform and repository checks, so it answers anywhere.
    result = subprocess.run([BASH, str(SCRIPT), "--help"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0
    for flag in ("--dry-run", "--yes", "--no-demo", "--hosted", "--print-env-resolution",
                 "--help"):
        assert flag in result.stdout


def test_unknown_flag_is_a_usage_error(tmp_path):
    result = subprocess.run([BASH, str(SCRIPT), "--nope"], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "unknown option: --nope" in result.stderr


# --- reading .env the way the application reads it ---------------------------
# config.py loads .env with python-dotenv. The script has to read the same file
# the same way, and it cannot use python-dotenv to do it: the guard runs before
# uv exists, which is the point of it running before uv exists. So the parser is
# written out in bash, and these tests are what holds it to the library —
# `--print-env-resolution` dumps how the script read the file, and the real
# dotenv_values() (this suite runs under `uv run`, so it is the locked one) says
# what the application would read.
SUPPORTED_FORMS = """\
# a comment line, and a blank one below

PLAIN=value
export EXPORTED=value
  INDENTED=value
SPACED = value
EMPTY=
INLINE_COMMENT=value # this is a comment
HASH_NO_SPACE=val#ue
TRAILING_SPACES=value\x20\x20\x20
DOUBLE="a quoted value"
SINGLE='a quoted value'
DOUBLE_KEPT_SPACES="  kept  "
DOUBLE_ESCAPED_QUOTE="say \\"hi\\""
DOUBLE_NEWLINE="line one\\nline two"
DOUBLE_TAB="a\\tb"
DOUBLE_BACKSLASH="a\\\\b"
DOUBLE_HASH="a#b"
DOUBLE_THEN_COMMENT="value" # comment after the quote
SINGLE_ESCAPED_QUOTE='it\\'s here'
SINGLE_BACKSLASH='a\\\\b'
SINGLE_NO_ESCAPE='a\\nb'
BARE_DOLLAR=$HOME/books
UNQUOTED_BACKSLASH=a\\b
LAST_WINS=first
LAST_WINS=second
"""

# What is refused, and the reason the refusal has to name. Each is a form
# python-dotenv accepts (or silently drops) and this parser will not guess at:
# reading it differently from the application is how a "fully local" install
# ends up embedding the library somewhere else. The first five are whitespace:
# python-dotenv's parser is Python's own \s class, which is every one of these
# as well as the space and tab the shell reading handles, and reproducing that
# class in bash means classifying UTF-8 by hand in whatever locale the run
# inherits. They are refused by line number wherever on the line they appear.
REFUSED_FORMS = [
    ("BAD=x\fy\n", "a form feed (U+000C)"),
    ("BAD=x\vy\n", "a vertical tab (U+000B)"),
    ("BAD=x\u00a0y\n", "a non-breaking space (U+00A0)"),
    ("BAD=x\u2028y\n", "a line separator (U+2028)"),
    ("BAD=x\u3000y\n", "an ideographic space (U+3000)"),
    ('BAD="oops\n', "the \" quote is never closed on this line"),
    ('BAD="line one\nline two"\n', "the \" quote is never closed on this line"),
    ("BAD='oops\n", "the ' quote is never closed on this line"),
    ("BAD=${HOME}/x\n", "a ${...} interpolation, which python-dotenv expands"),
    ('BAD="${HOME}/x"\n', "a ${...} interpolation, which python-dotenv expands"),
    ("BADLINE\n", "no = on the line"),
    ('BAD="x" trailing\n', "text after the closing quote that is not a comment"),
    ("BAD-NAME=x\n", '"BAD-NAME" is not a plain NAME'),
]


def env_resolution(sandbox):
    """How the script reads the .env in the clone: one record per name, in the
    order the file defines them, with the value unescaped again."""
    root, _, env = sandbox
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--print-env-resolution"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    resolved = {}
    order = []
    for line in result.stdout.splitlines():
        if not line.startswith("env-resolution\t"):
            continue
        _, name, escaped = line.split("\t", 2)
        undone, index = "", 0
        while index < len(escaped):
            if escaped[index] == "\\":
                undone += {"n": "\n", "r": "\r", "t": "\t", "\\": "\\"}[escaped[index + 1]]
                index += 2
            else:
                undone += escaped[index]
                index += 1
        resolved[name] = undone
        order.append(name)
    return resolved, order


# --- and never printing what it read -----------------------------------------
# `--print-env-resolution` printed every value verbatim, and a .env is where the
# keys live: a stub run of it reproduced OPENROUTER_API_KEY, LANGCHAIN_API_KEY
# and CHAINLIT_PASSWORD on stdout, from the flag whose whole audience is people
# pasting its output into a bug report. The names below are the ones the script
# redacts, by the shape of the name rather than by a list of the ones this
# project happens to use. Written out here rather than parsed out of the script,
# so a change to either list has to be made deliberately in both.
SECRET_SUFFIXES = ("_API_KEY", "_KEY", "_TOKEN", "_SECRET", "_PASS")
# Realistic names, and values that are visibly not keys: the shape of the NAME is
# what the redaction reads, and a fixture written in a provider's real key format
# is a secret-scanner finding in this repository's own history for nothing.
SECRET_VALUES = {
    "OPENROUTER_API_KEY": "not-a-real-openrouter-key",
    "LANGCHAIN_API_KEY": "lsv2-not-a-real-langchain-key",
    "LANGSMITH_API_KEY": "lsv2-not-a-real-langsmith-key-either",
    "CHAINLIT_PASSWORD": "not-the-real-one-either",
    "CHAINLIT_AUTH_SECRET": "not-a-real-auth-secret",
    "HF_TOKEN": "not-a-real-hugging-face-token",
    "DB_PASS": "not-a-real-database-password",
}
# ... beside the names that only look like them. MAX_OUTPUT_TOKENS is a number,
# not a token, and it ships in .env.example.
SECRET_FORMS = "".join(f"{name}={value}\n" for name, value in SECRET_VALUES.items()) + """\
EMPTY_API_KEY=
LLM_BACKEND=ollama
EMBED_BACKEND=ollama
LANGCHAIN_TRACING_V2=false
MAX_OUTPUT_TOKENS=2048
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
"""


def is_secret_name(name):
    """The rule scripts/install-mac.sh redacts by (is_secret_name there)."""
    upper = name.upper()
    return "PASSWORD" in upper or upper.endswith(SECRET_SUFFIXES)


@mac_only
def test_the_env_resolution_never_prints_a_credential(sandbox):
    """Every value in the file, and not one of the secrets in either stream. The
    record still says whether the name is set and how long the value is — which
    is what an argument about how the file was read turns on — and the values
    that are not credentials are printed as they were read."""
    root, _, env = sandbox
    (root / ".env").write_text(SECRET_FORMS, encoding="utf-8")
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--print-env-resolution"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    for name, value in SECRET_VALUES.items():
        assert value not in result.stdout, f"{name} was printed to stdout"
        assert value not in result.stderr, f"{name} was printed to stderr"
    printed = result.stdout.splitlines()
    for name in ("OPENROUTER_API_KEY", "CHAINLIT_PASSWORD", "DB_PASS", "HF_TOKEN",
                 "CHAINLIT_AUTH_SECRET"):
        assert (f"env-resolution\t{name}\t<set, {len(SECRET_VALUES[name])} chars>"
                in printed), name
    assert "env-resolution\tEMPTY_API_KEY\t" in printed        # set to nothing stays that
    # The names that are not credentials, printed as the parser read them.
    assert "env-resolution\tMAX_OUTPUT_TOKENS\t2048" in printed
    assert "env-resolution\tLLM_BACKEND\tollama" in printed


@mac_only
def test_a_credential_in_the_env_reaches_neither_stream_of_a_whole_run(sandbox):
    """Not only the debug flag: the same .env through all twelve steps, with the
    guard's own summary lines among them."""
    root, _, _ = sandbox
    (root / ".env").write_text(SECRET_FORMS, encoding="utf-8")
    reaches_the_start_path(sandbox)
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 0, result.stderr
    for name, value in SECRET_VALUES.items():
        assert value not in result.stdout + result.stderr, f"{name} was printed"


@mac_only
def test_the_redacted_resolution_still_agrees_with_python_dotenv(sandbox):
    """The equivalence proof survives the redaction: same names, same order,
    same values for everything that is not a credential — and for the ones that
    are, both sides agree on whether the name is set, and the record's character
    count is the length of the value the library read."""
    from dotenv import dotenv_values

    root, _, _ = sandbox
    (root / ".env").write_text(SECRET_FORMS, encoding="utf-8")
    resolved, order = env_resolution(sandbox)
    real = dotenv_values(root / ".env")
    assert order == list(real)
    for name, value in real.items():
        if not is_secret_name(name):
            assert resolved[name] == value, name
        elif value:
            assert resolved[name] == f"<set, {len(value)} chars>", name
        else:
            assert resolved[name] == "", name
    assert [name for name in real if is_secret_name(name)] == [
        *SECRET_VALUES, "EMPTY_API_KEY"], "the file stopped covering the redacted shapes"


@mac_only
def test_the_env_parser_reads_every_supported_form_as_python_dotenv_does(sandbox):
    """The equivalence proof. One .env carrying every form the parser claims to
    support — quotes of both kinds and the escapes inside them, an inline
    comment, an `export ` prefix, whitespace around the `=`, a bare $HOME that
    dotenv does NOT interpolate, a name defined twice — read by the script and
    by the library, compared value for value and in order.

    The parser this replaces was `sed -n "s/^NAME=//p"`: LLM_BACKEND="ollama"
    came back WITH its quotes, so the run classified itself as hosted, skipped
    the fully local guard entirely and let EMBED_BACKEND="openrouter" through,
    while python-dotenv read the very same file as a local answering model with
    every passage of the library embedded on OpenRouter."""
    from dotenv import dotenv_values

    root, _, _ = sandbox
    (root / ".env").write_text(SUPPORTED_FORMS, encoding="utf-8")
    resolved, order = env_resolution(sandbox)
    real = dotenv_values(root / ".env")
    assert order == list(real)
    assert resolved == dict(real)
    # And not a vacuous pass: the forms that used to be read wrong are in there.
    assert resolved["DOUBLE"] == "a quoted value"
    assert resolved["DOUBLE_NEWLINE"] == "line one\nline two"
    assert resolved["LAST_WINS"] == "second"


# Where the difference between the two whitespace classes actually decides a
# run: python-dotenv strips a comment on any of these, so LLM_BACKEND is
# "ollama" and the fully local guard applies to the whole file. The shell
# reading kept the character in the value, LLM_BACKEND never equalled "ollama",
# the run classified itself as hosted, and EMBED_BACKEND=openrouter on the next
# line went through — the whole library embedded off the machine by a run whose
# banner said "fully local".
WHITESPACE_BEFORE_A_COMMENT = [("\f", "a form feed (U+000C)"),
                               ("\v", "a vertical tab (U+000B)"),
                               ("\u00a0", "a non-breaking space (U+00A0)")]


@mac_only
@pytest.mark.parametrize("char,reason", WHITESPACE_BEFORE_A_COMMENT,
                         ids=[reason[-7:-1] for _, reason in WHITESPACE_BEFORE_A_COMMENT])
def test_whitespace_this_parser_cannot_classify_stops_the_run(sandbox, char, reason):
    from dotenv import dotenv_values

    root, records, _ = sandbox
    (root / ".env").write_text(f"LLM_BACKEND=ollama{char}# local\nEMBED_BACKEND=openrouter\n",
                               encoding="utf-8")
    # The half that makes it a security question and not a formatting one.
    assert dotenv_values(root / ".env")["LLM_BACKEND"] == "ollama"
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 2, result.stdout
    assert f"the .env already in this clone, line 1: {reason}" in " ".join(
        error_lines(result.stderr))
    assert invoked(records) == []
    assert not any("warning: EMBED_BACKEND" in line for line in printed_lines(result.stdout)), (
        "the run classified itself as hosted instead of refusing the line")


@mac_only
@pytest.mark.parametrize("text,reason", REFUSED_FORMS,
                         ids=[reason[:28] for _, reason in REFUSED_FORMS])
def test_an_env_line_outside_the_supported_subset_stops_the_run(sandbox, text, reason):
    """Fail closed, by line number, before anything is installed. The subset is
    what this parser can promise to read exactly as python-dotenv does; outside
    it the two readings differ, and the difference decides where the data goes,
    so neither is safe to assume."""
    root, records, _ = sandbox
    (root / ".env").write_text("GOOD=1\n" + text, encoding="utf-8")
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 2, result.stdout
    assert f"the .env already in this clone, line 2: {reason}" in " ".join(
        error_lines(result.stderr))
    assert invoked(records) == []


@mac_only
@pytest.mark.parametrize("text,conflict", [
    ('LLM_BACKEND="ollama"\nEMBED_BACKEND="openrouter"\n', "EMBED_BACKEND=openrouter"),
    ("LLM_BACKEND='ollama'\nEMBED_BACKEND='openrouter'\n", "EMBED_BACKEND=openrouter"),
    ("export LLM_BACKEND=ollama\nexport EMBED_BACKEND=openrouter\n", "EMBED_BACKEND=openrouter"),
    ("LLM_BACKEND = ollama\nEMBED_BACKEND = openrouter\n", "EMBED_BACKEND=openrouter"),
    ("LLM_BACKEND=ollama # local\nEMBED_BACKEND=openrouter # hosted\n",
     "EMBED_BACKEND=openrouter"),
    ('LLM_BACKEND=ollama\nOLLAMA_URL="http://ollama.example.com"\n',
     "OLLAMA_URL=http://ollama.example.com"),
    ('LLM_BACKEND=ollama\nLANGSMITH_TRACING_V2="true"\n', "LANGSMITH_TRACING_V2=true"),
])
def test_a_quoted_or_decorated_env_is_judged_by_its_value(sandbox, text, conflict):
    """Every one of these files selects the local answering model and then
    contradicts it, and every one of them walked through: the quotes, the
    `export `, the spaces around the `=` and the trailing comment all stayed in
    the value, so LLM_BACKEND never equalled "ollama" and the guard was never
    applied to the rest of the file."""
    root, records, _ = sandbox
    (root / ".env").write_text(text, encoding="utf-8")
    result = real_run(sandbox, "--no-demo")
    assert result.returncode == 2, result.stdout
    assert any(line.startswith(conflict + " (the .env already in this clone)")
               for line in error_lines(result.stderr)), error_lines(result.stderr)
    assert invoked(records) == []


# --- the guard runs before anything is installed -----------------------------
@mac_only
def test_the_guard_refuses_before_brew_would_install_uv(sandbox, tmp_path):
    """The fail-closed resolution used to sit after steps 5 and 6, where `brew
    install uv` and `uv python install` download and write. On a PATH with no uv
    — a fresh Mac, which is this script's whole audience — the run that was
    about to be refused had already installed a package manager's worth of
    software. Nothing between step 2 and the guard needs a tool: it reads
    pyproject.toml, config.py and .env.example, and those are files."""
    root, records, env = sandbox
    bindir = tmp_path / "no-uv-bin"
    bindir.mkdir()
    for name in ("brew", "ollama", "curl"):          # every recorder except uv
        stub = bindir / name
        stub.write_text(f'#!/bin/sh\necho "$@" >> "{records}/{name}"\nexit 0\n')
        stub.chmod(0o755)
    env = {**env, "PATH": os.pathsep.join([str(bindir), "/usr/bin", "/bin"]),
           **HOSTED_SHELL}
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--no-demo"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout
    assert "[3/12] Homebrew" not in result.stdout          # it never got that far
    assert invoked(records) == []
    assert not (root / ".env").exists()


@mac_only
def test_the_ollama_host_gate_refuses_before_brew_would_install_uv(sandbox, tmp_path):
    """The same for OLLAMA_HOST, which stood in step 7 instead: on a PATH with no
    uv — a fresh Mac — `brew install uv` and `uv python install` had already run
    by the time the run was refused for a variable that points a server, and an
    `ollama pull`, at somebody else's machine. It reads one exported variable and
    needs no tool, so it is judged with the rest of the resolution."""
    root, records, env = sandbox
    bindir = tmp_path / "no-uv-bin"
    bindir.mkdir()
    for name in ("brew", "ollama", "curl"):          # every recorder except uv
        stub = bindir / name
        stub.write_text(f'#!/bin/sh\necho "$@" >> "{records}/{name}"\nexit 0\n')
        stub.chmod(0o755)
    env = {**env, "PATH": os.pathsep.join([str(bindir), "/usr/bin", "/bin"]),
           "OLLAMA_HOST": "ollama.example.com:11434"}
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--no-demo"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout
    assert "[3/12] Homebrew" not in result.stdout          # it never got that far
    assert invoked(records) == []
    assert not (root / ".env").exists()


@mac_only
def test_a_missing_uv_is_installed_when_the_guard_lets_the_run_through(sandbox, tmp_path):
    """The other half, so the test above is not passing on a script that simply
    stopped installing uv: with nothing exported, the same PATH gets uv."""
    root, records, env = sandbox
    bindir = tmp_path / "no-uv-bin"
    bindir.mkdir()
    for name in ("brew", "ollama", "curl"):
        stub = bindir / name
        stub.write_text(f'#!/bin/sh\necho "$@" >> "{records}/{name}"\nexit 0\n')
        stub.chmod(0o755)
    env = {**env, "PATH": os.pathsep.join([str(bindir), "/usr/bin", "/bin"])}
    result = subprocess.run([BASH, "scripts/install-mac.sh", "--dry-run", "--no-demo"],
                            cwd=root, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "would run: brew install uv" in result.stdout
    assert invoked(records) == [], "a dry run invoked a tool"


# --- the five tracing flags, the two key names, the two endpoints ------------
# Two truth tables, not one. The three v2-only names are read by langsmith, which
# uploads on the exact string "true"; the two v1 names are read by
# langchain_core's env_var_is_set, whose only off values are "", "0", "false" and
# "False" — so LANGCHAIN_TRACING=off is SET, and a set v1 name with v2 tracing
# off makes CallbackManager.configure() raise RuntimeError on the first model
# call. LANGCHAIN_TRACING is in both lists: langsmith reads it as the fallback
# for TRACING_V2 and langchain_core as a v1 switch, so it has to pass both.
TRACING_V2_FLAGS = ["LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING"]
TRACING_V1_FLAGS = ["LANGCHAIN_TRACING", "LANGCHAIN_HANDLER"]
TRACING_FLAGS = TRACING_V2_FLAGS + TRACING_V1_FLAGS
# The spellings each side reads as off, and the ones that read as off and are not.
OFF_FOR_V2 = ["false", "0", "no", "off", "FALSE", "Off", ""]
OFF_FOR_V1 = ["false", "False", "0", ""]
ON_FOR_V1 = ["off", "no", "FALSE", "Off", "true", "1"]
V2_EFFECT = "prompts and answers would be uploaded as traces"
V1_EFFECT = ("the v1 names have only 0, false and False as off values, so this is tracing "
             "on: prompts and answers uploaded, or a RuntimeError on the first model call")


@mac_only
@pytest.mark.parametrize("flag", TRACING_FLAGS)
def test_every_tracing_flag_stops_the_fully_local_install(sandbox, flag):
    """langchain_core reads all five, under both prefixes and in the v1
    spellings, and any of them at a value that is not one of the spellings of
    off means prompts, retrieved passages and answers are uploaded. One test
    covered one flag; the other four were an assumption."""
    root, records, _ = sandbox
    effect = V1_EFFECT if flag in TRACING_V1_FLAGS else V2_EFFECT
    result = real_run(sandbox, "--no-demo", **{flag: "true"})
    assert result.returncode == 2, result.stdout
    assert f"{flag}=true (exported in this shell) — {effect}" in error_lines(result.stderr)
    assert invoked(records) == []
    assert not (root / ".env").exists()


@mac_only
@pytest.mark.parametrize("flag", TRACING_V2_FLAGS)
@pytest.mark.parametrize("off", OFF_FOR_V2)
def test_a_v2_tracing_flag_that_is_off_is_not_a_conflict(sandbox, flag, off):
    """The other half of the same rule, across every v2 name rather than one of
    them: these are the spellings langsmith reads as off, and a guard that
    refused them would refuse the .env this script writes itself."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", **{flag: off})
    assert result.returncode == 0, result.stderr
    assert "LLM_BACKEND=ollama" in (root / ".env").read_text()


@mac_only
@pytest.mark.parametrize("flag", TRACING_V1_FLAGS)
@pytest.mark.parametrize("off", OFF_FOR_V1)
def test_a_v1_tracing_name_at_its_own_off_values_is_not_a_conflict(sandbox, flag, off):
    """env_var_is_set has exactly four off values, and all four have to go
    through: a gate that refused `false` on the v1 names would refuse the way out
    it recommends."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", **{flag: off})
    assert result.returncode == 0, result.stderr
    assert "LLM_BACKEND=ollama" in (root / ".env").read_text()


@mac_only
@pytest.mark.parametrize("flag", TRACING_V1_FLAGS)
@pytest.mark.parametrize("value", ON_FOR_V1)
def test_a_v1_tracing_name_that_only_looks_off_stops_the_fully_local_install(sandbox, flag,
                                                                            value):
    """`LANGCHAIN_TRACING=off` is set as far as langchain_core is concerned, and
    a set v1 name with v2 tracing off raises RuntimeError inside
    CallbackManager.configure() on the first model call. One truth table for all
    five names accepted it, reported "tracing off", installed everything and left
    an application that could not answer a question."""
    root, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", **{flag: value})
    assert result.returncode == 2, result.stdout
    assert f"{flag}={value} (exported in this shell) — {V1_EFFECT}" in error_lines(result.stderr)
    assert any("every value but 0, false and False counts as" in line
               for line in error_lines(result.stderr)), "the rule is not named"
    assert invoked(records) == []
    assert not (root / ".env").exists()


@mac_only
@pytest.mark.parametrize("flag", TRACING_V1_FLAGS)
def test_hosted_mode_reports_a_v1_name_as_the_runtime_error_it_is(sandbox, flag):
    """The hosted mode reports rather than refuses — but not as an upload: a set
    v1 name with v2 tracing off sends nothing anywhere, it stops the first model
    call. `tracing is on: ... uploaded to <endpoint>` described the wrong
    consequence, and for LANGCHAIN_HANDLER it described one that cannot happen."""
    result = real_run(sandbox, "--no-demo", "--hosted", **{flag: "off"})
    assert result.returncode == 0, result.stderr
    printed = printed_lines(result.stdout)
    assert f"set as langchain_core reads it: {flag} — it counts every value but 0," in printed
    assert ("false and False as tracing on, so the first model call raises RuntimeError"
            in printed)
    assert not any(line.startswith("tracing is on:") for line in printed)


@mac_only
def test_the_langsmith_key_is_reported_and_does_not_decide_anything(sandbox):
    """Both key names are reported, because a reader who has one usually has the
    other — but only LANGCHAIN_API_KEY is judged: graph.py names that one, and
    no SDK starts tracing on a LANGSMITH_API_KEY with every flag off. Neither
    value is ever printed."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", LANGSMITH_API_KEY="lsv2-not-a-real-key")
    assert result.returncode == 0, result.stderr
    assert "LANGSMITH_API_KEY=<set> (exported in this shell)" in printed_lines(result.stdout)
    assert "lsv2-not-a-real-key" not in result.stdout + result.stderr
    assert "LLM_BACKEND=ollama" in (root / ".env").read_text()


@mac_only
@pytest.mark.parametrize("name", ["LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"])
def test_the_refusal_names_the_endpoint_the_traces_would_go_to(sandbox, name):
    """A destination, not a switch: the endpoint variables are never a conflict
    of their own, they are what the refusal has to name instead of the LangSmith
    default. Both prefixes are the same setting, and either one alone decides.

    The .env here is the one a reader writes by hand — .env.example with the
    local backend and its two tracing lines still commented out — because that
    is the state in which the key alone decides."""
    root, records, _ = sandbox
    (root / ".env").write_text(env_example_with_local_backend(root))
    result = real_run(sandbox, "--no-demo", LANGCHAIN_API_KEY="lsv2-not-a-real-key",
                      **{name: "https://eu.api.smith.langchain.com"})
    assert result.returncode == 2, result.stdout
    assert ("LANGCHAIN_API_KEY=<set> (exported in this shell) — a key with no "
            "LANGCHAIN_TRACING_V2 set turns tracing on by itself: prompts and answers "
            "would be uploaded to https://eu.api.smith.langchain.com"
            ) in error_lines(result.stderr)
    assert invoked(records) == []


@mac_only
@pytest.mark.parametrize("name", ["LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT"])
def test_hosted_mode_names_the_endpoint_where_tracing_is_only_reported(sandbox, name):
    """The hosted mode does not refuse tracing — it says where the second copy
    of the prompts and the retrieved passages is going."""
    result = real_run(sandbox, "--no-demo", "--hosted", LANGSMITH_TRACING_V2="true",
                      **{name: "https://eu.api.smith.langchain.com"})
    assert result.returncode == 0, result.stderr
    printed = printed_lines(result.stdout)
    assert "tracing is on: prompts, retrieved passages and answers are uploaded to" in printed
    # `.count(...) == 1` and not `in`: the destination gets a line of its own, so
    # the assertion is that exactly one printed line IS that URL. A bare URL
    # literal on the left of an `in` reads as a substring test on a URL wherever
    # it appears, which is the shape this file removed everywhere else.
    assert printed.count("https://eu.api.smith.langchain.com") == 1


# --- OLLAMA_HOST: the host, exactly ------------------------------------------
@mac_only
@pytest.mark.parametrize("bind", [
    "http://localhost:11434@ollama.example.com",   # userinfo, with a scheme
    "localhost:11434@ollama.example.com",          # ... and without one
    "[::1]:11434@ollama.example.com",
    "localhost.evil.com:11434",                    # loopback as a prefix of the host
    "127.0.0.1.evil.com",
    "localhost:notaport",                          # a port that is not a port
    "localhost/../x",                              # a path, so not an authority
    "ftp://localhost",                             # a scheme nothing serves on
])
def test_a_host_that_only_looks_like_loopback_is_refused(sandbox, bind):
    """The host of http://localhost:11434@ollama.example.com is
    ollama.example.com — everything in front of the @ is userinfo, and it is
    exactly the text a match on `localhost:*` reads as this machine. OLLAMA_HOST
    is where step 8's `ollama pull` goes, so that match sent this run's models to
    whatever machine the variable named. The authority is parsed and the host
    compared exactly; a bind address has no userinfo at all, so an @ in one is
    refused outright."""
    _, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", OLLAMA_HOST=bind)
    assert result.returncode == 1, result.stdout
    assert f"OLLAMA_HOST={bind}" in result.stderr
    assert invoked(records) == [], "the gate let a tool run past it"


@mac_only
@pytest.mark.parametrize("bind", ["LOCALHOST", "127.0.0.1", "::1", "[::1]",
                                  "http://LOCALHOST:11434", "HTTPS://localhost"])
def test_the_case_folded_loopback_spellings_still_pass(sandbox, bind):
    """A host name is case-insensitive, and the bracketless ::1 is the form a
    bind address takes. Refusing these would be the wrong half of the gate to
    fail: they are this machine."""
    _, records, _ = sandbox
    reaches_the_start_path(sandbox)
    result = real_run(sandbox, "--no-demo", OLLAMA_HOST=bind)
    assert result.returncode == 0, result.stderr
    assert "OLLAMA_HOST" not in result.stderr
    assert "services run ollama" in (records / "brew").read_text()


@mac_only
def test_a_userinfo_ollama_url_that_is_this_machine_is_not_refused(sandbox):
    """The URL reading is the one that HAS a userinfo production, so it is
    stripped there instead of refused: http://reader@localhost:11434 is this
    machine. Failing closed on the wrong half is still failing."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", OLLAMA_URL="http://reader@localhost:11434")
    assert result.returncode == 0, result.stderr
    assert "LLM_BACKEND=ollama" in (root / ".env").read_text()


# --- where the library is embedded -------------------------------------------
@mac_only
def test_hosted_mode_warns_when_the_embedder_is_openrouter(sandbox):
    """--hosted moves the ANSWERING model and nothing else. EMBED_BACKEND=
    openrouter sends every passage of the library to OpenRouter — not one
    question, the whole library — and it produced no warning at all, including
    for the exported combination this file's own HOSTED_SHELL describes: the
    run reported the variable two lines earlier as "reported only" and went on.
    The warning has to name the endpoint it resolves to."""
    result = real_run(sandbox, "--no-demo", "--hosted", **HOSTED_SHELL)
    assert result.returncode == 0, result.stderr
    printed = printed_lines(result.stdout)
    assert ("warning: EMBED_BACKEND=openrouter (exported in this shell), which is"
            in printed)
    assert "not on this machine — every passage of your library would be sent to" in printed
    assert printed.count("https://openrouter.ai/api/v1") == 1


@mac_only
def test_a_hosted_embedder_pulls_no_embedding_model(sandbox):
    """And the pull follows the same resolution: bge-m3 is 1.2 GB fetched for an
    embedder that is never going to be asked anything."""
    embed_model, _ = config_models()
    _, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", "--hosted", **HOSTED_SHELL)
    assert result.returncode == 0, result.stderr
    assert "no embedding model is pulled" in result.stdout
    assert not (records / "ollama").exists(), f"{embed_model} was pulled for nothing"


@mac_only
def test_the_local_mode_still_refuses_a_hosted_embedder_rather_than_warning(sandbox):
    """The warning belongs to the hosted mode only: under the fully local one
    the same value is a contradiction of the mode and is refused outright."""
    root, _, _ = sandbox
    result = real_run(sandbox, "--no-demo", EMBED_BACKEND="openrouter")
    assert result.returncode == 2, result.stdout
    assert ("EMBED_BACKEND=openrouter (exported in this shell) — every passage would be "
            "embedded by OpenRouter") in error_lines(result.stderr)
    assert not (root / ".env").exists()


# --- hosted and local, decided by one resolver -------------------------------
@mac_only
def test_hosted_with_an_exported_local_backend_pulls_the_answering_model(sandbox):
    """`--hosted LLM_BACKEND=ollama` is a local answering model: config.py reads
    .env without overriding what is exported, so the flag loses. The script read
    the flag for the pull and the environment for everything else, so it pulled
    no answering model, expected a key it does not need, and finished at "Done."
    with the first question about to ask Ollama for a model nothing fetched."""
    embed_model, llm_model = config_models()
    _, records, _ = sandbox
    result = real_run(sandbox, "--no-demo", "--hosted", LLM_BACKEND="ollama")
    assert result.returncode == 0, result.stderr
    pulled = (records / "ollama").read_text()
    assert f"pull {llm_model}" in pulled, "the answering model this run needs was skipped"
    assert f"pull {embed_model}" in pulled


@mac_only
def test_the_dry_run_plan_names_the_mode_the_loader_settles_on(sandbox):
    """The plan says which expectation step 12 will hold the loaded
    configuration to, and that is the resolver's answer, not the flag's."""
    out = dry_run(sandbox, "--hosted", "--no-demo")
    assert "it is not the hosted one this run set up" in out


# --- the preflight snippet, on the hosted half -------------------------------
@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_holds_a_hosted_run_to_its_backend(tmp_path):
    """The symmetric check, which did not exist: `if mode == "local"` and
    nothing else, so every hosted run ended in the ordinary classification
    however far the loaded configuration had drifted from it."""
    result = run_preflight("no-index", tmp_path, mode="hosted", LLM_BACKEND="ollama")
    assert result.returncode == 6, result.stdout + result.stderr
    assert "not the hosted one: LLM_BACKEND=ollama" in result.stdout


@pytest.mark.skipif(not have_package, reason="the package is not importable here")
def test_the_preflight_snippet_runs_the_tracing_hook_before_either_check(tmp_path):
    """Both expectations are judged after enable_tracing_if_key_present(), so a
    key that turns tracing on decides the local check the same way a flag would
    — and the hosted one still reports where the traces go."""
    result = run_preflight("no-index no-key", tmp_path, mode="hosted",
                           OPENROUTER_API_KEY="",
                           LANGCHAIN_API_KEY="lsv2-not-a-real-key")
    assert result.returncode == 5, result.stdout + result.stderr
    assert ("tracing: LANGCHAIN_TRACING_V2 -> https://api.smith.langchain.com "
            "(the LangSmith default)") in printed_lines(result.stdout)
    assert "lsv2-not-a-real-key" not in result.stdout + result.stderr
