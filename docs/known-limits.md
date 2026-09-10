# Known limits

From `backlog.md`, confirmed by the runs of 2026-09-05, 06 and 07 (`v0.2.0-rc1`), and — for the
local default that ships since 0.3.0 — by the local run of 2026-09-10:

- **The default local answering model is measurably less reliable than the hosted one.** Measured
  on the local backend on 2026-09-10
  ([`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md)): the
  default `qwen2.5:14b` scores 10/10 on the catalogue set with 17 / 0 / 0 quotes confirmed /
  unattributed / broken, and 8/10 on the research set with 41 / 1 / 2 — 18/20 and 58 / 1 / 2 over
  both, a 95.1 % (58/61) quote-confirmation rate. `qwen2.5:7b` scores 19/20 with 36 / 2 / 1, 92.3 %
  (36/39). That report's own verdict: "Neither model is good enough to advertise as a strong
  default: 19/20 and 18/20 with genuine unattributed and broken quotes in both." `c10`
  (aggregation) fails on both models, and `c09` (identify) fails on `qwen2.5:14b`. The quote check
  is a report, not a gate: it names an unattributed or a broken quote, it does not stop the answer
  from carrying one. Scope of those numbers: the harness's automatic score, no human graded the
  answers (the manual-correctness checkboxes in the report are unticked), single runs, and only
  `qwen2.5:7b`'s research subset was re-measured after the last prompt change, so `qwen2.5:14b`'s
  numbers describe the prompt as it stood in Runs 1-6. The hosted figures in the
  [README](../README.md#measured) table come from other sets and are not a like-for-like
  comparison; `LLM_BACKEND=openrouter` ([Configuration](configuration.md)) is the hosted path, and
  [Cost](cost.md) is what it costs. Measure your own model before trusting it:
  `LLM_BACKEND=ollama uv run eval/run_agent_eval.py`.
- **Identify mode can still stop at one book.** The coverage gate (ADR-013, since 0.2.0-rc1) spends the
  planner's next queued query before `reflect` may say "enough" with a single book, which is
  what brought Gulliver (c09) and the second gothic candidate (h22) into the clarify list; q06
  still does not clarify, and a book no query retrieves cannot be offered.
- **Comparative and aggregation questions may miss a work.** The planner issues queries centred
  on one side of the comparison and the other book is never retrieved. Decomposition per implied
  work is v0.2.
- **Exhaustive content questions are best-effort.** "Which of my books mention London?" reads
  like a catalogue question but needs the books' content: it goes through the research loop, and
  top-k retrieval cannot prove that no other book matches. The catalogue path (ADR-016) covers
  what the library holds (count, titles, a title or an author), not what the books say. A content
  question that names one book is limited to it only when the name resolves to exactly one
  catalogue entry; a name that fits several ("Holmes"), a fragment of a title ("Time"), or a
  longer name that merely contains one ("Dracula's Guest") gets the whole library.
- **Detail questions may skip drill-down** and be answered from card summaries instead of
  reading the chapter.
- **The time budget is coarse, and there is no hard deadline.** `QUESTION_DEADLINE_S` (300 s)
  is a budget for continuing the search: it is checked before each next decision, never
  mid-call, so the step in flight and the synthesis still complete. `LLM_TIMEOUT_S` is httpx's
  read timeout, which bounds the wait for the next chunk of a response, not the whole request:
  a provider that keeps sending slowly is not cut off. A search-loop call (plan, observe,
  reflect) is bounded per attempt by the smaller of `LLM_TIMEOUT_S` and what is left of the
  question's budget, never below 5 s. The retries are the client's own loop, not the SDK's
  (which samples one timeout when it builds a client and reuses that number for every retry it
  makes): each attempt is given the budget that is left when it starts, and once a failure and
  its backoff would leave 5 s or less the call gives up instead of retrying. So a capped call,
  attempts and backoff included, stays inside the seconds the question had left when it began,
  and with the local pair — 600 s a call against 300 s a question — no single loop call
  outlives the whole question and then retries. Two calls keep the full `LLM_TIMEOUT_S` per
  attempt, and the full retry count: the final synthesis, and anything the loop issues once the
  budget is already spent. Bounding those by the seconds left would end a deadline-stopped run
  in a timeout instead of the degraded answer the deadline exists to produce. For the usual
  failure shapes (no answer, a transient error) such an uncapped call takes up to
  `LLM_TIMEOUT_S` x (1 + `LLM_MAX_RETRIES`) plus the backoff between attempts (0.5 s doubling
  to a cap of 8 s, or the server's own `Retry-After` when it sends one, up to two minutes), and
  a node that asks for JSON may call twice, so an uncapped call in flight is around 720 s
  hosted / 3,600 s on a cold local model in those shapes; that is an estimate for them, not a
  guaranteed upper bound on a question. When the deadline is spent the
  answer is written from the evidence so far and the stop reason says so. The web UI
  additionally waits at most 300 s for a clarify reply.
- **Chapter reads are capped at 12,000 characters** and the cut is marked in-band within that
  budget; an empty read (chapter not in the index) yields no hit at all and is logged in the
  scratchpad, so nothing synthetic can be quoted as evidence.
- **Corpus changes mean a full re-ingest**, except single-book re-ingest via `--book`, which
  upserts that book's rows in place. `ayl-add` rewrites the whole table instead — a staged
  rebuild that carries the untouched books over and re-embeds only the run's books.
- **English corpus assumption.** The planner prompt hardcodes English search queries. Questions
  in other languages work (bge-m3 is multilingual), the queries do not.
- **"Your own library" covers plain text only, and without cards.** `ayl-add` takes `.txt` and
  `.md`; EPUB, PDF and audio are not handled (the demo corpus's audio path is Whisper in
  `scripts/ingest_demo_corpus.py`, driven by the manifest). It builds the transcripts table
  only — book-card generation needs an LLM per book and is not implemented — and its chapter
  detection is the demo heuristic, so an unusual edition may fall back to one `Full text`
  section. The retrieval and answer-quality numbers under [Evaluation](evaluation.md) were
  measured on the demo corpus, not on an arbitrary folder.
- **Prompt delimiters are a convention, not a boundary.** Retrieved text is wrapped in
  XML-like blocks with `<` neutralized; the sanitizer is a small EN/UA regex set. An injection
  cannot forge a source (provenance is checked against the stored passage), but it can steer
  evidence selection, the reflect decision, the clarify question and the answer. The canary
  proves the boundary MECHANICS (and its own ability to see a leak) for free for `observe`,
  `reflect`, `clarify` and `synthesize`, plus the UI render path; `plan` with a hostile
  clarification reply is not covered by it; live model resistance is measured for `observe`
  only, on one injection.
- **Markdown in the answer is rendered.** Image references are removed before rendering so the
  browser fetches nothing on its own; links stay and need a click. This now holds for every
  message the web UI sends, the HTML fragments included (the provenance badge with its tooltip,
  the evidence list, the metrics footer): each of them used to be escaped only, and an escape
  does not stop a blank line from ending the message's HTML block and handing what follows back
  to the markdown renderer.
- **Heuristic behavioural scoring**, no LLM judge: refusals detected by phrase markers,
  titles by substring match. `get_chapter` caps at 1000 chunks / 12k chars and reconciles
  section naming (`Chapter 59` vs `59`) heuristically.
- **A book is its `Title — Author` key, and the catalogue is a history of ingests, not a listing
  of your folder.** The key is derived from the file — front matter, a standalone title line, or
  the file name — and everything downstream is keyed on it: the citation, the chapter filter, the
  catalogue. Correct `author:` in a file's front matter and run `ayl-add` again, and the catalogue
  holds a second book: the corrected key is indexed, and the rows under the old one stay until
  someone removes them by hand. A file removed from the folder keeps its rows too, and a book card
  whose heading differs from its transcript's key by one character lists as two books. The count
  is the length of what the index holds, which is the history of what was ingested, not the
  current state of the folder. A `books` table with a stable id, and an ingest ledger beside it,
  are the planned fix (`backlog.md`).
