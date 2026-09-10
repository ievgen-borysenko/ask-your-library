# Cost

**The default configuration costs nothing.** `LLM_BACKEND=ollama` runs every agent node on a model
Ollama serves on your own machine, priced at `OLLAMA_PRICE_IN_PER_MTOK` /
`OLLAMA_PRICE_OUT_PER_MTOK` (both `0`), so the metrics line under every answer reads $0.0000 —
that is the arithmetic, not a rounded-down estimate. There is no account and no billing to set up,
and nothing below applies to it except the paragraph on cache reads at the end.

**It is slower, and that is the whole trade: local is free but slow, hosted answers in tens of
seconds for cents.** Per question, on a Mac, from single measured runs — no figure below is an
average across sets:

| | Per question | Cost per question |
|---|---|---|
| Local `qwen2.5:14b` | ~40 s catalogue, ~130-160 s research | $0 |
| Hosted `claude-sonnet-4.6` | ~10 s catalogue, ~27-28 s core set | ~$0.02-0.05 |

Where each figure comes from. Local: the mini-eval of 10.09
([`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md)) means 40.4 s
over the ten catalogue questions and 133.1 s over the ten research ones; the CLI run recorded in
the README's GIF took 147.7 s cold-cache, and two clean-clone runs of the quick start's own first
question took 157.0 s and 159.5 s on this machine — also cold-cache; the same question on a warm
cache came back in 60.4 s, which is why the range above is the honest one to plan against. Hosted: the core set of 07.09
([`eval-results/2026-09-07-v0.2.0-rc1-core.md`](eval-results/2026-09-07-v0.2.0-rc1-core.md))
means 28.2 s and $0.0488 per question over its eleven, the core run of 09.09 26.9 s and $0.0519,
and the catalogue set of 10.09
([`eval-results/2026-09-10-catalogue-set.md`](eval-results/2026-09-10-catalogue-set.md)) 9.5 s and
$0.0176 — a catalogue question is one model call and no search step, which is why it is the cheap
end of both columns. Single runs on one Mac, so read them as an order of magnitude, not a
benchmark.

Everything else on this page is the hosted alternative, `LLM_BACKEND=openrouter`: what it costs,
and the configuration every measured number here and in [`eval-results/`](eval-results/) was run
on.

The hosted orchestrator is Claude Sonnet via OpenRouter. A typical question costs roughly
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
On the default `LLM_BACKEND=ollama` the counter is not zero: Ollama serves a repeated prefix from its own
prompt cache and reports what it served, so the CLI prints a `cache: N tokens read from cache`
line — 436 tokens in the recorded CLI run on the [README](../README.md) front page.
