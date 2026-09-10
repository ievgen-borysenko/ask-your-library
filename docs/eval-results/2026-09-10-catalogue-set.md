> **Provenance of this artifact.** The catalogue set (`eval/golden/en-demo-catalog.yaml`, 10 questions: six about what
> the library holds, three content questions as negative controls, one hybrid item) run once on `466fc82` — this
> repository's `main` at the merge of `#18` — on 2026-09-10 with the default hosted planner, strict hit-id, the same
> bge-m3 demo index of 04.09: **behaviour 10/10 (catalogue 6/6, controls and hybrid 4/4); quote provenance 21 / 0 / 0
> confirmed / unattributed / broken on the four research items; $0.1762 for the set, $0.0136 for the six catalogue items
> together**, which took 0 search steps and one model call each. Model `anthropic/claude-sonnet-4.6`. Golden
> `en-demo-catalog.yaml@14b001e26f5e` — the same checksum the run below supersedes, so the two are the same measurement
> on different code. Corpus `manifest@ed94677aa3a3`, `toc@ef7a347ace1d`: the manifest checksum moved with `#17`, which
> re-pinned six drifted Gutenberg files, while the index did not — both tables carry their 04.09 build stamps
> (`cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01`,
> `transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31`), so this run read the same LanceDB the
> 09.09 run read and a re-run over a rebuilt index would be a different measurement. The report below is the harness
> output copied verbatim from `answers-1789023045.md`; nothing was recomputed, and the closing section is a reading of
> it rather than part of it. This run supersedes the 10/10 run of 2026-09-09 on `50b9347`
> ([`2026-09-09-catalogue-set.md`](2026-09-09-catalogue-set.md), $0.1749, 22 / 0 / 0), which stays as the record of
> that code. Single run, hosted planner, not reader-graded — the manual-correctness checkboxes below are unticked.

# Agent eval — 2026-09-10 08:50 — en-demo-catalog.yaml

run: code 466fc82 | golden en-demo-catalog.yaml@14b001e26f5e | manifest@ed94677aa3a3 | toc@ef7a347ace1d | model anthropic/claude-sonnet-4.6 | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=300s | single run

## k01-count (catalog, 0 steps, 2s, $0.0022, 1 calls, 624 in / 23 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** How many books do I have in my library?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k02-list (catalog, 0 steps, 2s, $0.0022, 1 calls, 626 in / 23 out tokens) — PASS: titles 33/33, catalog list: 33 of 33, stop: catalog: answered from the index tables, no search

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

## k03-has-yes (catalog, 0 steps, 2s, $0.0023, 1 calls, 622 in / 32 out tokens) — PASS: titles 1/1, catalog has: 1 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Ivanhoe?


Yes, in your library:
- Ivanhoe — Walter Scott

> quote provenance: catalog: 1 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k04-has-no (catalog, 0 steps, 1s, $0.0023, 1 calls, 622 in / 31 out tokens) — PASS: titles 0/0, catalog has: 0 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Is War and Peace in my library?


No book titled "War and Peace" is in your library. Closest titles: Pride and Prejudice.

> quote provenance: catalog: 0 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k05-by-author (catalog, 0 steps, 2s, $0.0024, 1 calls, 624 in / 34 out tokens) — PASS: titles 3/3, catalog by_author: 3 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have by Jules Verne?


3 book(s) by Jules Verne in your library:
- A Journey to the Interior of the Earth — Jules Verne
- Around the World in Eighty Days — Jules Verne
- Twenty Thousand Leagues Under the Sea — Jules Verne

> quote provenance: catalog: 3 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k06-count-ua (catalog, 0 steps, 2s, $0.0022, 1 calls, 632 in / 23 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Скільки книжок у моїй бібліотеці?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k07-content-not-catalog (answer, 1 steps, 10s, $0.0215, 4 calls, 6011 in / 231 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What are the names of the three musketeers?

- reflect -> stop: enough evidence

The three musketeers are Athos, Porthos, and Aramis [The Three Musketeers — Alexandre Dumas, Summary].

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

## k08-about-whaling (answer, 2 steps, 24s, $0.0464, 6 calls, 10705 in / 951 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have about whaling?

- reflect -> whale hunting ships crews
- reflect -> stop: enough evidence

Based on the evidence you have, your material on whaling comes entirely from **Moby-Dick by Herman Melville**.

Here is what it covers:

**The narrative context**
The story follows Ishmael, a sailor aboard the whaling ship Pequod out of Nantucket, whose voyage is driven by Captain Ahab's obsessive quest for revenge against Moby Dick, the white sperm whale that took his leg [Moby Dick — Herman Melville, Summary].

**Whaling as a subject within the book**
The novel goes well beyond just the story. Melville intersperses the narrative with detailed, encyclopedic chapters on whale biology and the whaling industry [Moby Dick — Herman Melville, Key Takeaways]. Specifically, numerous chapters cover:

- Whale anatomy and classification
- The practical work of whaling, including the chase, the kill, and the trying-out (rendering) of blubber

[Moby Dick — Herman Melville, Plot]

So your material gives you both a narrative window into 19th-century whaling life and a fairly encyclopedic treatment of the industry and the animals themselves, all within a single source.

> quote provenance: OK: all 6 quotes found verbatim in the passages they cite

## k09-mention-london (answer, 3 steps, 41s, $0.0736, 8 calls, 15294 in / 1850 out tokens) — PASS: titles 0/0, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which of my books mention London?

- reflect -> London city England
- reflect -> London setting
- reflect -> stop: enough evidence

Based on the evidence provided, the following books from your collection mention London:

1. **The War of the Worlds** (H. G. Wells) — London features prominently, including the chaotic evacuation of the city and the Martians advancing toward it [The War of the Worlds — H. G. Wells, Plot] [The War of the Worlds — H. G. Wells, XIV. IN LONDON.].

2. **The Adventures of Sherlock Holmes** (Arthur Conan Doyle) — Victorian London's underworld and class contrasts are a central theme [The Adventures of Sherlock Holmes — Arthur Conan Doyle, Themes].

3. **Around the World in Eighty Days** (Jules Verne) — The story begins in London, where Phileas Fogg is described as a wealthy London gentleman who makes his wager at London's Reform Club [Around the World in Eighty Days — Jules Verne, Summary].

4. **The Three Musketeers** (Alexandre Dumas) — London is mentioned as a destination when D'Artagnan declares "To London, gentlemen" [The Three Musketeers — Alexandre Dumas, Chapter XIX.].

5. **Dracula** (Bram Stoker) — London is referenced through the London Directory found among books [Dracula — Bram Stoker, CHAPTER II].

It is worth noting that while **A Study in Scarlet** is in your evidence, it only mentions Baker Street without explicitly naming London in the provided excerpt, so that claim cannot be confirmed from the available evidence.

> quote provenance: OK: all 13 quotes found verbatim in the passages they cite

## k10-hybrid-named-book (answer, 1 steps, 9s, $0.0211, 4 calls, 5677 in / 269 out tokens) — PASS: titles 1/1, named book -> retrieval filter Dracula — Bram Stoker (expected), stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Dracula, and why does Jonathan Harker stay at the castle?

- reflect -> stop: enough evidence

Yes, you have Dracula in your search results.

According to [Dracula — Bram Stoker, Summary], Jonathan Harker stays at the castle because he is being held prisoner there by Count Dracula. He originally traveled to Transylvania in a professional capacity, to complete a property sale for the Count, but discovered that his host was a vampire who would not let him leave.

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

---
10 completed, 0 errors, 0 clarify interrupts; quotes verified 21/21 (confirmed / unattributed / broken = 21 / 0 / 0); evidence items 21
behavior PASS 10/10 (answer 4/4, catalog 6/6); expected titles mentioned 106/106
cost $0.1762 total, $0.0176 mean per attempted question (28 LLM calls, 41437 in / 3467 out tokens; configured rates $3.0/M in, $15.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above

## What this run says

The hosted path is where it was. Between `50b9347` (09.09) and `466fc82` the loop gained the filled citation labels
and the rule that points at them, the underscore fix in `_normalize`, the refusal-tail scoring rule and the retry
loop bounded by the question deadline (`#18`); on this set none of it moves a verdict. Behaviour is 10/10 again,
with the same routing question by question: the six catalogue items answered from the index tables in 0 steps and
one model call, the three controls through the research loop at 1, 2 and 3 steps, the hybrid item with retrieval
limited to `Dracula — Bram Stoker`. Quote provenance is 0 unattributed and 0 broken again, over 21 evidence items
against 22: the single difference is `k09-mention-london`, where `observe` distilled 13 passages instead of 14, all
confirmed either way. The set cost $0.1762 against $0.1749, +0.7% on the same 28 model calls, and the six catalogue
items cost $0.0136 in both runs.

What is visible in the answers is the prompt change: every citation now carries the index key the evidence line
opens with — `[The Three Musketeers — Alexandre Dumas, Summary]` where the 09.09 run wrote
`[The Three Musketeers, Summary]`. That is the label-copying rule doing on the hosted model what it was measured
doing on the local ones, and it is why the answers read differently while the scores do not: the scorer checks the
structured catalogue result and the expected titles, not the citation string.

What this run does not say: it is one run of one set on one model, the correctness checkboxes are unticked, and a
green provenance column is a statement about where the quotes came from, never about whether the answers are right
(see [`../evaluation.md`](../evaluation.md)).
