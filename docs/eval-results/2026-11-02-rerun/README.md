# Re-measure of both shipped configurations — 2026-11-02

Both shipped configurations, the hosted default and the local default, on the core, extended and
catalogue golden sets at `--repeat 3`; the retriever eval on core and extended; and the `#29`
acceptance bar on the local default at `--repeat 5`. Every run reads the same commit and the same
index. This folder holds the harness's own reports and JSON sidecars of those runs, unedited, and
this page, which summarises them.

## What was measured

| | |
|---|---|
| Code | `6d73fc3` (`6d73fc39accc3a64bb8bd10e8c474c6b97d705fd`, `main` on 02.11.2026), detached checkout; every fingerprint stamps it clean (`--require-clean`, sidecar `code_clean: true`) |
| When | 02.11.2026 23:01 to 03.11.2026 00:50 CET, one batch, every run sequential |
| Machine | Mac mini (Apple Silicon) |
| Index | the demo index under `_data/lancedb`, given as `LIBRARY_DB_PATH` (resolution clause 1, an explicit path): 35 books; `cards_ollama=bge-m3/1024d chunker=card-sections-2 rows=165 v2 built=2026-09-19T12:28:41`, `transcripts_ollama=bge-m3/1024d chunker=sentence-pack-2 rows=11236 v26 built=2026-09-24T10:39:10`; `ayl doctor` reported no drift before the runs |
| Embeddings | `bge-m3` via Ollama (`EMBED_BACKEND=ollama`) for every run, hosted ones included |
| Golden sets | core `en-demo.yaml@2c43defa8bc7` (11 items), extended `en-demo-extended.yaml@338002f35e0e` (21 items), catalogue `en-demo-catalog.yaml@72eb2c2b2655` (10 items); corpus `manifest@c1fee42124dd`, `toc@3f0e05110358` |
| Step 1 flags | `--repeat 3 --clarify-pick second --require-clean` |
| Bar flags | `--repeat 5 --clarify-pick second --require-clean`, plus `--min-pass 9` (core) / `--min-pass 10` (catalogue) |
| Settings in every fingerprint | `strict_hit_id=on`, `clarify_pick=second`, `hit_chars=2500/12000(scan 120000)`, `steps=4/2/2`, `candidates=5`; `deadline=300s` hosted, `deadline=1200s` local |

Environment hygiene, the same for every run:

- Every setting that changes an answer or where it goes was unset (`env -u`): the model, price,
  reasoning, Ollama, OpenRouter, output-size, hit-size, step, clarify, timeout, deadline,
  strict-hit, scratch-directory and tracing variables. The configuration was then resolved by the
  measured commit's `config.py` before the first run and printed; a `.env` or `config.env` line
  setting any of those variables would have stopped the batch, and the measured checkout held no
  `.env`.
- `AYL_HOME` pointed at an empty folder, so no user configuration layer reached the runs.
- Tracing off (`LANGSMITH_TRACING_V2=false`, `LANGCHAIN_TRACING_V2=false`).
- The local runs had `OPENROUTER_API_KEY` unset; only `LLM_BACKEND` told the two configurations
  apart.
- No `--record-plans`: no planner recording was written into the tree.

The two configurations, as `config.py` resolved them:

| | Hosted default | Local default |
|---|---|---|
| `LLM_BACKEND` | `openrouter` | `ollama` |
| Model | `deepseek/deepseek-v4-flash-0731`, reasoning off | `qwen2.5:14b` |
| Configured rates, $/M in / out | 0.06 / 0.12 | 0.0 / 0.0 |

## How to read the numbers

Every figure in the tables is copied from a report's totals block (the lines after its last
`---`), which gives each figure **per attempt**: min–max over the attempts, with the mean. The
lines quoted under each table are copied verbatim. Three exceptions: the seconds rows are computed
from the sidecar, over every item-attempt's `seconds` field (`questions[].attempts[].seconds`),
and wall clock is the sidecar's top-level `seconds` for the run; the per-attempt lists such as
"(9, 10, 10)" are the sidecar's `totals.per_attempt.behavior_ok.values`; the runner exit codes of
the bar runs come from the batch's run log, which is not committed.

Behaviour PASS is the harness's heuristic, not answer correctness; "expected facts found" is
substring presence. See [Evaluation](../../evaluation.md).

## Hosted default, `--repeat 3`

| Set | Behaviour PASS, per attempt | Mean | Cost per attempt | Spent, all attempts | LLM calls per attempt | Seconds per question, min / median / max (mean) | Wall clock |
|---|---|---|---|---|---|---|---|
| Core, 11 items | 11–11/11 | 11.00 | $0.0075–$0.0085 (mean $0.0079) | $0.0238, 204 calls | 65–72 (mean 68.00) | 3 / 9 / 17 (8.5) | 281 s |
| Extended, 21 items | 18–18/21 | 18.00 | $0.0127–$0.0138 (mean $0.0132) | $0.0396, 353 calls | 114–123 (mean 117.67) | 1 / 8 / 30 (8.4) | 525 s |
| Catalogue, 10 items | 10–10/10 | 10.00 | $0.0023–$0.0027 (mean $0.0025) | $0.0076, 70 calls | 22–24 (mean 23.33) | 0 / 1.5 / 18 (4.0) | 118 s |

Behaviour by group, titles and facts, from the totals blocks:

- Core: `[aggregation 1–1/1, answer 7–7/7, identify 2–2/2, refusal 1–1/1]`;
  `expected titles mentioned 11–11/12 over 3 attempts (mean 11.00 per attempt)`;
  `expected facts found 14–15/24 over 3 attempts (mean 14.33 per attempt)`.
- Extended: `[aggregation 2–2/3, answer 6–6/7, identify 6–6/7, refusal 4–4/4]`;
  `expected titles mentioned 19–20/22 over 3 attempts (mean 19.67 per attempt)`;
  `expected facts found 25–26/34 over 3 attempts (mean 25.67 per attempt)`.
- Catalogue: `[answer 4–4/4, catalog 6–6/6]`;
  `expected titles mentioned 106–106/106 over 3 attempts (mean 106.00 per attempt)`;
  `expected facts found 14–14/15 over 3 attempts (mean 14.00 per attempt)`.

No attempt produced an unattributed or broken quote (quotes confirmed / checked per attempt: core
25/25, 25/25, 21/21; extended 28/28, 22/22, 31/31; catalogue 9/9, 5/5, 10/10). Total spend of the
hosted part: $0.0710.

Items that fail behaviour, hosted:

- Core and catalogue: none.
- Extended: the same three items in every attempt.
  - `q06-verne-guaranteed-clarify` (identify): `FAIL: titles 1/2, 2 duplicate quote(s) skipped,
    stop: enough evidence` in attempts 1 and 2; attempt 3 `FAIL: titles 1/2, 1 repeated search(es)
    replaced, 4 duplicate quote(s) skipped, stop: CRAG gate: 2 dry steps in a row`.
  - `h13-moby-dick-ending` (answer): `FAIL: titles 1/1, facts 3/3, drilldown NO, named book ->
    retrieval filter Moby Dick — Herman Melville, stop: enough evidence` in attempts 1 and 2;
    attempt 3 adds `chapter reads 2 (2 named what they were looking for, 0 opened a window off the
    head)` and stops at `CRAG gate: 2 dry steps in a row`.
  - `h17-lupin-beats-holmes` (aggregation): `FAIL: titles 1/2, facts 0/1 NO, chapter reads 1 (1
    named what they were looking for, 1 opened a window off the head), stop: requested chapter was
    already attempted (re-reading cannot show more text)` in all three.

Reports: [core](hosted-core/answers-1793656910.md), [extended](hosted-extended/answers-1793657192.md),
[catalogue](hosted-catalogue/answers-1793657720.md), each with its `.json` sidecar beside it.

## Local default, `--repeat 3`

| Set | Behaviour PASS, per attempt | Mean | Cost | LLM calls per attempt | Seconds per question, min / median / max (mean) | Wall clock |
|---|---|---|---|---|---|---|
| Core, 11 items | 9–10/11 (9, 10, 10) | 9.67 | $0.0000 | 87–89 (mean 87.67); 263 in all | 15 / 39 / 70 (38.1) | 1,256 s |
| Extended, 21 items | 17–17/21 | 17.00 | $0.0000 | 146–146 (mean 146.00); 438 in all | 1 / 22 / 69 (26.3) | 1,654 s |
| Catalogue, 10 items | 10–10/10 | 10.00 | $0.0000 | 26–26 (mean 26.00); 78 in all | 1 / 1 / 45 (10.1) | 299 s |

Behaviour by group, titles and facts, from the totals blocks:

- Core: `[aggregation 0–0/1, answer 7–7/7, identify 2–2/2, refusal 0–1/1]`;
  `expected titles mentioned 10–10/12 over 3 attempts (mean 10.00 per attempt)`;
  `expected facts found 9–10/24 over 3 attempts (mean 9.67 per attempt)`.
- Extended: `[aggregation 1–1/3, answer 6–6/7, identify 7–7/7, refusal 3–3/4]`;
  `expected titles mentioned 18–18/22 over 3 attempts (mean 18.00 per attempt)`;
  `expected facts found 24–24/34 over 3 attempts (mean 24.00 per attempt)`.
- Catalogue: `[answer 4–4/4, catalog 6–6/6]`;
  `expected titles mentioned 106–106/106 over 3 attempts (mean 106.00 per attempt)`;
  `expected facts found 14–14/15 over 3 attempts (mean 14.00 per attempt)`.

No attempt produced an unattributed or broken quote (quotes confirmed / checked per attempt: core
26/26, 25/25, 25/25; extended 29/29, 28/28, 28/28; catalogue 7/7 in each).

Items that fail behaviour, local:

- Core:
  - `c10-chivalry-two-books` (aggregation), every attempt: `FAIL: titles 1/2, facts 1/2 NO, clarify
    choice applied, 1 duplicate quote(s) skipped, stop: repeated clarify not allowed — finishing
    with what we have`.
  - `c08-refusal-tom-sawyer` (refusal), attempt 1 only: `FAIL: titles 0/0, 1 repeated search(es)
    replaced, 1 duplicate quote(s) skipped, stop: step limit (4) — wanted to keep searching`.
    Attempts 2 and 3 pass.
- Extended: the same four items in every attempt.
  - `h13-moby-dick-ending` (answer): `FAIL: titles 1/1, facts 3/3, drilldown NO, stop: enough
    evidence`.
  - `h16-which-stoic-book` (aggregation): `FAIL: titles 1/2, facts 2/2, stop: enough evidence`.
  - `h17-lupin-beats-holmes` (aggregation): `FAIL: titles 1/2, facts 0/1 NO, 1 quotes dropped
    before the answer (not in the passage they cited), peak 1 all-dropped step(s) in a row, 1
    duplicate quote(s) skipped, chapter reads 1 (1 named what they were looking for, 1 opened a
    window off the head), stop: step limit (4) — wanted to keep searching`.
  - `h21-refusal-kateryna-not-in-edition` (refusal): `FAIL: titles 0/0, 1 duplicate quote(s)
    skipped, stop: step limit (4) — wanted to keep searching`.
- Catalogue: none.

Reports: [core](local-core/answers-1793657840.md), [extended](local-extended/answers-1793659098.md),
[catalogue](local-catalogue/answers-1793660754.md), each with its `.json` sidecar beside it.

## The `#29` bar, local default, `--repeat 5`

The bar: behaviour at `--repeat 5` not below the 16.09 baseline of the local default
([`2026-09-16-local-models-repeat3.md`](../2026-09-16-local-models-repeat3.md): `qwen2.5:14b`
9/11 core and 10/10 catalogue on every attempt). `--min-pass` is a floor on the weakest attempt,
so the runner's exit code is the verdict.

| Set | Floor (`--min-pass`) | Behaviour PASS, per attempt | Weakest attempt | Mean | Runner exit | Verdict | Seconds per question, min / median / max (mean) | Wall clock |
|---|---|---|---|---|---|---|---|---|
| Core, 11 items | 9 | 9, 10, 10, 10, 10 | 9/11 | 9.80 | 0 | met | 13 / 32 / 66 (34.3) | 1,882 s |
| Catalogue, 10 items | 10 | 10 in all five | 10/10 | 10.00 | 0 | met | 1 / 1 / 45 (9.8) | 484 s |

- Core: `[aggregation 0–0/1, answer 7–7/7, identify 2–2/2, refusal 0–1/1]`;
  `expected titles mentioned 10–10/12 over 5 attempts (mean 10.00 per attempt)`;
  `expected facts found 9–10/24 over 5 attempts (mean 9.80 per attempt)`; 87–89 LLM calls per
  attempt, 437 in all; $0.0000.
- Catalogue: `[answer 4–4/4, catalog 6–6/6]`;
  `expected titles mentioned 106–106/106 over 5 attempts (mean 106.00 per attempt)`;
  `expected facts found 14–14/15 over 5 attempts (mean 14.00 per attempt)`; 26 LLM calls per
  attempt, 130 in all; $0.0000.
- Items that fail behaviour: core `c10-chivalry-two-books` in all five attempts (the same reason
  string as in the step-1 local core run) and `c08-refusal-tom-sawyer` in attempt 1 only (the same
  reason string as there); catalogue none.

**Caveat: the core golden file is not the baseline's.** The 16.09 baseline ran
`en-demo.yaml@edc151948a58`; this bar ran `en-demo.yaml@2c43defa8bc7`. The catalogue file is the
same in both (`en-demo-catalog.yaml@72eb2c2b2655`). The core floor of 9 is the baseline's count,
applied to the current checksum. The baseline's runs also read other code and an older index (that
report's provenance names both).

Reports: [core](bar-core/answers-1793661055.md), [catalogue](bar-catalogue/answers-1793662940.md).

## Retriever eval, no answering model

`eval/run_retrieval_eval.py` with `bge-m3` query embeddings via Ollama, the raw question as the
query, window = top-4 cards + top-4 transcripts.

| Set | Single-book presence | Multi-book full coverage | Mean coverage, multi-book |
|---|---|---|---|
| Core | 8/8 = 100% | 2/2 | 100% |
| Extended | 12/12 = 100% | 3/5 | 80% |

The two extended multi-book items not fully covered are `h17-lupin-beats-holmes` and
`h22-gothic-chase-ambiguous` (1/2 each). Per-corpus diagnostics: core hit@2/4/8 10/10, extended
hit@2/4/8 17/17, MRR (best-of-two) 1.000 on both. Output: [core](retrieval-core/retrieval.txt),
[extended](retrieval-extended/retrieval.txt).

## What is not in this folder

- **Manual correctness is unscored.** Every manual-correctness checkbox in every report is
  unticked; nobody has read these answers against the golden notes yet.
- **The raw retrieved passages and the console output are not committed.** Each run also wrote
  `scratch-*` files (the passages the agent retrieved) and a console log; they stay on the machine
  that ran the batch.
- **The README "Measured" table and its intervals (#131) are not updated here.** That is a
  follow-up, together with the manual grades.
