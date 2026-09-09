# Changelog

## Unreleased

- **Catalogue questions are answered by code (ADR-016).** "How many books do I have, and what
  are they called?" went through the research loop and came back with a sample: fourteen titles
  under a heading that said seventeen, of thirty-three, after four searches (the owner's first
  question to the web UI on 08.09). The planner has a third mode, `catalog`, in which it only
  names the operation (`count`, `list`, `has` a title, `by_author`); code reads the distinct book
  keys of both index tables (`library.list_books`, the demo's canary fixtures excluded by their
  `source` column), validates the operation, resolves a title or an author against that list
  (exact, contained as whole words, or a close match for a typo) and formats the answer, so the
  number in the answer is the length of the list under it and nothing can be listed that is not
  in the index. One model call, no search step; the CLI and the web UI show one `catalog` step
  and a "catalogue answer" badge instead of a quote count. A content question that names one
  book is answered from that book: the planner repeats the name, code resolves it, and retrieval
  is limited to the resolved key, as after a clarify; a name that matches nothing is searched
  everywhere and the answer says so; an operation the planner invents, or a catalogue request
  after a clarify reply, takes the research loop and the event says which; so does a question
  that also asks about content ("Do I have Dracula, and why does Harker stay?"), through a
  conservative gate on content vocabulary, with the named book as the retrieval filter (the
  gate knows words, not titles hidden in a question: routing beyond that vocabulary stays the
  planner's reading, measured by the set's negative controls). The list never reaches the model: the conversation memory keeps only the
  shape of a catalogue answer (operation, counts, the name asked about), never the titles, in
  the CLI, the web UI and a resumed chat (a tracing exporter, when enabled, still receives the
  graph state, the list included; the privacy section says so). An explicit author in a name
  ("Shared Title — Author Two", "Shared Title by Author Two") is a constraint: the other
  author's book with the same title is never confirmed, and an author who wrote neither
  resolves to nothing with both books as the closest. A book that also carries a
  canary-sourced row stays listed: only a key whose every row is a canary is a fixture. New eval set
  `eval/golden/en-demo-catalog.yaml`: type `catalog`, scored on the structured result with strict
  set equality against the manifest KEYS, "Title — Author" (one book too many fails, so does the
  right title under a wrong author, and the count must be the length of the list), against the
  size of the catalogue the item was written for
  (`expected_total`, which a targeted run of one or two items would otherwise never touch),
  three content questions as negative controls (one scored on routing alone) and one
  hybrid item that pins the named-book filter; a research question answered by the catalogue
  path fails its item. Tests: `tests/test_catalog.py` (`list_books` on a real index
  in tmp, the resolver, the answers in both languages, the planner-side guards) and ten
  end-to-end runs of the graph. An earlier run of the set routed the hybrid item to the
  catalogue ("has Dracula: yes", the content part unanswered): one sentence in the planner
  prompt and the gate above closed it; routing beyond the gate's vocabulary is measured, not
  enforced. The set's measured numbers are in the README's Evaluation section.
  Name resolution reads containment in one direction only: a name inside a title matches
  ("Time Machine" is The Time Machine), a title inside a longer name never does. "Dracula's
  Guest" is a different book from "Dracula", and the answer now says so and names Dracula as
  the closest title, where before it confirmed the book as held (and, as a retrieval filter,
  quietly searched Dracula alone). For titles that is decided before the close match for a
  typo, which is close enough to confirm another work by itself: "Dracula II" is 0.824 alike to
  a held "Dracula", over the 0.8 cutoff, so both the loose and the strict resolver used to
  answer it with Dracula. For authors the order is the other way round, so that "Sir Arthur
  Conan Doyle" (0.9) still resolves to the man on the shelf — a longer title is another work, a
  longer author name is usually the same person with an honorific or a middle name.
  An empty strict result is no longer read as "no such book"
  either: a one-word fragment of a held title ("Time") sets no filter and says nothing, instead
  of opening the answer with a note that a book on the shelf is not in the catalogue.
  The gate's vocabulary keeps "who" / "хто" as content words ("do I have Dracula, and who kills
  Lucy?" asks about the book), exempting only the authorship construction — "who wrote them",
  "who is the author", "who are their authors", "хто (їх) написав" — where an author is a
  catalogue attribute and the listing answers that half itself. And the title of a
  book the catalogue resolves is removed from the question before the vocabulary check, one
  occurrence of it, so that a book called "Why" does not take the reader's own "why" with it:
  "Do I have Where the Wild Things Are?" and "Чи є в мене «Як гартувалася сталь»?" are answered
  from the catalogue instead of ending as "I don't know" about a book on the shelf; the same
  question shape about a book nobody has still takes the research loop.
  A clarify that fires on the last allowed step settles both book fields too. The plan that
  answers it returns no search, and a state channel an update leaves out keeps the value it
  had, so a run that started with a name the catalogue does not hold and ended with the reader
  choosing a book that IS on the shelf still opened its answer with the "not in the library
  catalogue" note about the earlier name.
  The catalogue reader refuses a partial index: the listing is presented as exhaustive, so the
  full-text table is required (as it is for the preflight) and a table that disappears between
  the check and the read is an error naming the table, not a short list; a table without the
  `source` column is read as a library without canaries rather than failing. A catalogue read
  that fails inside `plan` costs the retrieval filter only: the question is planned without one
  and the whole library is searched, since before this path `plan` never touched the index and
  a failure there would end a question the research loop could still answer.
  The eval scorer pins more of the same result: the operation the code ran (`expected_op` on
  k01-k06), the size of the whole catalogue (`expected_total`, required on every `catalog` item
  — an item expecting nothing found used to pass over an empty index, and a targeted run of
  k03-k05 over any non-empty one), and, for the research control, that the planner routed the
  question
  itself, since a planner or catalogue fallback searched for another reason. The golden checksum in
  the run fingerprint changes with those keys and with the switch to full book keys, so numbers
  measured before and after are not the
  same run. The CI guard on the golden files now requires a `catalog` item's `expected_books` to
  BE manifest keys (they are scored by set equality, where a substring or a bare title can only
  fail), its `expected_count` to agree with them, and its `expected_total` to be the number of
  books in the manifest.
  A resumed web chat rebuilds its conversation memory unescaped: the persisted answer carries
  the HTML escaping it was rendered with, and `&amp;` belongs on the page, not in the next
  planner and synthesize prompt.
- **httpx2 2.12.0.** The lockfile moves `httpx2` (and its `httpcore2`) from 2.10.0 to 2.12.0, the
  release that closes the three advisories the dependency scan reported on 08.09 against an
  unchanged lockfile (`GHSA-8xx6-hgc6-gc2m`, `GHSA-h4x7-gw46-3wm6`, `GHSA-pf96-p4fj-6566`; the
  first is rated high). Nothing else in the lock changes; the suite passes on the new versions.
- **Chat titles in the sidebar.** `auto_tag_thread` is now off in `.chainlit/config.toml`. With it
  on, the first message of every chat asked the SQLAlchemy data layer to insert the thread with
  `tags=[chat profile]`; SQLite refuses a Python list, the data layer only logs the failure, and the
  insert that carried the title was lost with it, so any chat saved with the previous config is
  untitled in the sidebar. The chat profile is not lost by not tagging: the session's end writes
  it into the thread's metadata, which `on_chat_resume` reads (a session that never ends cleanly
  falls back to the default language, as before). A data-layer subclass that serializes the tags
  was the alternative; nothing in the app reads thread tags, so the flag is the smaller change.
  Not a 2.12.0 regression: the data layer's code is the same in 2.11.1 (upstream Chainlit issue
  2528). Three tests in `tests/test_ui.py` pin the reason: the title must persist with the shipped
  config, the flag stays off while SQLite still rejects the list (the logged reason included),
  and the config file keeps it off. Chats saved before this change keep no title; rename them
  from the sidebar.
- **Chainlit 2.12.0.** The `ui` extra now requires `chainlit>=2.12` and the lockfile moves from
  2.11.1 to 2.12.0 (the only other change is the removal of `audioop-lts`, a transitive
  dependency the new release no longer needs; nothing the agent runs changes). 2.12.0 is the
  release that closes the two MCP advisories recorded with exceptions in `osv-scanner.toml`; the
  exceptions are removed, and the pre-2.12.0 MCP transport sections are removed from
  `.chainlit/config.toml` (MCP stays disabled; the new schema declares servers server-side).
  Verified: unit and UI suites, the injection canary's mechanics stages, and a headless start of
  the web UI on loopback.
- **Security CI.** `.github/workflows/security.yml`: gitleaks (a release binary verified against
  a pinned SHA-256) over the complete range of a pull request (merge base to head, merged
  branches included), over the pushed range on `main`, and over the whole history once a week;
  OSV-Scanner over `uv.lock`, on every pull request, every push to `main` and once a week. Neither job is
  `continue-on-error`, so a scanner that cannot run is a failed check, not a silent pass. The two
  Chainlit 2.11.1 MCP advisories — `GHSA-w3fx-mc44-mf6j` (CVE-2026-45018, command injection over
  stdio) and `GHSA-hvfh-5mj3-5f3j` (CVE-2026-45019, SSRF over SSE and streamable-http) — were
  recorded in `osv-scanner.toml` as dated exceptions with the mitigation already shipped (MCP off
  in `.chainlit/config.toml`) until the Chainlit 2.12.0 entry above closed them; an advisory
  without an exception fails the job. Every third-party action in both workflows is pinned to a commit SHA with its version in a
  comment, and `.github/dependabot.yml` proposes weekly grouped updates for the uv lockfile and
  for the actions. `SECURITY.md` gains an "Automated checks" section with the policy.

## 0.2.0-rc1 (2026-09-07) — release candidate

- **Measured.** Tag `v0.2.0-rc1` = `33dba3f` (the merge of #74), single runs on 07.09 with
  `--require-clean`, strict hit-id, the same bge-m3 index as v0.1.0, Sonnet 4.6 via OpenRouter:
  core (11 questions) behaviour 11/11, quote provenance 47 / 0 / 0, $0.0488 mean per question, AI
  pre-check 10 correct / 0 incorrect / 1 incomplete (c06: the discovery scene not retrieved, the
  gap filled from the book card's plot summary); extended
  (21) 18/21, 73 / 0 / 0, $0.0429, the three failures the known gaps (q06 no clarify, h13 no
  drill-down, h17 Doyle side never retrieved; h22 now clarifies); retrieval unchanged (core 8/8 and
  2/2, extended 12/12 and 3/5); canary 6/6 checks passed, the live `observe` call BLOCKED. Every row carries its stop
  reason; no planner fallback and no deadline cut on either set. Targeted `--clarify-pick second`
  runs of c09 and h22: the choice applied, the answer drawn from the chosen book. Against v0.1.0
  the window and the gate together cost +39% per core question and +57% extended. Reports under
  `docs/eval-results/2026-09-07-v0.2.0-rc1-*.md` (core and extended with the targeted
  second-candidate runs as appendices, retrieval and canary in one file), verbatim harness output under a provenance
  header; the README table now has a v0.1.0 and a v0.2.0-rc1 column per set. The reader graded
  the eleven rc1 core answers on 07.09 in the core report: ten correct, c06 incomplete, agreeing
  with the pre-check; the example traces stay from the v0.1.0 run.
- **Version `0.2.0rc1`** in `pyproject.toml` and `uv.lock`; `ask-library --version` prints it. The
  tag `v0.2.0-rc1` itself still carries `0.1.0` (the bump landed after the measurement, which
  changes nothing the agent runs).
- **Public-release pass.** `NOTICE` (Apache-2.0 attribution), `SECURITY.md` (scope, how to report),
  `corpus/README.md` (what is committed, from where, under which statements); the README's License
  section points to them and the Evaluation section says where the measured code lives and how it
  relates to this repository's first commit. `docs/eval-results/` keeps the tagged baselines and
  the current reports (v0.1.0 core and extended, the 05.09 core summary the c06 trace cites, the
  ablation, the v0.2.0-rc1 core and extended reports with their targeted runs as appendices, the
  rc1 retrieval and canary outputs in one file); intermediate development reports stay in the
  development history. Review credits removed from test docstrings and one code comment (the
  invariants they explained stay); `.gitignore` covers `.env.*`, SQLite sidecars, `.files/` and
  `.DS_Store`; the backlog reads as open items plus a resolved list, without process headings.

- **Pre-rc1 audit fixes.** `plan` treats a non-list `queries` container (a number, `true`, one
  string, an object) as no plan: the raw-question fallback, announced, instead of a crash or a
  search of the string's letters. An empty clarify reply (the web UI's timeout) is a real resume
  and no longer bypasses the question deadline. The eval result carries `stop_reason` and the
  steps log records a reflect stop, so a run cut by the deadline and one written after "enough"
  read differently in the report. A test fixture no longer carries a real key prefix that the
  snapshot's private-marker guard rejects.
- **Docs after the pre-rc1 audit.** README: the headline provenance claim names what is checked
  (the collected evidence quotes, not the answer's own sentences); the fully-local recipe says
  how tracing really switches on (a LangSmith key in the environment) and how to keep it off;
  the time budget is described as a budget for continuing the search, with httpx's read timeout
  named for what it bounds; the canary's coverage is listed node by node. The four ADR-013
  measurement reports were committed with provenance headers and their primary provenance numbers
  (development history; not exported).

- **Openable evidence passages.** `validate` reports every evidence item with its verdict
  (`provenance.items`: confirmed / unattributed / broken, in evidence order). The web UI shows,
  under the badge, one expandable block per retrieved passage: book, section, hit id and the
  verdict counts in the summary; inside, every quote checked against it with its verdict, then
  the passage as observe saw it (escaped, image-free, line breaks as `<br>` so a card's
  paragraphs cannot break out of the block). `ask-library --verbose` prints the same list, one
  passage per hit, control characters stripped. The badge stays a count; this is what the
  audits asked for first: the reader can see the source of every quote without the scratchpad.

- **`plan` degrades on malformed JSON** like `observe` and `reflect` already did: after the one
  retry the raw question becomes the single search query, mode `answer`, and the plan event
  carries `plan_fallback` (also when valid JSON held no usable query) so the CLI, the web UI and
  the eval report say so. A local model that cannot produce JSON no longer ends the question
  with an error. A query that looks like one of the loop's own markers (`__chapter__|`,
  `__book__|`, `__clarify__`) is never obeyed, whether from the planner, the queue or the
  question itself: only `reflect` decides a chapter read, a probe or a clarify, and `act`
  ignores a malformed marker instead of raising.

- **Time budgets.** The client gets `LLM_TIMEOUT_S` (120 s hosted / 600 s local per attempt,
  tightening the SDK's 600 s default; connect stays 5 s) and `LLM_MAX_RETRIES` (2, the SDK's
  default made explicit): the timeout is httpx's read timeout, i.e. the wait for the next chunk
  of a response, so it cuts a provider that stops answering, not one that keeps streaming
  slowly. `QUESTION_DEADLINE_S` (300 s, `0` = none, `ask-library --deadline` per run) is a
  budget for continuing the search, checked by the loop before each next decision and never
  mid-call: the step in flight and the synthesis complete, then the answer is written from the
  evidence so far with the stop reason "question deadline reached". Neither is a hard deadline
  on a question (README, Known limits). Time waiting for a clarify reply is not counted. The
  eval fingerprint names the deadline. `MAX_STEPS` was never a time budget (third audit, 05.09).

- **End-to-end tests of the real graph.** `tests/test_graph_e2e.py` runs the compiled LangGraph
  through `runner.run_question` with a scripted model (faked at the `ChatOpenAI` factory, so the
  client's accounting runs) and an in-memory library: node order and the event contract, the
  clarify interrupt and resume with the book filter, an unresolved reply, the chapter drill-down
  and its repeat guard, an empty read, the CRAG gate, the step limit, the coverage probe, the
  JSON fallbacks of observe and reflect, the hit cut, the sanitizer on the retrieval path, an
  ambiguous or cut chapter read and the three provenance verdicts. Fifteen scenarios, no model,
  no database.

- **`nodes.py` split, no behaviour change.** The model client (`llm.py`: ChatOpenAI, usage
  accounting, `data_block`, `ask_json`, one `str_field` schema helper), the prompt rules
  (`prompts.py`), the clarify resolver (`clarify.py`), the coverage gate (`coverage.py`) and the
  provenance engine (`provenance.py`: evidence gate and `validate`) are modules of their own;
  `nodes.py` keeps the seven graph nodes and the routers. `title_of` lives in `library.py` next
  to the key separator. The loop budgets are config knobs (`MAX_STEPS`, `MAX_EMPTY_STREAK`,
  `MAX_CLARIFY_CANDIDATES`, the last capped at the resolver's five ordinals) and the eval
  fingerprint names the step and candidate budgets; a blank knob line in a copied `.env` means
  the default. Tests and the eval
  scripts patch the model client in `ask_your_library.llm`, the only place a model is called.
- **h12 removed from the core golden set by the reader (06.09).** It was never reader-verified,
  and the failure it demonstrated was a character's lie quoted as fact; the reader dropped it
  rather than keep an unverified item as the headline failure.
  `docs/examples/c06-fogg-missing-day.md` is now the committed failure trace: behaviour PASS, quote provenance 2/2 and an answer that is
  still incomplete, because the passage that answers the question was never retrieved. The core
  set is eleven questions from the next tag; the `v0.1.0`, rc1 and ablation artifacts keep their
  h12 rows as the record of runs over the twelve-question set and are not recomputed.

- **Fully local mode.** `LLM_BACKEND=ollama` runs every agent node on a local model through
  Ollama's OpenAI-compatible endpoint (`OLLAMA_LLM_MODEL`, default `qwen3.6`): no key, no
  account, cost lines read $0; preflight checks that the model is pulled; the UI's key gate and
  the CLI's key check are off in this mode. Embeddings were local by default already, so `ayl-add`
  never needed an account. Quality is not measured for local models; the README says so.

- **Ollama preflight tails.** A reply from `OLLAMA_URL` that preflight cannot read (not JSON, or
  not the shape of `/api/tags`) is now its own message instead of the unreachable one, which sent
  people to `ollama serve` for a port that usually holds something else; the body is read whenever
  either backend is Ollama, so local embeddings behind a hosted model fail here rather than on the
  first search. An HTTP 4xx/5xx belongs there too — a server did answer — and the message names
  the status; only a request that never got an answer still reads "Could not reach Ollama at ...".
  An empty model list is a valid reply however Ollama encodes it (`[]` or a Go `null`): the remedy
  is `ollama pull`, not "check the address". With local embeddings the embedding model
  (`OLLAMA_EMBED_MODEL`, default `bge-m3`) must be pulled as well, so a reachable Ollama without it
  is caught here instead of on the first search. The preflight and UI tests pin the backend, so they
  no longer go red in a shell with `LLM_BACKEND=ollama`, and CI runs the suite under both backends.

- **First-run tails.** `ask-library --help` / `--version` now answer before the preflight, so
  they work in a fresh clone with no key and no index (question and `--lang` via argparse); a
  failed single question (`ask-library "..."`) exits 1 instead of 0, so a script or an eval sees
  the failure the message already described — the interactive loop still keeps going; the
  web UI refuses to start without an OpenRouter key instead of reporting it only to someone who
  has already logged in (`AYL_ALLOW_START_WITHOUT_KEY=1` to import it anyway); `pyarrow` is
  declared as the direct dependency the ingest package always was; and the configuration table
  documents `AYL_STRICT_HIT_ID`, `AYL_CHAINLIT_DIR` and `LANGCHAIN_TRACING_V2`.
- **A follow-up question is a choice; cost shown at the pause.** When the clarify question
  offered exactly one book ("is this the one?") and the reader answers with a follow-up that
  names no book and rejects nothing ("what has he said when he saw them first?"), that book is
  the choice (was: unresolved, so the next search ran over every book again); once a book is
  chosen the loop is in answer mode by code, not at the planner's discretion. The run paused at
  a clarify now reports its cost so far (CLI line, UI line, `partial: true` metrics event); the
  final event still covers the whole run once.

- **The injection canary now proves the mechanics for `observe`, `reflect`, `clarify`, `synthesize`
  and the UI path, for free.** Five deterministic stages (`uv run eval/injection_canary.py
  --no-live`, no LLM call: sanitizer, observe controls, prompt boundary, detection, UI) check the
  prompt boundary of those nodes (a hostile marker reaches only data-block
  bodies or neutralized attributes of the user message, every untrusted `<` is neutralized, a
  crafted book title cannot forge a `<result>` or `<evidence>` delimiter), positive and negative
  detection controls for the clarify question and the answer, and the UI render path; the single
  live `observe` call stays last and stays the only paid one. `plan` with a hostile clarification
  reply is not covered by the canary.
- **Book filter after clarify and a coverage gate (ADR-013).** `library.search(book=...)`
  constrains both lists; after a resolved clarify the search itself is limited to the chosen
  book. `reflect` spends one extra search before stopping with evidence for at most one book:
  in identify mode the planner's next queued query, in answer mode a look inside a second book
  the question names by title or author surname (whole-word). CLI and UI show the step as
  "coverage gate". Measured 06.09 (window 2,500, single runs): core 12/12 with c09 now offering
  Gulliver as the second candidate and `--clarify-pick second` reporting `applied`; extended
  18/21 in the default run (h22 now asks; its reply stays unresolved in that mode) and 17/21
  with `--clarify-pick second` (h22 `applied`; h11 a title-less answer); q06 still never asks;
  h17's Doyle side is never retrieved by any query, a retrieval limit the gate cannot cross;
  cost +24% (core) and +21% (extended) per question over the 2,500 baseline. Provenance in those
  four runs (confirmed / unattributed / broken): core default 49 / 0 / 1 at $0.0478 mean (the one
  broken quote on c03, flagged by the validator), core `--clarify-pick second` 40 / 0 / 0 at
  $0.0415, extended default 72 / 0 / 0 at $0.0420, extended pick-second 70 / 0 / 0 at $0.0404;
  reports kept in the development history as `2026-09-06-adr013-*.md` (the 06.09 summaries had
  quoted 40 / 0 / 0 for the core default run, which was the pick-second figure). The first
  variant (probe the most-hit uncovered book) was measured and rejected: it picked noise books;
  see docs/backlog.md.

- **Generic ingest (`ayl-add`) no longer drops any of your text, adds no spurious sections, and
  section names are unique.** The demo corpus's table-of-contents heuristics (a 200-character
  minimum body per heading, and discarding everything before the first heading) applied to your
  own files too, so a short-but-real `CHAPTER I` and the preamble in front of it vanished from
  the index without a word — the `Full text` fallback did not trigger, because one chapter had
  been recognised. The generic path now keeps every heading whatever its body length and keeps
  the text before the first heading as a `Front matter` section; the demo pipeline keeps the
  filtering (and the detector is unchanged for it).
  - **Contents pages are merged, not dropped and not turned into sections.** Keeping every
    heading meant a raw Gutenberg `.txt` opened one tiny section per contents line, and those
    took the bare names, so `unique_titles` renamed the REAL chapters to `CHAPTER I (2)` — and
    `read_chapter` addresses a chapter by (book, section), so drilling into chapter one landed
    on a line of the contents page. A heading whose body is under `MIN_CHAPTER_CHARS` **and**
    whose title reappears later in the file is now read as a contents line: its heading line and
    its text are merged into the preceding section (into `Front matter` before the first real
    section) instead of opening one, so every character of the file is still indexed and the
    real chapters keep their bare names. Both halves of the test are load-bearing — a short
    heading whose title never comes back is a genuinely short chapter and keeps its own section.
    Each merge is logged (title, body length, target section) and counted in the run summary and
    in `--dry-run` (`N short headings merged into their preceding section`).
  - Separately, `unique_titles` counted original titles but never reserved the names it
    generated, so `Chapter I`, `Chapter I`, `Chapter I (2)` emitted `Chapter I (2)` twice; every
    emitted name is now reserved, and since `read_chapter` addresses a chapter by
    (book, section), two sections no longer read as one.

- **Generic local ingest (ADR-015): `uv run ayl-add <folder>`.** A folder of `.txt` / `.md`
  files becomes a queryable index without editing Python. One file = one book; the book key
  (`Title — Author`) comes from YAML front matter, else a standalone first title line
  (`Title — Author` / `Title by Author`), else the file name (`Title.txt` →
  `Title — Unknown`). Chapters come from Markdown `#` / `##` headings, else the demo corpus's
  prose heading heuristic, else a single `Full text` section; repeated section names are
  disambiguated because the section is part of the chunk id. Chunking, embedding, the staged
  publish, the FTS rebuild and the index fingerprint are the demo pipeline's own code, so a
  private library is indexed exactly like the demo corpus. `--dry-run` shows the plan without
  writing; `--cards` is not implemented and says why (cards need a paid LLM call per book).
  - **Updates go through staging, never through the live table.** Adding to an existing index
    builds a staging table from the rows that stay plus the freshly embedded rows of this run,
    and only then replaces the table, rebuilds the FTS index and rewrites the fingerprint. A
    failure part-way (embedding backend dies on book 7) leaves the index exactly as it was; the
    remaining crash window, between the drop and the create, is closed by `recover_staging` on
    the next run. The cost is that an update rewrites the whole table.
  - **Re-adding a book replaces its rows** (idempotent). The row key carries a digest of the
    full book key, so two keys that reduce to the same ASCII slug (two Cyrillic titles) stay
    two books instead of one deleting the other on the next add.
  - **The embedding fingerprint must match exactly** — model and dims — for an existing table.
    A table stamped with another model is refused, as before; a table with no stamp is now
    refused too, instead of being accepted on matching dims and then stamped with a model that
    wrote only part of it (`--stage stamp-meta` or a rebuild is the way out). Both refusals
    happen before the first embedding call.
  - **Symlinks are skipped and reported**, in or out of the folder, as are files under a
    symlinked directory: `is_file()` follows links, so `books/notes.md -> ~/.ssh/id_rsa` would
    otherwise have been read and sent to the embedding backend.
- **Chapter splitting moved into the package** (`ask_your_library.ingest.chapters`) from
  `scripts/ingest_demo_corpus.py`, which now imports it — one detector for every ingest path.
- **Book cards are optional.** `library.search` skips a corpus whose table is absent (logged once
  per process, never silently) and the preflight only requires `transcripts_<backend>`, so an
  index built by `ayl-add` runs the agent as it is. The missing-cards degradation is no longer
  visible only in the server log: `check_environment()` returns it as a non-fatal notice
  (`.notices`, alongside the list of problems it has always been) and the CLI prints it at
  start-up.
- **`library.read_chapter` returns three values on every path.** Without a transcripts table it
  returned a bare `""`, which the caller unpacked into three one-character strings; it now
  returns `("", "", "missing")` like the other empty cases.
- **One embedding and one connection per search step.** `search_both` ran two `search` calls, and
  each embedded the query and opened LanceDB again: two embeddings and two connections on every
  agent step, for one question. Both corpora are now searched on one connection with one
  embedding of the query (`_search_corpus`), in the same order, returning the same hits; `search`
  called on its own is unchanged, and a corpus whose table is absent is still skipped with the
  same once-per-process warning. An index with neither table costs one connection instead of two
  (it never paid for an embedding: `search` returned before embedding when the table was absent).
- **A chapter read asks the database for the book, not just the section.** `read_chapter`
  filtered on `section` alone, took the first 1,000 rows and resolved the book in Python:
  right for 33 books, wrong for a big library, where the cap can cut the wanted book out of the
  candidates before anyone looks for it. The book is now part of the `where` clause — the exact
  index key first, and, when that finds nothing (a bare title from `reflect`, "Don Quixote"), a
  query narrowed to books whose key contains "Don Quixote — ". `rows_for_book` still confirms
  the book in Python, so title-only matching stays exact ("Emma" is not "Emma's Diary") and a
  title shared by two authors is still refused as `ambiguous`. The filters are built with
  LanceDB's expression builder (`lancedb.expr`) and pushed down as expressions, so values
  travel as literals and no SQL is rendered here (`Expr.to_sql()` is a lossy debugging
  rendering only, never something to feed back into `.where()`); `lancedb>=0.34` is the floor
  that has it. The 1,000-row cap no longer decides which book is found on the exact-key path;
  a query that hits it is logged, because a single unstructured "Full text" section can exceed
  it, and when the bare-title fallback query hits it the read is refused as `ambiguous` (the
  candidate books may have been cut, so "one book" is not a fact there) rather than resolved
  by whatever the cap kept.

- **Ablation on the core set** (`eval/run_ablation.py`, ADR-014): the same twelve
  core questions under five conditions — no library, retrieve-then-answer once,
  the loop on cards only, the loop on transcripts only, and the shipped loop —
  scored with the unchanged agent-eval harness. The first run is committed as
  `docs/eval-results/2026-09-05-ablation-core.md`: the loop takes behaviour
  compliance from 6/12 to 12/12 and is what produces the clarify interrupt (quote
  provenance comes from the evidence-and-validation contract, which the ablation
  did not separate from the loop), but on this corpus of well-known classics it
  does not beat the model's own memory on answer content.
- **Observe window 1,200 -> 2,500 characters per search hit** (ADR-012), after measuring
  1,200 / 2,500 / 4,000 on the core set: c03 names both Madame Coquenard and Madame de
  Chevreuse from 2,500 up; behaviour and provenance unchanged; mean cost per core question
  +9% at 2,500 (+32% at 4,000), +28% on the extended set. `SEARCH_HIT_CHARS` and
  `CHAPTER_HIT_CHARS` are environment knobs and part of the eval fingerprint.

## 0.1.0 (2026-09-05) — first tagged release (development repository; nothing was published)

- **Structured quote provenance.** Every retrieved passage gets a stable id
  (`s<step>h<n>`) and is kept in state exactly as `observe` saw it; evidence
  is pinned to its passage (book and section come from the record, not from
  the model); `validate` requires the whole quote, as a normalized whole-token
  sequence, to be contiguous inside the cited passage. Three statuses partition
  the checked evidence: confirmed / unattributed (found in another passage) /
  broken. The scratchpad is a human log only.
- **Chapter reads report their status** (complete / partial / empty); a cut
  chapter carries an in-band marker; a bare title resolves to the indexed
  book; UI and CLI show the real stop reason.
- **Clarify with candidates.** The question lists the candidate books; the
  reply (title, ordinal, English or Ukrainian) resolves to one of them; the
  choice is passed to the planner and later evidence is filtered to it;
  unrecognized replies are reported, never guessed.
- **Golden sets split** into a reader-verified core (12) and an exploratory
  extended set (21); eval artifacts carry a full run fingerprint, including
  a dirty-tree marker; `--require-clean` for release runs; `--clarify-pick`
  diagnostic mode.
- **Export tool** (private, not part of this repository) is fail-closed: marker
  file, symlink and repo/home refusal, gitleaks required, exit codes 2/1/0.
- UI: empty password refused, markdown images neutralized, auth secret
  created with 0600, MCP sub-transports off; prompt delimiters neutralize "<".
- **One book identity across nodes.** A chapter read asked with a bare title
  produces a hit under the index key of the book actually read, so evidence
  from it survives the exact-key filter after a clarify; a bare title shared by
  two authors is refused instead of resolved by row order. `validate` checks
  every evidence item (an answer may cite "Dracula" for "Dracula — Bram
  Stoker"); items for books the answer does not name are counted, not skipped.

## Phase 2 — agent package (Aug 2026)

- Agent, eval harness, CLI (`uv run ask-library`) and Chainlit UI live in this
  repo as the installable `ask_your_library` package; every path/model/price
  is configured through the environment (see `.env.example`).
- Own ingest module (chunking + FTS) replaces the external chunker; verified
  to produce identical chunks on the full demo corpus.
- Fixed a latent telemetry bug in `act()` (injection redaction counted
  `len()` of an int).

## Phase 1 — demo corpus and evals (Aug 2026)

- Open demo corpus: 33 public-domain books (text + LibriVox audio through
  local Whisper) plus 2 synthetic canaries; staged, cached ingest script.
- Golden set with retrieval (hit@2/4/8, MRR) and agent-level evals; CI guard
  keeps golden questions inside the manifest.
- Quote-provenance validator (then called faithfulness) compares word sequences instead of bytes, so honest
  typography changes (markdown bold, curly quotes) no longer read as
  hallucinations while paraphrases still fail.
