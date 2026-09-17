# Architecture decision records

An ADR here records one decision that shaped the system: what was decided, what it replaced, and
what it was measured to buy. They were written from the code rather than ahead of it, so they
describe the system as built; where a variant was tried and dropped, the rejected variant is part
of the record, because it is usually the more useful half.

Twenty-four decisions, in the order they were taken. ADR-016 is written out as a file of its own
because it changed the planner's contract and added a node to the graph; the rest are summarised
here. ADR-017 to ADR-023 were recorded on 2026-09-16, after the fact: a review of this tree found
seven decisions the code had made and no record named. The four that constrain what may be built
next are written out below; the other three are reserved as stubs — number, title, one sentence —
to be written when the code they describe is next touched, so that the numbering is taken and the
decision is not forgotten. The measurements are not repeated in full: the reports under
[`docs/eval-results/`][reports] are the primary record, and each entry below names the one that
carries its numbers. Reports of
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

The graph is therefore the architecture diagram — the one [`architecture.md`](../architecture.md)
draws — the eval harness
drives the same graph, and clarify is one node rather than a mode. The price is state discipline:
every node returns only its deltas, and the reducer on `hits_log` became necessary the moment the
passages themselves moved into state. A persistent checkpointer is worth adding only if resuming a
question across processes ever becomes a requirement.

## ADR-002: Two corpora — book cards and chapter-aware transcripts — in one LanceDB

Status: accepted.

`cards_<backend>` holds a distilled card per book (summary, plot, characters, themes, takeaways,
generated once per book and grounded by a CI test on titles); `transcripts_<backend>` holds
chapter-aware chunks of the text, target 4,000 characters with 400 of overlap, keyed by note,
section and chunk number, with part-aware section names. Both tables carry an `index_meta`
fingerprint that is checked the first time a table is opened in a process. The alternative was one
corpus of raw chunks, which answers
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

Fed the raw golden question, the retriever window holds the expected book in 9/9 single-book
questions of the twelve-question core with multi-book coverage 2/2 (8/8 at `v0.2.0-rc1`, where the
reader had removed one question and nothing else changed), and in 12/12 single-book questions of
the extended set with multi-book coverage 3/5
([`2026-09-07-v0.2.0-rc1-retrieval-canary.md`][rc1-retrieval]). The known misses are in what the
agent queries and in what it sees of a hit, not in the ranking, which is why no reranker was added.

## ADR-004: Quote provenance checked in code against the passage the quote was pinned to

Status: accepted (rewritten in the release pass of 2026-09-05; amended twice on 2026-09-16, see
below: the card split, then the move of the check to the evidence gate).

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
guarantee is narrow, and [`architecture.md`](../architecture.md) states it as such: this is the
provenance of the evidence, not
the correctness of the answer.

**Amended 2026-09-16: the triple is about the books' own text, and a book card is not the book.**
A retrieved passage is either a book's own text or a **book card** — a per-book summary written by
one model call at ingest time — and until this amendment `validate` treated the two alike, so a
quote copied verbatim out of a model's summary counted as `confirmed` and the badge said it was
traced to its source. That was ADR-002's recorded consequence ("interfaces still do not label
evidence by source type") showing up in the arithmetic rather than only in the labels.
`confirmed / unattributed / broken` now partition the retrieved **book text** alone; a quote whose
only verbatim match is a card is a fourth outcome, `card_only`, which is never counted as traced;
the denominator every interface and the eval harness show is `checked_book_text`
(= `checked - card_only`); and each evidence item carries `source_kind` ("book_text" / "card"), the
corpus of the passage it is pinned to, so the CLI, the web chat and the harness label evidence off
one record. A hit logged without a `corpus` is counted as book text — the conservative reading, the
only one that cannot invent a card — but is labelled with nothing, because that is what its record
says. **The totals quoted in the paragraph above, and every report under
[`../eval-results/`](../eval-results/), were produced before this amendment and count card matches
inside the triple.** They are correct for what they measured and are not comparable, quote for
quote, with a run made after it; nothing was re-run to change a published number
([`../evaluation.md`](../evaluation.md), [`../known-limits.md`](../known-limits.md)).

**Amended 2026-09-16 (second amendment of the day): the check runs at the evidence gate, before the
answer is written; the post-synthesis check stays as the report (#29).** Until this amendment
`validate` was the last node of the graph, so a quote in no retrieved passage reached the reader
inside the answer and was counted underneath it — a warning about a sentence the reader had already
read. The same check now runs inside `_valid_evidence`, at the `observe` gate, over the step's own
passages cut exactly as the prompt cut them: **confirmed** is kept, **card_only** is kept and stays
outside every traced count, **unattributed** is re-pinned to the passage that holds the quote (so
the citation stops naming the wrong one), and **broken** is dropped and never reaches `synthesize`.
Counters travel with the run — `dropped_unverified`, the same number split by the rule that refused
each quote (`dropped_by_reason`: `no_hit`, `cross_book`, `short`, `not_found`), and `repinned` —
through the `observe` event, `RunResult`, the provenance report, the badge, the CLI line and the
harness. **Every** refusal of a well-formed quote is in the headline number, whichever rule made it;
the breakdown sums to it and is telemetry under it, never an outcome beside it. One quote that did
not reach the answer is one quote that did not reach the answer.

**A re-pin may correct a citation; it may not write a new one.** Three limits, all because the book
on an evidence item is the book the ANSWER cites. A quote is re-pinned only inside the cited hit's
own book — and the search is ordered **book before corpus**: the cited passage, then that book's
other text, then that book's cards, and only then anything else, whose holders exist to classify a
drop and never to receive a re-pin. Corpus-before-book was the first version of this and it was
wrong twice over: it let a transcript of an unrelated work outrank the cited book's own card, so
valid same-book evidence was dropped as cross-book. A quote whose only holder really does belong to
another work IS dropped, counted in `dropped_unverified` under `cross_book`: moving it would replace
a wrong citation with a confident wrong one, which is worse than refusing it, and taking the first
holder in retrieval order did exactly that. The second limit is length: a quote that has to FIND its
passage must be at least `MIN_REPIN_TOKENS` (4) normalized words, because "the sea" or "he said" is
inside almost any book and a match that short is a coincidence, not a provenance. The third governs
`AYL_STRICT_HIT_ID=0`, where an item may carry no usable hit id at all: the model's own `book` field
is then the one thing narrowing the search, resolved canonically by `catalog.resolve_title` — the
resolver that answers "do I have X" — and the quote must sit in exactly one passage of exactly that
one retrieved book. A name matching nothing, a name matching two books and a quote two passages hold
are all citations nobody could write down, and are dropped rather than guessed at. A quote that is
in the passage it cited is measured against none of this; nothing is being invented there.

**The cited passage is read before the rest of the run, and that changed one verdict.** A quote
inside the book card it cites is `card_only`, even where a chapter also holds those words; before
#29 the book text was searched first and such an item came back `unattributed` — "not in the cited
passage, found in another" — about a quote that *is* in the passage it cites. It is now true, and it
is the only reading the two gates can share: the gate sees one step and `validate` sees the run, so
a card quote from step 1 whose words step 2 retrieves as book text would otherwise get one verdict
at the gate and another in the report. The cost is stated rather than hidden — where a chapter does
say it too, the count credits the card and not the book, which is the conservative direction and the
house rule for cards.

Measured 2026-09-17 on two local models, each run under the gate on `c79018a` and compared with the
same model's pre-gate run on `169b511`, both golden sets at `--repeat 3`
([`../eval-results/2026-09-16-local-models-repeat3.md`](../eval-results/2026-09-16-local-models-repeat3.md))
— **and the two do not agree, which is why the acceptance is recorded per model.** `qwen2.5:14b`
kept its behaviour item for item (9/11 and 10/10), `broken` went 2 → 0 with
`confirmed == checked_book_text` at 34/34 over the same 34 quotes, `dropped_unverified` was 2 per
attempt (`not_found` 2; `no_hit` / `cross_book` / `short` 0; `repinned` 0) from the two questions
that had carried the broken quotes, and the LLM calls (79) and the steps distribution did not move.
`mistral-small3.2:24b-ctx20k` went `broken` 8–9 → 0 with `confirmed == checked_book_text` at 50/50
and 10–11 dropped per attempt (`not_found` 26, `no_hit` 6 over three attempts), and **lost one
behavioural PASS on two attempts of three** — `c03` with `titles 0/1`, its surviving evidence
carrying no citation once a second quote was refused. `cross_book` and `short` fired on neither
model, so the conservative re-pin limits above cost nothing measured so far; the hold on a
fully-dropped step did cost 6 LLM calls and 502 s on that model, on two items that still pass.
`qwen2.5:32b` has not been run under the gate.

The two gates run **one** function over one index of the run's passages (`classify_quote`,
`passage_index`), and `validate`'s own classification was rewritten onto it. That is the decision,
not an implementation detail: a second reading of "is this quote inside that passage" is exactly how
the entry check and the badge would come to disagree about the same quote, and a report that can
disagree with the gate it reports on is worth less than either. The consequence is an invariant
rather than a hope — on evidence that went through the gate, `confirmed == checked_book_text` and
`broken == 0` **by construction** — so the published triple stops being a measurement of the model's
quoting honesty and becomes a proof that the gate held. What it still does not cover is unchanged
and stated in the same words as before: the quotations the ANSWER writes are not evidence and
nothing checks them. #29's second half — citation by evidence id, checked against the answer's
sentences — is not built.

The arithmetic costs one normalization pass per step instead of one per run, on a loop whose
cheapest node is about seven seconds, and no model call. The risk was never that: it was **control
flow**, and the system design review of 16.09 §3(a) is the only document that named it. A step whose
every item is dropped would have become a dry step, and two dry steps end a run at the CRAG gate —
#29 would have improved provenance by shortening the search. The owner's decision of the same day
settles it and the code implements it: "dropped" is counted apart and is never a dry step. Such a
step neither advances the empty streak (its passages *were* retrieved, so the library is not silent
on the question) nor resets it (it proved nothing about the library either); the loop goes on to the
next query, and `reflect` is told how many quotes were dropped, in a line added to its context only
when there is one to add. No new stop reason was needed, because a dropped step never ends the loop
by that rule; when the loop ends by another one the reason names that rule and the counters say what
the gate spent, the honest refusal included.

**What the hold decision really costs, said as a number.** A model that quotes badly is no longer
stopped after two steps. Where the CRAG gate used to end such a run at step 2, it now runs to
`MAX_STEPS` (4), and every extra step is a search plus an `observe` call plus a `reflect` call — on
the local default, roughly the difference between a question of five model calls and one of nine.
That is the price of not shortening the search, paid exactly by the runs that produce the least, and
it is the reason the acceptance below is about behaviour at repeat and not only about the quote
counts.

**A second coupling, not decided here: the coverage gate (ADR-013).** `coverage._uncovered_books` is
the hits of the run minus the books the *evidence* names, so evidence the gate thinned makes a book
look uncovered and the one probe of a run fires where it would not have before. That is arguably
right — a book whose only quotes were dropped genuinely is not covered — and it costs a step from
the same budget the paragraph above already stretches. No code changed for it. It was to be reported
as the coverage-probe firing count beside the baseline's, and **that turned out not to be
measurable**: the probe has no counter in the sidecar and leaves no marker in `steps_log`, so neither
the baseline nor either gate run says how often it fired. Recording it is in `../backlog.md`.

**Measured 2026-09-17, per model** (`../eval-results/2026-09-16-local-models-repeat3.md`; each model
run under the gate on `c79018a` against its own pre-gate run on `169b511`, both golden sets at
`--repeat 3`). Conditions 1 and 2 — a confirmed ratio of 1.0 by construction on evidence, and a
published drop rate with its breakdown by reason and the re-pin count — are met on both models.
Condition 3, behaviour at `--repeat` not below the baseline, is **met on `qwen2.5:14b`** (9/11 and
10/10, item for item, with the same steps and calls) and **not met on
`mistral-small3.2:24b-ctx20k`**, which goes 11/11 → 10/11 on two attempts of three: `c03` with
`titles 0/1`, its surviving evidence carrying no citation once a second quote is refused. The
options are listed in `../backlog.md` and none is adopted here.

**Still unmeasured:** the coverage-probe firing count (no counter to read), `qwen2.5:32b` under the
gate, and every hosted model under it.

## ADR-005: `observe` sees a fixed budget of each hit; the rest of the loop sees only evidence

Status: accepted; the size of the budget was revised by ADR-012, and 2026-09-16 added one number to
what `reflect` sees (see below). The budget itself is unchanged.

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

Amended 2026-09-16 (#29): the budget is the same and no passage text moved, but `reflect` now sees
one more thing — **a count**, how many quotes the provenance gate dropped before they became
evidence. It is a number the code produced, not corpus text, so the blast radius this ADR buys is
unchanged; the reason it is there is that without it "evidence so far: (none)" after a step that
retrieved plenty reads to the planner as a silent library, and the next query would be chosen on
that misreading. The line is added only when the count is non-zero, so a run that drops nothing
sends the prompt it has always sent.

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
([`2026-09-07-v0.2.0-rc1-core.md`][rc1-core] for c09,
[`2026-09-07-v0.2.0-rc1-extended.md`][rc1-extended] for h22).

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
and [`privacy-and-threat-model.md`](../privacy-and-threat-model.md) says so in as many words.

An injection can steer evidence selection, the reflect decision, the clarify question and the
answer; what it cannot do is forge a source, because provenance is checked against the stored
passage (ADR-004). The canary's deterministic stages run for free in CI, and its single live call
is reported with the tagged runs ([`2026-09-07-v0.2.0-rc1-retrieval-canary.md`][rc1-retrieval]).
Coverage is one injection, not a suite, and live resistance is measured for `observe` only.

## ADR-009: One runner, three interfaces, events as the contract

Status: accepted; corrected 2026-09-07, amended 2026-09-16 (the correction is closed).

`runner.run_question(...)` is the execution path of the CLI and the web UI: it emits events and
calls back for a clarify reply, and per-question metrics accumulate in a `ContextVar` that is reset
per question, so concurrent web sessions do not mix their numbers. The correction: the eval harness
shares the initial state but drives the graph with its own loop, so it is not on the runner. Moving
it there, or extracting a shared result contract, is an open technical item and was not treated as
a release blocker.

One behaviour in every interface, and UI features cost nothing in the agent. The weak spot was that
the event contract lived in a docstring and drifted twice in one week; it is pinned by tests now —
a fake graph for the events, and end-to-end scenarios of the compiled graph driven by a scripted
model.

Amended 2026-09-16: **one execution path, and a result instead of the state.** The correction above
is closed. `run_question` returns a `RunResult` — the answer, the evidence and its provenance, the
clarify and catalogue fields, the usage snapshot, the wall clock and the failure if there was one —
and the CLI, the web UI and the eval harness read that instead of reaching into the graph's state.
The harness (`eval/run_agent_eval.py:run_one`) no longer drives `graph.stream`: it passes an event
collector and its own `--clarify-pick` reply policy into the runner, which owns the stream loop, the
interrupt, the per-question usage reset and the scratchpad. What is measured and what is shipped are
now the same code, which is the point: every behaviour number this project publishes is produced
through the interface a reader uses.

Two consequences of the same change. **A question that fails is still accounted for:** the metrics
event was emitted after the `try`, so a run that raised reported nothing at all and the calls it had
already paid for were invisible; it is emitted in a `finally` now, and the failure comes back on the
result (exception class and a message with local paths redacted) rather than as an exception through
every interface. The event contract itself is unchanged — same events, same order, same payloads —
except that `by_role` gained `seconds`. Delivery is the consumer's business and stays there: an
`on_event` that raises on the final metrics event is recorded on the result (`metrics_failure`) and
neither replaces the run's own outcome nor turns an answered question into an exception. **Wall clock per node role** is accumulated where tokens are
not: in a `finally` around the model call, so a call that timed out or exhausted its retries still
reports the time the question spent on it. Locally the cost of a question is $0, and a latency
budget that is not measured per node cannot be argued at all (#32); the harness report line and the
JSON sidecar carry it per question.

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

Every number is therefore attributable to a run, and the published failure trace is the most
instructive artifact in the repository ([`docs/examples/c06-fogg-missing-day.md`][c06-trace]). The
costs are
recorded as honestly: runs are single, the hosted model varies, and the scorer is heuristic — an
LLM judge stays out until human verdicts exist. A catalogue set of ten questions joined the two in
September (ADR-016).

Amended 2026-09-15: a fourth deterministic row. Every golden item whose answer has content carries
`expected_facts`, one to four short checkable strings taken from its own notes and the book cards,
and the harness reports `facts_found`/`facts_expected` per question and in the totals, `facts_ok`
when all of them occur in the answer text — folded, whitespace-normalised substring presence,
nothing fuzzy. It is reported beside the verdict and never inside it: the rejection of a single
headline score stands, the rows still cannot be confused, and there is still no LLM judge. What it
buys is the first step of the manual correctness read done deterministically — the report names the
answers that do not carry what the golden item says they must, instead of leaving all of them to be
read from the top — at the cost of a check that cannot tell a fact in a right sentence from the
same fact in a wrong one, which is why it decides nothing. The shape of the golden files is pinned
by a schema test from the same change (`tests/test_golden_schema.py`).

Amended 2026-09-15: a run may be repeated, and the report carries the spread. Every run also
writes a JSON sidecar beside the Markdown one (`answers-<ts>.json`): the fingerprint as fields
rather than as one line, and every attempt of every question with its full answer and the score
dict computed from it — the machine-readable record this decision always implied and never had, so
comparing two runs no longer means scraping numbers back out of prose. `--repeat N` runs each item
N times; scoring stays per attempt, and the aggregation counts the boolean rows (how many attempts
of N passed, never an average of true and false) and ranges the numbers (min / median / max of
cost, seconds and tokens). The "runs are single" position above is therefore **superseded for any
number that gets published**: such a run states its N in the fingerprint (`N attempts per item`
rather than `single run`), its headline is a range with the per-attempt mean beside it, and
`--min-pass` is a floor on the weakest attempt. What is not superseded is everything else in this
record — the three rows that cannot be confused, the fourth deterministic row beside them, no LLM
judge, `--require-clean` for published numbers. A run at `--repeat 1` writes the Markdown report
byte for byte as before (pinned by a test), so every artifact committed under
`docs/eval-results/` and the summary tool that reads them are unaffected. No repeated run has been
made yet and no published number changed here.

Amended 2026-09-15: a FOURTH harness, and the first one whose runs are free. `plan()` is one model
call followed by a hundred lines of deterministic post-processing, and until now the only way to
reach that code with a real planner reply was a paid run of a golden set — so it was usually not
measured at all. `eval/run_agent_eval.py --record-plans` keeps every `role="plan"` request/response
pair of a run that was happening anyway, and `eval/run_plan_eval.py` replays them through the real
node and the real routing, scoring the route, the catalogue operation, the named-book filter, the
fallbacks and the query count. The recording is committed (`eval/recordings/`, unlike
`eval/results/`) because it is the *input* a replayed number came from, and this record's
"every number is attributable to a run" means nothing if the input is on one machine. The seams
are a passive observer in `llm.py` and two rebound names; `nodes.py` is untouched, which keeps the
measured code the shipped code. **What it deliberately does not do is grade a prompt change**: the
recorded replies answer the `PLAN_RULES` of the tree they were recorded on, so the recording
carries that prompt's checksum next to the golden file's and the harness refuses to replay when
either has moved, stamping the report when it is told to anyway. A prompt change needs a new
recording and therefore a paid run — the cost this decision has always accepted for anything that
gets published, moved to the one place where it is unavoidable. The three rows that cannot be
confused, the fourth deterministic row, no LLM judge and `--require-clean` all stand; no number
here changed, and no recording of a real golden set has been made yet.

## ADR-011: Publishing by allowlist into a fresh repository, fail-closed tooling

Status: accepted; superseded on 2026-09-08 — see the note below.

The development repository stays the source of truth, and the public tree is produced from an
explicit file allowlist by an export tool that refuses to run on anything it does not recognise: an
output directory without its own marker, a symlinked output or one inside a repository or a home
directory, an allowlisted path that is missing, a missing secret scanner. That tool is private and
is not part of this repository; "Where the measured code lives" in
[`evaluation.md`](../evaluation.md) says what it does and how this tree relates to the measured
one. The alternative, publishing the development repository
with its history rewritten, would have left every intermediate artifact and every private note one
`git log` away.

The export is a command plus a manual push, and it was verified on a dry run before anything was
made public. The price, decided with the approach, is that later public updates are snapshots
rather than history.

**2026-09-08.** The export above ran once, to produce this repository from the development one;
no second export has followed it. Recorded here from the archived repository, which is private
(`ievgen-borysenko/ask-your-library-dev`) and not something a reader of this tree can check
directly: its final commit is `ef92368` (2026-09-08), and that commit's own subject says the
repository became the archive. What this repository does let a reader check: its first commit,
`945e549` (2026-09-08, `git log --reverse` to find it), is the export. Since that date this
repository is developed directly: every change lands as a pull request against `main`, gated by
the checks the branch ruleset requires ("Automated checks" in [`SECURITY.md`](../../SECURITY.md)),
and no allowlist is maintained for a file added after 2026-09-08 — a new path ships because a
reviewer and the ruleset's checks let it, not because an earlier list named it. What remains true:
CI's secret scan on every pull request and push to `main`, and the audit of the built tree —
commit identity, notices, resolvable links, no AI names — run against a fresh clone before any
change to this repository's visibility. What the fail-closed export tool no longer guards: the
marker-file, symlink and repo/home refusals and the check that every allowlisted path still exists
ran once, at that export, and do not run again for anything added since — nothing in this
repository's own checks re-derives or verifies an allowlist, so a new file's presence is gated by
review and the ruleset, not by that tool.

## ADR-012: Widen what `observe` sees — 1,200 to 2,500 characters per search hit

Status: accepted (measured and merged on 2026-09-06).

`SEARCH_HIT_CHARS` becomes a configuration knob and its default rises from 1,200 to 2,500
characters. Measured on the core set at 1,200 / 2,500 / 4,000, one run each: provenance clean at
all three, behaviour 12/12 at 1,200 and 2,500, mean cost per question +9% at 2,500 and +32% at
4,000, where the behaviour row read 11/12 because of a scorer artefact, not a changed answer. The
alternative that stayed unbuilt was a
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
shape with a visible notice instead of a silent degradation.

Two of those are **partly superseded by ADR-024** (2026-09-17). An update is no longer a staged
rebuild with a single publish: it is a per-book delete-and-append keyed by a minted `book_id`, and
the staged publish survives only for the first build of a table and for the demo corpus. And the
row key's digest is no longer what a re-ingest matches on. The digest still does the job it was
added for — two titles that reduce to the same ASCII slug stay two row keys — but a key derived
from title and author is exactly what a correction changes, so identity moved to the ledger.

A later audit closed two more defects in the splitter: duplicate section names, and short real chapters and the text before the first
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
costing $0.0136 together ([`2026-09-09-catalogue-set.md`][catalogue-set]), and a core run on the
same commit leaves the research loop where it was: 11/11 behaviour, 48/0/0 quotes, $0.0519 mean per
question against $0.0488 on `v0.2.0-rc1` ([`2026-09-09-catalogue-branch-core.md`][catalogue-core]).
Exhaustive content questions ("which of my books mention London?") are explicitly not covered by
this path and stay best-effort in the research loop.

## ADR-017: One passive observer of every JSON model call

Status: accepted; recorded 2026-09-16, after the fact (the seam itself landed on 2026-09-15 with the
plan-replay harness, ADR-010's fourth amendment).

`llm.JSON_CALL_OBSERVER` (`llm.py:442`) is one optional module-level hook that `ask_json` hands a
finished record of every attempt: the role, the attempt number, the system and user messages, the
raw reply, and the reason it was not JSON. Every attempt, not every successful one — the malformed
first reply of a retry is recorded (`llm.py:501-503`), and so is a call that never came back at all,
from the exception path before the bare `raise` (`:492`), because a timed-out planner that leaves no
record cannot be told from an item nobody ran. It cannot change what a call returns: it is given a
dict and nothing reads what it gives back, and `_observe_json_call` (`:451-459`) logs its own
failure instead of raising, since a recorder must never turn a paid run into a failed one. Nothing
in the application installs one; only the eval harness does, saving and restoring the previous value
around a run (`eval/plan_recording.py:381-382`, `:399`). A plain global rather than a `ContextVar`:
the only installer runs one question at a time in one thread, and the web UI, which serves
concurrent sessions, never installs one.

The alternatives were to thread a recorder argument through the nodes, which stops the measured code
from being the shipped code — the one thing the replay harness exists to guarantee; to keep a copy
of the node under `eval/`, which is a hundred lines of post-processing drifting away from the
original; and to monkeypatch `llm.ask_json` from the harness, which works but leaves the patch
re-implementing the parse, so a replayed reply would be read by code the live run never ran.
`json_object` (`llm.py:408-426`) is split out of `ask_json` for that same reason: a replay parses a
recorded reply with exactly the function that parsed it live.

What it buys is observing shipped code without forking it — the seam the free plan replay rests on.
What it costs is a rule that is easy to break silently: **a model call is recordable only if it goes
through `ask_json`**. `plan`, `observe` and `reflect` do (`nodes.py:147, 443, 506`); `synthesize`
calls `llm_invoke` directly (`:641`) and is in no recording, and any node added later that reaches
the model another way will be missing from every recording without anything saying so. One observer,
one installer, no chain: a second consumer needs a registry or a `ContextVar`, and that is a
decision to take then, not a shape to build now.

## ADR-018: A scripted backend behind a two-variable, refuse-loudly gate

Status: reserved, 2026-09-16 — to be written when the code is next touched.

The web UI's test seam installs a scripted backend only when a script path and a spelled-out
confirmation are both set, refuses outright when either name is a key in a `.env` file Chainlit has
already loaded, exits rather than half-installing, and prints a banner to stderr when it is armed
(`fake_backend.py`, called at `ui.py:52` before the imports it replaces): two variables reduce
accidental activation and the dotenv check rejects the one activation path nobody chose, but the
gate reads `os.environ` and cannot tell an exported variable from an inherited one — a process that
inherits both is armed (the environment is read at `fake_backend.py:123`), and anything able to set
them in the server's environment can already run code as the server (`:26-28`).

## ADR-019: The egress claim is enforced by an audit hook in the test process

Status: reserved, 2026-09-16 — to be written when the code is next touched.

"Nothing leaves the machine" is a claim about connection attempts, so the test process installs
`sys.addaudithook` as its floor — patches on `socket` miss `_socket`, by-value imports and UDP —
with one transport layer above it on both installed httpx distributions and every attempt recorded,
loopback included (`tests/egress_guard.py`), which keeps `src/` exactly as it ships.

## ADR-020: `_index_meta` fingerprints the embedder and nothing else

Status: accepted; recorded 2026-09-16, after the fact (the stamp is as old as ADR-002, the refusal
came with ADR-015).

`_index_meta` holds one row per index table with five fields — `table`, `backend`, `model`, `dims`,
`created` (`index_meta.py:21-29`), the first of them the key the row is looked up and replaced by —
written by ingest and checked the first time a table is opened in a process. `check_index`
(`:46-63`) compares the configured embedder against the vector width first and the stamped model
second, and the two cases it distinguishes are not treated alike.

A **stamp that is absent** is accepted: the dims match, an info-level line is logged, the search
proceeds (`:55-59`), because indexes built before fingerprints existed must keep working. A
**stamped model or a width that disagrees** with the configured embedder is fatal on read, not a
warning: `library.open_table` raises on it, once per table per process (`library.py:57-65`), and
preflight reports the same string as an `index_mismatch` problem before an interface starts
(`preflight.py:214-216`). On the write side `ayl-add` refuses both — the mismatch and the missing
stamp (`add_folder.py:348-378`) — because an unstamped table would let a partial write mix two
embedding models and then stamp the whole of it with the model that wrote only some of it; the
refusal names the three ways out (stamp it, rebuild it, or point `LIBRARY_DB_PATH` elsewhere).

No fingerprint at all was the state before ADR-002 and is the failure this exists to prevent:
another model of the same width degrades retrieval silently, with nothing to see. Checking dims
alone is the cheap half of that — 1024 is bge-m3 and several other models. A full manifest of
everything that shaped a table — chunker, splitter version, schema, source digests — was rejected as
more than could be kept truthful at the time, and it is still the direction.

So the row answered exactly one question, "which embedder built this table", and answered it before
a search rather than after a bad answer. It could not answer which chunker or which schema: after a
re-chunk (#28) a half-rebuilt index is a mixed index nothing can detect, and nothing recorded which
files were requested at all. #27 was to extend the row with `chunker` and `schema_version`, and the
policy decided for it — recorded here before the change, so the change would start from it — was
*warn on read, refuse on write*: a chunker or schema that disagrees degrades retrieval rather than
breaking it, and refusing on read would invalidate an index that took about half an hour to build,
while a write that mixes two chunkers cannot be undone at all. That is deliberately **not** the
embedder's rule above, which is fatal on read and stays so. `created` is there for a human reading
the table; no code routes on it.

**Amended 2026-09-17 (#27): the policy above is implemented, in these words.**
ADR-024 added the two fields; this is what now acts on them.

*What counts as a mismatch* (`index_meta.version_mismatch`): a stamped chunker that differs from
`chunking.CHUNKER_VERSION`, or a stamped `schema_version` HIGHER than this code's — an index
written by a newer release. Two things deliberately do not: an **older** stamped schema, which is
the migration this project actually performs (ADR-024 added `book_id`/`book_rev` to existing tables
in place, and the next `ayl-add` migrates and re-stamps), and would otherwise warn every reader of
every index built before the last release about something the next ingest fixes; and an **absent**
chunker — empty, or the ledger's `legacy` — which means nobody recorded it, and inventing a
disagreement out of an absence is what `legacy` exists to avoid.

*On read*, one warning line naming both values and the way out, logged once per table per process
in `library.open_table` and shown by preflight as a **notice**, not a problem: the interfaces
start, the index answers from the chunks it holds. *On write*, `ayl-add` refuses before it embeds
or deletes anything (`refuse_chunker_mismatch`, beside the embedder's refusal), and so does the
demo corpus's `--book` upsert — but **not** its full rebuild, which replaces every row and is
therefore the repair rather than a mix. `--doctor` reads every stamp out whether or not it
disagrees, because it is where somebody looks *before* an upgrade, and exits non-zero on a
mismatch.

*And the half a refusal cannot supply*: a rebuild discards the rows it replaces, so `ayl-add
--backup <dir>` copies the index directory and the chat database with a manifest (the stamps, the
row counts, a sha256 per file), taking the ingest lock and finishing any staged rebuild first, and
`--restore` verifies that manifest before it puts anything back. The refusal names it in its own
text: the remedy sentence is one constant, so the warning and the refusal cannot drift into
recommending two different things. See [`docs/upgrading.md`](../upgrading.md).

## ADR-021: The action channel is a reserved string marker in `current_query`

Status: accepted; recorded 2026-09-16, after the fact. The typed channel is deferred (#25).

One state field carries both "search this" and "do this". `reflect` may write three reserved markers
into `current_query` — `__chapter__|book|section` (`nodes.py:547`), `__book__|key|query`, the
coverage probe of ADR-013 (`coverage.py:70`), and `__clarify__` (`nodes.py:564`) — and `act`
dispatches on them by prefix and arity: `is_loop_marker` is "starts with `__`" (`state.py:6-11`),
the marker is split into exactly three parts, and one with fewer is acted on by nobody — no hits, a
note in the scratchpad, and the dry step counted (`nodes.py:321-371`). The same strings are read by
the router (`route_after_reflect`, `:601`) and rendered as steps by the CLI (`cli.py:101-107`), and
the contract is written out in the runner's docstring (`runner.py:29-30`). Only `reflect` writes
one, and it does so from a decision read against a schema — `read_chapter` with a `book` and a
`section` that are both strings, or the read is downgraded to "enough" (`nodes.py:523-547`): model
output driving an action is the design, not a leak. What the guard prevents is narrower and worth
stating exactly: a *planner query* that looks like a marker is dropped before it can be run
(`is_loop_marker`, `nodes.py:210`), and the fallback strips leading underscores from the reader's
own question (`:213`), so no marker string can be injected into the channel by planner output or by
raw user text.

A typed channel — a second state field holding `{"kind": ..., "book": ..., "section": ...}`, or an
enum beside the query — was the alternative, and the reason it was not taken is that the marker was
the cheapest way to add an action to a loop whose one conditional edge already routed on this field
and whose every consumer (the graph, the runner, both interfaces, the eval harness) already read it.
Keeping the string but validating it against an enum of prefixes was considered and is half a
decision: it catches a typo, not the arity.

The cost is a lexical convention doing a type system's work. The guard in `plan` exists only because
the channel is untyped; the parse is a `split("|", 2)` in one node and a `startswith` in four files;
a fourth action means one more prefix and one more arity to remember in all of them; and a question
that genuinely begins with `__` is quietly rewritten before it is searched for. None of that buys or
costs behaviour, which is why the change is deferred rather than scheduled: the typed channel goes
in with the next change to `reflect`, and this record exists so that change starts from a decision
instead of a discovery.

## ADR-022: Conversation memory and the scratchpad are free text

Status: accepted; recorded 2026-09-16, after the fact. Deliberate for the scratchpad, accidental for
`history` and kept.

`history` is a `list[str]`, one string per turn, `"Q: … A: …"` with the answer cut at 500 characters
(`runner.py:88-99`); it enters the state as text (`state.py:16`, `runner.py:72-86`) and the planner
and `synthesize` read it as text. The one exception is the shape ADR-016 forced: a catalogue answer
is kept as its operation and counts, never as the titles. The web UI does not hold that list across
a restart — `on_chat_resume` rebuilds it from Chainlit's persisted chat steps (`ui.py:658-706`),
pairing a user message with the assistant message after it, skipping badge HTML by its `<div` prefix
and the welcome message by its first words, un-escaping what was escaped for rendering, and reading
the catalogue shape from the message's metadata. The scratchpad is a Markdown log written per step
(`nodes.py:412`) that no code parses, stated where it is written (`:400`): ADR-004 removed the
parser that used to confirm quote badges by substring-matching this file.

Records for both — a turn object for the memory, JSONL for the scratchpad — is the obvious
alternative, and it is right for one half and wrong for the other. For the scratchpad, free text
*is* the decision: a log a human reads and no code may depend on is exactly what ADR-004 bought by
taking the parser away, and a parsable scratchpad invites the coupling back. For `history` it is
worth doing and unbuilt. Persisting the runner's own history beside the chat thread was the other
candidate for the resume path and adds a second store to keep consistent with the one Chainlit
already keeps.

What the scratchpad decision buys is that nothing can quietly start depending on a debug log again.
What the `history` one costs: memory whose only structure is a prefix cannot be filtered, counted or
redacted by code, and the resume path reconstructs meaning from rendered output, so it is coupled to
how answers are drawn — a new message type that looks like an assistant answer joins the memory, and
the two exclusions are prefix rules a change in rendering breaks silently. Records for `history` are
deferred to the next change of the web resume, because that reconstruction is the reader that would
have to change with them. The 500-character truncation is a chosen number, not a measured one.

## ADR-023: Retry and timeout policy belongs to the application, not the SDK

Status: reserved, 2026-09-16 — to be written when the code is next touched.

The model client is built with `max_retries=0` and one client per attempt, so a deadline cap is
recomputed rather than sampled once and reused by every retry; what is retryable, how long the wait
is, and which regime a call runs under are decided once per call in `llm.py`, and `synthesize` is
never capped — dense reasoning that today is recorded only in docstrings.

## ADR-024: A book ledger with a minted id; `ayl-add` updates one book at a time

Status: accepted (2026-09-17). Partly supersedes ADR-015; completes half of what ADR-020 left to
#27.

A book was a derived string and its row key a digest of that string (`bookkey.slug`), so a
corrected `author:` indexed a second book and deleted nothing — ADR-015's own recorded
consequence. `ayl-add` published by staged full rebuild because LanceDB OSS has no rename; the FTS
index was rebuilt whole every time; `_index_meta` carried no chunker or schema version, so a
re-chunk (#28) would leave a mixed index nothing could detect; and nothing recorded which files
had been *requested*, so "which of my books did not make it in" had no answer at all.

**Decision.** A `books` ledger table beside the index tables: `book_id` minted once and never
derived, `key`, `title`, `author`, `source_ref`, `sha256`, `chunker`, `embedding_model`, `status`
(requested / indexed / failed), `error`, `requested_at`, `indexed_at`, `rows`, `fts_seconds`. Its
API is `resolve` / `begin` / `commit` / `fail` / `missing` / `diff`.

**Which book is this?** `resolve` adopts an existing id on two signals and refuses to on a third,
and the order is the part that had to be got right. (1) **The key.** `Title — Author` is what the
reader sees and what the agent cites, so a book that still answers to its key is that book,
whatever happened to its text. (2) **The source.** Failing the key, the file at the same path in
the same folder is the same book whose metadata was corrected — which is the case the derived row
key could never express, and the whole point of the issue. `source_ref` is
`local:<folder digest>:<path inside it>`: the folder is in the reference because one index can be
fed from several folders, and without it a `notes.md` in a second library would be the first
library's book — and, worse, `--prune` run on either folder would delete the other's. (3) **The
digest adopts nothing.** A sha256 match alone is reported and not acted on: a byte-identical copy
of a book under another title would otherwise take over the first book's id, and its next write
would delete the first book's rows — a loss the staged rebuild this replaces could not produce. The
digest is of the book's TEXT, taken after the front matter and any title line are off it, because
correcting `author:` rewrites the file and changes nothing about the book.

One edge is left deliberately unresolved and is tested as such: when the key comes from the FILE
NAME, renaming the file changes the key and the path at once, and nothing remains to tell "I
corrected the author" from "I added another copy". That is indexed as a second book and the first
is reported as vanished, which `--prune` clears — a visible extra book being much the better
failure than a silent takeover. `ayl-add` becomes a per-book
delete-then-append keyed by `book_id`, with the ledger row written before and after and a recovery
pass at the start of every run. Rows carry `book_id` **beside** `note` for one release, so every
chunk id stays byte-compatible. `_index_meta` gains `chunker` and `schema_version`; readers
tolerate their absence and nothing refuses on them here. The version is derived from the stamped
table's own columns rather than asserted, because a version is a claim about the rows and a stamp
that claims what the rows do not have is worse than no stamp — it is what the refusal added in #27
acts on (ADR-020, amended 2026-09-17).

**The alternatives.** *(A) The staged rebuild as it was* — crash-safe and simple, but it has no
identity at all, which is the actual defect; the cost argument for replacing it turned out to be
weak (see the measurements below), the correctness argument did not. *(B) Per-book upsert keyed by
the derived slug* — cheap, but a corrected author still orphans rows, and the delete-then-add is
not transactional either, so it buys the new failure mode without buying the identity. *(C)
Ledger + per-book upsert with recovery* — chosen: the ledger is what makes an interrupted upsert
recoverable, which is the argument for identity **before** incrementality. *(D) A separate SQLite
metadata store* — rejected: two stores to keep consistent, and everything else already reads
LanceDB.

**What it was measured to buy, and what it was not.** Two numbers were taken on the built demo
corpus (7,285 transcript rows, M3 Pro) because the backlog asked for them before anything was
replaced. The **FTS rebuild is 0.8 s** — about 0.1 ms a row — so it stays whole, and an
incremental merge (#33) is not worth its complexity at that price. The **staged full rebuild is
0.2 s**, against 0.01 s for a per-book delete-and-append of one 59-row book. So at demo scale the
publish was *never* the cost the review supposed it was, and the honest claim for the per-book
path is not speed: it is that a correction renames instead of duplicating, that an interruption is
visible, and that "which of my files did not index" has an answer. The cost argument returns only
at a library an order of magnitude larger, and it has not been measured there.

**Consequences.** Easier: re-ingest, correction, upgrade, and the folder diff (`--dry-run`), with
a vanished file reported and deleted only under `--prune`. One rule the whole change is held to:
**recovery is a write.** The fingerprint table gained a staged rebuild of its own here, and
recovering it happens at the start of an ingest and nowhere else — a reader that recovered would
race the ingest that is mid-widening, and `read_index_meta` runs before every search. Readers
tolerate the staged copy instead and read it where the live table is missing. It is the same rule
`doctor` is held to, from the other side. Harder: two writes per book that must
agree, so a **stale ledger is a new class of failure** — reconciled by `ayl-add --doctor`, which
reports six shapes of drift and repairs none of them, because a check that rewrites what it checks
is not evidence. The crash window moved rather than closed: between the delete and the append one
book is absent, which the recovery pass finds on the next run. What that pass may NOT do is infer completion from rows
being present: `begin` marks a book `requested` before its text is embedded, so a crash there
leaves a full set of perfectly good, perfectly stale rows. Each row therefore carries `book_rev`,
the revision of the book it was built from, and recovery compares it with the revision the ledger
recorded — equal, the append landed and only the ledger write was lost (one book is one
`table.add()`, committed as a unit); unequal, absent or mixed, the book is re-indexed or reported
`STALE`, never marked indexed.
The catalogue keeps reading the index tables and not the ledger, or ADR-016's "the count is the
length of that list" weakens into a history of ingests.

**The gate.** Book identity moved into one module (`bookkey.py`) in the same change, and the risk
of that move is silent: a `slug` that differs by one character makes a delete match nothing. So
the exact keys, row keys and chunk ids of both ingest paths were frozen from the code as it stood
before (`tests/fixtures/book_identity.json`, generated at `b2157cb`) and checked against the built
index: all 35 book keys and all 1,228 chapter-level chunk-id prefixes reproduce exactly.

**Still open.** A book backfilled from a pre-ledger index records neither a digest nor a file, so the
first correction after that upgrade still mints a second id — `--doctor` reports the pair. The
cards table is joined to the transcripts table by the book key string alone; no card row carries a
`book_id`, and the ledger does not reconcile the two corpora — `--doctor` says so in its report
rather than leaving it to be discovered, and `--prune` keeps a card whose book it removes rather
than deleting from a table `ayl-add` never writes. And the per-book write is visible to a concurrent reader:
see `known-limits.md`.

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
