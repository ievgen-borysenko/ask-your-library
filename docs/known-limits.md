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
- **The hosted default answers correctly but thinly.** `deepseek/deepseek-v4-flash-0731` with
  `LLM_REASONING=off` passes the behaviour heuristic on every attempt of the core set, and a
  reader grading its answers found about **6 of 11 fully correct** per attempt (6.0 over three
  attempts; almost all the rest *incomplete*), against **9 of 11 for `anthropic/claude-sonnet-4.6`
  and for `google/gemini-3.8-flash`** on one attempt each — at about 1/65 of Sonnet 4.6's cost per
  question ($0.0007 against $0.0456 at the rates of the runs). Its typical miss: the answer says a
  detail is not in the evidence while the passages it retrieved hold it (`c06`'s "to-day is
  Saturday", `c04`'s "judge and executioner"), or retrieval never reached it. Every model tried
  shows the same class, thinking on did not help, and a prompt change made it worse; the fix is
  tracked in #81. Manual, single-grader, one index build that predates #80:
  [`eval-results/2026-09-19-hosted-default-quality.md`](eval-results/2026-09-19-hosted-default-quality.md).
  If you need depth more than price, the documented backup (already in `.env.example`) is
  `ORCHESTRATOR_MODEL=google/gemini-3.8-flash` with `PRICE_IN_PER_MTOK=0.75`,
  `PRICE_OUT_PER_MTOK=3.75` and `LLM_REASONING=provider`, at about $0.02 a research question.
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
- **Chapter reads are capped at 12,000 characters**, and since 2026-09-17 (#28,
  [ADR-025](adr/README.md)) that budget is spent around the match rather than at the head of the
  chapter — but only when the request says what it is looking for. 62% of the demo corpus's 1,246
  sections are longer than one read (median 14,821 characters, the longest 245,244), so until this
  change a question about the end of a long chapter was answered from its beginning. Now `reflect`
  may name a phrase, `act` reads up to `CHAPTER_SCAN_CHARS` (120,000) of the chapter and cuts the
  window around the best lexical match in it, and what is left out is stated in band at both ends.
  **The limits of that.** The match is lexical — the query's own words over the raw text, because
  neither retriever returns offsets — so a chapter that never spells the words it is asked about
  gets the head, exactly as before; so does a read decision that names no phrase, which is every
  decision a model makes that ignores the new optional field. A chapter longer than the scan
  budget is still cut at 120,000 characters before the window is chosen. There is no cursor: a
  second request for the same chapter cannot show the next window, it stops the loop
  (`stop_chapter_again`). The first behavioural measurement of it is
  [`eval-results/2026-09-18-rechunk-and-observe-feedback.md`](eval-results/2026-09-18-rechunk-and-observe-feedback.md):
  on `qwen2.5:14b` over the research set, 7 chapter reads per attempt, **7 of 7 named what they were
  looking for** and 5 of 7 moved the window off the head, with 0 row-cap hits; the two that kept the
  head are the case described above, where the query's own words are not found further in. It says
  nothing about whether the moved window answered the question better. An empty read (chapter not in the index) still yields no hit at all and is logged in the
  scratchpad, so nothing synthetic can be quoted as evidence.
- **The chunk is now the observation window, and what that bought is not measured yet.** Until
  2026-09-17 the chunker packed transcript chunks to 4,000 characters while `observe` read 2,500
  of a hit: **90.3% of the demo corpus's 7,285 chunks were longer than the window** (median 3,922,
  the longest 10,778 — raw Whisper output, where a "sentence" with no punctuation in it ran to
  10,140 characters), so the retriever ranked and fused text that was cut off before the model
  read it. The chunker now packs to 2,400 with a hard cap on such a run: on the 35 prepared demo
  texts, **11,282 chunks, median 2,304, the longest 2,400, 0% over the window**, at 55% more rows.
  That is a measurement of the chunks and of nothing else. **Whether answers get better is still
  unmeasured, and what is now measured is that they do not get worse**: on 2026-09-18 the corpus was
  re-ingested (11,282 rows) and both golden sets re-run on `qwen2.5:14b` against the pre-re-chunk
  gate baseline
  ([`eval-results/2026-09-18-rechunk-and-observe-feedback.md`](eval-results/2026-09-18-rechunk-and-observe-feedback.md)),
  and behaviour is identical item for item — 9/11 and 10/10, the same two failures, 10/12 titles and
  10/24 facts on both sides — at +2 LLM calls on the research set and −2 on the catalogue set. That
  pair is a before/after over six merges of `main`, not an isolated measurement of the chunker, and
  the report lists what else was in the gap. In the
  same pair, evidence items rise 43 -> 50 — **eight more card matches** (9 -> 17) against **one
  fewer book-text match** (34 -> 33), so seven more in net and none of it more of the books: treat
  the re-chunk as a defect removed at no behavioural cost, not as better answers. Every published eval report other than that one was
  produced against the old chunker and is not comparable, chunk for chunk, with a run made after it
  — nothing was re-run to change a published number. Raising `SEARCH_HIT_CHARS`
  now buys nothing (there is no chunk tail behind it) and lowering it cuts a chunk the retriever
  ranked whole.
- **Corpus changes are per book, and a re-chunk is still a full rebuild.** `ayl-add` updates one
  book at a time — resolve to a `book_id` in the `books` ledger, delete that book's rows, append
  the new ones, write the ledger row before and after — so the books a run does not name are
  neither read nor rewritten. The demo corpus keeps its staged whole-table rebuild (and its
  `--book` upsert): it builds a pinned corpus from scratch and has no run that adds one book. What
  still costs a full rebuild: a change of embedding model, and a change of chunker — both
  invalidate every vector or every chunk id in the table. #28 is the first chunker change this
  project has shipped, so every index built before 2026-09-17 needs that rebuild
  ([upgrading](upgrading.md)). Neither happens silently: the index is
  stamped with both, a reader warns and a write refuses (see the entry below and
  [upgrading](upgrading.md)), and `ayl-add --backup` is what survives the rebuild. The BM25 index
  is rebuilt whole after every run, measured at 0.8 s for the demo corpus's 7,285 rows at
  `sentence-pack-1`; at `sentence-pack-2` the same text is about 11,282 rows and the 0.8 s
  has not been retaken.
- **The delete and the append are not one transaction.** A crash between them leaves one book out
  of the index; its ledger row still says `requested`, and the recovery pass at the start of the
  next `ayl-add` finds it, re-indexes it when the run covers it and reports it by name when it
  does not. The same pass also catches the subtler shape: a crash while a book was being embedded
  leaves the index holding the PREVIOUS version of it, with nothing about the rows to say so.
  Every row therefore carries the revision of the book it was built from, and recovery compares
  it with what the ledger asked for — matching, the rows are confirmed; not matching, the book is
  re-indexed or reported as `STALE` and never marked indexed, because calling an older text
  current is the one thing a ledger must not do. The window is narrower than the one it replaced (a staged rebuild was all-or-nothing
  but rewrote the whole table), and it is visible instead of silent — which is why the ledger
  came before the incremental path, not after it. **A reader sees that window too:** for the
  fraction of a second between the delete and the append, a question asked in the web UI or the
  CLI searches an index in which that one book does not exist, and it answers without it rather
  than waiting or failing — the staged rebuild it replaced kept the old table queryable to the
  moment of the swap instead. Re-ask the question, or index when nobody is asking.
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
- **"Out of scope" is one optional field the planner fills in, and the code only enforces what
  it says.** Since #70 the planner may mark a request as one the library cannot answer at all —
  write me code, translate this, what is 1234 × 5678, be my chatbot — and then code ends the run
  at `plan`: no search, no model call for an answer, and a refusal that names the library as the
  reason. What "scope" means here is one line: *the request asks for something the library cannot
  supply*, and that is two things — a **deliverable** the books are not (code, a poem, a
  translation, arithmetic, a persona, an opinion) and **facts about a book that its own text does
  not hold** (when it was published and by whom, what it costs, the author's life, what critics
  said). By that rule naming a book on the shelf does not make either of them in scope - "a poem
  in the style of Dracula" and "when was Dracula published" are what it asks to be refused, while
  anything the books' *content* can answer is not - and that is the rule, not the measurement: the
  live run found both of those two let through (next entry). It is **not** a claim that the agent
  only ever says true things about your library, and it is not a filter on topics. What is NOT
  covered: the decision is the
  planner's reading of the question, so a small local model that does not set the field routes
  the request into the ordinary loop (where it is usually refused for lack of evidence — which is
  the `CONTAINED` outcome of the canary, not a pass); a request that hides the deliverable inside
  a book question ("what does chapter 3 say, and also write me the code for it") is one
  judgement, not two, and whichever way the planner reads it is what happens; nothing re-checks
  the decision after the answer is written; and there is no code-level keyword gate behind it,
  deliberately, because one would fire on in-scope questions ("how does the book translate the
  Latin motto?"). The mechanics run in CI on a scripted backend; what the gate does against a
  real answering model is the next entry
  ([`evaluation.md`](evaluation.md), "Scope canary").
- **The gate refuses the requests that name no book, and lets through the ones that name one.**
  Measured **7/9** on the local default (`qwen2.5:14b` via `ollama`,
  [`eval-results/2026-09-17-scope-canary-qwen2-5-14b.md`](eval-results/2026-09-17-scope-canary-qwen2-5-14b.md),
  #70). The seven that were refused name no book: a Python script, the capital of Australia, a
  persona, an opinion, a translation, an arithmetic product, chit-chat. The two that were not both
  name a book that is on the shelf - a poem in the style of one, and the publication history of
  another - and the planner reads each of them as a question about that book, so the run goes
  through the ordinary loop: the poem comes back composed by the model with a retrieved passage
  cited after each verse, and the publication date comes back cited to the book's own summary
  ("published in 1897" — which is where the second miss gets its footing, because a book card does
  hold the fact the rule assumes only the outside world has). So the line the gate actually draws is not the one `PLAN_RULES` describes: it is whether
  a shelved title is named, not whether the library can supply what is asked. In the other
  direction nothing was lost - the four in-scope controls and all eleven core golden questions
  came back with no gate refusal - so the failure mode here is a miss, not a false refusal. The
  issue stays open for the two misses and the README says nothing about the gate until a second
  iteration moves the number.
- **Markdown in the answer is rendered.** Image references are removed before rendering so the
  browser fetches nothing on its own; links stay and need a click. This now holds for every
  message the web UI sends, the HTML fragments included (the provenance badge with its tooltip,
  the evidence list, the metrics footer): each of them used to be escaped only, and an escape
  does not stop a blank line from ending the message's HTML block and handing what follows back
  to the markdown renderer.
- **Heuristic behavioural scoring**, no LLM judge: refusals detected by phrase markers,
  titles by substring match. `get_chapter` caps at 1,700 chunks — raised from 1,000 with the
  re-chunk, so the cap still reaches about the same 3.6M characters of one section, and every read
  that comes back at it is logged and counted into the eval report — and reconciles section naming
  (`Chapter 59` vs `59`) heuristically; the 12k it returns is a window inside up to 120k of the
  chapter, not its first 12k, when the request names what it is looking for.
- **A book's identity is minted; its NAME is still a derived string.** Every book has a `book_id`
  in the `books` ledger, assigned once and never recomputed, and `ayl-add` updates by that id. A
  book is recognised by its key, or — when the key is what changed — by being the same file in the
  same folder: so correcting `author:` in the front matter or on the title line renames the book
  rather than indexing a second one, and a file that moved inside the folder keeps its key and so
  its id. **Renaming the file itself to correct the key is the case this cannot carry**: the key
  and the path change together and nothing distinguishes a correction from a second copy, so the
  new name is indexed as a new book and the old one is reported as vanished (`--prune` clears it).
  Identical content alone never adopts an id — a byte-identical copy under another title is a
  second book, with a warning naming the first, because the alternative is one book silently
  replacing another. What is still derived is the `Title — Author` key itself, which is what the
  agent cites, what the chapter filter matches and what the catalogue lists; a book card whose
  heading differs from its transcript's key by one character still lists as two books, because the
  two tables are joined by that string and no card row carries a `book_id` — which is also why
  `--prune` removes a book's full-text rows and keeps its card, saying so, rather than deleting
  from a table `ayl-add` never writes. And a book backfilled
  from an index built before the ledger records neither a digest nor a file, so the *first*
  correction after that upgrade still creates a second book (the next one does not).
- **The catalogue is what the index holds, not what your folder holds.** It counts the distinct
  book keys of the index tables and never reads the ledger (ADR-016, ADR-024), so "N of N books"
  stays exactly as exhaustive as it was — but a book whose file you deleted is still listed until
  you re-run `ayl-add --prune`, and a file that failed to index is not listed at all. The two
  questions the catalogue cannot answer — what was requested, and what failed — are what
  `ayl-add --doctor` answers, by reconciling the ledger against the index tables and reporting
  the drift. A stale ledger is itself a failure mode now; that check is how it becomes visible.
- **The chunker and the schema version are enforced unevenly, on purpose.** `_index_meta` carries
  `chunker` and `schema_version` beside the embedding fingerprint, written by both ingest paths.
  The version is read from the table's own columns rather than assumed, so a table an ingest has
  not yet migrated, and the cards table — which never gains the ledger columns — are stamped for
  what they actually are. A disagreeing chunker (or a row schema NEWER than this code's) **warns
  on read and refuses on write**: the index goes on answering from the chunks it holds, and the
  next `ayl-add` into it stops before embedding or deleting anything. That is not the embedder's
  rule, which is fatal on read, and the difference is deliberate — a rebuild costs about half an
  hour and a read of differently-cut text is a degradation, not a broken index, while one
  mixed-chunker write cannot be undone at all. See [upgrading](upgrading.md).
  **What it cannot detect:** an index already mixed before this shipped, because nothing recorded
  which chunker wrote those rows; an absent chunker stamp is treated as the absence it is, read
  and written without a word. On a read or a write only the stamp is compared; the rows are
  measured in two places, both run by hand (#75). `--stage stamp-meta --chunker current` refuses
  to write the stamp when a row is longer than the packer can return (2,640 characters) or a book
  holds fewer rows than its prepared text needs, and `--doctor` prints the chunk-length
  distribution and reports rows above that ceiling as drift. What those two still cannot see: a
  table cut by another chunker whose rows happen to fit under the ceiling and above the floor; a
  cards table, whose chunker has no ceiling; row counts of books that have no prepared text
  beside them; and a stamp naming an OLDER version (`--chunker <name>`), which stays an
  assertion trusted exactly as far as the person who made it. The way out is `ayl-add <folder> --rebuild`, which drops the
  table and re-indexes — it keeps the ledger's minted ids, but the books the ledger holds that
  this folder does not lose their rows with the table and are reported as `requested`, to be
  re-indexed from their own folders.
- **The web UI's chat database is checked, not migrated.** `ui.py` creates its tables with
  `CREATE TABLE IF NOT EXISTS`, so a `chat.db` written by an older release keeps its old columns
  for ever. At startup the columns the schema declares are compared with the ones that are there
  and the difference is **warned** about, naming the missing columns; the file carries a
  chat-schema version of its own. Nothing alters the table: there is no `ALTER TABLE` migration
  and none is planned, because the failure is rare, the schema is Chainlit's rather than this
  project's, and the remedy (move the file aside, let it be recreated) destroys the conversation
  history and has to be the reader's decision. Until it is taken, the UI works for everything that
  does not touch the missing column.
- **A backup is a file copy with a statement attached, and the statement has limits.**
  `ayl-add --backup <dir>` copies the LanceDB directory and the web UI's `chat.db` with a manifest
  (the stamps, the row counts, a sha256 per file), after taking the ingest lock and finishing any
  interrupted staged rebuild — those two are what make the copy a copy of a whole index rather
  than of one caught mid-write. The lock is an **`flock`** on a file beside the index directory, so
  a crash never leaves it held — the kernel releases it with the process — but it is still
  **advisory and single-machine**: only this project's own write paths take it, nothing stops `cp`
  or any other program from writing while it is held, and on a network share `flock` means whatever
  that share implements (a refusal naming another machine says so). Restoring stages its copy
  beside the target and publishes by rename, and **never deletes** the index it replaces — it is
  moved aside and named — so a restore costs the disk of both until you remove one. `.scratch/`
  and `.env` are not copied at all, and the chat database is snapshotted through SQLite rather
  than copied as files, so a `chat.db` SQLite cannot open is reported and skipped rather than
  copied as bytes. A **symlink inside the index** is refused outright rather than copied or
  followed: a copy follows links while the digests skip them, so the manifest would describe a set
  of files that is not the set of files in the directory. LanceDB writes none, so this only ever
  refuses something somebody put there.
