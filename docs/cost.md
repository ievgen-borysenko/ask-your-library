# Cost

The orchestrator is Claude Sonnet via OpenRouter by default. A typical question costs roughly
**$0.04-0.05 per question on the demo set** at v0.2.0-rc1 (core mean $0.049, extended $0.043;
$0.03-0.04 at v0.1.0, before the 2,500-character window and the coverage gate): 4 to 12 LLM calls
(plan, then one observe and one reflect per step up to the 4-step budget, then synthesize; one more
plan call after a clarify),
dominated by input tokens from the distillation prompts. `validate` is free - it is plain code.
Output is capped by `MAX_OUTPUT_TOKENS` (2048), which matters: without a cap the provider
pre-authorizes the model maximum on every call. Prices come from `PRICE_IN_PER_MTOK` /
`PRICE_OUT_PER_MTOK`. The CLI prints a per-node breakdown after each question (calls, tokens,
USD per role), plus the stop reason, retrieval selectivity and redaction counts.

The metrics also carry a cache-read counter, and it stays at zero by construction: the client
never marks a prompt prefix for caching (no `cache_control` is sent), and even if it did, the
system prompts are below the provider's minimum cacheable prefix and the large user message —
question, results, evidence — changes at every step, so no prompt caching happens and there is
nothing to discount. "Cache reads not discounted" in the eval reports' cost line is a statement
about the configured rates, not a discount those runs missed.

That paragraph describes the hosted path, which every measured number on this page was run on.
On `LLM_BACKEND=ollama` the counter is not zero: Ollama serves a repeated prefix from its own
prompt cache and reports what it served, so the CLI prints a `cache: N tokens read from cache`
line — 9,274 tokens in the recorded run on the [README](../README.md) front page.
