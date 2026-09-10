# Cost

**The default configuration costs nothing.** `LLM_BACKEND=ollama` runs every agent node on a model
Ollama serves on your own machine, priced at `OLLAMA_PRICE_IN_PER_MTOK` /
`OLLAMA_PRICE_OUT_PER_MTOK` (both `0`), so the metrics line under every answer reads $0.0000 —
that is the arithmetic, not a rounded-down estimate. There is no account and no billing to set up,
and nothing below applies to it except the paragraph on cache reads at the end.

**Speed is not the whole trade.** Local is free but slow — hosted answers a research question in
tens of seconds for cents — and it also answers research questions less reliably: 8/10 with
41 / 1 / 2 quotes confirmed / unattributed / broken for the default `qwen2.5:14b` on the local run
of 2026-09-10, whose own verdict is that neither local candidate "is good enough to advertise as a
strong default" ([`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md),
and [Known limits](known-limits.md) for the full entry). This page prices and times that trade; it
does not measure the accuracy half.

Per question, on one Mac, from single measured runs. Every cell covers one kind of question: a
catalogue figure is computed from catalogue rows only, a research figure from research rows only,
and no cell is a mean over a set that mixes the two — those sets exist, and their whole-set means
are between six fast rows and four slow ones.

| | Catalogue question | Research question | Cost per question |
|---|---|---|---|
| Local `qwen2.5:14b` | 1-12 s over six rows (mean 3.3 s) | 61-217 s over 14 rows (mean 133 s over the research set's ten) | $0 for either |
| Hosted `claude-sonnet-4.6` | 1-2 s over six rows (mean 1.8 s) | 8-61 s over 26 rows (mean 27-28 s over each core set's eleven) | ~$0.002 catalogue, ~$0.05 research |

Which rows each figure covers. **Local**, all from the mini-eval of 10.09
([`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md)) on
`qwen2.5:14b`: catalogue is the six catalogue items of the catalogue set (`k01`-`k06`: 12, 1, 2, 2,
2 and 1 s, 20 s together); research is the ten items of the research set (`c01`-`c10`, 83 to 217 s,
and the report's own wall-clock mean over them is 133.1 s), widened at the fast end by the same
catalogue set's four research controls (`k07`-`k10`, 61 to 131 s). That mixture is why the report's
40.4 s for the catalogue set is not a catalogue figure: it is six 1-12 s rows and four 61-131 s ones
in one mean. One whole question end to end, from a clean clone with nothing resident, is recorded
separately in
[`eval-results/2026-09-10-first-question-local.md`](eval-results/2026-09-10-first-question-local.md):
160.8 s the first time and 62.7 s on the immediate repeat of the same question — a research
question, three search steps, inside the band above. The README's GIF is a different question and
the same kind of number: 147.7 s, also a cold first ask.

**Hosted**, `anthropic/claude-sonnet-4.6`: catalogue from the catalogue set of 10.09
([`eval-results/2026-09-10-catalogue-set.md`](eval-results/2026-09-10-catalogue-set.md)), whose six
catalogue items ran in 1 to 2 s and cost $0.0136 together, $0.0023 each; research from the core set
of 07.09 ([`eval-results/2026-09-07-v0.2.0-rc1-core.md`](eval-results/2026-09-07-v0.2.0-rc1-core.md)),
eleven research questions, mean 28.2 s and $0.0488, and the core run of 09.09
([`eval-results/2026-09-09-catalogue-branch-core.md`](eval-results/2026-09-09-catalogue-branch-core.md))
26.9 s and $0.0519; the catalogue set's own four research controls took 9 to 41 s at $0.0407 each.
A catalogue question is one model call and no search step, which is why it is the cheap end of both
columns — twenty times cheaper than a research one, not the $0.0176 the mixed set mean reports.
Single runs on one Mac (Apple M3 Pro, 36 GB), so read them as an order of magnitude, not a
benchmark.

Everything else on this page is the hosted alternative, `LLM_BACKEND=openrouter`: what it costs, and
the configuration every number below was run on. Not every report in
[`eval-results/`](eval-results/) is hosted — the two local ones named above are local, and each
report's provenance header names the backend it ran with.

The hosted orchestrator is Claude Sonnet via OpenRouter. A typical *research* question costs roughly
**$0.04-0.05 on the demo sets** at v0.2.0-rc1 (core mean $0.049, extended $0.043 — both sets are
research questions end to end; a catalogue question is the $0.002 row of the table above;
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

That paragraph is about the hosted path only. On the default `LLM_BACKEND=ollama` the counter is not
zero: Ollama serves a repeated prefix from its own
prompt cache and reports what it served, so the CLI prints a `cache: N tokens read from cache`
line — 436 tokens in the recorded CLI run on the [README](../README.md) front page, and 807 then
12,606 tokens on the cold and warm runs of
[`eval-results/2026-09-10-first-question-local.md`](eval-results/2026-09-10-first-question-local.md),
which is most of the 98 s between them.
