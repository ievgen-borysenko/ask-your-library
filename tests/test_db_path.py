"""Where the index is when no `--db` names one (ADR-026, #30).

The default moved from `data/lancedb` — relative, i.e. wherever the command was
typed — to `$AYL_HOME/index`. Three clauses, in order, in
`config.resolve_db_path`:

1. `LIBRARY_DB_PATH` set -> obeyed, always: no AYL_HOME, no git check, no notice.
2. unset, and `<cwd>/data/lancedb` holds `transcripts_<backend>` -> read there,
   with one stderr notice per process, never at `--help` / `--version`.
3. otherwise -> `$AYL_HOME/index`, created by the first write.

Nothing is copied, moved or deleted by the code, in any clause.
"""
import pytest

from ask_your_library import ayl, config, home, preflight
from ask_your_library.ingest import add_folder
from ask_your_library.preflight import PreflightResult
from conftest import run_fresh


def legacy_index(where, backend="ollama"):
    """A working directory holding an index at the old default, as LanceDB
    lays one out: one `<table>.lance` directory per table."""
    table = where / "data" / "lancedb" / f"transcripts_{backend}.lance"
    table.mkdir(parents=True)
    return where / "data" / "lancedb"


# --- the rule, clause by clause ----------------------------------------------

def test_clause_1_an_explicit_path_is_obeyed_even_over_an_old_index(tmp_path):
    legacy_index(tmp_path)
    choice = config.resolve_db_path("somewhere/else", cwd=tmp_path,
                                    backend="ollama", home=tmp_path / "home")
    assert choice.clause == 1
    assert choice.path == config.Path("somewhere/else")      # as written, not resolved
    assert "LIBRARY_DB_PATH is set" in choice.reason


def test_a_blank_variable_is_unset_and_not_the_working_directory(tmp_path):
    """`Path("")` is `.`: a copied `.env` line with nothing after the `=` used
    to open the working directory itself as the index."""
    choice = config.resolve_db_path("  ", cwd=tmp_path, backend="ollama",
                                    home=tmp_path / "home")
    assert choice.clause == 3


def test_clause_2_an_old_index_in_the_working_directory_is_read_where_it_is(tmp_path):
    old = legacy_index(tmp_path)
    choice = config.resolve_db_path("", cwd=tmp_path, backend="ollama", home=tmp_path / "home")
    assert choice.clause == 2
    assert choice.path == old and choice.path.is_absolute()
    assert "transcripts_ollama" in choice.reason and config.LEGACY_DB_SUNSET in choice.reason
    assert not (tmp_path / "home").exists(), "nothing is created, copied or moved"


def test_clause_2_needs_the_transcripts_table_of_this_backend(tmp_path):
    """A `data/lancedb` without `transcripts_<backend>` is not an index this
    configuration answers from — an empty folder, a cards-only index, another
    backend's — and does not keep the reader at the old default."""
    legacy_index(tmp_path, backend="openrouter")
    (tmp_path / "data" / "lancedb" / "cards_ollama.lance").mkdir()
    choice = config.resolve_db_path("", cwd=tmp_path, backend="ollama", home=tmp_path / "home")
    assert choice.clause == 3
    assert choice.path == (tmp_path / "home").resolve() / "index"
    assert "has no transcripts_ollama table" in choice.reason
    # the same folder IS the index for the backend that built it
    assert config.resolve_db_path("", cwd=tmp_path, backend="openrouter",
                                  home=tmp_path / "home").clause == 2


def test_clause_3_the_default_is_under_ayl_home_and_absolute(tmp_path):
    choice = config.resolve_db_path("", cwd=tmp_path, backend="ollama", home=tmp_path / "home")
    assert choice.clause == 3
    assert choice.path == (tmp_path / "home").resolve() / "index"
    assert "no data/lancedb in the working directory" in choice.reason
    assert not choice.path.exists(), "created by the first write, not by resolving it"


# --- the notice ----------------------------------------------------------------

def test_the_notice_names_the_new_default_the_path_and_the_move(tmp_path):
    old = legacy_index(tmp_path)
    choice = config.resolve_db_path("", cwd=tmp_path, backend="ollama", home=tmp_path / "home")
    notice = config.legacy_db_notice(choice, home=tmp_path / "home")
    new = (tmp_path / "home").resolve() / "index"
    assert str(old) in notice
    assert f"{new} ($AYL_HOME/index)" in notice
    assert "`ayl backup <dir>`" in notice
    assert f"`ayl restore <dir>/<timestamp> --db {new} --chat-db " in notice
    assert f"until {config.LEGACY_DB_SUNSET}, when it becomes an error" in notice
    assert "Nothing is moved for you" in notice
    assert f"LIBRARY_DB_PATH={old}" in notice          # the way to keep it where it is
    # while the checkout's chat.db is there, the web chat reads it and not the
    # restored copy: the move has to take it out of the way as well
    assert ("move data/lancedb out of this directory, and the checkout's .chainlit/chat.db "
            "(with its -wal/-shm) if there is one") in notice
    assert "\n" not in notice, "one line"


NOTICE = "note: reading the index at"


def test_the_notice_is_printed_once_per_process_and_only_on_use(tmp_path):
    """Importing the configuration says nothing; the first use says it once,
    however many times the index is asked for after that."""
    legacy_index(tmp_path)
    child = run_fresh(
        "import sys\n"
        "from ask_your_library import config\n"
        "print('imported', file=sys.stderr, flush=True)\n"
        "assert config.DB_CHOICE.clause == 2, config.DB_CHOICE\n"
        "for _ in range(3):\n"
        "    config.confirm_db_path()\n",
        cwd=tmp_path)
    before, _, after = child.stderr.partition("imported\n")
    assert NOTICE not in before
    assert after.count(NOTICE) == 1, child.stderr
    assert str(tmp_path / "data" / "lancedb") in after


def test_the_preflight_is_where_a_command_first_uses_the_index(tmp_path, monkeypatch):
    """`ayl ask`, `ayl doctor`, `ayl books` and the web chat reach the index
    through the preflight, so that is where the notice goes out — once, however
    many times it runs (the web chat runs it per chat)."""
    printed = []
    monkeypatch.setattr(config, "DB_CHOICE",
                        config.DbPathChoice(tmp_path / "old", 2, "clause two"))
    monkeypatch.setattr(config, "_db_confirmed", False)
    monkeypatch.setattr(config, "legacy_db_notice", lambda choice: printed.append(choice) or "n")
    preflight.check_environment(index_only=True)
    preflight.check_environment(index_only=True)
    assert len(printed) == 1
    # and a path named with --db is the reader's: nothing is said about it
    monkeypatch.setattr(config, "_db_confirmed", False)
    preflight.check_environment(index_only=True, db_path=tmp_path / "named")
    assert len(printed) == 1


@pytest.mark.parametrize("argv", [["--help"], ["--version"], ["ask", "--help"],
                                  ["ask", "--version"], ["add", "--help"],
                                  ["doctor", "--help"], ["backup", "--help"],
                                  ["restore", "--help"], ["books", "--help"]])
def test_no_notice_at_help_or_version_time(tmp_path, argv):
    """`cli.main`'s rule — parsing precedes any environment touch — holds for
    this too: a reader asking what the command takes, in a checkout that still
    has the old index, is told what it takes and nothing else."""
    legacy_index(tmp_path)
    child = run_fresh(f"import sys\nfrom ask_your_library import ayl\nsys.exit(ayl.main({argv!r}))",
                      cwd=tmp_path)
    assert NOTICE not in child.stderr + child.stdout
    assert child.stdout.strip(), "the help or the version was printed"


# --- a fresh process ------------------------------------------------------------

def test_unset_the_default_resolves_under_ayl_home_and_not_the_working_directory(tmp_path):
    """The whole point of the move: the same command typed in two directories
    opens one index, and neither directory gains a `data/`."""
    where = tmp_path / "typed-here"
    where.mkdir()
    (where / "data" / "lancedb").mkdir(parents=True)      # present, but no table in it
    out = run_fresh("from ask_your_library import config\n"
                    "print(config.DB_CHOICE.clause)\nprint(config.DB_PATH)",
                    cwd=where, AYL_HOME=str(tmp_path / "reader-home"))
    clause, path = out.stdout.split()
    assert clause == "3"
    assert path == str((tmp_path / "reader-home").resolve() / "index")
    assert not path.startswith(str(where))


def test_the_explicit_variable_wins_in_a_fresh_process(tmp_path):
    legacy_index(tmp_path)
    out = run_fresh("from ask_your_library import config\nprint(config.DB_PATH)",
                    cwd=tmp_path, LIBRARY_DB_PATH=str(tmp_path / "mine"))
    assert out.stdout.strip() == str(tmp_path / "mine")


# --- the git-work-tree refusal ----------------------------------------------------

def fake_checkout(tmp_path):
    repo = tmp_path / "checkout"
    (repo / ".git").mkdir(parents=True)
    return repo


def test_a_default_index_inside_a_checkout_is_refused_naming_the_variable(tmp_path,
                                                                           monkeypatch):
    repo = fake_checkout(tmp_path)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    monkeypatch.setattr(config, "DB_CHOICE",
                        config.resolve_db_path("", cwd=tmp_path, backend="ollama",
                                               home=repo / "ayl"))
    monkeypatch.setattr(config, "_db_confirmed", False)
    with pytest.raises(RuntimeError, match="inside the git work tree") as refused:
        config.confirm_db_path()
    assert "Set LIBRARY_DB_PATH to put the index somewhere else" in str(refused.value)
    assert not (repo / "ayl").exists()


def test_the_refusal_is_a_preflight_problem_not_a_traceback(tmp_path, monkeypatch):
    repo = fake_checkout(tmp_path)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    monkeypatch.setattr(config, "DB_CHOICE",
                        config.DbPathChoice(repo / "ayl" / "index", 3, "clause three"))
    monkeypatch.setattr(config, "_db_confirmed", False)
    problems = preflight.check_environment(index_only=True)
    assert problems.kinds == ["index_in_checkout"]
    assert "LIBRARY_DB_PATH" in problems[0]
    assert preflight.exit_code(problems) == preflight.EXIT_NOT_READY


def test_ayl_add_refuses_it_in_one_line(tmp_path, monkeypatch, capsys):
    repo = fake_checkout(tmp_path)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    monkeypatch.setattr(config, "DB_CHOICE",
                        config.DbPathChoice(repo / "ayl" / "index", 3, "clause three"))
    monkeypatch.setattr(config, "_db_confirmed", False)
    books = tmp_path / "books"
    books.mkdir()
    assert add_folder.main([str(books)]) == 1
    assert "Set LIBRARY_DB_PATH" in capsys.readouterr().err
    assert not (repo / "ayl").exists()


def test_an_explicit_path_inside_a_checkout_is_not_refused(tmp_path, monkeypatch):
    """Clause 1 is the escape: a developer who wants a throwaway index inside
    a checkout names it, and is obeyed."""
    repo = fake_checkout(tmp_path)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    monkeypatch.setattr(config, "DB_CHOICE",
                        config.resolve_db_path(str(repo / "idx"),
                                               cwd=tmp_path, backend="ollama"))
    monkeypatch.setattr(config, "_db_confirmed", False)
    assert config.confirm_db_path() == config.DB_PATH


# --- doctor names the situation ---------------------------------------------------

@pytest.mark.parametrize("clause", [1, 2, 3])
def test_doctor_names_the_index_and_the_rule_that_chose_it(clause, monkeypatch, capsys,
                                                           tmp_path):
    choice = config.DbPathChoice(tmp_path / f"index-{clause}", clause, f"because {clause}")
    monkeypatch.setattr(ayl, "DB_CHOICE", choice)
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult([], (), []))
    monkeypatch.setattr(add_folder, "main", lambda argv=None, prog=None: 0)
    assert ayl.main(["doctor"]) == 0
    assert f"index: {tmp_path / f'index-{clause}'} — because {clause}" in capsys.readouterr().out


def test_doctor_with_db_says_it_was_named(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(ayl, "check_environment",
                        lambda index_only=False, db_path=None, backend=None:
                        PreflightResult([], (), []))
    monkeypatch.setattr(add_folder, "main", lambda argv=None, prog=None: 0)
    assert ayl.main(["doctor", "--db", str(tmp_path / "i")]) == 0
    assert f"index: {tmp_path / 'i'} — named with --db" in capsys.readouterr().out


# --- the scratchpads: the web chat's rule, for the CLI too -------------------------

def test_the_cli_scratch_directory_is_under_ayl_home_and_absolute(tmp_path):
    out = run_fresh("from ask_your_library import cli\nprint(cli.SCRATCH_DIR)",
                    AYL_HOME=str(tmp_path / "reader-home"))
    assert out.stdout.strip() == str((tmp_path / "reader-home").resolve() / "scratch")


def test_the_cli_scratch_variable_wins_and_a_tilde_is_expanded(tmp_path):
    out = run_fresh("from ask_your_library import cli\nprint(cli.SCRATCH_DIR)",
                    HOME=str(tmp_path), ASK_SCRATCH_DIR="~/pads")
    assert out.stdout.strip() == str(tmp_path.resolve() / "pads")


def test_the_cli_and_the_web_chat_share_one_rule():
    from ask_your_library.ui import launcher
    assert launcher.scratch_dir() == home.scratch_dir()

