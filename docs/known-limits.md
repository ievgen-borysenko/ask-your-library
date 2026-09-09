# Known limits

From `backlog.md`, confirmed by the runs of 2026-09-05, 06 and 07 (`v0.2.0-rc1`):

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
  a provider that keeps sending slowly is not cut off. For the usual failure shapes (no answer,
  a transient error) one call takes up to `LLM_TIMEOUT_S` x (1 + `LLM_MAX_RETRIES`) plus the
  SDK's backoff (up to two minutes per retry when a 429 carries `Retry-After`), and a node that
  asks for JSON may call twice, so a step in flight is around 720 s hosted / 3,600 s on a cold
  local model in those shapes; that is an estimate for them, not a guaranteed upper bound on a
  question. When the deadline is spent the answer is written from the evidence so far and the
  stop reason says so. The web UI additionally waits at most 300 s for a clarify reply.
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
  section. The retrieval and answer-quality numbers below were measured on the demo corpus, not
  on an arbitrary folder.
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
