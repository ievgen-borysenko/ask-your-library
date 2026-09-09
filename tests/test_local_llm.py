"""LLM_BACKEND=ollama: every agent node runs on a local model through Ollama's
OpenAI-compatible endpoint, with no key, no cost and the local model named in
the fingerprint. Checked in a subprocess so the running interpreter's config is
not reloaded."""
import json

from conftest import fresh_output as _out, run_fresh as _run


def test_ollama_backend_points_the_client_at_ollama_with_no_key_and_no_price():
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.LLM_BACKEND, config.ORCHESTRATOR_MODEL, config.LLM_BASE_URL, "
            "config.LLM_NEEDS_KEY, config.PRICE_IN_PER_MTOK, config.PRICE_OUT_PER_MTOK]))")
    env = {"LLM_BACKEND": "ollama", "OLLAMA_LLM_MODEL": "qwen2.5:3b", "OLLAMA_URL": "http://localhost:11434"}
    backend, model, base, needs_key, pin, pout = json.loads(_out(code, **env))
    assert (backend, model, base, needs_key, pin, pout) == ("ollama", "qwen2.5:3b", "http://localhost:11434/v1", False, 0.0, 0.0)
    # the default stays OpenRouter with a key and list prices. The endpoint is
    # compared whole: a prefix test against a host name reads as an allow-list
    # check, and https://openrouter.ai.example.com would pass one.
    backend, model, base, needs_key, pin, pout = json.loads(_out(code))
    assert backend == "openrouter" and needs_key and pin == 3.0
    assert base == "https://openrouter.ai/api/v1"


def test_ollama_backend_needs_no_key_in_preflight_and_in_the_llm_factory():
    code = ("import json; from ask_your_library import preflight, llm; from unittest import mock; "
            "assert preflight.check_api_key() is None; "
            "captured = {}\n"
            "class Fake:\n"
            "    def __init__(self, **kw): captured.update(kw)\n"
            "llm.ChatOpenAI = Fake; llm.llm(); print(json.dumps({k: str(v) for k, v in captured.items()}))")
    kw = json.loads(_out(code, LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen2.5:3b"))
    assert kw["api_key"] == "ollama" and kw["base_url"].endswith("/v1") and kw["model"] == "qwen2.5:3b"


def test_openrouter_backend_still_refuses_without_a_key():
    code = "from ask_your_library import preflight; print(preflight.check_api_key() is not None)"
    assert _out(code, LLM_BACKEND="openrouter") == "True"


def test_a_copied_env_example_cannot_send_the_local_mode_to_openrouter(tmp_path):
    """A .env copied from the example carries the OpenRouter model, URL and
    prices; with LLM_BACKEND=ollama they must be ignored."""
    import shutil
    from pathlib import Path
    shutil.copy(Path(__file__).resolve().parents[1] / ".env.example", tmp_path / ".env")
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.ORCHESTRATOR_MODEL, config.LLM_BASE_URL, config.PRICE_IN_PER_MTOK]))")
    model, base, price = json.loads(_out(code, cwd=str(tmp_path), LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen2.5:3b"))
    assert model == "qwen2.5:3b" and base.startswith("http://localhost:11434") and price == 0.0
    # blank values in a .env mean the default, never a crash
    (tmp_path / ".env").write_text("PRICE_IN_PER_MTOK=\nPRICE_OUT_PER_MTOK= \nORCHESTRATOR_MODEL=\n")
    model, base, price = json.loads(_out(code, cwd=str(tmp_path)))
    assert model == "anthropic/claude-sonnet-4.6" and price == 3.0


def test_preflight_checks_the_model_the_client_will_call(monkeypatch):
    """The pulled-model check uses the effective ORCHESTRATOR_MODEL."""
    code = """
import json
from unittest import mock
from ask_your_library import preflight

class R:
    def raise_for_status(self):
        pass
    def json(self):
        # bge-m3 is listed too: local embeddings check their own model, and this
        # test is about the chat model the client will call.
        return {"models": [{"name": "qwen2.5:3b"}, {"name": "bge-m3:latest"}]}

with mock.patch.object(preflight.requests, "get", lambda *a, **k: R()):
    problems = [p for p in preflight.check_environment() if "pulled" in p or "завантаж" in p]
print(json.dumps(problems))
"""
    assert json.loads(_out(code, LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen2.5:3b")) == []
    missing = json.loads(_out(code, LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="nope:latest"))
    assert len(missing) == 1 and "nope:latest" in missing[0]


def test_an_invalid_backend_fails_fast_instead_of_falling_back_to_the_hosted_provider():
    """LLM_BACKEND=ollma must not become OpenRouter silently."""
    result = _run("from ask_your_library import config", check=False, LLM_BACKEND="ollma", OPENROUTER_API_KEY="sk-test")
    assert result.returncode != 0 and "LLM_BACKEND must be" in result.stderr
    assert "sk-test" not in result.stderr


def test_the_embeddings_endpoint_is_independent_of_where_the_answering_model_runs():
    """LLM_BACKEND=ollama with EMBED_BACKEND=openrouter keeps the OpenRouter
    embeddings endpoint; the answering model's endpoint is LLM_BASE_URL."""
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.OPENROUTER_BASE_URL, config.LLM_BASE_URL]))")
    base, llm = json.loads(_out(code, LLM_BACKEND="ollama", EMBED_BACKEND="openrouter", OLLAMA_URL="http://127.0.0.1:11434/"))
    assert base == "https://openrouter.ai/api/v1" and llm == "http://127.0.0.1:11434/v1"
    base, llm = json.loads(_out(code, OPENROUTER_BASE_URL="https://example.invalid/v1"))
    assert base == llm == "https://example.invalid/v1"


def test_hosted_embeddings_still_need_the_key_in_the_local_llm_mode():
    """LLM_BACKEND=ollama + EMBED_BACKEND=openrouter: the answering model is local
    but the embeddings are paid, so the key gate stays on."""
    code = "from ask_your_library import preflight; print(preflight.check_api_key() is not None)"
    assert _out(code, LLM_BACKEND="ollama", EMBED_BACKEND="openrouter") == "True"
    assert _out(code, LLM_BACKEND="ollama", EMBED_BACKEND="ollama") == "False"
