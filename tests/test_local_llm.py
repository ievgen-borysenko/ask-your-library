"""LLM_BACKEND=ollama: every agent node runs on a local model through Ollama's
OpenAI-compatible endpoint, with no key, no cost and the local model named in
the fingerprint. Checked in a subprocess so the running interpreter's config is
not reloaded.

Since 10.09.2026 this is also the SHIPPED default, so half of this file is about
what a fresh clone does with nothing configured, and the other half is about the
hosted backend still being exactly what it was when it is asked for by name."""
import json

from conftest import fresh_output as _out, run_fresh as _run


def test_ollama_backend_points_the_client_at_ollama_with_no_key_and_no_price():
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.LLM_BACKEND, config.ORCHESTRATOR_MODEL, config.LLM_BASE_URL, "
            "config.LLM_NEEDS_KEY, config.PRICE_IN_PER_MTOK, config.PRICE_OUT_PER_MTOK]))")
    env = {"LLM_BACKEND": "ollama", "OLLAMA_LLM_MODEL": "qwen2.5:3b", "OLLAMA_URL": "http://localhost:11434"}
    backend, model, base, needs_key, pin, pout = json.loads(_out(code, **env))
    assert (backend, model, base, needs_key, pin, pout) == ("ollama", "qwen2.5:3b", "http://localhost:11434/v1", False, 0.0, 0.0)
    # The hosted backend is unchanged when it is ASKED for, which is now the only
    # way to get it. The endpoint is compared whole: a prefix test against a host
    # name reads as an allow-list check, and https://openrouter.ai.example.com
    # would pass one.
    backend, model, base, needs_key, pin, pout = json.loads(_out(code, LLM_BACKEND="openrouter"))
    assert backend == "openrouter" and needs_key and pin == 3.0 and pout == 15.0
    assert base == "https://openrouter.ai/api/v1" and model == "anthropic/claude-sonnet-4.6"


def test_the_shipped_default_is_the_local_backend():
    """A fresh clone, no .env, nothing exported: a local model, no key needed,
    nothing to pay. The decision of 10.09.2026 — the first run must work with no
    account and no key — as the one assertion that fails if config.py's default
    ever drifts back to the hosted provider.

    The child has LLM_BACKEND unset (conftest scrubs every pinned name before
    run_fresh starts it) and an empty working directory, so what it reads is
    config.py's own default, not the suite's pin and not a .env in the
    checkout."""
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.LLM_BACKEND, config.ORCHESTRATOR_MODEL, config.LLM_BASE_URL, "
            "config.LLM_NEEDS_KEY, config.OPENROUTER_NEEDS_KEY, "
            "config.PRICE_IN_PER_MTOK, config.PRICE_OUT_PER_MTOK]))")
    backend, model, base, llm_key, any_key, pin, pout = json.loads(_out(code))
    assert backend == "ollama"
    assert model == "qwen2.5:14b" and base == "http://localhost:11434/v1"
    # Neither gate is on: not the answering model's, and not the one a hosted
    # embedder would turn on independently of where the answering model runs.
    assert llm_key is False and any_key is False
    assert pin == 0.0 and pout == 0.0


def test_the_shipped_env_example_is_the_local_configuration(tmp_path):
    """.env.example is what a reader copies to .env, so it has to BE the default
    rather than describe it: a copy that came up on OpenRouter would ask for a
    key the documentation says is not needed. Read through config, in a child
    whose working directory holds the copy, so this is the resolution the
    application performs and not a grep of the text."""
    import shutil
    from pathlib import Path

    shutil.copy(Path(__file__).resolve().parents[1] / ".env.example", tmp_path / ".env")
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.LLM_BACKEND, config.LLM_NEEDS_KEY, config.OPENROUTER_NEEDS_KEY, "
            "config.PRICE_IN_PER_MTOK, config.LLM_TIMEOUT_S, config.QUESTION_DEADLINE_S]))")
    backend, llm_key, any_key, price, timeout, deadline = json.loads(_out(code, cwd=str(tmp_path)))
    assert backend == "ollama" and llm_key is False and any_key is False and price == 0.0
    # The local time budgets, written out rather than inherited: a value in a
    # copied .env is an environment value and wins over config.py's per-backend
    # default, so the example carrying the hosted 120 s would have put every
    # local model on a budget meant for a hosted one.
    assert timeout == 600 and deadline == 1200


def test_ollama_backend_needs_no_key_in_preflight_and_in_the_llm_factory():
    code = ("import json; from ask_your_library import preflight, llm; from unittest import mock; "
            "assert preflight.check_api_key() is None; "
            "captured = {}\n"
            "class Fake:\n"
            "    def __init__(self, **kw): captured.update(kw)\n"
            "llm.ChatOpenAI = Fake; llm.llm(); print(json.dumps({k: str(v) for k, v in captured.items()}))")
    kw = json.loads(_out(code, LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen2.5:3b"))
    assert kw["api_key"] == "ollama" and kw["base_url"].endswith("/v1") and kw["model"] == "qwen2.5:3b"


def test_the_local_backend_asks_the_model_not_to_think_and_the_hosted_one_does_not():
    """Ollama does not count a reasoning model's thinking tokens against
    max_tokens, so a thinking model can reason past LLM_TIMEOUT_S and never
    begin its answer. Measured against Ollama 0.33.3, `reasoning_effort: "none"`
    is the one form its OpenAI-compatible endpoint honours; it is inert for a
    model without the thinking capability, so it goes on every local call — and
    it is not sent to the hosted backend, where "none" is not a value every
    model's API takes."""
    code = ("import json; from ask_your_library import llm; "
            "captured = {}\n"
            "class Fake:\n"
            "    def __init__(self, **kw): captured.update(kw)\n"
            "llm.ChatOpenAI = Fake; llm.llm(); print(json.dumps(captured.get('reasoning_effort')))")
    assert json.loads(_out(code, LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen3.6")) == "none"
    assert json.loads(_out(code, LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen2.5:7b")) == "none"
    assert json.loads(_out(code, LLM_BACKEND="openrouter", OPENROUTER_API_KEY="sk-test")) is None


def test_openrouter_backend_still_refuses_without_a_key():
    code = "from ask_your_library import preflight; print(preflight.check_api_key() is not None)"
    assert _out(code, LLM_BACKEND="openrouter") == "True"


def test_an_env_with_the_hosted_block_cannot_send_the_local_mode_to_openrouter(tmp_path):
    """The example ships the OpenRouter model, URL and prices as commented lines
    a reader uncomments to switch. Uncommented — which is the state of anyone
    who has ever tried the hosted mode, and of every .env the installer writes
    under --hosted — they must still be ignored the moment LLM_BACKEND=ollama:
    the local mode is configured by the OLLAMA_* variables alone."""
    import re
    import shutil
    from pathlib import Path
    shutil.copy(Path(__file__).resolve().parents[1] / ".env.example", tmp_path / ".env")
    hosted = re.sub(r"^# (ORCHESTRATOR_MODEL|PRICE_IN_PER_MTOK|PRICE_OUT_PER_MTOK)=",
                    r"\1=", (tmp_path / ".env").read_text(encoding="utf-8"), flags=re.M)
    # The three really are in the file to be uncommented; a silent no-op here
    # would make the rest of this test prove nothing.
    assert "\nORCHESTRATOR_MODEL=anthropic/" in hosted and "\nPRICE_IN_PER_MTOK=3.0" in hosted
    (tmp_path / ".env").write_text(hosted, encoding="utf-8")
    code = ("from ask_your_library import config; import json; "
            "print(json.dumps([config.ORCHESTRATOR_MODEL, config.LLM_BASE_URL, config.PRICE_IN_PER_MTOK]))")
    model, base, price = json.loads(_out(code, cwd=str(tmp_path), LLM_BACKEND="ollama", OLLAMA_LLM_MODEL="qwen2.5:3b"))
    # The endpoint whole, for the reason the test above gives: a prefix test
    # against a URL is the shape of an allow-list check and is not one —
    # http://localhost:11434.evil.example would pass it.
    assert model == "qwen2.5:3b" and base == "http://localhost:11434/v1" and price == 0.0
    # blank values in a .env mean the default, never a crash. Read on the hosted
    # backend, which is the one whose defaults these three names have.
    (tmp_path / ".env").write_text("PRICE_IN_PER_MTOK=\nPRICE_OUT_PER_MTOK= \nORCHESTRATOR_MODEL=\n")
    model, base, price = json.loads(_out(code, cwd=str(tmp_path), LLM_BACKEND="openrouter"))
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
    # And on the hosted backend the two are the same endpoint. Named explicitly:
    # the default is the local backend, where LLM_BASE_URL is Ollama's and this
    # would compare the two halves of the very thing the test separates.
    base, llm = json.loads(_out(code, LLM_BACKEND="openrouter",
                                OPENROUTER_BASE_URL="https://example.invalid/v1"))
    assert base == llm == "https://example.invalid/v1"


def test_hosted_embeddings_still_need_the_key_in_the_local_llm_mode():
    """LLM_BACKEND=ollama + EMBED_BACKEND=openrouter: the answering model is local
    but the embeddings are paid, so the key gate stays on."""
    code = "from ask_your_library import preflight; print(preflight.check_api_key() is not None)"
    assert _out(code, LLM_BACKEND="ollama", EMBED_BACKEND="openrouter") == "True"
    assert _out(code, LLM_BACKEND="ollama", EMBED_BACKEND="ollama") == "False"
