"""`hints`: how a printed command looks on each install, decided at call time."""
from ask_your_library import hints, paths
from ask_your_library.i18n import t
from ask_your_library.index_meta import rebuild_hint


def test_a_clone_types_uv_run_and_a_tool_install_does_not(monkeypatch):
    monkeypatch.setattr(paths, "REPO_ROOT", "/some/clone")
    assert hints.command("ayl add") == "uv run ayl add"
    monkeypatch.setattr(paths, "REPO_ROOT", "")
    assert hints.command("ayl add") == "ayl add"
    assert hints.script("scripts/x.py").endswith("from a clone of the repository")


def test_sentences_built_elsewhere_follow_the_install_at_call_time(monkeypatch):
    """The translated installer remedy and the rebuild hints used to be built
    at import, so a test (or anything else) that changed the install after it
    could not reach them."""
    monkeypatch.setattr(paths, "REPO_ROOT", "")
    assert "install-mac.sh" not in t("pf_no_embed_model", model="m")
    assert "`ayl init` pulls the models" in t("pf_no_embed_model", model="m")
    assert "uv run" not in rebuild_hint("transcripts_ollama")
    assert "from a clone of the repository" in rebuild_hint("cards_ollama")
    monkeypatch.setattr(paths, "REPO_ROOT", "/some/clone")
    assert "bash scripts/install-mac.sh" in t("pf_no_ollama", url="u", pulls="p")
    assert "uv run ayl add" in rebuild_hint("transcripts_ollama")


def test_the_configuration_page_is_the_installed_release_s(monkeypatch):
    assert hints.config_docs("0.5.0").endswith("/blob/v0.5.0/docs/configuration.md")
    assert hints.config_docs("unknown").endswith("/blob/main/docs/configuration.md")
