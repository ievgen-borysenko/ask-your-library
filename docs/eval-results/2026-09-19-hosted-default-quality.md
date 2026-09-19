# Hosted default, graded by hand — 2026-09-18 and 19

What the hosted default chosen on 18.09
([`2026-09-18-hosted-models.md`](2026-09-18-hosted-models.md)),
`deepseek/deepseek-v4-flash-0731` with `LLM_REASONING=off`, is worth once a reader grades its
answers, repeated three times per question; two experiments that tried to make it answer more
fully; and the other DeepSeek models against it. That report closed with three open items — a
repeated run, the extended set, a reader's pass over the answers. This report does all three.

- **Grades are manual and single-grader.** One reader graded every answer after the runs, per
  attempt, as correct / incorrect / incomplete against the golden notes, the convention of
  [Evaluation](../evaluation.md). "C / X / Inc" below counts those verdicts per attempt; "manual
  mean" is correct answers per attempt, averaged over the attempts. No second reader, no LLM
  judge. "Behaviour" is the harness's heuristic, not correctness.
- **Index: one build for every row.** Every fingerprint below reads the same bge-m3 index built
  17.09: transcripts `sentence-pack-2`, 11,282 rows, built `2026-09-17T21:59:46`; cards
  `card-sections-1`, 165 rows, built `2026-09-17T17:09:30`. That is the index **before #80**
  (sections split at part headings, merged 18.09); the runs of 19.09 read a kept copy of it, so
  they stay paired with those of 18.09. No run here measured the index `main` builds now.
- **Code.** `976f598` (the merge of #79, clean `main`, `--require-clean`) for the hosted default,
  the thinking-on experiment, the other DeepSeek models and Sonnet 4.6 on the extended set.
  `cb74843` for the prompt experiment: one commit on top of `976f598` that changes
  `src/ask_your_library/prompts.py` only, never merged. The single-attempt core rows of Sonnet
  4.6 and Gemini are the runs of the 18.09 report, on `5a4507b` — the same index, older code (the
  parent of #79's merge).
- **Golden sets.** Core `en-demo.yaml@edc151948a58` (11 items), extended
  `en-demo-extended.yaml@836d3870185d` (21 items). Both checksums predate #83, which since 19.09
  passes `c09` (and `h22`) on an answer that names both candidate books as well as on a clarify.
  So the **behaviour** column scores `c09` the old, stricter way; the **manual** grades already
  applied the #83 rule.
- Other settings, identical on every row: `strict_hit_id=on`, `clarify_pick=second`,
  `hit_chars=2500/12000(scan 120000)`, `steps=4/2/2`, `candidates=5`, `deadline=300s`, local
  query embeddings. One Mac (Apple M3 Pro, 36 GB).
- **Cost** is tokens times the configured rates named in each report's cost line (OpenRouter list
  prices on the day of the run), cache reads not discounted. "$/question" is the mean cost per
  attempt divided by the items of the set. Seconds are the mean over every item-attempt.
- The per-question reports are not committed. Every figure here is read from their fingerprint
  and summary lines, or is one of the manual grades.

## The hosted default, `--repeat 3`

Fingerprint: `code 976f598 | golden en-demo.yaml@edc151948a58 | … | model
deepseek/deepseek-v4-flash-0731 via openrouter (reasoning off) | … | 3 attempts per item`
(18.09, 18:53; the extended run 19:10).

| Set | Behaviour, per attempt | Manual C / X / Inc, per attempt | Manual mean | $/question | Mean s |
|---|---|---|---|---|---|
| Core, 11 items | 11/11, 11/11, 11/11 | 6/0/5, 7/0/4, 5/1/5 | 6.0 | 0.0007 | 31.9 |
| Extended, 21 items | 16/21, 16/21, 16/21 | 16/1/4, 12/1/8, 17/1/3 | 15.0 | 0.0006 | 21.6 |

Rates `$0.06/M in, $0.12/M out`. No attempt produced an unattributed or broken quote (core 26/26,
28/28, 22/22 confirmed; extended 26/26, 18/18, 29/29).

Against it, single attempts on the same index:

| Model | Set | Code | Behaviour | Manual C / X / Inc | $/question | Mean s |
|---|---|---|---|---|---|---|
| `anthropic/claude-sonnet-4.6` | core | `5a4507b` | 11/11 | 9/0/2 | 0.0456 | 25.3 |
| `google/gemini-3.8-flash` | core | `5a4507b` | 10/11 | 9/0/2 | 0.0202 | 28.5 |
| `anthropic/claude-sonnet-4.6` | extended | `976f598` | 16/21 | not graded | 0.0401 | 21.0 |

Sonnet 4.6 at `$3/M in, $15/M out`, Gemini at `$0.75/M in, $3.75/M out`.

## Two attempts to make it answer more fully

Core set, `--repeat 3`, same index.

| Run | Code | Behaviour, per attempt | Manual C / X / Inc, per attempt | Manual mean | $/question | Mean s |
|---|---|---|---|---|---|---|
| Hosted default (above) | `976f598` | 11, 11, 11 | 6/0/5, 7/0/4, 5/1/5 | 6.0 | 0.0007 | 31.9 |
| Thinking on, `LLM_REASONING=provider` | `976f598` | 10–11 (mean 10.67) | 5/0/6, 6/1/4, 4/1/6 | 5.0 | 0.0012 | 90.7 |
| Prompt change: `observe` keeps the answering sentence for every part, `synthesize` uses all of it | `cb74843` | 10, 10, 10 | 4/1/6, 5/0/6, 4/0/7 | 4.3 | 0.0006 | 19.5 |

The thinking-on run's fingerprint reads `(reasoning provider)`; it wrote 49,302 output tokens per
attempt against 7,787, and took 2.8× as long per question. The prompt change also ran the
extended set (behaviour 15–16/21, mean 15.33); that run was not graded by hand.

## Other DeepSeek models, thinking off

Core set, `--repeat 3`, code `976f598`, the same index (the kept pre-#80 copy), 19.09. Each model
and its rates were set by `ORCHESTRATOR_MODEL` / `PRICE_IN_PER_MTOK` / `PRICE_OUT_PER_MTOK`, with
`LLM_REASONING=off`. Two earlier starts of this batch failed on the network and are not
counted.

| Model | $/M in / out | Behaviour, per attempt | Manual mean | $/question | Mean s |
|---|---|---|---|---|---|
| `deepseek/deepseek-v4-flash-0731` (the default, 18.09 above) | 0.06 / 0.12 | 11, 11, 11 | 6.0 | 0.0007 | 31.9 |
| `deepseek/deepseek-v4-flash` | 0.047 / 0.095 | 10–11 (mean 10.33) | 6.0 | 0.0005 | 19.0 |
| `deepseek/deepseek-v4.1-flash` | 0.15 / 0.6 | 10–11 (mean 10.33) | 7.33 | 0.0021 | 27.5 |
| `deepseek/deepseek-v4-pro-0813` | 0.578 / 1.734 | 11, 11, 11 | 6.33 | 0.0065 | 25.9 |
| `deepseek/deepseek-v3.2` | 0.269 / 0.4 | 10, 10, 10 | 7.67 | 0.0034 | 23.0 |
| `deepseek/deepseek-v3.2`, repeated (19.09, 21:53) | 0.269 / 0.4 | 10–11 (mean 10.33) | 6.0 (5/1/5, 7/1/3, 6/1/4) | 0.0036 | 31.5 |

Over its six attempts `deepseek/deepseek-v3.2` averages 6.83 correct.

## What the rows hide

- **Behaviour is full; correctness is not.** The default passes the behaviour heuristic on every
  core attempt and is fully correct on 5 to 7 of 11. Almost all of the rest are *incomplete*, not
  *incorrect*: one incorrect verdict in 33 core answers, and one per attempt (3 in 63) on the
  extended set. The answers are short, they cite, and their quotes check — and they stop before
  the detail the question turns on.
- **The main failure class is shared by every model tried.** The answer says a detail is not in
  the evidence while the passages the agent retrieved hold it, or retrieval never reached it. The
  canonical cases: `c02` (the letter Huck tears up), `c04` (Crusoe's "judge and executioner"
  scruple), `c06` (Passepartout's "to-day is Saturday"), `h06` (the poverty and shame reason).
  Neither experiment moved them. Tracked in #81; its first step, logging what `observe` keeps per
  step, is PR #85.
- **Thinking costs time and did not buy correctness.** 5.0 against 6.0 correct at 2.8× the
  seconds. Three attempts on a single grader cannot separate 5.0 from 6.0; they can say thinking
  did not help.
- **The prompt change lost a behaviour.** The `c09` clarify never happened (clarify interrupts 0
  on every attempt, identify 1/2), and correct answers fell to 4.3. Not merged.
- **The spread between attempts is as large as the gaps between models.** `deepseek/deepseek-v3.2`
  scored 7.67 on its first three attempts and 6.0 on the next three, on the same code and index;
  the default spans 5 to 7 within one run. Differences of one correct answer per attempt between
  the DeepSeek rows are inside that spread.
- **`deepseek/deepseek-v4-flash` is not the default's id.** It is the undated listing, run at its
  own rates; it tied the default at 6.0.
- **`deepseek/deepseek-v4-pro-0813`** scored 6.33, with two incorrect verdicts on `c07`,
  at nearly 10× the default's cost per question.
- **Sonnet 4.6 and Gemini are single attempts, graded once.** Their 9 of 11 against the default's
  6.0 is the size of the gap, not a measured spread. Their code is `5a4507b`, one merge older.

## Decision

Keep `deepseek/deepseek-v4-flash-0731` with `LLM_REASONING=off` as the hosted default. Its best
alternative, `deepseek/deepseek-v3.2`, did not hold its lead on a repeat (7.67, then 6.0) and costs
about 5× more per question; the others did not beat it by more than the spread between attempts.
Thinking on and the prompt change are not adopted. The default answers correctly but thinly —
about 6 of 11 core questions fully correct against 9 for Sonnet 4.6 or Gemini on one attempt —
and [Known limits](../known-limits.md) says so; the fix belongs to the failure class of #81, which
applies to every model here, not to a model change.
