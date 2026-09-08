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
        assert t("pf_no_ollama", url=preflight.OLLAMA_URL) not in problems


def test_a_dead_ollama_in_the_local_mode_is_still_a_dead_ollama(monkeypatch, tmp_path):
    from ask_your_library.i18n import t

    preflight = local_llm(monkeypatch, tmp_path, requests.ConnectionError("refused"))
    assert preflight.check_environment() == [t("pf_no_ollama", url=preflight.OLLAMA_URL)]


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
    assert t("pf_no_ollama", url=preflight.OLLAMA_URL) not in problems


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
