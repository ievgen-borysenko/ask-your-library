# Hosted answering models — 2026-09-18

OpenRouter models against the hosted default of the day, `anthropic/claude-sonnet-4.6`, to choose
the default for `LLM_BACKEND=openrouter`. The shipped default stays local and is not measured here.

- run: code `5a4507b` (clean `main`) for every comparison row, both demo golden sets
  (`en-demo.yaml`, 11 research questions; `en-demo-catalog.yaml`, 6 catalogue questions + 4
  research controls), the re-chunked bge-m3 index of 17.09 (`sentence-pack-2`, 11,282 transcript
  rows; cards `card-sections-1`, 165 rows), `strict_hit_id=on`, `clarify_pick=second`, local query
  embeddings, `deadline=300s`.
- The model and its rates were set by `ORCHESTRATOR_MODEL` / `PRICE_IN_PER_MTOK` /
  `PRICE_OUT_PER_MTOK` only; rates are OpenRouter's list prices of 2026-09-18. Cost is tokens times
  those rates, cache reads not discounted, as in every hosted report.
- "Thinking off" rows ran `5a4507b` plus an uncommitted two-line probe that sent OpenRouter's
  `reasoning: {"enabled": false}` — what `LLM_REASONING=off` now does. The last row is the same
  default measured on the branch itself, clean tree, no overrides: its fingerprint reads
  `code 5bf222b | … | model deepseek/deepseek-v4-flash-0731 via openrouter (reasoning off)`.
- Single runs, one Mac (Apple M3 Pro, 36 GB), 15:11 to 17:57. DeepSeek V4.1 Flash with thinking
  on overlapped a local Ollama run on its catalogue set only. With thinking off its `c01` and `c02`
  first failed without reaching the model (a network outage: zero calls, LangSmith timing out in
  the same seconds) and were re-run alone; the row carries the re-run.
- Nobody graded the answers by hand. "Facts" is the harness's substring check, not correctness;
  "card-only" counts answers whose every quote matched only a model-written book card.

## Results

| Model | $/M in / out | Core behaviour | Core $/question | Core mean s | Facts | Card-only | Catalogue behaviour | Catalogue $/question | Catalogue mean s |
|---|---|---|---|---|---|---|---|---|---|
| `anthropic/claude-sonnet-4.6` (baseline) | 3 / 15 | 11/11 | 0.0456 | 25.3 | 14/24 | 2 | 10/10 | 0.0164 | 8.9 |
| `anthropic/claude-sonnet-5` | 2 / 10 | 10/11 | 0.0445 | 28.0 | 17/24 | 1 | 10/10 | 0.0114 | 7.8 |
| `google/gemini-3.8-flash` | 0.75 / 3.75 | 10/11 | 0.0202 | 28.5 | 15/24 | 2 | 10/10 | 0.0103 | 13.7 |
| `openai/gpt-5.6-luna` | 0.2 / 1.2 | 11/11 | 0.0032 | 20.5 | 10/24 | 5 | 9/10 | 0.0011 | 6.8 |
| `deepseek/deepseek-v4.1-flash`, thinking on | 0.15 / 0.6 | 11/11 | 0.0051 | 137.1 | 16/24 | 1 | 10/10 | 0.0017 | 34.2 |
| `deepseek/deepseek-v4.1-flash`, thinking off | 0.15 / 0.6 | 10/11 | 0.0022 | 32.2 | 15/24 | 0 | 10/10 | 0.0006 | 8.3 |
| `deepseek/deepseek-v4-flash-0731`, thinking off | 0.06 / 0.12 | 11/11 | 0.0006 | 24.0 | 13/24 | 2 | 10/10 | 0.0002 | 7.2 |
| same, on the branch (`5bf222b`, defaults) | 0.06 / 0.12 | 11/11 | 0.0007 | 22.3 | 14/24 | 2 | 10/10 | 0.0002 | 9.8 |

No run produced an unattributed or broken quote; every model refused `c08` honestly.

## What the rows hide

- **`c09` is the only core miss** of Sonnet 5, Gemini and V4.1 Flash with thinking off: each
  answered with both candidate books (Crusoe for solitary survival, Gulliver for the strange
  society) instead of the clarify the golden asks for. That expectation is still marked PROPOSED in
  the golden and waits for the reader's verdict. Sonnet 4.6 clarified, then spent the 4-step budget
  on the item ($0.086 of its $0.50 total).
- **Sonnet 5 saves little on research questions.** Its rates are a third lower, but it spent more
  tokens than Sonnet 4.6 on the same core set (155k in / 18k out against 112k / 11k): longer
  answers and more evidence carried from `observe` into the next prompts. On the catalogue set the
  input was the same (38.4k both) and the saving is the full 30%.
- **Luna searches shallowly.** Six of eleven core questions stopped after one search step, five
  answers rest on book cards only, and it found the fewest facts (10/24). Its catalogue miss is
  `k09` ("Which of my books mention London?"), which the planner routed to the catalogue and the
  fallback (`mixed_intent`) answered from one step.
- **Thinking is what made DeepSeek slow.** With it on, V4.1 Flash wrote 58k output tokens on the
  core set and took 39 to 367 s per question (`c07` ran past the 300 s budget and still passed).
  With it off: 9k tokens and a mean of 32 s. V4 Flash 0731 with it off wrote the least of any
  model (7.7k on the core set), so its answers are the shortest; its facts count is at the low end
  of the Claude and Gemini rows, not below them.

## Decision

Hosted default: `deepseek/deepseek-v4-flash-0731` with `LLM_REASONING=off` — the full behaviour
score on both sets at about 1/70 of Sonnet 4.6's cost per research question and the same latency,
confirmed on the branch itself. Documented backup: `google/gemini-3.8-flash` with
`PRICE_IN_PER_MTOK=0.75` / `PRICE_OUT_PER_MTOK=3.75`, the cheapest candidate that ran with its
provider's default settings. Open before the default is trusted further: a repeated run
(`--repeat 3`), the extended set, and a reader's pass over the answers, which are short. The
per-question reports of these runs are not committed; the table above is copied from their
summary lines.
