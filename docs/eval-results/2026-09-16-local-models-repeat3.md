> **Provenance of this artifact.** Six runs on 2026-09-16, three local models against two golden
> sets, every one of them at `--repeat 3 --record-plans --clarify-pick second` on the local backend
> (`LLM_BACKEND=ollama`, `EMBED_BACKEND=ollama`). **Code `169b511`** for all six — the merge of `#64`,
> which is the commit that first counted book-card matches apart from book text. **The evidence gate
> (`#65`) is NOT in these six runs.** Everything `#65` added — the quote check at the `observe`
> gate, the re-pin, the drop counters — landed after them, in `c79018a`. That is the point of the
> batch: it is the paired baseline the gate's own run is read against, agreed in advance in
> [`../evaluation.md`](../evaluation.md) ("the paired baseline on three local models is being
> produced, the gate's run comes after it").
>
> **The gate's runs are on this page too**, added 2026-09-17 in
> [their own section](#the-observe-gate-65-same-model-same-sets): `qwen2.5:14b` and
> `mistral-small3.2:24b-ctx20k`, both sets each, `--repeat 3 --clarify-pick second`, no
> `--record-plans`, on `c79018a`. Read the six runs above as the baseline and that section as the
> pair. **They do not agree**: the gate is behaviour-neutral on the shipped default and costs
> `mistral-small3.2:24b-ctx20k` one item on two attempts of three, so the acceptance for `#29` is
> stated per model rather than once. `qwen2.5:32b` has not been run on `c79018a`.
>
> Golden files: `en-demo.yaml@edc151948a58` (11 items) and `en-demo-catalog.yaml@72eb2c2b2655`
> (10 items); corpus `manifest@ed94677aa3a3`, `toc@ef7a347ace1d`; the same 04.09 bge-m3 demo index
> every local run since has read (`cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01`,
> `transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31`). Settings, identical on
> all six: `strict_hit_id=on`, `clarify_pick=second`, `hit_chars=2500/12000`, `steps=4/2`,
> `candidates=5`, `deadline=1200s`, `temperature=0`, `max_tokens=2048`, `reasoning_effort=none`,
> `llm_timeout_s=600`.
>
> **The runs were not made on a clean tree, and the reason is in the fingerprints.** Five of the six
> stamp `169b511+dirty(<checksum>)` and each dirty checksum differs from the others; only the first
> run of the batch (`qwen2.5:14b` / `en-demo`) stamps `169b511` clean. Nothing in the code changed
> between them: the harness hashes `git diff HEAD` **together with the un-ignored untracked files**,
> `--record-plans` writes its recording into `eval/recordings/` (a committed directory), and so run
> *n* is measured against a tree that already holds run *n-1*'s recording. The five checksums are a
> record of which recordings existed when each run started, not of five different codebases. This is
> the first thing on this page that a reader should not have to work out for themselves, and it is
> the reason `--require-clean` and `--record-plans` cannot both be used on the same run as the code
> stands.
>
> **First runs on this project to carry a spread.** Until today every published number was a single
> sample (`docs/evaluation.md`: "No repeated run has been made yet"). These are also the first runs
> to publish the `expected_facts` row on a repeat, the first with card-only matches counted apart
> from traced quotes, the first with per-role seconds, and the first whose planner calls are
> committed as replayable recordings (`eval/recordings/*.jsonl`, six files).
>
> **Where the raw output is.** The six `answers-<ts>.md` reports, their JSON sidecars, the
> scratchpads and the run log are harness output under `eval/results/`, which is **not committed**
> (`docs/backlog.md`, and the repository's own rule that results stay local); they live outside this
> tree at `_data/step0/` on the machine that ran them, and this page names each file it cites so the
> owner can put any number back against its source. What **is** committed is the input half: the two
> golden files at the checksums above, and the six planner recordings in
> [`../../eval/recordings/`](../../eval/recordings/) — `en-demo.edc151948a58.<model>.jsonl` and
> `en-demo-catalog.72eb2c2b2655.<model>.jsonl`, one line per golden id and attempt, 30 to 39 plan
> calls each. Every one of them was scanned before it was committed with the recorder's own
> `ABSOLUTE_PATH_RE` and `SECRET_PATTERNS` (`eval/plan_recording.py`): no absolute path, no
> credential, and each header's `golden_sha256_12` matches the golden file in this tree.
>
> Machine: one Apple M3 Pro, 36 GB, everything sequential — one model, one set, nothing else heavy
> alongside (`_data/step0/run-step0.sh`). Wall clock 16:38:44 → 23:00:15 CEST, 6 h 21 min for the
> batch, of which 21 minutes were spent on an attempt that was abandoned (see
> [The 131k-context trap](#the-131k-context-trap)).
>
> **Not reader-graded.** Every manual-correctness checkbox in every one of the six harness reports is
> unticked. Behaviour PASS is the harness's own heuristic; the facts row is substring presence;
> quote provenance is plain code against the stored passage. None of the three is answer
> correctness, and nobody read these answers against the golden notes.

# Three local models at `--repeat 3` — 2026-09-16

## What ran

| | |
|---|---|
| Backend | Ollama (`LLM_BACKEND=ollama`), OpenAI-compatible endpoint at `OLLAMA_URL/v1` |
| Embedder | `bge-m3`, 1024d, multilingual (`EMBED_BACKEND=ollama`) |
| Models | `qwen2.5:14b` (the shipped default), `qwen2.5:32b`, `mistral-small3.2:24b-ctx20k` |
| Flags | `--repeat 3 --record-plans --clarify-pick second` |
| Sets | `en-demo.yaml@edc151948a58` (11 items), `en-demo-catalog.yaml@72eb2c2b2655` (10 items) |
| Code | `169b511` (merge of `#64`); `#65`, the evidence gate, is **not** in it |
| Machine | Apple M3 Pro, 36 GB, sequential |

`mistral-small3.2:24b-ctx20k` is a derived model: `mistral-small3.2:24b` with `PARAMETER num_ctx
20480`. The stock tag could not be measured at all; the section below says why.

Wall clock per model and set, from `_data/step0/step0.log`:

| Model | `en-demo` | `en-demo-catalog` |
|---|---|---|
| `qwen2.5:14b` | 2,797 s (46 min 37 s) | 765 s (12 min 45 s) |
| `qwen2.5:32b` | 7,277 s (2 h 01 min 17 s) | 2,471 s (41 min 11 s) |
| `mistral-small3.2:24b-ctx20k` | 6,061 s (1 h 41 min 01 s) | 2,250 s (37 min 30 s) |
| `mistral-small3.2:24b` (stock, aborted) | 1,201 s on one attempt of one item | not reached |

## `en-demo` — the research set, 11 items, 3 attempts each

Sources: `_data/step0/results/<model>/en-demo/answers-*.md` (totals block after the last `---`) and
`answers-*.json` (`totals.per_attempt`, `per_group`, `questions[].spread`). Every figure below is
copied from those files; nothing on this page is recomputed from the answers. A single number means
the three attempts agreed exactly.

| Row | `qwen2.5:14b` | `qwen2.5:32b` | `mistral-small3.2:24b-ctx20k` |
|---|---|---|---|
| Behaviour PASS, per attempt | **9/11** ×3 | **9/11** ×3 | **11/11** ×3 |
| — by group (`answer` / `identify` / `refusal` / `aggregation`) | 7/7 · 1/2 · 1/1 · 0/1 | 6/7 · 2/2 · 1/1 · 0/1 | 7/7 · 2/2 · 1/1 · 1/1 |
| Clarify interrupts | 1 | 2 | 1 |
| Quotes confirmed / checked | 34 / 45 | 31 / 47 | 42–43 / 67–69 |
| — of which book text | 36 | 33 | 50–52 |
| Unattributed | 0 | 1 | 0 |
| Broken | 2 | 1 | **8–9** |
| Matched only a book card | 9 | 14 | 17 |
| Evidence items | 45 | 47 | 67–69 |
| Expected facts found | 10 / 24 | 12 / 24 | 11 / 24 |
| Answers carrying every fact | 1 / 9 | 2 / 9 | 2 / 9 |
| Titles mentioned | 10 / 12 | 9 / 12 | 11 / 12 |
| LLM calls | 79 | 86 | 82 |
| Tokens in | 132,375–132,377 | 142,792 | 139,688–140,398 |
| Tokens out | 7,981–8,015 | 9,055 | 12,700–12,803 |
| Per-question wall clock, min–max | 30–196 s | 94–432 s | 73–399 s |
| Seconds by role, median per attempt | plan 3.4 · **observe 45.3** · reflect 8.3 · synth 8.3 | plan 11.1 · **observe 136.5** · reflect 24.1 · synth 25.9 | plan 7.2 · **observe 107.5** · reflect 18.5 · synth 20.1 |
| Cost | $0.0000 | $0.0000 | $0.0000 |

Files: `answers-1789569528.{md,json}` (14b), `answers-1789573094.{md,json}` (32b),
`answers-1789584099.{md,json}` (mistral).

## `en-demo-catalog` — the catalogue set, 10 items, 3 attempts each

| Row | `qwen2.5:14b` | `qwen2.5:32b` | `mistral-small3.2:24b-ctx20k` |
|---|---|---|---|
| Behaviour PASS, per attempt | **10/10** ×3 | **10/10** ×3 | **10/10** ×3 |
| — by group (`catalog` / `answer`) | 6/6 · 4/4 | 6/6 · 4/4 | 6/6 · 4/4 |
| Clarify interrupts | 0 | 0 | 0 |
| Quotes confirmed / checked | 5–7 / 15–17 | 11 / 20 | 20 / 34 |
| — of which book text | 5–7 | 11 | 22 |
| Unattributed | 0 | 0 | 0 |
| Broken | 0 | 0 | 2 |
| Matched only a book card | 10 | 9 | 12 |
| Evidence items | 15–17 | 20 | 34 |
| Expected facts found | 13–14 / 15 | 14 / 15 | 14 / 15 |
| Answers carrying every fact | 7 / 8 | 7 / 8 | 7 / 8 |
| Titles mentioned | 106 / 106 | 106 / 106 | 106 / 106 |
| LLM calls | 28–30 | 30 | 32 |
| Tokens in | 34,483–38,354 | 38,724 | 44,676 |
| Tokens out | 2,093–2,309 | 2,958 | 5,098–5,137 |
| Per-question wall clock, min–max | 1–135 s | 3–390 s | 4–566 s |
| Seconds by role, median per attempt | plan 1.8 · **observe 47.5** · reflect 4.3 · synth 5.3 | plan 6.6 · **observe 100.3** · reflect 20.6 · synth 24.7 | plan 5.0 · **observe 68.5** · reflect 12.1 · synth 16.6 |
| Cost | $0.0000 | $0.0000 | $0.0000 |

Files: `answers-1789572328.{md,json}` (14b), `answers-1789580376.{md,json}` (32b),
`answers-1789590164.{md,json}` (mistral).

The six catalogue questions (`k01`-`k06`) are answered from the index tables in one model call with
no search on all three models — 1–7 seconds each, `stop: catalog: answered from the index tables, no
search`. The set separates nothing between these models.

## Per question, where they differ

Only four of the 21 items fail anywhere, and all four are in `en-demo`.

**`c09-shipwreck-first-person` — fails on `qwen2.5:14b`, passes on the other two, and the difference
is whether the clarify was asked at all.**

- `qwen2.5:14b`: `FAIL: titles 1/2, stop: enough evidence` — three attempts, no clarify, 8 calls,
  identical every time.
- `qwen2.5:32b`: `PASS: titles 1/2, clarify choice applied, stop: repeated clarify not allowed —
  finishing with what we have`. It still names one title of two; the identify group's PASS comes
  from asking, not from naming both. Candidates offered: Robinson Crusoe, *Gulliver's Travels*
  (chosen by `--clarify-pick second`), Moby Dick, *Twenty Thousand Leagues*, Huckleberry Finn.
- `mistral-small3.2:24b-ctx20k`: `PASS: titles 1/2, clarify choice applied, stop: step limit (4) —
  wanted to keep searching`.

This is ADR-013's coverage gate doing what it was built for on the two larger models and not firing
into a clarify on the 14b, which declares "enough evidence" with one book.

**`c04-crusoe-cannibals` — fails on `qwen2.5:32b` only.** `FAIL: titles 0/1, facts 0/2 NO, named
book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: requested chapter was already
attempted (re-reading cannot show more text)`. The named-book filter resolved correctly and the
32b then wrote an answer that does not mention the book it was reading. Both 14b and mistral pass
the same item with the same filter and the same stop reason. All three miss both expected facts.

**`c10-chivalry-two-books` — fails on both qwen models, passes on mistral.**

- `qwen2.5:14b`: `FAIL: titles 1/2, facts 1/2 NO, clarify choice applied, stop: repeated clarify
  not allowed — finishing with what we have` (attempt 1; attempts 2–3 stop at `enough evidence`
  with the same answer).
- `qwen2.5:32b`: `FAIL: titles 1/2, facts 0/2 NO, clarify choice applied, stop: enough evidence`.
  Both qwens clarify, both apply the second candidate (*Don Quixote*), and both then answer about
  one book.
- `mistral-small3.2:24b-ctx20k`: `PASS: titles 2/2, facts 0/2 NO, stop: enough evidence` — **1 step,
  4 calls, 5,230 tokens in**, no clarify at all. It retrieved both works on the first query, which
  is the cheapest pass anywhere in this batch and the only aggregation pass.

**`mistral-small3.2:24b-ctx20k` is 11/11 on `en-demo`** — the only 11/11 on the local backend in this
project's record, hosted Sonnet 4.6 on `v0.2.0-rc1` being the other one. Read it beside its broken
count.

### The facts row, and what it misses

`facts_found` per item, attempt 1 of each run (all three attempts agree except `k10` on the 14b):

| Item | `14b` | `32b` | `mistral` |
|---|---|---|---|
| `c01-ivanhoe-disguised-knight` | 2/3 | 2/3 | 1/3 |
| `c02-huck-go-to-hell` | 2/3 | 2/3 | 2/3 |
| `c03-musketeers-women` | 1/3 | 0/3 | 1/3 |
| `c04-crusoe-cannibals` | **0/2** | **0/2** | **0/2** |
| `c05-quixote-windmills` | 2/2 ✓ | 2/2 ✓ | 2/2 ✓ |
| `c06-fogg-missing-day` | 0/3 | 2/3 | 0/3 |
| `c07-alice-trial` | 1/3 | 1/3 | 2/3 |
| `c10-chivalry-two-books` | 1/2 | 0/2 | 0/2 |
| `h06-kobzar-mother-servant` | 1/3 | 3/3 ✓ | 3/3 ✓ |

The most common miss is not spread evenly: **`c04` loses both of its facts on all three models**, and
`c03` and `c10` lose all or all-but-one on all three. `c05-quixote-windmills` is the only `en-demo`
item every model carries in full. On the catalogue set the single miss is the same on all three —
`k10-hybrid-named-book`, 1/2 everywhere — and the other seven fact-bearing items are complete.
A behaviour PASS therefore says very little about the facts row: `c04` on the 14b and on mistral is
a PASS with 0/2 facts, and `c10` on mistral is a PASS with 0/2.

## Findings

### 1. Local models are deterministic across attempts, so `--repeat` here measures latency, not behaviour

**No behaviour verdict flipped anywhere.** Across 3 models × 2 sets × 11 or 10 items × 3 attempts,
every per-question `spread.behavior_ok` is 3/3 or 0/3 — never 1/3, never 2/3. The same holds for
`facts_ok`. The repeat produced 189 item-attempts and zero behavioural disagreements.

Below the verdict, the text itself:

- **`qwen2.5:32b` is byte-identical on every item of both sets.** All three attempts return the same
  answer string and the same provenance verification string, and the token counts are flat
  (142,792 in / 9,055 out on `en-demo`; 38,724 / 2,958 on the catalogue set) — not a range, one
  number.
- **`qwen2.5:14b` is byte-identical on all 11 items of `en-demo`** and on 9 of 10 catalogue items.
  Its `en-demo` token spread of 2 in / 34 out is entirely inside `c10`, the clarify item: the
  *answers* are identical, the internal path is not (attempt 1 stops at `repeated clarify not
  allowed`, attempts 2–3 at `enough evidence`, 14,884–14,886 in / 1,449–1,483 out). The one item
  whose text does move is `k10-hybrid-named-book`: two distinct answers over three attempts,
  8–10 calls, 10,580–14,451 tokens in — and the same PASS each time.
- **`mistral-small3.2:24b-ctx20k` varies on 4 items of 21**: `c03-musketeers-women` and
  `c08-refusal-tom-sawyer` on `en-demo`, `k08-about-whaling` and `k10-hybrid-named-book` on the
  catalogue set. Quantified, the variation is small: 0.5 % on tokens in (139,688–140,398) and 0.8 %
  on tokens out (12,700–12,803) for `en-demo`, 0.8 % on tokens out for the catalogue set, and the
  broken-quote count moves by one (8–9). Never enough to move a verdict.

What does vary, and by a lot, is time. On `qwen2.5:14b` / `en-demo` the per-question wall clock
spans 30–196 s while the answers do not change at all; `c01` runs 174 s on attempt 1 and 76–77 s on
attempts 2 and 3, for the identical 780 output tokens.

**So `--repeat N` against a local model at `temperature=0` buys a latency distribution and almost no
behavioural information.** It is not wasted — the latency spread is the number a local deployment
budget needs, and a zero spread is itself a published result rather than an assumption — but the
question `--repeat` was built to answer ("is this 9/11 stable, or did we sample the good run?")
cannot be answered on this backend. **Behaviour spread has to be measured on a hosted run**, where
the provider samples and the same prompt genuinely returns different text. That is the next
measurement, and it costs money.

### 2. `observe` dominates the clock, and the first attempt pays for residency

`observe` is 70–76 % of all model seconds in every one of the six runs — `en-demo`: 72 % (14b),
70 % (32b), 74 % (mistral); catalogue: 76 %, 67 %, 74 %. Nothing else comes close: `plan` is 4–8 %,
`reflect` 8–11 %, `synthesize` 9–15 %. Medians per call, `en-demo`:

| Role | `14b` | `32b` | `mistral` |
|---|---|---|---|
| `plan` | 3.4 s | 11.1 s | 7.2 s |
| `observe` | **45.3 s** | **136.5 s** | **107.5 s** |
| `reflect` | 8.3 s | 24.1 s | 18.5 s |
| `synthesize` | 8.3 s | 25.9 s | 20.1 s |

**Cold versus warm is visible in the same field**, and it is an `observe` effect above all. Median
`observe` seconds on attempt 1 against attempts 2–3, `en-demo`: 97.9 → 35.0 s on the 14b (2.8×),
241.2 → 98.0 s on the 32b (2.5×), 202.1 → 95.5 s on mistral (2.1×). The other roles barely move
(14b `plan` 3.7 → 3.3 s, `reflect` 11.8 → 7.0 s). `by_role_seconds` does not include the model
residency a first local question pays before any call, as `docs/evaluation.md` states, so the
attempt-1 penalty here is inside the calls: a longer prompt against a model whose weights and KV
cache are still being paged in. A latency budget written from attempt-1 numbers overstates steady
state by a factor of two to three, and one written from attempts 2–3 understates the first question
a reader ever asks.

### 3. Card-only matches are a large share of what is called evidence

`#64` made this countable for the first time. Per attempt:

| Set | `14b` | `32b` | `mistral` |
|---|---|---|---|
| `en-demo` | 9 of 45 (20 %) | 14 of 47 (30 %) | 17 of 67–69 (25 %) |
| `en-demo-catalog` | 10 of 15–17 (59–67 %) | 9 of 20 (45 %) | 12 of 34 (35 %) |
| both sets | 19 of 60–62 | 23 of 67 | 29 of 101–103 |

A book card is a per-book summary written by one model call at ingest time. A quote whose only
verbatim match is inside one is not a quote from the book, and on the catalogue set's four research
items **the majority of what the 14b cites is card text** — 10 of its 15–17 checked quotes. The
harness now says so in the report line and in the sidecar, and the confirmed ratio's denominator is
`checked_book_text` rather than `checked`.

**The triples published before 2026-09-16 counted these inside `confirmed`.** The most directly
affected published number is the local run of 2026-09-10 (`2026-09-10-local-models.md`, 58 / 1 / 2
over both sets, quoted in `README.md` and `docs/known-limits.md`): its confirmed count includes an
unknown number of card matches, because nothing separated them then. Nothing was re-run to correct
it and nothing should be — it is correct for what it measured — but it is not comparable, quote for
quote, with the table above.

### 4. Mistral has the best behaviour and the worst quote fidelity — which is the case `#65` exists for

`mistral-small3.2:24b-ctx20k` is the only model here that passes `en-demo` 11/11, including the
aggregation item both qwens fail, and it does it in fewer steps. It also leaves **8–9 broken quotes
per attempt** on that set and 2 more on the catalogue set — 10–11 per attempt over both, against
2 for the 14b and 1 for the 32b. A broken quote is text found in no retrieved passage at all: on
this code it reached the answer and was reported underneath it.

This is exactly the trade the evidence gate (`#65`) was accepted to remove, and it is why the gate's
own run must be made against **this** baseline rather than against the 14b alone. What that run has
to show, for each of the three models and both sets:

1. `confirmed == checked_book_text` and `broken == 0` — true by construction once the gate runs, so
   it is an assertion the run either satisfies or reveals a bug in.
2. A published drop rate: `dropped_unverified`, and `dropped_by_reason` split four ways
   (`no_hit`, `cross_book`, `short`, `not_found`), plus `repinned`. On mistral this number should be
   large — 8–9 quotes an attempt have to go somewhere — and if it is not, the gate is not seeing
   what `validate` saw here.
3. **Behaviour not below this baseline**: 9/11, 9/11, 11/11 on `en-demo` and 10/10 on the catalogue
   set for all three. A gate that buys clean provenance by costing mistral its aggregation pass is a
   different decision from the one that was accepted.
4. The two figures `docs/evaluation.md` names as consequences rather than causes: the
   coverage-probe firing count, and steps per question. Baseline steps per question here are low —
   mistral passes `c10` in 1 step — so a rise to `MAX_STEPS` on items whose quotes were all dropped
   will show plainly against these numbers.

**Answered 2026-09-17, in [the gate section below](#the-observe-gate-65-same-model-same-sets).**
Points 1 and 2 came out as written. Point 4 came out as written on mistral and not at all on the 14b:
`c10` really did go from 1 step to 2 and `c04` from 2 to 4, and the coverage probe did not move on
either model. Point 3 did **not** hold on mistral — it kept the aggregation pass this paragraph
worried about and lost a different item, `c03`, on two attempts of three, for a reason that has
nothing to do with step counts. The prediction was right about the mechanism and wrong about which
item it would cost.

### 5. The 131k-context trap

`mistral-small3.2:24b` could not be measured as pulled. Ollama loaded it with `num_ctx 131072`,
which on this machine means roughly 36 GB of weights-plus-KV and about 28 % of the model offloaded
to CPU (`_data/step0/step0.log`, 20:41). The first plan call of the first attempt of the first item
never returned: `c01-ivanhoe-disguised-knight (identify, 1 steps, 1201s, 1 calls, 603 in / 55 out
tokens, attempt 1/3) — FAIL: titles 0/1, stop: question deadline (1200 s) ran out during a model
call`. Its `by_role_seconds` reads `plan 192.2, observe 1005.4` — 603 input tokens took over three
minutes to plan against, and the deadline arrived inside `observe`. The run was stopped 21 minutes
in and the `.partial` recording removed; the one report it wrote is kept at
`_data/step0/results/mistral-small3.2_24b-ctx131k-aborted/`.

A derived model fixed it completely — `mistral-small3.2:24b` with `PARAMETER num_ctx 20480`, which
is the `-ctx20k` in every fingerprint above. The same 11 items then ran 73–399 s each.

**The application cannot fix this for the reader.** The local backend speaks to Ollama through its
OpenAI-compatible `/v1` endpoint, where an `options` block is accepted and ignored
(`src/ask_your_library/llm.py`), so there is no `num_ctx` this project can send. The context length
is a property of the model as Ollama holds it, set by a `Modelfile` or by the server's own
`OLLAMA_CONTEXT_LENGTH`. The recommendation is therefore documentation, not code: **any non-`qwen`
model whose default context window is large needs `num_ctx` set explicitly before it is worth
measuring**, and a reader who swaps `OLLAMA_LLM_MODEL` for a model with a 128k default on a 36 GB
machine will meet a deadline timeout rather than a memory error, which is a much harder failure to
read. A line to that effect is added to `docs/configuration.md` and `docs/known-limits.md` with
this report.

### 6. Bigger-same-family does not add passes; it moves them, at 2.6× the clock

`qwen2.5:32b` scores **9/11 on `en-demo`, exactly as `qwen2.5:14b` does**, and 10/10 on the
catalogue set, exactly as the 14b does. The verdicts are the same and the items are not: the 32b
wins `c09` (it clarifies where the 14b declares "enough evidence") and loses `c04` (it answers
without naming the book its own retrieval filter had already resolved). Two other rows move in the
32b's favour without changing a verdict — facts found 12/24 against 10/24, unattributed/broken 1/1
against 0/2 — and one moves against it: titles mentioned 9/12 against 10/12, and card-only matches
14 against 9.

The price is time: 7,277 s against 2,797 s on `en-demo` (**2.60×**) and 2,471 s against 765 s on the
catalogue set (**3.23×**), with median `observe` at 136.5 s against 45.3 s per call. Doubling the
parameter count inside one model family bought no behavioural improvement on these sets and cost
between two and a half and three times the wall clock. If the shipped default is to change, the
evidence here points across families rather than up a size ladder.

## The observe gate (`#65`), same model, same sets

Added 2026-09-17. Two runs under the gate, both on **`c79018a`** — `main` at the merge of `#65` —
both golden sets each, `--repeat 3 --clarify-pick second`, **no `--record-plans`**:
**`qwen2.5:14b`** (23:02:45 → 23:58:54 CEST) and **`mistral-small3.2:24b-ctx20k`** (00:04 → 02:29).
Sources: `_data/step0-gate/results/<model>/<set>/answers-*.{md,json}` and
`_data/step0-gate/step0.log`. `qwen2.5:32b` was not run. The two models do not give the same answer
about the gate, so each gets its own paired table and the acceptance is stated per model.

**It is not clean-stamped either, and that is the control.** Both runs stamp
`c79018a+dirty(2005429d26f5)` with `code_clean: false`, and — the informative part — **the same
checksum on both**, where the three baseline models produced five different ones. The cause is the
six baseline recordings, which were still untracked in the checkout when this run was made.
So the dirty stamp is not caused by `--record-plans` *taking* place; it is caused by an un-ignored
untracked file existing in the tree, and a later run that records nothing inherits the previous
batch's recordings all the same. The checksum being stable across this batch, where it moved on
every run of the recording batch, is the paired evidence for that reading. Committing the recordings
(this PR) is what makes the next run on this tree stamp clean; the general fix is in
`docs/backlog.md`.

### Paired table — `qwen2.5:14b`, `en-demo`, 11 items, 3 attempts

Baseline column repeats the table above (`169b511`, before the gate); gate column is the new run.
A single figure means all three attempts agreed exactly.

| Row | Baseline `169b511` | Gate `c79018a` |
|---|---|---|
| Behaviour PASS per attempt | 9/11 ×3 | **9/11 ×3** |
| — by group (`answer` / `identify` / `refusal` / `aggregation`) | 7/7 · 1/2 · 1/1 · 0/1 | 7/7 · 1/2 · 1/1 · 0/1 |
| Clarify interrupts | 1 | 1 |
| Confirmed / checked book text | 34 / 36 | **34 / 34** |
| Confirmed / checked, all quotes | 34 / 45 | 34 / 43 |
| Unattributed | 0 | 0 |
| Broken | **2** | **0** |
| Matched only a book card | 9 | 9 |
| Evidence items | 45 | 43 |
| Dropped before the answer | — (no gate in that code) | **2** |
| — `dropped_by_reason` | — | `not_found` 2 · `no_hit` 0 · `cross_book` 0 · `short` 0 |
| Re-pinned | — | 0 |
| Expected facts found | 10 / 24 | 10 / 24 |
| Answers carrying every fact | 1 / 9 | 1 / 9 |
| Titles mentioned | 10 / 12 | 10 / 12 |
| LLM calls | 79 | 79 |
| Tokens in | 132,375–132,377 | 132,309–132,311 |
| Tokens out | 7,981–8,015 | 7,863–7,897 |
| Per-question wall clock, min–max | 30–196 s | 30–196 s |
| Set wall clock | 2,797 s | 2,611 s |
| Steps distribution over 33 attempts | 2 steps ×21 · 3 ×6 · 4 ×6 | 2 steps ×21 · 3 ×6 · 4 ×6 |
| Seconds by role, median | plan 3.4 · observe 45.3 · reflect 8.3 · synth 8.3 | plan 3.3 · observe 41.4 · reflect 7.3 · synth 7.4 |

### Paired table — `qwen2.5:14b`, `en-demo-catalog`, 10 items, 3 attempts

| Row | Baseline `169b511` | Gate `c79018a` |
|---|---|---|
| Behaviour PASS per attempt | 10/10 ×3 | **10/10 ×3** |
| — by group (`catalog` / `answer`) | 6/6 · 4/4 | 6/6 · 4/4 |
| Clarify interrupts | 0 | 0 |
| Confirmed / checked book text | 5–7 / 5–7 | 5–7 / 5–7 |
| Broken · unattributed · card-only | 0 · 0 · 10 | 0 · 0 · 10 |
| Evidence items | 15–17 | 15–17 |
| Dropped before the answer · re-pinned | — | **0 · 0** |
| Expected facts found | 13–14 / 15 | 13–14 / 15 |
| LLM calls · tokens in · tokens out | 28–30 · 34,483–38,354 · 2,093–2,309 | 28–30 · 34,483–38,354 · 2,093–2,309 |
| Steps distribution over 30 attempts | 0 ×18 · 1 ×6 · 2 ×3 · 3 ×2 · 4 ×1 | 0 ×18 · 1 ×6 · 2 ×3 · 3 ×2 · 4 ×1 |
| Set wall clock | 765 s | 753 s |

The catalogue set is **unchanged in every field**, token for token and call for call. It had no
broken quotes to drop, so the gate had nothing to do on it.

### The reading — qwen2.5:14b

**Behaviour is unchanged: 9/11 and 10/10, item for item.** Not merely the same totals — the same
items, the same groups, the same two failures (`c09` and `c10`), the same single clarify. The facts
row, the titles row and `facts_ok` are also identical.

**Broken 2 → 0, and `confirmed == checked_book_text` (34/34) as the amendment says it must be.**
The 34 confirmed quotes are literally the same 34: the gate removed exactly the two broken ones from
the denominator and touched nothing else. `unattributed` was already 0 in the baseline, so nothing
had to be re-pinned, and `repinned` is 0.

**Two quotes dropped per attempt, both `not_found`, both from the items that carried the baseline's
two broken quotes** — `c01-ivanhoe-disguised-knight` (1) and `c02-huck-go-to-hell` (1), on all three
attempts. `no_hit`, `cross_book` and `short` are 0 across the whole run, so on this model and these
sets none of the three conservative refusals of ADR-004's re-pin limits fired at all; the only rule
that did any work is the plain one. The badge flips accordingly, from
`WARNING: 1 of 2 quotes NOT found verbatim in any retrieved passage (possible hallucination)` to
`OK: all 1 quotes found verbatim in the passages they cite (1 quotes dropped before the answer: not
found in the passages they cited)`.

**LLM calls are unchanged at 79 per attempt, and nothing had to compensate for anything.** The steps
distribution is identical in both runs — 21 attempts at 2 steps, 6 at 3, 6 at 4 — and it is
identical *per item*, not only in aggregate. `c03-musketeers-women` runs 4 steps in **both** runs and
`c08-refusal-tom-sawyer` runs 4 in both: neither was pushed to the step limit by the gate, because
neither had a quote dropped. Nine of the eleven items are byte-identical between the two runs, token
counts included; **the only two items that changed at all are `c01` and `c02`**, and they changed
because their answers are written from one evidence item fewer:

| | Baseline | Gate |
|---|---|---|
| `c01` tokens in / out | 10,514 / 780 | 10,469 / 652 |
| `c02` tokens in / out | 9,713 / 538 | 9,692 / 548 |

`c01` is the whole effect in one item. In the baseline its answer ends with two `Sources:` lines, the
second of which is the fabricated one; in the gate run that sentence never became evidence, the
answer is a paragraph with a single inline citation, and it still passes with the same `titles 1/1,
facts 2/3`. The run's 66 fewer input and ~118 fewer output tokens per attempt are that one dropped
sentence and its knock-on, not a behavioural change.

The 186 s the research set gained (2,797 → 2,611 s) is not attributable to the gate with any
confidence: role medians moved a little in the same direction (`observe` 45.3 → 41.4 s), the machine
was the only thing running in both cases, and one item's shorter synthesis cannot account for three
minutes. Read it as run-to-run noise on the same hardware.

**Determinism holds on the new code too.** All three attempts of the gate run are byte-identical on
every item of both sets, verification strings included — the same result the baseline gave for this
model on `en-demo`.

### Paired table — `mistral-small3.2:24b-ctx20k`

Added 2026-09-17. The second gate run, on the model the gate was argued for: same code `c79018a`,
same flags, no recording, 00:04 → 02:29 CEST.
Sources: `_data/step0-gate/results/mistral-small3.2_24b-ctx20k/<set>/answers-*.{md,json}`.

`en-demo`, 11 items, 3 attempts:

| Row | Baseline `169b511` | Gate `c79018a` |
|---|---|---|
| Behaviour PASS per attempt | 11/11 ×3 | **11/11, 10/11, 10/11** |
| — by group (`answer` / `identify` / `refusal` / `aggregation`) | 7/7 · 2/2 · 1/1 · 1/1 | **6–7/7** · 2/2 · 1/1 · 1/1 |
| Clarify interrupts | 1 | 1 |
| Confirmed / checked book text | 42–43 / 50–52 | **50 / 50** |
| Confirmed / checked, all quotes | 42–43 / 67–69 | 50 / 68 |
| Unattributed | 0 | 0 |
| Broken | **8–9** | **0** |
| Matched only a book card | 17 | 18 |
| Evidence items | 67–69 | 68 |
| Dropped before the answer | — | **10–11** |
| — `dropped_by_reason`, summed over 3 attempts | — | `not_found` 26 · `no_hit` 6 · `cross_book` 0 · `short` 0 |
| Re-pinned | — | 0 |
| Expected facts found | 11 / 24 | 12 / 24 |
| Answers carrying every fact | 2 / 9 | 2 / 9 |
| Titles mentioned | 11 / 12 | 10–11 / 12 |
| LLM calls | 82 | **88** |
| Tokens in | 139,688–140,398 | 153,109–154,451 |
| Tokens out | 12,700–12,803 | 14,011–14,053 |
| Per-question wall clock, min–max | 73–399 s | 96–403 s |
| Set wall clock | 6,061 s | 6,563 s |
| Steps distribution over 33 attempts | 1 step ×3 · 2 ×15 · 3 ×3 · 4 ×12 | **2 ×15 · 3 ×3 · 4 ×15** |
| Seconds by role, median | plan 7.2 · observe 107.5 · reflect 18.5 · synth 20.1 | plan 6.7 · observe 138.6 · reflect 23.6 · synth 17.6 |

`en-demo-catalog`, 10 items, 3 attempts:

| Row | Baseline `169b511` | Gate `c79018a` |
|---|---|---|
| Behaviour PASS per attempt | 10/10 ×3 | **10/10 ×3** |
| — by group (`catalog` / `answer`) | 6/6 · 4/4 | 6/6 · 4/4 |
| Confirmed / checked book text | 20 / 22 | **20 / 20** |
| Confirmed / checked, all quotes | 20 / 34 | 20 / 32 |
| Broken · unattributed · card-only | **2** · 0 · 12 | **0** · 0 · 12 |
| Evidence items | 34 | 32 |
| Dropped before the answer · re-pinned | — | **2 · 0** (`not_found` 6 over 3 attempts) |
| Expected facts found · answers with every fact | 14 / 15 · 7 / 8 | 14 / 15 · 7 / 8 |
| LLM calls · tokens in · tokens out | 32 · 44,676 · 5,098–5,137 | 32 · 44,540 · 5,079–5,120 |
| Steps distribution over 30 attempts | 0 ×18 · 1 ×3 · 2 ×6 · 4 ×3 | 0 ×18 · 1 ×3 · 2 ×6 · 4 ×3 |
| Set wall clock | 2,250 s | 2,130 s |

### The reading — mistral

**The provenance side is everything it was meant to be.** `broken` goes **8–9 → 0**,
`confirmed == checked_book_text` at **50/50**, `unattributed` 0, `repinned` 0. On the catalogue set,
2 → 0 and 20/20. Ten to eleven quotes an attempt are refused on the research set and 2 on the
catalogue set, split `not_found` 26 and `no_hit` 6 over the three research attempts — `cross_book`
and `short` never fired on either model, so nothing was lost to ADR-004's conservative re-pin
limits. Drops are concentrated: `c04` and `c10` 6 each over three attempts, `c06` 6 (all of them
`no_hit`), `c03` 5, and `c02`, `c05`, `c08` 3 each. `c01`, `c07`, `c09` and `h06` lose nothing.

**And the behaviour cost is real: 11/11 → 11/11, 10/11, 10/11.** One item, two of three attempts.
`c03-musketeers-women`, in the `answer` group:

- Baseline, all three attempts: `PASS: titles 1/1, facts 1/3 NO, named book -> retrieval filter The
  Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching`.
- Gate attempt 1, **1 quote dropped**: `PASS: titles 1/1, facts 1/3 NO, 1 quotes dropped before the
  answer (not in the passage they cited), ... stop: step limit (4) — wanted to keep searching`.
- Gate attempts 2 and 3, **2 quotes dropped**: `FAIL: titles 0/1, facts 1/3 NO, 2 quotes dropped
  before the answer (not in the passage they cited), named book -> retrieval filter The Three
  Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching`.

**The failure is not the step-limit mechanism, and the report should not pretend it is.** `c03`
takes 4 steps and 10 calls in *both* runs; only the number of surviving quotes differs. With one
quote dropped the answer still lists Madame Coquenard and the lady with the red cushion, each with a
`[The Three Musketeers — Alexandre Dumas, Chapter …]` citation. With two dropped, the surviving
evidence carries no usable citation and the model writes a hedge instead — "the women connected with
Porthos and Aramis are not explicitly named or detailed … The following is missing:" — with no book
name anywhere in it. `titles 0/1` is a substring check, so an answer that never names the book fails
it. The retrieval filter had resolved to the right book in every attempt; the answer stopped saying
so.

**The step-limit mechanism is real, and it is visible on two other items — both of which still
pass.** A step whose quotes are all dropped no longer counts as a dry step, the empty-streak stop
does not fire, and the loop keeps going:

| Item | Baseline steps / calls / tokens in | Gate steps / calls / tokens in |
|---|---|---|
| `c04-crusoe-cannibals` | 2 · 6 · 9,561 | **4** · 10 · 18,009 |
| `c10-chivalry-two-books` | 1 · 4 · 5,230 | **2** · 6 · 9,427 |

That is the whole of the `+6` LLM calls (82 → 88) and most of the ~14,000 extra input tokens per
attempt: `c04` gains 4 calls, `c10` gains 2, and every other item keeps its step count. It is also
why the steps histogram moves — the three 1-step attempts disappear and the 4-step bucket grows from
12 to 15 — and why the set costs 502 s more (6,061 → 6,563 s) with `observe` median up from 107.5 to
138.6 s. `c10`, the aggregation item, keeps `titles 2/2` and its PASS while doing twice the work;
`c04` keeps its PASS while doing twice the work. The cost here is time and tokens, not verdicts.

Determinism loosens slightly under the gate: 3 of 11 items differ across the run's own attempts
(`c03`, `c04`, `c08`) against 2 in the baseline (`c03`, `c08`), and `c03`'s difference is now the
one that decides a verdict.

The catalogue set is unaffected: same behaviour, same calls, same steps, 2 quotes dropped, and
136 fewer input tokens per attempt.

### Acceptance for `#29`, per model

The acceptance agreed in advance ([`../evaluation.md`](../evaluation.md)) was three conditions.
They do not come out the same way on the two models that have been run.

| Condition | `qwen2.5:14b` | `mistral-small3.2:24b-ctx20k` |
|---|---|---|
| 1. `confirmed == checked_book_text`, `broken == 0` by construction | **met** — 34/34 and 5–7/5–7, 0 broken | **met** — 50/50 and 20/20, 0 broken |
| 2. A published drop rate | **met** — 2/attempt research, 0 catalogue; `not_found` 2, rest 0; `repinned` 0 | **met** — 10–11/attempt research, 2 catalogue; `not_found` 26 + `no_hit` 6 over 3 attempts; `cross_book` 0, `short` 0, `repinned` 0 |
| 3. Behaviour at `--repeat` not below baseline | **met** — 9/11 and 10/10, item for item | **NOT met** — 11/11 → 10/11 on two of three attempts (`c03`), catalogue unchanged at 10/10 |

**Condition 3 fails on one model, one item, two of three attempts.** That is the honest size of it:
not a collapse, and not nothing. Stated in full — the gate buys 8–9 fewer broken quotes an attempt
on this model and costs one behavioural PASS on two attempts of three, plus 6 LLM calls, ~14,000
input tokens and 502 s per set.

**The mechanism behind the extra work is a decision that was taken deliberately.** A step whose
quotes were all dropped is held rather than counted as dry, so the empty-streak stop does not fire
and the loop spends the steps it has (`c04` 2 → 4, `c10` 1 → 2). That decision is what keeps `c10`
and `c04` passing while they search longer; it is also what makes a badly-quoting model run to the
step limit. `c03`'s failure is a separate effect — thinner evidence producing a hedged answer with
no citation in it — and no change to the hold decision would address it.

**What the owner can decide next**, named without a recommendation:

1. **Accept the trade as the price of zero broken quotes.** Publish 10–11/11 for this model with the
   drop rate beside it, and treat `c03`'s hedge as the correct behaviour of a model that has been
   denied the evidence it was going to misquote.
2. **Change hold → count-as-dry after N dropped steps.** Keep the hold for the first dropped step
   and let the second (or Nth) count toward the empty streak, which would return `c04` and `c10`
   toward their baseline step counts and give back most of the 6 calls and 502 s. It does not touch
   `c03`.
3. **Re-plan with a "quote verbatim" nudge in the `reflect` context.** Tell the model, in the loop,
   that quotes not present in the passage are being discarded, so the next step's quoting is aimed at
   the text rather than at the summary. This is the only one of the three that could move `c03`, and
   it is also a prompt change — so it invalidates every recording and needs its own baseline.

Not measured either way: `qwen2.5:32b` under the gate, and any hosted model under it.

## What this does not prove

- **Nothing here is correctness.** No answer was read against the golden notes. Every
  manual-correctness checkbox in all six reports is unticked, and the owner will grade them
  separately. Behaviour PASS is the harness's heuristic (titles by substring, refusals by phrase
  marker, clarify, drill-down); `facts_found` is folded, whitespace-normalised substring presence —
  it cannot tell a fact in a right sentence from the same fact in a wrong one; quote provenance says
  a quote is verbatim in the passage it cites, not that the answer reasons well from it. Three rows
  that cannot be confused (ADR-010), and none of them is the fourth.
- **One machine.** Every second on this page was measured on one M3 Pro with 36 GB. The role
  seconds, the cold/warm ratio and the 2.6× are properties of this machine and this Ollama build as
  much as of the models; the token counts and the verdicts are not.
- **Three attempts.** Enough to establish that these models return the same text three times in a
  row; not enough to bound how often they would not. A zero spread over three samples is not proof
  of determinism, and one item on the 14b and four on mistral did vary.
- **The gate is measured on two models of three, and they disagree.** `#65` is outside `169b511`
  and the six runs above. Under it, `qwen2.5:14b` keeps its behaviour exactly and
  `mistral-small3.2:24b-ctx20k` loses one item on two attempts of three — so "the gate is
  behaviour-neutral" is not a sentence this data supports, and neither is "the gate costs behaviour".
  It costs behaviour on a model that quotes badly, on one item, sometimes. `qwen2.5:32b` under the
  gate is not measured at all, and no hosted model is.
- **The catalogue set no longer separates anything.** All three models score 10/10, and the six
  catalogue questions are answered in one model call from the index tables with no search. It is a
  regression guard, not a discriminator, and reading three identical 10/10 rows as agreement between
  three models overstates what was asked of them.
- **Not paired with any hosted run.** The nearest hosted numbers are on different code, a different
  golden checksum, or both (`docs/known-limits.md` says which). Read the gap in shape, not in
  points.
