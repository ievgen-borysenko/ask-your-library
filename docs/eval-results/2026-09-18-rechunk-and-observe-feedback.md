> **Provenance of this artifact.** Three runs, all on the local backend (`LLM_BACKEND=ollama`,
> `EMBED_BACKEND=ollama`) and all against the **re-chunked** demo index built on 2026-09-17
> (`transcripts_ollama = bge-m3/1024d, chunker sentence-pack-2, rows 11282, built
> 2026-09-17T21:59:46`). This page continues
> [`2026-09-16-local-models-repeat3.md`](2026-09-16-local-models-repeat3.md), which is the baseline
> document: its six runs are the pre-gate baseline, its "The observe gate" section is the `c79018a`
> gate run, and both columns marked *baseline* below are read from that page's runs, not re-measured
> here.
>
> **Part A** is the paired measurement `#28` owes: `qwen2.5:14b`, both golden sets, `--repeat 3
> --clarify-pick second`, no `--record-plans`, on **`main` `c9e12bc`**, against the gate run of
> 16.09 on the old index. **It is a before/after over six merges, not an isolated measurement of
> the re-chunk.** Five other pull requests landed on `main` between the two commits, two of them in
> the answer path — the full list, and what controls what, is in
> [what moved between the two columns](#what-moved-between-the-two-columns). Every conclusion in
> part A is stated as "this is what the system did before and after", and the re-chunk is offered as
> the most economical explanation of the pair, never as its only one.
>
> **Part B** is the measurement `#29` owes: `mistral-small3.2:24b-ctx20k` and `qwen2.5:14b`, the
> research set, `--clarify-pick second`, **one attempt each**, on the branch **`538e6a6`**. Single
> attempts were run because the two baseline runs this page compares against showed **low
> attempt-to-attempt variability**: over their three attempts, `qwen2.5:14b` returned byte-identical
> answers on 11 of 11 research items and 9 of 10 catalogue items (`k10-hybrid-named-book` is the
> exception), and `mistral-small3.2:24b-ctx20k` on 8 of 11 research items — `c03`, `c04` and `c08`
> varied, and `c03`'s *verdict* varied with it. That is an observation about those runs, **not
> determinism and not a property of the models**
> ([finding 1](2026-09-16-local-models-repeat3.md#1-local-models-are-deterministic-across-attempts-so---repeat-here-measures-latency-not-behaviour)
> on the baseline page says as much). `c03` is one of the two items part B turns on, so a single
> attempt here cannot tell a stable result from one draw of a varying one, cannot reproduce the
> 11/11 ↔ 10/11 spread the mistral baseline carries, and gives no spread of its own to read.
>
> Golden files: `en-demo.yaml@edc151948a58` (11 items) and `en-demo-catalog.yaml@72eb2c2b2655`
> (10 items); corpus `manifest@ed94677aa3a3`, `toc@ef7a347ace1d` — the same four checksums the
> baseline page carries, so the questions did not move. Settings on every run here:
> `strict_hit_id=on`, `clarify_pick=second`, `hit_chars=2500/12000(scan 120000)`, `candidates=5`,
> `deadline=1200s`, `$0.0/M` both ways. The branch runs additionally carry
> `max_dropped_streak=2`, which prints as `steps=4/2/2` where `main` prints `steps=4/2`; that
> third number is how a reader tells a run with the cap from one without it.
>
> Sources, all local and none of them in this repository:
> `_data/step5b/results/qwen2.5_14b/<set>/answers-*.{md,json}` with `_data/step5b/step5b.log`,
> `_data/step5b/step0.log`, `_data/step5b/ingest.log` and `_data/step5b/doctor.log` (Part A);
> `_data/step5/29/results/<model>/en-demo/answers-*.{md,json}` with `_data/step5/29/29.log` and
> `_data/step5/29/step0.log` (Part B); `_data/step0-gate/results/<model>/<set>/answers-*.{md,json}`
> for both baselines.
>
> **Nothing on this page is correctness.** Same three rows as always (ADR-010): behaviour PASS is
> the harness's heuristic, `facts_found` is folded substring presence, quote provenance says a quote
> is verbatim in the passage it cites. Every manual-correctness checkbox in all five reports is
> unticked.

# The re-chunk, and the feedback the gate now gives back — 2026-09-18

## What ran

| # | Run | Code | Index | Model | Set(s) | Attempts | Wall |
|---|---|---|---|---|---|---|---|
| A | the re-chunk pair | `c9e12bc` (`main`) | new, 11,282 rows | `qwen2.5:14b` | both | 3 | 2,844 s + 653 s |
| A′ | its baseline | `c79018a+dirty(2005429d26f5)` | old, 7,285 rows | `qwen2.5:14b` | both | 3 | 2,611 s + 753 s |
| B1 | the branch | `538e6a6` | new, 11,282 rows | `mistral-small3.2:24b-ctx20k` | `en-demo` | 1 | 2,941 s |
| B2 | the branch | `538e6a6` | new, 11,282 rows | `qwen2.5:14b` | `en-demo` | 1 | 1,477 s |
| B1′ | mistral's baseline | `c79018a+dirty(2005429d26f5)` | old, 7,285 rows | `mistral-small3.2:24b-ctx20k` | `en-demo` | 3 | 6,563 s |

A is two sets one after the other on 17.09: the research set **21:59:50 → 22:47:14** CEST
(2,844 s) and the catalogue set **22:47:18 → 22:58:11** (653 s), so 22:47 is the boundary between
them and not the end of the run — `_data/step5b/step0.log` logs `exit=0 22:47 … / en-demo` and
`exit=0 22:58 … / en-demo-catalog`, and `_data/step5b/step5b.log` closes the whole stage at
22:58:12. B1 ran 22:58:17 → 23:47:18 and B2 23:47:22 → 00:11:59, again one after the other on the
same machine (`_data/step5/29/step0.log`). Both baselines are the gate runs of 16–17.09 already
published on the baseline page.

**The index A and B read is the same index, rebuilt once.** `scripts/ingest_demo_corpus.py --stage
ingest` ran 21:35 → 21:59 on 17.09 and wrote `transcripts done: 11282 chunks in 24.5 min (FTS
rebuild 0.7s)` (`_data/step5b/ingest.log`, last line); `ayl-add --doctor` then reported `no drift:
every indexed book has its rows, and every row its book` over 35 books and both tables
(`_data/step5b/doctor.log`). The card table was not re-chunked and is the same 165 rows on both
sides of every pair here.

**A first attempt at this pair, on 17.09, is discarded and is not on this page.** Its report header
(`_data/step5/results-INVALID-old-index/qwen2.5_14b/en-demo-catalog/answers-1789660953.md`, line 3)
says `chunker=sentence-pack-2 rows=7285 built=2026-09-17T17:09:30` — the new chunker's name on the
old chunker's row count. `_data/step5/ingest.log` says why: `nothing prepared — run the prepare
stages first`, so the ingest stage skipped all 35 books, while `_data/step5/stamp.log` shows the
stamp stage had already written `transcripts_ollama: stamped bge-m3 / 1024d / chunker
sentence-pack-2` over the untouched table. The run that followed at 17:09 therefore measured the old
index under the new index's name. That a stamp can be written without the rows it describes is
issue `#75`; every number below comes from the second run, and the first is kept only as its
counter-example. A third artifact in the same tree, `_data/step5/29-failed-wordsplit/`, is a 19:09
launch that died in four seconds with `invalid model name` (both model names reached the harness as
one argument) and spent 0 calls.

## A. Before and after the re-chunk (`#28`)

The change this section is *about* is the chunker, `sentence-pack-1` → `sentence-pack-2`, and with
it 7,285 transcript rows → 11,282. It is not the only change between the two columns: the code goes
`c79018a` → `c9e12bc`, six merges apart. **What the tables below show is what the system did before
and what it did after, on the same questions** —
[what moved between the two columns](#what-moved-between-the-two-columns) lists everything in the
gap, says which of it is controlled for and which is not, and every reading in this section is
written to be read against that list.

### Paired table — `qwen2.5:14b`, `en-demo`, 11 items, 3 attempts

A single figure means all three attempts agreed exactly.

| Row | Baseline `c79018a`, old index | Re-chunk `c9e12bc`, new index |
|---|---|---|
| Behaviour PASS per attempt | 9/11 ×3 | **9/11 ×3** |
| — by group (`answer` / `identify` / `refusal` / `aggregation`) | 7/7 · 1/2 · 1/1 · 0/1 | 7/7 · 1/2 · 1/1 · 0/1 |
| — the two failures | `c09`, `c10` | `c09`, `c10` |
| Clarify interrupts | 1 | 1 |
| Items whose plan set a retrieval book filter | 5 | **2** — and `#71`, not the re-chunk, [is what moved it](#what-moved-between-the-two-columns) |
| Confirmed / checked book text | 34 / 34 | **33 / 33** |
| Confirmed / checked, all quotes | 34 / 43 | 33 / 50 |
| Broken · unattributed | 0 · 0 | 0 · 0 |
| Matched only a book card | 9 | **17** |
| Evidence items | 43 | **50** |
| Dropped before the answer | 2 | **3** |
| — `dropped_by_reason` | `not_found` 2, rest 0 | `not_found` 3, rest 0 |
| Re-pinned | 0 | **1** |
| Chapter reads · aimed · window off the head | — (no counters in that code) | **7 · 7 · 5** |
| Chapter row-cap hits | — | 0 |
| Expected facts found | 10 / 24 | 10 / 24 |
| Answers carrying every expected fact | 1 / 9 | **3 / 9** |
| Titles mentioned | 10 / 12 | 10 / 12 |
| LLM calls | 79 | **81** |
| Tokens in | 132,309–132,311 | 132,234 |
| Tokens out | 7,863–7,897 | 8,080 |
| Set wall clock | 2,611 s | 2,844 s |
| Steps distribution over 33 attempts | 2 ×21 · 3 ×6 · 4 ×6 | 2 ×21 · **3 ×3 · 4 ×9** |

### Paired table — `qwen2.5:14b`, `en-demo-catalog`, 10 items, 3 attempts

| Row | Baseline `c79018a`, old index | Re-chunk `c9e12bc`, new index |
|---|---|---|
| Behaviour PASS per attempt | 10/10 ×3 | **10/10 ×3** |
| — by group (`catalog` / `answer`) | 6/6 · 4/4 | 6/6 · 4/4 |
| Confirmed / checked book text | 7 / 7, 5 / 5, 5 / 5 | **6 / 6 ×3** |
| Broken · unattributed · card-only | 0 · 0 · 10 | 0 · 0 · **7** |
| Evidence items | 17, 15, 15 | **13 ×3** |
| Dropped · re-pinned | 0 · 0 | **1 ×3** · 0 |
| Chapter reads · aimed · window off the head | — | 2 · 2 · 0 |
| Expected facts found | 14 / 15, 13 / 15, 13 / 15 | 13 / 15 ×3 |
| Titles mentioned | 106 / 106 | 106 / 106 |
| LLM calls · tokens in · tokens out | 30, 28, 28 · 34,483–38,354 · 2,093–2,309 | **26 ×3** · 30,093–30,094 · 2,148–2,149 |
| Steps distribution over 30 attempts | 0 ×18 · 1 ×6 · 2 ×3 · 3 ×2 · 4 ×1 | 0 ×18 · 1 ×6 · **2 ×6** |
| Set wall clock | 753 s | 653 s |

### Per question, where the research set differs

Every column is one attempt's figures, identical on all three attempts of both runs unless the cell
says otherwise. `ev` is evidence items, `dr` dropped, `ch` chapter reads (window off the head in
brackets), *filter* a plan that resolved a book and set the retrieval filter.

| Item | Baseline | Re-chunk | What moved |
|---|---|---|---|
| `c01-ivanhoe` | PASS, t 1/1, f 2/3, 2 steps, ev 3, dr 1 | PASS, t 1/1, f **1/3**, 2 steps, ev **5**, dr **0**, **re-pinned 1** | the dropped quote is now found in a neighbouring passage |
| `c02-huck` | PASS, t 1/1, f 2/3, 2 steps, ev 3, dr 1, filter | PASS, t 1/1, f **3/3**, 2 steps, ev 4, dr **0**, ch 1 (1), filter | |
| `c03-musketeers` | PASS, t 1/1, f 1/3, 4 steps, ev 6, dr 0 | PASS, t 1/1, f **0/3**, 4 steps, ev 6, dr **1**, ch 1 (1) | |
| `c04-crusoe` | PASS, t 1/1, f 0/2, 2 steps, ev 2, **filter** | PASS, t 1/1, f 0/2, 2 steps, ev 2, ch 1 (1), **no filter** | the chapter read, and the lost filter (`#71`) |
| `c05-quixote` | PASS, t 1/1, f 2/2, 2 steps, ev 5, **filter** | PASS, t 1/1, f 2/2, 2 steps, ev **7**, ch 1 (1), **no filter** | the lost filter (`#71`) |
| `c06-fogg` | PASS, t 1/1, f 0/3, 2 steps, ev 5, filter | PASS, t 1/1, f 0/3, 2 steps, ev 6, ch 1 (**0**), filter | the read aimed and the head was the best match |
| `c07-alice` | PASS, t 1/1, f 1/3, 2 steps, ev 2, **filter** | PASS, t 1/1, f **0/3**, 2 steps, ev 2, ch 1 (1), **no filter** | the lost filter (`#71`) |
| `c08-refusal` | PASS, 4 steps, ev 4, dr 0 | PASS, 4 steps, ev 5, dr **1** | |
| `c09-shipwreck` | **FAIL**, t 1/2, 3 steps, ev 3, dr 0 | **FAIL**, t 1/2, 3 steps, ev 3, dr **1** | the failure is unchanged |
| `c10-chivalry` | **FAIL**, t 1/2, f 1/2, **3** steps, 9 calls | **FAIL**, t 1/2, f 1/2, **4** steps, **11** calls, ch 1 (0) | one more step, one more search |
| `h06-kobzar` | PASS, t 1/1, f 1/3, 2 steps, ev 3 | PASS, t 1/1, f **3/3**, 2 steps, ev **2** | fewer evidence items, more of the golden facts |

### The reading

**No verdict moved, on either set.** Not the same totals only — the same items, the same groups, the
same two failures (`c09`, `c10`), the same single clarify, `10/12` titles on both sides and `10/24`
facts on both sides. On a 55%-larger index, with every chunk cut at a different place and five other
merges in the gap, `qwen2.5:14b` returns the same eleven verdicts and the same ten catalogue
verdicts. **That is not the same as "nothing moved"**: the plan sets three fewer retrieval filters
(`#71`'s, [see below](#what-moved-between-the-two-columns)), the evidence mix moves, `c10` takes an
extra step and the facts row redistributes — the rows underneath change while the verdicts do not.
What `#28`'s acceptance asked for was that the defect be closed without behaviour going below the
baseline, and on this pair it is not below it anywhere.

**The facts total is identical and its distribution is not.** Both runs find 10 of 24 expected
facts, but not the same ten: `c02` 2 → 3, `h06` 1 → 3, against `c01` 2 → 1, `c03` 1 → 0, `c07`
1 → 0. `answers carrying every expected fact` moves 1/9 → 3/9 for the same reason. A row that holds
still while five of its nine items move is a caution about reading the row, not a result: on 24
substring probes over 11 questions, the total is the least informative thing the row contains.

**The extra evidence is card text, not book text.** The arithmetic, since the two halves sum:
card-only matches go 9 → 17, which is **eight more**, and `checked_book_text` goes 34 → 33, which is
**one fewer** — so evidence items go 43 → 50, **seven more in net**. Nothing moved from one side to
the other: eight card matches were added and one book-text match was lost. The re-chunk did not put
more of the books in front of the model on this set, and `docs/evaluation.md`'s warning that card
matches are counted inside the provenance triple applies to this page with more force than to the
last one.

**One quote is re-pinned where it used to be dropped.** `c01-ivanhoe` loses a quote to `not_found`
in the baseline and loses none here, with `repinned` 1: the same model wrote the same sentence, and
after the change the passage that holds it is the passage the quote is pinned to. That is the re-pin
path of ADR-004 doing on a real run what it was written for, and it is the only cell on this page
where provenance is better after than before rather than merely different. Against it, `c02` also
stops dropping, while `c03`, `c08` and `c09` each lose one quote they did not lose before, so the
run total goes 2 → 3.

**The chapter read aims, and twice in seven it keeps the head.** `chapter_reads` 7,
`chapter_reads_aimed` 7, `chapter_windows_opened` 5, `chapter_row_cap_hits` 0, on all three
attempts. Every read the model made filled the new optional field — "what am I opening this chapter
for" — which is the first thing `#28` said the measurement had to answer, and it is answered
`7/7`. Five of those reads moved the window off the head of the chapter; `c06-fogg` and
`c10-chivalry` kept the head, which is the documented behaviour when the query's own words are not
found further in, not a read that failed to aim. On the catalogue set 2 reads, 2 aimed, and **0**
moved off the head — the catalogue questions are answered from the front of a section, so there the
window has nowhere better to go.
The baseline cannot be compared here at all: that code has no such counters, so the row is `—` and
not `0`.

**It costs two calls per attempt on the research set, and the cost has a name.** LLM calls 79 → 81
*per attempt*, and the steps distribution moves three attempts from 3 steps to 4 — all three of them
`c10-chivalry`, which goes 3 steps/9 calls → 4 steps/11 calls and fails either way. The set clock,
which covers all three attempts together, goes 2,611 → 2,844 s: **+233 s on the set**, about +78 s
an attempt, +8.9%. The catalogue set goes the other way on cost: 28–30 calls → 26 per attempt,
753 → 653 s on the set (−13%), and the steps distribution loses its 3- and 4-step attempts
entirely.

**The catalogue run became attempt-identical.** In the baseline one item varied,
`k10-hybrid-named-book`, whose first attempt took 10 calls and 4 evidence items against 8 and 2 on
the other two — enough to move the set totals to 30 calls against 28, 17 evidence items against 15
and 14 facts against 13. After the re-chunk all three attempts agree in every row, and both sets are
byte-identical across attempts. That is an observation about these three attempts and not a property
of the model.

### The chunk window itself

The run footer prints `hit_chars=2500/12000(scan 120000)` on both branch and `main` runs here: the
window `observe` reads a hit through did not move, and `SEARCH_HIT_CHARS` is the same 2,500 it has
always been. What moved is the text behind it.

The distribution is not something these runs measure — a report counts quotes, not chunk lengths —
so the claim `#28` published stands on its own measurement of the 35 prepared texts: **11,282
chunks, median 2,304, the longest 2,400, 0% over the window**, against 7,285 / 3,922 / 10,778 /
90.3% before it ([known limits](../known-limits.md), [ADR-025](../adr/README.md)). What this page
can add is that the index these runs read holds **exactly 11,282 transcript rows** — the ingest
log's last line and the `_index_meta` stamp both say so, and the doctor reports no drift — which is
consistent with the rows these answers were retrieved from having the distribution measured on the
prepared texts, and is one number matching rather than an independent re-measurement. The
over-the-window percentage is not recomputed anywhere on this page.

### What moved between the two columns

The baseline is `c79018a` and this run is `c9e12bc`, and `git log --first-parent c79018a..c9e12bc`
is six merges. Every one of them is in the gap the table reads as "the re-chunk":

| Merge | What it is | In the answer path? | Controlled for? |
|---|---|---|---|
| `#66` | the baseline eval reports and the planner recordings | no — documentation and `eval/` fixtures | n/a |
| `#67` | the book ledger and `bookkey` | **yes** — the `read_chapters` grammar moves out of `nodes.py` unchanged, but the retrieval book filter switches from a title prefix match to `bookkey.names_book`, and `catalog.py`, `clarify.py` and `provenance.py` follow it | **no** |
| `#68` | index stamps, backups, the ingest lock | **marginally** — `library.py` gains a once-per-process chunker-mismatch WARNING and nothing else on the read path; the rest is ingest and CLI | **no** |
| `#69` | **the re-chunk itself and the aimed chapter read** — the change this section is about | **yes** | it is the subject, not a confound |
| `#71` | the scope gate, one optional field in `PLAN_RULES` | **yes** — `plan` may now end a run before it searches, and its prompt changed | **yes**, and the control shows it moves a row — see below |
| `#74` | the docs-as-code suite | no — one `add_folder.py` touch and a test file | n/a |

`#65`'s evidence gate is in **both** columns, which is what makes the `dropped`, `repinned` and
`confirmed == checked_book_text` rows comparable at all.

**`#71` has a control run, it costs no behaviour — and it moves one row of the table above.** On
17.09 at 18:26 the core set ran once on the `#71` branch (`4b8a012+dirty(f44fdad60181)`) against the
**old** index: `9/11`, the same two failures, 78 calls, and no gate refusal on any of the eleven
questions (`_data/step5/scope/core/answers-1789662403.md`, and
[`2026-09-17-scope-canary-qwen2-5-14b.md`](2026-09-17-scope-canary-qwen2-5-14b.md) on `main`). That
is the old index with the new planner prompt, which makes it a control for more than the gate — and
read that way it says something the behaviour row does not. **The number of research items whose
plan resolves a book and sets a retrieval filter is 5 in the baseline, 2 in run A — and 2 in this
control, on the old index.** The three items that lose their filter are `c04-crusoe`,
`c05-quixote` and `c07-alice`, the same three in both. So that row belongs to `#71`, which added a
field to `PLAN_RULES` and changed what the planner writes beside it; it is not the re-chunk, and it
is a reminder that "no behaviour PASS moved" is a narrower statement than "nothing moved".
`mistral-small3.2:24b-ctx20k`, which never ran on `#71`, sets the same six filters before and after
the re-chunk, which is the paired evidence for reading it this way.

**`#67` and `#68` have no control run at all.** `#67` carries a real behavioural change on the same
retrieval filter — a bare title that used to match a book key by prefix now has to match it by
`bookkey.names_book` — and while the three filters that disappear are accounted for by `#71` above,
nothing here separates `#67`'s effect on the two that remain. `#68`'s only read-path change is a
warning. **This is the part of the confound this page cannot close.** The sentence the tables
support is "before these six merges the system did this, and after them it does that"; "the
re-chunk did it" is the most economical explanation of the pair and stays an explanation.

## B. Observe feedback, the book named, and the cap (`#29`)

Three changes are measured together, because they ship together: `observe` is handed back the
quotes the gate refused (`<quotes_dropped_earlier>`), `SYNTHESIZE_RULES` asks the answer to name the
book in its own text, and `MAX_DROPPED_STREAK` (2) bounds a run of all-dropped steps.

### Paired table — `mistral-small3.2:24b-ctx20k`, `en-demo`, 11 items

The baseline column is three attempts on the old index; the branch column is one attempt on the new
one. **Six changes are in that gap**, not one: `#28`'s re-chunk and `#29` together with `#66`,
`#67`, `#68` and `#74` — and not `#71`, which is on `main` and not on this branch. See
[the confound](#the-confound-applies-here-too); nothing in this table can be assigned to `#29`
alone.

| Row | Baseline `c79018a`, old index, ×3 | Branch `538e6a6`, new index, ×1 |
|---|---|---|
| Behaviour PASS | 11/11, 10/11, 10/11 | **10/11** |
| — by group (`answer` / `identify` / `refusal` / `aggregation`) | 6–7/7 · 2/2 · 1/1 · 1/1 | 6/7 · 2/2 · 1/1 · 1/1 |
| — the failure | `c03` on attempts 2 and 3 | **`c05`** |
| Clarify interrupts | 1 | 1 |
| Confirmed / checked book text | 50 / 50 | **32 / 32** |
| Broken · unattributed | 0 · 0 | **0** · 0 |
| Matched only a book card | 18 | 19 |
| Evidence items | 68 | **51** |
| Dropped before the answer | 10, 11, 11 | **16** |
| — `dropped_by_reason` | `not_found` 8–9 + `no_hit` 2 | `not_found` **16**, `no_hit` **0** |
| Re-pinned | 0 | 0 |
| Chapter reads · aimed · window off the head | — (no counters in that code) | 7 · 7 · 5 |
| Expected facts found | 12 / 24 | **9 / 24** |
| Answers carrying every expected fact | 2 / 9 | **0 / 9** |
| Titles mentioned | 11/12, 10/12, 10/12 | 10 / 12 |
| LLM calls | 88 | **85** |
| Tokens in · out | 153,109–154,451 · 14,011–14,053 | 144,678 · 12,893 |
| Set wall clock | 6,563 s over 3 attempts | 2,941 s |
| Steps distribution | 2 ×15 · 3 ×3 · 4 ×15 | 2 ×5 · 3 ×2 · 4 ×4 |

The wall clocks compare only against the first attempt: a single run pays for model residency, as
the baseline page's finding 2 says. Attempt 1 of the baseline sums to 3,096 s of per-question time
against this run's 2,941 s.

### Paired table — `qwen2.5:14b`, `en-demo`, 11 items — the closest pair on this page

Both columns are the **same index**, the same corpus and the same golden file; only the code
differs. It is the closest this page gets to isolating `#29`, and it is **not** a one-change pair:
the branch is `538e6a6`, which is the `#29` work merged with `main` at `64e700b`, while run A is
`c9e12bc` = `64e700b` + `#71`. So `#29` is present in the branch column and absent from run A, and
`#71` is present in run A and absent from the branch. The fingerprints say so: run A prints
`steps=4/2`, the branch prints `steps=4/2/2`, and only run A can refuse at the scope gate. Two rows
below are `#71`'s and not `#29`'s — the items that set a retrieval book filter (2 in run A, 5 in the
branch, the same 5 as the pre-`#71` baseline) and the three items behind them, `c04`, `c05` and
`c07`.

| Row | Run A, `c9e12bc`, ×3 | Branch `538e6a6`, ×1 |
|---|---|---|
| Behaviour PASS | 9/11 ×3 | **10/11** |
| — by group | 7/7 · 1/2 · 1/1 · 0/1 | 7/7 · **2/2** · 1/1 · 0/1 |
| — the failures | `c09`, `c10` | **`c10`** |
| Clarify interrupts | 1 | **2** |
| Items whose plan set a retrieval book filter | 2 | **5** — `#71`'s row, not `#29`'s |
| Confirmed / checked book text | 33 / 33 | **34 / 34** |
| Broken · unattributed | 0 · 0 | 0 · 0 |
| Matched only a book card | 17 | **10** |
| Evidence items | 50 | **44** |
| Dropped before the answer | 3 | **4** |
| — `dropped_by_reason` | `not_found` 3 | `not_found` 3 + **`no_hit` 1** |
| Chapter reads · aimed · window off the head | 7 · 7 · 5 | **8 · 8 · 6** |
| Expected facts found | 10 / 24 | **9 / 24** |
| Answers carrying every expected fact | 3 / 9 | 2 / 9 |
| Titles mentioned | 10 / 12 | **9 / 12** |
| LLM calls | 81 | **82** |
| Tokens in · out | 132,234 · 8,080 | 133,829 · 8,413 |
| Wall clock | 2,844 s (attempt 1: 1,494 s) | 1,477 s |

Item for item against run A: `c01` gains a step and a chapter read and keeps its PASS; `c09` turns
FAIL → **PASS**; `c10` stays FAIL with the same 1/2 titles and goes 4 steps → 3; every other item
keeps its verdict. **No item on this model is below its baseline** — which is the acceptance
condition as it was written, and is a statement about the pair rather than about `#29`: `#71`'s
planner prompt is in run A and not in the branch, and `c09`, the item that moved, is one where the
plan's own decisions (whether to clarify, which book to resolve) are what the verdict turns on.

### `c03` on mistral: the answer names the book now

The baseline's `c03-musketeers-women` is the item `#29` was written for. On attempts 2 and 3 it
scored `titles 0/1` and FAILED: 9 evidence items, 2 dropped, and an answer that opens "Based on the
provided evidence, the women connected with Porthos and Aramis are not explicitly named" and never
writes *The Three Musketeers* anywhere — with `unused: 9`, the harness's own note that nine pieces
of evidence belonged to a book the answer does not name.

On the branch the item PASSES with `titles 1/1`, and it does so **on less evidence than the two
failing attempts had**: 6 evidence items against 9, 3 quotes dropped against 2, the same 4 steps and
10 calls, and the same hedging conclusion ("The evidence does not provide specific names or detailed
information about the women connected with Porthos and Aramis"). The answer's first sentence is now
`The evidence from "The Three Musketeers" provides some information about the women connected with
Porthos and Aramis.` The hedge did not go away and the facts row went 1/3 → 0/3; what changed is
that a reader of the first sentence knows which book is being spoken of — which is what
`SYNTHESIZE_RULES` asks for, and it happens here under evidence thinner than the evidence the item
failed on, which is the harder condition. Attribution, said properly: six merges are between these
two columns, so this is the before and the after and `SYNTHESIZE_RULES` is the change in them that
asks for exactly this sentence. The run also reads a chapter here (`The Three Musketeers —
Alexandre Dumas|Chapter IX.|partial`), which the baseline code could not do, and that is `#28`'s.

### `c05` on mistral: what happened, in one paragraph

`c05-quixote-windmills` passed all three baseline attempts with `titles 1/1`, `facts 2/2`, 8
evidence items and one dropped quote; on the branch it FAILS with `titles 0/1`, `facts 0/2`,
**zero** evidence items and **5 quotes dropped, all `not_found`**, over 3 steps and 6 calls. The
retrieval was not the problem: the scratchpad
(`_data/step5/29/results/mistral-small3.2_24b-ctx20k/en-demo/scratch-c05-quixote-windmills.md`)
shows all three steps returning 8 hits each, filtered to *Don Quixote*, with two chunks of
`CHAPTER VIII.` — the windmills chapter — as the top two transcript hits on every one of them (the
four cards rank above them, as they always do). What changed is the route: the
baseline answered this question by asking for chapters outright (`__chapter__|Don Quixote —
Miguel de Cervantes|CHAPTER VIII.`, then `CHAPTER XXIII.`) and quoting from what came back, while
the branch run never asked for a chapter at all (`chapter_reads` 0) and instead issued two ordinary
searches, quoting five times from the retrieved passages and getting all five refused as not
character-exact. The `<quotes_dropped_earlier>` block was therefore in front of the model on steps 2
and 3 by construction — `observe` writes `dropped_quotes` whenever the gate refuses one, and the
next `observe` prompt carries the last six with the sentence "copy exactly this time" — and the
model went on writing quotes the gate refused; the run's artifacts record the refusals but not the
prompt, so the block's *presence* is read from the code path and its *effect* here is read from the
outcome, which is none. **The answer names no book because there is no answer**: with
`state["evidence"]` empty, `synthesize` returns the fixed refusal ("I searched both the book cards
and the transcripts, but found no evidence for this question in the library. Honest answer: I don't
know.") by code, without a model call, so `SYNTHESIZE_RULES` — the rule that asks for the title —
was never sent. The naming rule cannot rescue an answer that has no evidence behind it; that is the
shape of this failure, and it is a different shape from `c03`'s, which was a thin answer that
existed and would not name its book.

### Did the cap fire?

`c05` stopped at 3 steps on `CRAG gate: 2 dry steps in a row`, where the same item ran to 3 steps in
the baseline and other mistral items ran to 4. Under `MAX_DROPPED_STREAK=2` a step that drops every
quote is held on the first occurrence and counted dry from the second, so three consecutive
all-dropped steps reach `empty_streak` 2 exactly at step 3 and the gate ends the run there — which
fits. **It is not the only sequence that fits.** A step that produces no quotes at all is dry by the
rule that predates `#29`, so one all-dropped step followed by two silent ones ends at the same place
with the same message. The run's artifacts do not break the 5 refusals down per step and
`dropped_streak` is not written into the report or the sidecar, so **this page cannot say which of
the two happened**, and therefore cannot say that the cap saved a step here. Whether `MAX_DROPPED_STREAK`
ever fired in either branch run is not decidable from what these runs recorded. Making it decidable
is one counter — refusals per step, or the streak at the stop — in the item header.

### `c09` on `qwen2.5:14b`: a PASS with no evidence and no title

The 14b branch run turns `c09-shipwreck-first-person` from FAIL to PASS, and the mechanism deserves
saying out loud because the row is the one that carries the acceptance. `c09`'s golden
`expected_behavior` is `clarify`, so behaviour PASS means "it asked the clarifying question", and
nothing else. Run A did not ask (3 steps, no clarify) and failed; the branch run asked on step 4 and
passed. What follows the question is not part of the PASS and is worse than the baseline's: the
harness answered with the second expected book, the resolver accepted it
(`clarify_chosen: Gulliver's Travels — Jonathan Swift`, `clarify_unresolved: false`), the post-clarify
filter kept only evidence for the chosen book and there was none, so the item ends with **0 evidence
items, `titles 0/2`, and the same code-written refusal as `c05`** — which is why the diagnostic row
reads `choice: violated` rather than `applied`: the refusal names no book, so no chosen title can be
found in it. `titles mentioned` for the set drops 10/12 → 9/12 on exactly this item. The PASS is the
behaviour and nothing but the behaviour.

### The confound applies here too

The 14b pair (run A against the branch) is the closest pair on this page and still carries two
changes, `#29` one way and `#71` the other, as the table above says. **The mistral pair carries
six.** Its baseline is the old index on `c79018a`, so the gap holds `#28`'s re-chunk, `#66`, `#67`,
`#68` and `#74` as well as `#29` — but not `#71`, which is on `main` and not on the branch — and
there is no run of `mistral-small3.2:24b-ctx20k` on the new index without `#29` to separate them.
`c05`'s regression sits inside that gap and cannot be assigned. The 14b pair suggests `#29` is not
by itself what breaks such an item — the same index and the same three `#29` changes cost 14b
nothing and gain it `c09` — but that pair carries `#71` in the opposite direction, it is a different
model, and neither of those is a control. The run that would settle it is
`mistral-small3.2:24b-ctx20k` on `c9e12bc`, the new index without `#29`, and it was not made.

### Acceptance

The acceptance stated in the PR and in ADR-004's amendment of 2026-09-17 was three conditions.

| Condition | `qwen2.5:14b` | `mistral-small3.2:24b-ctx20k` |
|---|---|---|
| 1. Not below its baseline, item for item | **met** — 10/11 against run A's 9/11 on the same index; `c09` FAIL → PASS, every other item unchanged, none lost. The pair is the closest on this page and still carries `#71` the other way, so this is met as a before/after, not as an isolated effect of `#29` | **not applicable** — no same-index baseline exists for this model |
| 2. Not below 10/11, with `c03` naming the book | — | **met** — 10/11, and `c03` PASSES with `titles 1/1` on 6 evidence items where the failing baseline attempts had 9 |
| 3. `broken == 0` | **met** — 0 broken, 34/34 confirmed | **met** — 0 broken, 32/32 confirmed |

**Every stated condition is met.** Said exactly, because the shape of the mistral column is easy to
round off: the baseline is **11/11, 10/11, 10/11** over its three attempts, and the branch run is
**10/11**. The branch matches two of those three attempts and is one item below the third. "Not
below 10/11" — the condition as it was written — is met; "mistral is where it was" would need the
11/11 attempt to be the outlier, and one attempt cannot say whether it was.

**Separately: the failure moved rather than disappeared.** The item that fails is not the same item.
`c03` failed on two of the three baseline attempts and passes here; `c05`, which passed all three,
fails. Read as "the regression `#29` was written to fix is fixed", the row is true; read as "mistral
got better", it is not, and the second reading is the one a bare 10/11 invites. Beside it:
`facts_found` 12/24 → 9/24, `answers carrying every expected fact` 2/9 → 0/9, evidence items
68 → 51, and 16 quotes dropped against 10–11. On this model the branch produces less of everything
and passes a count of items inside the baseline's own range.

**Part B is one attempt per model, against baselines whose observed variability was low.** That is
not the same as a deterministic model, and this page does not claim one. Measured on the two
baseline runs themselves: `qwen2.5:14b` repeated itself byte for byte on 11 of 11 research items and
9 of 10 catalogue items, and `mistral-small3.2:24b-ctx20k` on 8 of 11 research items — `c03`, `c04`
and `c08` varied, and of those only `c03`'s verdict moved with it. `c03` is one of the two items
this section turns on. So a single attempt here cannot tell a stable result from one draw of a
varying one, cannot reproduce the 11/11 ↔ 10/11 spread the mistral baseline carries, and offers no
spread of its own against which to read either number. The three-attempt columns on this page do
repeat themselves row for row, the catalogue run included; that is evidence about those runs, not a
property of the models.

## What this does not prove

- **Nothing here is correctness.** No answer was read against the golden notes; every
  manual-correctness checkbox in all five reports is unticked. Behaviour PASS is a heuristic over
  titles, refusal markers, clarify and drill-down; `facts_found` is folded substring presence and
  cannot tell a fact in a right sentence from the same fact in a wrong one; quote provenance says a
  quote is verbatim in the passage it cites and nothing about the reasoning around it.
- **The re-chunk pair carries five other merges, and one of them moves a row.** `#71` has a control
  run of its own on the old index: it costs no behaviour PASS, but it *is* what takes the items
  setting a retrieval book filter from 5 to 2, so "controlled for" means "its effect is identified",
  not "it has none". `#66` and `#74` are reports and tests. `#67` and `#68` have no control at all,
  and `#67` changes the book-filter match rule. Part A's reading is the most economical explanation
  of the pair, not the only one it admits.
- **The mistral pair carries six merges**, `#28`'s re-chunk and `#29` among them, and `c05`'s
  regression cannot be assigned to any of them. The run that would separate the two that matter —
  mistral on `c9e12bc`, the new index without `#29` —
  was not made.
- **Whether `MAX_DROPPED_STREAK` fired is not in the data.** The cap is configured (`steps=4/2/2`,
  `max_dropped_streak: 2` in both branch sidecars) and `c05` stops in a way consistent with it, but
  no artifact records the streak or the per-step refusal counts, so the cap has no measured effect
  on this page in either direction.
- **The chunk-length distribution is not re-measured here.** It is quoted from `#28`'s measurement
  of the 35 prepared texts and tied to these runs by one matching number, the 11,282 rows in the
  index. "0% of chunks over the window" is not a figure any run on this page computed.
- **One corpus, 21 questions, two models.** The 33-book demo corpus at one index build; the research
  set is 11 items, so a single item is worth 9 points of a behaviour row. `qwen2.5:32b` was not run,
  no hosted model was run, and the Ukrainian and catalogue sides of the corpus are one item and ten
  items respectively.
- **One machine, and the clocks say so.** Every second here is an M3 Pro with 36 GB running Ollama,
  and the first attempt of each run pays for model residency: the per-attempt wall clocks are a
  property of that machine as much as of the models. The token counts and the verdicts are not.
- **Part B is one attempt per model, and nothing here shows determinism.** The baselines repeated
  themselves on 11 of 11 and 8 of 11 research items across their three attempts; that is low
  observed variability on those runs, not a property of these models, and `c03` — one of the two
  items part B turns on — is among the items that did vary. A single attempt has no spread of its
  own, so neither part B number can be placed inside or outside a range.
