"""The scripted-backend seam's gate: what it takes to turn it on, and what it
does when it is off.

The seam exists so tests/ui can start a real Chainlit server with no model, no
key and no index (`ask_your_library.fake_backend`). Everything valuable about it
is in the refusals, so they are what this file pins: one variable is never
enough, a wrong phrase is a refusal and not a warning, and with neither variable
set nothing is imported, nothing is patched and nothing is printed.
"""
import sys

import pytest

from ask_your_library import fake_backend
from ask_your_library.fake_backend import (CONFIRM_PHRASE, CONFIRM_VAR, ENABLE_VAR, MODULE_NAME,
                                           install_fake_backend)

SCRIPT = """
installed = []


def install():
    installed.append(True)
"""


@pytest.fixture(autouse=True)
def no_leftover_script():
    """The loaded file lives in sys.modules under a fixed name; a test that put
    one there must not be what the next test observes."""
    yield
    sys.modules.pop(MODULE_NAME, None)


@pytest.fixture
def script(tmp_path):
    path = tmp_path / "backend.py"
    path.write_text(SCRIPT)
    return path


def enable(monkeypatch, path=None, confirm=None):
    for name, value in ((ENABLE_VAR, path), (CONFIRM_VAR, confirm)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, str(value))


def test_with_neither_variable_it_does_nothing_at_all(monkeypatch, capsys):
    enable(monkeypatch)
    assert install_fake_backend() is None
    assert MODULE_NAME not in sys.modules
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_confirmation_alone_is_not_a_backend(monkeypatch):
    """The phrase names no script, so there is nothing to install: a shell that
    carries it around is inert, not armed."""
    enable(monkeypatch, confirm=CONFIRM_PHRASE)
    assert install_fake_backend() is None


def test_a_script_without_the_confirmation_refuses_to_start(monkeypatch, script):
    """Not a warning and not a fallback to the real backend: a server that came
    up answering from a script would be indistinguishable from a working one."""
    enable(monkeypatch, path=script)
    with pytest.raises(SystemExit) as refusal:
        install_fake_backend()
    message = str(refusal.value)
    assert CONFIRM_VAR in message and CONFIRM_PHRASE in message
    assert MODULE_NAME not in sys.modules          # nothing was loaded, let alone run


def test_the_confirmation_must_be_the_phrase(monkeypatch, script):
    enable(monkeypatch, path=script, confirm="1")
    with pytest.raises(SystemExit):
        install_fake_backend()


def test_both_together_load_the_file_and_call_install(monkeypatch, script, capsys):
    enable(monkeypatch, path=script, confirm=CONFIRM_PHRASE)
    assert install_fake_backend() == str(script)
    assert sys.modules[MODULE_NAME].installed == [True]
    # The operator who started the process is told, on stderr, what it is.
    assert "FAKE BACKEND" in capsys.readouterr().err


def test_a_missing_or_unusable_script_is_a_refusal(monkeypatch, tmp_path):
    enable(monkeypatch, path=tmp_path / "nothing-here.py", confirm=CONFIRM_PHRASE)
    with pytest.raises(SystemExit) as refusal:
        install_fake_backend()
    assert "no such file" in str(refusal.value)

    without_install = tmp_path / "half.py"
    without_install.write_text("value = 1\n")
    enable(monkeypatch, path=without_install, confirm=CONFIRM_PHRASE)
    with pytest.raises(SystemExit) as refusal:
        install_fake_backend()
    assert "install()" in str(refusal.value)


def test_the_banner_names_the_script_it_installed(monkeypatch, script, capsys):
    enable(monkeypatch, path=script, confirm=CONFIRM_PHRASE)
    install_fake_backend()
    assert str(script) in capsys.readouterr().err


# --- the .env path, which is how this would be armed by accident --------------
def test_a_dotenv_naming_either_variable_refuses_to_start(monkeypatch, tmp_path, script):
    """chainlit's own import calls load_dotenv(<cwd>/.env) before ui.py runs a
    line, so a `.env` carrying these names IS the process environment by the time
    the seam reads it. The refusal does not try to work out where the current
    value came from: the name being a key in that file is enough."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{ENABLE_VAR}={script}\n{CONFIRM_VAR}={CONFIRM_PHRASE}\n")
    # Exactly what dotenv would have done, so the test describes the real shape.
    enable(monkeypatch, path=script, confirm=CONFIRM_PHRASE)
    with pytest.raises(SystemExit) as refusal:
        install_fake_backend()
    message = str(refusal.value)
    assert ENABLE_VAR in message and ".env" in message
    assert MODULE_NAME not in sys.modules          # nothing was loaded, let alone run


def test_the_confirmation_alone_in_a_dotenv_is_refused_too(monkeypatch, tmp_path, script):
    """Either name is enough: half a pair in a file is still a pair nobody
    typed, and the half that is missing is the easy one to export by habit."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{CONFIRM_VAR}={CONFIRM_PHRASE}\n")
    enable(monkeypatch, path=script, confirm=CONFIRM_PHRASE)
    with pytest.raises(SystemExit) as refusal:
        install_fake_backend()
    assert CONFIRM_VAR in str(refusal.value)


def test_an_unrelated_dotenv_changes_nothing(monkeypatch, tmp_path, script, capsys):
    """The check is about these two names, not about having a `.env` at all —
    every developer has one, and it is what `cp .env.example .env` is for."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("LLM_BACKEND=ollama\nLIBRARY_DB_PATH=data/lancedb\n")
    enable(monkeypatch, path=script, confirm=CONFIRM_PHRASE)
    assert install_fake_backend() == str(script)
    assert "FAKE BACKEND" in capsys.readouterr().err


def test_an_unparsable_dotenv_does_not_invent_a_refusal(monkeypatch, tmp_path, script):
    """dotenv itself skips what it cannot read; a refusal nobody could explain
    would be worse than the sentence in SECURITY.md."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_bytes(b"\xff\xfe not text at all \x00")
    enable(monkeypatch, path=script, confirm=CONFIRM_PHRASE)
    assert install_fake_backend() == str(script)


def test_the_dotenv_is_not_read_at_all_when_the_seam_is_off(monkeypatch, tmp_path):
    """The file is consulted only once the seam has been asked for. An ordinary
    start — neither name in the environment — reads two environment variables
    and returns, whatever any `.env` nearby happens to say."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(f"{ENABLE_VAR}=/nowhere.py\n")
    enable(monkeypatch)                              # neither name in the environment
    assert install_fake_backend() is None


def test_the_phrase_is_a_sentence_not_a_flag():
    """A one-character value ("1", "true") is the shape an operator sets by
    habit; this one has to be typed on purpose."""
    assert len(CONFIRM_PHRASE) > 20 and "script" in CONFIRM_PHRASE
    assert fake_backend.BANNER.format(path="x").startswith("FAKE BACKEND")
