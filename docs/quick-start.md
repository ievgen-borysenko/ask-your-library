# Quick start

The macOS one-command install is on the [README](../README.md); this page is the same thing
step by step, the path on every other system, and every command the project ships.

## On a Mac, one script does all of the below

```bash
git clone https://github.com/ievgen-borysenko/ask-your-library.git && cd ask-your-library
bash scripts/install-mac.sh --dry-run    # the plan, printed; nothing is changed
bash scripts/install-mac.sh              # mostly download time, + ~30 min for the demo corpus
```

[`scripts/install-mac.sh`](../scripts/install-mac.sh) installs `uv` and Ollama through Homebrew
(whose own install command it prints and never runs for you), starts Ollama for this session
only (`brew services run`, which registers no login item — the one-liner that makes it permanent
is printed at the end), pulls the two models, syncs the locked environment, writes a fully local
`.env`, asks once before the demo corpus, and finishes on the preflight the CLI runs before
every question. `--no-demo`, `--hosted`, `--yes` and `--help` are the rest of it. It never runs
`sudo`. What reaches the network is the package fetches through `brew`, `uv` and `ollama` and,
if you say yes to the demo corpus, the checksum-pinned public-domain texts
[`scripts/ingest_demo_corpus.py`](../scripts/ingest_demo_corpus.py) downloads from gutenberg.org —
the two LibriVox books are not fetched, their transcripts being committed. The manual steps
below are the same thing by hand: the path on every other system, and on a Mac when you would
rather run each step yourself.

One more flag has been added since that paragraph was written: `--print-env-resolution` prints
how the installer resolved every setting that decides where your data goes, with values whose
names look like credentials shown as `<set, N chars>`.

## The manual steps, on any system

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/), [Ollama](https://ollama.com) for
local embeddings, an OpenRouter API key for the answering model (or none at all: see
[Fully local, no account](configuration.md#fully-local-no-account)).

```bash
uv sync                                  # install
ollama pull bge-m3                       # local embedding model (1024 dims)
cp .env.example .env                     # then set OPENROUTER_API_KEY in .env
uv run scripts/ingest_demo_corpus.py     # build the demo corpus (~30 min first run)
```

The ingest is staged and cached in `data/`, so it is safe to interrupt and re-run:
`--stage prepare-text|prepare-audio|prepare-canaries|ingest|cards` runs one stage, `--book <substring>`
re-ingests a single book in place. Sources are checksum-pinned in `corpus/manifest.yaml`
(`--no-verify` to skip). The text path works on any OS; two books come from LibriVox audio and
their Whisper transcripts are committed under `corpus/prepared-audio/`, so the full corpus
builds everywhere. Running the transcription itself (`--retranscribe`) needs macOS with MLX
Whisper.

Your own books instead of (or beside) the demo corpus — see
[Add your own books](add-your-own-books.md):

```bash
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books
LIBRARY_DB_PATH=~/ayl-index uv run ask-library "..."
```

## Ask a question, run the UI, run the evals

```bash
uv run ask-library "What does Marcus Aurelius say about anger?"
uv run ask-library                       # interactive chat with conversation memory
uv run ask-library --verbose "..."        # plus every evidence item with the passage it was checked against

# web UI (Chainlit, same core as the CLI), bound to loopback; throwaway local demo, admin / change-me:
# the login form's first field is labelled "Email address"; type the username there
AYL_ALLOW_DEFAULT_LOGIN=1 uv run --extra ui chainlit run ui.py -w --host 127.0.0.1
# with a real password (the UI refuses to start on the placeholder one):
CHAINLIT_USERNAME=... CHAINLIT_PASSWORD=... uv run --extra ui chainlit run ui.py -w --host 127.0.0.1

# evals
uv run eval/run_retrieval_eval.py        # no LLM calls, free
uv run eval/run_agent_eval.py            # full agentic loop over the golden set
uv run eval/injection_canary.py          # one LLM call (the last stage)
uv run --extra ui eval/injection_canary.py --no-live  # all available stages, no LLM call, free
uv run --group dev pytest -q             # unit tests, the compiled graph end to end with a scripted model, golden-set/manifest guard
```
