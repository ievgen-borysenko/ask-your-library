# Backlog

Ordered roughly by priority; items graduate into issues when picked up. Items marked (AR-31.08)
come from the independent architect review of 31.08, (CR-03.09) from the second cross-review of
03.09, (audit 04.09) from the independent audit of 04.09, (reviews 05.09) from the full reviews
of 05.09. Resolved items are listed at the end with the mechanism that closed them, because the
open ones often refer to them.

## Release status

- Measured and documented: tag `v0.2.0-rc1` (07.09) with the core and extended reports, retrieval
  and canary outputs, the reader's verdicts on the eleven core answers, and the v0.1.0 baseline
  (`docs/eval-results/`, `docs/evaluation.md`).
- Released and public since 2026-09-09 (tag `v0.2.0`), after the short live check of the web UI
  on a clean environment — the passage under an evidence item readable in the browser (not merely
  sent), a clarify including the no-reply case, chat restore after a reload, and a first start by
  the README. That check is no longer a manual one: since 2026-09-15 `tests/ui` walks the same
  path in a browser against a scripted backend, at desktop and phone width, and CI runs it in the
  `ui-smoke` job (below, and in `docs/evaluation.md`). The job is deliberately NOT in the branch
  ruleset's required checks: it is the newest and the slowest, and it should earn that first.
- Done since: security CI (`.github/workflows/security.yml`: gitleaks over the complete range of
  each event, OSV-Scanner over `uv.lock`, weekly; Dependabot; every action pinned to a commit SHA)
  and Chainlit 2.12.0, the release that closes the two MCP advisories, with the config cleaned and
  the UI re-checked (`SECURITY.md`, CHANGELOG). The catalogue path (ADR-016): questions about what
  the library holds are answered by code from the index tables — one model call, no search step,
  the number in the answer the length of the list under it — with an eval set of its own. The
  hardening pass: two zero-click image channels in the web UI closed at both ends, a `Host` check
  and a `SameSite=strict` login cookie on the loopback UI, terminal escape sequences stripped
  where corpus text becomes index metadata, prompt text or a printed line, evidence passages
  readable again after 2.12 rendered them as code snippets, an honest quote out of a poisoned
  passage confirmed again, and a `conftest.py` that stops the suite inheriting the shell.
- Done at the visibility switch (2026-09-09): a ruleset on `main` requires the checks
  `test (openrouter)`, `test (ollama)`, `test-ui (openrouter)`, `test-ui (ollama)`,
  `install-script`, `secrets` and `dependencies` — eight since `workflows` joined them on
  2026-09-15 — keeps branches up to date, and allows no
  force-push, no deletion and no bypass; a code scanning rule blocks on CodeQL security alerts of
  high or higher and on other alerts at error level; Dependabot alerts, secret scanning with push
  protection, and private vulnerability reporting are on.

## Agent behaviour

- **Identify mode can still stop at one book.** The coverage gate (ADR-013) spends the planner's
  next queued query before "enough" with a single book: c09 and h22 clarify with the right second
  candidate. Still open: q06 (still does not clarify) and any candidate no query retrieves. The
  "distinct books in the raw hits" variant was measured and rejected (it probed noise books).
  The gate's extra step costs +20-25% per question where it fires; whether that price is right
  for the two clarify cases it buys is an open question.
- **Comparative / aggregation questions do not query every work.** h17 (and q15, since retired
  from the extended set as a duplicate) ask for a Doyle-side contrast; the planner issues
  Lupin-centric queries and the Doyle book is never retrieved. Decompose comparative questions
  into one query per implied work. The catalogue resolver (ADR-016) can give that decomposition
  both works' keys; the gate itself is still open.
- **"How exactly / what happens" questions answered from card summaries.** h13 (Moby Dick ending)
  passes on facts but skips the chapter drill-down the golden expects; reflect should prefer
  read_chapter when evidence for a detail question comes only from cards.
- **Observe sees the first 2,500 characters of a hit (1,200 until 0.1.0), ranking saw ~4,000.**
  c06 in the 05.09 core run: the Chapter XXXVII window ended one line before the sentence that
  answers the question, and the model inverted the day of the week. Read a window around the
  matching span instead of the chunk head (also: reading a window around the matching span
  instead of the chapter head in `read_chapter`).
- **Behaviour gaps need code-level gates, not prompts** (audit 04.09). Prompt-only tuning
  (per-work queries, surfaced candidates in reflect, cards-only drill-down rule) was measured on
  golden v3: 37/42 vs 36/42 baseline, with all five target failures at the time (q06/h05 clarify,
  q15/h17 Doyle side, h13 drill-down; h05 and q15 since retired as duplicates) unchanged. Next
  attempts: require one query per implied work before "enough" on comparative questions; force
  read_chapter for "how exactly" questions whose evidence is cards-only.
- **Exhaustive content questions are best-effort.** "Which of my books mention London?" reads
  like a catalogue question but needs the books' content: it goes through the research loop, and
  top-k retrieval cannot prove that no other book matches. The catalogue path (ADR-016) answers
  what the library holds, not what the books say. Next: honest marking in the synthesis ("found
  in these N books; no full scan was run") and, separately, a full scan per book as an explicit,
  priced decision.
- ~~Trust boundary: synthesize consumes evidence before validate runs; a "verifying" state in the
  UI, or validation before synthesis.~~ **Done 2026-09-16 (#29, first half):** the quote check runs
  at the `observe` gate, so `synthesize` consumes verified evidence only — a broken quote is dropped
  before the answer, an unattributed one is re-pinned to the passage that holds it, and the
  post-synthesis check stays as the report (ADR-004, second amendment of 16.09). **The behavioural
  effect is unmeasured until the next local run:** the paired baseline on three local models is
  being produced, the gate's own run follows it, and the acceptance is a confirmed ratio of 1.0 by
  construction, a published drop rate, and behaviour at repeat not below the baseline. Still open
  from #29: citation by evidence id, checked against the answer's own sentences, and a broken quote
  failing the evaluation instead of only being counted.
- Behavioural scoring is heuristic (substring titles, refusal phrase markers); refusal markers are
  loose ("do not have", "доказів") and should be anchored to the library; an LLM judge for answer
  correctness remains future work.
- **The re-plan after a clarify is recorded but not replayed.** `eval/run_plan_eval.py` replays the
  first planner call of an item; a clarify sends the run back through `plan()`, and what that
  second call receives is a function of graph state — the evidence collected, the candidates the
  loop offered, the reader's reply — which the `llm.JSON_CALL_OBSERVER` seam never sees. The
  harness accounts for it (`calls_recorded` / `calls_replayed`, non-zero exit unless
  `--allow-unreplayed`) rather than inventing the state. Replaying it needs the runner to snapshot
  that state beside each recorded call, which is a second record with its own redaction question
  (evidence passages are book text) and its own size — the reason it is a follow-up and not part of
  the first slice.
- Still open from the ablation idea: vector-only vs BM25-only, and the planner's rewritten query
  vs the raw question. The second of those has a **free path** since the plan-only replay
  (`eval/run_plan_eval.py`): a recording holds the planner's rewritten queries for every golden
  item, and the raw question is in the golden file beside it, so the two query sets can be fed to
  the retriever — which `eval/run_retrieval_eval.py` already does with the raw question and no
  model call — and compared at the cost of one recording that a normal run makes anyway. What
  that would compare is the retrieval WINDOW of each, not the answers: a full comparison of the
  finished answers still needs two paid runs.

## Retrieval, ingest, eval harness, code quality

- **Book identity is a derived string, and no ingest ledger records what went in.** A book is its
  `Title — Author` key, derived from the file (front matter, a standalone title line, or the file
  name), and every downstream reference — the citation, the chapter filter, the catalogue
  listing — is that string. Correcting `author:` in a file and running `ayl-add` again therefore
  adds a second book instead of renaming the first: the corrected key is indexed and the rows
  under the old one stay until someone removes them by hand; a file removed from the folder keeps
  its rows; a card whose heading differs from its transcript's key by one character lists as two
  books. And since `ayl-add` rebuilds the table (carrying over the rows it did not replace)
  without recording requested / indexed / failed per file, "which of my files did not index"
  cannot be answered either (`list_books` shows what
  is there, never what is missing). The catalogue is exhaustive for what the index holds, which
  is the history of what was ingested, not the current state of the folder
  (`docs/known-limits.md`). Fix: a `books` table with a stable id that a re-ingest updates in place, and an ingest
  ledger beside it.
- **A local latency budget still misses what is not a model call.** Since 16.09 `by_role` carries
  `seconds` beside calls and tokens (the wall clock of each model call, retries and timeouts
  included), and the eval report and sidecar carry them per question — the precondition #32 was
  blocked on, because locally a question costs $0 and seconds are the only currency there is. What
  they do not cover: model residency (the ~98 s of the first question that is model load plus a
  cold prompt cache, paid before any call this counts), and the parts of a node that are not a
  call — retrieval is under a second today, which is why the role granularity was enough to start.
  Closing #32 means deciding those two separately.
- `validate` accepts one-token quotes; require a minimum of 3-5 tokens in `_valid_evidence` (a
  reviewer disagrees: one name can be evidence; decide with a case).
- Link answer claims to evidence ids (citations by id in the answer, checked by code); today the
  guard verifies the collected evidence quotes, not the answer's own sentences.
- Canary: live model resistance is measured for `observe` alone, and there is no end-to-end run
  asserting that the corpus canary books never reach an answer (the four free stages cover the
  prompt boundary and the detection mechanics of every node).
- Eval: record the provider's model revision actually served (the metrics carry the routed model
  name only); the dirty hash does not recurse into untracked directories.
- Partial re-ingest and `ayl-add` check the index fingerprint before writing; still open: a staging
  completion marker.
- `library.search`'s book filter is still a quoted SQL string; move it to the `lancedb.expr`
  builder the chapter filters use (LanceDB has no bound parameters, but `col` / `lit` / `contains`
  are pushed down as an expression; `Expr.to_sql()` is a lossy debugging rendering and must never be
  fed back into `.where()`; `contains` matches literally, so `%` and `_` are not wildcards; there
  is no `starts_with` / `like`, so the bare-title narrowing is a `contains` confirmed exactly in
  Python; the dependency floor is `lancedb>=0.34` for that reason).
- A chapter miss costs four filtered scans: two section variants ("Chapter 59" / "59") x (exact
  key, `contains` fallback), and no scalar index exists on `book` or `section` (the only index is
  FTS on `text`). A scalar index on those columns, or skipping the fallback when the exact query
  for the first variant already found the book under another section, is future work. The row
  cap (1,000) still truncates a single section longer than that (logged) and, on the bare-title
  fallback, is refused as `ambiguous` because candidate books may have been cut.
- **The egress test's "Ollama is not running" port is reserved on UDP, which is not the same as
  owning it.** `tests/egress_guard.py`'s `reserved_loopback_port` needs two things at once: a port
  nothing else can take for the length of the run, and a connection to it that fails *fast* and as
  ECONNREFUSED, because that is what "Ollama is not running" looks like. Holding a bound,
  non-listening TCP socket gives the first and not the second — measured on macOS (Darwin 25.6,
  CPython 3.12): a connect to such a port TIMES OUT, the SYN is dropped, 4.00 s against a 4 s
  deadline, while the same port after the socket closes refuses in 0.00 s (Linux answers RST in
  both cases). Beyond the seconds, the stall changes what is under test: every connect waits out
  its whole connect timeout, the run stops failing on an unreachable endpoint and starts degrading
  into an answer. So the port is held on UDP and left free on TCP — separate port spaces, so the
  kernel will not hand the number out as an ephemeral port while TCP still refuses at once. What
  remains is not a race but a deliberate collision: something choosing to bind this exact TCP port
  in the ephemeral range. Two ways to close it properly, neither done: a held TCP **listener**
  that accepts and immediately closes, with the tests' failure-class assertions loosened from
  "refused" to "no usable reply" (it owns the port outright, at the cost of a fuzzier assertion);
  or a controlled local stub that owns the port and answers a documented 4xx, which is precise but
  is a second server to maintain and a second thing that can be wrong.
- Typed evidence/hit models instead of dicts.
- Sentence splitter consumes closing quotes/brackets into the separator; very long
  punctuation-free sentences exceed the chunk target.
- `ayl-add`: EPUB/PDF input, a generic card generator (paid), measuring retrieval on a non-demo
  folder.
- Enable SQLite foreign keys in the Chainlit schema; a retention/cleanup command for the
  scratchpad and chat history once the tool outgrows single-user local use.
- `pyproject`: declare `langchain-core` as a direct dependency (`llm.py` imports
  `langchain_core.messages` at module import time and the name arrives transitively). `httpx` and
  `openai` are declared since 0.3.1; this item is what is left of that one.
- **There are two httpx distributions in the tree, and the second half of `llm.CallTimeout`
  catches nothing.** The model client's SDK depends on `httpx2` 2.12 while `llm.py` imports
  `httpx` 0.28 for its `Timeout` object and for `CallTimeout`; the two are unrelated packages, and
  `issubclass(httpx2.TimeoutException, httpx.TimeoutException)` is False. So a timeout raised
  inside the SDK's own transport is an `httpx2.TimeoutException` and the `httpx.TimeoutException`
  arm of `CallTimeout` cannot see it. Harmless today — the SDK wraps such a timeout in
  `APITimeoutError`, which is the other arm and is what actually fires — but the comment at
  `llm.py:~228` ("the bare httpx class is kept beside it for a timeout raised before the SDK wraps
  it") is false as written. The same seam is worth a second look next to it: the `httpx.Timeout`
  object `llm.llm()` builds is stored on the SDK's client unconverted (it is not an
  `httpx2.Timeout`), so whether the per-attempt bound is honoured rests on duck typing across two
  packages. Found while writing the egress guard, which had to patch
  both distributions' transports for the same reason (`tests/egress_guard.py`). Recorded, not
  fixed: the fix is in `src/` and belongs to a change of its own.

- **Both README GIFs predate 16.09 and show a badge that no longer exists.** The CLI one shows
  "5/5 traced" over evidence that now splits into book text and book cards; the web one shows the
  old watermark, no source labels on the evidence passages, and opens on Chainlit's login page
  rather than on the chat — its thumbnail, the still a scrolling reader sees, is another product's
  brand and a password field. Captioned honestly for now. Re-record both after the next eval run,
  from the composer and not from the login screen, and check the frames against the badge the
  release actually ships.

## Product / spec decisions

- Language: answer in the language of the question in BOTH locales; the locale should only drive
  UI chrome (currently the `en` profile forces English answers, while the Ukrainian profile
  description promises Ukrainian answers but the instruction says "language of the question").
- Structured citations: evidence IDs -> citations in the answer -> per-claim provenance check.
- Full adversarial injection suite (paraphrase, other languages, unicode obfuscation, metadata
  poisoning, evidence suppression).
- `plan` prompt hardcodes ENGLISH search queries (corpus language); make the corpus language
  configurable.
- `get_chapter` section-name variants ("Chapter 59" vs "59") are a heuristic; store a normalized
  section key at ingest time instead.
- Evidence block in the UI: **whether the passage was cut**, and keeping the passages for restored
  chats. The source-type half of this item closed on 16.09 — every passage now says "book text" or
  "book card (a model-written summary)", and a quote that matched only a card is counted apart from
  the traced ones (`provenance.validate`, `card_only`). The rest is not done: an opened passage
  still does not say that it is the first 1,200 characters of a longer chunk, and a resumed chat
  has no passages at all, because `RunView` lives for one question and nothing persists the
  `hits_log` beside the message.
- **On a phone, the answer after a clarify is gone before it can be read.** Measured on a screen
  recording of the gothic-novel question (two candidates, one clarify) at 390x844 on 15.09, whose
  phase log reads: question sent +13.3 s, the agent asks back +35.4 s, the reply goes in +38.5 s,
  the answer lands +70.8 s, the badge had to be scrolled back INTO view +72.3 s. That last pair is
  the item: the provenance badge and the evidence block render right underneath the answer and
  push it off the top of an 844 px viewport in about a second and a half. Nothing is broken and
  nothing is lost — scrolling up gets it back — but the one thing the reader waited a minute for
  is the one thing they do not get to read. Noticed while scripting `tests/ui`, which does not
  depend on it: the smoke test asserts that text is on the page, never where the page is scrolled
  to. Fix worth considering: keep the answer anchored (scroll to the top of the answer message,
  not to the bottom of the thread) when a badge and an evidence block follow it.
- **A phone reload lands in a new chat, and nobody has decided whether it should.** In a wide
  window Chainlit moves the browser onto `/thread/<id>` a beat after the first answer, so a reload
  restores the conversation. At 390 px it never does: the thread history is off-canvas and is not
  in the DOM until the sidebar toggle is pressed, so the address the reload would need exists only
  as a link behind that toggle, and reloading the page a phone is actually showing opens an empty
  chat. `tests/ui/test_ui_smoke.py` handles both shapes (it opens the sidebar and reads the link),
  which is how the difference was found; what it cannot decide is whether losing the conversation
  on a phone reload is acceptable, a Chainlit setting, or something `ui.py` should do for itself.
- Rate limits and budgets only matter if the UI ever leaves localhost; before any hosted or
  multi-user deployment: isolation, budgets, retention, deployment security, a separate SCA.
- A shorter README and a first-answer path that does not start with a 30-minute ingest (a small
  demo subset with ready questions).
- One-command install: `scripts/install-mac.sh` is the first step of it, not the item. macOS
  only — no Linux, no Windows — and no packaging: no formula, no installer, no published wheel,
  so a reader still clones the repository and runs a script from it. Homebrew stays a
  prerequisite they install themselves (the script prints the official command and exits 1), and
  Ollama stays a prerequisite of the product, one the script installs and starts for the session
  but does not replace — keeping it up across reboots is a login item the reader registers
  themselves. The demo corpus is still a ~30-minute build behind a prompt, so the first answer is
  not one command away either (same item as above).

## Resolved (kept because the open items refer to them)

- **A book card counted as a quote from the book, and nothing on the screen said which was which.**
  The badge read "n/n traced to their source" over an evidence list whose passages could be a
  chapter or a per-book summary one model call wrote at ingest time, and only the section name
  ("Summary", "Key Takeaways") hinted at the difference — ADR-002's recorded consequence,
  "interfaces still do not label evidence by source type". Closed on 16.09 in `provenance.validate`,
  so the CLI, the web chat and the eval harness see one split: `confirmed / unattributed / broken`
  are about the books' own text alone, a quote whose only verbatim match is a card is `card_only`
  and never in the traced count, the denominator is `checked_book_text`, and every item carries
  `source_kind`. Reports published before that date counted card matches inside the triple
  (`docs/evaluation.md`).
- **The first screen of the web chat taught nothing.** One sentence naming four node names, then
  ~1,100 px of nothing and an empty composer: the four behaviours the README claims were on no
  screen that could show them. Closed on 16.09 with `@cl.set_starters` — identify, the catalogue
  count, a question between two books of the shelf, and one the shelf cannot answer — written from
  the loaded index rather than from a hardcoded shelf, and an empty index gets none. The welcome
  message went with it: Chainlit draws its welcome screen only while the thread holds no message.
- **The quote was not located inside the passage it was checked against.** It was printed above
  the passage and the reader was left to find it. Closed on 16.09: `provenance.match_span` locates
  the run over the same normalization the check uses, and the web UI marks it.

- **A question that failed was measured by nothing, and the eval harness was a second execution
  path.** The metrics event was emitted after the `try` in `runner.run_question`, so a run that
  raised reported no metrics at all — the model calls it had already paid for were invisible to the
  CLI, the web UI and the report — and `eval/run_agent_eval.py` drove `graph.stream`, the clarify
  interrupt and the usage reset itself, so the numbers this project publishes were produced by code
  no reader ever runs. Closed on 16.09 (ADR-009 amended): `run_question` returns a `RunResult` —
  the answer, evidence, provenance, the clarify and catalogue fields, the usage snapshot, the wall
  clock and the failure (class and a message with local paths redacted) — the metrics event is
  emitted in a `finally`, and the harness is a consumer of the runner like the other two, with its
  `--clarify-pick` policy as the reply callback. The event contract is unchanged except that
  `by_role` gained `seconds`; the byte-compat report fixture is untouched.

- README quickstart, honest claims, privacy/data-flow, threat model, known limits (AR-31.08,
  CR-03.09); golden split core/extended with fingerprinted artifacts; `--help`/`--version` without
  a key, UI key gate before login, `pyarrow` declared, fresh-clone check green; c09 reworded;
  h12 removed from the core set by the reader on 06.09 (never reader-verified; a character's lie
  taken as fact was its failure), the core set is eleven questions from `v0.2.0-rc1`; the
  canonical failure trace is c06 (`docs/examples/c06-fogg-missing-day.md`).
- **Nothing in the suite could see a connection attempt**, so the local configuration's central
  privacy claim was proved by construction (a faked model, an in-memory library, blanked
  credentials) rather than asserted. Closed by `tests/test_egress_local.py` and
  `tests/egress_guard.py`: an egress guard whose floor is CPython's socket audit hook (every
  socket, whatever its class or import path, background threads and UDP included) with an httpx
  transport layer above it in both installed httpx distributions, refusing anything that is not
  loopback; the real preflight, embedder and compiled graph run under it in the shipped local
  configuration with Ollama not running — every attempt to loopback on the configured Ollama port,
  no hosted provider or tracing endpoint contacted or looked up, and a clean failure on the
  unreachable local runtime instead of a hosted fallback. Controls: each door refusing a
  deliberate attempt, a module that connects at import time, and the same graph under
  `LLM_BACKEND=openrouter` where the attempt to `openrouter.ai:443` is recorded and refused.
  Scope, stated in the test and in `docs/privacy-and-threat-model.md`: one Python process on the
  `runner.run_question` path — not Chainlit, not Ollama, not the browser, not a subprocess.
  Still open: the Chainlit server's own egress is untested, because the `ui` extra is not
  installed in the legs that run this file.
- **Eval reports record single runs.** Closed by `--repeat N` and a JSON sidecar per run
  (`eval/run_agent_eval.py`, ADR-010 amended 15.09): each item runs N times, scoring stays per
  attempt, and both files carry the spread — the boolean rows as how many attempts of N passed,
  cost / seconds / tokens as min / median / max, the totals headline as a range with the
  per-attempt mean beside it, and `--min-pass` as a floor on the weakest attempt. The fingerprint
  says which kind of run it was (`N attempts per item` vs `single run`), and `answers-<ts>.json`
  is the machine-readable record beside the Markdown: the fingerprint as fields, every attempt
  with its answer and its `score()` dict. A run at `--repeat 1` writes the Markdown byte for byte
  as before. Failures are published alongside the numbers, as they already were. **Measured
  16.09**: three local models against both golden sets at `--repeat 3 --record-plans
  --clarify-pick second` on `169b511`
  (`docs/eval-results/2026-09-16-local-models-repeat3.md`), so published numbers carry a spread now
  — and the spread on the behaviour rows is **zero**. No per-question verdict moved on any of
  189 item-attempts; `qwen2.5:32b` was byte-identical on every item of both sets. What the repeat
  measured is latency (30–196 s per question for identical answers on the shipped default).
- **Open decision: the evidence gate's acceptance is met on the shipped default and not on
  `mistral-small3.2:24b-ctx20k`.** Measured 17.09
  (`docs/eval-results/2026-09-16-local-models-repeat3.md`): that model goes `broken` 8–9 → 0 and
  `confirmed == checked_book_text` 50/50, and loses one behavioural PASS on two attempts of three
  (`c03`, `titles 0/1`) plus 6 LLM calls and 502 s a set. Three options are on the table and none is
  adopted: accept the trade as the price of zero broken quotes; let a step whose quotes were all
  dropped count toward the empty streak after the Nth rather than being held (returns `c04` and `c10`
  toward their baseline step counts, does not touch `c03`); or tell `reflect` in-loop that
  unverifiable quotes are being discarded, which is the only option that could move `c03` and is a
  prompt change, so it invalidates every recording and needs its own baseline. `qwen2.5:32b` under
  the gate is unmeasured and would inform the choice.
- **`--record-plans` writes into a committed directory, so it dirties the code stamp and cannot be
  combined with `--require-clean`.** `eval/recordings/` is committed by design, the run fingerprint
  hashes `git diff HEAD` together with the un-ignored untracked files, and the recording is written
  during the run — so a recording run stamps itself dirty, and in a batch each run is stamped by its
  predecessor's file (five different `dirty(...)` checksums over the six runs of 16.09). The gate
  run of the same night is the control: it recorded nothing, still stamped
  `c79018a+dirty(2005429d26f5)` because the baseline's recordings were untracked in the tree, and
  stamped the *same* checksum on both its sets. So the trigger is an un-ignored untracked file, not
  the act of recording. Fix either way: exclude `eval/recordings/` from the dirty hash (it is an
  input the fingerprint already names by checksum through the golden file, and a recording cannot
  change the code that produced it), or write to a staging path outside the hashed set and move the
  file into place once it is finalised. Until then a run whose numbers get published must choose
  between `--require-clean` and a recording, which is the wrong choice to have to make.
- **Verify the clarify path is model-independent.** On the runs of 16.09
  `mistral-small3.2:24b-ctx20k` asked the `c09` clarify, had the choice applied and reported
  `clarify choice applied`, yet its recording holds exactly one plan call per attempt (33 for 11
  items × 3), where both qwen models recorded a second plan call for every clarified item
  (`qwen2.5:14b` 36 calls with one clarify, `qwen2.5:32b` 39 with two). Either the clarify reply
  re-enters the graph without re-planning on some branch, or the recorder misses that call on one of
  the two paths; both are defects and they are not the same defect. Read
  `eval/recordings/en-demo.edc151948a58.*.jsonl` beside the three sidecars' `clarify_*` fields.
- **A hosted run for behaviour spread.** Next, and the reason the row above is not fully closed: at
  `temperature=0` a local model answers the same way every time, so `--repeat` cannot tell a stable
  9/11 from a lucky one on that backend. The question needs a provider that samples —
  `LLM_BACKEND=openrouter`, the core set at `--repeat 3` or more, `--require-clean`, on the user's
  explicit go and inside a named budget. Until then every published behaviour verdict is a single
  behavioural sample however many attempts produced it.
- ADR-012: `SEARCH_HIT_CHARS` is a config knob, default raised 1,200 -> 2,500 after measuring
  1,200 / 2,500 / 4,000 on the core set (c03 complete at 2,500 and 4,000; c06 is not a window
  problem, the answering passage is never in the window).
- ADR-013: `library.search(book=...)` filters both lists; after a resolved clarify retrieval is
  limited to the chosen book; a deterministic coverage gate in `reflect` spends one extra search
  before "enough"/"clarify" when the evidence names at most one book. The first variant (probe the
  most-hit uncovered book of the window) was measured and rejected: it picked a noise book in four
  of four firings. The second variant (identify: the planner's next queued query; answer: a look
  inside a named, uncovered book) is what ships: c09 and h22 offer the right second candidate and
  `--clarify-pick second` reports `applied` on both; the gate is spent after any clarify.
- ADR-014: retrieval/loop ablation on the core set (`eval/run_ablation.py`,
  `docs/eval-results/2026-09-05-ablation-core.md`).
- ADR-015: `uv run ayl-add <folder>` (`src/ask_your_library/ingest/add_folder.py`) indexes a
  folder of .txt/.md files: book key from front matter / first line / file name, chapters from
  Markdown headings or the prose heuristic (shared in `ingest/chapters.py`), the demo pipeline's
  chunking, embedding, staged publish, FTS rebuild and index stamp, idempotent per book,
  model-mismatch refusal before any embedding call; cards are not generated; search and preflight
  treat a missing cards table as a supported shape.
- Provenance against the cited passage (release pass A3): hits carry `hit_id`, `state.hits_log`
  keeps every passage as observe saw it, evidence is pinned to its hit (book/section from the
  record), and `validate` requires the whole normalized quote to be contiguous in that passage:
  fabricated short sentences, spliced sentences, wrong-passage attribution and service text no
  longer confirm. Statuses partition `checked`. The scratchpad is a human log only.
  `AYL_STRICT_HIT_ID=0` resolves a missing hit_id by the quote instead of dropping the item.
- `read_chapters` entries carry a status (`book|section|complete|partial|empty`); prompts say
  "attempted", never "fully read"; an `empty` read does not count as a drill-down in the eval;
  UI and CLI show the real stop reason. An empty chapter read no longer counts as read: the book
  resolves by exact key or exact title part, an empty read yields no hit (logged in the scratchpad
  outside any <<<hit>>> block, chapter still recorded so reflect does not loop), and a cut chapter
  carries a "chapter continues" marker inside the observe budget (`CHAPTER_HIT_CHARS` = 12,000).
- `get_chapter`: the book is in the `where` clause via the `lancedb.expr` builder (the exact key,
  then a narrowed query for a bare title), `rows_for_book` is the exact confirmation after it; a
  bare title shared by two authors is refused (`ambiguous`), never resolved by row order.
- `search_both`: both corpora on one connection with one embedding (`_search_corpus`).
- The badge counts evidence passages ("evidence passages traced"); every evidence item opens to
  the passage it was checked against in the web UI (`ask-library --verbose` in the CLI).
- Canary: four deterministic, free stages (`--no-live`): the prompt boundary of observe / reflect
  / clarify / synthesize (marker only in data-block bodies or neutralized attributes, every
  untrusted `<` neutralized, no forged `<result>` / `<evidence>`), positive and negative detection
  controls for the clarify question and the answer, and the UI render path, with
  `tests/test_injection_canary.py` breaking the defense on purpose to prove each stage can fail.
- LLM client timeout and retry policy, per-question deadline (`LLM_TIMEOUT_S`, `LLM_MAX_RETRIES`,
  `QUESTION_DEADLINE_S`, `--deadline`); `nodes.py` split (llm client, prompts, nodes, clarify
  resolver, coverage gate, provenance engine); loop budgets as config knobs; end-to-end tests of
  the real graph with a scripted model (`tests/test_graph_e2e.py`); `plan` degrades on malformed
  JSON; eval validates requested ids and records per-question cost and tokens. Pinned since
  15.09: the golden files' own shape (`tests/test_golden_schema.py` — the keys each file allows,
  so a misspelled `expected_behaviour` fails instead of being ignored, required keys, types,
  ids unique across the three sets, no question asked twice) and the `expected_facts` /
  `facts_ok` row (`tests/test_agent_eval_facts.py` — the matching rule, the empty case, and that
  the facts do not move `behavior_ok`).
- Non-goals documented in `docs/known-limits.md`: re-ingest per corpus change (and the staged
  rebuild of `ayl-add`), `get_chapter` caps, EN/UA-only injection patterns.
- **The web UI's release walkthrough was a manual pass before every release** (the release-status
  item above): first start, login, a question, the live steps, the badge, an evidence passage
  opened, the catalogue answer, a reload that restores the chat, a clarify left unanswered. Closed
  on 2026-09-15 by `tests/ui/test_ui_smoke.py`, which drives a real `chainlit run ui.py --headless`
  with Playwright at 1280x800 and 390x844, and by the `ui-smoke` CI job that installs the browser
  and uploads a screenshot of any failing page. It needs no model, no key and no index: the seam
  is `AYL_UI_FAKE_BACKEND` plus its spelled-out confirmation
  (`src/ask_your_library/fake_backend.py`, `docs/configuration.md`, `SECURITY.md`), which loads
  `tests/ui/scripted_backend.py` into the server process and replaces the model, the two retrieval
  functions, the catalogue reader and the preflight — the same substitution `tests/test_graph_e2e.py`
  makes in-process. With neither variable set nothing is loaded and nothing is patched.
- Workflow linter: a `workflows` job in `ci.yml` runs actionlint (release tarball, SHA-256
  verified, no third-party action) over every file under `.github/workflows/`, shellcheck included
  since it ships on `ubuntu-latest`, pyflakes not installed so it stays off; first run found
  nothing to fix in the three existing workflows. `workflows` was added to the ruleset's required
  checks on 2026-09-15, so there are eight (the seven above plus this one).
