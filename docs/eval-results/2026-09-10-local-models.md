> **Provenance of this artifact.** Five runs on 2026-09-10 against the local backend only
> (`LLM_BACKEND=ollama`, `EMBED_BACKEND=ollama`), plus one two-question probe of the thinking model,
> plus **Run 7**, added in review round 1 at the default time budgets and stamped separately — it is
> the one run made from a clean tree (`--require-clean`, code `37f71e2`) and its own section carries
> its settings and its fingerprints, which differ from the six below in the deadline and in the
> corpus manifest. Runs 1-6 carry the stamp that follows.
> Code `5b19f2d+dirty(4e721d730cb1)`: `5b19f2d` was `origin/main` when the runs were made, and the
> dirty checksum covers this branch's whole code change and nothing else — this report file did not
> exist yet, and the harness hashes `git diff HEAD` together with the un-ignored untracked files, so
> no report can be written and then measured at the same stamp. **The branch was afterwards rebased
> onto `4cab2be`** (`#17`, which re-pinned six Gutenberg files whose upstream copies had been
> regenerated), so that checksum is a record of what ran rather than something a `git diff` from the
> rebased head reproduces. The re-pin does not reach these numbers: of the six files, three change no
> ingested text at all, and the other three change a handful of characters (*Pride and Prejudice* two
> typo fixes, *Moby Dick* two quote marks and `soil` → `soul`, *Memoirs of Napoleon Bonaparte* a
> dropped transcriber credit) — none of those strings appears anywhere in the output below, and all 33
> titles are unchanged, which is what the catalogue set scores. The index used here was built from the
> corpus as `5b19f2d` pinned it and the fingerprints name that manifest, so a re-run at the rebased
> head over a rebuilt index would be a different measurement; it has not been made.
> Golden files: `en-demo-catalog.yaml@14b001e26f5e` and
> `en-demo.yaml@f041a0290000`, **both unchanged by this branch** and both identical to the checksums
> the mini-eval this compares against reported. Corpus `manifest@f093bb27dab1`, `toc@ef7a347ace1d`.
> Index: the demo LanceDB built 2026-09-10, `cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39`,
> `transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30`, reused as built and not
> rebuilt for these runs. Model tags `qwen2.5:7b` (4.7 GB), `qwen2.5:14b` (9.0 GB), `qwen3.6` (23 GB),
> all already pulled; Ollama 0.33.3. Settings per run: `strict_hit_id=on`, `hit_chars=2500/12000`,
> `steps=4/2`, `candidates=5`, `LLM_TIMEOUT_S=600`, `LLM_MAX_RETRIES=2`, `deadline=1200s` — the same
> pair the mini-eval used, so the loop is bounded the same way. **`$0.0000` on every run**, reported by
> the harness itself: no hosted key was present and nothing left the machine.
>
> **Coverage caveat.** Two sets only: the whole catalogue set (10 items) and the ten `c*` items of
> `en-demo.yaml` (`h06` is Ukrainian and out of scope; the harness takes ids positionally, so the
> subset ran exactly). Behaviour is the harness's automatic score; the manual-correctness checkboxes
> in the pasted output are **unticked** — no human has read these answers against the golden notes.
> The hosted default model was not re-measured here at all, so nothing in this report says what the
> prompt change does to `anthropic/claude-sonnet-4.6`. The "before" column is the mini-eval of the same
> two sets on `b797d33` (tag `v0.2.0`); between `b797d33` and `5b19f2d` the only files in the agent's
> path that changed are `src/ask_your_library/sanitize.py` and `eval/injection_canary.py`
> (`git diff --stat b797d33 5b19f2d -- src eval` → 2 files, 23 insertions, 3 deletions), and the
> `sanitize.py` change rewrites one character class span by span without altering the set it matches,
> so the two measurements are comparable.

# Local models on the fixed path — 2026-09-10

Four defects found by the local mini-eval of 2026-09-10 were fixed on `fix/local-model-path`, and the
same two sets were re-run for both `qwen2.5` candidates, plus the research subset a second time for
`qwen2.5:7b` to see run-to-run variance. Review round 1 added a third `qwen2.5:7b` research run at the
default time budgets (Run 7), because runs 1-6 used a 1,200 s deadline under which the new per-call cap
never binds.

- the synthesize rules now carry one filled citation example and forbid the literal placeholder
- `provenance._normalize` treats `_` as punctuation, so Gutenberg italics no longer break a correct quote
- the eval's `REFUSAL_MARKERS` cover the "the evidence does not contain / cover / include it" family
- `LLM_BACKEND=ollama` sends `reasoning_effort: "none"`, and no search-loop call outlives the question
  deadline — while the final synthesize, and anything issued after the deadline, keep the full timeout

## Before and after

Behaviour is the harness's automatic PASS count. Quotes are its `confirmed / unattributed / broken`.
"Placeholder answers" counts answers whose text contains the literal token `[book,` — the word *book*
left standing inside a citation bracket. That is slightly wider than the mini-eval's headline count of
11, which counted only the bare string `[book, chapter]`; by the narrower rule the before column reads
3 + 8 = 11 for 7b and 0 for 14b, and every after cell is 0 under both rules. Mean seconds is wall time
over the ten questions of the set, the mini-eval's own definition.

| Model | Set | Behaviour | Quotes conf / unattr / broken | Placeholder answers | Wall | Mean s/question |
|---|---|---|---|---|---|---|
| `qwen2.5:7b` before | catalogue | 10/10 | 8 / 0 / 0 | 3/10 | 180 s | 18.0 |
| `qwen2.5:7b` **after** | catalogue | 10/10 | 8 / 0 / 0 | **0/10** | 178 s | 17.8 |
| `qwen2.5:7b` before | research | 6/10 | 27 / 2 / **2** | 9/10 | 685 s | 68.5 |
| `qwen2.5:7b` **after** | research | **9/10** | 28 / 2 / **1** | **0/10** | 673 s | 67.3 |
| `qwen2.5:7b` **after** | research, 2nd run | **9/10** | 28 / 2 / **1** | **0/10** | 300 s | 30.0 |
| `qwen2.5:7b` **after** | research, default budgets (Run 7) | **9/10** | 28 / 2 / **1** | **0/10** | 708 s | 70.8 |
| `qwen2.5:7b` before | **combined** | 16/20 | 35 / 2 / 2 | 12/20 | 865 s | 43.3 |
| `qwen2.5:7b` **after** | **combined** | **19/20** | **36 / 2 / 1** | **0/20** | 851 s | 42.6 |
| `qwen2.5:14b` before | catalogue | 10/10 | 17 / 0 / 0 | 1/10 | 396 s | 39.6 |
| `qwen2.5:14b` **after** | catalogue | 10/10 | 17 / 0 / 0 | **0/10** | 404 s | 40.4 |
| `qwen2.5:14b` before | research | 5/10 | 41 / 1 / 2 | 2/10 | 1366 s | 136.6 |
| `qwen2.5:14b` **after** | research | **8/10** | 41 / 1 / 2 | **0/10** | 1331 s | 133.1 |
| `qwen2.5:14b` before | **combined** | 15/20 | 58 / 1 / 2 | 3/20 | 1762 s | 88.1 |
| `qwen2.5:14b` **after** | **combined** | **18/20** | **58 / 1 / 2** | **0/20** | 1735 s | 86.8 |
| `qwen3.6` before | any | never finished a question | — | — | — | — |
| `qwen3.6` **after** | c02 + c08 probe | **2/2** | 3 / 0 / 0 | **0/2** | 73 s | 36.5 |

Quote confirmation rate: 7b **36/39 = 92.3 %** (was 89.7 %), 14b **58/61 = 95.1 %** (unchanged — 14b's
quoting was never the problem). 14b still grounds more heavily: 61 quotes checked against 39.

### Per question, research set

| id | type | 7b before | 7b after | 7b 2nd run | 14b before | 14b after |
|---|---|---|---|---|---|---|
| c01-ivanhoe-disguised-knight | identify | PASS 34 s | PASS 34 s | PASS 20 s | PASS 121 s | PASS 114 s |
| c02-huck-go-to-hell | answer | PASS 49 s | PASS 49 s | PASS 23 s | PASS 104 s | PASS 100 s |
| c03-musketeers-women | answer | **FAIL** 95 s | **PASS** 95 s | PASS 35 s | PASS 193 s | PASS 183 s |
| c04-crusoe-cannibals | answer | **FAIL** 86 s | **PASS** 86 s | PASS 31 s | **FAIL** 101 s | **PASS** 94 s |
| c05-quixote-windmills | answer | PASS 55 s | PASS 50 s | PASS 25 s | PASS 130 s | PASS 121 s |
| c06-fogg-missing-day | answer | PASS 72 s | PASS 69 s | PASS 36 s | **FAIL** 99 s | **PASS** 102 s |
| c07-alice-trial | answer | PASS 45 s | PASS 44 s | PASS 20 s | PASS 84 s | PASS 83 s |
| c08-refusal-tom-sawyer | refusal | **FAIL** 67 s | **PASS** 66 s | PASS 23 s | **FAIL** 175 s | **PASS** 173 s |
| c09-shipwreck-first-person | identify | PASS 87 s | PASS 87 s | PASS 45 s | **FAIL** 140 s | FAIL 140 s |
| c10-chivalry-two-books | aggregation | FAIL 93 s | FAIL 91 s | FAIL 39 s | FAIL 216 s | FAIL 217 s |

## Reading

**The placeholder is gone, and gone for both models.** `qwen2.5:7b` printed the unfilled citation in
12 of 20 answers before and in 0 of 20 after, across two independent runs of the research set;
`qwen2.5:14b`, which had three half-filled ones (`[book, Themes]`), has none either. Both models now
write the filled form the rules show them — `[Adventures of Huckleberry Finn — Mark Twain, CHAPTER XXXI.]`
in 7b's `c02`, `[Don Quixote — Miguel de Cervantes, CHAPTER VIII.]` where the evidence is Don Quixote.
7b can therefore produce a demo frame that meets the brief, which it could not before.

**Three of the seven behaviour points came from the two harness defects, not from the models.** `c08`
flipped for both models because a correct refusal in the phrasing they actually use is now scored as
one; nothing about how either model declines has changed, and neither narrated the fence scene from
memory before or after. 7b's `c02` gained a confirmed quote instead of a broken one because the italics
markup around `_go_` no longer breaks the word-sequence match — the outcome the golden file's own note
on `c02` says the design intends. The rest is the prompt: `c03` and `c04` for 7b, `c04` and `c06` for
14b, all answer-type items whose score depends on the answer naming its book, which a filled citation
does and a bare `[book, chapter]` does not.

**How a refusal is scored, and why the marker alone is not enough.** The widened marker family also
covers hedges a model emits constantly ("the evidence does not include the exact wording, but ..."), so
a marker on its own would let "The library does not contain this, but in the novel the captain ..."
score PASS while telling the story from model memory — the exact failure `c08` exists to catch. The
rule is therefore two-part: an explicit marker, **and the answer ending there** — at most 40 words
after the first marker (`REFUSAL_TAIL_WORDS` in `eval/run_agent_eval.py`). The budget is read off the
answers in this report: 37 words after `does not contain` in 7b's `c08`, 36 after `does not cover` in
14b's, 11 after `no evidence` in the `qwen3.6` probe — in each case a marker sentence that restates the
question plus one more sentence about the evidence, and no room for a retold episode. The provenance
count is deliberately not part of the rule: an honest refusal cites the card that says the thing is not
in this edition, and `c08` confirmed 3 quotes on 7b and 4 on 14b while declining. The rule's remaining
limit, stated: a model that declines and then narrates in a dozen words still passes, which is what the
manual-correctness checkbox is for. The tail rule landed **after** the runs below were made — the
answers are unchanged and were re-scored against it, and every `c08` output in this file still PASSes.

**One broken quote left for 7b, two for 14b, and both models still fabricate.** The count moved from 2
to 1 for 7b and stayed at 2 for 14b. `c10` (aggregation) fails for both, before and after, and `c09`
still fails for 14b. Neither model is good enough to advertise as a strong default: 19/20 and 18/20
with genuine unattributed and broken quotes in both. The README's existing warning that small local
models are less reliable stays accurate and should not be softened.

**Latency is not a like-for-like number; behaviour is.** At `temperature=0` the two 7b research runs
produced identical scores, identical provenance verdicts and identical per-question token counts (the
`diff` below is 26 lines, all of them seconds, two rephrased sentences in `c09` and 13 output tokens on
`c06`), so the behaviour deltas above are not sampling noise. Wall time is another matter: the same set
took 673 s and then 300 s, purely on whether the model was already resident. The first run of each set
is the honest cold-ish number, and those are the ones in the table.

**`qwen3.6` finishes now.** Before this branch it never completed a question: its reasoning tokens are
not counted against `MAX_OUTPUT_TOKENS`, so one node ran past `LLM_TIMEOUT_S`, retried twice, and the
question deadline is consulted only between calls. Of the four forms tried against Ollama 0.33.3's
OpenAI-compatible endpoint, only `reasoning_effort: "none"` is honoured — `think: false`,
`chat_template_kwargs: {enable_thinking: false}` and an `options: {think: false}` block are all
accepted with HTTP 200 and ignored (one warm short prompt each: 14.2 s, 1865 reasoning characters and
no answer for the baseline and for each of the three ignored forms; 1.0 s, 0 reasoning characters and a
complete answer for `reasoning_effort`). With it, the two-question probe below completes both in 73 s
with all three quotes confirmed. That is a probe, not an eval: `qwen3.6` has not been run over either
full set, and no claim is made here about its scores.

## Commands

```bash
# the demo index was reused as built, never rebuilt
LLM_BACKEND=ollama OLLAMA_LLM_MODEL=<tag> EMBED_BACKEND=ollama OLLAMA_EMBED_MODEL=bge-m3 \
  LIBRARY_DB_PATH=<demo index> LLM_TIMEOUT_S=600 LLM_MAX_RETRIES=2 QUESTION_DEADLINE_S=1200 \
  GOLDEN_PATH=eval/golden/en-demo-catalog.yaml EVAL_RESULTS_DIR=<scratch>/<tag>-catalog \
  uv run python eval/run_agent_eval.py

LLM_BACKEND=ollama OLLAMA_LLM_MODEL=<tag> EMBED_BACKEND=ollama OLLAMA_EMBED_MODEL=bge-m3 \
  LIBRARY_DB_PATH=<demo index> LLM_TIMEOUT_S=600 LLM_MAX_RETRIES=2 QUESTION_DEADLINE_S=1200 \
  GOLDEN_PATH=eval/golden/en-demo.yaml EVAL_RESULTS_DIR=<scratch>/<tag>-research \
  uv run python eval/run_agent_eval.py \
    c01-ivanhoe-disguised-knight c02-huck-go-to-hell c03-musketeers-women \
    c04-crusoe-cannibals c05-quixote-windmills c06-fogg-missing-day \
    c07-alice-trial c08-refusal-tom-sawyer c09-shipwreck-first-person \
    c10-chivalry-two-books

# Run 7 (review round 1): the same research subset with the two time variables UNSET, so the
# config defaults decide — LLM_TIMEOUT_S=600 (the ollama default) against QUESTION_DEADLINE_S=300
LLM_BACKEND=ollama OLLAMA_LLM_MODEL=qwen2.5:7b EMBED_BACKEND=ollama OLLAMA_EMBED_MODEL=bge-m3 \
  LIBRARY_DB_PATH=<demo index> \
  GOLDEN_PATH=eval/golden/en-demo.yaml EVAL_RESULTS_DIR=<scratch>/7b-defaults \
  uv run python eval/run_agent_eval.py --require-clean \
    c01-ivanhoe-disguised-knight c02-huck-go-to-hell c03-musketeers-women \
    c04-crusoe-cannibals c05-quixote-windmills c06-fogg-missing-day \
    c07-alice-trial c08-refusal-tom-sawyer c09-shipwreck-first-person \
    c10-chivalry-two-books
```

The harness output of all seven runs follows, copied verbatim from the report files it wrote; nothing
was recomputed. Two are given as headlines, totals and a complete `diff` against the run they are
otherwise identical to, line for line: the second 7b research run against the first, and Run 7 against
the second.

---

## Run 1 — `qwen2.5:7b`, catalogue set (wall 178 s)

# Agent eval — 2026-09-10 04:25 — en-demo-catalog.yaml

run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo-catalog.yaml@14b001e26f5e | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen2.5:7b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run

## k01-count (catalog, 0 steps, 7s, $0.0000, 1 calls, 576 in / 29 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** How many books do I have in my library?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k02-list (catalog, 0 steps, 1s, $0.0000, 1 calls, 578 in / 29 out tokens) — PASS: titles 33/33, catalog list: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** What are the names of all the books in my library?


33 books in your library (by the index tables):
- A Journey to the Interior of the Earth — Jules Verne
- A Study in Scarlet — Arthur Conan Doyle
- Adventures of Huckleberry Finn — Mark Twain
- Alice's Adventures in Wonderland — Lewis Carroll
- Around the World in Eighty Days — Jules Verne
- Celebrated Crimes — Alexandre Dumas
- Don Quixote — Miguel de Cervantes
- Dracula — Bram Stoker
- Frankenstein — Mary Shelley
- Gulliver's Travels — Jonathan Swift
- Ivanhoe — Walter Scott
- Jane Eyre — Charlotte Brontë
- Meditations — Marcus Aurelius
- Memoirs of Napoleon Bonaparte — Louis Antoine Fauvelet de Bourrienne
- Moby Dick — Herman Melville
- Pride and Prejudice — Jane Austen
- Robinson Crusoe — Daniel Defoe
- Romeo and Juliet — William Shakespeare
- Seneca's Morals — Lucius Annaeus Seneca
- The Adventures of Sherlock Holmes — Arthur Conan Doyle
- The Call of the Wild — Jack London
- The Extraordinary Adventures of Arsène Lupin — Maurice Leblanc
- The Hound of the Baskervilles — Arthur Conan Doyle
- The Kobzar of the Ukraine — Taras Shevchenko
- The Odyssey — Homer
- The Picture of Dorian Gray — Oscar Wilde
- The Secret Adversary — Agatha Christie
- The Three Musketeers — Alexandre Dumas
- The Time Machine — H. G. Wells
- The War of the Worlds — H. G. Wells
- Treasure Island — Robert Louis Stevenson
- Twenty Thousand Leagues Under the Sea — Jules Verne
- Wuthering Heights — Emily Brontë

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k03-has-yes (catalog, 0 steps, 2s, $0.0000, 1 calls, 572 in / 47 out tokens) — PASS: titles 1/1, catalog has: 1 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Ivanhoe?


Yes, in your library:
- Ivanhoe — Walter Scott

> quote provenance: catalog: 1 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k04-has-no (catalog, 0 steps, 1s, $0.0000, 1 calls, 574 in / 38 out tokens) — PASS: titles 0/0, catalog has: 0 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Is War and Peace in my library?


No book titled "War and Peace" is in your library. Closest titles: Pride and Prejudice.

> quote provenance: catalog: 0 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k05-by-author (catalog, 0 steps, 2s, $0.0000, 1 calls, 576 in / 40 out tokens) — PASS: titles 3/3, catalog by_author: 3 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have by Jules Verne?


3 book(s) by Jules Verne in your library:
- A Journey to the Interior of the Earth — Jules Verne
- Around the World in Eighty Days — Jules Verne
- Twenty Thousand Leagues Under the Sea — Jules Verne

> quote provenance: catalog: 3 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k06-count-ua (catalog, 0 steps, 1s, $0.0000, 1 calls, 586 in / 29 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Скільки книжок у моїй бібліотеці?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k07-content-not-catalog (answer, 1 steps, 25s, $0.0000, 4 calls, 5439 in / 183 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What are the names of the three musketeers?

- reflect -> stop: enough evidence

The names of the three musketeers are Athos, Porthos, and Aramis. [The Three Musketeers — Alexandre Dumas — Summary]

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

## k08-about-whaling (answer, 4 steps, 75s, $0.0000, 10 calls, 17778 in / 577 out tokens) — PASS: titles 1/1, stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have about whaling?

- reflect -> whaling in Moby Dick
- reflect -> whaling in Moby Dick
- reflect -> whaling in Moby Dick
- reflect -> stop: step limit (4) — wanted to keep searching

The evidence provided does not contain specific information about whaling practices or the industry. It focuses on Captain Ahab's pursuit of the white whale, Moby Dick. [Moby Dick — Herman Melville, Plot]

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

## k09-mention-london (answer, 1 steps, 18s, $0.0000, 4 calls, 4395 in / 179 out tokens) — PASS: titles 0/0, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which of my books mention London?

- reflect -> stop: enough evidence

The War of the Worlds — H. G. Wells — Plot: mentions London as the setting where the Martians' advance and the Black Smoke occur. [The War of the Worlds — H. G. Wells, Plot.]

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

## k10-hybrid-named-book (answer, 2 steps, 45s, $0.0000, 6 calls, 9125 in / 498 out tokens) — PASS: titles 1/1, named book -> retrieval filter Dracula — Bram Stoker (expected), stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Dracula, and why does Jonathan Harker stay at the castle?

- reflect -> __chapter__|Dracula — Bram Stoker|CHAPTER XXIV
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

According to the evidence provided, Dracula does not explicitly state that Jonathan Harker has Dracula, but it is implied that Harker is staying at the castle to take care of his wife, Madam Mina, as mentioned in [Dracula — Bram Stoker, CHAPTER XXIV]. The reason for Harker staying at the castle is to look after Madam Mina while Dracula and others go to search for something, likely related to confirming something about her. [Dracula — Bram Stoker, CHAPTER XXIV] also mentions that Harker will board a ship to find out more information and return to provide comfort. However, the specific reason for his stay at the castle is primarily to ensure Madam Mina's safety and well-being.

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

---
10 completed, 0 errors, 0 clarify interrupts; quotes verified 8/8 (confirmed / unattributed / broken = 8 / 0 / 0); evidence items 8
behavior PASS 10/10 (answer 4/4, catalog 6/6); expected titles mentioned 106/106
cost $0.0000 total, $0.0000 mean per attempted question (30 LLM calls, 40199 in / 1649 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

---

## Run 2 — `qwen2.5:7b`, research subset (wall 673 s)

# Agent eval — 2026-09-10 04:28 — en-demo.yaml

run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo.yaml@f041a0290000 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen2.5:7b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run

## c01-ivanhoe-disguised-knight (identify, 2 steps, 34s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** What was that novel where a knight returns to England in disguise, his father has rejected him, and there is all this conflict between Saxons and Normans while King Richard is returning?

- reflect -> __chapter__|Ivanhoe — Walter Scott|Plot
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

(No book titled "The Once and Future King" is in the library catalogue; the whole library was searched instead.)

The novel you are referring to is "Ivanhoe" by Walter Scott. In the plot, Wilfred of Ivanhoe, a Saxon knight, is disinherited by his father Cedric for supporting the Norman King Richard and loving the Saxon ward Rowena. Wilfred returns secretly from the Crusades disguised as a pilgrim, leading to conflicts between Saxons and Normans. [Ivanhoe — Walter Scott, Plot.]

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

## c02-huck-go-to-hell (answer, 2 steps, 49s, $0.0000, 6 calls, 9737 in / 577 out tokens) — PASS: titles 1/1, named book -> retrieval filter Adventures of Huckleberry Finn — Mark Twain, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Huck say, "All right, then, I'll go to hell"? What has he decided to do?

- reflect -> __chapter__|Adventures of Huckleberry Finn — Mark Twain|CHAPTER XXXI.
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

Huck decides to follow his conscience and help Jim, despite the risk of going to hell according to societal norms. This decision is made after Huck reflects on Jim's kindness towards him and his gratitude, leading Huck to conclude that he would rather face eternal punishment than continue to participate in the injustice of slavery. [Adventures of Huckleberry Finn — Mark Twain, CHAPTER XXXI.]

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

## c03-musketeers-women (answer, 4 steps, 95s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** I remember that Constance Bonacieux was d'Artagnan's love and that Milady had been Athos's wife. But who were the women connected with Porthos and Aramis?

- reflect -> Porthos's love interests in The Three Musketeers
- reflect -> women connected with Porthos in The Three Musketeers
- reflect -> women connected with Porthos in The Three Musketeers
- reflect -> stop: step limit (4) — wanted to keep searching

Based on the evidence provided, Porthos and Aramis are associated with a "lady of the red cushion" in Chapter XXIX. However, the specific identity of this lady is not mentioned. For Aramis, there is a reference to his amorous adventures with a princess, but no specific woman is named. [The Three Musketeers — Alexandre Dumas, Chapter VII.] mentions Aramis's connection to a princess but does not provide the name. [The Three Musketeers — Alexandre Dumas, Chapter XXIX.] describes interactions between Porthos and a woman, but her identity remains unknown.

> quote provenance: WARNING: 1 of 4 quotes NOT found verbatim in any retrieved passage (possible hallucination):
  - The Three Musketeers — Alexandre Dumas: "Aramis, though having the air of having nothing secret about him, was a young fe..."

## c04-crusoe-cannibals (answer, 4 steps, 86s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** What did Crusoe do when he first discovered that cannibals were visiting the island? Did he attack them immediately?

- reflect -> Robinson Crusoe first encounter with cannibals
- reflect -> Robinson Crusoe's first encounter with cannibals
- reflect -> Robinson Crusoe's first encounter with cannibals
- reflect -> stop: step limit (4) — wanted to keep searching

The evidence provided does not contain information about Crusoe's actions when he first discovered that cannibals were visiting the island or whether he attacked them immediately. [Robinson Crusoe — Daniel Defoe, CHAPTER V.] focuses on Crusoe's initial arrival and his gratitude, but does not mention the incident with the cannibals.

> quote provenance: PARTIAL: 2 of 4 quotes confirmed in the passages they cite (2 quotes found in a retrieved passage other than the one cited — not counted as confirmed)

## c05-quixote-windmills (answer, 2 steps, 50s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Don Quixote attack the windmills even after Sancho tells him what they are, and how does he explain what happened after they knock him down?

- reflect -> __chapter__|Don Quixote — Miguel de Cervantes|CHAPTER VIII.
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

Don Quixote attacks the windmills even after Sancho tells him what they are because he is so convinced that they are giants that he neither hears Sancho's warnings nor perceives the true nature of the windmills. [Don Quixote — Miguel de Cervantes, CHAPTER VIII.] After being knocked down by the windmills, Don Quixote explains that those are giants and that he is engaging them in combat, despite the fact that Sancho had previously informed him of their true nature. [Don Quixote — Miguel de Cervantes, CHAPTER VIII.]

> quote provenance: OK: all 3 quotes found verbatim in the passages they cite

## c06-fogg-missing-day (answer, 3 steps, 69s, $0.0000, 8 calls, 12196 in / 915 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why did Phileas Fogg think he had lost the wager after reaching London, and how did he discover that he had actually won?

- reflect -> how Phileas Fogg realized he had won the wager at the end of Around the World in
- reflect -> __chapter__|Around the World in Eighty Days — Jules Verne|CHAPTER XXXVII.
- reflect -> stop: enough evidence

Phileas Fogg thought he had lost the wager after reaching London because he arrived just as the clock at the Reform Club struck nine o'clock, which was the deadline for the wager. He did not realize that by traveling eastward, he had gained a full day across the International Date Line, arriving with time to spare. This twist in the plot allowed him to win the wager of twenty thousand pounds [Around the World in Eighty Days — Jules Verne, CHAPTER XXXVII.].

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c07-alice-trial (answer, 2 steps, 44s, $0.0000, 6 calls, 8767 in / 511 out tokens) — PASS: titles 1/1, named book -> retrieval filter Alice's Adventures in Wonderland — Lewis Carroll, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Alice stop being afraid during the trial and finally challenge the Queen and the whole court?

- reflect -> __chapter__|Alice's Adventures in Wonderland — Lewis Carroll|Chapter 12
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

Alice stops being afraid during the trial and finally challenges the Queen and the whole court because she has grown to her full size, which gives her the confidence to stand up to the authority figures. This is evident from her interactions with the jury and the Queen in Chapter 12 of "Alice's Adventures in Wonderland" — Lewis Carroll, where she asserts herself by shouting "Stuff and nonsense" and directly addressing the Queen, saying "Off with her head." [Alice's Adventures in Wonderland — Lewis Carroll, Chapter 12.]

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

## c08-refusal-tom-sawyer (refusal, 3 steps, 66s, $0.0000, 8 calls, 15000 in / 545 out tokens) — PASS: titles 0/0, named book not in the catalogue: The Adventures of Tom Sawyer, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** How did Tom Sawyer make the other boys pay him for the chance to paint the fence?

- reflect -> how did tom sawyer make his friends pay him to paint the fence in the adventures
- reflect -> how did tom sawyer make his friends pay him to paint the fence in Adventures of 
- reflect -> stop: enough evidence

(No book titled "The Adventures of Tom Sawyer" is in the library catalogue; the whole library was searched instead.)

The evidence provided does not contain information about Tom Sawyer making the other boys pay him for the chance to paint the fence. This information is from "Adventures of Huckleberry Finn" by Mark Twain, but it does not address the specific question asked.

> quote provenance: OK: all 3 quotes found verbatim in the passages they cite

## c09-shipwreck-first-person (identify, 3 steps, 87s, $0.0000, 10 calls, 19072 in / 1171 out tokens, clarify) — PASS: titles 1/2, clarify reply unresolved, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: repeated clarify not allowed — finishing with what we have

- [ ] manual correctness (facts match the golden notes?)

**Question:** There was a book told entirely in the first person by a man who is shipwrecked and washes up somewhere completely unfamiliar. I can't remember whether it was mainly about surviving on his own or about getting along in a strange society. Which one was it? I might be mixing two of them up.

- reflect -> first person narrative shipwrecked man social interaction
- reflect -> __clarify__
- clarify: Could you confirm if the book you're thinking of is 'Robinson Crusoe' by Daniel Defoe, which seems to cover both surviving on his own and getting along in a strange society, or if you're considering another book?
Candidates in the library (answer with a number or a title):
1) Robinson Crusoe — Daniel Defoe
2) Moby Dick — Herman Melville
3) Seneca's Morals — Lucius Annaeus Seneca
4) Adventures of Huckleberry Finn — Mark Twain
- reflect -> stop: repeated clarify not allowed — finishing with what we have

The book you are referring to is most likely "Robinson Crusoe" by Daniel Defoe. The summary indicates that the narrative is primarily about a man who is shipwrecked and survives alone on an uninhabited island. While the text mentions that Crusoe rescues a native man named Friday and forms a relationship with him, the main focus of the story is on his survival and adaptation to the island. Therefore, the book is mainly about surviving on his own rather than getting along in a strange society. [Robinson Crusoe — Daniel Defoe, Summary.]

> quote provenance: OK: all 3 quotes found verbatim in the passages they cite

## c10-chivalry-two-books (aggregation, 4 steps, 91s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have

- [ ] manual correctness (facts match the golden notes?)

**Question:** There are two books in my library about knights and chivalry. One seems to take the whole code of honour seriously and the other makes fun of it. Which is which, and how does each one treat the idea of being a knight?

- reflect -> serious and satirical portrayals of knighthood in literature
- reflect -> serious and satirical portrayals of knighthood in literature
- reflect -> __clarify__
- clarify: Are you asking about 'Don Quixote' by Miguel de Cervantes, which seems to make fun of the code of honour, or is there another book in your library that you haven't mentioned yet?
Candidates in the library (answer with a number or a title):
1) Don Quixote — Miguel de Cervantes
2) Ivanhoe — Walter Scott
3) Gulliver's Travels — Jonathan Swift
4) Memoirs of Napoleon Bonaparte — Louis Antoine Fauvelet de Bourrienne
5) Twenty Thousand Leagues Under the Sea — Jules Verne
- reflect -> stop: repeated clarify not allowed — finishing with what we have

Don Quixote by Miguel de Cervantes is the book that takes the whole code of honour seriously and makes fun of it. The novel presents the idealized concept of knighthood through Don Quixote's actions and beliefs, while also satirizing these ideals through the character of Sancho Panza and the broader comedic situations that arise, such as the windmill episode [Don Quixote — Miguel de Cervantes, CHAPTER LII]. The book humorously contrasts the romantic and noble aspirations of knighthood with the practical and often absurd realities of the world.

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

---
10 completed, 0 errors, 2 clarify interrupts; quotes verified 28/31 (confirmed / unattributed / broken = 28 / 2 / 1); evidence items 31
behavior PASS 9/10 (aggregation 0/1, answer 6/6, identify 2/2, refusal 1/1); expected titles mentioned 9/11
cost $0.0000 total, $0.0000 mean per attempted question (81 LLM calls, 138083 in / 7477 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

---

## Run 3 — `qwen2.5:7b`, research subset again (wall 300 s)

```
run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo.yaml@f041a0290000 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen2.5:7b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run
```

## c01-ivanhoe-disguised-knight (identify, 2 steps, 20s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c02-huck-go-to-hell (answer, 2 steps, 23s, $0.0000, 6 calls, 9737 in / 577 out tokens) — PASS: titles 1/1, named book -> retrieval filter Adventures of Huckleberry Finn — Mark Twain, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c03-musketeers-women (answer, 4 steps, 35s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching
## c04-crusoe-cannibals (answer, 4 steps, 31s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching
## c05-quixote-windmills (answer, 2 steps, 25s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c06-fogg-missing-day (answer, 3 steps, 36s, $0.0000, 8 calls, 12196 in / 928 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence
## c07-alice-trial (answer, 2 steps, 20s, $0.0000, 6 calls, 8767 in / 511 out tokens) — PASS: titles 1/1, named book -> retrieval filter Alice's Adventures in Wonderland — Lewis Carroll, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c08-refusal-tom-sawyer (refusal, 3 steps, 23s, $0.0000, 8 calls, 15000 in / 545 out tokens) — PASS: titles 0/0, named book not in the catalogue: The Adventures of Tom Sawyer, stop: enough evidence
## c09-shipwreck-first-person (identify, 3 steps, 45s, $0.0000, 10 calls, 19072 in / 1171 out tokens, clarify) — PASS: titles 1/2, clarify reply unresolved, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: repeated clarify not allowed — finishing with what we have
## c10-chivalry-two-books (aggregation, 4 steps, 39s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have

---
10 completed, 0 errors, 2 clarify interrupts; quotes verified 28/31 (confirmed / unattributed / broken = 28 / 2 / 1); evidence items 31
behavior PASS 9/10 (aggregation 0/1, answer 6/6, identify 2/2, refusal 1/1); expected titles mentioned 9/11
cost $0.0000 total, $0.0000 mean per attempted question (81 LLM calls, 138083 in / 7490 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

`diff` against run 2 — every difference, in full:

```diff
1c1
< # Agent eval — 2026-09-10 04:28 — en-demo.yaml
---
> # Agent eval — 2026-09-10 04:39 — en-demo.yaml
5c5
< ## c01-ivanhoe-disguised-knight (identify, 2 steps, 34s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
---
> ## c01-ivanhoe-disguised-knight (identify, 2 steps, 20s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
20c20
< ## c02-huck-go-to-hell (answer, 2 steps, 49s, $0.0000, 6 calls, 9737 in / 577 out tokens) — PASS: titles 1/1, named book -> retrieval filter Adventures of Huckleberry Finn — Mark Twain, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
---
> ## c02-huck-go-to-hell (answer, 2 steps, 23s, $0.0000, 6 calls, 9737 in / 577 out tokens) — PASS: titles 1/1, named book -> retrieval filter Adventures of Huckleberry Finn — Mark Twain, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
33c33
< ## c03-musketeers-women (answer, 4 steps, 95s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching
---
> ## c03-musketeers-women (answer, 4 steps, 35s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching
49c49
< ## c04-crusoe-cannibals (answer, 4 steps, 86s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching
---
> ## c04-crusoe-cannibals (answer, 4 steps, 31s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching
64c64
< ## c05-quixote-windmills (answer, 2 steps, 50s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
---
> ## c05-quixote-windmills (answer, 2 steps, 25s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
77c77
< ## c06-fogg-missing-day (answer, 3 steps, 69s, $0.0000, 8 calls, 12196 in / 915 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence
---
> ## c06-fogg-missing-day (answer, 3 steps, 36s, $0.0000, 8 calls, 12196 in / 928 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence
91c91
< ## c07-alice-trial (answer, 2 steps, 44s, $0.0000, 6 calls, 8767 in / 511 out tokens) — PASS: titles 1/1, named book -> retrieval filter Alice's Adventures in Wonderland — Lewis Carroll, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
---
> ## c07-alice-trial (answer, 2 steps, 20s, $0.0000, 6 calls, 8767 in / 511 out tokens) — PASS: titles 1/1, named book -> retrieval filter Alice's Adventures in Wonderland — Lewis Carroll, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
104c104
< ## c08-refusal-tom-sawyer (refusal, 3 steps, 66s, $0.0000, 8 calls, 15000 in / 545 out tokens) — PASS: titles 0/0, named book not in the catalogue: The Adventures of Tom Sawyer, stop: enough evidence
---
> ## c08-refusal-tom-sawyer (refusal, 3 steps, 23s, $0.0000, 8 calls, 15000 in / 545 out tokens) — PASS: titles 0/0, named book not in the catalogue: The Adventures of Tom Sawyer, stop: enough evidence
120c120
< ## c09-shipwreck-first-person (identify, 3 steps, 87s, $0.0000, 10 calls, 19072 in / 1171 out tokens, clarify) — PASS: titles 1/2, clarify reply unresolved, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: repeated clarify not allowed — finishing with what we have
---
> ## c09-shipwreck-first-person (identify, 3 steps, 45s, $0.0000, 10 calls, 19072 in / 1171 out tokens, clarify) — PASS: titles 1/2, clarify reply unresolved, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: repeated clarify not allowed — finishing with what we have
136c136
< The book you are referring to is most likely "Robinson Crusoe" by Daniel Defoe. The summary indicates that the narrative is primarily about a man who is shipwrecked and survives alone on an uninhabited island. While the text mentions that Crusoe rescues a native man named Friday and forms a relationship with him, the main focus of the story is on his survival and adaptation to the island. Therefore, the book is mainly about surviving on his own rather than getting along in a strange society. [Robinson Crusoe — Daniel Defoe, Summary.]
---
> The book you are referring to is most likely "Robinson Crusoe" by Daniel Defoe. The summary indicates that the narrative is primarily about a man who is shipwrecked and survives alone on an uninhabited island. While the text mentions that Crusoe rescues a native man named Friday and forms a relationship with him, the main focus of the story is on his survival and adaptation to the island. Therefore, the book mainly centers around surviving on his own rather than getting along in a strange society. [Robinson Crusoe — Daniel Defoe, Summary.]
140c140
< ## c10-chivalry-two-books (aggregation, 4 steps, 91s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have
---
> ## c10-chivalry-two-books (aggregation, 4 steps, 39s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have
165c165
< cost $0.0000 total, $0.0000 mean per attempted question (81 LLM calls, 138083 in / 7477 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
---
> cost $0.0000 total, $0.0000 mean per attempted question (81 LLM calls, 138083 in / 7490 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
```

---

## Run 4 — `qwen2.5:14b`, catalogue set (wall 404 s)

# Agent eval — 2026-09-10 04:44 — en-demo-catalog.yaml

run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo-catalog.yaml@14b001e26f5e | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen2.5:14b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run

## k01-count (catalog, 0 steps, 12s, $0.0000, 1 calls, 576 in / 16 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** How many books do I have in my library?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k02-list (catalog, 0 steps, 1s, $0.0000, 1 calls, 578 in / 16 out tokens) — PASS: titles 33/33, catalog list: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** What are the names of all the books in my library?


33 books in your library (by the index tables):
- A Journey to the Interior of the Earth — Jules Verne
- A Study in Scarlet — Arthur Conan Doyle
- Adventures of Huckleberry Finn — Mark Twain
- Alice's Adventures in Wonderland — Lewis Carroll
- Around the World in Eighty Days — Jules Verne
- Celebrated Crimes — Alexandre Dumas
- Don Quixote — Miguel de Cervantes
- Dracula — Bram Stoker
- Frankenstein — Mary Shelley
- Gulliver's Travels — Jonathan Swift
- Ivanhoe — Walter Scott
- Jane Eyre — Charlotte Brontë
- Meditations — Marcus Aurelius
- Memoirs of Napoleon Bonaparte — Louis Antoine Fauvelet de Bourrienne
- Moby Dick — Herman Melville
- Pride and Prejudice — Jane Austen
- Robinson Crusoe — Daniel Defoe
- Romeo and Juliet — William Shakespeare
- Seneca's Morals — Lucius Annaeus Seneca
- The Adventures of Sherlock Holmes — Arthur Conan Doyle
- The Call of the Wild — Jack London
- The Extraordinary Adventures of Arsène Lupin — Maurice Leblanc
- The Hound of the Baskervilles — Arthur Conan Doyle
- The Kobzar of the Ukraine — Taras Shevchenko
- The Odyssey — Homer
- The Picture of Dorian Gray — Oscar Wilde
- The Secret Adversary — Agatha Christie
- The Three Musketeers — Alexandre Dumas
- The Time Machine — H. G. Wells
- The War of the Worlds — H. G. Wells
- Treasure Island — Robert Louis Stevenson
- Twenty Thousand Leagues Under the Sea — Jules Verne
- Wuthering Heights — Emily Brontë

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k03-has-yes (catalog, 0 steps, 2s, $0.0000, 1 calls, 572 in / 24 out tokens) — PASS: titles 1/1, catalog has: 1 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Ivanhoe?


Yes, in your library:
- Ivanhoe — Walter Scott

> quote provenance: catalog: 1 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k04-has-no (catalog, 0 steps, 2s, $0.0000, 1 calls, 574 in / 24 out tokens) — PASS: titles 0/0, catalog has: 0 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Is War and Peace in my library?


No book titled "War and Peace" is in your library. Closest titles: Pride and Prejudice.

> quote provenance: catalog: 0 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k05-by-author (catalog, 0 steps, 2s, $0.0000, 1 calls, 576 in / 26 out tokens) — PASS: titles 3/3, catalog by_author: 3 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have by Jules Verne?


3 book(s) by Jules Verne in your library:
- A Journey to the Interior of the Earth — Jules Verne
- Around the World in Eighty Days — Jules Verne
- Twenty Thousand Leagues Under the Sea — Jules Verne

> quote provenance: catalog: 3 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k06-count-ua (catalog, 0 steps, 1s, $0.0000, 1 calls, 586 in / 16 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Скільки книжок у моїй бібліотеці?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k07-content-not-catalog (answer, 1 steps, 61s, $0.0000, 4 calls, 5607 in / 342 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What are the names of the three musketeers?

- reflect -> stop: enough evidence

The names of the three musketeers are Athos, Porthos, and Aramis [The Three Musketeers — Alexandre Dumas, Summary].

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

## k08-about-whaling (answer, 2 steps, 121s, $0.0000, 6 calls, 9858 in / 832 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have about whaling?

- reflect -> books about whaling
- reflect -> stop: enough evidence

You have information about whaling from "Moby Dick" by Herman Melville, which includes details about the whaling ship Pequod, its crew, and the pursuit of the white whale Moby Dick. The evidence covers the narrative of a sailor signing onto a whaling ship, the characterization of Captain Ahab's quest for revenge against Moby Dick, and some cetology (the study of whales) [Moby Dick — Herman Melville — Summary]. [Moby Dick — Herman Melville — Plot] [Moby Dick — Herman Melville — CHAPTER 32. Cetology.]

> quote provenance: OK: all 6 quotes found verbatim in the passages they cite

## k09-mention-london (answer, 1 steps, 68s, $0.0000, 4 calls, 4921 in / 550 out tokens) — PASS: titles 0/0, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which of my books mention London?

- reflect -> stop: enough evidence

Your books that mention London are:

- The Adventures of Sherlock Holmes — Arthur Conan Doyle — Themes: "Victorian London's underworld and class contrasts — cases move between grand households and criminal back streets"
- The Adventures of Sherlock Holmes — Arthur Conan Doyle — X. THE ADVENTURE OF THE NOBLE BACHELOR: "The initials were, of course, of the highest importance, but more valuable still was it to know that within a week he had settled his bill at one of the most select London hotels."
- A Study in Scarlet — Arthur Conan Doyle — Themes: "Structural experiment — the novel splits into a London detective story and a Utah frontier melodrama told in flashback"
- The War of the Worlds — H. G. Wells — Plot: "mass panic drives Londoners into flight"

Dracula by Bram Stoker does not mention London according to the provided evidence.

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## k10-hybrid-named-book (answer, 4 steps, 131s, $0.0000, 10 calls, 14433 in / 612 out tokens) — PASS: titles 1/1, named book -> retrieval filter Dracula — Bram Stoker (expected), stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Dracula, and why does Jonathan Harker stay at the castle?

- reflect -> __chapter__|Dracula — Bram Stoker|Summary
- reflect -> Dracula Jonathan Harker stay castle why
- reflect -> __chapter__|Dracula — Bram Stoker|CHAPTER III
- reflect -> stop: step limit (4) — wanted to keep searching

Yes, you have access to "Dracula" by Bram Stoker. Jonathan Harker stays at Count Dracula's castle because he initially travels there to complete a property sale for Count Dracula [Dracula — Bram Stoker — Summary]. He later discovers that he is a prisoner held by the vampire Count Dracula [Dracula — Bram Stoker — CHAPTER III].

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

---
10 completed, 0 errors, 0 clarify interrupts; quotes verified 17/17 (confirmed / unattributed / broken = 17 / 0 / 0); evidence items 17
behavior PASS 10/10 (answer 4/4, catalog 6/6); expected titles mentioned 106/106
cost $0.0000 total, $0.0000 mean per attempted question (30 LLM calls, 38281 in / 2458 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

---

## Run 5 — `qwen2.5:14b`, research subset (wall 1331 s)

# Agent eval — 2026-09-10 04:51 — en-demo.yaml

run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo.yaml@f041a0290000 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen2.5:14b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run

## c01-ivanhoe-disguised-knight (identify, 2 steps, 114s, $0.0000, 6 calls, 10492 in / 661 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What was that novel where a knight returns to England in disguise, his father has rejected him, and there is all this conflict between Saxons and Normans while King Richard is returning?

- reflect -> father rejects son saxon norman conflict
- reflect -> stop: enough evidence

The novel you are referring to is "Ivanhoe" by Walter Scott. In this novel, Wilfred of Ivanhoe, a Saxon knight, returns secretly from the Crusades disguised as a pilgrim after being disinherited by his father Cedric for supporting the Norman King Richard and loving the Saxon ward Rowena. There is significant conflict between Saxons and Normans, and King Richard is returning to England, planning to seize the throne from his brother Prince John. [Ivanhoe — Walter Scott — Plot]

> quote provenance: WARNING: 1 of 4 quotes NOT found verbatim in any retrieved passage (possible hallucination):
  - Ivanhoe — Walter Scott: "King Richard, scheming to seize the throne from his brother Prince John, and the..."

## c02-huck-go-to-hell (answer, 2 steps, 100s, $0.0000, 6 calls, 9687 in / 554 out tokens) — PASS: titles 1/1, named book -> retrieval filter Adventures of Huckleberry Finn — Mark Twain, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Huck say, "All right, then, I'll go to hell"? What has he decided to do?

- reflect -> __chapter__|Adventures of Huckleberry Finn — Mark Twain|CHAPTER XXXI.
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

Huck says, "All right, then, I'll go to hell," after he decides not to turn Jim in and instead chooses to help him escape slavery. This decision is a pivotal moral crisis for Huck, where he chooses to support Jim's freedom over societal norms and his own upbringing. [Adventures of Huckleberry Finn — Mark Twain, Plot] [Adventures of Huckleberry Finn — Mark Twain, CHAPTER XXXI.]

> quote provenance: WARNING: 1 of 4 quotes NOT found verbatim in any retrieved passage (possible hallucination):
  - Adventures of Huckleberry Finn — Mark Twain: "All right, then, I’ll go to hell...."

## c03-musketeers-women (answer, 4 steps, 183s, $0.0000, 10 calls, 18644 in / 880 out tokens) — PASS: titles 1/1, stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** I remember that Constance Bonacieux was d'Artagnan's love and that Milady had been Athos's wife. But who were the women connected with Porthos and Aramis?

- reflect -> women connected with Aramis in The Three Musketeers
- reflect -> __chapter__|The Three Musketeers — Alexandre Dumas|Chapter XXIX.
- reflect -> __chapter__|The Three Musketeers — Alexandre Dumas|Chapter XXXII.
- reflect -> stop: step limit (4) — wanted to keep searching

From the provided evidence, we can infer the following:

- For Porthos, the evidence mentions a connection with the procurator's wife, who calls him "Monsieur Porthos" and invites him in, suggesting a romantic or social involvement [The Three Musketeers — Alexandre Dumas — Chapter XXXII.]. However, the exact nature of their relationship is not detailed in the given evidence.

- Regarding Aramis, the evidence does not provide specific information about a woman connected to him. The character description mentions Aramis's conflict between his military life and religious vocation, but it does not specify a romantic interest [The Three Musketeers — Alexandre Dumas — Characters]. Therefore, the evidence is insufficient to determine a specific woman connected to Aramis.

> quote provenance: OK: all 6 quotes found verbatim in the passages they cite

## c04-crusoe-cannibals (answer, 2 steps, 94s, $0.0000, 6 calls, 8962 in / 538 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** What did Crusoe do when he first discovered that cannibals were visiting the island? Did he attack them immediately?

- reflect -> __chapter__|Robinson Crusoe — Daniel Defoe|CHAPTER XII. A CAVE RETREAT
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

When Crusoe first discovered that cannibals were visiting the island, he was horrified and felt sick. He did not attack them immediately; instead, he was overwhelmed by the sight and the horror of the situation. [Robinson Crusoe — Daniel Defoe, CHAPTER XII. A CAVE RETREAT]

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

## c05-quixote-windmills (answer, 2 steps, 121s, $0.0000, 6 calls, 9678 in / 857 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Don Quixote attack the windmills even after Sancho tells him what they are, and how does he explain what happened after they knock him down?

- reflect -> __chapter__|Don Quixote — Miguel de Cervantes|CHAPTER VIII.
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

Don Quixote attacks the windmills because he mistakes them for giants, a result of his delusions about chivalry and his quest to revive knightly virtues. Even after Sancho clarifies that they are windmills, Don Quixote insists that a sorcerer has transformed the giants into mills to prevent him from achieving glory. After being knocked down by the windmill's sails, Don Quixote attributes his defeat to the sorcerer's interference rather than recognizing the windmills as harmless structures. [Don Quixote — Miguel de Cervantes, CHAPTER VIII.]

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c06-fogg-missing-day (answer, 2 steps, 102s, $0.0000, 6 calls, 7514 in / 817 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why did Phileas Fogg think he had lost the wager after reaching London, and how did he discover that he had actually won?

- reflect -> __chapter__|Around the World in Eighty Days — Jules Verne|CHAPTER XXXIV.
- reflect -> stop: enough evidence

Phileas Fogg thought he had lost the wager after reaching London because he was five minutes late, as stated in the evidence: "Having made the tour of the world, he was behind-hand five minutes. He had lost the wager!" [Around the World in Eighty Days — Jules Verne, CHAPTER XXXIV.]

However, he discovered that he had actually won when he was mistakenly arrested and detained in the Custom House for five minutes. This delay meant that when he completed his journey, he was exactly on time, as the five minutes he was detained were subtracted from the time he had taken to travel around the world. The evidence shows: "Sir,” he stammered, “sir—forgive me—most—unfortunate resemblance—robber arrested three days ago—you are free!” Phileas Fogg was free!" [Around the World in Eighty Days — Jules Verne, CHAPTER XXXIV.]

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c07-alice-trial (answer, 2 steps, 83s, $0.0000, 6 calls, 8679 in / 408 out tokens) — PASS: titles 1/1, named book -> retrieval filter Alice's Adventures in Wonderland — Lewis Carroll, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Alice stop being afraid during the trial and finally challenge the Queen and the whole court?

- reflect -> __chapter__|Alice's Adventures in Wonderland — Lewis Carroll|Chapter 12
- reflect -> stop: stopped: requested chapter was already attempted (re-reading cannot show more text)

Alice stops being afraid during the trial and challenges the Queen and the court when she becomes frustrated with the absurdity of the proceedings. Specifically, she loudly declares, "Stuff and nonsense," expressing her dissatisfaction with the idea of having the sentence before the trial [Alice's Adventures in Wonderland — Lewis Carroll, Chapter 12]. This moment marks her shift from fear to defiance, as she begins to question the logic of the court's actions.

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

## c08-refusal-tom-sawyer (refusal, 4 steps, 173s, $0.0000, 10 calls, 19873 in / 581 out tokens) — PASS: titles 0/0, named book not in the catalogue: The Adventures of Tom Sawyer, stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** How did Tom Sawyer make the other boys pay him for the chance to paint the fence?

- reflect -> how did tom sawyer convince the other boys to pay him to paint the fence
- reflect -> how did tom sawyer get the other boys to pay him to paint the fence
- reflect -> Tom Sawyer make other boys pay to paint fence
- reflect -> stop: step limit (4) — wanted to keep searching

(No book titled "The Adventures of Tom Sawyer" is in the library catalogue; the whole library was searched instead.)

The provided evidence does not cover how Tom Sawyer made the other boys pay him for the chance to paint the fence. The evidence is from "Adventures of Huckleberry Finn" and does not relate to the question about Tom Sawyer's fence-painting trick.

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

## c09-shipwreck-first-person (identify, 3 steps, 140s, $0.0000, 8 calls, 14478 in / 640 out tokens) — FAIL: titles 1/2, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** There was a book told entirely in the first person by a man who is shipwrecked and washes up somewhere completely unfamiliar. I can't remember whether it was mainly about surviving on his own or about getting along in a strange society. Which one was it? I might be mixing two of them up.

- reflect -> shipwrecked man first person strange society
- reflect -> shipwrecked man society book
- reflect -> stop: enough evidence

The book you're thinking of is "Robinson Crusoe" by Daniel Defoe. It is told entirely in the first person by a man who is shipwrecked and spends 28 years on an uninhabited island. The narrative focuses mainly on surviving on his own rather than getting along in a strange society, as the island is uninhabited. [Robinson Crusoe — Daniel Defoe, Summary]

> quote provenance: OK: all 3 quotes found verbatim in the passages they cite

## c10-chivalry-two-books (aggregation, 3 steps, 217s, $0.0000, 9 calls, 14935 in / 1776 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** There are two books in my library about knights and chivalry. One seems to take the whole code of honour seriously and the other makes fun of it. Which is which, and how does each one treat the idea of being a knight?

- reflect -> __chapter__|Don Quixote — Miguel de Cervantes|CHAPTER LII
- reflect -> __clarify__
- clarify: Could you specify which book among 'Don Quixote — Miguel de Cervantes' and another book about knights and chivalry you are referring to?
Candidates in the library (answer with a number or a title):
1) Don Quixote — Miguel de Cervantes
2) Ivanhoe — Walter Scott
3) The Three Musketeers — Alexandre Dumas
4) The Extraordinary Adventures of Arsène Lupin — Maurice Leblanc
- reflect -> stop: enough evidence

Based on the evidence provided, the book that makes fun of the code of honour and the idea of being a knight is "Don Quixote" by Miguel de Cervantes. This is evident from several chapters, such as [CHAPTER XLIX.], where the narrator describes the books of chivalry as "lies and frivolity" and expresses a desire to throw them away or burn them. Additionally, [CHAPTER XXXII.] shows a curate arguing against the existence of knights like those in chivalric books, suggesting that these books are fabrications and inventions of idle wits.

The book that takes the code of honour seriously is not directly mentioned in the evidence provided. However, given the context, it can be inferred that the other book is likely a traditional chivalric romance that upholds the ideals of knighthood without the satirical critique present in "Don Quixote."

> quote provenance: PARTIAL: 8 of 9 quotes confirmed in the passages they cite (1 quotes found in a retrieved passage other than the one cited — not counted as confirmed)

---
10 completed, 0 errors, 1 clarify interrupts; quotes verified 41/44 (confirmed / unattributed / broken = 41 / 1 / 2); evidence items 44
behavior PASS 8/10 (aggregation 0/1, answer 6/6, identify 1/2, refusal 1/1); expected titles mentioned 9/11
cost $0.0000 total, $0.0000 mean per attempted question (73 LLM calls, 122942 in / 7712 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

---

## Probe — `qwen3.6`, two questions (wall 73 s)

# Agent eval — 2026-09-10 05:15 — en-demo.yaml

run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo.yaml@f041a0290000 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen3.6 | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run

## c02-huck-go-to-hell (answer, 1 steps, 46s, $0.0000, 4 calls, 5828 in / 718 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Huck say, "All right, then, I'll go to hell"? What has he decided to do?

- reflect -> stop: enough evidence

Huck says he will "go to hell" because he has decided to help Jim escape slavery rather than turn him in [Adventures of Huckleberry Finn — Mark Twain, Plot]. He reaches this conclusion during a pivotal moral crisis where he tears up a letter exposing Jim's whereabouts, choosing to betray his conscience and societal standards rather than betray his friend [Adventures of Huckleberry Finn — Mark Twain, Summary]. The evidence provided does not contain the full text of CHAPTER XXXI. beyond the fragment "So I got a piece of paper and a pencil, all glad and excited, and s" [Adventures of Huckleberry Finn — Mark Twain, CHAPTER XXXI.], so it cannot provide further specific details from that chapter regarding this decision.

> quote provenance: OK: all 3 quotes found verbatim in the passages they cite

## c08-refusal-tom-sawyer (refusal, 2 steps, 24s, $0.0000, 4 calls, 9250 in / 94 out tokens) — PASS: titles 0/0, stop: CRAG gate: 2 dry steps in a row

- [ ] manual correctness (facts match the golden notes?)

**Question:** How did Tom Sawyer make the other boys pay him for the chance to paint the fence?

- reflect -> how Tom Sawyer convinced friends to whitewash the fence
- reflect -> stop: CRAG gate: 2 dry steps in a row

I searched both the book cards and the transcripts, but found no evidence for this question in the library. Honest answer: I don't know.

> quote provenance: no evidence — the answer itself is an honest refusal

---
2 completed, 0 errors, 0 clarify interrupts; quotes verified 3/3 (confirmed / unattributed / broken = 3 / 0 / 0); evidence items 3
behavior PASS 2/2 (answer 1/1, refusal 1/1); expected titles mentioned 1/1
cost $0.0000 total, $0.0000 mean per attempted question (8 LLM calls, 15078 in / 812 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

---

## Run 7 — `qwen2.5:7b`, research subset at the DEFAULT time budgets (wall 708 s)

Added in review round 1, from a clean tree (`--require-clean`, code `37f71e2`), to measure the timeout path the other runs never touched: `LLM_TIMEOUT_S` and `QUESTION_DEADLINE_S` unset, so the config defaults apply — 600 s a call against a 300 s question, the pair the cap was written for, instead of the 1200 s deadline runs 1-6 used. **What bound:** the cap was in force on every one of the 71 search-loop calls (each was given what was left of the 300 s question budget, from 300 s down to about 190 s at the worst point, rather than the configured 600 s) and on none of the 10 final synthesize calls, which kept the full 600 s. Nothing fired: no question reached the deadline (the longest, `c03`, took 110 s of 300 s, so 0 of 10 stop reasons are the deadline), no call hit the 5 s floor, and the harness reports 0 errors — i.e. tightening the effective per-call bound from 600 s to at most 300 s cost nothing. The run reproduces Run 2 exactly: same 9/10 behaviour, same 28 / 2 / 1 quotes, the same answer text and the same per-question token counts for all ten questions; the complete `diff` against Run 2 is five wall-clock numbers, given in full below.

One fingerprint does move, and it is not the index: `manifest@ed94677aa3a3` against Run 2's `manifest@f093bb27dab1`. The manifest hash describes the corpus files **in the working tree**, and this run was made at the rebased head, where `#17` re-pinned six of them. The index is the same one runs 1-6 used, built before that re-pin and reused as built (`rows=165` / `rows=7285`, both `built=2026-09-10T00:18:39` / `...T00:18:30`, identical to every other run's line), so the manifest here names the tree's corpus rather than the corpus the index was built from.

```
run: code 37f71e2 | golden en-demo.yaml@f041a0290000 | manifest@ed94677aa3a3 | toc@ef7a347ace1d | model qwen2.5:7b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=300s | single run
```

## c01-ivanhoe-disguised-knight (identify, 2 steps, 44s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c02-huck-go-to-hell (answer, 2 steps, 49s, $0.0000, 6 calls, 9737 in / 577 out tokens) — PASS: titles 1/1, named book -> retrieval filter Adventures of Huckleberry Finn — Mark Twain, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c03-musketeers-women (answer, 4 steps, 110s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching
## c04-crusoe-cannibals (answer, 4 steps, 96s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching
## c05-quixote-windmills (answer, 2 steps, 51s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c06-fogg-missing-day (answer, 3 steps, 69s, $0.0000, 8 calls, 12196 in / 915 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence
## c07-alice-trial (answer, 2 steps, 44s, $0.0000, 6 calls, 8767 in / 511 out tokens) — PASS: titles 1/1, named book -> retrieval filter Alice's Adventures in Wonderland — Lewis Carroll, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
## c08-refusal-tom-sawyer (refusal, 3 steps, 66s, $0.0000, 8 calls, 15000 in / 545 out tokens) — PASS: titles 0/0, named book not in the catalogue: The Adventures of Tom Sawyer, stop: enough evidence
## c09-shipwreck-first-person (identify, 3 steps, 87s, $0.0000, 10 calls, 19072 in / 1171 out tokens, clarify) — PASS: titles 1/2, clarify reply unresolved, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: repeated clarify not allowed — finishing with what we have
## c10-chivalry-two-books (aggregation, 4 steps, 92s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have

---
10 completed, 0 errors, 2 clarify interrupts; quotes verified 28/31 (confirmed / unattributed / broken = 28 / 2 / 1); evidence items 31
behavior PASS 9/10 (aggregation 0/1, answer 6/6, identify 2/2, refusal 1/1); expected titles mentioned 9/11
cost $0.0000 total, $0.0000 mean per attempted question (81 LLM calls, 138083 in / 7477 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

`diff` against Run 2 — every difference, in full:

```diff
1c1
< # Agent eval — 2026-09-10 04:28 — en-demo.yaml
---
> # Agent eval — 2026-09-10 06:17 — en-demo.yaml
3c3
< run: code 5b19f2d+dirty(4e721d730cb1) | golden en-demo.yaml@f041a0290000 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model qwen2.5:7b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=1200s | single run
---
> run: code 37f71e2 | golden en-demo.yaml@f041a0290000 | manifest@ed94677aa3a3 | toc@ef7a347ace1d | model qwen2.5:7b | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-10T00:18:39 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-10T00:18:30 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=300s | single run
5c5
< ## c01-ivanhoe-disguised-knight (identify, 2 steps, 34s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
---
> ## c01-ivanhoe-disguised-knight (identify, 2 steps, 44s, $0.0000, 6 calls, 6261 in / 474 out tokens) — PASS: titles 1/1, named book not in the catalogue: The Once and Future King, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
33c33
< ## c03-musketeers-women (answer, 4 steps, 95s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching
---
> ## c03-musketeers-women (answer, 4 steps, 110s, $0.0000, 10 calls, 20093 in / 897 out tokens) — PASS: titles 1/1, named book -> retrieval filter The Three Musketeers — Alexandre Dumas, stop: step limit (4) — wanted to keep searching
49c49
< ## c04-crusoe-cannibals (answer, 4 steps, 86s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching
---
> ## c04-crusoe-cannibals (answer, 4 steps, 96s, $0.0000, 10 calls, 18834 in / 755 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: step limit (4) — wanted to keep searching
64c64
< ## c05-quixote-windmills (answer, 2 steps, 50s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
---
> ## c05-quixote-windmills (answer, 2 steps, 51s, $0.0000, 6 calls, 9381 in / 644 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: stopped: requested chapter was already attempted (re-reading cannot show more text)
140c140
< ## c10-chivalry-two-books (aggregation, 4 steps, 91s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have
---
> ## c10-chivalry-two-books (aggregation, 4 steps, 92s, $0.0000, 11 calls, 18742 in / 988 out tokens, clarify) — FAIL: titles 1/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have
167,168d166
< 
< ---
```
