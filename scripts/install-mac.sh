#!/usr/bin/env bash
#
# Ask Your Library — macOS setup (Apple silicon and Intel).
#
# Takes a fresh clone to a working local install: prerequisites, models,
# dependencies, .env, the demo corpus, and the project's own preflight. Nothing
# here runs sudo. What reaches the network: package fetches through brew, uv and
# ollama, and — when you say yes to the demo corpus — the checksum-pinned
# public-domain texts scripts/ingest_demo_corpus.py downloads from gutenberg.org.
# The two LibriVox audiobooks are not fetched: their transcripts are committed
# under corpus/prepared-audio/, so archive.org is reached only by that script's
# --retranscribe. Nothing else leaves this machine.
#
#   bash scripts/install-mac.sh                 # fully local: Ollama answers and embeds
#   bash scripts/install-mac.sh --dry-run       # print the plan, change nothing
#   bash scripts/install-mac.sh --yes           # no confirmation before the demo build
#   bash scripts/install-mac.sh --no-demo       # skip the demo corpus
#   bash scripts/install-mac.sh --hosted        # keep the OpenRouter answering model
#
# Exit codes: 0 done, 1 a prerequisite is missing or a step failed (both are printed
# with the fix), 2 bad usage.
# -E, not just -e: without it the ERR trap below is not inherited by functions,
# command substitutions or subshells, so every failure inside one of them ended
# the script at the failing command's own status with nothing of ours printed.
set -Eeuo pipefail

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

Exit codes: 0 done, 1 a prerequisite is missing or a step failed (both are
printed with the fix), 2 bad usage (an unknown option, or not run from the
repository root).
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

# A failing tool is reported here and the script exits 1 — one of the documented
# codes. Bare "$@" would let `set -e` abort with the tool's own status instead,
# printing nothing of ours: `brew install uv` exiting 17 ended the script at 17.
run() {
    if [ "$dry_run" -eq 1 ]; then
        printf '       would run: %s\n' "$*"
        return 0
    fi
    printf '       running: %s\n' "$*"
    local status=0
    "$@" || status=$?
    if [ "$status" -ne 0 ]; then
        fail "$* failed with status $status."
        fail "fix that and re-run: every step here is idempotent, so nothing is repeated."
        exit 1
    fi
}

# The net under everything `run` does not cover — a cp, a sed, a substitution.
# The ERR trap fires exactly where `set -e` would have exited, so it adds no new
# failure, only the missing message and the documented status. `set -E` above is
# what carries it into functions and substitutions; `run`'s own `|| status=$?`
# still keeps it off the commands `run` wraps, which report themselves once.
on_error() {
    local status=$?
    fail "$BASH_COMMAND failed with status $status."
    exit 1
}
trap on_error ERR

printf 'Ask Your Library — macOS setup\n'
if [ "$dry_run" -eq 1 ]; then
    printf 'Dry run: the plan only. Nothing is installed, downloaded or written.\n'
fi
if [ "$hosted" -eq 1 ]; then
    requested_backend="openrouter"
    requested_mode="hosted"
    printf 'Configuration: hosted answering model (OpenRouter), local embeddings.\n'
else
    requested_backend="ollama"
    requested_mode="fully local"
    printf 'Configuration: fully local — Ollama answers and embeds. No account, no key.\n'
fi
printf '\n'

# --- 1. macOS ---------------------------------------------------------------
os_name="$(uname -s)"
step "macOS: uname reports $os_name $(uname -m)"
if [ "$os_name" != "Darwin" ]; then
    fail "this installer is for macOS only; uname -s reports $os_name."
    fail "on other systems follow the manual Quick start in docs/quick-start.md."
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
# config.py strips trailing slashes before it builds an endpoint out of this
# value; without the same here a URL written with one asks for //api/tags.
while [ "${ollama_url%/}" != "$ollama_url" ]; do ollama_url="${ollama_url%/}"; done
embed_model="$(setting OLLAMA_EMBED_MODEL)"
llm_model="$(setting OLLAMA_LLM_MODEL)"
if [ -z "$ollama_url" ] || [ -z "$embed_model" ] || [ -z "$llm_model" ]; then
    fail "could not read the Ollama defaults from src/ask_your_library/config.py."
    fail "export OLLAMA_URL, OLLAMA_EMBED_MODEL and OLLAMA_LLM_MODEL, then re-run."
    exit 1
fi

# Which backend this run will actually answer with — decided before step 8, and
# by the .env already in the clone when there is one: step 10 never overwrites
# one, so the flag alone would pull a model this run is never going to call and
# expect a key this run is never going to need. Only when there is no .env does
# --hosted (or its absence) decide.
env_backend="$(dotenv_value LLM_BACKEND)"
effective_backend="${env_backend:-$requested_backend}"

# --- 7. Ollama --------------------------------------------------------------
ollama_ready() { curl -fsS --max-time 3 "$ollama_url/api/tags" >/dev/null 2>&1; }

step "Ollama: the binary, and a server answering on $ollama_url/api/tags"
if command -v ollama >/dev/null 2>&1; then
    note "$(command -v ollama)"
else
    note "missing"
    run brew install ollama
fi
ollama_started=0        # this script brought a server up, either way
ollama_service=0        # ... and it was brew services, which the last block names
ollama_pid=""           # ... or a bare `ollama serve`, whose pid is how to stop it
if [ "$dry_run" -eq 1 ]; then
    plan "start it for this session (brew services run ollama, else 'ollama serve')"
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
            # What the server binds is OLLAMA_HOST, not OLLAMA_URL: the URL only
            # says where to look for one. So an exported OLLAMA_HOST decides what
            # the server started here listens on, and putting one on the network
            # is not this script's call. The gate is therefore closed by default:
            # through it go an empty value (Ollama's own loopback default) and the
            # spellings of loopback, with an optional scheme and port — nothing
            # else. A bare port is refused with the rest: ":11434" is a host/port
            # pair whose empty host means every interface, and "0" is 0.0.0.0.
            ollama_bind="${OLLAMA_HOST-}"
            case "$ollama_bind" in
                http://*)  ollama_bind_host="${ollama_bind#http://}" ;;
                https://*) ollama_bind_host="${ollama_bind#https://}" ;;
                *)         ollama_bind_host="$ollama_bind" ;;
            esac
            # Unlike a URL host, a bind address may be a bare ::1 — and that form
            # carries no port, ::1:11434 being an address in its own right; the
            # bracketed form is the one that takes one.
            case "$ollama_bind_host" in
                ""|localhost|localhost:*|127.0.0.1|127.0.0.1:*|"::1"|"[::1]"|"[::1]:"*) ;;
                *)
                    fail "OLLAMA_HOST=$ollama_bind is not one of the loopback forms this script"
                    fail "will start a server on, so it could listen beyond this machine. Run"
                    fail "'unset OLLAMA_HOST' and re-run, or start Ollama yourself with the"
                    fail "binding you want."
                    exit 1
                    ;;
            esac
            # `run`, not `start`: `start` writes a LaunchAgent and brings Ollama
            # up at every login. Making it permanent is the reader's call, and
            # the command for it is printed in the next steps.
            if brew services run ollama >/dev/null 2>&1; then
                note "started for this session: brew services run ollama (no login item)"
                ollama_service=1
            else
                # mktemp, not a fixed name: TMPDIR can be world-writable, and a
                # symlink planted at a name we would pick is a symlink nohup
                # follows.
                serve_log="$(mktemp "${TMPDIR:-/tmp}/ask-your-library-ollama.XXXXXX")"
                note "brew services could not start it; running 'ollama serve' in the background"
                note "server log: $serve_log"
                nohup ollama serve >"$serve_log" 2>&1 &
                ollama_pid=$!
                note "pid $ollama_pid — it outlives this script; the last block stops it"
            fi
            ollama_started=1
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
if [ "$effective_backend" = "ollama" ]; then
    note "$llm_model — answers, a chat model: approximately 3-8 GB depending on the tag"
else
    note "no answering model is pulled: the answering model stays on OpenRouter"
    if [ -n "$env_backend" ] && [ "$requested_backend" = "ollama" ]; then
        note "that is the .env already in this clone deciding, not this run's flags"
    fi
fi
pull_model "$embed_model"
if [ "$effective_backend" = "ollama" ]; then
    pull_model "$llm_model"
fi

# --- 9. dependencies --------------------------------------------------------
step "Dependencies: the locked environment, with the web UI extra"
run uv sync --locked --extra ui

# --- 10. configuration ------------------------------------------------------
local_env() {
    # The lines local mode changes. LLM_TIMEOUT_S is one of them because
    # config.py defaults it to 600 s under LLM_BACKEND=ollama, while a value
    # copied from .env.example is an environment value and wins — which would
    # leave a local model on the hosted 120 s per-attempt budget.
    # QUESTION_DEADLINE_S has no such per-backend default: it is 300 s in both
    # modes, and 300 s is the whole wall clock of a question, checked before each
    # next decision. A local model that loads cold can spend that in the plan
    # node alone, so local mode gets twenty minutes — room for four steps of it.
    # The two tracing lines are uncommented for the same reason docs/configuration.md
    # gives them: this mode is the one where nothing leaves the machine, and the SDK
    # reads a LANGSMITH_/LANGCHAIN_ flag another project's shell exported.
    sed -e 's/^LLM_BACKEND=.*/LLM_BACKEND=ollama/' \
        -e 's/^LLM_TIMEOUT_S=.*/LLM_TIMEOUT_S=600/' \
        -e 's/^QUESTION_DEADLINE_S=.*/QUESTION_DEADLINE_S=1200/' \
        -e 's/^# LANGSMITH_TRACING_V2=false/LANGSMITH_TRACING_V2=false/' \
        -e 's/^# LANGCHAIN_TRACING_V2=false/LANGCHAIN_TRACING_V2=false/' .env.example
}

# Hosted mode keeps the example as it is. A function so it goes through the same
# writer as the local one, and fails the same way.
hosted_env() { cat .env.example; }

# `local_env > .env` truncated .env into existence before the writer produced a
# byte, so a sed that failed — an unreadable .env.example is enough — left an
# empty file behind. And an empty .env is not an obvious ruin: step 10 refuses to
# overwrite a .env that exists, and config.py resolves an empty one to the hosted
# defaults, so the next run of a fully local install came up on OpenRouter and
# said nothing. The output lands beside it instead, and only a complete,
# non-empty file is moved into place.
write_env() {
    local tmp=".env.tmp.$$"
    if "$@" >"$tmp" && [ -s "$tmp" ]; then
        mv "$tmp" .env
        return 0
    fi
    rm -f "$tmp"
    fail "$* wrote no usable .env; the file was left untouched."
    fail "fix that and re-run, or copy .env.example to .env yourself."
    exit 1
}

# What the summary shows — never a key line: this is printed, and .env is where
# a key lives.
SUMMARY_KEYS='LIBRARY_DB_PATH|EMBED_BACKEND|OLLAMA_URL|OLLAMA_EMBED_MODEL'
SUMMARY_KEYS="$SUMMARY_KEYS|LLM_BACKEND|OLLAMA_LLM_MODEL|LLM_TIMEOUT_S|QUESTION_DEADLINE_S"
SUMMARY_KEYS="$SUMMARY_KEYS|LANGSMITH_TRACING_V2|LANGCHAIN_TRACING_V2"

env_summary() {
    # `|| true`: no match is an empty summary, not a failed script under `set -e`.
    { grep -E "^($SUMMARY_KEYS)=" || true; } | while IFS= read -r line; do note "$line"; done
}

step "Configuration: .env in the repository root"
if [ -f .env ]; then
    note ".env exists and is never overwritten; nothing in it was changed"
    if [ -z "$env_backend" ]; then
        note "it sets no LLM_BACKEND, so config.py's own default picks the backend"
    elif [ "$env_backend" = "$requested_backend" ]; then
        note "it sets LLM_BACKEND=$env_backend, which is the mode named at the top"
    else
        note "it sets LLM_BACKEND=$env_backend, so that is the mode this run set up"
        note "the $requested_mode configuration named at the top was NOT applied: an"
        note "existing .env decides. Edit it yourself (or move it aside and re-run)."
    fi
elif [ "$hosted" -eq 1 ]; then
    if [ "$dry_run" -eq 1 ]; then
        plan "copy .env.example to .env unchanged"
        hosted_env | env_summary
    else
        write_env hosted_env
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
        write_env local_env
        note "written from .env.example"
        env_summary < .env
    fi
    note "OPENROUTER_API_KEY stays empty: nothing goes to OpenRouter in this mode."
fi

# --- 11. demo corpus --------------------------------------------------------
db_path="$(setting LIBRARY_DB_PATH)"
if [ -z "$db_path" ]; then
    fail "could not read LIBRARY_DB_PATH from src/ask_your_library/config.py."
    fail "export LIBRARY_DB_PATH, then re-run."
    exit 1
fi
# Used exactly as the package uses it: config.py is Path(os.environ.get(...)) with
# no expanduser, so a literal "~/index" is a directory called "~" for the app and
# has to be one here too — expanding it here would have the two halves of one run
# looking in different places. The ayl-add lines printed below are command lines,
# where the shell expands the tilde long before the package sees the value.
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
    note "about 30 minutes on the first run. It downloads public-domain texts from"
    note "gutenberg.org (checksum-pinned in corpus/manifest.yaml) — the only thing"
    note "here that reaches anywhere but a package registry — and uses the two"
    note "audiobook transcripts already committed under corpus/prepared-audio/, so"
    note "archive.org is not contacted. Every stage is cached in data/, so it is"
    note "safe to interrupt and re-run."
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
#
# It reports every problem the same way, so a bare run says only "something is
# wrong": this run's own leftovers (no index yet, no key yet) would read like an
# unreachable Ollama. The snippet classifies them instead. An expected problem is
# the message check_environment itself would produce for a condition this run
# knowingly left behind, rendered through i18n.t with the same arguments — the
# comparison is against those strings, never against an English fragment.
# Exit: 0 nothing to report, 3 only the missing index, 4 only the missing key,
# 5 both, 1 anything else — including a package that will not import, which is
# what a bad LLM_BACKEND in a pre-existing .env does at config import time.
preflight_code='
import sys

try:
    from ask_your_library.config import DB_PATH, TABLES
    from ask_your_library.i18n import t
    from ask_your_library.preflight import check_environment

    result = check_environment()
except Exception as error:
    print(f"       - the preflight could not run: {type(error).__name__}: {error}")
    raise SystemExit(1)

expected = sys.argv[1].split() if len(sys.argv) > 1 else []
# The only required table is the transcripts one, so the missing-tables message
# preflight would build has exactly that name in it.
no_index = set()
if "no-index" in expected:
    no_index = {t("pf_no_db", path=DB_PATH),
                t("pf_no_tables", path=DB_PATH, tables=TABLES["transcripts"])}
no_key = {t("pf_no_key")} if "no-key" in expected else set()

for problem in result:
    print(f"       - {problem}")
if result.notices:
    notice_header = t("pf_notice_header")
    print(f"       {notice_header}")
    for notice in result.notices:
        print(f"       - {notice}")

problems = set(result)
if not problems:
    raise SystemExit(0)
if problems <= no_index:
    raise SystemExit(3)
if problems <= no_key:
    raise SystemExit(4)
if problems <= no_index | no_key:
    raise SystemExit(5)
raise SystemExit(1)
'

step "Verification: the preflight the CLI runs before every question"
# What this run left for later, and therefore expects to be told about.
preflight_expect=""
if [ "$demo_ready" -eq 0 ]; then
    preflight_expect="no-index"
fi
if [ "$effective_backend" != "ollama" ]; then
    preflight_expect="$preflight_expect no-key"
fi
if [ "$dry_run" -eq 1 ]; then
    plan "run ask_your_library.preflight.check_environment() and report its problems"
else
    preflight_status=0
    uv run python -c "$preflight_code" "$preflight_expect" || preflight_status=$?
    case "$preflight_status" in
        0)
            note "no problems"
            ;;
        3)
            note "the missing index is the only problem, and it is this run's own:"
            note "build the demo corpus, or point LIBRARY_DB_PATH at one of your own"
            note "built with ayl-add."
            ;;
        4)
            note "the missing key is the only problem, and it is expected here:"
            note "set OPENROUTER_API_KEY in .env (or export it) before the first question."
            ;;
        5)
            note "both problems are this run's own: no index yet, and no OPENROUTER_API_KEY."
            note "build the demo corpus (or point LIBRARY_DB_PATH at one of your own), and"
            note "set the key in .env before the first question."
            ;;
        *)
            fail "the preflight reported the problems above."
            exit 1
            ;;
    esac
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
printf '      the web chat on 127.0.0.1, login admin / change-me (the form asks for an\n'
printf '      "Email address": type the username there). That variable is what\n'
printf '      allows the placeholder password; set CHAINLIT_USERNAME and CHAINLIT_PASSWORD\n'
printf '      for a real one and drop it.\n'
printf '  LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books\n'
printf '      index your own .txt / .md books, then ask the same way against that path.\n'
if [ "$ollama_service" -eq 1 ]; then
    printf '  brew services start ollama\n'
    printf '      Ollama was started for this session only. This registers it as a login\n'
    printf '      item instead, so it is up after every restart.\n'
elif [ "$ollama_started" -eq 1 ]; then
    printf "  kill %s                      # or: pkill -f 'ollama serve'\n" "$ollama_pid"
    printf "      brew services could not start Ollama, so it runs here as a background\n"
    printf "      'ollama serve' that outlives this script. Either command stops it; the\n"
    printf '      log is %s. To have it back at every login instead:\n' "$serve_log"
    printf '      brew services start ollama\n'
fi
