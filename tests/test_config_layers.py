"""Where a setting comes from (ADR-027): exported > the working directory's
`.env` > `$AYL_HOME/config.env` > the code's default — the same for every
command.

`load_dotenv()` with no path used to search upward from the CALLING FILE,
i.e. from this package: a clone found its own `.env` from any directory, an
installed wheel found none, and only a `python -c` (which python-dotenv treats
as interactive) searched the working directory. Every child below claims a
`__file__` for `__main__`, which is what a console script has, so a regression
to that search fails here and not only in a REPL.

Configuration is resolved at import, so each case is a fresh interpreter.
"""
import json

import pytest

from conftest import run_fresh

# What a console script looks like to python-dotenv: a `__main__` with a file.
AS_A_SCRIPT = "import __main__\n__main__.__file__ = '/nonexistent/ayl-entry.py'\n"

PROBE = AS_A_SCRIPT + (
    "import json\n"
    "from ask_your_library import config\n"
    "names = ('OLLAMA_URL', 'OLLAMA_LLM_MODEL', 'OLLAMA_EMBED_MODEL', 'OPENROUTER_EMBED_MODEL')\n"
    "print(json.dumps({'values': {'OLLAMA_URL': config.OLLAMA_URL,\n"
    "                             'OLLAMA_LLM_MODEL': config.OLLAMA_LLM_MODEL,\n"
    "                             'OLLAMA_EMBED_MODEL': config.OLLAMA_EMBED_MODEL,\n"
    "                             'OPENROUTER_EMBED_MODEL': config.OPENROUTER_EMBED_MODEL,\n"
    "                             'AYL_HOME': str(config.AYL_HOME)},\n"
    "                  'sources': {n: config.setting_source(n) for n in names}}))\n")


def probe(cwd, **env) -> dict:
    return json.loads(run_fresh(PROBE, cwd=cwd, **env).stdout)


def test_the_working_directory_s_dotenv_is_read_by_a_script_entry_too(tmp_path):
    (tmp_path / ".env").write_text("OLLAMA_LLM_MODEL=from-the-cwd-dotenv\n", encoding="utf-8")
    seen = probe(tmp_path)
    assert seen["values"]["OLLAMA_LLM_MODEL"] == "from-the-cwd-dotenv"
    assert seen["sources"]["OLLAMA_LLM_MODEL"] == str(tmp_path / ".env")


@pytest.mark.parametrize("marker", [".git", "pyproject.toml"])
def test_the_project_root_s_dotenv_is_found_from_a_subdirectory(tmp_path, marker):
    """Inside a clone, from any folder of it: the project's `.env`."""
    (tmp_path / marker).mkdir() if marker == ".git" else (tmp_path / marker).write_text("")
    (tmp_path / ".env").write_text("OLLAMA_LLM_MODEL=from-the-project\n", encoding="utf-8")
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    assert probe(inner)["values"]["OLLAMA_LLM_MODEL"] == "from-the-project"


def test_a_dotenv_above_the_project_root_is_not_read(tmp_path):
    """A `.env` in a home folder, or another tool's, above the project: it
    used to override `config.env` from every directory below it."""
    (tmp_path / ".env").write_text("OLLAMA_LLM_MODEL=from-above-the-project\n", encoding="utf-8")
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    inner = project / "src"
    inner.mkdir()
    seen = probe(inner)
    assert seen["values"]["OLLAMA_LLM_MODEL"] != "from-above-the-project"
    assert seen["sources"]["OLLAMA_LLM_MODEL"] == "default"


def test_outside_any_project_only_the_working_directory_s_dotenv_counts(tmp_path):
    (tmp_path / ".env").write_text("OLLAMA_LLM_MODEL=from-an-ancestor\n", encoding="utf-8")
    inner = tmp_path / "a" / "b"
    inner.mkdir(parents=True)
    assert probe(inner)["sources"]["OLLAMA_LLM_MODEL"] == "default"
    (inner / ".env").write_text("OLLAMA_LLM_MODEL=from-here\n", encoding="utf-8")
    assert probe(inner)["values"]["OLLAMA_LLM_MODEL"] == "from-here"


def test_exported_beats_dotenv_beats_home_config_beats_default(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.env").write_text("OLLAMA_URL=http://home-config:1\n"
                                     "OLLAMA_LLM_MODEL=from-home\n"
                                     "OLLAMA_EMBED_MODEL=from-home\n", encoding="utf-8")
    work = tmp_path / "work"
    work.mkdir()
    (work / ".env").write_text("OLLAMA_URL=http://dotenv:2\nOLLAMA_LLM_MODEL=from-dotenv\n",
                               encoding="utf-8")
    seen = probe(work, AYL_HOME=str(home), OLLAMA_URL="http://exported:3")
    assert seen["values"]["OLLAMA_URL"] == "http://exported:3"            # 1 over 2 and 3
    assert seen["values"]["OLLAMA_LLM_MODEL"] == "from-dotenv"            # 2 over 3
    assert seen["values"]["OLLAMA_EMBED_MODEL"] == "from-home"            # 3 over 4
    assert seen["values"]["OPENROUTER_EMBED_MODEL"] == "openai/text-embedding-3-small"
    assert seen["sources"] == {"OLLAMA_URL": "exported",
                               "OLLAMA_LLM_MODEL": str(work / ".env"),
                               "OLLAMA_EMBED_MODEL": str(home / "config.env"),
                               "OPENROUTER_EMBED_MODEL": "default"}


def test_the_home_config_cannot_move_the_home_it_lives_in(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.env").write_text(f"AYL_HOME={tmp_path / 'elsewhere'}\n"
                                     "OLLAMA_LLM_MODEL=from-home\n", encoding="utf-8")
    seen = probe(tmp_path, AYL_HOME=str(home))
    assert seen["values"]["AYL_HOME"] == str(home)
    assert seen["values"]["OLLAMA_LLM_MODEL"] == "from-home"


def test_the_dotenv_s_ayl_home_decides_which_home_config_is_read(tmp_path):
    """`AYL_HOME` may itself come from the `.env`, so the home file is read
    after it: the `.env` names the folder, the folder's file fills the rest."""
    home = tmp_path / "chosen-home"
    home.mkdir()
    (home / "config.env").write_text("OLLAMA_LLM_MODEL=from-the-chosen-home\n", encoding="utf-8")
    (tmp_path / ".env").write_text(f"AYL_HOME={home}\n", encoding="utf-8")
    child = run_fresh(PROBE, cwd=tmp_path)
    # run_fresh exports an AYL_HOME of its own, which wins over the .env line:
    # drop it for this child so the .env is what names the folder.
    assert json.loads(child.stdout)["values"]["AYL_HOME"] != str(home)
    seen = json.loads(run_fresh("import os\nos.environ.pop('AYL_HOME', None)\n" + PROBE,
                                cwd=tmp_path).stdout)
    assert seen["values"]["AYL_HOME"] == str(home)
    assert seen["values"]["OLLAMA_LLM_MODEL"] == "from-the-chosen-home"


def test_the_home_config_s_ayl_home_line_reaches_no_child_either(tmp_path):
    """With AYL_HOME unset the home is ~/AskYourLibrary, and its config.env
    may carry an AYL_HOME line. Loaded with `load_dotenv`, that line was
    EXPORTED: this process kept its home, and every child it started — the
    web chat's server, the doctor `ayl init` runs, the demo build — resolved
    the other folder."""
    reader = tmp_path / "reader"
    (reader / "AskYourLibrary").mkdir(parents=True)
    (reader / "AskYourLibrary" / "config.env").write_text(
        f"AYL_HOME={tmp_path / 'elsewhere'}\nOLLAMA_LLM_MODEL=from-home\n", encoding="utf-8")
    code = ("import os, subprocess, sys\n"
            "os.environ.pop('AYL_HOME', None)\n" + AS_A_SCRIPT +
            "from ask_your_library import config\n"
            "print(config.AYL_HOME)\n"
            "print(os.environ.get('AYL_HOME'))\n"
            "print(config.OLLAMA_LLM_MODEL)\n"
            "child = subprocess.run([sys.executable, '-c', 'from ask_your_library import config; "
            "print(config.AYL_HOME)'], capture_output=True, text=True, check=True)\n"
            "print(child.stdout.strip())\n")
    home, exported, model, in_child = run_fresh(code, cwd=tmp_path, HOME=str(reader)) \
        .stdout.splitlines()
    assert home == str(reader / "AskYourLibrary")
    assert exported == "None"
    assert model == "from-home"
    assert in_child == home
