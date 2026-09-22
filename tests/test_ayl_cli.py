"""`ayl`, the dispatcher (#30): that `--help` and `--version` are documentation
and not a run, that every subcommand hands the arguments after its name to the
parser that always took them, that the exit codes come back out, and that
`books` — the only command here with code of its own — lists a real index
without a model.

The autouse fixture is the one from test_cli.py: no key, and a preflight and a
graph that explode if anything touches them. A router that quietly grew an
environment read would pass every other test in this file.
"""
import argparse
from pathlib import Path

import lancedb
import pytest
import requests

from ask_your_library import ayl, cli, library
from ask_your_library.catalog import render_catalog, run_catalog
from ask_your_library.embeddings import OllamaEmbedder
from ask_your_library.i18n import t
from ask_your_library.ingest import add_folder
from ask_your_library.library import TITLE_SEPARATOR
from ask_your_library.preflight import PreflightResult
from test_add_folder import PARA, fake_embedder, write  # noqa: F401


@pytest.fixture(autouse=True)
def no_environment(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_ENV_FILE", raising=False)

    def forbidden(index_only=False, db_path=None, backend=None):
        raise AssertionError("check_environment() was called for --help/--version")
    monkeypatch.setattr(ayl, "check_environment", forbidden)
    monkeypatch.setattr(cli, "check_environment", forbidden)

    def no_graph():
        raise AssertionError("build_graph() was called for --help/--version")
    monkeypatch.setattr(cli, "build_graph", no_graph)


# --- the command surface itself ----------------------------------------------

@pytest.mark.parametrize("flag", ["--help", "--version"])
def test_help_and_version_exit_zero_without_a_key(flag, capsys):
    with pytest.raises(SystemExit) as exit_info:
        ayl.main([flag])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip()


def test_version_names_this_command_and_the_installed_version(capsys):
    with pytest.raises(SystemExit):
        ayl.main(["--version"])
    out = capsys.readouterr().out
    assert out.startswith("ayl ") and cli.package_version() in out


def test_help_lists_every_subcommand(capsys):
    with pytest.raises(SystemExit):
        ayl.main(["--help"])
    out = capsys.readouterr().out
    for name in ("ask", "add", "doctor", "backup", "restore", "books", "ui"):
        assert name in out


def test_no_command_and_an_unknown_command_are_argparse_errors(capsys):
    for argv in ([], ["reindex"]):
        with pytest.raises(SystemExit) as exit_info:
            ayl.main(argv)
        assert exit_info.value.code == 2
    assert "reindex" in capsys.readouterr().err


# --- the split: everything after the command name belongs to the command ------

@pytest.mark.parametrize("argv, head, rest", [
    (["ask", "--verbose", "a question"], ["ask"], ["--verbose", "a question"]),
    (["add", "~/books", "--rebuild", "--backup", "~/b"],
     ["add"], ["~/books", "--rebuild", "--backup", "~/b"]),
    (["ask", "ask"], ["ask"], ["ask"]),                 # a question that is a command name
    (["ask", "--", "-q"], ["ask"], ["--", "-q"]),
    (["--version"], ["--version"], []),                 # no command: all of it is ayl's
    ([], [], []),
])
def test_the_arguments_after_the_command_name_are_not_read_by_ayl(argv, head, rest):
    """`nargs=REMAINDER` would stop at `--verbose` and hand it to `ayl`, which
    accepts no such option — every flag of the two parsers below would have to
    be written out here to survive. This split is what keeps them verbatim."""
    assert ayl.split_argv(argv) == (head, rest)


# --- dispatch -----------------------------------------------------------------

@pytest.fixture
def recorded(monkeypatch):
    """`cli.main` and `add_folder.main` replaced by recorders, so a dispatch
    test asserts the argv and the prog a subcommand hands over and runs
    nothing. Returns the call log."""
    calls = []

    def ask(argv=None, prog="ask-library"):
        calls.append(("ask", list(argv), prog))

    def add(argv=None, prog="ayl-add"):
        calls.append(("add", list(argv), prog))
        return 0
    monkeypatch.setattr(cli, "main", ask)
    monkeypatch.setattr(add_folder, "main", add)
    return calls


HOME = str(Path("~").expanduser())


@pytest.mark.parametrize("argv, expected", [
    (["ask", "--verbose", "who is Fagin?"],
     ("ask", ["--verbose", "who is Fagin?"], "ayl ask")),
    # `add` is the one that is handed its arguments unread: it IS that command,
    # so its parser is the one the docs-as-code check of #72 compares against.
    (["add", "~/books", "--rebuild", "--backup", "~/b"],
     ("add", ["~/books", "--rebuild", "--backup", "~/b"], "ayl add")),
    (["backup", "~/b", "--db", "~/i"],
     ("add", ["--backup", f"{HOME}/b", "--db", f"{HOME}/i"], "ayl backup")),
    (["restore", "~/b/20260922", "--db", "~/i", "--force"],
     ("add", ["--restore", f"{HOME}/b/20260922", "--db", f"{HOME}/i", "--force"],
      "ayl restore")),
])
def test_each_subcommand_reaches_the_parser_that_always_took_those_flags(argv, expected,
                                                                        recorded):
    assert ayl.main(argv) == 0
    assert recorded == [expected]


def test_a_verb_forwards_only_what_the_reader_typed(recorded):
    """An option left out means "whatever is configured", which is the ingest
    parser's own default: passing its default back would make every run look
    like one that named a database."""
    assert ayl.main(["backup", "/b"]) == 0
    assert recorded == [("add", ["--backup", "/b"], "ayl backup")]


def test_backup_without_a_directory_is_argparses_own_error(recorded, capsys):
    """The directory is this verb's required positional, so an empty `ayl
    backup` is answered by name — not by argparse missing the argument of a
    `--backup` flag the reader never typed."""
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["backup"])
    assert exit_info.value.code == 2
    assert recorded == [] and "ayl backup" in capsys.readouterr().err


# --- a verb flag cannot be smuggled under another verb ------------------------

@pytest.mark.parametrize("verb, argv", [
    ("ayl backup", ["backup", "/b", "--doctor"]),
    ("ayl backup", ["backup", "/b", "--restore", "/x"]),
    ("ayl restore", ["restore", "/b", "--doctor"]),
    ("ayl restore", ["restore", "/b", "--backup", "/x"]),
    ("ayl doctor", ["doctor", "--backup", "/x"]),
    ("ayl doctor", ["doctor", "--restore", "/x"]),
    ("ayl doctor", ["doctor", "--rebuild"]),
])
def test_another_verbs_flag_is_not_an_option_of_this_one(verb, argv, recorded, capsys):
    """The ingest parser answers `--doctor` before `--backup`, so `ayl backup
    <dir> --doctor` took no copy, reported a clean index and exited 0. Each
    verb now declares its own options, and one of these is not among them."""
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(argv)
    assert exit_info.value.code == 2
    assert recorded == [] and verb in capsys.readouterr().err


@pytest.mark.parametrize("flag, verb", [("--doctor", "ayl doctor"),
                                        ("--backup", "ayl backup"),
                                        ("--restore", "ayl restore"),
                                        ("--rebuild", "ayl add <folder> --rebuild")])
def test_the_escape_hatch_does_not_carry_a_verb_flag_either(flag, verb, recorded, capsys):
    """`--` passes a flag this verb does not declare straight to the ingest
    command, which is the point of it — but a flag that decides WHICH command
    runs is not an option, and it is named rather than obeyed."""
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["backup", "/b", "--", flag])
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert recorded == []
    assert flag in err and verb in err          # and it names what to type instead


@pytest.mark.parametrize("abbreviation, verb", [
    ("--doct", "ayl doctor"), ("--back", "ayl backup"),
    ("--rest", "ayl restore"), ("--rebu", "ayl add <folder> --rebuild"),
    ("--doctor=1", "ayl doctor"),          # and the `=value` spelling of one
])
def test_an_abbreviated_verb_flag_does_not_get_through_the_hatch(abbreviation, verb,
                                                                 recorded, capsys):
    """argparse resolves an unambiguous long option by its PREFIX, so `--doct`
    reached `--doctor` on the other side of the hatch: `ayl backup /dest --
    --doct` ran the doctor, exited 0 and copied nothing. The screen matches by
    prefix now, and the ingest parser refuses abbreviations outright."""
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["backup", "/dest", "--", abbreviation])
    err = capsys.readouterr().err
    assert exit_info.value.code == 2
    assert recorded == [] and abbreviation in err and verb in err


@pytest.mark.parametrize("abbreviation", ["--doct", "--rest", "--rebu"])
def test_the_ingest_parser_refuses_an_abbreviated_flag_on_its_own(abbreviation, capsys):
    """The second half of the same fix, at the parser rather than at the hatch:
    `ayl add ~/books --doct` is a bad command line, not a doctor run."""
    with pytest.raises(SystemExit) as exit_info:
        add_folder.build_parser().parse_args([abbreviation])
    assert exit_info.value.code == 2
    assert abbreviation in capsys.readouterr().err


def test_a_flag_that_is_not_a_verbs_keeps_working_in_full(recorded):
    """`--backend` starts like `--backup` and is not one: the prefix screen
    reads the VERB flag's name, not the other way round."""
    assert ayl.main(["backup", "/b", "--", "--backend", "openrouter"]) == 0
    assert recorded == [("add", ["--backup", "/b", "--backend", "openrouter"], "ayl backup")]


def test_the_escape_hatch_passes_an_undeclared_flag_through(recorded):
    """The documented way out: a flag of the ingest parser that this verb does
    not declare (`ayl backup` has no `--backend`, the copy is of a directory)
    still reaches it, after everything the verb itself parsed."""
    assert ayl.main(["backup", "/b", "--db", "/i", "--", "--backend", "openrouter"]) == 0
    assert recorded == [("add", ["--backup", "/b", "--db", "/i", "--backend", "openrouter"],
                         "ayl backup")]


def test_a_subcommands_help_is_the_help_of_the_parser_that_runs_it(capsys):
    """`ayl ask --help` must print the CLI's own options under the name that
    was typed — not `ask-library`'s, and not a second copy kept here."""
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["ask", "--help"])
    out = capsys.readouterr().out
    assert exit_info.value.code == 0
    assert "usage: ayl ask" in out and "--deadline" in out and "--lang" in out

    with pytest.raises(SystemExit):
        ayl.main(["add", "--help"])
    out = capsys.readouterr().out
    assert "usage: ayl add" in out and "--rebuild" in out and "--prune" in out


def test_backup_answers_help_instead_of_missing_its_directory(capsys):
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["backup", "--help"])
    assert exit_info.value.code == 0
    assert "usage: ayl backup" in capsys.readouterr().out


# --- the exit status of a subcommand is the exit status of `ayl` --------------

@pytest.mark.parametrize("code", [0, 1, 2, 3, 5])
def test_an_ask_exit_status_passes_through(monkeypatch, code):
    """`cli.main` reports by raising SystemExit (the preflight's 3/4/5 among
    them); the router must not swallow or renumber it."""
    def ask(argv=None, prog=None):
        raise SystemExit(code)
    monkeypatch.setattr(cli, "main", ask)
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["ask", "q"])
    assert exit_info.value.code == code


def test_an_ask_that_returns_is_a_zero(recorded):
    assert ayl.main(["ask", "q"]) == 0


@pytest.mark.parametrize("code", [0, 1, 2])
def test_an_add_exit_status_passes_through(monkeypatch, code):
    """`add_folder.main` reports by returning; the console script exits with
    what `ayl.main` returns, so the number has to arrive here unchanged."""
    monkeypatch.setattr(add_folder, "main", lambda argv=None, prog=None: code)
    assert ayl.main(["add", "~/books"]) == code


# --- doctor: the environment half and the index half --------------------------

def test_doctor_aims_both_halves_at_the_same_index(monkeypatch, capsys):
    """The environment half is reported first, and it is aimed where the reader
    aimed the command: a preflight left on LIBRARY_DB_PATH reported the
    configured database as missing while the doctor beside it read `--db`."""
    order = []

    def preflight(index_only=False, db_path=None, backend=None):
        order.append(("preflight", index_only, str(db_path), backend))
        return PreflightResult([], (), [])
    monkeypatch.setattr(ayl, "check_environment", preflight)

    def doctor(argv=None, prog=None):
        order.append(("doctor", list(argv), prog))
        return 0
    monkeypatch.setattr(add_folder, "main", doctor)

    assert ayl.main(["doctor", "--db", "~/i", "--backend", "openrouter"]) == 0
    assert order == [
        # the whole environment (not index_only), at ~/i, as openrouter built it
        ("preflight", False, f"{HOME}/i", "openrouter"),
        ("doctor", ["--doctor", "--db", f"{HOME}/i", "--backend", "openrouter"], "ayl doctor")]


def test_doctor_without_a_db_leaves_the_configured_one_to_the_preflight(monkeypatch):
    """Nothing typed means nothing forwarded: `None` is what
    `check_environment` and the ingest parser both read as "the configured
    index", and neither is told a path that is only their own default."""
    seen = []
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        seen.append((db_path, backend)) or PreflightResult([], (), []))
    monkeypatch.setattr(add_folder, "main",
                        lambda argv=None, prog=None: seen.append(list(argv)) or 0)

    assert ayl.main(["doctor"]) == 0
    assert seen == [(None, None), ["--doctor"]]


def test_a_broken_environment_still_runs_the_index_doctor_and_sets_the_status(monkeypatch,
                                                                             capsys):
    """Both halves always run: an unreachable Ollama must not hide ledger drift,
    which is what the reader opened this command for. The status is the
    preflight's classification, the same number `ayl ask` would exit with."""
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult(["ollama is not there"], (), ["no_ollama"]))
    seen = []
    monkeypatch.setattr(add_folder, "main",
                        lambda argv=None, prog=None: seen.append(list(argv)) or 0)

    assert ayl.main(["doctor"]) == 5
    assert seen == [["--doctor"]]
    assert "ollama is not there" in capsys.readouterr().err


def test_a_healthy_environment_leaves_the_doctors_own_status(monkeypatch):
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult([], (), []))
    monkeypatch.setattr(add_folder, "main", lambda argv=None, prog=None: 1)
    assert ayl.main(["doctor"]) == 1


def test_doctor_help_answers_before_the_preflight(capsys):
    """The autouse fixture's `check_environment` explodes: this passes only
    because `ayl doctor --help` parses and exits first."""
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["doctor", "--help"])
    assert exit_info.value.code == 0
    assert "usage: ayl doctor" in capsys.readouterr().out


# --- books: the catalogue without a model call --------------------------------

def key(title, author):
    return f"{title}{TITLE_SEPARATOR}{author}"


MOBY = key("Moby Dick", "Herman Melville")
GULLIVER = key("Gulliver's Travels", "Jonathan Swift")


def row(book, source="pg:1", section="Chapter 1", n=1):
    return {"chunk_id": f"{book}/{section}/{n}", "note": "n", "book": book, "source": source,
            "section": section, "text": "text", "vector": [0.0, 1.0]}


@pytest.fixture
def index(tmp_path, monkeypatch):
    """A transcripts table in tmp, the one library.DB_PATH points at — the
    fixture of test_catalog.py, which is what `list_books` reads."""
    monkeypatch.setattr(library, "DB_PATH", tmp_path / "db")
    db = lancedb.connect(str(tmp_path / "db"))
    db.create_table(library.TABLES["transcripts"], [row(MOBY), row(GULLIVER, "pg:829")])
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult([], (), []))


def test_books_lists_the_index_and_calls_no_model(index, monkeypatch, capsys):
    """The listing a question routed to the catalogue produces today, for the
    price of the planner call that routes it. Here it is the two functions
    alone: a chat client built at all is the failure this asserts against."""
    from ask_your_library import llm
    monkeypatch.setattr(llm, "llm", lambda *a, **k: pytest.fail("books built a model client"))
    monkeypatch.setattr(llm, "llm_invoke", lambda *a, **k: pytest.fail("books called a model"))

    assert ayl.main(["books"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == render_catalog(run_catalog({"op": "list", "title": "",
                                                      "author": ""})).strip()
    assert MOBY in out and GULLIVER in out


def test_books_without_an_index_is_the_preflights_status_and_not_a_traceback(monkeypatch,
                                                                            capsys):
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult(["no index yet"], (), ["no_db"]))
    assert ayl.main(["books"]) == 3
    assert "no index yet" in capsys.readouterr().err


def test_books_takes_no_arguments_and_says_so(capsys):
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["books", "--everything"])
    assert exit_info.value.code == 2
    assert "ayl books" in capsys.readouterr().err


# --- books over the real preflight: no Ollama, no key -------------------------

def embedded_row(book, source="pg:1"):
    """A row whose vector is as wide as the configured embedder declares, so
    the real fingerprint check reads this index as one that embedder built —
    the two-dimensional vectors above are for `list_books`, which reads two
    metadata columns and no vector at all."""
    return {**row(book, source), "vector": [0.0] * OllamaEmbedder.dims}


@pytest.fixture
def unreachable_everything(tmp_path, monkeypatch):
    """A real index, and the REAL preflight over it, in the environment a
    reader most often has: a hosted answering model whose key is not set, and
    an Ollama that nothing answers on. Returns the index path."""
    from ask_your_library import preflight

    monkeypatch.setattr(ayl, "check_environment", preflight.check_environment)
    monkeypatch.setattr(preflight, "LLM_BACKEND", "openrouter")
    monkeypatch.setattr(preflight, "EMBED_BACKEND", "ollama")
    monkeypatch.setattr(preflight, "OPENROUTER_NEEDS_KEY", True)
    monkeypatch.setattr(preflight, "openrouter_api_key",
                        lambda: (_ for _ in ()).throw(RuntimeError("no key")))

    class Dead:
        def get(self, *a, **k):
            raise requests.ConnectionError("nothing on that port")
    monkeypatch.setattr(preflight, "requests", Dead())

    db_path = tmp_path / "db"
    monkeypatch.setattr(preflight, "DB_PATH", db_path)
    monkeypatch.setattr(library, "DB_PATH", db_path)
    lancedb.connect(str(db_path)).create_table(
        library.TABLES["transcripts"], [embedded_row(MOBY), embedded_row(GULLIVER, "pg:829")])
    return db_path


def test_books_lists_the_index_with_no_ollama_and_no_key(unreachable_everything, capsys):
    """The listing is two metadata columns of a table that is already on this
    disk. Nothing about it needs a model server or an account, so neither may
    stand between the reader and it."""
    assert ayl.main(["books"]) == 0
    out = capsys.readouterr()
    assert MOBY in out.out and GULLIVER in out.out
    assert t("pf_header") not in out.err          # nothing is wrong with THIS run


def test_doctor_still_reports_the_unreachable_ollama(unreachable_everything, capsys):
    """The other half of the same decision: `ayl doctor` answers "is this
    machine ready", so it keeps checking everything and keeps the status that
    says which to fix first."""
    from ask_your_library import preflight

    assert ayl.main(["doctor", "--db", str(unreachable_everything)]) == 5
    err = capsys.readouterr().err
    assert t("pf_header") in err
    assert t("pf_no_ollama", url=preflight.OLLAMA_URL,
             pulls=preflight.pull_commands()) in err
    assert t("pf_no_key") in err


def test_doctor_reports_a_healthy_index_the_configured_path_does_not_hold(monkeypatch,
                                                                         tmp_path, capsys,
                                                                         fake_embedder):
    """`ayl doctor --db <dir>` over a healthy index exits 0.

    It did not: the preflight half stayed on `config.DB_PATH`, which in a clone
    that keeps its library elsewhere does not exist, so the command printed
    `Database not found: data/lancedb` — the line docs/upgrading.md tells the
    reader to act on — and exited 3 over an index it had just reconciled
    cleanly. Everything else here is stubbed exactly as tests/test_preflight.py
    stubs it, so the one variable is which database the two halves read."""
    from ask_your_library import preflight

    db_path = tmp_path / "db"
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.txt", PARA * 4)
    add_folder.add_books(add_folder.read_folder(folder), "ollama", db_path, folder)
    capsys.readouterr()                        # the ingest's own lines are not the subject

    monkeypatch.setattr(ayl, "check_environment", preflight.check_environment)
    monkeypatch.setattr(preflight, "DB_PATH", tmp_path / "nothing-was-built-here")
    monkeypatch.setattr(preflight, "openrouter_api_key", lambda: "sk-x")
    monkeypatch.setattr(preflight, "get_embedder", lambda backend: fake_embedder)
    monkeypatch.setattr(preflight, "check_index", lambda *a: None)

    class Up:
        def get(self, *a, **k):
            return type("Tags", (), {
                "status_code": 200,
                "raise_for_status": lambda self: None,
                "json": lambda self: {"models": [{"name": "bge-m3:latest"},
                                                 {"name": "qwen2.5:14b"}]}})()
    monkeypatch.setattr(preflight, "requests", Up())

    assert ayl.main(["doctor", "--db", str(db_path)]) == 0
    out = capsys.readouterr()
    assert "no drift" in out.out and t("pf_header") not in out.err


# --- ui -----------------------------------------------------------------------

def test_ui_runs_chainlit_against_the_checkouts_script_on_loopback(monkeypatch, tmp_path):
    script = tmp_path / "ui.py"
    script.write_text("")
    monkeypatch.setattr(ayl, "REPO_ROOT", str(tmp_path))
    seen = []
    monkeypatch.setattr(ayl.subprocess, "call",
                        lambda command, cwd=None: seen.append((command, cwd)) or 0)

    assert ayl.main(["ui", "-w", "--port", "8123"]) == 0
    assert seen == [(["chainlit", "run", str(script), "--host", "127.0.0.1", "-w",
                      "--port", "8123"], tmp_path)]


def test_ui_starts_chainlit_in_the_checkout_so_the_committed_config_is_the_one_that_loads(
        monkeypatch, tmp_path):
    """Chainlit derives its app root from `CHAINLIT_APP_ROOT or os.getcwd()`
    and WRITES a default `.chainlit/config.toml` where it finds none. Started
    anywhere else, the committed config is not the one that loads:
    `unsafe_allow_html`, `auto_tag_thread = false`, the narrowed
    `allow_origins` and the MCP disable SECURITY.md names are all silently back
    at Chainlit's defaults, and a `.chainlit/` appears in the caller's
    directory."""
    script = tmp_path / "ui.py"
    script.write_text("")
    monkeypatch.setattr(ayl, "REPO_ROOT", str(tmp_path))
    seen = {}
    monkeypatch.setattr(ayl.subprocess, "call",
                        lambda command, cwd=None: seen.update(cwd=cwd) or 0)

    assert ayl.main(["ui"]) == 0
    assert seen["cwd"] == script.parent == tmp_path


def test_ui_without_a_checkout_names_what_is_missing(monkeypatch, capsys):
    """Installed as a wheel there is no repository above the package and no
    ui.py in it: the web chat is not in the distribution yet."""
    monkeypatch.setattr(ayl, "REPO_ROOT", "")
    monkeypatch.setattr(ayl.subprocess, "call",
                        lambda command, cwd=None: pytest.fail("chainlit was started anyway"))

    assert ayl.main(["ui"]) == 1
    assert "ui.py" in capsys.readouterr().err


def test_ui_without_chainlit_names_the_extra(monkeypatch, tmp_path, capsys):
    (tmp_path / "ui.py").write_text("")
    monkeypatch.setattr(ayl, "REPO_ROOT", str(tmp_path))

    def missing(command, cwd=None):
        raise FileNotFoundError(command[0])
    monkeypatch.setattr(ayl.subprocess, "call", missing)

    assert ayl.main(["ui"]) == 1
    assert "--extra ui" in capsys.readouterr().err


def test_ui_help_does_not_start_a_server(monkeypatch, capsys):
    monkeypatch.setattr(ayl.subprocess, "call",
                        lambda command, cwd=None: pytest.fail("chainlit was started for --help"))
    with pytest.raises(SystemExit) as exit_info:
        ayl.main(["ui", "--help"])
    assert exit_info.value.code == 0
    assert "usage: ayl ui" in capsys.readouterr().out


# --- the two names `ayl` replaced ---------------------------------------------

def test_ask_library_says_what_to_type_instead_and_runs_the_same_code(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(cli, "main", lambda argv=None: seen.append(argv))
    cli.ask_library_main(["a question"])
    err = capsys.readouterr().err
    assert seen == [["a question"]]
    assert err.count("\n") == 1 and "ayl ask" in err and "0.6.0" in err


def test_ayl_add_says_what_to_type_instead_and_returns_the_same_status(monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(add_folder, "main", lambda argv=None: seen.append(argv) or 3)
    assert add_folder.ayl_add_main(["~/books"]) == 3
    err = capsys.readouterr().err
    assert seen == [["~/books"]]
    assert err.count("\n") == 1 and "ayl add" in err and "0.6.0" in err


def test_ayl_itself_prints_no_deprecation_notice(recorded, capsys):
    """The notice belongs to the old names; the new one is not deprecated."""
    ayl.main(["ask", "q"])
    ayl.main(["add", "~/books"])
    assert "deprecated" not in capsys.readouterr().err


# --- the parser is a parser ---------------------------------------------------

def test_build_parser_returns_a_parser_that_knows_every_command():
    parser = ayl.build_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    assert set(ayl.SUMMARY) == set(ayl.DISPATCH)
    assert parser.parse_args(["books"]).command == "books"


def test_ui_script_is_the_repository_root_walk(monkeypatch, tmp_path):
    monkeypatch.setattr(ayl, "REPO_ROOT", str(tmp_path))
    assert ayl.ui_script() is None                      # a root without a ui.py
    (tmp_path / "ui.py").write_text("")
    assert ayl.ui_script() == Path(tmp_path) / "ui.py"
