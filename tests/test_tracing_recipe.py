"""The "keep tracing off" recipe of docs/configuration.md, pinned against the installed
LangSmith SDK.

The SDK reads two prefixes (LANGSMITH_ first, then LANGCHAIN_) and prefers the
*_TRACING_V2 variables over the legacy *_TRACING ones, so a shell that
inherited LANGSMITH_TRACING=true from another project would trace despite
LANGCHAIN_TRACING_V2=false. The recipe therefore sets both *_TRACING_V2
variables to false; these tests fail the day an SDK upgrade changes that.
"""
import pytest

from ask_your_library.graph import enable_tracing_if_key_present

RECIPE = {"LANGSMITH_TRACING_V2": "false", "LANGCHAIN_TRACING_V2": "false"}
TRACING_VARS = ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2",
                "LANGSMITH_API_KEY", "LANGCHAIN_API_KEY")


def tracing_enabled() -> bool:
    import langsmith.utils as utils

    utils.get_env_var.cache_clear()          # the SDK caches lookups per process
    return bool(utils.tracing_is_enabled())


@pytest.fixture
def clean_env(monkeypatch):
    for name in TRACING_VARS:
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch


INHERITED = [
    {"LANGSMITH_TRACING": "true", "LANGSMITH_API_KEY": "lsv2_pt_test"},          # snapshot-allow
    {"LANGSMITH_TRACING_V2": "true", "LANGSMITH_API_KEY": "lsv2_pt_test"},       # snapshot-allow
    {"LANGCHAIN_TRACING": "true", "LANGCHAIN_API_KEY": "lsv2_pt_test"},          # snapshot-allow
    {"LANGCHAIN_TRACING_V2": "true", "LANGCHAIN_API_KEY": "lsv2_pt_test"},       # snapshot-allow
]


@pytest.mark.parametrize("inherited", INHERITED, ids=lambda d: next(iter(d)))
def test_an_inherited_tracing_flag_really_traces(clean_env, inherited):
    """The shapes the recipe has to beat: each one switches tracing on by itself,
    as the SDK reads it (asserted before the app's helper runs, which would
    otherwise mask the legacy LANGCHAIN_TRACING case by injecting the V2 flag)."""
    for name, value in inherited.items():
        clean_env.setenv(name, value)
    assert tracing_enabled() is True
    enable_tracing_if_key_present()          # the app adds nothing that switches it off
    assert tracing_enabled() is True


@pytest.mark.parametrize("inherited", INHERITED, ids=lambda d: next(iter(d)))
def test_the_recipe_keeps_tracing_off_whatever_was_inherited(clean_env, inherited):
    for name, value in inherited.items():
        clean_env.setenv(name, value)
    for name, value in RECIPE.items():
        clean_env.setenv(name, value)
    enable_tracing_if_key_present()          # sets LANGCHAIN_TRACING_V2 only when it is unset
    assert tracing_enabled() is False


def test_the_old_recipe_alone_was_not_enough(clean_env):
    """Documents why both variables are needed: LANGSMITH_TRACING_V2 is read first."""
    clean_env.setenv("LANGSMITH_TRACING_V2", "true")
    clean_env.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")   # snapshot-allow
    clean_env.setenv("LANGCHAIN_TRACING_V2", "false")
    assert tracing_enabled() is True


def test_no_flag_no_tracing(clean_env):
    """A key alone (either prefix, no flag) does not trace; the app adds the flag only for LANGCHAIN_API_KEY."""
    clean_env.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")   # snapshot-allow
    assert tracing_enabled() is False
    clean_env.setenv("LANGCHAIN_API_KEY", "lsv2_pt_test")   # snapshot-allow
    enable_tracing_if_key_present()
    assert tracing_enabled() is True
