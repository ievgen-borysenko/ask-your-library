> **Provenance of this artifact.** One question asked twice through the CLI on 2026-09-10, from a
> clean `git clone` of this repository at `7c470bc` (`feat/local-by-default`), working tree clean and
> **no `.env` at all** — so every setting except the index path is `config.py`'s own default, which
> is what the quick start's reader gets. This is not an eval-harness run: there is no golden set, no
> score and no `run:` fingerprint line, only the CLI's own metrics block, pasted verbatim below and
> nothing recomputed from it. `LIBRARY_DB_PATH` pointed at the demo index built on
> 2026-09-10T00:18 (`cards_ollama` 165 rows, `transcripts_ollama` 7285 rows, bge-m3/1024d) — the
> same LanceDB [`2026-09-10-local-models.md`](2026-09-10-local-models.md) read, reused as built and
> never rebuilt for this. Machine: Apple M3 Pro, 36 GB, macOS 26.6.2, Ollama 0.33.3, both models
> served on the GPU. Two runs on one machine: an order of magnitude, not a benchmark.

# First question from a clean clone — 2026-09-10 — `LLM_BACKEND=ollama`, `qwen2.5:14b`

**Why this record exists.** `docs/cost.md` quoted a first-question latency that no committed report
held, taken from a scratch directory nobody else could open. The figure is worth having — the first
ask is the one a reader makes — so it is measured here instead, in the shape the other reports in
this directory use, and `cost.md` cites this file.

## Configuration

Everything below is a default of `7c470bc` unless the command sets it. `LLM_BACKEND=ollama` (the
shipped default), `OLLAMA_LLM_MODEL=qwen2.5:14b`, `EMBED_BACKEND=ollama`, `OLLAMA_EMBED_MODEL=bge-m3`,
`OLLAMA_URL=http://localhost:11434`, `LLM_TIMEOUT_S=600` and `QUESTION_DEADLINE_S=1200` (both the
local-backend defaults this branch introduced), `MAX_OUTPUT_TOKENS=2048`, `MAX_STEPS=4`,
`SEARCH_HIT_CHARS=2500`, `CHAPTER_HIT_CHARS=12000`. Prices are the local ones, `$0.0/M` in and out,
which is why the cost line reads `$0.0000` and is arithmetic rather than an estimate.

## Commands

```bash
git clone <this repository> && cd ask-your-library && git checkout 7c470bc
uv sync --locked
# the demo index was reused as built, never rebuilt; nothing else is set
LIBRARY_DB_PATH=<demo index> uv run ask-library "What does Marcus Aurelius say about anger?"
# then, immediately, the same command again
```

The question is the one the README's quick start prints as "the first question".

## Cold — first ask, nothing resident

`ollama ps` was empty before this run: neither `qwen2.5:14b` nor `bge-m3` was loaded, and the
process was a fresh one against a venv `uv sync` had just created. Started 16:45:20 local time.

```
[plan] mode=answer, queries: ['Marcus Aurelius anger', 'what does Marcus Aurelius say about anger', 'meditations marcus aurelius anger']
[act #1] found 8 hits
[observe] evidence so far: 1
[reflect] searching more: meditations marcus aurelius anger
[act #2] found 8 hits
[observe] evidence so far: 3
[reflect] reading chapter: Meditations — Marcus Aurelius / THE ELEVENTH BOOK
[act #3] found 1 hits
[observe] evidence so far: 4
[reflect] stopped: requested chapter was already attempted (re-reading cannot show more text)

[quote provenance] OK: all 4 quotes found verbatim in the passages they cite
[metrics] qwen2.5:14b: 8 LLM calls, 12999 in / 754 out tokens, ~$0.0000, 160.8s, search steps: 3
  stop: requested chapter was already attempted (re-reading cannot show more text)
  per node: plan $0.0000 (1x), observe $0.0000 (3x), reflect $0.0000 (3x), synthesize $0.0000 (1x)
  retrieval: 17 hits -> 4 evidence items; injection redactions: 0
  cache: 807 tokens read from cache
```

## Warm — the same question again, model resident

Started 16:48:12, with both models still loaded (`ollama ps`: `qwen2.5:14b` 15 GB and `bge-m3`
673 MB, 100% GPU). Same three search steps, same stop reason, same token counts, same answer text.

```
[quote provenance] OK: all 4 quotes found verbatim in the passages they cite
[metrics] qwen2.5:14b: 8 LLM calls, 12999 in / 754 out tokens, ~$0.0000, 62.7s, search steps: 3
  stop: requested chapter was already attempted (re-reading cannot show more text)
  per node: plan $0.0000 (1x), observe $0.0000 (3x), reflect $0.0000 (3x), synthesize $0.0000 (1x)
  retrieval: 17 hits -> 4 evidence items; injection redactions: 0
  cache: 12606 tokens read from cache
```

## The answer, once (both runs printed it identically)

> Marcus Aurelius advises patience and tolerance towards others' faults, viewing anger as an
> unproductive response to the inevitable imperfections of people. He suggests understanding the
> nature of those who wrong us, recognizing that their actions stem from their own flawed
> understanding, and thus, there is no reason for our anger to be troubled by them. He also notes
> that our own opinions about the sins of others are what truly cause us distress, and if we can
> remove these opinions, we can also remove our anger [Meditations — Marcus Aurelius, Themes].
> Additionally, he encourages acceptance of the present moment and the roles we play in the
> universe, which can help in managing anger [Meditations — Marcus Aurelius, THE ELEVENTH BOOK].

- [ ] manual correctness (facts match the source text?)

## Reading

**160.8 s cold, 62.7 s warm, and the difference is residency, not the question.** Identical token
counts and an identical answer at `temperature=0`, so the 98 s between them is model load plus a
cold prompt cache: the cold run's metrics block reports 807 tokens read from cache against 12,606
on the warm one. A reader's very first question is the cold number; the second one they ask is the
warm number, and both are below the 1,200 s question deadline the local backend now defaults to —
which was the point of measuring: under the old flat 300 s deadline this question spent more than
half its budget.

**This is a research question, and it lands where the research figures say it should.** Three
search steps including a chapter read, which is the expensive path; `docs/cost.md`'s local research
band (61 to 217 s per question, from the sets in
[`2026-09-10-local-models.md`](2026-09-10-local-models.md)) contains both runs. A catalogue question
on the same machine and model takes 1 to 12 s, because it makes one model call and never searches.

**What this record does not say.** Two runs, one question, one machine, one model — nothing here is
a distribution, and the answer's correctness is a manual read, not a score (see
[`../evaluation.md`](../evaluation.md)). The CLI run in the README's GIF is a *different* question
(the half-remembered island-and-cannibals `identify` question) and its 147.7 s is the same kind of
number as the 160.8 s here: a cold first ask on this machine, its own metrics block reporting 436
tokens read from cache.
