# Architecture decision records

An ADR here records one decision that shaped the system: what was decided, what it replaced, and
what it was measured to buy. They were written from the code rather than ahead of it, so they
describe the system as built; where a variant was tried and dropped, the rejected variant is part
of the record, because it is usually the more useful half.

Sixteen decisions, in the order they were taken. ADR-016 is written out as a file of its own
because it changed the planner's contract and added a node to the graph; the rest are summarised
here. The measurements are not repeated in full: the reports under [`docs/eval-results/`][reports]
are the primary record, and each entry below names the one that carries its numbers. Reports of
intermediate development runs were not exported with this repository; where a decision was measured
only by such a run, the entry says so.

## ADR-001: LangGraph StateGraph with an explicit bounded loop

Status: accepted (July 2026, confirmed on 2026-09-05).

One `StateGraph` with seven nodes and two routers (the catalogue node of ADR-016 later made it
eight); the state is a `TypedDict` in which `hits_log` grows through an append reducer; a
`MemorySaver` checkpointer holds it, `interrupt()` carries the clarify pause, and every question
runs under its own thread id, deleted when the run ends. The alternatives were a hand-rolled loop
over the model SDK, which has no interrupt or resume without custom state plumbing, and a role
framework of the CrewAI or AutoGen kind, which hides the control flow this project exists to show.

The graph is therefore the architecture diagram — the one the README draws — the eval harness
drives the same graph, and clarify is one node rather than a mode. The price is state discipline:
every node returns only its deltas, and the reducer on `hits_log` became necessary the moment the
passages themselves moved into state. A persistent checkpointer is worth adding only if resuming a
question across processes ever becomes a requirement.

## ADR-002: Two corpora — book cards and chapter-aware transcripts — in one LanceDB

Status: accepted.

`cards_<backend>` holds a distilled card per book (summary, plot, characters, themes, takeaways,
generated once per book and grounded by a CI test on titles); `transcripts_<backend>` holds
chapter-aware chunks of the text, target 4,000 characters with 400 of overlap, keyed
`<book>/<section>/<n>` with part-aware section names. Both tables carry an `index_meta` fingerprint
that is checked when they are opened. The alternative was one corpus of raw chunks, which answers
"which book was it" badly: an identify question needs a whole-book summary, a detail question needs
the text.

Identify mode works from the cards and detail mode from the text, and the two kinds of evidence
stay distinguishable by their `corpus` field. The ablation later measured each corpus on its own
(ADR-014). Cards are an AI-generated secondary source, and the interfaces still do not label
evidence by source type — an open item in [`docs/backlog.md`][backlog].

## ADR-003: Hybrid retrieval with hand-written RRF, no reranker

Status: accepted.

`library.search` runs a vector search (bge-m3 through Ollama, 1024 dimensions) and a BM25/FTS
search, twenty candidates each, and fuses the two lists with Reciprocal Rank Fusion written out in
`library.py` (`RRF_K = 60`); `search_both` gives the agent four card and four transcript hits per
step, and a broken FTS index degrades to vector-only with a warning. LanceDB's built-in hybrid
reranker was less code but ties the scoring to the library's API; a cross-encoder reranker was left
out because nothing had measured ranking as the weak link.

Fed the raw golden question, the retriever window holds the expected book in 9/9 core and 12/12
extended single-book questions, with multi-book coverage 2/2 core and 3/5 extended; the numbers are
unchanged at `v0.2.0-rc1` apart from the question the reader removed
([`2026-09-07-v0.2.0-rc1-retrieval-canary.md`][rc1-retrieval]). The known misses are in what the
agent queries and in what it sees of a hit, not in the ranking, which is why no reranker was added.

## ADR-004: Quote provenance checked in code against the passage the quote was pinned to

Status: accepted (rewritten in the release pass of 2026-09-05).

`act` gives every retrieved passage a stable id (`s<step>h<n>`) and stores it in `state.hits_log`
exactly as `observe` will see it; `observe` must name the id a quote was copied from; the book and
section on an evidence item are taken from that passage's record, never from the model; `validate`
requires the whole quote, normalized, to be a contiguous whole-token run inside one segment of the
cited passage, and partitions the checked evidence into confirmed, unattributed and broken. Until
this decision the badge came from substring-matching a Markdown scratchpad — a parser and its data
sharing one text stream, where a fabricated short sentence, a wrong section or service text from
the log could all confirm. An LLM judge was the other candidate and was rejected:
non-deterministic, priced per call, and it grades prose rather than provenance.

The badge now means what it says, and so do the eval totals: 46 confirmed / 0 unattributed / 0
broken on the v0.1.0 core run ([`2026-09-05-v0.1.0-core.md`][v010-core]) and 47/0/0 on `v0.2.0-rc1`
([`2026-09-07-v0.2.0-rc1-core.md`][rc1-core]), with no evidence lost to strict hit-id mode. The
guarantee is narrow, and the README states it as such: this is the provenance of the evidence, not
the correctness of the answer.

## ADR-005: `observe` sees a fixed budget of each hit; the rest of the loop sees only evidence

Status: accepted; the size of the budget was revised by ADR-012.

Raw hits never reach `plan`, `reflect` or `synthesize`. `observe` receives one `<result>` block
per hit, carrying that hit's id, book and section, with the text cut to `SEARCH_HIT_CHARS`
(`CHAPTER_HIT_CHARS` for a chapter read), and returns quotes with a `why`; `reflect` decides on
book / section / why lines. The alternative, passing the retrieved text down the loop, pays input
tokens at every node and widens the surface an injected instruction can reach.

What this buys is cost control, the pinning of ADR-004, and an injection blast radius that stops at
`observe`. The cut is also the mechanism behind two published failures: at 1,200 characters c03
named only one of the two women its question asks about, which ADR-012 fixed, while c06's answering
passage is not in the window at any size — a retrieval problem, traced in
[`docs/examples/c06-fogg-missing-day.md`][c06-trace]. That `reflect` decides on a thin summary,
with no quotes and no candidate set, is the mechanism behind "identify rarely clarifies", which
ADR-013 addressed.

## ADR-006: Clarify as an interrupt with a candidate list and a code resolver

Status: accepted; extended by ADR-013, which limits retrieval to the chosen book.

`reflect` may ask once per run; the question carries a numbered list of at most five candidates
(the books in the evidence first, then every book in `hits_log`); the reply is resolved in code —
full key, whole-word title, ordinal in English or Ukrainian, negations ignored, longest title
wins — to exactly one book key or to nothing; the key reaches the planner as the reader's choice,
evidence for rejected books is dropped, and an unrecognized reply keeps everything and says so.
Letting a model read the reply was the alternative; the transport, the list and the resolver are
deterministic and unit-tested instead.

The clarify interrupt is one of the two things the ablation credits the loop with (ADR-014). Its
weakness is upstream: a candidate the retriever never returned cannot be offered. The eval's
`--clarify-pick second` mode measures whether the choice is honoured, and on `v0.2.0-rc1` it
reports `applied` on both clarify items, with the answer drawn from the chosen book
([`2026-09-07-v0.2.0-rc1-core.md`][rc1-core]).

## ADR-007: Chapter drill-down with an honest read status

Status: accepted.

`reflect` may ask to read one chapter; `get_chapter` resolves the book by its exact index key and
then, for a bare title, by a query narrowed to keys containing it, joins the chunks in order and
cuts at `CHAPTER_HIT_CHARS` with an in-band marker; `read_chapters` entries carry a status —
complete, partial or empty — an empty read produces no hit at all, and a second request for the
same chapter stops the loop. The alternative, counting any attempt as a read, let the loop believe
it had read a chapter that was not in the index, and let the prompts say "read" where "attempted"
was the truth.

The detail question about the windmills is answered from the chapter in the tagged runs, and both
interfaces show the real stop reason. There is no continuation cursor, so a chapter longer than the
budget is read once and cut. The book travels in the database filter as an expression rather than
being resolved in Python afterwards, and a bare title shared by two authors is refused as ambiguous
instead of settled by row order; the 1,000-row cap and the missing scalar index on `book` and
`section` are open items in [`docs/backlog.md`][backlog].

## ADR-008: Injection defence in layers, stated exactly

Status: accepted.

Rules live in the system message and data in the user message, wrapped in XML-like blocks with
every untrusted `<` neutralized; `sanitize_context` redacts a small English/Ukrainian set of
instruction patterns and counts the redactions as telemetry; the agent holds no mutating tool; the
web UI escapes HTML and removes image references; a canary reports BLOCKED, CONTAINED or FAILED.
The option not taken was to present the delimiters as a security boundary — nothing enforces them,
and the README says so in as many words.

An injection can steer evidence selection, the reflect decision, the clarify question and the
answer; what it cannot do is forge a source, because provenance is checked against the stored
passage (ADR-004). The canary's deterministic stages run for free in CI, and its single live call
is reported with the tagged runs ([`2026-09-07-v0.2.0-rc1-retrieval-canary.md`][rc1-retrieval]).
Coverage is one injection, not a suite, and live resistance is measured for `observe` only.

## ADR-009: One runner, three interfaces, events as the contract

Status: accepted, with a correction recorded on 2026-09-07.

`runner.run_question(...)` is the execution path of the CLI and the web UI: it emits events and
calls back for a clarify reply, and per-question metrics accumulate in a `ContextVar` that is reset
per question, so concurrent web sessions do not mix their numbers. The correction: the eval harness
shares the initial state but drives the graph with its own loop, so it is not on the runner. Moving
it there, or extracting a shared result contract, is an open technical item and was not treated as
a release blocker.

One behaviour in every interface, and UI features cost nothing in the agent. The weak spot was that
the event contract lived in a docstring and drifted twice in one week; it is pinned by tests now —
a fake graph for the events, and fifteen end-to-end scenarios of the compiled graph driven by a
scripted model.

## ADR-010: Evaluation as a first-class deliverable, correctness kept separate

Status: accepted.

Two golden sets — a reader-verified core (twelve questions until 2026-09-06, eleven since) and an
exploratory extended set of twenty-one — and three harnesses: retrieval without a model call, agent
behaviour with a heuristic scorer, and the injection canary. Every report carries a run fingerprint
(the code revision with a dirty marker, the golden and manifest checksums, the model, the index
rows and build time, the strict and pick modes), a release run must be made on a clean tree
(`--require-clean`), and the artifacts are committed. The alternative, a single headline score, was
rejected in favour of three rows that cannot be confused: behavioural compliance, human-reviewed
correctness, and quote provenance.

Every number is therefore attributable to a run, and the published failure is the strongest
artifact in the repository ([`docs/examples/c06-fogg-missing-day.md`][c06-trace]). The costs are
recorded as honestly: runs are single, the hosted model varies, and the scorer is heuristic — an
LLM judge stays out until human verdicts exist. A catalogue set of ten questions joined the two in
September (ADR-016).

## ADR-011: Publishing by allowlist into a fresh repository, fail-closed tooling

Status: accepted.

The development repository stays the source of truth, and the public tree is produced from an
explicit file allowlist by an export tool that refuses to run on anything it does not recognise: an
output directory without its own marker, a symlinked output or one inside a repository or a home
directory, an allowlisted path that is missing, a missing secret scanner. That tool is private and
is not part of this repository; the README's "Where the measured code lives" says what it does and
how this tree relates to the measured one. The alternative, publishing the development repository
with its history rewritten, would have left every intermediate artifact and every private note one
`git log` away.

The export is a command plus a manual push, and it was verified on a dry run before anything was
made public. The price, decided with the approach, is that later public updates are snapshots
rather than history.

## ADR-012: Widen what `observe` sees — 1,200 to 2,500 characters per search hit

Status: accepted (measured and merged on 2026-09-06).

`SEARCH_HIT_CHARS` becomes a configuration knob and its default rises from 1,200 to 2,500
characters. Measured on the core set at 1,200 / 2,500 / 4,000, one run each: behaviour 12/12 and
provenance clean at 1,200 and 2,500, mean cost per question +9% at 2,500 and +32% at 4,000, where
behaviour also lost a question to a scorer artefact. The alternative that stayed unbuilt was a
window centred on the matching span instead of the head of the chunk, which needs the hit offsets
from both retrievers; at +9% for the simple constant it was not worth the machinery.

Against the acceptance the decision was written with: c03 names both Madame Coquenard and Madame de
Chevreuse from 2,500 characters up — met; c06 is not a window problem, its answering passage is in
no window at any size, and it moved to the coverage and drill-down track — not met. The three
window runs stay in the development history and are not among the exported reports; what the change
does is visible in the tagged pair, [`2026-09-05-v0.1.0-core.md`][v010-core] at 1,200 characters
and [`2026-09-07-v0.2.0-rc1-core.md`][rc1-core] at 2,500, where it is measured together with
ADR-013.

## ADR-013: A book filter after clarify and a deterministic coverage gate

Status: accepted in its second variant (2026-09-06); the first variant was measured and rejected.

`library.search` takes a `book` filter, so that after a resolved clarify the retrieval itself is
limited to the chosen book, and `reflect` spends one extra search before it may stop with evidence
for at most one book: in identify mode the planner's next queued query, in answer mode a look
inside a second book the question names. The gate is spent after any clarify. The first variant
probed the most-hit book of the window that the evidence had never touched; measured, it fired four
times and picked a noise book every time, for a structural reason — a book the window never held
cannot be offered by anything derived from the window. Prompt-only tuning had already been measured
with no effect.

Against the acceptance: c09 and h22 offer the right second candidate and honour the reader's
choice — met; q06 still never asks, and the other side of h17 is retrieved by no query at all —
not met, and both stay in [`docs/backlog.md`][backlog]. The gate costs a step where it fires:
+24% per core question and +21% per extended question over the 2,500-character baseline in the
runs of 2026-09-06, and, measured together with ADR-012 on the `v0.2.0-rc1` tag, +39% per core
question and +57% per extended question against v0.1.0
([`2026-09-07-v0.2.0-rc1-core.md`][rc1-core], [`2026-09-07-v0.2.0-rc1-extended.md`][rc1-extended]).
The four runs that measured the gate on its own stay in the development history.

## ADR-014: A small ablation on the core set

Status: accepted (measured on 2026-09-05, the harness merged on 2026-09-06).

Run the twelve core questions under five conditions — the model with no library at all, one
retrieval followed by one answer, the loop restricted to cards, the loop restricted to transcripts,
and the shipped loop — once each, scored by the unchanged agent-eval harness, and publish one
table. The guard written into the decision was to keep it that comparison and not let it grow into
a matrix over every question and every knob.

The result is the most uncomfortable number in the project: on answer content the full loop is not
better than the model's own memory for these twelve famous classics — 9 correct / 1 incorrect / 2
incomplete in both conditions — while behavioural compliance goes from 6/12 to 12/12, the refusal
holds where the memory condition narrates a book the library does not have, and the clarify
interrupt exists only in the loop, at roughly 6.8 times the cost of answering from memory.
Provenance comes from the extraction-and-validation contract, which this run did not separate from
the loop. The consequence for how the project describes itself is in the README: grounded, refuses,
verifiable — not more correct. Full table and per-question reading:
[`2026-09-05-ablation-core.md`][ablation].

## ADR-015: Generic local ingest — `ayl-add <folder>`

Status: accepted (2026-09-06, with two rounds of fixes).

A folder of `.txt` / `.md` files becomes a queryable index without editing Python: the book key
from front matter, a standalone first title line or the file name; chapters from Markdown headings
or the prose heuristic; then the demo pipeline's own chunking, embedding, staged publish, FTS
rebuild and index stamp, so a private library is indexed exactly like the demo corpus. The
alternative was to document the table contract and leave the ingest to the reader, which would have
left "your own library" a claim the repository did not support.

Acceptance was met on a smoke test: two files, local embeddings, one paid question answered with
its quotes confirmed. The review rounds are the more useful part of the record — symlinks are never
followed, a table with no fingerprint is refused rather than stamped after the fact, a row key
carries a digest of the book key so two titles that reduce to the same ASCII slug stay two books,
an update is a staged rebuild with a single publish, and a missing cards table became a supported
shape with a visible notice instead of a silent degradation. A later audit closed two more defects
in the splitter: duplicate section names, and short real chapters and the text before the first
heading disappearing without a word. One limitation is documented rather than fixed — a `CHAPTER I`
that repeats across volumes in one file is read as a contents line and merged into the section
above it, reported, never lost.

## ADR-016: The catalogue path — what the library holds is answered by code

Status: accepted (2026-09-08). Written out in full in [`016-catalog-path.md`](016-catalog-path.md).

`plan` gains a third mode in which it only names an operation (`count`, `list`, `has` a title,
`by_author`); code reads the distinct book keys of the index tables, validates the operation,
resolves a title or an author against that list and formats the answer, so the number in an answer
is the length of the list under it and nothing can be listed that is not in the index. The question
that forced the decision was the owner's first question to the web UI: fourteen titles under a
heading that said seventeen, of thirty-three, after four searches and ten model calls, with every
"quote" confirmed — a green badge over an incomplete answer. A prompt-only fix leaves the count
with the model; a regex router before the model is brittle across two languages and follow-ups.

Catalogue questions now cost one model call and no search step, and the answer is exhaustive by
construction for what the index holds. The catalogue set scores 10/10, its six catalogue items
costing $0.014 together ([`2026-09-09-catalogue-set.md`][catalogue-set]), and a core run on the
same commit leaves the research loop where it was: 11/11 behaviour, 48/0/0 quotes, $0.0519 mean per
question against $0.0488 on `v0.2.0-rc1` ([`2026-09-09-catalogue-branch-core.md`][catalogue-core]).
Exhaustive content questions ("which of my books mention London?") are explicitly not covered by
this path and stay best-effort in the research loop.

[reports]: ../eval-results/
[backlog]: ../backlog.md
[c06-trace]: ../examples/c06-fogg-missing-day.md
[v010-core]: ../eval-results/2026-09-05-v0.1.0-core.md
[ablation]: ../eval-results/2026-09-05-ablation-core.md
[rc1-core]: ../eval-results/2026-09-07-v0.2.0-rc1-core.md
[rc1-extended]: ../eval-results/2026-09-07-v0.2.0-rc1-extended.md
[rc1-retrieval]: ../eval-results/2026-09-07-v0.2.0-rc1-retrieval-canary.md
[catalogue-set]: ../eval-results/2026-09-09-catalogue-set.md
[catalogue-core]: ../eval-results/2026-09-09-catalogue-branch-core.md
