# Configuration

Every setting, and how the hosted answering model is switched on if you want one.

The shipped default is fully local: `LLM_BACKEND=ollama` and `EMBED_BACKEND=ollama`, so a fresh
clone answers with no account, no key and nothing to pay. Nothing below has to be set for that;
the [Fully local, no account](#fully-local-no-account) section is what that default does, and
[Cost](cost.md) is about the hosted alternative.

All settings are environment variables (`.env` in the repo root is loaded; exported variables
win). `.env.example` **is** the default configuration — copy it to `.env` and edit from there;
the hosted lines ship commented out with what they cost written beside them.

| Variable | Default | Purpose |
|---|---|---|
| `LIBRARY_DB_PATH` | `data/lancedb` | LanceDB with `cards_<backend>` / `transcripts_<backend>` |
| `EMBED_BACKEND` | `ollama` | `ollama` (local bge-m3) or `openrouter`; also selects the table suffix |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Embedding model, 1024 dims, multilingual |
| `OPENROUTER_EMBED_MODEL` | `openai/text-embedding-3-small` | Embeddings when `EMBED_BACKEND=openrouter`, 1536 dims |
| `LLM_BACKEND` | `ollama` | The default: every agent node runs on a local model through Ollama's OpenAI-compatible endpoint — no account, no key, no cost. `openrouter` sends the question and the retrieved passages to OpenRouter instead, and then a key is required |
| `OLLAMA_LLM_MODEL` | `qwen2.5:14b` | Local model for the agent nodes when `LLM_BACKEND=ollama` (must be pulled; preflight checks). In that mode the answering model runs at `OLLAMA_URL/v1`; `ORCHESTRATOR_MODEL` and `PRICE_*` are not applied; `OLLAMA_PRICE_IN_PER_MTOK` / `OLLAMA_PRICE_OUT_PER_MTOK` (default 0) price the local model if you want to |
| `OPENROUTER_API_KEY` | (unset) | Required when the answering model or the embeddings come from OpenRouter; not needed with `LLM_BACKEND=ollama` and the default local embeddings |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint works; serves the answering model when `LLM_BACKEND=openrouter` and the embeddings when `EMBED_BACKEND=openrouter` |
| `OPENROUTER_ENV_FILE` | (unset) | Opt-in file scanned for the key; never read unless set |
| `ORCHESTRATOR_MODEL` | `anthropic/claude-sonnet-4.6` | Model for all agent nodes **when `LLM_BACKEND=openrouter`**; not applied in the default local mode, where `OLLAMA_LLM_MODEL` decides |
| `MAX_OUTPUT_TOKENS` | `2048` | Hard output cap per call; without it the provider pre-authorizes the model maximum |
| `SEARCH_HIT_CHARS` | `2500` | Characters of each search hit that `observe` sees (and the quote check compares against); 1,200 until 0.1.0 |
| `CHAPTER_HIT_CHARS` | `12000` | Characters of a chapter read that `observe` sees; the cut is marked in-band |
| `MAX_STEPS` | `4` | Search or chapter-read steps per question; the eval fingerprint names it |
| `MAX_EMPTY_STREAK` | `2` | CRAG gate: the loop stops after this many dry steps in a row |
| `MAX_CLARIFY_CANDIDATES` | `5` | Longest list of books a clarify question offers; at most 5, the ordinals the reply resolver understands |
| `LLM_TIMEOUT_S` | `600` (the default backend is local; `120` with `LLM_BACKEND=openrouter`) | Per-attempt read/write timeout of one model call (the SDK's default was 600 s; connect stays 5 s) |
| `LLM_MAX_RETRIES` | `2` | Extra attempts on a timeout or a transient provider error, made by `llm_invoke`'s own loop with the SDK's retries switched off, so every attempt is re-bounded by what is left of the question; an uncapped call then takes up to timeout x (1 + retries) plus backoff, a capped one stops when the budget does (see [Known limits](known-limits.md): a slowly streaming response is not bounded) |
| `QUESTION_DEADLINE_S` | `1200` (the default backend is local; `300` with `LLM_BACKEND=openrouter`) | Time budget per question, checked before each next decision: the loop stops searching and answers from what it found, stop reason shown; a model call that runs out of time inside the budget ends the loop the same way, not the run; clarify waiting time excluded; `0` = none; `ask-library --deadline` overrides it for a run. Like `LLM_TIMEOUT_S` this is `config.py`'s default and a copied `.env` overrides it — `.env.example` and `scripts/install-mac.sh` write the same `1200` for the local mode and `300` for the hosted one |
| `PRICE_IN_PER_MTOK` / `PRICE_OUT_PER_MTOK` | `3.0` / `15.0` | USD per 1M tokens, for the cost estimate; read only when `LLM_BACKEND=openrouter`. The default local backend prices at `OLLAMA_PRICE_*` (0), so its cost lines read $0.0000 |
| `ASK_LANG` | `en` | UI language: `en` or `ua` |
| `ASK_SCRATCH_DIR` | `.scratch` | Where raw-hit scratchpads are written (a human-readable log; `validate` does not read it) |
| `GOLDEN_PATH` | `eval/golden/en-demo.yaml` | Golden set used by both eval harnesses |
| `EVAL_RESULTS_DIR` | `eval/results` | Eval reports and per-question scratchpads |
| `AYL_STRICT_HIT_ID` | `1` | Evidence must name the `hit_id` it was copied from or it is dropped; `0` resolves a missing id by finding the hit that contains the quote (still evidence-based) |
| `LANGCHAIN_API_KEY` / `LANGCHAIN_PROJECT` | (unset) / `ask-your-library` | Setting the key enables LangSmith tracing (`build_graph` sets `LANGCHAIN_TRACING_V2=true`); the SDK also reads `LANGSMITH_API_KEY` with `LANGSMITH_TRACING[_V2]=true` |
| `LANGCHAIN_TRACING_V2` / `LANGSMITH_TRACING_V2` | (unset) | Set both to `false` to keep tracing off whatever the environment inherited: `LANGSMITH_TRACING_V2` is read first, then `LANGCHAIN_TRACING_V2`, then the legacy `*_TRACING` flags |
| `CHAINLIT_USERNAME` / `CHAINLIT_PASSWORD` | `admin` / `change-me` | Web UI login |
| `CHAINLIT_AUTH_SECRET` | generated | Signs login tokens; persisted to `.chainlit/auth-secret` |
| `AYL_CHAINLIT_DIR` | `.chainlit/` next to `ui.py` | Where the UI writes its chat db and auth secret; tests and the canary point it at a temp dir |
| `AYL_ALLOW_DEFAULT_LOGIN` | (unset) | `1` allows the placeholder password (local demo only) |
| `AYL_ALLOW_START_WITHOUT_KEY` | (unset) | `1` lets `ui.py` be imported without an OpenRouter key (tests, the injection canary). The gate it bypasses only exists when a key is needed at all, so it does nothing in the default local configuration; with a hosted answering model or hosted embeddings the server otherwise refuses to start, before anyone can log in |
| `ASK_DEBUG` | (unset) | `1` re-raises CLI errors instead of printing a message |

`ask-library --help` and `ask-library --version` need none of it: they print and exit before
the preflight, so they work in a fresh clone with no key and no index.

### Exit codes

The preflight runs before every question and prints each problem with its remedy. The status it
exits with names the one to fix first, so a script wrapping `ask-library` does not have to match
on translated prose:

| Code | Meaning |
|---|---|
| `0` | an answer |
| `1` | the environment is not ready for a reason with no remedy of its own (an index built by another embedding model), or the run itself failed |
| `2` | a bad command line (argparse's own) |
| `3` | no index yet — build the demo corpus, run `ayl-add`, or point `LIBRARY_DB_PATH` at one |
| `4` | a hosted backend is configured and has no key |
| `5` | Ollama is not reachable, does not answer as Ollama, or a configured model is not pulled |

`3` and `5` are the two ordinary ways a fresh clone fails, and both messages carry the commands
that fix them, `bash scripts/install-mac.sh` included.

## Fully local, no account

This is the shipped default, not a mode to opt into: it is what a clone does with no `.env` and
nothing exported. Where this section says "this README" it means the project
[README](../README.md), and the numbers it means are the ones in that page's
[Measured](../README.md#measured) table — measured on the hosted configuration, not on this one.

Indexing needs no account either: `ayl-add` chunks locally and embeds with Ollama's `bge-m3`.
So the whole system runs on this machine, and there is nothing to set:

```bash
ollama pull qwen2.5:14b                   # the default OLLAMA_LLM_MODEL; or any chat model
uv run ask-library "..."                  # no key, cost lines read $0.0000
uv run --extra ui chainlit run ui.py -w --host 127.0.0.1   # the UI's key gate is off in this mode
```

`bash scripts/install-mac.sh` does the pulls and writes this `.env` for you. Nothing in either
command names a backend, because the local one is the default; `LLM_BACKEND=openrouter` is how
you leave it.

`OLLAMA_LLM_MODEL` picks the model; preflight fails early if it is not pulled (a model pulled as
`name:latest` counts as `name`), and so does `OLLAMA_EMBED_MODEL` whenever embeddings are local —
otherwise a reachable Ollama without `bge-m3` passes every check and fails on the first search.
Preflight also separates the two ways `OLLAMA_URL` can disappoint: nothing answered at all
("could not reach Ollama" — nothing is listening, or the request timed out; start with
`ollama serve` and the URL) versus something that answered but did not answer as `/api/tags` — an
HTTP 4xx/5xx, a body that is not JSON, or an unexpected shape — which usually means something other
than Ollama is on that port, and the message names the status it got. The reply is read whenever
anything runs on Ollama, embeddings included, so a hosted-model setup gets the same early
failure. Everything else is
unchanged: the same graph, the same provenance check, the same eval harness (every report names
the model AND the backend in its fingerprint). What is not the same is quality: every number in
that README was measured on the hosted configuration (`anthropic/claude-sonnet-4.6` via
OpenRouter), and the agent nodes
expect strict JSON, which small local models return less reliably. A malformed reply is retried
once with the parse error shown to the model; if it fails again, `observe` keeps no evidence from
that step, `reflect` stops the loop ("no usable decision") and `plan` searches the raw question
as its one query and says so in the plan step and in the eval report. Measure your model on the
core set before trusting it: `LLM_BACKEND=ollama uv run eval/run_agent_eval.py`. In this mode the answering model is configured by the `OLLAMA_*`
variables only (`OLLAMA_LLM_MODEL`, `OLLAMA_URL`, optional `OLLAMA_PRICE_*`): `ORCHESTRATOR_MODEL`
and the OpenRouter prices in a copied `.env` are OpenRouter settings and are not applied, so
nothing goes to OpenRouter by accident; `OPENROUTER_BASE_URL` keeps serving `EMBED_BACKEND=openrouter`
if you use it. An unknown `LLM_BACKEND` value refuses to start rather than falling back to
either backend. "Nothing leaves the machine" holds with the defaults as shipped — `LLM_BACKEND=ollama`,
`EMBED_BACKEND=ollama`, an `OLLAMA_URL` that points at this machine — and no LangSmith tracing. Tracing is switched on by the environment, and the
SDK reads two prefixes: `build_graph` sets `LANGCHAIN_TRACING_V2=true` whenever `LANGCHAIN_API_KEY` is
present and that variable is unset, and the SDK itself honours `LANGSMITH_TRACING` /
`LANGSMITH_TRACING_V2` with `LANGSMITH_API_KEY`, which another project's shell may have exported. To
keep tracing off whatever the environment inherited, set both `LANGSMITH_TRACING_V2=false` and
`LANGCHAIN_TRACING_V2=false` (the `*_TRACING_V2` variables take precedence over the legacy
`*_TRACING` ones, and the `LANGSMITH_` prefix over `LANGCHAIN_`; `tests/test_tracing_recipe.py` pins
this against the installed SDK). Prompts and retrieved text would otherwise go to LangSmith.
