# Ablation on the core set (ADR-014)

- run: `code ab4e458 | golden en-demo.yaml@34de64f4a728 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model anthropic/claude-sonnet-4.6 | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31 | strict_hit_id=on | clarify_pick=default | single run`
- questions: 12 core golden questions (`en-demo.yaml`), one run per condition, 5 conditions
- code `ab4e458` is `88881ee` — the code the `v0.1.0` core run used — plus the two ablation commits, which touch `eval/run_ablation.py`, `tests/test_ablation.py` and the two lines those paths add to the private export allowlist — nothing the agent runs. The golden checksum `34de64f4a728` is the file as it stood at run time; the h12 `notes:` line was reworded afterwards in the `v0.1.0` release commit, so a later run of the same questions will report a different golden hash for the same twelve questions.
- full answers per condition: `eval/results/ablation-1788644387-no-context.md`, `eval/results/ablation-1788644387-retrieve-answer.md`, `eval/results/ablation-1788644387-cards-only.md`, `eval/results/ablation-1788644387-transcripts-only.md`, `eval/results/ablation-1788644387-agent.md` (not committed)

## What each condition is

- **`no-context`** — the orchestrator model answers from memory: the question only, same `llm_invoke` path, a system rule to answer from what it knows and say when it is unsure. No retrieval.
- **`retrieve-answer`** — one `search_both(question, k=4)` call; the 8 hits, sanitized and cut to `SEARCH_HIT_CHARS` (1,200) as observe would see them, go straight into one synthesize-style prompt. No plan/observe/reflect, no clarify, no validate.
- **`cards-only`** — the full agent loop, `search_both` restricted to the cards corpus (4 hits per step instead of 8).
- **`transcripts-only`** — the full agent loop, `search_both` restricted to the transcripts corpus (4 hits per step instead of 8).
- **`agent`** — the full loop as shipped — identical to `eval/run_agent_eval.py`.

Behaviour scoring, the per-question run and the fingerprint come from `eval/run_agent_eval.py`, imported unchanged. Cost, calls and tokens are the same per-question accounting that harness uses — the accumulator is reset at the start of every question and read back with `usage_fields()` — so the numbers here and there are the same measurement. The mean is per ATTEMPTED question: a question that errored still spent what it spent before failing.

## Comparison

| condition | behaviour PASS | expected titles | provenance conf/unatt/broken | AI pre-check corr/incorr/incompl | llm calls | total cost | mean cost/question | seconds |
|---|---|---|---|---|---|---|---|---|
| `no-context` | 6/12 | 9/13 | n/a | 9 / 1 / 2 | 12 | $0.0581 | $0.0048 | 93 |
| `retrieve-answer` | 9/12 | 12/13 | n/a | 7 / 2 / 3 | 12 | $0.1463 | $0.0122 | 97 |
| `cards-only` | 12/12 | 13/13 | 29 / 0 / 0 of 29 | 8 / 0 / 4 | 73 | $0.2878 | $0.0240 | 197 |
| `transcripts-only` | 11/12 | 12/13 | 33 / 0 / 1 of 34 | 9 / 1 / 2 | 75 | $0.4024 | $0.0335 | 247 |
| `agent` | 12/12 | 13/13 | 40 / 0 / 0 of 40 | 9 / 1 / 2 | 62 | $0.3932 | $0.0328 | 251 |

Total for the run: $1.2878, 234 LLM calls, 885 seconds.

Errors (question did not complete): `no-context` 0, `retrieve-answer` 0, `cards-only` 0, `transcripts-only` 0, `agent` 0.

Clarify caveat: `c09-shipwreck-first-person` in the golden set requires a clarify interrupt, which `no-context` and `retrieve-answer` cannot produce by construction — those conditions fail it whatever they answer. Behaviour PASS on the remaining questions only: `no-context` 6/11, `retrieve-answer` 9/11, `cards-only` 11/11, `transcripts-only` 10/11, `agent` 11/11.

`no-context` has no retrieval at all. `retrieve-answer` has no distilled quotes: its "evidence" is the raw retrieved passage, so running `validate` over it would compare each passage against itself and confirm 100% by construction. Provenance is therefore reported as n/a for both, not as a score.

## AI pre-check, per question

**This is an AI pre-check by the session that produced this artifact, not a human verdict.** Each cell is that session's reading of the answer in `eval/results/ablation-*.md` against the golden notes: `correct`, `incorrect` or `incomplete`. A reader's verdict, when it exists, overrides it: the last column is an unticked box per question, ticked by the reader who has checked that row.

| id | `no-context` | `retrieve-answer` | `cards-only` | `transcripts-only` | `agent` | reader's verdict |
|---|---|---|---|---|---|---|
| c01 | correct | correct | correct | correct | correct | [ ] |
| c02 | correct | correct | correct | correct | correct | [ ] |
| c03 | correct | incomplete | incomplete | correct | incomplete | [ ] |
| c04 | correct | correct | incomplete | correct | correct | [ ] |
| c05 | correct | incomplete | incomplete | correct | correct | [ ] |
| c06 | incomplete | incorrect | incomplete | incomplete | incomplete | [ ] |
| c07 | correct | correct | correct | incomplete | correct | [ ] |
| c08 | incorrect | correct | correct | correct | correct | [ ] |
| c09 | correct | correct | correct | correct | correct | [ ] |
| c10 | incomplete | correct | correct | correct | correct | [ ] |
| h06 | correct | incomplete | correct | correct | correct | [ ] |
| h12 | correct | incorrect | correct | incorrect | incorrect | [ ] |

The labels that are not self-evident from the table:

- **c03** (the women of Porthos and Aramis) — `transcripts-only` is the only retrieval condition that names both Madame Coquenard (quoted from Chapter XXIX) and Madame de Chevreuse (Chapter LXII). `no-context` names both from model memory. `cards-only`, `retrieve-answer` and the full `agent` all quote the Chapter XXIX passage and then say the name is not in the evidence.
- **c05** (the windmills) — `transcripts-only` and `agent` both reach Chapter VIII and quote the sage Friston explanation verbatim, in this edition's spelling. `no-context` gives the same explanation from memory with the other common spelling ("Freston"). `cards-only` and `retrieve-answer` say the post-fall explanation is not in the evidence; `cards-only` then names Friston anyway with an explicit "I cannot confirm that from the evidence".
- **c06** (Fogg's missing day) — incomplete everywhere: no condition reaches Passepartout's "to-day is Saturday". `retrieve-answer` is the one that goes further and is wrong: it reports Passepartout believing the next day was Sunday and Fogg answering "Monday", inverting the day of the week — the same failure recorded for the 05.09 11:45 core run.
- **c08** (the refusal question) — `no-context` narrates the whitewashing scene from model memory, which is exactly what a library-grounded answer must not do; every retrieval condition refuses. `retrieve-answer` refuses honestly ("the evidence provided does not contain … I cannot accurately describe") but is scored FAIL because that wording matches none of the scorer's refusal markers: a limit of the heuristic, not a behaviour failure.
- **c10** (the two chivalry books) — `no-context` cannot see the shelves at all and says so, then guesses Malory and Cervantes; the four retrieval conditions all name Ivanhoe and Don Quixote correctly.
- **h12** (Mr Brown) — `retrieve-answer`, `transcripts-only` and `agent` all repeat Sir James's own false accusation (that Julius Hersheimmer was murdered and impersonated) as fact; `transcripts-only` goes further and answers "Julius Hersheimmer" as Mr Brown. `cards-only` and `no-context` name Sir James Peel Edgerton and stop there. The three failing conditions are precisely the ones whose retrieval window contained the Chapter XXVI lie verbatim.

## Reading

**On this run the agent loop is not better than the loop-free conditions on answer content.** The
full `agent` reads 9 correct / 1 incorrect / 2 incomplete; `no-context` — the same model with no
library at all — also reads 9 / 1 / 2, and `transcripts-only` reads 9 / 1 / 2 as well. Nine of the
twelve questions are about world-famous public-domain classics, which is exactly the material a
hosted model already knows; on this corpus the model's own memory is a strong baseline and the
ablation cannot separate the loop from it on correctness alone.

What the loop does buy is visible in the other columns. Behaviour PASS goes from 6/12 without a
library to 12/12 with the full loop, and the single question where the difference matters most is
c08: `no-context` cheerfully narrates the fence-whitewashing scene from a book that is not in the
library, while every retrieval condition refuses. Provenance was measured only in the three loop
conditions — 40/40 quotes confirmed for `agent`, one broken quote in 34 for `transcripts-only`
(a Rebecca line in c10 attributed to Ivanhoe Chapter XXIX that is in no retrieved passage) — but it
is produced by the extraction-and-validation contract, which this ablation did not separate from
the loop: a single retrieval followed by the same extraction and check would carry it too. What the
loop itself adds is the extra steps and the `c09` clarify, reachable only inside it. Grounding is
what makes an answer checkable and refusable, not what makes it right.

Two results cut against "more retrieval is better". On c03 the single-corpus `transcripts-only`
condition beats the full agent, which had both corpora and twice the window: it names Madame
Coquenard and Madame de Chevreuse from Chapters XXIX and LXII, while the agent — three steps, two
rewritten queries, both corpora — quotes the same Chapter XXIX passage and concludes the name is
not in the evidence. The mechanism is not established by this run: `search_both` keeps four hits
per corpus, so card summaries do not displace chapter text in retrieval; the difference lies in what
`observe` selected from eight hits instead of four, in the later trajectory, or in model variance.
And h12 is the sharpest result in the table: the three conditions
whose retrieval window carried Sir
James's own lie verbatim (`retrieve-answer`, `transcripts-only`, `agent`) all repeat it as fact
with clean provenance, while the two that did not see it (`cards-only`, `no-context`) answer
correctly. Retrieval moved that answer from right to wrong, and provenance 40/40 said nothing
about it.

One cross-check: the `agent` condition here and the separate `v0.1.0` core run
(`docs/eval-results/2026-09-05-v0.1.0-core.md`) reach the same pre-check — 9 / 1 / 2, with h12
wrong and c03 and c06 incomplete in both. Two runs agreeing is a consistency check on the reading,
not a second measurement of the system.

Cost is the one unambiguous ordering: $0.0048 per question with no library, $0.0122 for
retrieve-then-answer, $0.0328 for the full loop — 6.8x the no-context baseline and 2.7x the
single-shot retrieval, for behaviour, provenance and clarify rather than for correctness.

## Limits of this table

- One run per condition per question, hosted model, temperature 0 but output still varies between runs; a difference of one or two questions is not a measured effect.
- Behaviour PASS is the heuristic scorer (titles mentioned, refusal marker, clarify, drill-down), not correctness. The AI pre-check column is a reading, not a judge.
- `cards-only` and `transcripts-only` are leave-one-corpus-out, not a like-for-like swap: `k` stays 4, so those conditions see a window of 4 hits per step where the full agent sees 8. Part of any gap between them and `agent` is half the window, not the corpus.
- `cards-only` and `transcripts-only` restrict `search_both` only. A chapter drill-down (`get_chapter`) still reads the transcripts table, so a `cards-only` run that drills into a chapter is not corpus-pure; the per-condition report lists the chapter reads. On this run all five `cards-only` chapter reads came back `empty` — the section names the loop had seen were card sections ("Plot", "Key Poems") or a card's chapter label that is not the transcript's chapter key — so no transcript text reached a `cards-only` answer.
- `no-context` and `retrieve-answer` cannot produce a clarify interrupt, so `c09` is a structural FAIL for them however good the answer is; the row above reports behaviour PASS without it as well.
- Provenance is n/a, not zero, for `no-context` and `retrieve-answer` — see the note above the per-question table: `retrieve-answer` has no distilled quotes, so `validate` would check each passage against itself.
- Cost is the orchestrator's own token cost at the configured prices; embeddings run locally and are not priced here.
- The run shared an OpenRouter key and a LanceDB index with a concurrent release eval; no request failed (0 errors in every condition), but wall-clock seconds are not a latency measurement.
- **The per-condition scratchpads of this run were overwritten.** The harness writes its scratchpad to `eval/results/scratch-<id>.md`, and on this run all five conditions ran one after another over the same directory, so only the last condition's (`agent`) scratchpads survived; the four earlier conditions left their answers, steps and totals in `eval/results/ablation-1788644387-<condition>.md` but no scratchpad. Statements above about what a condition's retrieval window contained (h12, c03, c05) rest on those answer files, their step logs and the quotes the answers themselves cite, not on a scratchpad. The runner now points the harness at `eval/results/<condition>/` per condition, so a future run keeps all five; this run cannot be repeated to recover them.

