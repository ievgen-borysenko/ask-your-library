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
import shutil
import stat
import sys
from pathlib import Path

import lancedb
import pytest
import requests

from ask_your_library import ayl, config, home, init_cmd, ollama, preflight
from ask_your_library.embeddings import OllamaEmbedder
from ask_your_library.index_meta import expected_chunker, write_index_meta
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
        shutil.copytree(REPO / "corpus" / "cards", self.clone / "corpus" / "cards")
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

        def build(path, backend, full, cache):
            assert cache == self.home / "demo" / "cache", "the cache is under AYL_HOME"
            self.builds.append((path, backend, full))
            # What the script leaves: the requested library, whole, and only it.
            shutil.rmtree(path, ignore_errors=True)
            demo_library(path, STARTER if not full else list(MANIFEST_KEYS))
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


MANIFEST_KEYS = {entry["id"]: f"{entry['title']} — {entry['author']}"
                 for entry in (lambda m: m["books"] + m["canaries"])(
                     __import__("yaml").safe_load((REPO / "corpus" / "manifest.yaml")
                                                  .read_text(encoding="utf-8")))}
CARDED = {path.stem for path in (REPO / "corpus" / "cards").glob("*.md")}


def _table(db, name, keys, fts=True, meta=True, ids=None):
    """A table as the script publishes one: a row per book key (with the
    ledger's book_id, as the ingest writes it), then (unless the interruption
    came first) its full-text index, then its stamp."""
    ids = ids or {}
    rows = [{"chunk_id": f"{i}", "book": key, "book_id": ids.get(key, ""),
             "text": f"text of {key}"}
            for i, key in enumerate(sorted(keys))] or [
        {"chunk_id": "x", "book": "", "book_id": "", "text": "t"}]
    db.create_table(name, rows, mode="overwrite")
    if fts:
        db.open_table(name).create_fts_index("text", use_tantivy=False, replace=True)
    if meta:
        write_index_meta(db, name, "ollama", OllamaEmbedder.model, OllamaEmbedder.dims,
                         chunker=expected_chunker(name))


def demo_state_folder(path: Path, transcripts=None, cards=None, *, ledger=None,
                      t_staging=False, c_staging=False, t_fts=True, c_fts=True,
                      t_meta=True, c_meta=True, cards_from=None):
    """A demo folder in any state the script can leave: `transcripts` /
    `cards` the manifest ids each table holds (None: no table), a staging
    table beside either, a missing full-text index or stamp, and `ledger`
    ({id: status}, default: `indexed` for every transcripts book)."""
    path.mkdir(parents=True, exist_ok=True)
    db = lancedb.connect(path)
    key = lambda note: MANIFEST_KEYS.get(note, f"{note.title()} — Someone")  # noqa: E731
    statuses = ledger if ledger is not None else {n: "indexed" for n in (transcripts or [])}
    book_ledger = open_ledger(db)
    ids = {}
    for note, status in statuses.items():
        ref = f"manifest:{note}" if note in MANIFEST_KEYS else f"local:{note}"
        book_id = book_ledger.resolve(*key(note).split(" — ", 1), source_ref=ref)
        book_ledger.begin(book_id, key=key(note), source_ref=ref, embedding_model="fake")
        if status == "indexed":
            book_ledger.commit(book_id, rows=1)
        ids[key(note)] = book_id
    if transcripts is not None:
        _table(db, "transcripts_ollama", {key(n) for n in transcripts}, t_fts, t_meta, ids)
    staged = lambda notes: [{"chunk_id": f"s{i}", "book": key(n), "text": "t"}  # noqa: E731
                            for i, n in enumerate(STARTER if notes is True else notes)]
    if t_staging:
        db.create_table("transcripts_ollama__staging", staged(t_staging), mode="overwrite")
    if cards is not None:
        _table(db, "cards_ollama", {key(n) for n in cards if n in CARDED}, c_fts, c_meta)
    if c_staging:
        db.create_table("cards_ollama__staging",
                        staged([n for n in (STARTER if c_staging is True else c_staging)
                                if n in CARDED]), mode="overwrite")


def demo_library(path: Path, notes, source="manifest", ledger_notes=None, cards=True):
    """A finished demo library over `notes` (a foreign ledger with
    source="local"; a ledger that says other than the table with
    `ledger_notes`; no cards table with cards=False)."""
    path.mkdir(parents=True, exist_ok=True)
    if source != "manifest":
        db = lancedb.connect(path)
        _table(db, "transcripts_ollama", {f"{n.title()} — Someone" for n in notes})
        book_ledger = open_ledger(db)
        for note in notes:
            book_id = book_ledger.resolve(note.title(), "Someone", source_ref=f"{source}:{note}")
            book_ledger.begin(book_id, key=f"{note.title()} — Someone",
                              source_ref=f"{source}:{note}", embedding_model="fake")
            book_ledger.commit(book_id, rows=1)
        return
    demo_state_folder(path, notes, notes if cards else None,
                      ledger={n: "indexed" for n in (notes if ledger_notes is None
                                                     else ledger_notes)})


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
    assert ("scripts/ingest_demo_corpus.py --starter --backend ollama --cache-dir "
            f"{machine.home / 'demo' / 'cache'}") in out
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
    assert "Left to you: this configuration needs OPENROUTER_API_KEY" in out


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


def test_an_exported_hosted_embedder_is_refused_in_the_local_mode(machine, capsys):
    machine.mp.setattr(config, "EXPORTED", frozenset({"EMBED_BACKEND"}))
    machine.mp.setattr(config, "EMBED_BACKEND", "openrouter")
    assert init() == 2
    err = capsys.readouterr().err
    assert "EMBED_BACKEND=openrouter is exported in this shell" in err
    assert "`ayl init --mode hosted`, in which an exported switch decides" in err


def test_in_the_hosted_mode_an_exported_switch_decides_and_is_named(machine, monkeypatch,
                                                                   capsys):
    """As the installer's --hosted: the export wins over the file, the run
    follows it, and step 2 says so — no refusal."""
    machine.mp.setattr(config, "EXPORTED", frozenset({"EMBED_BACKEND"}))
    machine.mp.setattr(config, "EMBED_BACKEND", "openrouter")
    monkeypatch.setenv("EMBED_BACKEND", "openrouter")
    machine.check_status = preflight.EXIT_NO_KEY
    assert init("--mode", "hosted") == 0
    out = capsys.readouterr().out
    assert "Mode: neither mode `ayl init` writes — OpenRouter answers, OpenRouter embeds" in out
    assert "EMBED_BACKEND=openrouter is exported in this shell and wins over it" in out
    assert "\nLLM_BACKEND=openrouter\n" in (machine.home / "config.env").read_text()
    assert machine.pulls == [], "nothing of this configuration runs on Ollama"


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
    assert "already built (6 of 6 books in the index); nothing to do" in capsys.readouterr().out


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
    wanted = {note: MANIFEST_KEYS[note] for note in STARTER}
    assert init_cmd.demo_state(tmp_path / "none", "ollama", wanted)[0] == "absent"
    other = tmp_path / "other"
    (other / "transcripts_openrouter.lance").mkdir(parents=True)
    assert init_cmd.demo_state(other, "ollama", wanted) == ("other_backend",
                                                            "transcripts_openrouter")
    demo_library(tmp_path / "partial", STARTER[:2])
    assert init_cmd.demo_state(tmp_path / "partial", "ollama", wanted) == (
        "partial", "2 of 6 books in the index")
    demo_library(tmp_path / "complete", STARTER)
    assert init_cmd.demo_state(tmp_path / "complete", "ollama", wanted)[0] == "complete"
    unledgered = tmp_path / "unledgered"
    unledgered.mkdir()
    lancedb.connect(unledgered).create_table("transcripts_ollama", [{"x": 1}])
    assert init_cmd.demo_state(unledgered, "ollama", wanted) == (
        "foreign", "it holds books that are not the demo corpus's")


def test_an_interrupted_first_build_s_staging_table_is_not_another_backend(machine, tmp_path):
    """Ctrl-C during the first demo build leaves `transcripts_<backend>__staging`
    and no built table; the rerun has to resume it, not refuse it."""
    demo = machine.home / "demo" / "index"
    demo.mkdir(parents=True)
    lancedb.connect(demo).create_table("transcripts_ollama__staging", [{"x": 1}])
    assert init_cmd.demo_state(demo, "ollama", {n: MANIFEST_KEYS[n] for n in STARTER}) == (
        "absent", "")
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
    cache = tmp_path / "home" / "demo" / "cache"
    assert init_cmd.build_demo(demo, "ollama", full=False, cache=cache) == 0
    assert init_cmd.build_demo(demo, "ollama", full=True, cache=cache) == 0
    assert init_cmd.closing_check(demo) == 0
    assert init_cmd.closing_check(None) == 0
    script = str(tmp_path / "clone" / "scripts" / "ingest_demo_corpus.py")
    (starter, env1), (full, env2), (doctor, env3), (doctor_own, env4) = calls
    # --cache-dir: the downloads and prepared texts under AYL_HOME, and
    # nothing written under the checkout (F-demo-writes-checkout)
    assert starter == [sys.executable, script, "--backend", "ollama", "--cache-dir", str(cache),
                       "--starter"]
    assert full == [sys.executable, script, "--backend", "ollama", "--cache-dir", str(cache)]
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


# --- completeness is read from the tables (F2-demo-completeness) -------------------------

def test_a_full_ledger_over_a_starter_table_is_not_the_full_corpus(tmp_path):
    """A full run, then a `--starter` one: the ledger (before the script
    reconciled it) said every book was indexed while the table held six."""
    full = {note: MANIFEST_KEYS[note] for note in MANIFEST_KEYS}
    demo_library(tmp_path / "demo", STARTER, ledger_notes=list(MANIFEST_KEYS))
    state, detail = init_cmd.demo_state(tmp_path / "demo", "ollama", full)
    assert state == "partial" and detail == f"6 of {len(full)} books in the index"


def test_a_book_without_its_card_is_not_built(tmp_path):
    wanted = {note: MANIFEST_KEYS[note] for note in STARTER}
    demo_library(tmp_path / "demo", STARTER, cards=False)
    assert init_cmd.demo_state(tmp_path / "demo", "ollama", wanted)[0] == "partial"


def test_a_row_of_a_book_no_manifest_entry_names_is_foreign(tmp_path):
    wanted = {note: MANIFEST_KEYS[note] for note in STARTER}
    demo_library(tmp_path / "demo", STARTER + ["my-own-notes"], ledger_notes=STARTER)
    assert init_cmd.demo_state(tmp_path / "demo", "ollama", wanted) == (
        "foreign", "it holds books that are not the demo corpus's")


def test_full_over_a_starter_library_rebuilds_even_with_a_stale_full_ledger(machine):
    machine.check_status = 0
    demo_library(machine.home / "demo" / "index", STARTER, ledger_notes=list(MANIFEST_KEYS))
    assert init("--demo", "--full") == 0
    assert machine.builds and machine.builds[-1][2] is True


# --- the two switches are validated before any step (F2-embed-backend-typo) --------------

def test_a_typo_in_embed_backend_from_a_dotenv_is_refused_with_its_source(machine,
                                                                         monkeypatch, capsys):
    dotenv = machine.tmp / "work" / ".env"
    dotenv.parent.mkdir()
    dotenv.write_text("EMBED_BACKEND=ollma\n")
    machine.mp.setattr(config, "PROJECT_ENV", dotenv)
    machine.mp.setattr(config, "EMBED_BACKEND", "ollma")
    monkeypatch.setenv("EMBED_BACKEND", "ollma")
    assert init("--no-demo") == 2
    err = capsys.readouterr().err
    assert f"EMBED_BACKEND='ollma' [{dotenv}] is not a backend" in err
    assert "one of ollama, openrouter" in err
    assert machine.tags.calls == 0 and machine.pulls == [] and not machine.home.exists()


def test_a_dry_run_refuses_the_typo_too(machine, monkeypatch):
    monkeypatch.setenv("EMBED_BACKEND", "ollma")
    machine.mp.setattr(config, "EMBED_BACKEND", "ollma")
    assert init("--dry-run", "--no-demo") == 2


def test_blank_is_the_default_for_llm_backend_and_not_for_embed_backend(machine, monkeypatch,
                                                                       capsys):
    """As config.py reads them: LLM_BACKEND through `_env`, EMBED_BACKEND as
    it stands, which no embedder answers to."""
    monkeypatch.setenv("LLM_BACKEND", "  ")
    assert init("--no-demo") == 0
    capsys.readouterr()
    monkeypatch.setenv("EMBED_BACKEND", "")
    assert init("--no-demo") == 2
    assert "blank is not the default for this one" in capsys.readouterr().err


def test_a_valid_pair_init_does_not_write_is_named_not_left_undecided(machine, monkeypatch,
                                                                      capsys):
    """Local answers with hosted embeddings: a supported configuration, which
    sends every passage to OpenRouter — said, never an empty mode."""
    dotenv = machine.tmp / "work" / ".env"
    dotenv.parent.mkdir()
    dotenv.write_text("LLM_BACKEND=ollama\nEMBED_BACKEND=openrouter\n")
    machine.mp.setattr(config, "PROJECT_ENV", dotenv)
    machine.mp.setattr(config, "EMBED_BACKEND", "openrouter")
    monkeypatch.setenv("EMBED_BACKEND", "openrouter")
    machine.check_status = 0
    assert init("--no-demo") == 0
    out = capsys.readouterr().out
    assert "Mode: neither mode `ayl init` writes — Ollama answers, OpenRouter embeds" in out
    assert init_cmd.mode_of("openrouter", "openrouter") == "custom"


# --- every state an interrupted build can leave (F3-demo-cross-table) ----------------------
# The script's publish points, in order, for one run from library OLD to NEW
# (`--stage all`, no --book): the transcripts are rebuilt through a staging
# table, then full-text indexed, then stamped; the ledger rows are begun while
# the staging table fills, committed after the stamp, and reconciled; then the
# cards go through the same steps. One snapshot per gap between two of them.
FULL = list(MANIFEST_KEYS)


def snapshot(old, new, step):
    """The folder after an interruption at `step` of a run from `old` to
    `new` (manifest ids; old None for a first build), as demo_state_folder
    arguments. A rebuild keeps the old stamp until the new one is written —
    same embedder, same chunker — so only a first build lacks it."""
    first = old is None
    begun = {**({n: "indexed" for n in old} if old else {}), **{n: "requested" for n in new}}
    def t(**kw):
        return dict(transcripts=new, cards=old, ledger=begun, t_meta=not first, **kw)
    return {
        "S0 before anything is published": dict(transcripts=old, cards=old),
        "S1 transcripts staging being built": dict(transcripts=old, cards=old, ledger=begun,
                                                   t_staging=new),
        "S2 old transcripts dropped, staging complete": dict(transcripts=None, cards=old,
                                                             ledger=begun, t_staging=new),
        "S3 transcripts published, staging not dropped": t(t_staging=new, t_fts=False),
        "S4 transcripts published, no full-text index": t(t_fts=False),
        "S5 transcripts indexed, not stamped": t(),
        "S6 transcripts stamped, ledger not committed": dict(
            transcripts=new, cards=old, ledger=begun),
        "S7 ledger committed, not reconciled": dict(
            transcripts=new, cards=old,
            ledger={**{n: "indexed" for n in (old or [])}, **{n: "indexed" for n in new}}),
        "S8 ledger reconciled, cards not started": dict(transcripts=new, cards=old),
        "S9 cards staging being built": dict(transcripts=new, cards=old, c_staging=new),
        "S10 old cards dropped, staging complete": dict(transcripts=new, cards=None,
                                                        c_staging=new),
        "S11 cards published, staging not dropped": dict(transcripts=new, cards=new,
                                                         c_staging=new, c_fts=False,
                                                         c_meta=not first),
        "S12 cards published, no full-text index": dict(transcripts=new, cards=new, c_fts=False,
                                                        c_meta=not first),
        "S13 cards indexed, not stamped": dict(transcripts=new, cards=new, c_meta=not first),
        "S14 finished": dict(transcripts=new, cards=new),
    }[step]


STEPS = [
    "S0 before anything is published", "S1 transcripts staging being built",
    "S2 old transcripts dropped, staging complete", "S3 transcripts published, staging not dropped",
    "S4 transcripts published, no full-text index", "S5 transcripts indexed, not stamped",
    "S6 transcripts stamped, ledger not committed", "S7 ledger committed, not reconciled",
    "S8 ledger reconciled, cards not started", "S9 cards staging being built",
    "S10 old cards dropped, staging complete", "S11 cards published, staging not dropped",
    "S12 cards published, no full-text index", "S13 cards indexed, not stamped", "S14 finished"]
RUNS = {"first build": (None, STARTER), "starter to full": (STARTER, FULL),
        "full to starter": (FULL, STARTER)}


def expected(old, new, step, wanted):
    """What a reader is owed: the library is built only where the run had not
    started (S0, and only if the old library holds what is asked) or had
    finished (S14, the same for the new one). S13 of a REBUILD is S14 but for
    the stamp's date: the old stamp names the same embedder and chunker the
    new one would, over rows, cards, index and ledger that are all final —
    nothing a search or a write reads differs. Of a first build, it lacks
    the stamp, and is rebuilt."""
    finished = step.startswith("S14 ") or (step.startswith("S13 ") and old is not None)
    held = old if step.startswith("S0 ") else new if finished else None
    if held is not None and set(wanted) <= set(held):
        return "complete"
    no_table = (step.startswith("S2 ") or (old is None and step[:3] in ("S0 ", "S1 ")))
    return "absent" if no_table else "partial"


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("run", list(RUNS))
def test_an_interrupted_build_is_never_taken_for_a_built_one(tmp_path, run, step):
    old, new = RUNS[run]
    folder = tmp_path / "demo"
    demo_state_folder(folder, **snapshot(old, new, step))
    for request, wanted in (("--demo", STARTER), ("--demo --full", FULL)):
        got = init_cmd.demo_state(folder, "ollama", {n: MANIFEST_KEYS[n] for n in wanted})[0]
        assert got == expected(old, new, step, wanted), (run, step, request)


def test_the_gate_s_case_starter_transcripts_over_full_cards_is_rebuilt(machine, capsys):
    """Built --full, then `--starter` stopped after its transcripts were
    published and reconciled and before the cards stage: the cards still hold
    the whole corpus. init used to call it built."""
    folder = machine.home / "demo" / "index"
    demo_state_folder(folder, STARTER, FULL)
    state, detail = init_cmd.demo_state(folder, "ollama",
                                        {n: MANIFEST_KEYS[n] for n in STARTER})
    assert state == "partial" and "its cards are not its books'" in detail
    machine.check_status = 0
    assert init("--demo") == 0
    assert machine.builds == [(folder, "ollama", False)]


# --- a dry run ends on the status the real run ends on (F3-dry-run-status) -------------------
# Every way the real run ends non-zero that can be told without a write or a
# request is set up below, once per case; the dry run goes first (it changes
# nothing), then the real run over the same machine. The closing `ayl doctor`
# is a recorder (it needs a request); where a case is about what it reads, the
# recorder answers what the doctor answers for that index — the status
# tests/test_preflight.py pins for the same condition.

def _in_a_work_tree(machine, with_config):
    (machine.tmp / ".git").mkdir()
    if with_config:
        machine.home.mkdir(parents=True)
        (machine.home / "config.env").write_text("LLM_BACKEND=ollama\nEMBED_BACKEND=ollama\n")
        machine.mp.setattr(config, "HOME_CONFIG", machine.home / "config.env")
    machine.check_status = 1                       # the doctor's index_in_checkout


def _outside_a_checkout(machine):
    machine.mp.setattr(init_cmd, "REPO_ROOT", "")


def _old_index_here(machine):
    old = machine.tmp / "cwd" / "data" / "lancedb"
    demo_library(old, STARTER)
    choice = config.DbPathChoice(old, 2, "an index at the old default")
    machine.mp.setattr(config, "DB_CHOICE", choice)
    machine.mp.setattr(config, "DB_PATH", old)


def _foreign_demo_folder(machine):
    demo_library(machine.home / "demo" / "index", ["my-book"], source="local")


def _reader_index_stamped_by_another_embedder(machine):
    index = machine.home / "index"
    index.mkdir(parents=True)
    db = lancedb.connect(index)
    db.create_table("transcripts_ollama", [{"chunk_id": "1", "book": "Mine — Me", "book_id": "",
                                            "text": "t", "vector": [0.0] * 1024}])
    write_index_meta(db, "transcripts_ollama", "ollama", "another-model", 1024,
                     chunker=expected_chunker("transcripts_ollama"))
    machine.check_status = 1                       # the doctor's index_mismatch


def _reader_index_with_ledger_drift(machine):
    demo_state_folder(machine.home / "index", STARTER, STARTER,
                      ledger={**{n: "indexed" for n in STARTER}, "moby-dick": "indexed"})
    machine.check_status = 1                       # the doctor's ledger drift


def _built_demo(machine):
    demo_library(machine.home / "demo" / "index", STARTER)
    machine.check_status = 0


def _hosted_without_a_key(machine):
    machine.check_status = preflight.EXIT_NO_KEY   # the reader's to set: a leftover


PARITY = [
    ("first run", [], None, 0),
    ("home in a work tree, no config yet", [], lambda m: _in_a_work_tree(m, False), 1),
    ("home in a work tree, config exists", [], lambda m: _in_a_work_tree(m, True), 1),
    ("demo outside a checkout", ["--demo"], _outside_a_checkout, 1),
    ("demo over an old index", ["--demo"], _old_index_here, 1),
    ("demo folder holds other books", ["--demo"], _foreign_demo_folder, 1),
    ("reader index of another embedder", [], _reader_index_stamped_by_another_embedder, 1),
    ("reader index with ledger drift", [], _reader_index_with_ledger_drift, 1),
    ("demo already built", ["--demo"], _built_demo, 0),
    ("hosted, key not set", ["--mode", "hosted"], _hosted_without_a_key, 0),
]


@pytest.mark.parametrize("case", PARITY, ids=[c[0] for c in PARITY])
def test_the_dry_run_ends_on_the_real_run_s_status(machine, case):
    _, flags, setup, status = case
    if setup:
        setup(machine)
    dry = init("--dry-run", "--no-demo" if "--demo" not in flags else "--demo",
               *[f for f in flags if f != "--demo"])
    real = init("--no-demo" if "--demo" not in flags else "--demo",
                *[f for f in flags if f != "--demo"])
    assert (dry, real) == (status, status)


@pytest.mark.parametrize("env, exit_status", [({"EMBED_BACKEND": "ollma"}, 2),
                                              ({"LANGSMITH_TRACING_V2": "true"}, 2)])
def test_a_refusal_from_configuration_is_the_same_status_dry_or_real(machine, monkeypatch,
                                                                    env, exit_status):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    if "EMBED_BACKEND" in env:
        machine.mp.setattr(config, "EMBED_BACKEND", env["EMBED_BACKEND"])
    assert init("--dry-run", "--no-demo") == init("--no-demo") == exit_status


def test_what_a_dry_run_cannot_know_it_says_it_did_not_check(machine, capsys):
    """Whether Ollama answers, the pulls and a demo build need a request: a
    real run can end on 5 or 1 over them, and the dry run says so rather than
    implying a 0 covers them."""
    assert init("--dry-run", "--demo") == 0
    out = capsys.readouterr().out
    assert ("Not checked without a request, so not part of this status: whether Ollama "
            "answers and has the models, and the pulls; the demo build and the check over it."
            in out)


# --- no demo build while a credential is configured (F7-demo-traceback) -------------------

@pytest.mark.parametrize("dry", [False, True])
def test_the_demo_is_not_built_while_a_url_carries_a_credential(machine, capsys, dry):
    """The demo build is a child whose error output can print the URL it was
    sent to, user:password@ included (the embedders' HTTP errors, #107): it is
    not started then — exit 2, our own words — and steps 1-4 still run."""
    machine.mp.setattr(config, "OLLAMA_URL", CREDENTIAL_URL)
    status = init(*(["--dry-run"] if dry else []), "--demo")
    out, err = capsys.readouterr()
    assert status == 2
    assert machine.builds == []
    assert "carries a credential" in err and "issue #107" in err
    assert SECRET not in out + err
    assert "[4/5] Configuration" in out
    if not dry:
        assert (machine.home / "config.env").is_file(), "steps 1-4 ran"


def test_without_a_credential_the_demo_is_built_as_before(machine):
    machine.check_status = 0
    assert init("--demo") == 0 and len(machine.builds) == 1


def test_the_question_is_not_asked_when_the_answer_could_not_be_built(machine):
    machine.mp.setattr(config, "OLLAMA_URL", CREDENTIAL_URL)
    machine.answer("y")
    assert init() == 0
    assert machine.prompts == [] and machine.builds == []


def test_a_staging_table_of_other_books_makes_the_folder_foreign(tmp_path):
    """The demo script's rule, so init agrees with it (F7-staging-foreign)."""
    folder = tmp_path / "demo"
    demo_state_folder(folder, STARTER, STARTER, t_staging=["my-own-notes"])
    assert init_cmd.demo_state(folder, "ollama", {n: MANIFEST_KEYS[n] for n in STARTER}) == (
        "foreign", "it holds books that are not the demo corpus's")
