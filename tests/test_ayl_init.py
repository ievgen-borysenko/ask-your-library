"""`ayl init`, the first run: each of its five steps, `--dry-run`, a second run
that changes nothing and says so, `--yes`, the mode, the opt-in demo library
kept apart from the reader's index, an index from before ADR-026, and
`--help` touching nothing.

Nothing here reaches a network or an Ollama: `/api/tags` is answered by a
fake `requests` on the preflight (the same seam tests/test_preflight.py uses),
a pull by a recorder, the demo build and the closing `ayl doctor` by
recorders standing where the two child processes would start. `AYL_HOME`,
the configuration files and the checkout are all under `tmp_path`.
"""
import os
import stat
import sys
from pathlib import Path

import lancedb
import pytest
import requests

from ask_your_library import ayl, config, home, init_cmd, ollama, preflight
from ask_your_library.i18n import t
from ask_your_library.ingest.ledger import open_ledger
from ask_your_library.ui import launcher
from conftest import REPO

ANSWERS, EMBEDS = "answers-model:7b", "embeds-model"
# The real pull, kept before any fixture replaces it with a recorder.
REAL_PULL = ollama.pull
SECRET = "s3cret-not-a-real-password"
CREDENTIAL_URL = f"http://reader:{SECRET}@localhost:11434"
STARTER = ["frankenstein", "meditations", "senecas-morals", "alice-in-wonderland",
           "hound-of-the-baskervilles", "study-in-scarlet"]


class Tags:
    """`requests` as `preflight.ollama_tags` uses it."""
    def __init__(self, names=(), down=False):
        self.names, self.down, self.calls = list(names), down, 0

    def get(self, url, timeout=None):
        self.calls += 1
        if self.down:
            raise requests.ConnectionError("refused")
        names = self.names

        class Reply:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"models": [{"name": name} for name in names]}
        return Reply()


class NotATerminal:
    def isatty(self):
        return False


class Machine:
    """One fresh machine: where everything is, and what each seam saw."""
    def __init__(self, tmp_path, monkeypatch):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.home = tmp_path / "home"
        self.clone = tmp_path / "clone"
        (self.clone / "corpus").mkdir(parents=True)
        (self.clone / "scripts").mkdir()
        (self.clone / "corpus" / "manifest.yaml").write_text(
            (REPO / "corpus" / "manifest.yaml").read_text(encoding="utf-8"), encoding="utf-8")
        (self.clone / "scripts" / "ingest_demo_corpus.py").write_text("# stand-in\n")
        self.pulls, self.builds, self.checks = [], [], []
        self.check_status = preflight.EXIT_NO_INDEX
        self.tags = Tags([f"{EMBEDS}:latest"])
        self.prompts = []

        mp = monkeypatch
        mp.setattr(config, "AYL_HOME", self.home)
        mp.setattr(config, "HOME_CONFIG", self.home / "config.env")
        mp.setattr(config, "PROJECT_ENV", None)
        mp.setattr(config, "EXPORTED", frozenset())
        mp.setattr(config, "LLM_BACKEND", "ollama")
        mp.setattr(config, "EMBED_BACKEND", "ollama")
        mp.setattr(config, "OLLAMA_URL", "http://localhost:11434")
        mp.setattr(config, "TABLES", config.tables_for("ollama"))
        choice = config.DbPathChoice(self.home / "index", 3, "the default under AYL_HOME")
        mp.setattr(config, "DB_CHOICE", choice)
        mp.setattr(config, "DB_PATH", choice.path)
        mp.setattr(preflight, "LLM_BACKEND", "ollama")
        mp.setattr(preflight, "EMBED_BACKEND", "ollama")
        mp.setattr(preflight, "ORCHESTRATOR_MODEL", ANSWERS)
        mp.setattr(preflight, "OLLAMA_LLM_MODEL", ANSWERS)
        mp.setattr(preflight, "OLLAMA_EMBED_MODEL", EMBEDS)
        mp.setattr(preflight, "requests", self.tags)
        mp.setattr(init_cmd, "REPO_ROOT", str(self.clone))
        mp.setattr(launcher, "REPO_ROOT", str(self.clone))
        mp.setattr(sys, "stdin", NotATerminal())

        def pull(model, on_progress=None, url=None):
            self.pulls.append(model)
            if on_progress:
                on_progress("success", None, None)
        mp.setattr(ollama, "pull", pull)

        def build(path, backend, full):
            self.builds.append((path, backend, full))
            demo_library(path, STARTER if not full else STARTER + ["moby-dick"])
            return 0
        mp.setattr(init_cmd, "build_demo", build)

        def check(db):
            self.checks.append(db)
            return self.check_status
        mp.setattr(init_cmd, "closing_check", check)

    def answer(self, reply):
        class Terminal:
            def isatty(self):
                return True
        self.mp.setattr(sys, "stdin", Terminal())

        def prompt(text=""):
            self.prompts.append(text)
            return reply
        self.mp.setattr("builtins.input", prompt)

    def configured(self):
        """What a second process would load: the file this run wrote exists."""
        return (self.home / "config.env").is_file()


@pytest.fixture
def machine(tmp_path, monkeypatch):
    return Machine(tmp_path, monkeypatch)


def demo_library(path: Path, notes, source="manifest"):
    """An index as the demo build leaves one: a transcripts table and a
    ledger row per book, every one indexed."""
    path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(path)
    db.create_table("transcripts_ollama", [{"chunk_id": "x", "text": "t"}], mode="overwrite")
    ledger = open_ledger(db)
    for note in notes:
        ref = f"{source}:{note}"
        book_id = ledger.resolve(note.title(), "Someone", source_ref=ref)
        ledger.begin(book_id, key=f"{note} — Someone", source_ref=ref, embedding_model="fake")
        ledger.commit(book_id, rows=1)


def init(*argv) -> int:
    return ayl.main(["init", *argv])


# --- --help and --dry-run touch nothing -------------------------------------------

def test_help_is_documentation_and_touches_nothing(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("an environment seam was touched for --help")
    for owner, name in ((preflight, "ollama_tags"), (ollama, "pull"), (home, "write_private"),
                        (init_cmd, "closing_check"), (init_cmd, "build_demo")):
        monkeypatch.setattr(owner, name, forbidden)
    with pytest.raises(SystemExit) as raised:
        init("--help")
    assert raised.value.code == 0
    out = capsys.readouterr().out
    for flag in ("--mode", "--demo", "--no-demo", "--full", "--yes", "--dry-run",
                 "--print-env-resolution"):
        assert flag in out


def test_ayl_help_lists_init(capsys):
    with pytest.raises(SystemExit):
        ayl.main(["--help"])
    assert "init" in capsys.readouterr().out


def test_dry_run_prints_every_step_in_order_and_changes_nothing(machine, capsys):
    assert init("--dry-run", "--demo") == 0
    out = capsys.readouterr().out
    order = [out.index(f"[{n}/5]") for n in range(1, 6)]
    assert order == sorted(order)
    assert f"would ask http://localhost:11434/api/tags" in out
    assert f"would pull {ANSWERS}" in out and f"would pull {EMBEDS}" in out
    assert f"would write {machine.home / 'config.env'}" in out and "LLM_BACKEND=ollama" in out
    assert "scripts/ingest_demo_corpus.py --starter --backend ollama" in out
    assert str(machine.home / "demo" / "index") in out
    assert "Nothing was pulled, written or built" in out
    assert machine.tags.calls == 0, "no request to Ollama"
    assert not machine.home.exists(), "nothing written, not even the folder"
    assert machine.pulls == machine.builds == machine.checks == []


# --- the five steps -----------------------------------------------------------------

def test_a_first_run_pulls_what_is_missing_and_writes_the_local_configuration(machine, capsys):
    assert init() == 0
    out = capsys.readouterr().out
    assert machine.pulls == [ANSWERS], "the embedder was already pulled, as name:latest"
    assert f"{EMBEDS}: already pulled" in out
    written = (machine.home / "config.env").read_text(encoding="utf-8")
    for line in ("LLM_BACKEND=ollama", "EMBED_BACKEND=ollama", "LLM_TIMEOUT_S=600",
                 "QUESTION_DEADLINE_S=1200", "LANGSMITH_TRACING_V2=false"):
        assert f"\n{line}\n" in written
    assert "LIBRARY_DB_PATH=" not in written.replace("# Unset LIBRARY_DB_PATH", "")
    assert stat.S_IMODE(os.stat(machine.home / "config.env").st_mode) == 0o600
    assert machine.checks == [None], "the closing doctor reads the reader's own index"
    assert "Left to you: your index is empty until you add books" in out
    assert "ayl add ~/books" in out and "demo library: not built" in out
    assert machine.builds == []


def test_a_second_run_changes_nothing_and_says_so(machine, capsys):
    assert init() == 0
    machine.tags.names.append(ANSWERS)
    machine.mp.setattr(config, "HOME_CONFIG", machine.home / "config.env")
    before = (machine.home / "config.env").read_text(encoding="utf-8")
    machine.pulls.clear()
    capsys.readouterr()
    assert init() == 0
    out = capsys.readouterr().out
    assert machine.pulls == []
    assert f"{ANSWERS}: already pulled" in out and f"{EMBEDS}: already pulled" in out
    assert "exists and is never rewritten; nothing was changed" in out
    assert "Nothing to do: every step was already done" in out
    assert (machine.home / "config.env").read_text(encoding="utf-8") == before


def test_the_hosted_mode_pulls_only_the_embedder_and_leaves_the_key_to_the_reader(machine,
                                                                                  capsys):
    machine.check_status = preflight.EXIT_NO_KEY
    machine.tags.names.clear()
    assert init("--mode", "hosted") == 0
    out = capsys.readouterr().out
    assert machine.pulls == [EMBEDS]
    written = (machine.home / "config.env").read_text(encoding="utf-8")
    assert "\nLLM_BACKEND=openrouter\n" in written and "\nEMBED_BACKEND=ollama\n" in written
    assert "\nLLM_TIMEOUT_S=120\n" in written and "\nOPENROUTER_API_KEY=\n" in written
    assert "OPENROUTER_API_KEY is left empty on purpose" in out
    assert "Left to you: the hosted mode needs OPENROUTER_API_KEY" in out


def test_an_exported_switch_that_contradicts_the_mode_is_refused_before_anything(machine,
                                                                                capsys):
    machine.mp.setattr(config, "EXPORTED", frozenset({"LLM_BACKEND"}))
    machine.mp.setattr(config, "LLM_BACKEND", "openrouter")
    assert init() == 2
    assert "LLM_BACKEND=openrouter is exported" in capsys.readouterr().err
    assert machine.tags.calls == 0 and machine.pulls == [] and not machine.home.exists()


def test_an_existing_dotenv_decides_and_a_contrary_mode_flag_is_named_not_applied(machine,
                                                                                 capsys):
    dotenv = machine.tmp / "work" / ".env"
    dotenv.parent.mkdir()
    dotenv.write_text("LLM_BACKEND=ollama\n")
    machine.mp.setattr(config, "PROJECT_ENV", dotenv)
    assert init("--mode", "hosted") == 0
    out = capsys.readouterr().out
    assert f"read from {dotenv}" in out and "--mode hosted was NOT applied" in out
    assert machine.pulls == [ANSWERS], "the configuration that decides is the local one"
    assert not (machine.home / "config.env").exists()


def test_a_dotenv_that_sets_no_mode_switch_does_not_stop_the_config_file(machine, capsys):
    """A `.env` naming only an endpoint or a model chooses no mode: init still
    writes config.env, which that `.env` sits above."""
    dotenv = machine.tmp / "work" / ".env"
    dotenv.parent.mkdir()
    dotenv.write_text("OLLAMA_EMBED_MODEL=embeds-model\nLLM_BACKEND=\n")
    machine.mp.setattr(config, "PROJECT_ENV", dotenv)
    assert init() == 0
    assert (machine.home / "config.env").is_file()


def test_a_dotenv_outside_the_checkout_is_named_as_one(machine, capsys):
    dotenv = machine.tmp / "elsewhere" / ".env"
    dotenv.parent.mkdir()
    dotenv.write_text("LLM_BACKEND=ollama\n")
    machine.mp.setattr(config, "PROJECT_ENV", dotenv)
    init()
    assert f"read from {dotenv} (a .env outside this checkout)" in capsys.readouterr().out


def test_an_exported_hosted_embedder_gets_its_own_remedy(machine, capsys):
    """Choosing the other mode does not fix this one: both embed locally."""
    machine.mp.setattr(config, "EXPORTED", frozenset({"EMBED_BACKEND"}))
    machine.mp.setattr(config, "EMBED_BACKEND", "openrouter")
    assert init("--mode", "hosted") == 2
    err = capsys.readouterr().err
    assert "EMBED_BACKEND=openrouter is exported in this shell" in err
    assert "both modes `ayl init` writes embed on this machine" in err
    assert "--mode local" not in err


def test_an_exported_switch_is_named_as_the_source_over_an_existing_file(machine, capsys):
    dotenv = machine.tmp / "work" / ".env"
    dotenv.parent.mkdir()
    dotenv.write_text("LLM_BACKEND=ollama\nEMBED_BACKEND=ollama\n")
    machine.mp.setattr(config, "PROJECT_ENV", dotenv)
    machine.mp.setattr(config, "EXPORTED", frozenset({"LLM_BACKEND"}))
    init()
    assert ("LLM_BACKEND=ollama comes from a variable exported in this shell, which wins "
            "over that file") in capsys.readouterr().out


# --- the local mode is held to "nothing leaves this machine" -------------------------

@pytest.mark.parametrize("url, shown", [
    ("http://gpu-box.example.com:11434", "OLLAMA_URL=http://gpu-box.example.com:11434"),
    ("http://reader:hunter2@ollama.example.com:11434",
     "OLLAMA_URL=http://<credentials>@ollama.example.com:11434"),
])
def test_a_local_mode_with_a_remote_ollama_is_refused(machine, capsys, url, shown):
    machine.mp.setattr(config, "OLLAMA_URL", url)
    assert init() == 2
    err = capsys.readouterr().err
    assert shown in err and "is not this machine" in err and "hunter2" not in err
    assert machine.tags.calls == 0 and not machine.home.exists()


def test_a_tracing_flag_on_is_refused_in_the_local_mode(machine, monkeypatch, capsys):
    monkeypatch.setenv("LANGSMITH_TRACING_V2", "true")
    assert init() == 2
    assert "LANGSMITH_TRACING_V2=true" in capsys.readouterr().err


def test_a_v1_tracing_flag_langchain_counts_as_set_is_refused(machine, monkeypatch, capsys):
    monkeypatch.setenv("LANGCHAIN_HANDLER", "langchain")
    assert init() == 2
    assert "LANGCHAIN_HANDLER" in capsys.readouterr().err


def test_a_langsmith_key_alone_is_refused_only_when_no_file_turns_tracing_off(machine,
                                                                            monkeypatch,
                                                                            capsys):
    """The file this run writes sets LANGCHAIN_TRACING_V2=false; an existing
    configuration may not, and then the key alone turns tracing on."""
    monkeypatch.setenv("LANGCHAIN_API_KEY", "lsv2-not-a-real-key")
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    assert init() == 0, "written now: the file turns it off"
    machine.mp.setattr(config, "HOME_CONFIG", machine.home / "config.env")
    capsys.readouterr()
    assert init() == 2
    err = capsys.readouterr().err
    assert "LANGCHAIN_API_KEY" in err and "lsv2-not-a-real-key" not in err


def test_the_hosted_mode_is_not_held_to_the_local_rule(machine, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING_V2", "true")
    machine.check_status = preflight.EXIT_NO_KEY
    assert init("--mode", "hosted") == 0


def test_no_ollama_stops_at_step_1_with_exit_5_and_the_preflight_s_remedy(machine, capsys):
    machine.tags.down = True
    assert init() == preflight.EXIT_NO_LOCAL_RUNTIME
    err = capsys.readouterr().err
    assert t("pf_no_ollama", url="http://localhost:11434",
             pulls=f"`ollama pull {ANSWERS}`, `ollama pull {EMBEDS}`") in err
    assert machine.pulls == [] and not machine.home.exists()


def test_a_failed_pull_is_exit_5_and_writes_nothing(machine, capsys):
    def fails(model, on_progress=None, url=None):
        raise ollama.PullError(f"Ollama could not pull {model}: file does not exist")
    machine.mp.setattr(ollama, "pull", fails)
    assert init() == preflight.EXIT_NO_LOCAL_RUNTIME
    assert "file does not exist" in capsys.readouterr().err
    assert not (machine.home / "config.env").exists()


def test_an_interrupted_run_says_it_resumes(machine, capsys):
    def interrupted(model, on_progress=None, url=None):
        raise KeyboardInterrupt
    machine.mp.setattr(ollama, "pull", interrupted)
    assert init() == 130
    assert "Run `ayl init` again" in capsys.readouterr().err


def test_a_home_inside_a_git_work_tree_is_refused_for_the_configuration(machine, capsys):
    (machine.tmp / ".git").mkdir()
    assert init() == preflight.EXIT_NOT_READY
    assert "inside the git work tree" in capsys.readouterr().err
    assert not (machine.home / "config.env").exists()


# --- the demo library: opt-in, and apart from the reader's index -------------------

def test_demo_builds_the_starter_subset_into_its_own_index(machine, capsys):
    machine.check_status = 0
    assert init("--demo") == 0
    demo = machine.home / "demo" / "index"
    assert machine.builds == [(demo, "ollama", False)]
    assert machine.checks == [demo], "the closing doctor reads the demo library"
    assert not (machine.home / "index").exists(), "the reader's own index is untouched"
    out = capsys.readouterr().out
    assert f"LIBRARY_DB_PATH={demo} uv run ayl ask \"{init_cmd.FIRST_QUESTION}\"" in out


def test_a_built_demo_library_is_not_built_again(machine, capsys):
    machine.check_status = 0
    assert init("--demo") == 0
    machine.builds.clear()
    capsys.readouterr()
    assert init("--demo") == 0
    assert machine.builds == []
    assert "already built (6 of 6 books indexed); nothing to do" in capsys.readouterr().out


def test_full_rebuilds_a_starter_library_as_the_whole_corpus(machine):
    machine.check_status = 0
    assert init("--demo") == 0
    assert init("--demo", "--full") == 0
    assert machine.builds[-1][2] is True


def test_full_needs_demo(machine, capsys):
    with pytest.raises(SystemExit) as raised:
        init("--full")
    assert raised.value.code == 2
    assert "--full" in capsys.readouterr().err


def test_a_dry_run_ends_on_the_status_the_real_run_would(machine, capsys):
    """A demo asked for that the real run would not build (here: outside a
    checkout) is exit 1 in the plan too, not a 0 the real run then breaks."""
    machine.mp.setattr(init_cmd, "REPO_ROOT", "")
    assert init("--dry-run", "--demo") == preflight.EXIT_NOT_READY
    assert machine.builds == [] and not machine.home.exists()


@pytest.mark.parametrize("reply, built", [("", False), ("n", False), ("y", True), ("yes", True)])
def test_on_a_terminal_one_question_decides_the_demo_and_no_is_the_default(machine, reply,
                                                                          built, capsys):
    machine.answer(reply)
    init()
    assert len(machine.prompts) == 1 and "[y/N]" in machine.prompts[0]
    assert bool(machine.builds) is built
    out = capsys.readouterr().out
    assert "a few minutes" in out, "the estimate comes before the question"
    assert ("Nothing to do" in out) is False, "a first run changes something"


@pytest.mark.parametrize("flags", [["--yes"], ["--no-demo"], ["--demo"]])
def test_a_flag_answers_the_question_so_it_is_not_asked(machine, flags):
    machine.answer("y")
    init(*flags)
    assert machine.prompts == []
    assert bool(machine.builds) is (flags == ["--demo"])


def test_without_a_terminal_nothing_is_asked_and_no_demo_is_built(machine):
    init()
    assert machine.prompts == [] and machine.builds == []


def test_the_default_answer_is_one_constant(machine, monkeypatch):
    """The owner's switch: flip it and `--yes` and an empty answer both mean
    'build the demo'."""
    monkeypatch.setattr(init_cmd, "BUILD_DEMO_BY_DEFAULT", True)
    machine.check_status = 0
    init("--yes")
    assert len(machine.builds) == 1


def test_outside_a_checkout_the_demo_is_refused_with_the_way_on(machine, capsys):
    machine.mp.setattr(init_cmd, "REPO_ROOT", "")
    assert init("--demo") == preflight.EXIT_NOT_READY
    err = capsys.readouterr().err
    assert "ship with the clone, not with the installed package" in err
    assert "ayl add <folder>" in err
    assert machine.builds == []
    assert (machine.home / "config.env").exists(), "steps 1-4 work anywhere"


def test_a_demo_folder_holding_the_reader_s_own_books_is_not_built_over(machine, capsys):
    demo_library(machine.home / "demo" / "index", ["my-book"], source="local")
    assert init("--demo") == preflight.EXIT_NOT_READY
    assert "holds books that are not the demo corpus's" in capsys.readouterr().err
    assert machine.builds == []


# --- an index from before ADR-026 ------------------------------------------------------

def test_an_old_index_in_the_working_directory_gets_the_move_not_a_second_index(machine,
                                                                              capsys):
    old = machine.tmp / "cwd" / "data" / "lancedb"
    demo_library(old, STARTER)
    choice = config.DbPathChoice(old, 2, "an index at the old default")
    machine.mp.setattr(config, "DB_CHOICE", choice)
    machine.mp.setattr(config, "DB_PATH", old)
    assert init("--demo") == preflight.EXIT_NOT_READY
    out = capsys.readouterr().out
    assert "`ayl backup <dir>`, then `ayl restore <dir>/<timestamp> --db" in out
    assert "demo library: NOT built" in out
    assert f"--db {machine.home / 'demo' / 'index'}` in that restore" in out, \
        "a manifest-only old index is a demo library: offer the demo location"
    assert machine.builds == []
    assert old.is_dir(), "nothing is moved by code"


def test_the_clone_s_old_index_is_found_when_init_runs_elsewhere(machine, capsys):
    demo_library(machine.clone / "data" / "lancedb", ["meditations"])
    init()
    out = capsys.readouterr().out
    assert f"the clone at {machine.clone} holds an index at the old default" in out


def test_an_old_chat_database_gets_its_move_printed(machine, capsys):
    chat = machine.clone / ".chainlit" / "chat.db"
    chat.parent.mkdir()
    chat.write_bytes(b"")
    init()
    assert f"the web chat's history is read from {chat}" in capsys.readouterr().out
    assert chat.is_file()


# --- demo_state and --print-env-resolution -------------------------------------------

def test_what_an_existing_folder_is_as_a_demo_library(tmp_path):
    wanted = set(STARTER)
    assert init_cmd.demo_state(tmp_path / "none", "ollama", wanted)[0] == "absent"
    other = tmp_path / "other"
    (other / "transcripts_openrouter.lance").mkdir(parents=True)
    assert init_cmd.demo_state(other, "ollama", wanted) == ("other_backend",
                                                            "transcripts_openrouter")
    demo_library(tmp_path / "partial", STARTER[:2])
    assert init_cmd.demo_state(tmp_path / "partial", "ollama", wanted) == (
        "partial", "2 of 6 books indexed")
    demo_library(tmp_path / "complete", STARTER)
    assert init_cmd.demo_state(tmp_path / "complete", "ollama", wanted)[0] == "complete"
    unledgered = tmp_path / "unledgered"
    unledgered.mkdir()
    lancedb.connect(unledgered).create_table("transcripts_ollama", [{"x": 1}])
    assert init_cmd.demo_state(unledgered, "ollama", wanted) == (
        "foreign", "no ledger describes its books")


def test_an_interrupted_first_build_s_staging_table_is_not_another_backend(machine, tmp_path):
    """Ctrl-C during the first demo build leaves `transcripts_<backend>__staging`
    and no built table; the rerun has to resume it, not refuse it."""
    demo = machine.home / "demo" / "index"
    demo.mkdir(parents=True)
    lancedb.connect(demo).create_table("transcripts_ollama__staging", [{"x": 1}])
    assert init_cmd.demo_state(demo, "ollama", set(STARTER)) == ("absent", "")
    machine.check_status = 0
    assert init("--demo") == 0
    assert machine.builds == [(demo, "ollama", False)]


def test_the_env_resolution_names_each_source_and_never_a_key(machine, monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-not-a-real-key")
    monkeypatch.setattr(config, "EXPORTED", frozenset({"OPENROUTER_API_KEY", "OLLAMA_URL"}))
    assert init("--print-env-resolution") == 0
    out = capsys.readouterr().out
    assert "sk-not-a-real-key" not in out
    assert "OPENROUTER_API_KEY=<set, 17 chars>  [exported]" in out
    assert "OLLAMA_URL=" in out and machine.tags.calls == 0 and machine.pulls == []
    # the installer's whole data-flow list, and the opt-in key file
    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING", "LANGCHAIN_HANDLER",
                 "LANGCHAIN_ENDPOINT", "LANGSMITH_ENDPOINT", "LANGSMITH_API_KEY",
                 "OPENROUTER_ENV_FILE", "OLLAMA_HOST"):
        assert f"  {name}=" in out, name


def test_the_env_resolution_never_prints_a_credential_written_into_a_url(machine,
                                                                        monkeypatch, capsys):
    monkeypatch.setenv("LANGCHAIN_ENDPOINT", "https://user:s3cret@smith.example.com")
    init("--print-env-resolution")
    out = capsys.readouterr().out
    assert "s3cret" not in out
    assert "LANGCHAIN_ENDPOINT=https://<credentials>@smith.example.com" in out


# --- the two child processes, as they are started -------------------------------------

def test_the_demo_build_and_the_doctor_are_started_with_these_arguments(monkeypatch, tmp_path):
    """The recorders above stand where these two calls are; this pins the calls
    themselves: the script by path with `--starter` (none for --full) and the
    backend, the doctor as a module, each with LIBRARY_DB_PATH naming the demo
    library only when one is meant."""
    calls = []
    monkeypatch.setattr(init_cmd.subprocess, "call",
                        lambda argv, env=None: calls.append((argv, env)) or 0)
    monkeypatch.setattr(init_cmd, "REPO_ROOT", str(tmp_path / "clone"))
    monkeypatch.setenv("LIBRARY_DB_PATH", "/the/reader/s/own")
    demo = tmp_path / "home" / "demo" / "index"
    assert init_cmd.build_demo(demo, "ollama", full=False) == 0
    assert init_cmd.build_demo(demo, "ollama", full=True) == 0
    assert init_cmd.closing_check(demo) == 0
    assert init_cmd.closing_check(None) == 0
    script = str(tmp_path / "clone" / "scripts" / "ingest_demo_corpus.py")
    (starter, env1), (full, env2), (doctor, env3), (doctor_own, env4) = calls
    assert starter == [sys.executable, script, "--backend", "ollama", "--starter"]
    assert full == [sys.executable, script, "--backend", "ollama"]
    assert env1["LIBRARY_DB_PATH"] == env2["LIBRARY_DB_PATH"] == env3["LIBRARY_DB_PATH"] \
        == str(demo)
    assert doctor == doctor_own == [sys.executable, "-m", "ask_your_library.ayl", "doctor"]
    assert env4["LIBRARY_DB_PATH"] == "/the/reader/s/own", "the reader's own, untouched"


# --- a credential written into OLLAMA_URL is never printed (F-url-credentials) -----------

def no_secret(capsys):
    out, err = capsys.readouterr()
    assert SECRET not in out and SECRET not in err, (out, err)
    return out + err


def test_the_dry_run_prints_the_url_without_its_credential(machine, capsys):
    machine.mp.setattr(config, "OLLAMA_URL", CREDENTIAL_URL)
    assert init("--dry-run", "--no-demo") == 0
    printed = no_secret(capsys)
    assert "Ollama at http://<credentials>@localhost:11434" in printed
    assert "would ask http://<credentials>@localhost:11434/api/tags" in printed


def test_a_real_step_prints_the_url_without_its_credential(machine, capsys):
    machine.mp.setattr(config, "OLLAMA_URL", CREDENTIAL_URL)
    assert init("--no-demo") == 0
    assert "Ollama at http://<credentials>@localhost:11434" in no_secret(capsys)


def test_a_failed_tags_call_names_the_url_without_its_credential(machine, capsys):
    machine.mp.setattr(config, "OLLAMA_URL", CREDENTIAL_URL)
    machine.tags.down = True
    assert init("--no-demo") == preflight.EXIT_NO_LOCAL_RUNTIME
    assert "Could not reach Ollama at http://<credentials>@localhost:11434" in no_secret(capsys)


@pytest.mark.parametrize("answer", ["http_error", "error_line", "connection"])
def test_a_failed_pull_names_the_url_without_its_credential(machine, capsys, answer):
    from test_ollama_pull import FakeRequests, Stream
    machine.mp.setattr(config, "OLLAMA_URL", CREDENTIAL_URL)
    machine.mp.setattr(ollama, "pull", REAL_PULL)
    fake = {"http_error": FakeRequests(Stream([], status=500, text='{"error": "disk full"}')),
            "error_line": FakeRequests(Stream([{"error": "file does not exist"}])),
            "connection": FakeRequests(error=requests.ConnectionError(
                f"HTTPConnectionPool: Max retries exceeded with url {CREDENTIAL_URL}"))}[answer]
    machine.mp.setattr(ollama, "requests", fake)
    machine.mp.setattr(ollama, "RequestException", requests.RequestException)
    assert init("--no-demo") == preflight.EXIT_NO_LOCAL_RUNTIME
    assert fake.calls[0]["url"] == f"{CREDENTIAL_URL}/api/pull", "the request keeps it"
    no_secret(capsys)


def test_the_preflight_s_ollama_texts_carry_no_credential(monkeypatch):
    """What `ayl doctor` (init's closing check) and `ayl ask` print."""
    monkeypatch.setattr(preflight, "OLLAMA_URL", CREDENTIAL_URL)
    monkeypatch.setattr(preflight, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(preflight, "DB_PATH", Path("/nonexistent/index"))
    monkeypatch.setattr(config, "_db_confirmed", True)
    for fake in (Tags(down=True), BadTags()):
        monkeypatch.setattr(preflight, "requests", fake)
        problems = preflight.check_environment(db_path=Path("/nonexistent/index"))
        text = " ".join(problems)
        assert SECRET not in text and "http://<credentials>@localhost:11434" in text


class BadTags:
    def get(self, url, timeout=None):
        class Reply:
            status_code = 503

            def raise_for_status(self):
                raise requests.HTTPError(f"503 Server Error for url: {url}")
        return Reply()


def test_an_embedding_http_error_carries_no_credential(monkeypatch):
    """requests keeps `user:password@` in the URL of an HTTPError's text; a
    demo build's traceback would print it."""
    from ask_your_library import embeddings

    class Response:
        status_code = 500
        url = f"{CREDENTIAL_URL}/api/embed"

        def raise_for_status(self):
            raise requests.HTTPError(f"500 Server Error: boom for url: {self.url}")

    class Post:
        def post(self, *args, **kwargs):
            return Response()
    monkeypatch.setattr(embeddings, "requests", Post())
    with pytest.raises(requests.HTTPError) as raised:
        embeddings.OllamaEmbedder(CREDENTIAL_URL)._embed(["text"])
    assert SECRET not in str(raised.value)
    assert "http://<credentials>@localhost:11434/api/embed" in str(raised.value)
