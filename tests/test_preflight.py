"""Unit tests for the environment preflight (no network, no DB)."""
import pytest
import requests


@pytest.fixture(autouse=True)
def hosted_backend(monkeypatch):
    """config reads the environment once, at import time, so a developer whose
    shell (or .env) says LLM_BACKEND=ollama would otherwise run these tests
    against a different preflight: no key gate, plus the pulled-model check.
    Every test below describes the default backend; the local mode has its own
    tests, which pin it the same way."""
    from ask_your_library import preflight

    monkeypatch.setattr(preflight, "LLM_BACKEND", "openrouter")
    monkeypatch.setattr(preflight, "EMBED_BACKEND", "ollama")
    monkeypatch.setattr(preflight, "OPENROUTER_NEEDS_KEY", True)
    monkeypatch.setattr(preflight, "OLLAMA_EMBED_MODEL", "bge-m3")   # OLLAMA_EMBED_MODEL is read at import time too


def test_preflight_reports_all_three_failures(monkeypatch, tmp_path):
    from ask_your_library import preflight

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(preflight, "openrouter_api_key",
                        lambda: (_ for _ in ()).throw(RuntimeError("no key")))
    monkeypatch.setattr(preflight, "DB_PATH", tmp_path / "missing")

    class Dead:
        def get(self, *a, **k):
            raise requests.ConnectionError("down")
    monkeypatch.setattr(preflight, "requests", Dead())

    problems = preflight.check_environment()
    assert len(problems) == 3


class Tags:
    """What GET /api/tags answers: `payload` is what .json() returns, or an
    exception instance it raises (a body that is not JSON)."""

    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


def healthy(monkeypatch, tmp_path, tables):
    """A preflight whose only variable is which tables the database holds. The
    embedding model is pulled: local embeddings are the default, so an Ollama
    without bge-m3 is a problem of its own (tested below), not the baseline."""
    from ask_your_library import preflight

    monkeypatch.setattr(preflight, "openrouter_api_key", lambda: "sk-x")

    class Up:
        def get(self, *a, **k):
            return Tags({"models": [{"name": "bge-m3:latest"}]})
    monkeypatch.setattr(preflight, "requests", Up())
    monkeypatch.setattr(preflight, "DB_PATH", tmp_path)
    monkeypatch.setattr(preflight, "get_embedder",
                        lambda backend: type("E", (), {"model": "m", "dims": 3})())
    monkeypatch.setattr(preflight, "check_index", lambda *a: None)

    class DB:
        def table_names(self):
            return list(tables)
    monkeypatch.setattr(preflight, "lancedb",
                        type("L", (), {"connect": staticmethod(lambda p: DB())})())
    return preflight


def test_preflight_clean_environment(monkeypatch, tmp_path):
    from ask_your_library import preflight as pf
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))

    result = preflight.check_environment()
    assert result == []
    assert result.notices == []


def test_missing_cards_table_is_a_notice_not_an_error(monkeypatch, tmp_path):
    """An `ayl-add` index has no cards table. That is supported, but the person
    asking must be told, not only the server log."""
    from ask_your_library import preflight as pf
    preflight = healthy(monkeypatch, tmp_path, [pf.TABLES["transcripts"]])

    result = preflight.check_environment()
    assert result == []                       # not fatal
    assert len(result.notices) == 1
    assert pf.TABLES["cards"] in result.notices[0]


def local_llm(monkeypatch, tmp_path, answer, model="qwen3.6"):
    """A preflight in LLM_BACKEND=ollama mode over a healthy database, whose
    only variable is what /api/tags answers: a `Tags` stub, or an exception
    instance raised by the request itself."""
    from ask_your_library import preflight as pf
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))
    monkeypatch.setattr(preflight, "LLM_BACKEND", "ollama")
    monkeypatch.setattr(preflight, "OPENROUTER_NEEDS_KEY", False)   # no key in this mode
    monkeypatch.setattr(preflight, "ORCHESTRATOR_MODEL", model)     # = OLLAMA_LLM_MODEL in config

    class Ollama:
        def get(self, *a, **k):
            if isinstance(answer, Exception):
                raise answer
            return answer
    monkeypatch.setattr(preflight, "requests", Ollama())
    return preflight


def test_a_model_pulled_as_latest_is_the_configured_model(monkeypatch, tmp_path):
    """`ollama pull qwen3.6` lists the model as `qwen3.6:latest`; the configured
    name without a tag must still count as pulled."""
    embed = {"name": "bge-m3:latest"}
    preflight = local_llm(monkeypatch, tmp_path, Tags({"models": [{"name": "qwen3.6:latest"}, embed]}))
    assert preflight.check_environment() == []

    preflight = local_llm(monkeypatch, tmp_path, Tags({"models": [{"name": "other:latest"}, embed]}))
    problems = preflight.check_environment()
    assert len(problems) == 1 and "qwen3.6" in problems[0]


def test_an_empty_model_list_is_a_valid_reply_however_it_is_encoded(monkeypatch, tmp_path):
    """Nothing pulled yet is `[]` — or `null`, which is what Go encodes an empty
    slice as and what older Ollama builds send. Both mean "this IS Ollama, it
    just has no models": the remedy is `ollama pull`, not "check the address"."""
    from ask_your_library.i18n import t

    for models in ([], None):
        preflight = local_llm(monkeypatch, tmp_path, Tags({"models": models}))
        problems = preflight.check_environment()
        assert t("pf_no_local_model", model="qwen3.6") in problems
        assert t("pf_ollama_bad_reply", url=preflight.OLLAMA_URL, status=200) not in problems


def test_a_reply_that_cannot_be_read_is_not_reported_as_a_dead_ollama(monkeypatch, tmp_path):
    """Something answers on OLLAMA_URL, but it is not Ollama's /api/tags:
    `ollama serve` is not the fix, so the message must not ask for it."""
    from ask_your_library.i18n import t
    import json

    for payload in (json.JSONDecodeError("Expecting value", "<html>", 0),   # not JSON at all
                    {"error": "unauthorized"},                              # no models key
                    {"models": "qwen3.6"},                                  # not a list of entries
                    {"models": ["qwen3.6"]}):                               # entries are not objects
        preflight = local_llm(monkeypatch, tmp_path, Tags(payload))
        problems = preflight.check_environment()
        assert problems == [t("pf_ollama_bad_reply", url=preflight.OLLAMA_URL, status=200)]
        assert t("pf_no_ollama", url=preflight.OLLAMA_URL, pulls=preflight.pull_commands()) not in problems


def test_a_dead_ollama_in_the_local_mode_is_still_a_dead_ollama(monkeypatch, tmp_path):
    from ask_your_library.i18n import t

    preflight = local_llm(monkeypatch, tmp_path, requests.ConnectionError("refused"))
    assert preflight.check_environment() == [t("pf_no_ollama", url=preflight.OLLAMA_URL, pulls=preflight.pull_commands())]


def test_an_http_error_is_a_bad_reply_and_names_the_status(monkeypatch, tmp_path):
    """A 4xx/5xx means a server answered: `ollama serve` would not help, and the
    status code is what tells the reader who did answer."""
    from ask_your_library.i18n import t

    class Broken(Tags):                       # answers, but with an HTTP error
        status_code = 503

        def raise_for_status(self):
            raise requests.HTTPError("503 Server Error")

    preflight = local_llm(monkeypatch, tmp_path, Broken({}))
    problems = preflight.check_environment()
    assert problems == [t("pf_ollama_bad_reply", url=preflight.OLLAMA_URL, status=503)]
    assert "503" in problems[0]
    assert t("pf_no_ollama", url=preflight.OLLAMA_URL, pulls=preflight.pull_commands()) not in problems


def test_local_embeddings_need_their_model_pulled_too(monkeypatch, tmp_path):
    """A reachable Ollama without bge-m3 answers /api/tags happily and then
    fails on the first search; preflight is where that must surface."""
    from ask_your_library.i18n import t

    chat = {"name": "qwen3.6:latest"}
    pulled = local_llm(monkeypatch, tmp_path, Tags({"models": [chat, {"name": "bge-m3"}]}))
    assert pulled.check_environment() == []                       # the bare name counts

    latest = local_llm(monkeypatch, tmp_path, Tags({"models": [chat, {"name": "bge-m3:latest"}]}))
    assert latest.check_environment() == []                       # and so does name:latest

    missing = local_llm(monkeypatch, tmp_path, Tags({"models": [chat, {"name": "nomic-embed-text:latest"}]}))
    assert missing.check_environment() == [t("pf_no_embed_model", model="bge-m3")]


def test_a_hosted_llm_still_needs_the_local_embedding_model(monkeypatch, tmp_path):
    """The default shape (hosted answering model, local embeddings): the chat
    model is nobody's business locally, the embedding model still is."""
    from ask_your_library import preflight as pf
    from ask_your_library.i18n import t
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))

    class NoEmbeddings:
        def get(self, *a, **k):
            return Tags({"models": [{"name": "qwen3.6:latest"}]})
    monkeypatch.setattr(preflight, "requests", NoEmbeddings())
    assert preflight.check_environment() == [t("pf_no_embed_model", model="bge-m3")]


def test_an_unreadable_reply_is_caught_with_a_hosted_llm_too(monkeypatch, tmp_path):
    """The default shape: hosted answering model, local embeddings. The same
    /api/tags reply is what the embedder will talk to, so a 200 that is not
    Ollama must fail preflight here as well — otherwise it surfaces as a
    retrieval error on the first question."""
    from ask_your_library import preflight as pf
    from ask_your_library.i18n import t
    import json

    for payload in (json.JSONDecodeError("Expecting value", "<html>", 0), {"error": "nope"}):
        preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))
        assert preflight.LLM_BACKEND == "openrouter" and preflight.EMBED_BACKEND == "ollama"

        class Weird:
            def get(self, *a, **k):
                return Tags(payload)
        monkeypatch.setattr(preflight, "requests", Weird())
        assert preflight.check_environment() == [t("pf_ollama_bad_reply", url=preflight.OLLAMA_URL, status=200)]


def test_a_hosted_llm_never_asks_for_a_pulled_chat_model(monkeypatch, tmp_path):
    """Only the pulled-model half stays conditional: with LLM_BACKEND=openrouter
    an Ollama that has bge-m3 but no chat model is a healthy environment."""
    from ask_your_library import preflight as pf
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))

    class Embeddings:
        def get(self, *a, **k):
            return Tags({"models": [{"name": "bge-m3:latest"}]})
    monkeypatch.setattr(preflight, "requests", Embeddings())
    assert preflight.check_environment() == []


def test_a_repo_env_file_cannot_hand_the_suite_a_provider_key(tmp_path):
    """The suite must not be able to reach a provider, whatever is on the
    machine — and `config.load_dotenv()` runs at the first package import and
    fills in any name that is ABSENT, reading a .env from the working directory
    and its parents. Dropping the keys therefore left the door open: a .env in
    the repository root put them straight back. conftest pins them blank
    instead, which holds the name and reads as "no key" everywhere.

    Driven through the shared fresh-interpreter helper, with a planted .env as
    the working directory: the pin only ever happens before the first import,
    so nothing in this process can show whether it worked.

    On the HOSTED backend, named here rather than left to the default. Under the
    shipped local one check_api_key() returns None whether a key is present or
    not — it is the gate that is off, not the key that is absent — so the
    planted key could sail through and this test would still be green."""
    from conftest import fresh_output

    planted = 'OPENROUTER_API_KEY="sk-planted-not-a-real-key"\n'
    (tmp_path / ".env").write_text(planted, encoding="utf-8")
    code = ("from conftest import pin_environment\n"
            "pin_environment()\n"
            "import os\n"
            "from ask_your_library import preflight\n"
            "print(repr(os.environ['OPENROUTER_API_KEY']), preflight.check_api_key() is not None)")
    assert fresh_output(code, cwd=str(tmp_path), LLM_BACKEND="openrouter") == "'' True"


# --- the exit code a first run gets ------------------------------------------
# The shipped default answers on a local model, so the two ways a fresh clone
# fails — no Ollama yet, no index yet — are the ordinary first-run path and not
# the caller's mistake. A wrapper script has to tell them apart, and the only
# thing it can read is the status: the messages are translated, and matching on
# prose is what this classification exists to replace.

def test_a_clean_environment_exits_zero():
    from ask_your_library import preflight

    assert preflight.exit_code(preflight.PreflightResult()) == preflight.EXIT_OK


def test_a_missing_ollama_and_a_missing_index_are_different_statuses(monkeypatch, tmp_path):
    """The two first-run conditions, each on its own, each with its own code."""
    from ask_your_library import preflight as pf

    preflight = local_llm(monkeypatch, tmp_path, requests.ConnectionError("refused"))
    result = preflight.check_environment()
    assert result.kinds == ["no_ollama"]
    assert pf.exit_code(result) == pf.EXIT_NO_LOCAL_RUNTIME == 5

    # Ollama up with both models pulled, and nothing indexed yet: the other half
    # of a first run, and the half whose remedy is a command, not an install.
    preflight = local_llm(monkeypatch, tmp_path,
                          Tags({"models": [{"name": "qwen3.6:latest"}, {"name": "bge-m3:latest"}]}))
    monkeypatch.setattr(preflight, "DB_PATH", tmp_path / "not-built-yet")
    result = preflight.check_environment()
    assert result.kinds == ["no_db"]
    assert pf.exit_code(result) == pf.EXIT_NO_INDEX == 3
    # And it says which command builds one.
    assert "ingest_demo_corpus.py" in result[0] and "ayl-add" in result[0]


def test_a_missing_key_keeps_its_own_status_on_the_hosted_backend(monkeypatch, tmp_path):
    """The hosted configuration's own first-run failure, unchanged by the flip:
    it is neither of the two above and must not borrow either code."""
    from ask_your_library import preflight as pf
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))
    monkeypatch.setattr(preflight, "openrouter_api_key",
                        lambda: (_ for _ in ()).throw(RuntimeError("no key")))

    result = preflight.check_environment()
    assert result.kinds == ["no_key"]
    assert pf.exit_code(result) == pf.EXIT_NO_KEY == 4


def test_the_status_names_the_problem_to_fix_first(monkeypatch, tmp_path):
    """A fresh clone usually has several at once — no Ollama AND no index. The
    code is a precedence, not a subset test: with nothing to answer with, the
    index is not the remedy to send the reader to, and a 30-minute build is a
    poor first instruction to someone who cannot finish it either way. Every
    problem is still in the list."""
    from ask_your_library import preflight as pf

    preflight = local_llm(monkeypatch, tmp_path, requests.ConnectionError("refused"))
    monkeypatch.setattr(preflight, "DB_PATH", tmp_path / "not-built-yet")
    result = preflight.check_environment()
    assert set(result.kinds) == {"no_ollama", "no_db"}
    assert len(result) == 2
    assert pf.exit_code(result) == pf.EXIT_NO_LOCAL_RUNTIME


def test_anything_else_keeps_the_status_it_always_had(monkeypatch, tmp_path):
    """An index built by another embedding model is not a first-run condition
    and has no remedy of its own to name, so it stays the 1 every caller that
    only tests for non-zero already handles."""
    from ask_your_library import preflight as pf
    preflight = healthy(monkeypatch, tmp_path, list(pf.TABLES.values()))
    monkeypatch.setattr(preflight, "check_index", lambda *a: "bge-m3 vs nomic-embed-text")

    result = preflight.check_environment()
    assert set(result.kinds) == {"index_mismatch"}
    assert pf.exit_code(result) == pf.EXIT_NOT_READY == 1


def test_the_remedy_names_the_models_this_configuration_will_open(monkeypatch, tmp_path):
    """`ollama pull bge-m3` printed to somebody running nomic-embed-text sends
    them to fetch a model their run never opens. The message is built from the
    configured names, and it carries the whole first-run remedy: install, start,
    pull, or the one command that does all three."""
    preflight = local_llm(monkeypatch, tmp_path, requests.ConnectionError("refused"),
                          model="qwen2.5:3b")
    monkeypatch.setattr(preflight, "OLLAMA_EMBED_MODEL", "nomic-embed-text")

    message = preflight.check_environment()[0]
    assert "ollama pull qwen2.5:3b" in message and "ollama pull nomic-embed-text" in message
    assert "bge-m3" not in message and "qwen2.5:14b" not in message
    assert "brew install ollama" in message and "ollama serve" in message
    assert "bash scripts/install-mac.sh" in message
