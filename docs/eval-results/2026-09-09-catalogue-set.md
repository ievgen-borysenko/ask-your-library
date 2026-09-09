> **Provenance of this artifact.** The catalogue set (`eval/golden/en-demo-catalog.yaml`, 10 questions: six about what
> the library holds, three content questions as negative controls, one hybrid item) run once on `50b9347` on 2026-09-09
> with the default hosted planner, strict hit-id, the bge-m3 demo index of 04.09: **behaviour 10/10 (catalogue 6/6, controls
> and hybrid 4/4); quote provenance 22 / 0 / 0 confirmed / unattributed / broken on the four research items; $0.1749 for the
> set, $0.0136 for the six catalogue items together**, which took 0 search steps and one model call each. The report below
> is the harness output copied verbatim from `answers-1788956691.md`; nothing was recomputed. This run supersedes the
> 10/10 run of the same day on `b0d1321` ($0.1570): between the two, the scorer moved from titles to the full index keys
> "Title — Author", every catalogue item gained `expected_total` (the catalogue must hold the whole corpus) and
> `expected_op`, and the resolver and the vocabulary gate changed (containment in one direction, "who" a content word
> except for authorship, the resolved title masked once), so the two runs have different golden checksums and are not
> the same measurement. The runs before that are in the pull request's comments: 7/7 on `7060129` (seven items then)
> and 9/10 on `494d602`, where the hybrid item was routed to the catalogue as `has`.

# Agent eval — 2026-09-09 14:24 — en-demo-catalog.yaml

run: code 50b9347 | golden en-demo-catalog.yaml@14b001e26f5e | manifest@f093bb27dab1 | toc@ef7a347ace1d | model anthropic/claude-sonnet-4.6 | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=300s | single run

## k01-count (catalog, 0 steps, 3s, $0.0022, 1 calls, 624 in / 23 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

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

## k04-has-no (catalog, 0 steps, 1s, $0.0023, 1 calls, 622 in / 31 out tokens) — PASS: titles 0/0, catalog has: 0 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** Is War and Peace in my library?


No book titled "War and Peace" is in your library. Closest titles: Pride and Prejudice.

> quote provenance: catalog: 0 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k05-by-author (catalog, 0 steps, 1s, $0.0024, 1 calls, 624 in / 34 out tokens) — PASS: titles 3/3, catalog by_author: 3 of 33, stop: catalog: answered from the index tables, no search

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have by Jules Verne?


3 book(s) by Jules Verne in your library:
- A Journey to the Interior of the Earth — Jules Verne
- Around the World in Eighty Days — Jules Verne
- Twenty Thousand Leagues Under the Sea — Jules Verne

> quote provenance: catalog: 3 of 33 books listed by code from the index tables (exhaustive; no quotes to check)

## k06-count-ua (catalog, 0 steps, 1s, $0.0022, 1 calls, 632 in / 23 out tokens) — PASS: titles 33/33, catalog count: 33 of 33, stop: catalog: answered from the index tables, no search

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

## k08-about-whaling (answer, 2 steps, 22s, $0.0456, 6 calls, 10636 in / 912 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What do I have about whaling?

- reflect -> whale hunting ships crews
- reflect -> stop: enough evidence

Based on the evidence available, you have one book related to whaling:

**Moby Dick by Herman Melville**

This novel is deeply connected to the subject of whaling in multiple ways:

- The story follows Ishmael, a sailor who boards the whaling ship Pequod out of Nantucket, where Captain Ahab pursues a monomaniacal quest for revenge against Moby Dick, the white sperm whale that took his leg. [Moby Dick, Summary]

- Beyond the narrative, Melville intersperses the story with detailed, encyclopedic chapters on whale biology and the whaling industry. [Moby Dick, Key Takeaways]

- Specifically, numerous chapters cover whale anatomy, classification, and the practical work of whaling, including the chase, the kill, and the trying-out of blubber. [Moby Dick, Plot]

So Moby Dick serves both as a dramatic story and as a substantial reference on 19th-century whaling practices and whale biology.

> quote provenance: OK: all 6 quotes found verbatim in the passages they cite

## k09-mention-london (answer, 3 steps, 39s, $0.0735, 8 calls, 15232 in / 1855 out tokens) — PASS: titles 0/0, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which of my books mention London?

- reflect -> London city England
- reflect -> London setting
- reflect -> stop: enough evidence

Based on the evidence provided, the following books mention London:

- **The War of the Worlds** (H. G. Wells) — London features heavily throughout, including the panicked evacuation of the city, its chaotic exodus, and the Martians advancing toward and destroying areas around it. [The War of the Worlds, Plot; The War of the Worlds, Summary; The War of the Worlds, XIV. IN LONDON.]

- **The Adventures of Sherlock Holmes** (Arthur Conan Doyle) — Victorian London's underworld and class contrasts are a central theme, with cases moving between grand households and criminal back streets. [The Adventures of Sherlock Holmes, Themes]

- **Around the World in Eighty Days** (Jules Verne) — Phileas Fogg is described as a wealthy London gentleman who begins his wager at London's Reform Club. [Around the World in Eighty Days, Characters; Around the World in Eighty Days, Plot; Around the World in Eighty Days, Summary]

- **The Three Musketeers** (Alexandre Dumas) — London is mentioned explicitly when D'Artagnan declares "To London, gentlemen." [The Three Musketeers, Chapter XIX]

- **Dracula** (Bram Stoker) — The London Directory is referenced among books found in Dracula's castle. [Dracula, Chapter II]

Note: The evidence for **A Study in Scarlet** does not mention London, so it cannot be confirmed from the available data.

> quote provenance: OK: all 14 quotes found verbatim in the passages they cite

## k10-hybrid-named-book (answer, 1 steps, 9s, $0.0208, 4 calls, 5613 in / 264 out tokens) — PASS: titles 1/1, named book -> retrieval filter Dracula — Bram Stoker (expected), stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Do I have Dracula, and why does Jonathan Harker stay at the castle?

- reflect -> stop: enough evidence

Yes, you have Dracula in your evidence.

According to the summary, Jonathan Harker stays at the castle because he traveled to Transylvania to complete a property sale for Count Dracula [Dracula, Summary]. However, he ends up being held there against his will, as his host turns out to be a vampire who keeps him prisoner [Dracula, Summary].

> quote provenance: OK: all 1 quotes found verbatim in the passages they cite

---
10 completed, 0 errors, 0 clarify interrupts; quotes verified 22/22 (confirmed / unattributed / broken = 22 / 0 / 0); evidence items 22
behavior PASS 10/10 (answer 4/4, catalog 6/6); expected titles mentioned 106/106
cost $0.1749 total, $0.0175 mean per attempted question (28 LLM calls, 41178 in / 3433 out tokens; configured rates $3.0/M in, $15.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above
