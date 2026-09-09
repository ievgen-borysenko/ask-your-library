> **Provenance of this artifact.** The catalogue set (`eval/golden/en-demo-catalog.yaml`, 10 questions: six about what
> the library holds, three content questions as negative controls, one hybrid item) run once on `b0d1321` on 2026-09-09
> with the default hosted planner, strict hit-id, the bge-m3 demo index of 04.09: **behaviour 10/10 (catalogue 6/6, controls
> and hybrid 4/4); quote provenance 17 / 0 / 0 confirmed / unattributed / broken; $0.1570 for the set, $0.0136 for the six
> catalogue items together**, which took 0 search steps and one model call each. The report below is the harness output
> copied verbatim from `answers-1788902671.md`; nothing was recomputed. The two runs before it are in the pull
> request's comments: 7/7 on `7060129` (seven items then) and 9/10 on `494d602`, where the hybrid item was routed to the
> catalogue as `has` — one sentence in the planner prompt and the vocabulary gate closed that, and this run is the
> measurement of the shipped code.

# Agent eval — 2026-09-08 23:24 — en-demo-catalog.yaml

run: code b0d1321 | golden en-demo-catalog.yaml@2d43a4cf13ee | manifest@f093bb27dab1 | toc@ef7a347ace1d | model anthropic/claude-sonnet-4.6 | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=300s | single run

## k01-count (catalog, 0 steps, 2s, $0.0022, 1 calls, 624 in / 23 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** How many books do I have in my library?


Your library holds 33 books (by the index tables).

> quote provenance: catalog: 33 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k02-list (catalog, 0 steps, 1s, $0.0022, 1 calls, 626 in / 23 out tokens) — PASS: titles 33/33, catalog list: 33 of 33, stop: catalog: answered from the index tables, no search

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

## k03-has-yes (catalog, 0 steps, 1s, $0.0023, 1 calls, 622 in / 32 out tokens) — PASS: titles 1/1, catalog has: 1 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Ivanhoe?


Yes, in your library:
- Ivanhoe — Walter Scott

> quote provenance: catalog: 1 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k04-has-no (catalog, 0 steps, 2s, $0.0023, 1 calls, 622 in / 31 out tokens) — PASS: titles 0/0, catalog has: 0 of 33, stop: catalog: answered from the index tables, no search

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

## k07-content-not-catalog (answer, 1 steps, 10s, $0.0214, 4 calls, 5947 in / 236 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What are the names of the three musketeers?

- reflect -> stop: enough evidence

Based on the evidence provided, the three musketeers are **Athos**, **Porthos**, and **Aramis** [The Three Musketeers, Summary].

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

## k08-about-whaling (answer, 1 steps, 23s, $0.0313, 4 calls, 5868 in / 914 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have about whaling?

- reflect -> stop: enough evidence

Based on the evidence available, you have material on **Moby Dick** by Herman Melville, which contains substantial content related to whaling.

Specifically, the book covers whaling in the following ways:

**Narrative elements**
- The story follows Ishmael, a sailor who signs onto the whaling ship Pequod out of Nantucket [Moby Dick, Summary]
- The crew is led by Captain Ahab on a quest to hunt Moby Dick, a white sperm whale [Moby Dick, Plot]
- The plot includes details like harpooners and the practical workings of a whaling voyage [Moby Dick, Plot]

**Technical and encyclopedic content**
- The novel intersperses its narrative with detailed chapters on whale biology and the whaling industry [Moby Dick, Key Takeaways]
- It covers cetology (the study of whales), whaling technique, and related topics [Moby Dick, Summary]
- One chapter specifically discusses the sperm whale as the most commercially valuable creature, being the only source of spermaceti [Moby Dick, Chapter 32]

In short, Moby Dick serves as both an adventure story and something close to an encyclopedia of 19th-century whaling knowledge [Moby Dick, Summary]. That appears to be the only source you have on the topic based on the available evidence.

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

## k09-mention-london (answer, 3 steps, 41s, $0.0699, 8 calls, 14942 in / 1673 out tokens) — PASS: titles 0/0, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which of my books mention London?

- reflect -> London city England
- reflect -> London setting
- reflect -> stop: enough evidence

Based on the evidence provided, the following books mention London:

**The War of the Worlds** by H. G. Wells
London features prominently, with descriptions of its chaotic evacuation and the narrator's brother witnessing the panicked exodus from the city. The narrator himself later returns to a seemingly abandoned London [The War of the Worlds, Plot; The War of the Worlds, Summary].

**The Adventures of Sherlock Holmes** by Arthur Conan Doyle
Victorian London's underworld and class contrasts are a central theme, with cases moving between grand households and criminal back streets [The Adventures of Sherlock Holmes, Themes].

**Around the World in Eighty Days** by Jules Verne
London is the starting and ending point of the story. Phileas Fogg is described as a wealthy London gentleman who makes his wager at the Reform Club, and the climax hinges on whether he arrives back in London in time [Around the World in Eighty Days, Characters; Around the World in Eighty Days, Plot].

**The Three Musketeers** by Alexandre Dumas
London is mentioned directly in dialogue, when D'Artagnan announces they must travel there [The Three Musketeers, Chapter XIX].

**Dracula** by Bram Stoker
London is referenced through the London Directory found among books of reference in Dracula's castle [Dracula, Chapter II].

**A Study in Scarlet** by Arthur Conan Doyle
While London is not explicitly named in the provided excerpt, the famous address of 221B Baker Street is mentioned, which is a London address [A Study in Scarlet, Summary]. However, the evidence does not directly state the word "London" for this book, so this one is only partially supported.

> quote provenance: OK: all 11 quotes found verbatim in the passages they cite

## k10-hybrid-named-book (answer, 1 steps, 9s, $0.0208, 4 calls, 5614 in / 267 out tokens) — PASS: titles 1/1, named book -> retrieval filter Dracula — Bram Stoker (expected), stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Dracula, and why does Jonathan Harker stay at the castle?

- reflect -> stop: enough evidence

Yes, you have Dracula in your evidence.

As for your question: Jonathan Harker stays at the castle because he is being held prisoner there by Count Dracula. He originally traveled to Transylvania in his professional capacity as a solicitor to complete a property sale for the Count, but his host turned out to be a vampire who kept him captive [Dracula, Summary].

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

---
10 completed, 0 errors, 0 clarify interrupts; quotes verified 17/17 (confirmed / unattributed / broken = 17 / 0 / 0); evidence items 17
behavior PASS 10/10 (answer 4/4, catalog 6/6); expected titles mentioned 106/106
cost $0.1570 total, $0.0157 mean per attempted question (26 LLM calls, 36121 in / 3256 out tokens; configured rates $3.0/M in, $15.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above
