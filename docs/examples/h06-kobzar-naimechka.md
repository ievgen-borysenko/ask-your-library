# Trace: a vague recollection of a Ukrainian poem (success)

Golden item `h06-kobzar-mother-servant`, type `answer`, expected book *The Kobzar of the Ukraine*.
Run: 2026-09-05 23:34, code `88881ee`, see [README](README.md) for the fingerprint.
Scored: behaviour PASS (titles 1/1), quote provenance OK (4/4 confirmed), 1 step, 19 s, $0.0248,
4 LLM calls (4,388 in / 776 out tokens).

## Question

> In a Ukrainian poem, a mother left her baby with some older couple and then came to work for
> them as a servant. What was the poem, and why did she do it?

The question names no title, no author and no character. It is the kind of half-memory the
product is built for.

## Step 1: plan -> act

The planner rewrote the question into one search query:

```
Ukrainian poem mother leaves baby older couple servant
```

`search_both` returned the 8-hit window below (4 card chunks + 4 transcript chunks, fused by
reciprocal rank fusion; `dist` is the raw vector distance, lower is closer). Every hit is from
the same index key, `The Kobzar of the Ukraine — Taras Shevchenko`. The `hit id` is what the
agent quotes against: in strict mode an evidence item must name the hit it copied from, and the
book and section are then taken from the hit record, never from the model.

| hit id | corpus | book | section | rrf | dist |
|---|---|---|---|---|---|
| s1h1 | cards | The Kobzar of the Ukraine | Key Poems | 0.0328 | 0.8306 |
| s1h2 | cards | The Kobzar of the Ukraine | Key Takeaways | 0.0323 | 0.9485 |
| s1h3 | cards | The Kobzar of the Ukraine | Summary | 0.0317 | 0.9998 |
| s1h4 | cards | The Kobzar of the Ukraine | Structure | 0.0312 | 1.0236 |
| s1h5 | transcripts | The Kobzar of the Ukraine | NAIMECHKA OR THE SERVANT | 0.0308 | 0.7795 |
| s1h6 | transcripts | The Kobzar of the Ukraine | THE MEANING OF SERFDOM | 0.0308 | 0.9023 |
| s1h7 | transcripts | The Kobzar of the Ukraine | A DREAM | 0.0285 | 0.9567 |
| s1h8 | transcripts | The Kobzar of the Ukraine | NAIMECHKA OR THE SERVANT | 0.0164 | 0.7771 |

Two hits carry the answer's citations. Hit `s1h1`, the book card (an AI-generated summary of the volume,
see `corpus/cards/`):

> - **"Naimechka; or The Servant"** — a narrative poem about Hanna, an unmarried mother who
>   leaves her infant son Mark with a childless couple, returns to them as a servant to raise
>   him, and reveals that she is his mother only on her deathbed
> [...]

Hit `s1h5`, the poem itself (Gutenberg #68486, A. J. Hunter's translation), as chunked from the
prepared text — the old couple take Hanna on, and she raises her own son as their servant:

> You don’t know us, We don’t know you. You’ll stay with us a few days, Get acquainted with our
> ways; We’ll see you day by day, Bye and bye we’ll talk of pay. Is it so, daughter?” “Very
> good, uncle.” “We invite you into the house.” And so they to agreement came. [...] She in the
> house and out doth work From morning light to evening’s mirk. And yet the child is her special
> care; Whatever befalls, she’s the mother there. [...] So the servant never rests, But the
> night her spirit tests. In her chamber then, I ween, Many a tear she sheds unseen. Yet none
> knows nor sees it all But the little Mark so small. [...]

The third hit worth reading is `s1h8`, a different chunk of the same section that the answer
does not cite: the old couple, childless and worrying who will bury them, hear a child at their
gate.

> “Anastasia, wife of mine, Soon will come our fatal day, Who will lay our bones away?” “God
> only knows. [...] “Hold a minute, Hearest thou? Something cries Beyond the gate—’tis like a
> child. Let’s run! See’st ought? I thought something was there.” Together they sprang And to
> the gate running; Then stopped in silence wondering. Before the stile a swaddled child, Not
> bound tightly, just wrapped lightly, For it was in summer mild, And the mother with fond
> caress Had covered it

That is where the chunk stops for the agent: `observe` read the first 1,200 characters of each (this run; 2,500 since 0.2, ADR-012)
search hit, and here the cut lands mid-sentence. The mother's own statement of her reason is
earlier still: the poem's Prologue, in the opening ~1,000 characters of the same chapter, where
she refuses to give the child her name and so bind him to poverty and her shame (the golden
notes quote that line against `data/prepared/kobzar.json`). Neither retrieved chunk of this
section reaches it, so it is not in this window at all.

## Step 1: observe -> reflect

`observe` distilled the window into 4 evidence items; `reflect` judged the evidence sufficient
and the loop stopped after one step.

## Answer (verbatim)

> The poem is "Naimechka; or The Servant" by the Ukrainian poet Taras Shevchenko, from his
> collection The Kobzar of the Ukraine [The Kobzar of the Ukraine, Key Poems].
>
> The mother, Hanna, was an unmarried mother, and it appears her unmarried status was the driving
> reason behind her actions. She left her infant son Mark with a childless couple, then returned
> to that same household to work as their servant [The Kobzar of the Ukraine, Key Poems]. This
> arrangement allowed her to remain close to her son and continue to care for him -- as the poem
> notes, "Whatever befalls, she's the mother there" [The Kobzar of the Ukraine, NAIMECHKA OR THE
> SERVANT] -- while concealing her true identity, presumably to protect both herself and the
> child from the social stigma attached to illegitimacy. She maintained this secret throughout
> her life, only revealing on her deathbed that she was Mark's mother [The Kobzar of the Ukraine,
> Key Poems].
>
> The evidence does not go into further detail about the specific social circumstances or the
> fate of the father, so those aspects of her motivation cannot be fully addressed from the
> available sources.

Provenance verdict from the harness:

```
quote provenance: OK: all 4 quotes found verbatim in the passages they cite
```

## What to notice

- **The "what" is answered from the poem, the "why" is answered honestly short.** The one line
  the answer quotes from the book text, "Whatever befalls, she's the mother there", is in `s1h5`,
  and the validator found it in the hit the evidence names - the `confirmed` bucket, not
  `unattributed`. Hanna's own statement of her reason is in the poem's Prologue, which this run
  never retrieved; instead of filling the gap, the model hedged ("it appears", "presumably") and
  closed with an explicit statement of what the evidence does not cover. That paragraph is the
  interesting part of this trace: the same window that lets it name the poem does not let it
  prove the motive, and the answer says so.
- **The quote survived retyped typography.** The book text has a curly apostrophe
  ("she’s"); the answer has a straight one ("she's"). The validator compares normalized word
  sequences, not bytes, exactly so that honest requoting is not scored as a hallucination, while
  a paraphrase still fails word by word.
- **The deathbed reveal rests on a card, not on the poem.** The citation `[..., Key Poems]`
  points at `s1h1`, an AI-generated summary. The poem's ending was not in the window. The
  statement is correct - the golden notes verify it against `data/prepared/kobzar.json` - but the
  system does not tell the reader that this sentence has a weaker kind of support than the quoted
  one. The backlog carries the related fix: prefer a chapter drill-down when a detail question's
  evidence is cards-only.
- **The section label alone does not identify a chunk.** `s1h5` and `s1h8` are both
  `NAIMECHKA OR THE SERVANT`, and the answer's citation cannot tell them apart; the hit id can.
  That is why the evidence carries `hit_id` and the validator checks against it.
- **Hybrid fusion, not vector distance alone, ordered the window.** `s1h8` has the closest vector
  distance of all eight hits (0.7771) yet lands last after fusion, because the keyword side
  ranked the cards higher. It still made the 8-hit window, which is what the retrieval eval
  measures.
- **One step was enough here.** For a question with one clear target that is the right
  behaviour; the same "enough after one step" reflex is what makes the agent under-clarify on
  ambiguous identify questions (see [Known limits](../known-limits.md)), and what stops it going after the
  chapter it never retrieved in [the c06 trace](c06-fogg-missing-day.md).
