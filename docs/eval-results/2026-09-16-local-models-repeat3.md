> **Provenance of this artifact.** Six runs on 2026-09-16, three local models against two golden
> sets, every one of them at `--repeat 3 --record-plans --clarify-pick second` on the local backend
> (`LLM_BACKEND=ollama`, `EMBED_BACKEND=ollama`). **Code `169b511`** for all six — the merge of `#64`,
> which is the commit that first counted book-card matches apart from book text. **The evidence gate
> (`#65`) is NOT in this code.** Everything `#65` added — the quote check at the `observe` gate, the
> re-pin, the drop counters — landed after these runs, in `c79018a`, and nothing on this page
> measures it. That is the point of the page: it is the paired baseline the gate's own run is to be
> read against, agreed in advance in
> [`../evaluation.md`](../evaluation.md) ("the paired baseline on three local models is being
> produced, the gate's run comes after it").
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
- **The gate is not in this code.** `#65` is entirely outside `169b511`. Nothing here says what the
  evidence gate does to behaviour, to steps, or to the coverage probe; that is the run this page
  exists to be compared against.
- **The catalogue set no longer separates anything.** All three models score 10/10, and the six
  catalogue questions are answered in one model call from the index tables with no search. It is a
  regression guard, not a discriminator, and reading three identical 10/10 rows as agreement between
  three models overstates what was asked of them.
- **Not paired with any hosted run.** The nearest hosted numbers are on different code, a different
  golden checksum, or both (`docs/known-limits.md` says which). Read the gap in shape, not in
  points.
