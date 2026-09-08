# ADR-016: The catalogue path — what the library holds is answered by code

Status: accepted, 2026-09-08 (the pull request that adds this file). Earlier decisions
(ADR-001 to ADR-015) are summarised in the README's Architecture section; this one is written
out because it changes the planner's contract and adds a node to the graph.

## Context

The first question a new user asks a library agent is about the library: how many books, which
titles, do I have X. Sent through the research loop (plan → act → observe → reflect), such a
question gets a sample, not an answer. Top-k search returns the neighbours of a phrase, not the
set of distinct sources; `observe` keeps hits by the text of a chunk while the answer sits in
its metadata (a book found in one step was dropped as "dry" in the next); `reflect`
re-phrases the same query; the stop rule counts passages, not coverage; and the number in the
answer is written by a model over a list it saw. The owner's first question to the web UI
(08.09) returned fourteen titles under a heading that said seventeen, of thirty-three, for four
searches and ten model calls, with every "quote" (a title from metadata) confirmed by the
provenance check — a green badge over an incomplete answer.

This is not a defect of one node. Two products were folded into one loop: "the library system
knows what it holds" and "the research agent searches inside the books".

## Decision

A separate, deterministic path for questions about what the library holds:

- `plan` keeps its one model call and gains a third mode, `catalog`, with a structured
  operation: `{"op": "count" | "list" | "has" | "by_author", "title": ..., "author": ...}`.
  The model recognises the intent (it sees the conversation and reads any language); it does
  not count, does not list, does not decide whether the result is complete.
- Code does everything after that. `parse_catalog_request` validates the operation against an
  enum ("has" needs a title, "by_author" an author); anything else goes to the research loop,
  and the event says so. `library.list_books()` reads the distinct book keys of both index tables,
  excluding the demo's canary fixtures by their `source` column, never by name. A title or an
  author is resolved against that list by code: exact (case, accents and apostrophes folded, a
  leading article ignored), then contained as whole words, then a close match for a typo
  (surname alone for authors); several matches are returned as several. The answer is a
  template over the result; the number in it is `len()` of the list under it.
- A new `catalog` node between `plan` and `validate`; `validate` reports a catalogue answer
  (`provenance.catalog = {op, count, total}` next to the zero quote counts) and the interfaces
  show one `catalog` step and a "catalogue answer" badge instead of "0/0 traced".
- The hybrid: a content question that names one book carries the name in the planner's
  `book` field; the same resolver turns it into an index key and retrieval is limited to it
  (`act`, like the filter after a resolved clarify, ADR-013). No match: the whole library is
  searched and the answer starts by saying so. Several matches: no filter, no note.
- Code refuses an invalid operation and a catalogue request after a clarify reply (the reply
  settled a book of the research loop), and sends a question that also asks about content
  ("Do I have Dracula, and why does Harker stay?") to the research loop with the named book as
  the filter: a conservative gate on content vocabulary (why, how, who, about, mention, ...),
  because the planner labelled exactly that question "has" once. The event says which happened.
  The gate knows words, not titles: "the names of the three musketeers" is beyond it, so that
  routing stays the planner's reading, measured by the controls of the catalogue eval set.
- The list never reaches the model: the answer is a template, and the conversation memory that
  the next turn's planner sees keeps only the operation, the counts and the name asked about.

## Options considered

A. Prompt only ("answer catalogue questions from the hits"): the loop still samples, and the
count is still the model's. B. A regex router before the model (no call at all for exact
forms): brittle across two languages and follow-ups ("and which of them are by Verne?"), and it
would become a second source of wrong routes. C. This decision: the model names the intent,
code validates and executes. C keeps the one paid call the planner already makes and moves
every number and every list into code.

## Consequences

- Catalogue questions cost one model call and no search; the answer is exhaustive by
  construction for what the index holds. "Searchable" means "has rows in the tables"; a book
  that failed to ingest is invisible here (no ingest ledger exists yet — `docs/backlog.md`).
- Exhaustive content questions ("which of my books mention London?") are not covered: they
  need the books' content and stay best-effort in the research loop, recorded as a known limit.
- The eval gains a set of its own, `eval/golden/en-demo-catalog.yaml`, scored on the structured
  result with strict set equality against the manifest, plus three negative controls (content
  questions that look like listings; one scored on routing alone) and one hybrid item that
  pins the named-book filter; a research question answered by the catalogue path fails its
  item.

## Not in scope

Natural-language-to-SQL over the metadata; genre or topic facets from the cards; reading
statistics; recommendations; a full work/edition model; multi-user permissions; an exhaustive
semantic scan of arbitrary topics. Collections and reading status are a later decision.
