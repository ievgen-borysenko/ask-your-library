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
# with the fix), 2 bad usage, or a configuration the application would not load —
# an exported variable that contradicts the mode this run sets up, or a .env line
# this script cannot read the way python-dotenv would.
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
Usage: bash scripts/install-mac.sh [--dry-run] [--yes] [--no-demo] [--hosted]
                                   [--print-env-resolution] [--help]

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
  --print-env-resolution
                  debug: print how this script reads the .env it would judge —
                  one `env-resolution<TAB>NAME<TAB>value` record per name, with
                  \\, newlines and tabs escaped — and exit. Installs nothing.
                  It is how the tests hold this reading to python-dotenv's
  --help, -h      this text

Exit codes: 0 done, 1 a prerequisite is missing or a step failed (both are
printed with the fix), 2 bad usage (an unknown option, or not run from the
repository root), a shell whose exported settings contradict the mode — the
application reads .env without overriding what is already exported, so those
values, not this script's, would decide where your data goes — or a .env line
outside the subset this script can read exactly as python-dotenv does.
USAGE
}

dry_run=0
assume_yes=0
want_demo=1
hosted=0
print_resolution=0

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) dry_run=1 ;;
        -y|--yes) assume_yes=1 ;;
        --no-demo) want_demo=0 ;;
        --hosted) hosted=1 ;;
        --print-env-resolution) print_resolution=1 ;;
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

# The model names and the endpoint come from the code, so this script cannot
# pull a model the app will never ask for. Exported value first, then .env, then
# the default in config.py — the order config.py itself resolves them in.
config_default() {
    first_line "$(sed -n "s/.*(\"$1\", *\"\\([^\"]*\\)\").*/\\1/p" src/ask_your_library/config.py)"
}

local_env() {
    # .env.example IS the local configuration now, so the first three
    # substitutions are normally rewrites of a line to itself. They stay, and
    # they are what this function guarantees rather than what it happens to
    # find: the three values below are the ones that decide where a local run's
    # data goes and how long it is given, and this mode may not inherit any of
    # them from a file that has since been edited.
    #   LLM_BACKEND: the whole point of the mode.
    #   LLM_TIMEOUT_S: config.py defaults it to 600 s under LLM_BACKEND=ollama,
    #     but a value in .env is an environment value and wins over that
    #     default — which would leave a local model on the hosted 120 s budget.
    #   QUESTION_DEADLINE_S: per backend by the same rule, and written out for the
    #     same reason. 300 s is the whole wall clock of a question, checked before
    #     each next decision, and a local model that loads cold can spend it in
    #     the plan node alone. Twenty minutes is room for four steps of it.
    # The two tracing lines are uncommented for the reason docs/configuration.md
    # gives: this mode is the one where nothing leaves the machine, and the SDK
    # reads a LANGSMITH_/LANGCHAIN_ flag another project's shell exported.
    sed -e 's/^LLM_BACKEND=.*/LLM_BACKEND=ollama/' \
        -e 's/^LLM_TIMEOUT_S=.*/LLM_TIMEOUT_S=600/' \
        -e 's/^QUESTION_DEADLINE_S=.*/QUESTION_DEADLINE_S=1200/' \
        -e 's/^# LANGSMITH_TRACING_V2=false/LANGSMITH_TRACING_V2=false/' \
        -e 's/^# LANGCHAIN_TRACING_V2=false/LANGCHAIN_TRACING_V2=false/' .env.example
}

# Hosted mode is now the one that transforms: `cat .env.example` used to be the
# hosted configuration and is the local one since the default flipped, so
# copying the file unchanged under --hosted would have written a fully local
# .env and announced it as hosted. The same three lines as above, in the other
# direction, plus the three OpenRouter settings the example ships commented out
# — ORCHESTRATOR_MODEL and the two prices are read only by this backend, and a
# hosted .env without them would leave the model and the cost estimate to
# config.py's defaults instead of stating them where the reader can change them.
# The key line is NOT touched: it stays empty, and the reader fills it in.
hosted_env() {
    sed -e 's/^LLM_BACKEND=.*/LLM_BACKEND=openrouter/' \
        -e 's/^LLM_TIMEOUT_S=.*/LLM_TIMEOUT_S=120/' \
        -e 's/^QUESTION_DEADLINE_S=.*/QUESTION_DEADLINE_S=300/' \
        -e 's/^# ORCHESTRATOR_MODEL=/ORCHESTRATOR_MODEL=/' \
        -e 's/^# PRICE_IN_PER_MTOK=/PRICE_IN_PER_MTOK=/' \
        -e 's/^# PRICE_OUT_PER_MTOK=/PRICE_OUT_PER_MTOK=/' .env.example
}

# --- the configuration the application will actually load -------------------
# Everything from here to the end of this section reads files and decides; it
# installs nothing. It sits BEFORE steps 3-6 on purpose: `brew install uv` and
# `uv python install` download and write, and a run this section is going to
# refuse had already done both by the time the refusal was printed. Nothing
# below needs brew, uv, git or Ollama — only pyproject.toml, config.py and
# .env / .env.example, all of which step 2 has just confirmed are here.
#
# config.py calls load_dotenv() without override, so a variable this shell
# exports wins over every line step 10 writes. A shell already carrying another
# project's hosted settings therefore produced a "fully local" install that
# answered on OpenRouter, embedded on OpenRouter and uploaded traces, while
# every line printed here still said local. The variables below are the ones
# that decide where data goes: which backend answers, which one embeds, the
# endpoint each one calls, and whether prompts and answers are uploaded as
# traces — both prefixes, and the v1 names langchain_core still reads — and the
# LangSmith key, which needs no flag of its own: graph.py turns a key with no
# LANGCHAIN_TRACING_V2 set into LANGCHAIN_TRACING_V2=true before the first node
# runs, so a key alone is a tracing switch that none of the five flags shows.
BACKEND_VARS="LLM_BACKEND EMBED_BACKEND"
ENDPOINT_VARS="OLLAMA_URL OLLAMA_HOST OPENROUTER_BASE_URL LANGCHAIN_ENDPOINT LANGSMITH_ENDPOINT"
# The tracing names are read by two libraries with two different truth tables,
# and one table applied to all of them is what let LANGCHAIN_TRACING=off through.
# V2: langsmith's get_env_var reads these four for "is tracing on", and uploads
# on the exact string "true" — every other value is off.
# V1: langchain_core's env_var_is_set reads these two, and counts a name as SET
# unless its value is "", "0", "false" or "False". A set v1 name with v2 tracing
# off makes CallbackManager.configure() raise RuntimeError before the first
# answer, so "off" and "no" on them are not off at all.
# LANGCHAIN_TRACING is deliberately in both lists: langchain_core reads it as a
# v1 switch and langsmith reads it as the fallback for TRACING_V2, so it has to
# satisfy both rules. TRACING_VARS is the reported and judged list — the union,
# in the order the two prefixes are named everywhere else in this script.
TRACING_V2_VARS="LANGSMITH_TRACING_V2 LANGCHAIN_TRACING_V2 LANGSMITH_TRACING LANGCHAIN_TRACING"
TRACING_V1_VARS="LANGCHAIN_TRACING LANGCHAIN_HANDLER"
TRACING_VARS="LANGSMITH_TRACING_V2 LANGCHAIN_TRACING_V2 LANGSMITH_TRACING LANGCHAIN_TRACING LANGCHAIN_HANDLER"
# LANGCHAIN_API_KEY is the one that is judged. LANGSMITH_API_KEY is reported
# beside it because a reader who has one usually has the other, but nothing in
# this project reads it: graph.py names LANGCHAIN_API_KEY, config.py names
# neither, and no SDK starts tracing on a key with every flag off. Neither
# value is ever printed — see shown_value.
KEY_VARS="LANGCHAIN_API_KEY LANGSMITH_API_KEY"
DATA_FLOW_VARS="$BACKEND_VARS $ENDPOINT_VARS $TRACING_VARS $KEY_VARS"

# The .env the application will read: the one already in the clone, or the one
# step 10 is about to write, resolved once so the guard judges the same text the
# writer produces. An unreadable .env.example is the one case where there is
# nothing to judge — that is step 10's failure to report, with its own message.
# An EMPTY .env is not that case: it is a real resolution in which every value
# is config.py's own default, so a fully local run has to be held to those
# defaults exactly as it is held to any other text. They are the local ones
# since the shipped default flipped, which is why an empty .env now resolves to
# a mode the guard passes rather than to the hosted one it used to refuse — the
# judgement is the same either way, and it is the values that changed.
planned_env_read=1
if [ -f .env ]; then
    planned_env="$(cat .env 2>/dev/null || true)"
    planned_env_source="the .env already in this clone"
elif [ "$hosted" -eq 1 ]; then
    planned_env="$(hosted_env 2>/dev/null || true)"
    planned_env_source="the .env this run writes"
    [ -n "$planned_env" ] || planned_env_read=0
else
    planned_env="$(local_env 2>/dev/null || true)"
    planned_env_source="the .env this run writes"
    [ -n "$planned_env" ] || planned_env_read=0
fi

# --- reading that .env the way the application reads it ----------------------
# python-dotenv is what config.py loads .env with, and it cannot be used here:
# this section runs before uv exists, which is the whole point of it running
# before uv exists. So the subset python-dotenv supports is reproduced in bash
# — no interpreter to find, nothing to install — and every form outside that
# subset stops the run instead of being guessed at. The parser it replaces was
# `sed -n "s/^NAME=//p"`, which handed back LLM_BACKEND="ollama" WITH its
# quotes: not equal to "ollama", so the run classified itself as hosted and
# never applied the local guard at all, while python-dotenv read the same file
# as a local backend with an OpenRouter embedder.
#
# Reproduced: blank lines and # comments; an optional `export ` prefix;
# whitespace around the `=`; unquoted values, where whitespace followed by #
# starts a comment; values in matching single or double quotes, quotes removed,
# with the escapes python-dotenv decodes (\\ and \' inside single quotes;
# those, \" and \a \b \f \n \r \t \v inside double ones).
# Refused, by line number: an unmatched quote (which is also how a multi-line
# value arrives), a ${VAR} interpolation (python-dotenv expands those by
# default and this script will not), a line with no `=`, a name that is not a
# plain identifier, and anything but a comment after a closing quote.
dotenv_names=""
dotenv_trimmed=""
dotenv_scanned=""
dotenv_rest=""

dotenv_refuse() {
    fail "$planned_env_source, line $1: $2."
    fail "the application reads .env with python-dotenv, which would read that line"
    fail "differently from this script — and the difference decides where your data"
    fail "goes, so neither reading is safe to assume. Write the line as NAME=value"
    fail "(quotes optional, matched and closed if used, no \${...}) and re-run."
    exit 2
}

# Trimming through a global instead of a command substitution: this runs over
# every line of the file, and a fork per line is a fork too many.
dotenv_ltrim() {
    dotenv_trimmed="$1"
    while :; do
        case "$dotenv_trimmed" in
            " "*|$'\t'*) dotenv_trimmed="${dotenv_trimmed#?}" ;;
            *) break ;;
        esac
    done
}

dotenv_rtrim() {
    dotenv_trimmed="$1"
    while :; do
        case "$dotenv_trimmed" in
            *" "|*$'\t') dotenv_trimmed="${dotenv_trimmed%?}" ;;
            *) break ;;
        esac
    done
}

# Reads a quoted value out of "$1", which starts with the quote character, into
# dotenv_scanned, and leaves what follows the closing quote in dotenv_rest.
# Returns 1 when the quote is never closed — python-dotenv would then either
# swallow the following lines (its value patterns are DOTALL) or drop the line
# entirely, and neither is something to guess between.
dotenv_scan_quoted() {
    local text="$1" quote value="" index=1 char next
    quote="${text:0:1}"
    while [ "$index" -lt "${#text}" ]; do
        char="${text:index:1}"
        if [ "$char" = "\\" ]; then
            # A backslash always consumes the character after it, so \" does not
            # close a double-quoted value and \\ is not the start of an escape.
            index=$((index + 1))
            [ "$index" -lt "${#text}" ] || return 1
            next="${text:index:1}"
            if [ "$quote" = "'" ]; then
                case "$next" in
                    "\\"|"'") value="$value$next" ;;
                    *) value="$value\\$next" ;;
                esac
            else
                case "$next" in
                    "\\"|"'"|'"') value="$value$next" ;;
                    a) value="$value"$'\a' ;;
                    b) value="$value"$'\b' ;;
                    f) value="$value"$'\f' ;;
                    n) value="$value"$'\n' ;;
                    r) value="$value"$'\r' ;;
                    t) value="$value"$'\t' ;;
                    v) value="$value"$'\v' ;;
                    *) value="$value\\$next" ;;
                esac
            fi
        elif [ "$char" = "$quote" ]; then
            dotenv_scanned="$value"
            dotenv_rest="${text:$((index + 1))}"
            return 0
        else
            value="$value$char"
        fi
        index=$((index + 1))
    done
    return 1
}

# Whitespace python-dotenv counts as whitespace and this script does not. Its
# parser is Python's own class: [^\S\r\n] around the `=` and after `export`,
# `re.sub(r"\s+#.*", "")` for an inline comment, and `rstrip()` at the end of an
# unquoted value — all of which match every character below as well as the space
# and tab the trimming above handles. `LLM_BACKEND=ollama<FF># local` is the
# shape that decides a run: dotenv_values() reads "ollama" because the form feed
# starts the comment, the reading here kept it, LLM_BACKEND never equalled
# "ollama", and the fully local guard was skipped for the whole file — the
# EMBED_BACKEND=openrouter line on the next one with it. Reproducing Python's
# class in bash 3.2 means classifying UTF-8 by hand in whatever locale the run
# inherits, so these are refused by line number instead, wherever on the line
# they appear: the same fail-closed answer the rest of this parser gives a form
# it cannot promise to read exactly. Indexed arrays only — macOS ships bash 3.2,
# which has no associative ones — and the bytes are spelled out in octal so the
# match is on the character and not on a range that a locale might widen.
DOTENV_ODD_WS=($'\013' $'\014' $'\034' $'\035' $'\036' $'\037'
               $'\302\205' $'\302\240' $'\341\232\200'
               $'\342\200\200' $'\342\200\201' $'\342\200\202' $'\342\200\203'
               $'\342\200\204' $'\342\200\205' $'\342\200\206' $'\342\200\207'
               $'\342\200\210' $'\342\200\211' $'\342\200\212'
               $'\342\200\250' $'\342\200\251' $'\342\200\257'
               $'\342\201\237' $'\343\200\200')
DOTENV_ODD_WS_NAME=("a vertical tab (U+000B)"
                    "a form feed (U+000C)"
                    "a file separator (U+001C)"
                    "a group separator (U+001D)"
                    "a record separator (U+001E)"
                    "a unit separator (U+001F)"
                    "a next-line control character (U+0085)"
                    "a non-breaking space (U+00A0)"
                    "a Unicode space character (U+1680)"
                    "a Unicode space character (U+2000)"
                    "a Unicode space character (U+2001)"
                    "a Unicode space character (U+2002)"
                    "a Unicode space character (U+2003)"
                    "a Unicode space character (U+2004)"
                    "a Unicode space character (U+2005)"
                    "a Unicode space character (U+2006)"
                    "a Unicode space character (U+2007)"
                    "a Unicode space character (U+2008)"
                    "a Unicode space character (U+2009)"
                    "a Unicode space character (U+200A)"
                    "a line separator (U+2028)"
                    "a paragraph separator (U+2029)"
                    "a narrow non-breaking space (U+202F)"
                    "a Unicode space character (U+205F)"
                    "an ideographic space (U+3000)")

dotenv_parse() {
    local line number=0 trimmed key value tail odd=0
    dotenv_names=""
    while IFS= read -r line || [ -n "$line" ]; do
        number=$((number + 1))
        line="${line%$'\r'}"            # a CRLF file: that \r is the line ending
        case "$line" in
            *$'\r'*) dotenv_refuse "$number" "a carriage return inside the line" ;;
        esac
        odd=0
        while [ "$odd" -lt "${#DOTENV_ODD_WS[@]}" ]; do
            case "$line" in
                *"${DOTENV_ODD_WS[odd]}"*)
                    dotenv_refuse "$number" \
                        "${DOTENV_ODD_WS_NAME[odd]}, which python-dotenv counts as whitespace"\
" and this script does not read anywhere on a line" ;;
            esac
            odd=$((odd + 1))
        done
        dotenv_ltrim "$line"
        trimmed="$dotenv_trimmed"
        [ -n "$trimmed" ] || continue                   # a blank line
        case "$trimmed" in
            "#"*) continue ;;                           # a comment line
        esac
        case "$trimmed" in
            export" "*|export$'\t'*)
                trimmed="${trimmed#export}"
                dotenv_ltrim "$trimmed"
                trimmed="$dotenv_trimmed"
                ;;
        esac
        case "$trimmed" in
            *"="*) ;;
            *) dotenv_refuse "$number" \
                   "no = on the line, so python-dotenv holds the name with no value at all" ;;
        esac
        dotenv_rtrim "${trimmed%%=*}"
        key="$dotenv_trimmed"
        dotenv_ltrim "${trimmed#*=}"
        value="$dotenv_trimmed"
        case "$key" in
            ""|[0-9]*|*[!A-Za-z0-9_]*)
                dotenv_refuse "$number" \
                    "\"$key\" is not a plain NAME (letters, digits and _, not starting with a digit)" ;;
        esac
        case "$value" in
            '"'*|"'"*)
                if ! dotenv_scan_quoted "$value"; then
                    dotenv_refuse "$number" "the ${value:0:1} quote is never closed on this line"
                fi
                dotenv_ltrim "$dotenv_rest"
                tail="$dotenv_trimmed"
                case "$tail" in
                    ""|"#"*) ;;
                    *) dotenv_refuse "$number" "text after the closing quote that is not a comment" ;;
                esac
                value="$dotenv_scanned"
                ;;
            *)
                # python-dotenv: the rest of the line, then re.sub(r"\s+#.*", "")
                # and rstrip() — so whitespace before a # starts a comment, and a
                # # with no whitespace in front of it is part of the value.
                case "$value" in
                    *" #"*|*$'\t'"#"*)
                        case "$value" in
                            *" #"*) value="${value%%" #"*}" ;;
                        esac
                        case "$value" in
                            *$'\t'"#"*) value="${value%%$'\t'"#"*}" ;;
                        esac
                        ;;
                esac
                dotenv_rtrim "$value"
                value="$dotenv_trimmed"
                ;;
        esac
        case "$value" in
            *'${'*) dotenv_refuse "$number" \
                        "a \${...} interpolation, which python-dotenv expands from the environment" ;;
        esac
        # No associative arrays: this has to run under the bash 3.2 macOS ships.
        # $key is an identifier by the check above, and the right-hand side is a
        # variable, so the assignment neither splits nor globs.
        eval "dotenv_v_$key=\$value"
        case " $dotenv_names " in
            *" $key "*) ;;
            *) dotenv_names="$dotenv_names $key" ;;
        esac
    done <<< "$1"
}

# The names whose VALUE is a credential — one list, because both places that
# print a resolved .env have to agree on it: the guard's summary lines below,
# and --print-env-resolution, which printed every value verbatim and so handed a
# run's OPENROUTER_API_KEY, LANGCHAIN_API_KEY and CHAINLIT_PASSWORD to stdout.
# That is the flag whose whole audience is people pasting its output into a bug
# report. Matched on the shape of the name rather than against the names this
# project happens to use — a .env is the reader's file, and HF_TOKEN or
# CHAINLIT_AUTH_SECRET is as much a credential as the three above — and folded,
# so a lower-case spelling is caught too. It over-matches on purpose: a flag
# whose name ends in _KEY (AYL_ALLOW_START_WITHOUT_KEY) is redacted with the
# keys, because a redacted flag costs a reader one line of a file they have and
# a printed key costs them the key.
is_secret_name() {
    case "$(printf '%s' "$1" | tr '[:lower:]' '[:upper:]')" in
        *_API_KEY|*_KEY|*_TOKEN|*_SECRET|*PASSWORD*|*_PASS) return 0 ;;
        *) return 1 ;;
    esac
}

# The debug flag, and the way the tests prove this parser and python-dotenv
# agree: one record per name, in the order the file defines them, with the
# value escaped so a newline inside one (a \n in a double-quoted value) cannot
# be mistaken for the end of the record. A credential's value is not in the
# record: whether the name is set, and how long the value is, is everything an
# argument about how this file was read turns on.
print_env_resolution() {
    local name variable value out index char
    for name in $dotenv_names; do
        variable="dotenv_v_$name"
        value="${!variable-}"
        if is_secret_name "$name"; then
            if [ -n "$value" ]; then
                printf 'env-resolution\t%s\t<set, %s chars>\n' "$name" "${#value}"
            else
                printf 'env-resolution\t%s\t\n' "$name"
            fi
            continue
        fi
        out=""
        index=0
        while [ "$index" -lt "${#value}" ]; do
            char="${value:index:1}"
            case "$char" in
                "\\") out="$out\\\\" ;;
                $'\n') out="${out}\\n" ;;
                $'\r') out="${out}\\r" ;;
                $'\t') out="${out}\\t" ;;
                *) out="$out$char" ;;
            esac
            index=$((index + 1))
        done
        printf 'env-resolution\t%s\t%s\n' "$name" "$out"
    done
}

if [ "$planned_env_read" -eq 1 ]; then
    dotenv_parse "$planned_env"
fi
if [ "$print_resolution" -eq 1 ]; then
    print_env_resolution
    exit 0
fi

# The value that .env gives a name, as python-dotenv would give it.
planned_value() {
    local variable="dotenv_v_$1"
    printf '%s\n' "${!variable-}"
}

# Whether that .env names the variable at all. python-dotenv fills every name it
# holds a line for, a blank line included, so "set to nothing" and "not
# mentioned" are two different states of the environment — and graph.py reads
# exactly that difference.
dotenv_defines() {
    case " $dotenv_names " in
        *" $1 "*) return 0 ;;
    esac
    return 1
}

setting() {
    local name="$1" value
    value="${!name-}"
    [ -n "$value" ] || value="$(planned_value "$name")"
    [ -n "$value" ] || value="$(config_default "$name")"
    printf '%s\n' "$value"
}

ollama_url="$(setting OLLAMA_URL)"
# config.py strips trailing slashes before it builds an endpoint out of this
# value; without the same here a URL written with one asks for //api/tags.
while [ "${ollama_url%/}" != "$ollama_url" ]; do ollama_url="${ollama_url%/}"; done
embed_model="$(setting OLLAMA_EMBED_MODEL)"
llm_model="$(setting OLLAMA_LLM_MODEL)"
# The download sizes step 8 prints were measured on the two defaults and on
# nothing else, so it has to know whether the model it is about to name IS the
# default. An override gets its name printed with no number beside it: this
# script cannot know what an arbitrary tag weighs, and `ollama pull` says so a
# moment later anyway.
default_embed_model="$(config_default OLLAMA_EMBED_MODEL)"
default_llm_model="$(config_default OLLAMA_LLM_MODEL)"
if [ -z "$ollama_url" ] || [ -z "$embed_model" ] || [ -z "$llm_model" ]; then
    fail "could not read the Ollama defaults from src/ask_your_library/config.py."
    fail "export OLLAMA_URL, OLLAMA_EMBED_MODEL and OLLAMA_LLM_MODEL, then re-run."
    exit 1
fi
# config.py hands OLLAMA_URL to the client as it stands — LLM_BASE_URL is that
# value with /v1 after it — so a value with no scheme is not an address the
# application can call, and "localhost:11434" is the spelling that looks like
# one. Refused here, by name, rather than as a mismatch eleven steps later.
case "$ollama_url" in
    *://*) ;;
    *)
        fail "OLLAMA_URL=$ollama_url has no scheme, and config.py uses the value as it"
        fail "stands: the answering model would be asked for at $ollama_url/v1, which is"
        fail "not an address. Write it in full (http://localhost:11434), or unset"
        fail "OLLAMA_URL to use that default, and re-run."
        exit 2
        ;;
esac

# The mode this run SETS UP — which is what the guard below holds the loaded
# configuration to. Decided by the .env already in the clone when there is one:
# step 10 never overwrites one, so the flag alone would set up a mode the file
# contradicts. Only when there is no .env does --hosted (or its absence) decide.
env_backend=""
if [ -f .env ]; then
    env_backend="$(planned_value LLM_BACKEND)"
fi
setup_backend="${env_backend:-$requested_backend}"
if [ "$setup_backend" = "ollama" ]; then
    setup_mode="fully local"
else
    setup_mode="hosted"
fi

# Set as far as the loader is concerned: exported at any value, an empty one
# included (python-dotenv skips a name that is already in the environment), or
# written in the .env it reads.
env_defines() {
    [ -n "${!1+set}" ] || dotenv_defines "$1"
}

# config.py resolves a blank in two ways, and the difference decides the run.
# _env(NAME, default) reads a blank as "the default was meant"; a plain
# os.environ.get(NAME, default) keeps the blank. So an exported LLM_BACKEND=
# resolves to config.py's own default and never reaches the line in .env — that
# line is not read at all, the name being in the environment already. The
# default it lands on is the local backend now; under --hosted that is the
# mismatch step 12 refuses, and it is the same rule that used to bite the other
# way round when the default was the hosted one.
blank_is_default() {
    case "$1" in
        LLM_BACKEND|OPENROUTER_BASE_URL) return 0 ;;
        *) return 1 ;;
    esac
}

# config.py's own order: an exported variable first, then .env, then the default.
# Exportedness, not emptiness, is what decides the first of the three.
effective_value() {
    local value=""
    if [ -n "${!1+set}" ]; then
        value="${!1}"
    elif dotenv_defines "$1"; then
        value="$(planned_value "$1")"
    else
        config_default "$1"
        return 0
    fi
    if [ -z "$value" ] && blank_is_default "$1"; then
        config_default "$1"
        return 0
    fi
    printf '%s\n' "$value"
}

# Where that value comes from. The exported environment is the only source this
# script cannot rewrite, and the only one whose remedy is `unset`.
value_source() {
    if [ -n "${!1+set}" ]; then
        if [ -z "${!1}" ] && blank_is_default "$1"; then
            printf 'exported empty in this shell, which config.py reads as the default\n'
        else
            printf 'exported in this shell\n'
        fi
    elif dotenv_defines "$1"; then
        printf '%s\n' "$planned_env_source"
    else
        printf 'the default in config.py\n'
    fi
}

# A key is a credential: whether it is set is what decides here, and its value is
# never printed. Everything else is shown as it stands. The list of names is the
# one --print-env-resolution redacts by, so the two cannot disagree about what a
# credential is.
shown_value() {
    if is_secret_name "$1"; then
        if [ -n "$2" ]; then printf '<set>\n'; else printf '\n'; fi
    else
        printf '%s\n' "$2"
    fi
}

# host[:port], compared against the spellings of this machine EXACTLY. A match
# on a prefix read localhost:11434@ollama.example.com as loopback — everything
# in front of the @ is userinfo, and ollama.example.com is the host the request
# actually goes to — so an @ is refused outright here and the caller that has a
# userinfo production (a URL) strips it before calling. Case folded, because a
# host name is case-insensitive and LOCALHOST was being refused. The second
# argument is the one difference between the two readings of "this machine": a
# URL's IPv6 host must be bracketed (::1:11434 is an address in its own right),
# a bind address may be bare.
authority_is_loopback() {
    local authority="$1" allow_bare_ipv6="${2-0}" host port
    case "$authority" in
        *@*) return 1 ;;                        # userinfo, not a host
        */*|*"?"*|*"#"*) return 1 ;;            # a path, query or fragment: not an authority
    esac
    authority="$(printf '%s' "$authority" | tr '[:upper:]' '[:lower:]')"
    if [ "$allow_bare_ipv6" = "1" ] && [ "$authority" = "::1" ]; then
        return 0
    fi
    case "$authority" in
        "["*"]")   host="$authority";                port="" ;;
        "["*"]:"*) host="${authority%%]*}]";         port="${authority#*]:}" ;;
        *:*)       host="${authority%%:*}";          port="${authority#*:}" ;;
        *)         host="$authority";                port="" ;;
    esac
    case "$host" in
        localhost|127.0.0.1|"[::1]") ;;
        *) return 1 ;;
    esac
    case "$port" in
        "") return 0 ;;
        *[!0-9]*) return 1 ;;                   # a port that is not a port: malformed
        *) return 0 ;;
    esac
}

# The endpoint config.py hands to the client, as a URL: the authority is cut out
# of it, and the userinfo with it — http://reader@localhost:11434 IS this
# machine, http://localhost:11434@ollama.example.com is not.
url_is_loopback() {
    local authority="${1#*://}"
    authority="${authority%%/*}"                # the authority only: no path,
    authority="${authority%%\?*}"               # ... no query,
    authority="${authority%%#*}"                # ... no fragment,
    authority="${authority##*@}"                # ... and no userinfo.
    authority_is_loopback "$authority"
}

# OLLAMA_HOST is a host[:port] with an optional scheme, and it has no userinfo
# production at all — so an @ in it is not a user name, it is the text that made
# a prefix match call somebody else's machine loopback.
ollama_host_is_loopback() {
    local value="$1" authority
    [ -n "$value" ] || return 0                 # Ollama's own default is loopback
    case "$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')" in
        http://*|https://*) authority="${value#*://}" ;;
        *://*) return 1 ;;                      # some other scheme: not a form to serve on
        *) authority="$value" ;;
    esac
    authority_is_loopback "$authority" 1
}

# Off in every spelling the v2 flags accept; anything else is tracing on. Wider
# than langsmith's own rule — it uploads on the exact string "true" and reads
# everything else as off — so a value outside both lists ("yes", "1") is refused
# rather than assumed. Failing that way costs a reader one edit; failing the
# other way uploads their library's passages.
tracing_is_off() {
    case "$(printf '%s' "$1" | tr '[:upper:]' '[:lower:]')" in
        ""|false|0|no|off) return 0 ;;
        *) return 1 ;;
    esac
}

# The v1 names, by langchain_core's rule and not by the list above.
# env_var_is_set(name) is `name in os.environ and os.environ[name] not in
# {"", "0", "false", "False"}` — no folding, and "off" is not in it. So
# LANGCHAIN_TRACING=off is SET: CallbackManager.configure() sees v1 tracing on
# with v2 off and raises RuntimeError before the first answer, while the list
# above read the same value as off, reported "tracing: off" and finished the
# install. Case matters here: "false" and "False" are off, "FALSE" is not.
tracing_v1_is_off() {
    case "$1" in
        ""|0|false|False) return 0 ;;
        *) return 1 ;;
    esac
}

# Off for the name it is given, under every rule that reads that name.
# LANGCHAIN_TRACING is in both lists and has to satisfy both.
tracing_flag_is_off() {
    case " $TRACING_V1_VARS " in
        *" $1 "*) tracing_v1_is_off "$2" || return 1 ;;
    esac
    case " $TRACING_V2_VARS " in
        *" $1 "*) tracing_is_off "$2" || return 1 ;;
    esac
    return 0
}

# graph.py's own rule, in the shell. enable_tracing_if_key_present() sets
# LANGCHAIN_TRACING_V2=true whenever LANGCHAIN_API_KEY is not empty and that
# name is not set AT ALL — an empty value counts as set, which is why the .env
# this script writes carries the line rather than leaving it commented out. So a
# key inherited from another project, with no flag anywhere, turns tracing on
# while every flag this script reads still says off.
key_enables_tracing() {
    [ -n "$(effective_value LANGCHAIN_API_KEY)" ] || return 1
    if env_defines LANGCHAIN_TRACING_V2; then return 1; fi
    return 0
}

# Traces actually leaving: one of the four names langsmith reads at a value that
# is not one of the spellings of off, or the key rule above. The v1 names are
# judged separately (v1_tracing_set below): LANGCHAIN_HANDLER cannot turn v2
# tracing on, it can only stop the run with a RuntimeError, so counting it here
# named an upload that would never happen.
tracing_resolves_on() {
    local flag
    for flag in $TRACING_V2_VARS; do
        if ! tracing_is_off "$(effective_value "$flag")"; then return 0; fi
    done
    key_enables_tracing
}

# Where the traces would go. Both names are the same setting under the two
# prefixes; LangSmith has a default endpoint that no variable names.
trace_endpoint() {
    local endpoint
    endpoint="$(effective_value LANGSMITH_ENDPOINT)"
    [ -n "$endpoint" ] || endpoint="$(effective_value LANGCHAIN_ENDPOINT)"
    [ -n "$endpoint" ] || endpoint="https://api.smith.langchain.com (the LangSmith default)"
    printf '%s\n' "$endpoint"
}

# What contradicts "fully local". OLLAMA_HOST is reported but not judged here:
# it decides what a server started by this script binds and which server its
# `ollama pull` talks to, not where the application sends anything, and step 7
# refuses every non-loopback value of it with its own message. OPENROUTER_BASE_URL
# is reported for a similar reason: with both backends on Ollama nothing reads
# it, and a backend that does read it is refused on the backend variable itself.
# The two tracing endpoints are destinations, not switches: they are reported,
# and what is refused is tracing resolving on at all.
contradicts_local() {
    case "$1" in
        LLM_BACKEND|EMBED_BACKEND) [ "$2" != "ollama" ] ;;
        OLLAMA_URL) ! url_is_loopback "$2" ;;
        LANGCHAIN_API_KEY) key_enables_tracing ;;
        LANGSMITH_TRACING_V2|LANGCHAIN_TRACING_V2|LANGSMITH_TRACING|LANGCHAIN_TRACING|LANGCHAIN_HANDLER)
            ! tracing_flag_is_off "$1" "$2" ;;
        *) false ;;
    esac
}

# What each contradiction would do, so the refusal is a consequence and not a
# list of names.
local_effect() {
    case "$1" in
        LLM_BACKEND) printf 'the answering model would run on OpenRouter, not on Ollama\n' ;;
        EMBED_BACKEND) printf 'every passage would be embedded by OpenRouter\n' ;;
        OLLAMA_URL) printf 'that endpoint is not on this machine\n' ;;
        LANGCHAIN_API_KEY)
            printf 'a key with no LANGCHAIN_TRACING_V2 set turns tracing on by itself: '
            printf 'prompts and answers would be uploaded to %s\n' "$(trace_endpoint)" ;;
        LANGCHAIN_TRACING|LANGCHAIN_HANDLER)
            printf 'the v1 names have only 0, false and False as off values, so this is '
            printf 'tracing on: prompts and answers uploaded, or a RuntimeError on the '
            printf 'first model call\n' ;;
        *) printf 'prompts and answers would be uploaded as traces\n' ;;
    esac
}

conflict_names=""
conflict_lines=""
exported_lines=""
for name in $DATA_FLOW_VARS; do
    value="$(effective_value "$name")"
    shown="$(shown_value "$name" "$value")"
    origin="$(value_source "$name")"
    if [ -n "${!name+set}" ]; then
        exported_lines="$exported_lines$name=$shown ($origin)"$'\n'
    fi
    # Nothing to judge when the file that decides could not be read: there is no
    # text to hold anything to, and step 10 stops the run on it with its own
    # message. An empty .env is a different thing — it resolves to config.py's
    # own defaults for real, and those are judged like any other values.
    if [ "$planned_env_read" -eq 1 ] && [ "$setup_mode" = "fully local" ] \
        && contradicts_local "$name" "$value"; then
        conflict_names="$conflict_names $name"
        conflict_lines="$conflict_lines  $name=$shown ($origin) — $(local_effect "$name")"$'\n'
    fi
done

if [ -n "$conflict_names" ]; then
    fail "this run sets up the fully local configuration, but that is not what the"
    fail "application would load. These values decide where your data goes:"
    printf '%s' "$conflict_lines" | while IFS= read -r line; do fail "$line"; done
    exported_conflicts=""
    dotenv_conflicts=""
    for name in $conflict_names; do
        if [ -n "${!name+set}" ]; then
            exported_conflicts="$exported_conflicts $name"
        else
            dotenv_conflicts="$dotenv_conflicts $name"
        fi
    done
    if [ -n "$exported_conflicts" ]; then
        fail "config.py reads .env without overriding what is already exported, so an"
        fail "exported variable wins over every line this script writes."
        fail "remove them from this shell:"
        fail " unset$exported_conflicts"
        unset_flags=""
        for name in $exported_conflicts; do unset_flags="$unset_flags -u $name"; done
        fail "or start the script without them:"
        fail " env$unset_flags bash scripts/install-mac.sh"
    fi
    # Said only of the names that are actually in it: the sentence above is
    # about an exported variable, and printing it over a conflict this shell
    # never exported described the wrong file.
    if [ -n "$dotenv_conflicts" ]; then
        fail "nothing in this shell exports these — each line above names where its"
        fail "value came from. Edit .env (or move it aside and re-run) for:$dotenv_conflicts"
    fi
    case " $conflict_names " in
        *" LANGCHAIN_API_KEY "*)
            fail "the key needs no flag of its own: build_graph sets LANGCHAIN_TRACING_V2=true"
            fail "whenever a key is present and that name is not set at all. Either drop the"
            fail "key, or set LANGCHAIN_TRACING_V2=false — the .env this script writes for the"
            fail "local mode carries that line, so a run with no .env yet is already covered."
            ;;
    esac
    case " $conflict_names " in
        *" LANGCHAIN_TRACING "*|*" LANGCHAIN_HANDLER "*)
            fail "LANGCHAIN_TRACING and LANGCHAIN_HANDLER are the v1 names, and langchain_core"
            fail "reads them with env_var_is_set: every value but 0, false and False counts as"
            fail "set, \"off\" and \"no\" included. Unset the name, or write false."
            ;;
    esac
    fail "to answer on OpenRouter on purpose, run: bash scripts/install-mac.sh --hosted"
    if [ "$dry_run" -eq 1 ]; then
        fail "(dry run: nothing was installed, downloaded or written; a real run stops here too)"
    fi
    exit 2
fi

# OLLAMA_HOST is read twice by ollama and not at all by config.py — the
# application's endpoint is OLLAMA_URL. A server started by step 7 BINDS it, and
# the CLI reads it as the address of the server it talks to, so it is also where
# the `ollama list` and `ollama pull` of step 8 go. Both readings are refused
# beyond loopback: one would put a server on the network, the other would pull
# this run's models onto somebody else's machine. It is judged HERE, with the
# rest of the resolution and before step 3, because that is the only place a
# refusal costs nothing: standing in step 7 it had `brew install uv` and `uv
# python install` in front of it, so a fresh Mac — this script's whole audience —
# had a package manager's worth of software downloaded and written for a run
# that was never going to be allowed to start anything. Nothing in this check
# needs a tool: it reads one exported variable.
# The gate is closed by default: through it go an empty value (Ollama's own
# loopback default) and the spellings of loopback, with an optional scheme and
# port — nothing else. A bare port is refused with the rest: ":11434" is a
# host/port pair whose empty host means every interface, and "0" is 0.0.0.0. The
# host is compared exactly, not by prefix: "localhost:11434@ollama.example.com"
# begins with the loopback spelling and IS ollama.example.com, so `localhost:*`
# let this run's models be pulled onto that machine. ollama_host_is_loopback
# refuses an @ outright — a bind address has no userinfo — along with a port that
# is not digits and anything carrying a path.
ollama_bind="${OLLAMA_HOST-}"
if ! ollama_host_is_loopback "$ollama_bind"; then
    fail "OLLAMA_HOST=$ollama_bind is not one of the loopback forms this script will"
    fail "start a server on, or send an 'ollama pull' to, so it could listen — or"
    fail "fetch — beyond this machine. Run 'unset OLLAMA_HOST' and re-run, or start"
    fail "Ollama yourself with the binding you want."
    exit 1
fi

# Past the guard, so this is the configuration the run is going to carry out —
# and it is the SAME resolver that decides every setup step from here on: which
# models step 8 pulls, whether step 12 expects a missing key, and which
# expectation step 12 holds the loaded configuration to. Reading the flag for
# one of those and the environment for another is how --hosted with an exported
# LLM_BACKEND=ollama pulled no answering model, expected a key it did not need,
# and finished with the first question about to ask a local Ollama for a model
# nothing had pulled.
loaded_backend="$(effective_value LLM_BACKEND)"
loaded_embed_backend="$(effective_value EMBED_BACKEND)"
if [ "$loaded_backend" = "ollama" ]; then
    loaded_mode="fully local"
else
    loaded_mode="hosted"
fi

if [ -n "$exported_lines" ]; then
    printf 'Exported in this shell, and read before .env — this is what decides the run:\n'
    printf '%s' "$exported_lines" | while IFS= read -r line; do note "$line"; done
    if [ "$setup_mode" != "fully local" ]; then
        note "the hosted configuration is what this run sets up, so these are reported only"
    fi
elif [ "$planned_env_read" -eq 1 ]; then
    printf 'Nothing exported in this shell decides where data goes; .env does.\n'
fi

# Only ever reached in the hosted mode: in the local one tracing resolving on is
# a refusal, above. Named with its destination, because a mode that sends the
# question to a provider still does not say anything about a second copy of the
# prompts and the retrieved passages going somewhere else.
if tracing_resolves_on; then
    note "tracing is on: prompts, retrieved passages and answers are uploaded to"
    note "  $(trace_endpoint)"
    note "set LANGCHAIN_TRACING_V2=false (and LANGSMITH_TRACING_V2=false) to stop that"
fi

# And the v1 names, which are not a third spelling of that switch: a set one with
# v2 tracing off is not an upload, it is a RuntimeError out of
# CallbackManager.configure() before the first answer. Reported here rather than
# refused, for the same reason the values above are: the hosted mode reports what
# it finds. In the local mode the same names are a conflict and the run stopped.
v1_tracing_set=""
for name in $TRACING_V1_VARS; do
    if ! tracing_v1_is_off "$(effective_value "$name")"; then
        v1_tracing_set="$v1_tracing_set $name"
    fi
done
if [ -n "$v1_tracing_set" ]; then
    note "set as langchain_core reads it:$v1_tracing_set — it counts every value but 0,"
    note "false and False as tracing on, so the first model call raises RuntimeError"
    note "unless LANGCHAIN_TRACING_V2 is on. Unset those names, or write false."
fi

# --hosted moves the ANSWERING model off this machine and nothing else, so
# wherever the embeddings resolve to is where every passage of the library goes
# — the whole library, not one question. Both halves of that are named here,
# with the destination each resolves to: a remote Ollama endpoint (the .env this
# flag writes keeps EMBED_BACKEND=ollama), and an embedding backend that is not
# Ollama at all. The second one used to print nothing — not even for the
# EMBED_BACKEND=openrouter this run reports two lines above as "reported only".
if [ "$setup_mode" != "fully local" ]; then
    if [ "$loaded_embed_backend" = "ollama" ]; then
        if ! url_is_loopback "$(effective_value OLLAMA_URL)"; then
            note "warning: EMBED_BACKEND=ollama with OLLAMA_URL=$(effective_value OLLAMA_URL), which is"
            note "not on this machine — every passage of your library would be sent there to be"
            note "embedded. --hosted asks for a hosted answering model, not for that. Unset"
            note "OLLAMA_URL, or set EMBED_BACKEND=openrouter if the remote endpoint is meant."
        fi
    else
        if [ "$loaded_embed_backend" = "openrouter" ]; then
            embed_destination="$(effective_value OPENROUTER_BASE_URL)"
        else
            embed_destination="whatever endpoint the $loaded_embed_backend backend calls"
        fi
        note "warning: EMBED_BACKEND=$loaded_embed_backend ($(value_source EMBED_BACKEND)), which is"
        note "not on this machine — every passage of your library would be sent to"
        note "  $embed_destination"
        note "to be embedded. --hosted asks for a hosted answering model, not for that. Set"
        note "EMBED_BACKEND=ollama (the value .env.example ships) to keep the library here."
    fi
fi

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

# --- 7. Ollama --------------------------------------------------------------
ollama_ready() { curl -fsS --max-time 3 "$ollama_url/api/tags" >/dev/null 2>&1; }

step "Ollama: the binary, and a server answering on $ollama_url/api/tags"
# OLLAMA_HOST — what a server started below binds, and where step 8's `ollama
# pull` goes — was judged with the rest of the resolution, before step 3. The
# gate used to sit here, and it sat inside the branch that starts a server, so a
# server already answering skipped it entirely and the pull went to whatever
# machine the variable named.
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
    # Only a server on this machine is ours to start, by the same rule the guard
    # above holds an Ollama endpoint to.
    if ! url_is_loopback "$ollama_url"; then
        fail "nothing answers on $ollama_url, and it is not an address on this machine."
        fail "start Ollama there (or unset OLLAMA_URL to use the default) and re-run."
        exit 1
    fi
    # `run`, not `start`: `start` writes a LaunchAgent and brings Ollama up at
    # every login. Making it permanent is the reader's call, and the command for
    # it is printed in the next steps.
    if brew services run ollama >/dev/null 2>&1; then
        note "started for this session: brew services run ollama (no login item)"
        ollama_service=1
    else
        # mktemp, not a fixed name: TMPDIR can be world-writable, and a symlink
        # planted at a name we would pick is a symlink nohup follows.
        serve_log="$(mktemp "${TMPDIR:-/tmp}/ask-your-library-ollama.XXXXXX")"
        note "brew services could not start it; running 'ollama serve' in the background"
        note "server log: $serve_log"
        nohup ollama serve >"$serve_log" 2>&1 &
        ollama_pid=$!
        note "pid $ollama_pid — it outlives this script; the last block stops it"
    fi
    ollama_started=1
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

# Which models this run needs is the configuration the APPLICATION will load,
# not the flag it was started with: an exported LLM_BACKEND=ollama under
# --hosted is a local answering model, and skipping its pull because the flag
# said hosted left the first question asking Ollama for a model that was never
# fetched. Both halves come from effective_value, the same resolver the guard
# and step 12 use.
step "Models: pull what Ollama does not have yet (the sizes below are approximate)"
if [ "$loaded_embed_backend" = "ollama" ]; then
    # 1.2 GB was measured on bge-m3 and holds for bge-m3. A different
    # OLLAMA_EMBED_MODEL is a different download, and printing 1.2 GB beside it
    # would be a number this script invented.
    if [ "$embed_model" = "$default_embed_model" ]; then
        note "$embed_model — embeddings, approximately 1.2 GB"
    else
        note "$embed_model — embeddings, size depends on the model"
    fi
else
    note "no embedding model is pulled: EMBED_BACKEND=$loaded_embed_backend embeds elsewhere"
fi
if [ "$loaded_backend" = "ollama" ]; then
    # Same rule, and the reason it was written: 9 GB is qwen2.5:14b, the default
    # this script reads out of config.py, and the line used to print it beside
    # whatever name it had resolved — so a 4.7 GB qwen2.5:7b in .env was
    # announced as a 9 GB download.
    if [ "$llm_model" = "$default_llm_model" ]; then
        note "$llm_model — answers, a chat model: approximately 9 GB"
    else
        note "$llm_model — answers, a chat model: size depends on the model"
    fi
else
    note "no answering model is pulled: the answering model stays on OpenRouter"
    if [ -n "$env_backend" ] && [ "$requested_backend" = "ollama" ]; then
        note "that is the .env already in this clone deciding, not this run's flags"
    fi
fi
if [ "$loaded_embed_backend" = "ollama" ]; then
    pull_model "$embed_model"
fi
if [ "$loaded_backend" = "ollama" ]; then
    pull_model "$llm_model"
fi

# --- 9. dependencies --------------------------------------------------------
step "Dependencies: the locked environment, with the web UI extra"
run uv sync --locked --extra ui

# --- 10. configuration ------------------------------------------------------
# `local_env > .env` truncated .env into existence before the writer produced a
# byte, so a sed that failed — an unreadable .env.example is enough — left an
# empty file behind. And an empty .env is not an obvious ruin: step 10 refuses to
# overwrite a .env that exists, and config.py resolves an empty one to its own
# defaults, so what the reader configured was quietly not what ran. That used to
# put a fully local install on OpenRouter; with the default flipped it puts a
# --hosted install on a local model that this run pulled nothing for. Both are
# the same defect, and both are why the output lands beside .env instead, with
# only a complete, non-empty file moved into place.
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
# It also prints the configuration the application resolves — the same import
# the CLI performs, so the run ends with the values the app will use and not
# with the ones step 10 wrote. Those differ whenever a variable is exported:
# config.py loads .env without override. A second argument names the mode the
# effective resolver settled on, and BOTH of its values are checked: a local one
# the loader does not agree with ends the run, and so does a hosted one whose
# answering backend came back local — the run pulled no model for that.
# Exit: 0 nothing to report, 3 only the missing index, 4 only the missing key,
# 5 both, 6 the effective configuration is not the mode this run set up, 1
# anything else — including a package that will not import, which is what a bad
# LLM_BACKEND in a pre-existing .env does at config import time.
preflight_code='
import os
import sys
from urllib.parse import urlsplit

try:
    from ask_your_library.config import (DB_PATH, EMBED_BACKEND, LLM_BACKEND, LLM_BASE_URL,
                                         OLLAMA_URL, TABLES)
    from ask_your_library.graph import enable_tracing_if_key_present
    from ask_your_library.i18n import t
    from ask_your_library.preflight import check_environment
    # The rule that decides the v1 names, imported rather than copied: it is
    # what CallbackManager.configure() itself calls, and a second copy of it
    # here is exactly the drift this check exists to catch.
    from langchain_core.utils.env import env_var_is_set

    # Tracing is not decided by the flags alone. build_graph calls this before
    # the first node, and it turns a LANGCHAIN_API_KEY with no
    # LANGCHAIN_TRACING_V2 set into LANGCHAIN_TRACING_V2=true. Reading the
    # environment without running it reported "off" for a run that traces, so
    # the same function the application uses is run here first, rather than a
    # second copy of its rule that could drift from it.
    enable_tracing_if_key_present()
    result = check_environment()
except Exception as error:
    print(f"       - the preflight could not run: {type(error).__name__}: {error}")
    raise SystemExit(1)

expected = sys.argv[1].split() if len(sys.argv) > 1 else []
mode = sys.argv[2] if len(sys.argv) > 2 else ""
# Both prefixes, and two truth tables rather than one. These four are what
# langsmith reads for "is tracing on", and any value that is not one of these
# spellings of off is taken as an upload.
TRACING = ("LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING",
           "LANGCHAIN_TRACING")
OFF = ("", "false", "0", "no", "off")
tracing_on = [name for name in TRACING
              if os.environ.get(name, "").strip().lower() not in OFF]
# The v1 names are judged by the rule langchain_core applies, not by that list:
# env_var_is_set counts every value but "", "0", "false" and "False" as set, so
# LANGCHAIN_TRACING=off is set. Set, with v2 tracing off, is what makes
# CallbackManager.configure() raise RuntimeError on the first model call — while
# the list above reported "tracing: off" and this run finished.
TRACING_V1 = ("LANGCHAIN_TRACING", "LANGCHAIN_HANDLER")
v1_tracing_set = [name for name in TRACING_V1 if env_var_is_set(name)]
print(f"       LLM_BACKEND={LLM_BACKEND}, EMBED_BACKEND={EMBED_BACKEND}")
print(f"       LLM_BASE_URL={LLM_BASE_URL}, OLLAMA_URL={OLLAMA_URL}")
if tracing_on:
    # A flag says that traces leave; the endpoint says where to. Neither name is
    # required, so the destination of a run that sets neither is the default the
    # LangSmith client falls back to.
    endpoint = (os.environ.get("LANGSMITH_ENDPOINT", "").strip()
                or os.environ.get("LANGCHAIN_ENDPOINT", "").strip()
                or "https://api.smith.langchain.com (the LangSmith default)")
    print("       tracing: " + ", ".join(tracing_on) + " -> " + endpoint)
else:
    print("       tracing: off")
if v1_tracing_set:
    print("       tracing (v1): " + ", ".join(v1_tracing_set) + " is set as "
          "langchain_core reads it — the first model call raises RuntimeError "
          "unless v2 tracing is on")

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

if mode == "local":
    wrong = [f"{name}={value}" for name, value in
             (("LLM_BACKEND", LLM_BACKEND), ("EMBED_BACKEND", EMBED_BACKEND))
             if value != "ollama"]
    if urlsplit(OLLAMA_URL).hostname not in ("localhost", "127.0.0.1", "::1"):
        wrong.append(f"OLLAMA_URL={OLLAMA_URL}")
    wrong += tracing_on
    wrong += [name for name in v1_tracing_set if name not in tracing_on]
    if wrong:
        print("       - the loaded configuration is not the fully local one: "
              + ", ".join(wrong))
        raise SystemExit(6)
elif mode == "hosted":
    # The same check the other way round, which was missing entirely: a hosted
    # run pulled no answering model and expects a key, so a loaded LLM_BACKEND
    # that is not the hosted one is the same mismatch — the first question would
    # ask a local Ollama for a model nothing fetched. Only the answering backend
    # is judged here: where the embeddings go is a warning with its destination
    # named, not a refusal, because hosted embeddings are a supported shape.
    if LLM_BACKEND != "openrouter":
        print("       - the loaded configuration is not the hosted one: "
              f"LLM_BACKEND={LLM_BACKEND}")
        raise SystemExit(6)

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
# config.py's own rule: OPENROUTER_NEEDS_KEY is a hosted answering model OR
# hosted embeddings, so a local backend with EMBED_BACKEND=openrouter needs the
# key too and used to have the missing one reported as an unclassified problem.
if [ "$loaded_backend" != "ollama" ] || [ "$loaded_embed_backend" = "openrouter" ]; then
    preflight_expect="$preflight_expect no-key"
fi
# The expectation the loader is held to, from the same resolver as the pulls
# above: what the application will load, not what the flag asked for. Both
# expectations are checked in the snippet — a hosted run that loads a local
# backend is the mismatch that used to walk through to "Done."
preflight_mode="hosted"
if [ "$loaded_backend" = "ollama" ]; then
    preflight_mode="local"
fi
if [ "$dry_run" -eq 1 ]; then
    plan "run ask_your_library.preflight.check_environment() and report its problems"
    plan "print the configuration ask_your_library.config resolves, and stop the run when"
    plan "it is not the $loaded_mode one this run set up"
else
    preflight_status=0
    uv run python -c "$preflight_code" "$preflight_expect" "$preflight_mode" || preflight_status=$?
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
        6)
            fail "the configuration the application loads is not the $loaded_mode one this"
            fail "run set up — the values printed above are what config.py resolved. It reads"
            fail ".env without overriding what is already exported, so a .env rewrite is no"
            fail "fix: unset the variables named above (or use env -u) and re-run."
            exit 2
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
# The index comes first when there is none: `ask-library` without one exits 3 on
# a preflight that says the same thing, so putting the question at the top of
# this list would hand the reader a command that cannot work yet.
if [ "$demo_ready" -eq 0 ] && [ "$want_demo" -eq 0 ]; then
    # --no-demo: the reader said they have their own books, so the index step is
    # theirs and the demo build is not offered again.
    printf '  LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books\n'
    printf '      index your books first — there is no index yet, and the question below\n'
    printf '      has nothing to search until there is. Ask against the same path:\n'
    printf '      LIBRARY_DB_PATH=~/ayl-index uv run ask-library "..."\n'
elif [ "$demo_ready" -eq 0 ]; then
    printf '  uv run scripts/ingest_demo_corpus.py\n'
    printf '      build the demo corpus first — about 30 minutes. The question below has\n'
    printf '      nothing to search until this finishes. Your own books instead:\n'
    printf '      LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books\n'
fi
printf '  uv run ask-library "What does Marcus Aurelius say about anger?"\n'
# The one sentence this whole mode exists for, printed where the reader is about
# to type the command: no account, no key, nothing to pay. The answering model is
# named because it is the thing that makes that true, and it is the model this
# run actually pulled, not the default this script was written against.
if [ "$loaded_backend" = "ollama" ]; then
    printf '      your first question. No account, no key, nothing to pay: %s answers\n' "$llm_model"
    printf '      it on this machine, and the metrics line under the answer reads $0.0000.\n'
else
    printf '      your first question. Set OPENROUTER_API_KEY in .env before you run it:\n'
    printf '      this run set up the hosted answering model, which needs a key and is\n'
    printf '      billed per question (docs/cost.md). The fully local mode, which needs\n'
    printf '      neither, is what this script sets up without --hosted.\n'
fi
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
