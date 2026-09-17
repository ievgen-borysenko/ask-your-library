# Known limits

From `backlog.md`, confirmed by the runs of 2026-09-05, 06 and 07 (`v0.2.0-rc1`), and — for the
local default that ships since 0.3.0 — by the local run of 2026-09-10:

- **The default local answering model is not good enough to advertise as a strong default, and
  this project's own measurement of it says so.** Measured on the local backend on 2026-09-10
  ([`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md)). Two
  measurements, and they are not the same kind of thing: the scores below are **behavioural
  compliance**, the harness's own heuristic (titles by substring, refusals by phrase marker,
  clarify, drill-down), and the quote triples are **provenance**, checked by plain code against the
  stored passage. Neither is answer correctness, which nobody graded on any local run. The
  default `qwen2.5:14b` scores 10/10 on the catalogue set with 17 / 0 / 0 quotes confirmed /
  unattributed / broken, and 8/10 on the research set with 41 / 1 / 2 — 18/20 and 58 / 1 / 2 over
  both, a 95.1 % (58/61) quote-confirmation rate. `qwen2.5:7b` scores 19/20 with 36 / 2 / 1, 92.3 %
  (36/39). That report's own verdict: "Neither model is good enough to advertise as a strong
  default: 19/20 and 18/20 with genuine unattributed and broken quotes in both." `c10`
  (aggregation) fails on both models, and `c09` (identify) fails on `qwen2.5:14b`. The quote check
  is a report, not a gate: it names an unattributed quote (text from another retrieved passage, not
  from the one the answer cites) and a broken one (in no retrieved passage at all), and it does not
  stop the answer from carrying either.

  **That last sentence describes the run, not the code as it stands since 2026-09-16.** The check
  runs at the evidence gate now (#29): a quote in no retrieved passage of its step is dropped before
  `synthesize` sees it, one found in another passage is re-pinned to the passage that holds it, and
  the report after the answer reports on evidence that already passed the same check. The numbers
  above were produced before that and are what they are — the 1 unattributed and 2 broken of 61 are
  quotes that reached a reader. **What the gate does to behaviour is now measured on two local
  models, and they do not agree**
  ([`eval-results/2026-09-16-local-models-repeat3.md`](eval-results/2026-09-16-local-models-repeat3.md),
  each model on `c79018a` against itself on `169b511`, both golden sets at `--repeat 3`).

  On the shipped default `qwen2.5:14b` the gate is free: behaviour unchanged item for item — 9/11 on
  the research set and 10/10 on the catalogue set, the same two failures, the same clarify — with
  **broken 2 → 0**, `confirmed == checked_book_text` at 34/34, **2 quotes dropped per attempt** (both
  `not_found`; `no_hit`, `cross_book` and `short` all 0; `repinned` 0), the same 79 LLM calls and the
  same steps distribution. The two dropped are the two this page publishes above as broken, from the
  same two questions.

  **On `mistral-small3.2:24b-ctx20k` it is not free, and this page will not round that off.** That
  model leaves 8–9 broken quotes an attempt without the gate. Under it: **broken 8–9 → 0**,
  `confirmed == checked_book_text` at 50/50, **10–11 quotes dropped per attempt** — and behaviour
  **11/11 → 11/11, 10/11, 10/11**, because `c03` fails two attempts of three with `titles 0/1`: with
  two quotes dropped rather than one, the surviving evidence carries no citation and the answer
  hedges without naming the book. The run also costs 6 more LLM calls, ~14,000 more input tokens an
  attempt and 502 s, because a step whose quotes were all dropped is held rather than counted as dry,
  so two other items search to the step limit — both of those still pass. **So the agreed acceptance
  for the gate is met on the default and not met on the model it was argued for**, on one item, on
  two attempts of three; the report names the options and adopts none. `qwen2.5:32b` under the gate
  is unmeasured. What the gate does NOT reach is unchanged: it checks the evidence the answer is
  written from, never the sentences the answer writes around it.

  **The gate throws away some true evidence, on purpose.** A quote whose only holder is a passage of
  a *different* book is dropped rather than re-attributed: the book on an evidence item is the book
  the answer cites, and moving a quote across works would replace a wrong citation with a confident
  wrong one. So a model that names the wrong book beside a real quote loses that quote instead of
  having it corrected, and the count is published (`dropped_by_reason.cross_book`). The same goes
  for a quote under four normalized words that is not in the passage it cited, and — where
  `AYL_STRICT_HIT_ID=0` lets a quote arrive with no passage named at all — for one whose stated book
  matches no retrieved book, matches two, or is held by two passages of the right book. All of them
  are the conservative direction: fewer citations, none of them invented by the check.

  What the hosted configuration does on the nearest sets, and how near they are. The catalogue set
  is the same golden file at the same checksum (`en-demo-catalog.yaml@14b001e26f5e`): hosted
  Sonnet 4.6 scored 10/10 with 21 / 0 / 0 on 2026-09-10
  ([`eval-results/2026-09-10-catalogue-set.md`](eval-results/2026-09-10-catalogue-set.md)) — that
  set is clean on both, and on both runs every checked quote comes from its four research items
  (`k07`-`k10`, three negative controls and the hybrid), the six catalogue questions being answered
  from the index tables with no quotes to check. That hosted run says of itself: "Single run,
  hosted planner, not reader-graded". The research questions are the ten `c*` items of
  `en-demo.yaml`; the nearest hosted run of that file is the core set of 2026-09-07 (`v0.2.0-rc1`),
  those ten plus the Ukrainian `h06`, at 11/11 with 47 / 0 / 0 — passing both `c09` and `c10`.
  That one **was** read against the golden
  notes, and the reader's verdicts are ten `correct` and one `incomplete` (`c06`), so 11/11 there
  is behavioural compliance and 10 / 0 / 1 is what a reader made of the same eleven answers — the
  only reader grading anywhere in this comparison, and it is on the hosted side. Neither hosted run
  is a paired measurement: different code, a different index build, and for the research one a
  different golden checksum. Read them as the shape of the gap. `LLM_BACKEND=openrouter`
  ([Configuration](configuration.md)) is the hosted path and [Cost](cost.md) is what it costs.
  Scope of the local numbers: the harness's automatic score, no human graded the answers (the
  manual-correctness checkboxes in the report are unticked), single runs, and the last prompt
  change was followed by one re-measurement only — `qwen2.5:7b`'s research subset — so
  `qwen2.5:14b` throughout and the catalogue half of both combined rows describe the prompt as it
  stood in Runs 1-6. Measure your own model before trusting it:
  `LLM_BACKEND=ollama uv run eval/run_agent_eval.py`.
- **A local model's context window is Ollama's business, and a large default is a trap.** This
  project cannot set `num_ctx`: the local backend uses Ollama's OpenAI-compatible `/v1` endpoint,
  where an `options` block is accepted and ignored, and Ollama 0.34 picks the window adaptively from
  the memory available unless a tag or a Modelfile pins it. Most tags pin nothing:
  `mistral-small3.2:24b` carries no `num_ctx`, and on one M3 Pro / 36 GB it loaded at 131072 — about
  36 GB, roughly 28 % offloaded to the CPU — where the failure is not an out-of-memory error but a
  question deadline expiring inside a single model call (603 input tokens, 1,201 s; `plan 192.2,
  observe 1005.4`, so the plan call did return and the deadline landed inside `observe`). A derived
  model at `num_ctx 20480` ran the same eleven questions in 73–399 s each. That 131072 is what one
  run observed, not a property of the tag: read `ollama ps` for the context actually loaded and pin
  it in a Modelfile when the number has to be reproducible
  ([Configuration](configuration.md)); measured 2026-09-16
  ([`eval-results/2026-09-16-local-models-repeat3.md`](eval-results/2026-09-16-local-models-repeat3.md)).
- **A repeated local run measures latency, not behaviour.** At `temperature=0` the three local
  models of 2026-09-16 returned the same answers three times over: across 189 item-attempts no
  per-question behaviour verdict and no `facts_ok` moved, `qwen2.5:32b` was byte-identical on every
  item of both golden sets, `qwen2.5:14b` varied on one item of 21 and `mistral-small3.2:24b-ctx20k`
  on four (0.5 % of tokens in, 0.8 % of tokens out). What did vary is time — 30–196 s per question
  on the shipped default for identical answers, with `observe` 70–76 % of all model seconds and
  2–3× slower on a cold first attempt than on the two after it. So `--repeat N` locally buys a
  latency distribution and almost no behavioural information, and **a spread on the behaviour rows
  still has to be measured on a hosted run**, where the provider samples. Three attempts on one
  machine; a zero spread over three samples is not proof of determinism.
- **"Nothing leaves the machine" is tested for one process on one path, not for your machine.**
  `tests/test_egress_local.py` records every outbound connection attempt the application's own
  Python process makes — through CPython's socket audit events, which cover every socket whatever
  its class or import path, plus an httpx transport layer above them — and asserts that in the
  shipped local configuration every one of them goes to loopback on the configured Ollama port,
  with no hosted provider and no tracing endpoint contacted or even looked up. What it sees is
  every network call made **through Python's socket module**: the standard library, `requests`,
  urllib3, httpx, httpcore, asyncio and the model client's SDK. What it does **not** see is a call
  that reaches libc without passing through CPython — a native extension with its own C sockets,
  or a `ctypes` call into `getaddrinfo` / `connect`. That blind spot is pinned by a deliberately
  failing control test and bounded by another that asserts no known native-networking package
  (`grpcio`, `pycurl`, `pycares`, `aiodns`, `uvloop`, `pyzmq`, `psycopg`, `pymongo`, `redis`) is
  installed in that interpreter or in the application's locked runtime closure; `uvloop` in
  particular would move every asyncio socket out of the hook's sight, and `grpcio` arrives with
  the `ui` extra, which is one more reason the Chainlit process is outside the claim. Those are
  two tests, and they answer differently where the extra IS installed — a developer following
  [Quick start](quick-start.md), or the `ui-smoke` CI job: the interpreter half skips itself and
  says why (that environment was never inside the claim), while the locked-closure half runs
  everywhere and must pass, because no extra can excuse what the application itself depends on. The path is
  `runner.run_question` over the compiled graph, with the real preflight and the real embedder:
  what the CLI and the eval harness run, and what the web UI's Python half calls into. It is **not**
  Chainlit, which the test does not exercise (the `ui` extra is not installed in those CI legs);
  not Ollama, which is a separate process and does what it does with a prompt once it has one; not
  the browser or Chainlit's JavaScript bundle; not any process started by this one; and not
  `scripts/ingest_demo_corpus.py`, which downloads a corpus on purpose. See
  [Privacy](privacy-and-threat-model.md).
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
  reading the chapter. Since 2026-09-16 the answer no longer hides it: a quote whose only verbatim
  match is a book card is counted apart from the traced quotes (`card_only` in `validate`), the
  badge says "+N matched only a book card — a model-written summary, not a quote from the book",
  and the evidence list labels each passage "book text" or "book card". It is a label and a count,
  not a fix: the agent still answers such questions from the card rather than reading the chapter,
  and a question answered entirely off cards now says so instead of showing "n/n traced". **Every
  eval report published before that date counted card matches inside the confirmed / unattributed /
  broken triple**, so the quote numbers quoted here and in the README's table describe retrieval
  provenance — the quote is verbatim in the passage it cites — and not that a book said it.
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
