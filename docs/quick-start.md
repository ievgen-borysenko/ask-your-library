# Quick start

The short version is on the [README](../README.md); this page is the same thing step by step,
what each step does, and every command the project ships.

## The first run: `ayl init`

Requirements: Python 3.11+, [uv](https://docs.astral.sh/uv/) and
[Ollama](https://ollama.com), installed and running — Ollama runs both the embeddings and, in the
default configuration, the answering model. No account and no API key: see
[Fully local, no account](configuration.md#fully-local-no-account).

```bash
git clone https://github.com/ievgen-borysenko/ask-your-library.git && cd ask-your-library
uv sync                                  # the locked environment
uv run ayl init --dry-run                # every step, printed; nothing is pulled, written or built
uv run ayl init                          # check Ollama, pull the models, write the configuration
uv run ayl add ~/books                   # your own .txt / .md books, into your index
uv run ayl ask "..."
```

`ayl init` runs five steps, and each one is skipped when it is already done, so a second run
changes nothing and says so:

1. **Model server** — asks Ollama's `/api/tags` whether it answers and what it has pulled. When
   nothing answers it stops with exit status 5 and the remedy (install, start, or set
   `OLLAMA_URL`).
2. **Mode** — `--mode local` (the default: Ollama answers and embeds, no key) or `--mode hosted`
   (OpenRouter answers, the embeddings stay local, and you set `OPENROUTER_API_KEY` yourself;
   `ayl init` never takes a key). A configuration that already exists decides instead and is
   never rewritten; an exported `LLM_BACKEND` or `EMBED_BACKEND` that contradicts the mode is
   refused (exit 2) before anything changes, because an exported variable would win over the file.
3. **Models** — pulls what that mode needs and Ollama does not have (by default `qwen2.5:14b`,
   9.0 GB, and `bge-m3`; the names come from `OLLAMA_LLM_MODEL` / `OLLAMA_EMBED_MODEL`), with the
   progress streamed. An interrupted pull resumes on the next run.
4. **Configuration** — writes `~/AskYourLibrary/config.env` (`$AYL_HOME/config.env`, readable by
   you only) unless a `.env` in the working directory or that file already exists. It is read
   beneath exported variables and a `.env` ([configuration](configuration.md)).
5. **Libraries** — names your index (`~/AskYourLibrary/index`) and what `ayl add` puts in it. An
   index or chat history an earlier version kept in the clone is reported with the commands that
   move it ([upgrading](upgrading.md#the-index-moved-to-ayl_homeindex)); nothing is moved for you,
   and no second index is built beside it.

Then it runs `ayl doctor` and prints the next commands. `--yes` asks nothing;
`ayl init --print-env-resolution` prints where each setting that decides where your data goes
comes from.

**The demo library.** `ayl init` asks once whether to build it — on a terminal, and no is the
default — or `--demo` builds it and `--no-demo` skips the question. It is six public-domain
classics (`starter: true` in `corpus/manifest.yaml`, chosen to reach every path a first question
takes) built in a few minutes into `~/AskYourLibrary/demo/index`, **apart from your own index**, so
your library never starts mixed with the classics. `--demo --full` builds the whole demo corpus
(33 books and two canaries, about 30 minutes). Ask it by naming it:

```bash
uv run ayl init --demo
LIBRARY_DB_PATH=~/AskYourLibrary/demo/index uv run ayl ask "What does Marcus Aurelius say about anger?"
LIBRARY_DB_PATH=~/AskYourLibrary/demo/index uv run ayl books
```

The demo library is built by [`scripts/ingest_demo_corpus.py`](../scripts/ingest_demo_corpus.py)
(`--starter` for the subset), which ships with the clone and not with the package, so
`ayl init --demo` needs a clone. It downloads the checksum-pinned texts from gutenberg.org — the
two LibriVox books are not fetched, their transcripts being committed — and stages and caches
them in the clone's `data/`, so the build is safe to interrupt: `ayl init --demo` again resumes
it. Run by hand, `ingest_demo_corpus.py` writes whatever `LIBRARY_DB_PATH` names, so name the
demo library (and add `--starter` for the six-book one); run bare, it would aim at your own index,
and it refuses one that holds books `ayl add` indexed:

```bash
LIBRARY_DB_PATH=~/AskYourLibrary/demo/index uv run scripts/ingest_demo_corpus.py --starter --stage ingest
```

It takes `--stage prepare-text|prepare-audio|prepare-canaries|ingest|cards` for one stage,
`--book <substring>` to re-ingest a single book in place, and `--no-verify` to skip the checksum
pins; running the transcription itself (`--retranscribe`) needs macOS with MLX Whisper.

To answer on a hosted model instead, run `ayl init --mode hosted` and set `OPENROUTER_API_KEY` in
the `config.env` it writes. That path costs money per question ([Cost](cost.md)); the local one
does not, and quotes less reliably — the default `qwen2.5:14b` left 1 unattributed and 2 broken
quotes among the 61 checked by code on the run of 2026-09-10
([`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md)). Single run,
nobody graded the answers, and no hosted run is paired with it; the qualified comparison is in
[Known limits](known-limits.md).

Your index is `~/AskYourLibrary/index` — `$AYL_HOME/index`, outside the clone — and
`LIBRARY_DB_PATH` puts it anywhere else ([configuration](configuration.md)); an index an earlier
version built in the clone's `data/lancedb` is read where it is until 0.6.0
([upgrading](upgrading.md#the-index-moved-to-ayl_homeindex)). Adding books is
[Add your own books](add-your-own-books.md); `ayl doctor` reports whether the index and its book
ledger agree.

## On a Mac, one script does the installs too

```bash
bash scripts/install-mac.sh --dry-run    # the plan, printed; nothing is changed
bash scripts/install-mac.sh              # mostly download time
```

[`scripts/install-mac.sh`](../scripts/install-mac.sh) installs `uv` and Ollama through Homebrew
(whose own install command it prints and never runs for you), starts Ollama for this session
only (`brew services run`, which registers no login item — the one-liner that makes it permanent
is printed at the end), pulls the two models, syncs the locked environment, writes the fully local
`.env`, hands the demo library to `ayl init` (which asks its one question), and finishes on the
preflight the CLI runs before every question. `install-mac.sh` also takes `--no-demo`,
`--hosted` (the OpenRouter answering model, which needs a key you set yourself), `--yes` (build
the demo library without asking) and `--help`; its `--print-env-resolution` prints how the
installer resolved every setting that decides where your data goes, with values whose names look
like credentials shown as `<set, N chars>`. It never runs `sudo`. What reaches the network is the package fetches through
`brew`, `uv` and `ollama` and, if you say yes to the demo library, the checksum-pinned texts above.

## Ask a question, run the UI, run the evals

Every command below reads your index; put `LIBRARY_DB_PATH=~/AskYourLibrary/demo/index` in front
of one to aim it at the demo library instead.

```bash
uv run ayl ask "Which book in my library is about a shipwreck?"
uv run ayl ask                           # interactive chat with conversation memory
uv run ayl ask --verbose "..."           # plus every evidence item with the passage it was checked against
uv run ayl books                         # what the index holds, listed by code: no model call, $0
uv run ayl doctor                        # the environment and the index, both halves, nothing written

# web UI (Chainlit, same core as the CLI), bound to loopback; throwaway local demo, admin / change-me:
# the login form's first field is labelled "Email address"; type the username there
AYL_ALLOW_DEFAULT_LOGIN=1 uv run --extra ui ayl ui -w
# with a real password (the UI refuses to start on the placeholder one):
CHAINLIT_USERNAME=... CHAINLIT_PASSWORD=... uv run --extra ui ayl ui -w

# evals
uv run eval/run_retrieval_eval.py        # no LLM calls, free
uv run eval/run_agent_eval.py            # full agentic loop over the golden set
uv run eval/injection_canary.py          # one LLM call (the last stage; free on the local backend)
uv run --extra ui eval/injection_canary.py --no-live  # all available stages, no LLM call, free
uv run eval/scope_canary.py --live       # out-of-scope requests + the in-scope controls, on the configured model
uv run eval/scope_canary.py --no-live    # the same set on the scripted backend: mechanics, no LLM call, free
uv run --group dev pytest -q             # unit tests, the compiled graph end to end with a scripted model, golden-set/manifest guard
uv run playwright install chromium      # once: the browser tests/ui drives (not a Python package)
uv run --group dev --extra ui pytest -q tests/ui  # the web UI's release walkthrough in a browser,
                                        # desktop and phone, against a scripted backend (no model, no index)
```

`ayl --help` lists the commands and `ayl <command> --help` prints what one of them accepts;
`ayl add`, `ayl backup`, `ayl restore` and `ayl doctor` take the flags of
[Add your own books](add-your-own-books.md) and [Upgrading](upgrading.md). The two names `ayl`
replaced — `ask-library` and `ayl-add` — are still installed and still run the same code; each
prints one deprecation line and is removed at `0.6.0`.
