# Backlog

Ordered roughly by priority; items graduate into issues when picked up. Items marked (AR-31.08)
come from the independent architect review of 31.08, (CR-03.09) from the second cross-review of
03.09, (audit 04.09) from the independent audit of 04.09, (reviews 05.09) from the full reviews
of 05.09. Resolved items are listed at the end with the mechanism that closed them, because the
open ones often refer to them.

## Release status

- Measured and documented: tag `v0.2.0-rc1` (07.09) with the core and extended reports, retrieval
  and canary outputs, the reader's verdicts on the eleven core answers, and the v0.1.0 baseline
  (`docs/eval-results/`, README "Evaluation").
- Before this tree is called 0.2.0, one item is open: a short live check of the web UI on a clean
  environment — the passage under an evidence item readable in the browser (not merely sent), a
  clarify including the no-reply case, chat restore after a reload, and a first start by the
  README.
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
- At the visibility switch: branch protection on `main` (required checks `test`, `test-ui`,
  `secrets`, `dependencies`; no force-push, no deletion), private vulnerability reporting, push
  protection; then CodeQL and a workflow linter, which are free on a public repository.

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
- Trust boundary: synthesize consumes evidence before validate runs; a "verifying" state in the
  UI, or validation before synthesis.
- Behavioural scoring is heuristic (substring titles, refusal phrase markers); refusal markers are
  loose ("do not have", "доказів") and should be anchored to the library; an LLM judge for answer
  correctness remains future work.
- Eval reports record single runs; repeat runs or state the single-run limitation (the reports
  do); publish failures alongside numbers (they do). Still open from the ablation idea: vector-only
  vs BM25-only, and the planner's rewritten query vs the raw question.

## Retrieval, ingest, eval harness, code quality

- **Book identity is a derived string, and no ingest ledger records what went in.** A book is its
  `Title — Author` key, derived from the file (front matter, a standalone title line, or the file
  name), and every downstream reference — the citation, the chapter filter, the catalogue
  listing — is that string. Correcting `author:` in a file and running `ayl-add` again therefore
  adds a second book instead of renaming the first: the corrected key is indexed and the rows
  under the old one stay until someone removes them by hand; a file removed from the folder keeps
  its rows; a card whose heading differs from its transcript's key by one character lists as two
  books. And since `ayl-add` rebuilds the table (carrying over the rows it did not replace) without
  recording requested / indexed / failed
  per file, "which of my files did not index" cannot be answered either (`list_books` shows what
  is there, never what is missing). The catalogue is exhaustive for what the index holds, which
  is the history of what was ingested, not the current state of the folder (README, Known
  limits). Fix: a `books` table with a stable id that a re-ingest updates in place, and an ingest
  ledger beside it.
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
- Typed evidence/hit models instead of dicts.
- Sentence splitter consumes closing quotes/brackets into the separator; very long
  punctuation-free sentences exceed the chunk target.
- `ayl-add`: EPUB/PDF input, a generic card generator (paid), measuring retrieval on a non-demo
  folder.
- Enable SQLite foreign keys in the Chainlit schema; a retention/cleanup command for the
  scratchpad and chat history once the tool outgrows single-user local use.
- `pyproject`: declare `httpx` and `langchain-core` as direct dependencies (both are imported
  directly and currently arrive transitively).

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
- Evidence block in the UI: show the source type (text / card / transcript) and whether the
  passage was cut; keep the passages for restored chats.
- Rate limits and budgets only matter if the UI ever leaves localhost; before any hosted or
  multi-user deployment: isolation, budgets, retention, deployment security, a separate SCA.
- A shorter README and a first-answer path that does not start with a 30-minute ingest (a small
  demo subset with ready questions).

## Resolved (kept because the open items refer to them)

- README quickstart, honest claims, privacy/data-flow, threat model, known limits (AR-31.08,
  CR-03.09); golden split core/extended with fingerprinted artifacts; `--help`/`--version` without
  a key, UI key gate before login, `pyarrow` declared, fresh-clone check green; c09 reworded;
  h12 removed from the core set by the reader on 06.09 (never reader-verified; a character's lie
  taken as fact was its failure), the core set is eleven questions from `v0.2.0-rc1`; the
  canonical failure trace is c06 (`docs/examples/c06-fogg-missing-day.md`).
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
  JSON; eval validates requested ids and records per-question cost and tokens.
- Non-goals documented in README "Known limits": re-ingest per corpus change (and the staged
  rebuild of `ayl-add`), `get_chapter` caps, EN/UA-only injection patterns.
