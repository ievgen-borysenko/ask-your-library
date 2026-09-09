> **Provenance of this artifact.** The core set (`eval/golden/en-demo.yaml`, 11 questions) run once on `50b9347` on
> 2026-09-09, the final commit of the catalogue branch (ADR-016) with `main` merged in, with the default hosted planner,
> strict hit-id, the bge-m3 demo index of 04.09: **behaviour 11/11 (answer 7/7, identify 2/2, refusal 1/1, aggregation
> 1/1); quote provenance 48 / 0 / 0 confirmed / unattributed / broken; $0.5711 for the set, $0.0519 mean per question
> (73 model calls)**, one clarify interrupt (c09, the reply unresolved by design of the auto-answer). Against the
> `v0.2.0-rc1` run of 07.09 on `33dba3f` (11/11, 47/0/0, $0.0488 mean, 70 calls) the behaviour and the provenance are
> unchanged and the cost is 6% higher; what differs is the path: the three questions that name one book (c04, c05, c06)
> now run with retrieval limited to that book by the catalogue resolver, and the refusal item (c08) carries the note
> that the named book is not in the catalogue. The report below is the harness output copied verbatim from
> `answers-1788956783.md`; nothing was recomputed; the manual correctness column is unticked (a single run, not a
> reader's verdict).

# Agent eval — 2026-09-09 14:26 — en-demo.yaml

run: code 50b9347 | golden en-demo.yaml@f041a0290000 | manifest@f093bb27dab1 | toc@ef7a347ace1d | model anthropic/claude-sonnet-4.6 | cards_ollama=bge-m3/1024d rows=165 v2 built=2026-09-04T22:23:01 | transcripts_ollama=bge-m3/1024d rows=7285 v2 built=2026-09-04T23:54:31 | strict_hit_id=on | clarify_pick=default | hit_chars=2500/12000 | steps=4/2 | candidates=5 | deadline=300s | single run

## c01-ivanhoe-disguised-knight (identify, 2 steps, 22s, $0.0457, 6 calls, 11291 in / 790 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What was that novel where a knight returns to England in disguise, his father has rejected him, and there is all this conflict between Saxons and Normans while King Richard is returning?

- reflect -> King Richard returning England medieval novel
- reflect -> stop: enough evidence

The novel you are thinking of is **Ivanhoe** (1819) by Walter Scott.

It matches all the details you mentioned:

- The protagonist, Wilfred of Ivanhoe, is a Saxon knight who was disinherited by his father Cedric for supporting the Norman King Richard [Ivanhoe, Plot].
- He returns secretly from the Crusades in disguise, specifically as a pilgrim [Ivanhoe, Plot].
- The story is set against the backdrop of tension between Saxon and Norman nobility in 12th-century England [Ivanhoe, Summary].
- King Richard the Lionheart is returning and eventually reasserts his throne, with Cedric ultimately reconciling with his son [Ivanhoe, Plot].

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c02-huck-go-to-hell (answer, 1 steps, 15s, $0.0258, 4 calls, 5749 in / 567 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Huck say, "All right, then, I'll go to hell"? What has he decided to do?

- reflect -> stop: enough evidence

Based on the evidence provided, Huck says "All right, then, I'll go to hell" at the moral climax of the novel [Adventures of Huckleberry Finn, Summary]. He has been deeply torn about helping Jim escape slavery, because by the standards of his era, helping an enslaved person escape was considered morally and legally wrong [Adventures of Huckleberry Finn, Summary].

The specific decision he makes is to tear up a letter that would have exposed Jim's whereabouts — essentially destroying the evidence that would have led to Jim being recaptured [Adventures of Huckleberry Finn, Plot]. Despite his conscience telling him that helping Jim is sinful by the era's norms, Huck chooses loyalty to his friend over the social and religious codes he has been taught, accepting what he believes will be his own damnation rather than betray Jim [Adventures of Huckleberry Finn, Summary].

In short, Huck decides to help free Jim, prioritizing his personal bond and sense of human decency over the corrupt moral framework of the slave-holding society around him.

> quote provenance: OK: all 2 quotes found verbatim in the passages they cite

## c03-musketeers-women (answer, 4 steps, 31s, $0.0823, 10 calls, 21446 in / 1199 out tokens) — PASS: titles 1/1, stop: step limit (4) — wanted to keep searching

- [ ] manual correctness (facts match the golden notes?)

**Question:** I remember that Constance Bonacieux was d'Artagnan's love and that Milady had been Athos's wife. But who were the women connected with Porthos and Aramis?

- reflect -> Aramis woman mistress love interest
- reflect -> __chapter__|The Three Musketeers — Alexandre Dumas|Chapter XXV.
- reflect -> Aramis woman love interest Three Musketeers
- reflect -> stop: step limit (4) — wanted to keep searching

Based on the evidence provided:

**Porthos** was connected with Madame Coquenard, described as "the old wife of a procurator of the Châtelet" who was "at least fifty" years old [The Three Musketeers, Chapter XXV].

**Aramis** is a more complicated case. The evidence shows he was described as "a young fellow made up of mysteries" with rumored romantic success, but his specific love interest is not clearly named in the provided evidence [The Three Musketeers, Chapter VII]. There is a passing mention of Madame d'Aiguillon and Madame de Chevreuse in connection with Aramis, but only in the context of errands and favors, not as a clear romantic attachment [The Three Musketeers, Chapter VII].

To be honest, the evidence provided here does not fully answer the question regarding Aramis's primary love interest. A more complete answer about her identity would require additional passages from the novel beyond what has been supplied here.

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

## c04-crusoe-cannibals (answer, 2 steps, 31s, $0.0529, 6 calls, 10339 in / 1462 out tokens) — PASS: titles 1/1, named book -> retrieval filter Robinson Crusoe — Daniel Defoe, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** What did Crusoe do when he first discovered that cannibals were visiting the island? Did he attack them immediately?

- reflect -> __chapter__|Robinson Crusoe — Daniel Defoe|CHAPTER XII. A CAVE RETREAT
- reflect -> stop: enough evidence

When Crusoe first discovered the evidence of cannibals visiting the island, he did not attack them immediately. His initial reaction was one of overwhelming horror and physical revulsion. According to the evidence, he was so astonished by the sight that he "entertained no notions of any danger to myself from it for a long while," turned away from the scene, became physically sick, and actually vomited "with uncommon violence." He then fled the area as quickly as he could and returned to his habitation [Robinson Crusoe, Chapter XII].

Far from attacking them, his response was to withdraw and conceal himself. He reasoned that the cannibals did not come to the island looking for anything in particular, and that if he simply did not reveal himself, he could remain hidden for many more years, just as he had already gone eighteen years without being discovered [Robinson Crusoe, Chapter XII].

In fact, he became deeply fearful of any encounter with them, describing his aversion as so strong that he "was as fearful of seeing them as of seeing the devil himself." He then kept strictly within his own small circuit of habitation for almost two years after this discovery [Robinson Crusoe, Chapter XII].

So his immediate and sustained response was one of horror, retreat, and deliberate concealment, not attack.

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c05-quixote-windmills (answer, 2 steps, 30s, $0.0488, 6 calls, 10342 in / 1183 out tokens) — PASS: titles 1/1, named book -> retrieval filter Don Quixote — Miguel de Cervantes, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Don Quixote attack the windmills even after Sancho tells him what they are, and how does he explain what happened after they knock him down?

- reflect -> __chapter__|Don Quixote|CHAPTER VIII.
- reflect -> stop: enough evidence

## Don Quixote and the Windmills

**Why he attacks despite Sancho's warning**

When Sancho points out that the objects are windmills, Don Quixote flatly dismisses his squire's perception, telling him: "It is easy to see that thou art not used to this business of adventures; those are giants; and if thou art afraid, away with thee out of this and betake thyself to prayer while I engage them in fierce and unequal combat." [Don Quixote, Chapter VIII] His conviction is so absolute that he neither hears Sancho's cries nor recognizes what the windmills are even as he draws close to them, charging at them while shouting at them not to flee. [Don Quixote, Chapter VIII]

**His explanation after being knocked down**

Rather than accepting that he was simply wrong, Don Quixote attributes the defeat to the malicious sorcery of an enemy. He tells Sancho: "I think, and it is the truth, that that same sage Friston who carried off my study and books, has turned these giants into mills in order to rob me of the glory of vanquishing them, such is the enmity he bears me; but in the end his wicked arts will avail but little against my good sword." [Don Quixote, Chapter VIII]

In short, his delusion is self-sealing: the windmills were giants, and if they now appear as windmills, that is only proof of a wizard's interference, not of his own error.

> quote provenance: OK: all 4 quotes found verbatim in the passages they cite

## c06-fogg-missing-day (answer, 2 steps, 26s, $0.0445, 6 calls, 8885 in / 1192 out tokens) — PASS: titles 1/1, named book -> retrieval filter Around the World in Eighty Days — Jules Verne, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why did Phileas Fogg think he had lost the wager after reaching London, and how did he discover that he had actually won?

- reflect -> __chapter__|Around the World in Eighty Days — Jules Verne|CHAPTER XXXVII.
- reflect -> stop: enough evidence

## Phileas Fogg's Mistaken Belief and His Discovery

**Why He Thought He Had Lost**

After completing his journey and returning to London, Phileas Fogg believed he had arrived a day too late to win his wager. He had been carefully tracking the days of his travels but was convinced he had failed to meet the eighty-day deadline.

**The Actual Error**

The reason for his miscalculation is explained clearly: Fogg had, without suspecting it, gained one day on his journey simply because he had travelled constantly *eastward*. As the evidence states, "he would, on the contrary, have lost a day had he gone in the opposite direction, that is, *westward*" [Around the World in Eighty Days, Chapter XXXVII]. By travelling eastward around the globe, he had effectively gained twenty-four hours without realizing it.

**How He Discovered the Truth**

The discovery came through a chain of fortunate events. It was Passepartout who urgently alerted him to the mistake, crying out: "You have made a mistake of one day! We arrived twenty-four hours ahead of time; but there are only ten minutes left!" [Chapter XXXVII]. This left Fogg just barely enough time to act.

Fogg himself later acknowledged that the discovery was only possible because of his companion Aouda's suggestion that they marry, which sent Passepartout to the Reverend Samuel Wilson's — and it was during that errand that the error came to light. As Fogg told Aouda: "If you had not suggested our marriage, my servant would not have gone to the Reverend Samuel Wilson's, I should not have been apprised of my error" [Chapter XXXVII].

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c07-alice-trial (answer, 4 steps, 27s, $0.0591, 10 calls, 15090 in / 921 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Why does Alice stop being afraid during the trial and finally challenge the Queen and the whole court?

- reflect -> __chapter__|Alice's Adventures in Wonderland — Lewis Carroll|Plot
- reflect -> Alice challenges the Queen and court
- reflect -> __chapter__|Alice's Adventures in Wonderland — Lewis Carroll|Chapter 12
- reflect -> stop: enough evidence

## Why Alice Stops Being Afraid at the Trial

The reason is straightforward and physical: Alice loses her fear because she has grown to an enormous size. As stated directly in the text, "she had grown so large in the last few minutes that she wasn't a bit afraid of interrupting him" [Alice's Adventures in Wonderland, Chapter 12]. Her growing physical stature directly corresponds to her growing confidence and boldness.

By the time she delivers her final challenge, "she had grown to her full size," at which point she confronts the entire court with the declaration: "Who cares for you? You're nothing but a pack of cards" [Alice's Adventures in Wonderland, Chapter 12].

In other words, it is not a gradual psychological overcoming of fear through courage or reasoning, but rather a literal, physical transformation that removes her sense of vulnerability. Once she is large enough to no longer feel threatened by the court, she is free to speak her mind and denounce the whole proceedings, which ultimately causes the trial to descend into chaos before she wakes from the dream [Alice's Adventures in Wonderland, Plot].

> quote provenance: OK: all 5 quotes found verbatim in the passages they cite

## c08-refusal-tom-sawyer (refusal, 2 steps, 8s, $0.0330, 4 calls, 9941 in / 210 out tokens) — PASS: titles 0/0, named book not in the catalogue: Tom Sawyer, stop: CRAG gate: 2 dry steps in a row

- [ ] manual correctness (facts match the golden notes?)

**Question:** How did Tom Sawyer make the other boys pay him for the chance to paint the fence?

- reflect -> Tom Sawyer whitewashing fence trick convincing others to work
- reflect -> stop: CRAG gate: 2 dry steps in a row

(No book titled "Tom Sawyer" is in the library catalogue; the whole library was searched instead.)

I searched both the book cards and the transcripts, but found no evidence for this question in the library. Honest answer: I don't know.

> quote provenance: no evidence — the answer itself is an honest refusal

## c09-shipwreck-first-person (identify, 4 steps, 55s, $0.0982, 11 calls, 21363 in / 2274 out tokens, clarify) — PASS: titles 2/2, clarify reply unresolved, stop: repeated clarify not allowed — finishing with what we have

- [ ] manual correctness (facts match the golden notes?)

**Question:** There was a book told entirely in the first person by a man who is shipwrecked and washes up somewhere completely unfamiliar. I can't remember whether it was mainly about surviving on his own or about getting along in a strange society. Which one was it? I might be mixing two of them up.

- reflect -> castaway washes ashore unfamiliar strange society first person narrative
- reflect -> shipwreck survivor adapting foreign unknown civilization first person novel
- reflect -> __clarify__
- clarify: You may be thinking of one or both of these books:

1. **Robinson Crusoe** by Daniel Defoe — first-person shipwreck narrative focused on solo survival on an uninhabited island.
2. **Gulliver's Travels** by Jonathan Swift — first-person narrative where the protagonist is repeatedly stranded in strange, unfamiliar societies.

Does either of these match what you're remembering, or could you be mixing up both?
Candidates in the library (answer with a number or a title):
1) Robinson Crusoe — Daniel Defoe
2) Gulliver's Travels — Jonathan Swift
3) The Secret Adversary — Agatha Christie
4) Moby Dick — Herman Melville
5) Frankenstein — Mary Shelley
- reflect -> stop: repeated clarify not allowed — finishing with what we have

The most likely candidate is Robinson Crusoe by Daniel Defoe.

Your description fits it on every point. It is told entirely in the first person, framed as the autobiography of Crusoe himself [Robinson Crusoe, Summary]. The protagonist is shipwrecked and washes ashore somewhere completely unfamiliar to him, specifically an uninhabited island near the Orinoco River [Robinson Crusoe, Plot]. The book is primarily about surviving alone: building shelter, farming, domesticating goats, and keeping a journal [Robinson Crusoe, Plot]. The inward, reflective first-person voice is very prominent, as seen in passages where Crusoe sits down to reason through his situation in writing [Robinson Crusoe, Chapter IV].

You may be mixing it up with Gulliver's Travels by Jonathan Swift, which also features a first-person narrator who ends up set ashore in unknown lands [Gulliver's Travels, Part IV, Chapter I]. However, Gulliver's Travels is mainly about navigating strange societies rather than solo survival, which matches the second possibility you mentioned. The two books are a natural pair to confuse because both use a first-person castaway-style premise, but Robinson Crusoe is the one dominated by solitary survival, while Gulliver's Travels is dominated by encounters with foreign civilizations.

The evidence does not include the full text of Gulliver's Travels, so I can only partially confirm the contrast, but the distinction above is well supported by what is provided.

> quote provenance: OK: all 8 quotes found verbatim in the passages they cite (1 pieces of evidence for books the answer does not name were checked too)

## c10-chivalry-two-books (aggregation, 1 steps, 21s, $0.0296, 4 calls, 5730 in / 827 out tokens) — PASS: titles 2/2, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** There are two books in my library about knights and chivalry. One seems to take the whole code of honour seriously and the other makes fun of it. Which is which, and how does each one treat the idea of being a knight?

- reflect -> stop: enough evidence

Based on the evidence provided:

**Ivanhoe** by Walter Scott treats knighthood seriously, or at least with genuine dramatic weight. The theme described as "chivalry and its limits" suggests a thoughtful, if not uncritical, engagement with the knightly code. The passage from Chapter XXIX shows a knight speaking with sincere passion about chivalric duty -- the love of battle, honour, and renown are presented as deeply felt obligations ("laws of chivalry to which we are sworn"), not as objects of ridicule. The tone is earnest, even if the book also tests those ideals against "real cruelty and prejudice."

**Don Quixote** by Miguel de Cervantes takes the opposite approach, using knighthood as the target of satire and comedy. The passage from Chapter XIII makes clear that the other characters regard Don Quixote's devotion to chivalric ideals as outright madness -- a "form of madness that overmastered him." The humour comes from a man taking the old knightly code with complete seriousness in a world that has moved on, making him appear absurd to everyone around him.

In short: Scott treats chivalry as a serious, if complicated, moral framework, while Cervantes mocks it by showing what a man looks like when he genuinely believes in it long after it has ceased to make sense.

I should note that the evidence here is limited to brief excerpts, so a fuller comparison of both books would require more text.

> quote provenance: OK: all 3 quotes found verbatim in the passages they cite

## h06-kobzar-mother-servant (answer, 2 steps, 30s, $0.0512, 6 calls, 10856 in / 1243 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** In a Ukrainian poem, a mother left her baby with some older couple and then came to work for them as a servant. What was the poem, and why did she do it?

- reflect -> Ukrainian poetry mother infant abandoned works as servant
- reflect -> stop: enough evidence

The poem is "Naimechka; or The Servant" by the Ukrainian poet Taras Shevchenko, from his collection The Kobzar of the Ukraine.

The mother, Hanna, was an unmarried woman who had given birth to a son, Mark. She left the infant with a childless couple and then returned to their household as a servant. Her motivation was rooted in shame and self-sacrifice: as an unmarried mother, she did not want to bind her child to poverty and to the social stigma of his illegitimate birth. As she says in the poem, she would not give him "his mother's shame" and resolved that she alone must "rue" her fault [The Kobzar of the Ukraine, NAIMECHKA OR THE SERVANT]. By placing him with the couple, she gave him a more respectable upbringing, while still remaining close enough to care for him as a servant -- the poem notes that "whatever befalls, she's the mother there" [The Kobzar of the Ukraine, NAIMECHKA OR THE SERVANT].

She maintained this secret her entire life, revealing that she was his mother only on her deathbed [The Kobzar of the Ukraine, Key Poems]. The poem is described as a central narrative tragedy of lifelong self-denial ending in a deathbed confession [The Kobzar of the Ukraine, Key Takeaways].

> quote provenance: OK: all 7 quotes found verbatim in the passages they cite

---
11 completed, 0 errors, 1 clarify interrupts; quotes verified 48/48 (confirmed / unattributed / broken = 48 / 0 / 0); evidence items 48
behavior PASS 11/11 (aggregation 1/1, answer 7/7, identify 2/2, refusal 1/1); expected titles mentioned 12/12
cost $0.5711 total, $0.0519 mean per attempted question (73 LLM calls, 131032 in / 11868 out tokens; configured rates $3.0/M in, $15.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above
