# Evaluation

The harnesses, the golden sets and the runs behind the results table; the README carries the
same table without this text around it.

**`eval/run_retrieval_eval.py` - component baseline, no LLM calls.** Feeds the *raw* golden
question to the retriever and asks whether the resulting window (top-4 card chunks + top-4
transcript chunks, exactly what `search_both` gives the agent) contains the expected book(s).
Single-book questions score presence; multi-book questions score coverage and whether *all*
expected books are present. Per-corpus hit@k and MRR are diagnostics only. This measures the
retriever with the raw question; the agent rewrites the question into its own queries, so this is a
component baseline, not a bound on agent quality in either direction.

**`eval/run_agent_eval.py` - behavioural scoring of the full loop.** Every golden question runs
through the whole graph (clarify interrupts are auto-answered, so the run is non-interactive),
scored on: expected titles mentioned in the answer (accent-folded substring, not a citation
check), refusal questions answering with an explicit refusal (an evidence-free answer told from
model knowledge fails), `expected_behavior: clarify` questions actually triggering a clarify
interrupt, `expects_chapter_read` questions actually drilling into a chapter of an expected
book, and `catalog` questions on their structured result (the set of books the code listed must
equal the expected set of index keys, "Title — Author", so the right title under a wrong author
fails; the count must be the length of that list, the operation must be the one
the item names, and the catalogue as a whole must hold the `expected_total` the item was written
for, or a run of two or three items could certify a partial index; a research question answered
by the catalogue path fails, and so does a research control the planner did not route itself,
where a planner or catalogue fallback searched instead). Quote provenance totals come from
`validate`. Scoring is heuristic, no LLM judge -
**answer correctness is still a manual read**, which is why the harness writes every answer
into a report with a per-question correctness checkbox.

Three golden sets, reported separately. **Core** (`eval/golden/en-demo.yaml`, 11 questions, the
default `GOLDEN_PATH`): eight questions on books the golden author has read and a two-book
comparison of two of them (Ivanhoe and Don Quixote), all nine reader-verified; h06, one of the two
questions the example traces are built on, verified against the source text by an AI session only;
and one genuinely ambiguous identify (Crusoe or Gulliver), proposed and awaiting the reader's
verdict on the item itself. Each item's notes state its level. The file held twelve questions when
the v0.1.0 column was measured; the reader removed h12 on 06.09, and the v0.2.0-rc1 column is the
eleven-question set (see the note under the table).
**Extended**
(`eval/golden/en-demo-extended.yaml`, 21 questions) is the former v3 draft with near-duplicates
removed; its notes were checked against the source text by an AI session only, so its numbers are
exploratory.
**Catalogue** (`eval/golden/en-demo-catalog.yaml`, 10 questions): six questions about what the
library holds (count, the full list, a title that is there, one that is not, an author, the count
in Ukrainian), scored on the structured result against the manifest's book keys and its size;
three content questions
that look like listings as negative controls (one scored on routing alone); and one hybrid item
that pins the named-book retrieval filter. Measured on `50b9347` (09.09, single run, the branch's
final commit with the scoring on keys and `expected_total`; the earlier 10/10 run of the same day
on `b0d1321` scored titles only and has a different golden checksum, so it is not the same
measurement): 10/10; the six catalogue items with 0 search steps and one model call each; the three
controls through the research loop (1, 2 and 3 steps); the hybrid item with retrieval limited to
Dracula; 22/22 quotes confirmed on the four research items; $0.17 for the set, of which the six
catalogue items cost $0.014 together (`eval-results/2026-09-09-catalogue-set.md`).
Re-measured on `466fc82` (10.09, this repository's `main` at the merge of `#18`, same golden checksum and the same
04.09 index): 10/10 again with the same routing question by question, 21/21 quotes confirmed on the
four research items — one evidence item fewer on the London question — and $0.1762 for the set, of
which the six catalogue items again cost $0.0136
([`eval-results/2026-09-10-catalogue-set.md`](eval-results/2026-09-10-catalogue-set.md)).

Two measured trees, both single runs, clean tree (`--require-clean`), strict hit-id mode, the same
bge-m3 index: **v0.1.0**, 2026-09-05 on code `88881ee` (the last code commit before tag `v0.1.0`;
the tag's commit adds documentation only), with a 1,200-character observe window, summarised in
`eval-results/2026-09-05-v0.1.0-*.md`; and **v0.2.0-rc1**, 2026-09-07 on tag `v0.2.0-rc1`
(`33dba3f`), with the 2,500-character window (ADR-012) and the coverage gate (ADR-013) together
plus everything in the 0.2.0-rc1 changelog. The rc1 reports
`eval-results/2026-09-07-v0.2.0-rc1-{core,extended,retrieval-canary}.md` are the harness
output verbatim under a provenance header (the two targeted second-candidate runs are appendices of
the core and extended reports); every agent row carries its stop reason and would say so if the
planner had fallen back or the deadline had cut the search (neither happened on either set). The
window and the gate were introduced and measured one at a time during development (the CHANGELOG
records those steps); the two columns below are the first measurement of both on one run: +39% per
core question and +57% per extended question against v0.1.0 (from the committed totals, $0.5364/11
against $0.4215/12 and $0.9008/21 against $0.5722/21).

A third run of the core set, 2026-09-09 on `50b9347` (the catalogue branch's final commit, this
repository), checks that the catalogue path (ADR-016) left the research loop's numbers where they
were: 11/11 behaviour, 48 / 0 / 0 quotes confirmed / unattributed / broken, $0.0519 mean per
question against $0.0488 on rc1 (73 model calls against 70). What changed is the path, not the
verdicts: the three questions that name one book (c04, c05, c06) now run with retrieval limited to
that book by the catalogue resolver, and the refusal question's answer carries the note that the
named book is not in the catalogue. Single run, not reader-graded; the report is
`eval-results/2026-09-09-catalogue-branch-core.md`. The table below keeps the two tagged
baselines.

A local-backend run of both sets, 2026-09-10 on `qwen2.5:7b` and `qwen2.5:14b` with a `qwen3.6`
probe, records what the loop does with no hosted key present — `$0.0000` on every run, nothing left
the machine; not reader-graded, and only the research subset was re-measured after the last prompt
change, which the report's own coverage caveat states:
[`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md).

## Where the measured code lives

The measurements were made in the private development repository before this repository was
created, and the reports name that repository's commits (`33dba3f`, `88881ee`, `1222b09`, ...):
those identify the measured trees in that history, they are not commits you can check out here,
and they are kept as recorded because rewriting them would suggest that a different code was
measured. What you can check instead: the first commit of this repository carries the eval harness
(`eval/*.py`) and `scripts/ingest_demo_corpus.py` byte-identical to the measured `33dba3f`, `src/`
and `ui.py` identical up to one comment line each (a review credit removed; the launch command in
the `ui.py` docstring completed with `--host 127.0.0.1`), and `eval/golden/en-demo.yaml` identical
except for one editorial note on c09 (a review credit removed after the run; the questions are
unchanged, and the core report's header records the resulting checksum change); the other
differences are documentation, the eval reports themselves and the version string. Reports of intermediate development runs are
not exported; the ones here are the tagged baselines the text refers to. The export from the
development repository is done by a private allowlist tool (a deny-by-default file list, a
private-marker grep and a gitleaks scan) that is not part of this repository.

| Measurement | Core v0.1.0 (12 questions, window 1,200) | Core v0.2.0-rc1 (11 questions, 2,500 + gate) | Extended v0.1.0 | Extended v0.2.0-rc1 |
|---|---|---|---|---|
| Retriever window, single-book presence | 9/9 | 8/8 | 12/12 | 12/12 |
| Retriever window, multi-book full coverage | 2/2 | 2/2 | 3/5 | 3/5 |
| Agent eval, questions completed | 12/12 | 11/11 | 21/21 | 21/21 |
| Behavioural compliance (heuristic scorer: titles, refusal, clarify, drill-down) | 12/12 | 11/11 | 17/21 | 18/21 |
| Answer quality, correct / incorrect / incomplete (AI pre-check of that run; the reader's own verdicts on the v0.2.0-rc1 run are in `eval-results/2026-09-07-v0.2.0-rc1-core.md` and confirm the pre-check: 10 correct, c06 incomplete; the v0.1.0 run was not graded by the reader) | 9 / 1 / 2 | 10 / 0 / 1 | not scored | not scored |
| Quote provenance, validator v0.1: confirmed / unattributed / broken | 46 / 0 / 0 | 47 / 0 / 0 | 53 / 0 / 0 | 73 / 0 / 0 |
| Clarify where the golden requires it | 1/1 | 1/1 | 0/2 | 1/2 |
| Chapter drill-down where expected | not in set | not in set | 0/1 | 0/1 |
| Cost per question, mean (Sonnet 4.6 via OpenRouter, configured rates) | $0.035 | $0.049 | $0.027 | $0.043 |

h12 was removed from the core set by the reader on 06.09 (never reader-verified; a character's lie
taken as fact was its failure); the v0.1.0 column is the 12-question run, the v0.2.0-rc1 column the
11-question core, which is also why the retriever row reads 8/8 there (h12's row is gone, nothing
else changed in retrieval: the index is the same).

On v0.1.0, behavioural compliance and provenance are green on all twelve core answers; a read of the
same answers against the golden notes finds one wrong (h12, then still in the set: a character's false
accusation reported as fact) and two incomplete: c03 names Madame Coquenard but not
Madame de Chevreuse, c06 never reaches Passepartout's
"to-day is Saturday" and says so (the committed trace). On v0.2.0-rc1 the AI pre-check of the eleven
answers finds ten correct and one incomplete, and the reader's read of 07.09 agrees row by row: c06 again, in a different shape: it reads Chapter
XXXIV, quotes Fix's apology from it, and supplies the date-line explanation from the book card's
plot summary instead of the discovery scene (Chapter XXXVII was not retrieved), without saying that
the scene itself is missing; Passepartout's "to-day is Saturday" and the Reform Club dash are
absent; c03 names both women this time and hedges Madame de Chevreuse as not
clearly established by the passages; c09, reworded on 05.09 to name both readings of the question,
offers Crusoe and Gulliver as candidates, answers Crusoe
with the harness's "not sure" reply and, with the second candidate chosen (`--clarify-pick second`,
committed as a one-question run), applies the choice and answers from Gulliver's Travels. The
extended failures are the known agent gaps under [Known limits](known-limits.md): on v0.1.0 four (q06 and h22 no
clarify, h17 Doyle side never retrieved, h13 no drill-down), on v0.2.0-rc1 three (h22 now clarifies
and offers Frankenstein and Dracula; q06, h17 and h13 unchanged).

Private cross-lingual library (Ukrainian questions over an English corpus, 10 questions, not in
this repo): single-book presence 6/7, multi-book coverage 1/3. The honest hard case - a
multilingual embedder handles single-target questions across languages, cross-lingual
aggregation does not hold up.

## Where the quality comes from

**`eval/run_ablation.py` - the same twelve core questions under five conditions** (ADR-014; the
architecture decision records are in [`adr/README.md`](adr/README.md)), one run
each on 2026-09-05, code `ab4e458` (`88881ee` plus the ablation harness - `eval/run_ablation.py`,
`tests/test_ablation.py` and their two entries in the private export allowlist - which
changes nothing the agent runs), clean tree, same index and same model as the table above. It
answers "how much of this is the agent loop and how much is the model, the corpus or plain
retrieval?". `no-context` is the orchestrator model with the question and nothing else;
`retrieve-answer` is one `search_both` call feeding one synthesize prompt, no loop; `cards-only`
and `transcripts-only` are the full loop with retrieval restricted to one corpus (a window of 4
hits per step instead of 8); `agent` is the shipped loop.

| condition | behaviour PASS | expected titles | provenance conf/unatt/broken | AI pre-check corr/incorr/incompl | mean cost/question |
|---|---|---|---|---|---|
| `no-context` (no library at all) | 6/12 | 9/13 | n/a | 9 / 1 / 2 | $0.0048 |
| `retrieve-answer` (retrieve once, answer once) | 9/12 | 12/13 | n/a | 7 / 2 / 3 | $0.0122 |
| `cards-only` (loop, cards corpus) | 12/12 | 13/13 | 29 / 0 / 0 of 29 | 8 / 0 / 4 | $0.0240 |
| `transcripts-only` (loop, transcripts corpus) | 11/12 | 12/13 | 33 / 0 / 1 of 34 | 9 / 1 / 2 | $0.0335 |
| `agent` (the shipped loop) | 12/12 | 13/13 | 40 / 0 / 0 of 40 | 9 / 1 / 2 | $0.0328 |

**On this run the full loop is not better than the loop-free conditions on answer content**: it
reads 9 correct / 1 incorrect / 2 incomplete, and so does the model with no library at all. Nine of
the twelve questions are about world-famous classics the model already knows, so on this corpus the
ablation cannot separate the loop from model memory on correctness. What the loop demonstrably buys
is in the other columns - behaviour PASS 6/12 to 12/12, quote provenance, and the clarify interrupt
- at 6.8x the cost of answering from memory. Provenance comes from the evidence-and-validation
contract, which this ablation did not separate from the loop: a single retrieval followed by the same
extraction and check would carry it too; the loop's own contribution is the extra steps and the clarify. Two results
cut the other way: the single-corpus `transcripts-only` condition beats the full agent on c03 (the
mechanism is not established by this run: each corpus keeps its own four hits, so cards do not
displace chapter text in retrieval; the difference is in what `observe` selected from eight hits
instead of four, or plain model variance), and on h12 - a former core item, removed by the reader
on 06.09, whose rows this artifact keeps as the record of the run - the three conditions whose
window carried a character's lie verbatim all repeated it as fact with clean provenance, while the
two that never saw it answered correctly. The `agent` condition reproduces the `v0.1.0` core run's
pre-check exactly - 9 / 1 / 2, the same three questions - which is a consistency check across two
independent runs, not a second measurement. Full table, per-question pre-check and limits:
[`eval-results/2026-09-05-ablation-core.md`](eval-results/2026-09-05-ablation-core.md).
The pre-check column is an AI reading of every answer against the golden notes by the session that
ran the ablation, not a human verdict.

## What the green numbers do NOT prove

- **Not correctness.** A 100% confirmed quote-provenance score means every quote really came
  from a hit of the book it is attributed to. If a character makes a false claim and the agent
  quotes it verbatim from the right chapter, provenance passes and the answer is still wrong; and
  a question whose answering passage was never retrieved scores the same green as one that was.
  Only a correctness read of the report catches either (the AI pre-check did, and on 07.09 the
  reader graded the eleven v0.2.0-rc1 answers in their report: ten correct, c06 incomplete).
- **Not answer quality.** Behavioural PASS means the expected titles were mentioned, a refusal
  refused, a clarify clarified. It does not grade reasoning or prose. c06 (Fogg's missing day)
  is PASS with provenance 2/2 and does not answer the second half of its question: the scene that
  answers it, Passepartout's "to-day is Saturday" in Chapter XXXVII, never entered the retrieval
  window, so the answer states honestly that the discovery moment is not in the evidence. That
  failure and a clean success are committed as full traces in
  [`examples/`](examples/README.md).
- **Not that the model read what it cites.** c06 in the 05.09 core run cited
  a Chapter XXXVII passage whose 1,200-character window ended one line before Passepartout's
  "to-day is Saturday" and inverted the day of the week; on the v0.1.0 run that chapter is not in
  the window at all and the answer stops short and says the discovery moment is not in the
  evidence; on the v0.2.0-rc1 run it is not in the window either and the answer fills the gap from
  the book card's plot summary without saying so. PASS and green provenance every time. Widening the observe window (measured during
  development, ADR-012) does not fix c06, because the passage is not in the window to widen. c05 (the windmills) once read an empty chapter because `reflect` passed the
  bare title while the index keys rows as "Title — Author"; fixed, and the tagged run quotes the Friston passage.
- **Not generalization.** The demo corpus is 33 classics with a golden set written against them.
  Numbers on your own library will differ.
