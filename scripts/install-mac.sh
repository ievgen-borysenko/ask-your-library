#!/usr/bin/env bash
#
# Ask Your Library — macOS setup (Apple silicon and Intel).
#
# Takes a fresh clone to a working local install: prerequisites, models,
# dependencies, .env, the demo corpus, and the project's own preflight. Every
# download goes through brew, uv or ollama; nothing here runs sudo, and nothing
# leaves this machine beyond those package fetches.
#
#   bash scripts/install-mac.sh                 # fully local: Ollama answers and embeds
#   bash scripts/install-mac.sh --dry-run       # print the plan, change nothing
#   bash scripts/install-mac.sh --yes           # no confirmation before the demo build
#   bash scripts/install-mac.sh --no-demo       # skip the demo corpus
#   bash scripts/install-mac.sh --hosted        # keep the OpenRouter answering model
#
# Exit codes: 0 done, 1 a prerequisite is missing (the fix is printed), 2 bad usage.
set -euo pipefail

STEPS=12
step_no=0
# How long a freshly started Ollama gets to answer on /api/tags.
OLLAMA_WAIT_S=60

step() {
    step_no=$((step_no + 1))
    printf '[%d/%d] %s\n' "$step_no" "$STEPS" "$1"
}

note() { printf '       %s\n' "$1"; }
plan() { printf '       would %s\n' "$1"; }
fail() { printf 'error: %s\n' "$1" >&2; }

# The first line of a possibly multi-line value. `| head -1` would be shorter,
# but `set -o pipefail` turns the SIGPIPE it can send the writer into a failure.
first_line() { printf '%s\n' "${1%%$'\n'*}"; }

usage() {
    cat <<'USAGE'
Usage: bash scripts/install-mac.sh [--dry-run] [--yes] [--no-demo] [--hosted] [--help]

Sets up Ask Your Library on macOS: uv and Ollama through Homebrew, the two
models, the locked dependencies, a .env, and (optionally) the demo corpus.
Run it from the repository root.

  --dry-run       print the plan and exit; reads files, changes nothing, installs
                  nothing, and never invokes brew, uv or ollama
  --yes, -y       do not ask before the demo corpus build (about 30 minutes)
  --no-demo       skip the demo corpus; the script prints how to index a folder of
                  your own books instead
  --hosted        write the hosted configuration (OpenRouter answering model)
                  instead of the fully local one. The key is never taken on the
                  command line: the script names the variable to set
  --help, -h      this text

Exit codes: 0 done, 1 a prerequisite is missing (the fix is printed),
2 bad usage (an unknown option, or not run from the repository root).
USAGE
}

dry_run=0
assume_yes=0
want_demo=1
hosted=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) dry_run=1 ;;
        -y|--yes) assume_yes=1 ;;
        --no-demo) want_demo=0 ;;
        --hosted) hosted=1 ;;
        -h|--help) usage; exit 0 ;;
        *) fail "unknown option: $1"; usage >&2; exit 2 ;;
    esac
    shift
done

run() {
    if [ "$dry_run" -eq 1 ]; then
        printf '       would run: %s\n' "$*"
        return 0
    fi
    printf '       running: %s\n' "$*"
    "$@"
}

printf 'Ask Your Library — macOS setup\n'
if [ "$dry_run" -eq 1 ]; then
    printf 'Dry run: the plan only. Nothing is installed, downloaded or written.\n'
fi
if [ "$hosted" -eq 1 ]; then
    printf 'Configuration: hosted answering model (OpenRouter), local embeddings.\n'
else
    printf 'Configuration: fully local — Ollama answers and embeds. No account, no key.\n'
fi
printf '\n'

# --- 1. macOS ---------------------------------------------------------------
os_name="$(uname -s)"
step "macOS: uname reports $os_name $(uname -m)"
if [ "$os_name" != "Darwin" ]; then
    fail "this installer is for macOS only; uname -s reports $os_name."
    fail "on other systems follow the manual Quick start in README.md."
    exit 1
fi

# --- 2. repository root -----------------------------------------------------
step "Repository root: this project's pyproject.toml in the working directory"
if [ ! -f pyproject.toml ] || ! grep -q '^name = "ask-your-library"' pyproject.toml; then
    # Where the clone is, for the message only; empty when $0 says nothing useful.
    script_root="$(cd "$(dirname "$0")/.." 2>/dev/null && pwd)" || script_root=""
    fail "no ask-your-library pyproject.toml here. Run the script from the clone root:"
    if [ -n "$script_root" ]; then
        fail "  cd \"$script_root\" && bash scripts/install-mac.sh"
    fi
    exit 2
fi
note "$(pwd)"

# --- 3. Homebrew ------------------------------------------------------------
step "Homebrew: brew on PATH (it installs uv and Ollama)"
if ! command -v brew >/dev/null 2>&1; then
    # Both standard prefixes: /opt/homebrew on Apple silicon, /usr/local on Intel.
    for brew_prefix in /opt/homebrew /usr/local; do
        if [ -x "$brew_prefix/bin/brew" ]; then
            note "$brew_prefix/bin/brew exists but is not on PATH; used for this run"
            note "make that permanent: eval \"\$($brew_prefix/bin/brew shellenv)\""
            PATH="$brew_prefix/bin:$PATH"
            export PATH
            break
        fi
    done
fi
if ! command -v brew >/dev/null 2>&1; then
    brew_install_url='https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh'
    fail "Homebrew is missing. Install it yourself with the official command:"
    printf '  /bin/bash -c "$(curl -fsSL %s)"\n' "$brew_install_url" >&2
    fail "(from https://brew.sh — this script never runs it for you), then re-run."
    exit 1
fi
note "$(command -v brew)"

# --- 4. Git -----------------------------------------------------------------
step "Git: git on PATH (part of the Command Line Tools)"
if ! command -v git >/dev/null 2>&1; then
    fail "git is missing. Install the Command Line Tools, then re-run:"
    fail "  xcode-select --install"
    exit 1
fi
note "$(command -v git)"

# --- 5. uv ------------------------------------------------------------------
step "uv: uv on PATH (it provides Python and the locked dependencies)"
if command -v uv >/dev/null 2>&1; then
    note "$(command -v uv)"
else
    note "missing"
    run brew install uv
fi

# --- 6. Python --------------------------------------------------------------
step "Python: the version pyproject.toml requires, provided by uv"
python_req="$(sed -n 's/^requires-python *= *">=\([0-9][0-9.]*\)".*/\1/p' pyproject.toml)"
python_req="$(first_line "$python_req")"
if [ -z "$python_req" ]; then
    fail "could not read requires-python from pyproject.toml. Install an interpreter"
    fail "yourself (uv python install <version>) and re-run."
    exit 1
fi
note "requires-python >=$python_req"
if [ "$dry_run" -eq 1 ]; then
    plan "check 'uv python find >=$python_req'"
    plan "run 'uv python install $python_req' when no interpreter answers that"
elif uv python find ">=$python_req" >/dev/null 2>&1; then
    note "an interpreter >=$python_req is already available to uv"
else
    run uv python install "$python_req"
fi

# The model names and the endpoint come from the code, so this script cannot
# pull a model the app will never ask for. Exported value first, then .env, then
# the default in config.py — the order config.py itself resolves them in.
config_default() {
    first_line "$(sed -n "s/.*(\"$1\", *\"\\([^\"]*\\)\").*/\\1/p" src/ask_your_library/config.py)"
}

dotenv_value() {
    [ -f .env ] || return 0
    first_line "$(sed -n "s/^$1=//p" .env)"
}

setting() {
    local name="$1" value
    value="${!name-}"
    [ -n "$value" ] || value="$(dotenv_value "$name")"
    [ -n "$value" ] || value="$(config_default "$name")"
    printf '%s\n' "$value"
}

ollama_url="$(setting OLLAMA_URL)"
embed_model="$(setting OLLAMA_EMBED_MODEL)"
llm_model="$(setting OLLAMA_LLM_MODEL)"
if [ -z "$ollama_url" ] || [ -z "$embed_model" ] || [ -z "$llm_model" ]; then
    fail "could not read the Ollama defaults from src/ask_your_library/config.py."
    fail "export OLLAMA_URL, OLLAMA_EMBED_MODEL and OLLAMA_LLM_MODEL, then re-run."
    exit 1
fi

# --- 7. Ollama --------------------------------------------------------------
ollama_ready() { curl -fsS --max-time 3 "$ollama_url/api/tags" >/dev/null 2>&1; }

step "Ollama: the binary, and a server answering on $ollama_url/api/tags"
if command -v ollama >/dev/null 2>&1; then
    note "$(command -v ollama)"
else
    note "missing"
    run brew install ollama
fi
if [ "$dry_run" -eq 1 ]; then
    plan "start it (brew services start ollama, else 'ollama serve' in the background)"
    plan "wait up to ${OLLAMA_WAIT_S}s for $ollama_url/api/tags to answer"
elif ollama_ready; then
    note "already answering"
else
    # Only a server on this machine is ours to start. Quoted patterns are
    # literal, which the IPv6 form needs: bare [::1] is a bracket expression.
    ollama_host="${ollama_url#*//}"
    ollama_host="${ollama_host%%/*}"
    case "$ollama_host" in
        localhost|localhost:*|127.0.0.1|127.0.0.1:*|"[::1]"|"[::1]:"*)
            if brew services start ollama >/dev/null 2>&1; then
                note "started: brew services start ollama"
            else
                serve_log="${TMPDIR:-/tmp}/ask-your-library-ollama.log"
                note "brew services could not start it; running 'ollama serve' in the background"
                note "server log: $serve_log"
                nohup ollama serve >"$serve_log" 2>&1 &
            fi
            ;;
        *)
            fail "nothing answers on $ollama_url, and it is not an address on this machine."
            fail "start Ollama there (or unset OLLAMA_URL to use the default) and re-run."
            exit 1
            ;;
    esac
    waited=0
    while [ "$waited" -lt "$OLLAMA_WAIT_S" ] && ! ollama_ready; do
        sleep 1
        waited=$((waited + 1))
    done
    if ! ollama_ready; then
        fail "Ollama did not answer on $ollama_url/api/tags within ${OLLAMA_WAIT_S}s."
        fail "start it in another terminal ('ollama serve'), then re-run."
        exit 1
    fi
    note "answering after ${waited}s"
fi

# --- 8. models --------------------------------------------------------------
pull_model() {
    local model="$1"
    if [ "$dry_run" -eq 1 ]; then
        plan "run: ollama pull $model (skipped when it is already pulled)"
        return 0
    fi
    # A model pulled as `name:latest` counts as `name`, the rule preflight applies.
    local name
    while read -r name _; do
        case "$name" in
            "$model"|"$model:latest")
                note "$model is already pulled"
                return 0
                ;;
        esac
    done <<< "$(ollama list 2>/dev/null || true)"
    run ollama pull "$model"
}

step "Models: pull what Ollama does not have yet (the sizes below are approximate)"
note "$embed_model — embeddings, approximately 1.2 GB"
if [ "$hosted" -eq 1 ]; then
    note "no answering model is pulled: --hosted keeps it on OpenRouter"
else
    note "$llm_model — answers, a chat model: approximately 3-8 GB depending on the tag"
fi
pull_model "$embed_model"
if [ "$hosted" -eq 0 ]; then
    pull_model "$llm_model"
fi

# --- 9. dependencies --------------------------------------------------------
step "Dependencies: the locked environment, with the web UI extra"
run uv sync --locked --extra ui

# --- 10. configuration ------------------------------------------------------
local_env() {
    # The only two lines local mode changes. LLM_TIMEOUT_S is one of them because
    # config.py defaults it to 600 s under LLM_BACKEND=ollama, while a value
    # copied from .env.example is an environment value and wins — which would
    # leave a local model on the hosted 120 s per-attempt budget.
    sed -e 's/^LLM_BACKEND=.*/LLM_BACKEND=ollama/' \
        -e 's/^LLM_TIMEOUT_S=.*/LLM_TIMEOUT_S=600/' .env.example
}

# What the summary shows — never a key line: this is printed, and .env is where
# a key lives.
SUMMARY_KEYS='LIBRARY_DB_PATH|EMBED_BACKEND|OLLAMA_URL|OLLAMA_EMBED_MODEL'
SUMMARY_KEYS="$SUMMARY_KEYS|LLM_BACKEND|OLLAMA_LLM_MODEL|LLM_TIMEOUT_S"

env_summary() {
    # `|| true`: no match is an empty summary, not a failed script under `set -e`.
    { grep -E "^($SUMMARY_KEYS)=" || true; } | while IFS= read -r line; do note "$line"; done
}

step "Configuration: .env in the repository root"
if [ -f .env ]; then
    note ".env exists and is never overwritten; nothing in it was changed"
    note "it sets LLM_BACKEND=$(dotenv_value LLM_BACKEND)"
elif [ "$hosted" -eq 1 ]; then
    if [ "$dry_run" -eq 1 ]; then
        plan "copy .env.example to .env unchanged"
        env_summary < .env.example
    else
        cp .env.example .env
        note "written from .env.example"
        env_summary < .env
    fi
    note "OPENROUTER_API_KEY is left empty on purpose. Set it in .env (or export it)"
    note "before the first question; this script never takes a key as an argument."
else
    if [ "$dry_run" -eq 1 ]; then
        plan "write .env from .env.example with these values"
        local_env | env_summary
    else
        local_env > .env
        note "written from .env.example"
        env_summary < .env
    fi
    note "OPENROUTER_API_KEY stays empty: nothing goes to OpenRouter in this mode."
fi

# --- 11. demo corpus --------------------------------------------------------
db_path="$(setting LIBRARY_DB_PATH)"
case "$db_path" in "~/"*) db_path="$HOME/${db_path#\~/}" ;; esac
demo_ready=0
for table in "$db_path"/transcripts_*.lance; do
    [ -e "$table" ] || continue
    demo_ready=1
done

step "Demo corpus: an index at $db_path"
if [ "$want_demo" -eq 0 ]; then
    note "skipped (--no-demo). Index a folder of your own .txt / .md books instead:"
    note "  LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books"
    note "  LIBRARY_DB_PATH=~/ayl-index uv run ask-library \"...\""
elif [ "$demo_ready" -eq 1 ]; then
    note "an index is already there; nothing is rebuilt"
    note "update it later with: uv run scripts/ingest_demo_corpus.py"
else
    note "about 30 minutes on the first run. It downloads public-domain texts"
    note "(checksum-pinned in corpus/manifest.yaml) and uses the two audiobook"
    note "transcripts already committed under corpus/prepared-audio/. Every stage is"
    note "cached in data/, so it is safe to interrupt and re-run."
    build_demo=0
    if [ "$dry_run" -eq 1 ]; then
        plan "ask once for confirmation, then run: uv run scripts/ingest_demo_corpus.py"
    elif [ "$assume_yes" -eq 1 ]; then
        build_demo=1
    elif [ ! -t 0 ]; then
        note "no terminal to ask on, so it was skipped; re-run with --yes to build it."
    else
        printf '       Build it now? [y/N] '
        reply=""
        read -r reply || true
        case "$reply" in
            [yY]|[yY][eE][sS]) build_demo=1 ;;
            *) note "skipped. Build it later: uv run scripts/ingest_demo_corpus.py" ;;
        esac
    fi
    if [ "$build_demo" -eq 1 ]; then
        run uv run scripts/ingest_demo_corpus.py
        demo_ready=1
    fi
fi

# --- 12. verification -------------------------------------------------------
# check_environment() is what the CLI runs before every question: the key when
# one is needed, Ollama reachable with both models pulled, a database with the
# expected tables and a matching index fingerprint. No model call, no cost.
preflight_code='
from ask_your_library.preflight import check_environment

problems = check_environment()
for problem in problems:
    print(f"       - {problem}")
raise SystemExit(1 if problems else 0)
'

step "Verification: the preflight the CLI runs before every question"
if [ "$dry_run" -eq 1 ]; then
    plan "run ask_your_library.preflight.check_environment() and report its problems"
elif uv run python -c "$preflight_code"; then
    note "no problems"
elif [ "$hosted" -eq 1 ]; then
    note "expected until OPENROUTER_API_KEY is set; everything else is in place."
elif [ "$demo_ready" -eq 0 ]; then
    note "expected without an index: build the demo corpus, or point LIBRARY_DB_PATH"
    note "at one of your own built with ayl-add."
else
    fail "the preflight reported the problems above."
    exit 1
fi

printf '\n'
if [ "$dry_run" -eq 1 ]; then
    printf 'Dry run finished. Nothing was installed, downloaded or written.\n'
else
    printf 'Done.\n'
fi
printf 'Next steps:\n'
printf '  uv run ask-library "What does Marcus Aurelius say about anger?"\n'
printf '  AYL_ALLOW_DEFAULT_LOGIN=1 uv run --extra ui chainlit run ui.py -w --host 127.0.0.1\n'
printf '      the web chat on 127.0.0.1, login admin / change-me. That variable is what\n'
printf '      allows the placeholder password; set CHAINLIT_USERNAME and CHAINLIT_PASSWORD\n'
printf '      for a real one and drop it.\n'
printf '  LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books\n'
printf '      index your own .txt / .md books, then ask the same way against that path.\n'
