# Trace: Fogg's missing day, green checks and an incomplete answer (honest failure)

Golden item `c06-fogg-missing-day`, type `answer`, expected book *Around the World in Eighty Days*.
Run: 2026-09-05 23:34, code `88881ee`, see [README](README.md) for the fingerprint.
Scored: behaviour **PASS** (titles 1/1), quote provenance **OK** (2/2 confirmed), 1 step, 13 s,
$0.0191, 4 LLM calls (4,040 in / 465 out tokens).
**The answer is incomplete, and says so.** Every automated signal in this repo is green on it and
the answer still does not answer the second half of the question, because the passage that answers
it never entered the retrieval window. That is why it is committed: the honest version of the same
gap that, in an earlier run, produced a confidently wrong sentence instead.

## Question

> Why did Phileas Fogg think he had lost the wager after reaching London, and how did he discover
> that he had actually won?

Two halves. The first is plot summary and every card in the corpus carries it. The second is a
single scene in one chapter.

## Step 1: plan -> act

The planner rewrote the question into one search query:

```
Phileas Fogg lost wager London
```

`search_both` returned the 8-hit window below (4 card chunks + 4 transcript chunks, fused by
reciprocal rank fusion; `dist` is the raw vector distance, lower is closer). Every hit is from the
same index key, `Around the World in Eighty Days — Jules Verne`. The `hit id` is what the agent
quotes against: in strict mode an evidence item must name the hit it copied from, and the book and
section are then taken from the hit record, never from the model.

| hit id | corpus | book | section | rrf | dist |
|---|---|---|---|---|---|
| s1h1 | cards | Around the World in Eighty Days | Plot | 0.0325 | 0.9275 |
| s1h2 | cards | Around the World in Eighty Days | Characters | 0.032 | 1.0351 |
| s1h3 | cards | Around the World in Eighty Days | Summary | 0.032 | 0.9541 |
| s1h4 | cards | Around the World in Eighty Days | Key Takeaways | 0.0315 | 0.9766 |
| s1h5 | transcripts | Around the World in Eighty Days | CHAPTER V. | 0.0315 | 0.7609 |
| s1h6 | transcripts | Around the World in Eighty Days | CHAPTER XXXVI. | 0.031 | 0.807 |
| s1h7 | transcripts | Around the World in Eighty Days | CHAPTER III. | 0.0309 | 0.7312 |
| s1h8 | transcripts | Around the World in Eighty Days | CHAPTER XXXIV. | 0.0309 | 0.8774 |

Read the section column before anything else. The four transcript hits are Chapters V, XXXVI, III
and XXXIV. The scene the question asks about is in Chapter XXXVII, and Chapter XXXVII is not in
this window.

Both of the answer's citations land on cards. Hit `s1h1`, the book card's `Plot` section (an
AI-generated summary of the volume, see `corpus/cards/`), which `observe` reads to a hard
1,200-character cut — here in the middle of the very sentence that would have explained the twist:

> Phileas Fogg, a wealthy, exactingly punctual London gentleman, bets his fellow Reform Club
> members twenty thousand pounds that he can travel around the world in eighty days using the
> era's new steamship and railway networks. [...] Fix, having failed to secure an arrest warrant in
> time, eventually arrests Fogg in Liverpool near journey's end, delaying him just long enough that
> Fogg believes he has lost the wager by arriving in London a day late. In a final twist, Fogg
> realizes that by travelin

Hit `s1h4`, the `Key Takeaways` card, which supplies the one bullet the second paragraph of the
answer rests on:

> - The famous twist ending reveals Fogg gained an extra day by traveling eastward across the
>   International Date Line

All four transcript hits stop before the scene (Chapters III, V, XXXIV and XXXVI; nothing after it
was retrieved). `s1h8` is the head of Chapter XXXIV, Fogg freed at the Custom House and ordering a
special train to London — the quoted head stops before the arrival in London:

> Phileas Fogg was free! He walked to the detective, looked him steadily in the face, and with the
> only rapid motion he had ever made in his life, or which he ever would make, drew back his arms,
> and with the precision of a machine knocked Fix down. [...] Mr. Fogg, Aouda, and Passepartout
> left the Custom House without delay, got into a cab, and in a few moments descended at the
> station. Phileas Fogg asked if there was an express train about to leave for London. It was forty
> minutes past two. The express train had left thirty-five minutes before. Phileas Fogg then
> ordered a special train. There were several rapi

And `s1h6` is Chapter XXXVI, the Reform Club waiting for a man nobody can locate, cut mid-word at
the same 1,200 characters:

> It is time to relate what a change took place in English public opinion when it transpired that
> the real bankrobber, a certain James Strand, had been arrested, on the 17th day of December, at
> Edinburgh. [...] His five friends of the Reform Club passed these three days in a state of
> feverish suspense. Would Phileas Fogg, whom they had forgotten, reappear before their eyes! Where
> was he at this moment? The 17th of December, the day of James Strand’s arrest, was the
> seventy-sixth since Phileas Fogg’s departure, and no news of him had been received. Was he dead?
> Had he abandoned the effort, or was he continuing his journey along the route agreed u

The remaining transcript hit, `s1h7`, is Chapter III — Fogg naming the terms of the bet in the
Reform Club (“As today is Wednesday, the 2nd of October, I shall be due in London in this very
room of the Reform Club, on Saturday, the 21st of December, at a quarter before nine p.m.”). Three
of the four transcript hits are about the wager rather than its resolution, which is what the query
asked for.

## Step 1: observe -> reflect

`observe` distilled the window into 2 evidence items; `reflect` judged the evidence sufficient and
the loop stopped after one step. No chapter drill-down, no second query.

## Answer (verbatim)

> Based on the evidence provided:
>
> Phileas Fogg believed he had lost the wager because he was arrested by Fix in Liverpool near the
> end of his journey, which delayed him just long enough that he arrived in London thinking he was
> a day late [Around the World in Eighty Days, Plot].
>
> However, the twist ending reveals that Fogg had actually gained an extra day by traveling
> eastward across the International Date Line, meaning he had in fact completed the journey within
> the eighty-day limit [Around the World in Eighty Days, Key Takeaways].
>
> The evidence does not detail the precise moment or mechanism by which Fogg discovered this fact
> — for example, who informed him or exactly how he realized the date discrepancy — so that
> specific detail cannot be confirmed from the sources provided.

Provenance verdict from the harness:

```
quote provenance: OK: all 2 quotes found verbatim in the passages they cite
```

## What to notice

- **Everything the repo measures is green, and the answer is still short.** Behaviour PASS (the
  expected title is mentioned), quote provenance 2/2 confirmed, one step, no error, $0.0191. The
  reader's verdict on this question, recorded 07.09 against the `v0.2.0-rc1` run of it in
  [`docs/eval-results/2026-09-07-v0.2.0-rc1-core.md`](../eval-results/2026-09-07-v0.2.0-rc1-core.md),
  is `incomplete`: the answer "omits Passepartout's encounter with the clergyman and the final dash
  to the Reform Club", and "citing the geographic date line explains the physical phenomenon, but
  fails to answer the narrative question of how the character learned the truth". No automated check in this repo produces that verdict.
- **The last paragraph is the reason this trace is here rather than in the wrong bucket.** The
  model does not guess the discovery scene. It states what the evidence does not cover, in the same
  register as h06's closing paragraph. Honest incompleteness is the best available behaviour when
  the window is missing the answer — but it is still a missing answer, and the eval has to record
  it as one.
- **The answering passage was never retrieved.** The golden notes for this item put it in
  Chapter XXXVII: travelling eastward Fogg "gained one day on his journey" without noticing, and
  Passepartout bursts in with "to-day is Saturday", not Sunday, in time for the Reform Club.
  Chapter XXXVII is in the index — `corpus/toc/around-the-world-80-days.json` lists it — it simply
  never ranked into the eight hits for the query `Phileas Fogg lost wager London`. The query
  describes the *problem* ("lost wager"), and the chapters that discuss the wager outrank the one
  chapter that resolves it.
- **This is a coverage failure, not a window-size one.** Three of the four transcript hits above
  are cut mid-word at 1,200 characters, which looks like the cause and is not. ADR-012 measured the
  observe window at 1,200, 2,500 and 4,000 characters on this core set: c03 completes at 2,500 and
  4,000, c06 stays incomplete at all three, because a wider window widens the chunks that are in
  the window and Chapter XXXVII is not one of them (`docs/backlog.md`: "c06 is not a window
  problem, the answering passage is never in the window"). The fix has to change *what is
  retrieved* — a second query or a chapter drill-down when a detail question's evidence is
  cards-only — not how much of each hit is read.
- **One step was enough, and that is the mechanism.** The same "enough after one step" reflex that
  makes h06 cheap and right stops the loop here with two card bullets in hand. `reflect` had the
  information it needed to doubt itself: both evidence items came from cards, neither from the book
  text, for a question that asks for a specific scene.
- **"International Date Line" is the corpus's phrase, not Verne's.** It comes from `s1h4`, an
  AI-generated card bullet, and the v0.1.0 artifact flags it: a gloss, not text. Provenance is
  green and correctly so — the quote really is verbatim in the hit the evidence names — but the
  citation `[Around the World in Eighty Days, Key Takeaways]` looks exactly like a citation of the
  novel to a reader skimming the answer. Same limit as the deathbed reveal in
  [the h06 trace](h06-kobzar-naimechka.md): card-supported and text-supported claims are typeset
  identically.
- **The failure mode has moved between runs, and the direction matters.** In the 05.09 core run
  (the ADR-014 ablation write-up calls it "the 05.09 11:45 core run"; its report,
  `answers-1788604408.md`, is stamped 12:33, and it is summarised in
  [`docs/eval-results/2026-09-05-core.md`](../eval-results/2026-09-05-core.md)) Chapter XXXVII
  *was* in the window, cut one line before "to-day is Saturday", and the answer inverted the day of
  the week — it had Fogg told it was Monday. That is **wrong**, not incomplete. Both tagged runs —
  `v0.1.0-rc1`, 05.09 22:07, and `v0.1.0`, 05.09 23:34, the run above — stop short and say so. The
  ADR-014 ablation of 05.09 23:39 reads `incomplete` in four of its five conditions, and the fifth,
  `retrieve-answer` (one retrieval, one synthesize, no loop), inverts the day of the week again in
  the same way as the 05.09 core run. Three recorded runs and five ablation conditions, and not one
  of them reaches Passepartout's line.
- **Why this is the committed failure example.** It is reader-verified, the reader's `incomplete`
  verdict is recorded against it, and the mechanism generalises: a green provenance score is a
  statement about where words came from, never about whether the words that would have answered the
  question were ever put in front of the model. The previous canonical failure trace, `h12`
  (a character's lie quoted as fact), was removed from the core set by the reader on 06.09 because
  it was never reader-verified; the ablation artifact still records its finding as a former core
  item.
