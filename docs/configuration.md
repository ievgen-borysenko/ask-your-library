# Configuration

Every setting, and how to run the whole system on your own machine with no account.

All settings are environment variables (`.env` in the repo root is loaded; exported variables
win). See `.env.example`.

| Variable | Default | Purpose |
|---|---|---|
| `LIBRARY_DB_PATH` | `data/lancedb` | LanceDB with `cards_<backend>` / `transcripts_<backend>` |
| `EMBED_BACKEND` | `ollama` | `ollama` (local bge-m3) or `openrouter`; also selects the table suffix |
| `OLLAMA_URL` | `http://localhost:11434` | Local Ollama endpoint |
| `OLLAMA_EMBED_MODEL` | `bge-m3` | Embedding model, 1024 dims, multilingual |
| `OPENROUTER_EMBED_MODEL` | `openai/text-embedding-3-small` | Embeddings when `EMBED_BACKEND=openrouter`, 1536 dims |
| `LLM_BACKEND` | `openrouter` | `ollama` runs every agent node on a local model through Ollama's OpenAI-compatible endpoint: no key, no cost |
| `OLLAMA_LLM_MODEL` | `qwen2.5:14b` | Local model for the agent nodes when `LLM_BACKEND=ollama` (must be pulled; preflight checks). In that mode the answering model runs at `OLLAMA_URL/v1`; `ORCHESTRATOR_MODEL` and `PRICE_*` are not applied; `OLLAMA_PRICE_IN_PER_MTOK` / `OLLAMA_PRICE_OUT_PER_MTOK` (default 0) price the local model if you want to |
| `OPENROUTER_API_KEY` | (unset) | Required when the answering model or the embeddings come from OpenRouter; not needed with `LLM_BACKEND=ollama` and the default local embeddings |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | Any OpenAI-compatible endpoint works; serves the answering model when `LLM_BACKEND=openrouter` and the embeddings when `EMBED_BACKEND=openrouter` |
| `OPENROUTER_ENV_FILE` | (unset) | Opt-in file scanned for the key; never read unless set |
| `ORCHESTRATOR_MODEL` | `anthropic/claude-sonnet-4.6` | Model for all agent nodes |
| `MAX_OUTPUT_TOKENS` | `2048` | Hard output cap per call; without it the provider pre-authorizes the model maximum |
| `SEARCH_HIT_CHARS` | `2500` | Characters of each search hit that `observe` sees (and the quote check compares against); 1,200 until 0.1.0 |
| `CHAPTER_HIT_CHARS` | `12000` | Characters of a chapter read that `observe` sees; the cut is marked in-band |
| `MAX_STEPS` | `4` | Search or chapter-read steps per question; the eval fingerprint names it |
| `MAX_EMPTY_STREAK` | `2` | CRAG gate: the loop stops after this many dry steps in a row |
| `MAX_CLARIFY_CANDIDATES` | `5` | Longest list of books a clarify question offers; at most 5, the ordinals the reply resolver understands |
| `LLM_TIMEOUT_S` | `120` (`600` with `LLM_BACKEND=ollama`) | Per-attempt read/write timeout of one model call (the SDK's default was 600 s; connect stays 5 s) |
| `LLM_MAX_RETRIES` | `2` | Extra attempts on a timeout or a transient provider error, made by `llm_invoke`'s own loop with the SDK's retries switched off, so every attempt is re-bounded by what is left of the question; an uncapped call then takes up to timeout x (1 + retries) plus backoff, a capped one stops when the budget does (see [Known limits](known-limits.md): a slowly streaming response is not bounded) |
| `QUESTION_DEADLINE_S` | `300` | Time budget per question, checked before each next decision: the loop stops searching and answers from what it found, stop reason shown; clarify waiting time excluded; `0` = none; `ask-library --deadline` overrides it for a run |
| `PRICE_IN_PER_MTOK` / `PRICE_OUT_PER_MTOK` | `3.0` / `15.0` | USD per 1M tokens, for the cost estimate |
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
| `AYL_ALLOW_START_WITHOUT_KEY` | (unset) | `1` lets `ui.py` be imported without an OpenRouter key (tests, the injection canary); the server otherwise refuses to start, before anyone can log in |
| `ASK_DEBUG` | (unset) | `1` re-raises CLI errors instead of printing a message |

`ask-library --help` and `ask-library --version` need none of it: they print and exit before
the preflight, so they work in a fresh clone with no key and no index.

## Fully local, no account

This section is the README's own text, moved here unchanged. Where it says "this README" it
means the project [README](../README.md), and the numbers it means are the ones in that page's
[Measured](../README.md#measured) table.

Indexing your own books needs no account by default: `ayl-add` chunks locally and embeds with Ollama's
`bge-m3` by default. Only the answering model needs OpenRouter. To run everything on this machine:

```bash
ollama pull qwen2.5:14b                        # or any chat model; the default OLLAMA_LLM_MODEL
LLM_BACKEND=ollama uv run ask-library "..."        # no key, cost lines read $0.0000
LLM_BACKEND=ollama uv run --extra ui chainlit run ui.py -w --host 127.0.0.1   # the UI's key gate is off in this mode
```

`OLLAMA_LLM_MODEL` picks the model; preflight fails early if it is not pulled (a model pulled as
`name:latest` counts as `name`), and so does `OLLAMA_EMBED_MODEL` whenever embeddings are local —
otherwise a reachable Ollama without `bge-m3` passes every check and fails on the first search.
Preflight also separates the two ways `OLLAMA_URL` can disappoint: nothing answered at all
("could not reach Ollama" — nothing is listening, or the request timed out; start with
`ollama serve` and the URL) versus something that answered but did not answer as `/api/tags` — an
HTTP 4xx/5xx, a body that is not JSON, or an unexpected shape — which usually means something other
than Ollama is on that port, and the message names the status it got. The reply is read whenever
anything runs on Ollama, embeddings included, so the default hosted-model setup gets the same early
failure. Everything else is
unchanged: the same graph, the same provenance check, the same eval harness (every report names
the local model in its fingerprint). What is not the same is quality: every number in this README
was measured with the OpenRouter default (`anthropic/claude-sonnet-4.6`), and the agent nodes
expect strict JSON, which small local models return less reliably. A malformed reply is retried
once with the parse error shown to the model; if it fails again, `observe` keeps no evidence from
that step, `reflect` stops the loop ("no usable decision") and `plan` searches the raw question
as its one query and says so in the plan step and in the eval report. Measure your model on the
core set before trusting it: `LLM_BACKEND=ollama uv run eval/run_agent_eval.py`. In this mode the answering model is configured by the `OLLAMA_*`
variables only (`OLLAMA_LLM_MODEL`, `OLLAMA_URL`, optional `OLLAMA_PRICE_*`): `ORCHESTRATOR_MODEL`
and the OpenRouter prices in a copied `.env` are OpenRouter settings and are not applied, so
nothing goes to OpenRouter by accident; `OPENROUTER_BASE_URL` keeps serving `EMBED_BACKEND=openrouter`
if you use it. An unknown `LLM_BACKEND` value refuses to start rather than falling back to the
hosted provider. "Nothing leaves the machine" holds with the defaults `EMBED_BACKEND=ollama`, an `OLLAMA_URL` that
points at this machine, and no LangSmith tracing. Tracing is switched on by the environment, and the
SDK reads two prefixes: `build_graph` sets `LANGCHAIN_TRACING_V2=true` whenever `LANGCHAIN_API_KEY` is
present and that variable is unset, and the SDK itself honours `LANGSMITH_TRACING` /
`LANGSMITH_TRACING_V2` with `LANGSMITH_API_KEY`, which another project's shell may have exported. To
keep tracing off whatever the environment inherited, set both `LANGSMITH_TRACING_V2=false` and
`LANGCHAIN_TRACING_V2=false` (the `*_TRACING_V2` variables take precedence over the legacy
`*_TRACING` ones, and the `LANGSMITH_` prefix over `LANGCHAIN_`; `tests/test_tracing_recipe.py` pins
this against the installed SDK). Prompts and retrieved text would otherwise go to LangSmith.
