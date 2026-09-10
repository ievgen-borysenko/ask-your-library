# What Ask Your Library is

The long-form description this project's front page used to open with.

Agentic RAG over a personal book library: a LangGraph agent asks the model, in its planner role, for
English search queries, runs hybrid retrieval (bge-m3 vectors + BM25, fused with RRF) over a LanceDB index,
distills candidate evidence, reflects on whether it has enough, optionally asks you a clarifying
question or reads a whole chapter, and answers with `[book, chapter]` citations. Every evidence quote the agent collected is then checked
in code against the exact passage it was copied from (the answer's own sentences are not checked claim by claim), per-node token cost is reported per
question, and the demo corpus (33 public-domain books plus 2 synthetic canaries), the golden
sets and every eval run are fingerprinted. A reference implementation with an honest eval
harness, not a "chat with your PDFs" demo. Your own books go in with one command
(`uv run ayl-add <folder>` over a folder of `.txt` / `.md` files, embedded locally by default); the
distilled book cards the demo corpus also carries still need an LLM per book and are not
generated for you.

The most instructive artifact is a failure: an answer that passes every automated gate and still
does not answer the question, because the passage that would have answered it was never retrieved -
with the mechanism explained, in
[`examples/c06-fogg-missing-day.md`](examples/c06-fogg-missing-day.md).

## What it does

- **Answers from your own library, with provenance.** Two corpora: distilled book cards and
  chapter-aware full-text chunks. Answers cite `[book, chapter]`; a code-based guard verifies
  each evidence quote the agent collected against the exact passage it was copied from (the
  answer's own sentences are not checked claim by claim).
- **Knows what it holds.** Questions about the library itself (how many books, which titles,
  whether a title or an author is in it) are answered by code from the index tables,
  exhaustively: the planner only names the operation, the list is read from the tables and the
  number in the answer is the length of that list (ADR-016). A content question that names one
  book is answered from that book. Content questions stay evidence-based and may be incomplete:
  a search cannot prove that nothing else matches.
- **Behaves like an agent, not a pipeline.** plan / act / observe / reflect loop with a step
  budget, a CRAG-style early stop after consecutive dry steps, chapter drill-down for detail
  questions, and a human-in-the-loop clarify interrupt when a half-remembered book matches
  several candidates.
- **Reports what it cost.** Per-node LLM calls, tokens and USD after every question, with
  retrieval selectivity (hits seen vs evidence kept) and injection-redaction counts.
- **Is measurable.** Two eval harnesses, an injection canary and a checksum-pinned corpus; every
  run records the code SHA, golden and index fingerprints and the model, so a number is always
  attributable. Runs are single and hosted-model output varies, so a changed number is a signal
  to look at, not proof of a changed system.
