# Changelog

## 0.2.1 (unreleased)

- **The shipped default is fully local: no account, no key, no money to try it.** `LLM_BACKEND`
  defaults to `ollama` instead of `openrouter`, so a clone that follows any path — the installer,
  the manual quick start, or `uv run ask-library "..."` with no `.env` at all — answers on a model
  Ollama serves on this machine, and its cost lines read $0.0000 because `OLLAMA_PRICE_*` are 0.
  Nobody has to create a paid account to see whether the thing works. The hosted path is unchanged
  and is now opt-in: `LLM_BACKEND=openrouter` behaves exactly as the default used to, key, prices
  and endpoint included. Everything that hung off the old default followed. The key gates
  (`OPENROUTER_NEEDS_KEY`, `preflight.check_api_key`, `ui.py`'s startup refusal) were already
  conditional and simply stop firing; the UI's refusal now names the local configuration as a way
  out rather than only the key. `.env.example` **is** the local configuration — including the
  local time budgets, `LLM_TIMEOUT_S=600` and `QUESTION_DEADLINE_S=1200`, because a value in a
  copied `.env` wins over `config.py`'s per-backend default — with `ORCHESTRATOR_MODEL` and the
  two `PRICE_*` lines shipped commented out beside a note on what the hosted path costs and that
  it needs an account. That inverts `scripts/install-mac.sh`: `--hosted` is now the mode that
  transforms the example (backend, both time budgets, the three commented lines), and the local
  mode writes it out as it stands. An invalid `LLM_BACKEND` still refuses to start rather than
  falling back — to either backend now, since falling back to the local one would leave a run
  meant for a hosted model asking Ollama for something nobody pulled.
- **A first run with nothing configured ends in an instruction, not a stack trace — and in a
  distinct exit code.** `preflight.check_environment()` records the KIND of each problem beside
  its prose, and `preflight.exit_code()` turns those kinds into the status the CLI exits with:
  `3` no index yet, `4` a hosted backend with no key, `5` Ollama unreachable, not answering as
  Ollama, or missing a configured model, `1` anything else — the status it always was. It is a
  precedence, not a subset test: a fresh clone usually has several problems at once, every one is
  still printed, and the code names the one to fix first, so a wrapper script can act on it
  without matching on translated prose. The unreachable-Ollama message now carries the whole
  remedy, because on a machine where nothing is installed yet the missing step was the install:
  `brew install ollama`, `ollama serve`, then one `ollama pull` per model **this** configuration
  will open (read from `OLLAMA_LLM_MODEL` / `OLLAMA_EMBED_MODEL`, so a run on `nomic-embed-text`
  is not sent to fetch `bge-m3`), or `bash scripts/install-mac.sh`, which does all of it. The
  missing-index message names `ayl-add` beside the demo build. `install-mac.sh` closes on the
  exact next command, in the order it works: the corpus build first when there is no index
  (`ask-library` before it would exit 3 on that same message), the reader's own `ayl-add` instead
  under `--no-demo`, then the first question with the sentence the mode exists for — no account,
  no key, nothing to pay, the local model named.
- **Every eval harness states the backend it ran with.** `run_fingerprint()` — and therefore
  `run_ablation.py`, which imports it — prints `model <name> via <backend>`; the injection canary
  opens with the answering model and backend it is about to test; `run_retrieval_eval.py`, which
  calls no answering model, names the embedder instead. The backend used to go unsaid, and unsaid
  meant the hosted default, which would now leave the reports in `docs/eval-results/`
  indistinguishable from a free local run. **No measured number was touched.** Those reports were
  produced on the hosted configuration, and the README's results table, `docs/evaluation.md` and
  `docs/cost.md` now say so where they present them, together with the fact that the default
  configuration is local and free and is not what any of them measures.
- **The README is a front page, and the long text is in `docs/`.** What the project is, the
  architecture and the quote check, the manual quick start, the settings table, the evaluation
  narrative, privacy and the threat model, the injection layers, cost and the known limits moved
  out of the README into nine pages under `docs/` — `overview.md`, `architecture.md`,
  `quick-start.md`, `configuration.md`, `add-your-own-books.md`, `evaluation.md`,
  `privacy-and-threat-model.md`, `cost.md` and `known-limits.md` — sentence for sentence. Three
  classes of edit were made to that text and nothing else: relative links rewritten to resolve
  from `docs/`, headings renamed or moved a level (`## License` is `## Status and licence` on the
  front page), and three sentences added where a page needed a qualification the README's own
  context used to carry — `--print-env-resolution` in `quick-start.md`, the hosted-path scope of
  the cache-read counter in `cost.md`, and which README "this README" points at in
  `configuration.md`. Every one of them is a separate added sentence, not a rewrite of the moved
  text; a line-by-line check of the base README against the new tree leaves no prose residual.
  The README keeps the macOS install, the first question, the measured-results table and a
  five-line privacy-and-cost summary, and gains one Mermaid diagram: the flow in plain terms. The
  architecture as an offline and an online subgraph opens `docs/architecture.md` instead, above the
  control-flow diagram that page already carried, which now wears the same CODE / AI / HUMAN legend
  with its nodes and edge labels untouched; both diagrams are reconciled against `graph.py`
  and `nodes.py` — the catalogue node and `validate` are in them, `synthesize` runs before
  `validate` and `validate` only reports, and both the CRAG gate and the deterministic coverage
  gate sit on the `reflect` edge, where the code puts them. The course-demo
  Excalidraw originals are kept as editable sources in `docs/diagrams/`. Every reference that
  pointed into the README — `SECURITY.md`, the ADRs, the backlog, an example trace, four test
  files and the message `install-mac.sh` prints on a non-macOS system — now names the page
  that holds the text. The README also carries two recorded runs, one per way of asking.
  `docs/img/ask-library-demo.gif` (87 KB) is the CLI on a half-remembered question — a man who ends
  up on an island and comes across cannibals, no title given, which is the `identify` path —
  answered by `qwen2.5:14b`, the default local model `scripts/install-mac.sh` pulls, over the demo
  corpus with no API key: the plan, both search steps, the chapter read, the answer naming Robinson
  Crusoe and saying why, and the quote check reporting all three quotes found verbatim — the whole
  run stands in the frame the GIF holds for eight seconds. The caption quotes the figure the CLI
  itself prints there, 147.7 s, and that one is a cold-cache number: the same block reports
  `cache: 436 tokens read from cache`, so it is what a first ask costs on this machine rather than
  a warm-cache artefact. `docs/img/ask-library-ui.gif` (828 KB) is the web UI on a different
  question — what d'Artagnan said before fighting three men at once, and why — answered by the
  hosted model `anthropic/claude-sonnet-4.6` through OpenRouter, with the embeddings still
  local. It ends on the green quote-provenance badge reading `evidence passages 5/5 traced to their
  source`, with the Chapter V passage opened under it and the quote sitting on the text it was
  checked against; the caption quotes the $0.0724 the UI's own metrics line reports. That question
  is on the hosted model because the local one cannot carry it: asked the same thing,
  `qwen2.5:14b` found the right book and then invented one of its two quotes — a sentence that
  appears nowhere in the text — which the validator flagged as `WARNING: 1 of 2 quotes NOT found
  verbatim`. The check did its job either way, and the two GIFs now show both halves of the trade
  the docs describe: what the free local default answers well, and the question that needs the
  hosted model before every quote comes back confirmed.
  `docs/quick-start.md` lists `--print-env-resolution` with the other installer flags.
- **The stripped control-character class is assembled, not written as a range.** CodeQL's
  `py/overly-large-range` flagged `[\x00-\x08\x0e-\x1f…]` in `sanitize.py`, and the reason a checker
  can say that is the reason the rule exists: a range is read by its two endpoints, so how far it
  reaches from there is what the reader takes on trust — a class widened by one character reads the
  same as this one. The set itself is deliberate and is not narrowed here: the C0 controls minus tab
  and every line break, DEL, the zero-width and bidi formatting characters, the BOM. What changed is
  how it is spelled. `_codepoints` expands explicit inclusive blocks — `(0x00, 0x08)`, `(0x0e, 0x1f)`
  — and the single code points into the characters themselves, and `re.escape` writes them into the
  class, so the compiled pattern holds 43 spelled-out characters and no `first-last` span for a regex
  parser to read. No suppression comment was added, and the block-by-block comments that document the
  set stay beside the blocks. The set is provably the same one: every code point in `range(0x110000)`
  matches the new expression exactly when it matched the old, 43 either way with an empty symmetric
  difference, and `LINE_BREAK_RE` and `strip_control_chars` are untouched. The Unicode-wide test that
  pins the set code point by code point still passes, and a second test now pins the form — the class
  body carries no unescaped `-` and spells each character out once — so a future edit cannot bring a
  range back quietly.
- **The default local answering model is `qwen2.5:14b`.** `OLLAMA_LLM_MODEL` defaulted to `qwen3.6`:
  23 GB, a thinking model, and the one of the three candidates that has never been run over an eval set
  end to end — the report carries a two-question probe of it and says as much. A default should be a
  model the eval actually measured, and `docs/eval-results/2026-09-10-local-models.md` (Runs 1-8)
  measured two. It does not make a clean case for either, and this entry is not going to read as if it
  did. On the harness's automatic score `qwen2.5:7b` (4.7 GB) is **ahead**: 19/20 against 14b's 18/20.
  `c09` (identify) passes on 7b and fails on 14b. Broken quotes — a quote the passage it cites does not
  contain — came down to one for 7b and stayed at two for 14b. The report's own verdict is quoted
  rather than filtered: "Neither model is good enough to advertise as a strong default: 19/20 and 18/20
  with genuine unattributed and broken quotes in both." What the choice rests on is the other half.
  14b grounds far more heavily — 61 quotes checked against 39, 95.1 % of them confirmed against
  92.3 % — and it keeps the parts of a question apart. `c10` asks which of two books takes chivalry
  seriously and which mocks it; it FAILS on both models, but 7b fails by collapsing the two into one
  sentence that is simply wrong ("Don Quixote … is the book that takes the whole code of honour
  seriously and makes fun of it"), while 14b answers the half the evidence carries, names Don Quixote
  for it, and then says the serious one "is not directly mentioned in the evidence provided". A wrong
  answer and a partial one that declines what it cannot ground are not the same failure, and the second
  is the behaviour this project asks for everywhere else. That is the owner's call, made for grounding
  and for complete answers, and the costs are named rather than hidden: 9.0 GB to pull instead of 4.7,
  and roughly twice the wall time per question (86.8 s against 42.6 s, mean over the twenty questions
  of both sets). One caveat from the report travels with the comparison: round 2 changed the synthesize
  rules and only 7b's research subset was re-run afterwards, so 14b's numbers describe the prompt as it
  stood in Runs 1-6. `OLLAMA_LLM_MODEL=qwen2.5:7b` in `.env` is one line for a machine that would
  rather have the speed, and the warning that a small local model is less reliable than the hosted
  default stands unchanged — the report says in as many words that it should not be softened.
  `scripts/install-mac.sh` reads the name out of `config.py` and pulls whatever it finds there, so only
  the printed download size needed editing. It was wrong twice over: "approximately 3-8 GB depending on
  the tag" for a model that is 9 GB, and that number went beside whatever name had been resolved, so an
  `OLLAMA_LLM_MODEL` override was announced at the default's size. Each size line now prints its number
  only when the model IS the default it was measured on — 9 GB for `qwen2.5:14b`, 1.2 GB for `bge-m3` —
  and says "size depends on the model" otherwise.
- **A stop reason is printed once, not twice.** `stop_chapter_again` opened with `stopped: ` while
  every line that shows a stop reason already says that word itself, so a chapter the model asked for
  a second time reached the terminal as `[reflect] stopped: stopped: requested chapter was already
  attempted` and the web UI's reflect step as `stopped: stopped: ...`. The prefix is gone from the
  reason in both languages, and the three templates that add it — `ev_reflect_stopped`, `m_stop`,
  `ui_stopped` — are untouched. A test walks every `stop_*` reason in the table in `en` and `ua` and
  asserts that none of them opens with the word its own line carries and that each rendered line holds
  it exactly once, so the next reason written with the prefix baked in fails instead of shipping. The
  eval reports keep the doubled form: they record what was printed when they were made.
- **The New Chat dialog no longer says it will clear the chat.** Chainlit's stock wording — "This will
  clear your current chat history. Are you sure you want to continue?" — describes an app without a
  data layer. This one has: every chat goes to `.chainlit/chat.db` and stays in the sidebar, which is
  what the confirmation is warning about destroying. `.chainlit/translations/en-US.json` is tracked
  from now on — the 2.12.0 file byte for byte, with that one string replaced by "This starts a new
  chat. The current chat stays in your history." Two behaviours of `chainlit/config.py` make that safe
  and are written out next to the `language` setting in `.chainlit/config.toml`: `init_config()` seeds
  the directory with every language the package ships on each start (and on `chainlit init`) but skips
  a file that already exists, so the tracked one is never overwritten; and `load_translation()` serves
  the file for the effective language WHOLE, out of that directory alone, with no per-key merge against
  the package copy — which is why ours has to be a full copy rather than a one-key override. The same
  comment names the third: `config.py` resolves `.chainlit/` from `CHAINLIT_APP_ROOT`, defaulting to
  the CURRENT WORKING DIRECTORY, so the tracked file wins for a server started in the clone root, which
  is what every documented command does, and a run started elsewhere seeds a fresh directory there and
  gets upstream's wording back. Tests pin all three behaviours: the key set against the installed
  package's file, so a Chainlit bump that renames a key fails the suite instead of blanking a label;
  the single string that differs; and the seeding step leaving our file alone. `.gitignore` goes on
  ignoring the other 22 languages.
- **That copy is attributed, because it is somebody else's file.** `.chainlit/translations/en-US.json`
  is Chainlit 2.12.0's own, under Apache-2.0, and §4(b) of that licence asks a modified third-party
  file to carry a notice saying it was changed — nothing in the tree said so, and `NOTICE` credited
  only this project's author. `NOTICE` now names the file, the upstream version, the one changed key
  and the date, and records that the installed distribution ships neither a LICENSE nor a NOTICE of its
  own to quote a copyright line from: its metadata declares only the licence and the authors, and
  inventing a copyright line to fill the gap would be worse than saying there is none. The JSON keeps
  no headers — Apache asks for the notice, not for a comment in every file, and this one has no syntax
  for it. `.chainlit/translations/README.md` carries the same provenance beside the file, and a test
  holds the two ends together: dropping the copy without the paragraph, or the paragraph without the
  copy, fails the suite.
- **Every evidence line carries the citation to use, and the rules name no book at all.**
  `Every claim must cite its source as [book, chapter]` named the format without ever showing one
  filled in, and `qwen2.5:7b` ended 11 of the 20 answers of the local mini-eval with the literal
  string `[book, chapter]` — including every answer that was otherwise good enough to put in front of
  a reader, while `qwen2.5:14b` substituted it in all 20. The first fix put a worked example in the
  rules, taken from the demo corpus. Review round 2 rejected that: the example is a REAL title and
  section, it sits in the shared system message of every question, and a model that copies it into an
  answer about an unrelated book is caught by nothing — provenance checks that evidence quotes come
  from the passages they name, never that the answer's citations do. So the example is gone, and each
  evidence line opens with its own filled label instead — `- [Book — Author, Section] "quote"` — and the
  rule points at that label rather than showing one: cite as `[book, chapter]`, with the book and the
  section filled in, by copying the label the evidence line opens with, never writing the two
  placeholder words literally and never writing a label the evidence does not carry. The only titles
  the model can cite are the ones the evidence put in front of it. It is deliberately the smallest
  edit to a prompt whose behaviour is measured — the example swapped for a pointer, the rest of the
  sentence intact; two rewrites that restructured the rule were measured first and both scored worse
  on the local research subset, which the report records. The ablation's retrieve-and-answer arm
  builds the same line shape, since it shares the rules. The documented citation format is unchanged
  and the golden files are untouched, so only the code SHA of an eval fingerprint moves. Measured:
  0 of 20 placeholder answers for 7b and 0 of 20 for 14b after the first fix, and 0 of 10 again on the
  labelled form (`docs/eval-results/2026-09-10-local-models.md`).
- **Project Gutenberg's italics markup no longer breaks a correctly copied quote.** `_normalize` maps
  punctuation to whitespace through `[^\w\s...]`, and `\w` keeps the underscore, so the `_go_` of
  "All right, then, I'll _go_ to hell" survived as its own token: a quote copied character for
  character out of Huckleberry Finn, Chapter XXXI did not match the passage it came from and was
  reported as a possible hallucination — the outcome the golden file's own note on `c02` says must not
  happen. The underscore is punctuation now, dropped on both sides of the comparison, the quote and the
  passage alike, and before the rules that keep meaning inside numbers, so a signed number in italics
  reads like a bare one. It stays a separator rather than a deletion: `_go_to_hell_` is three words.
- **A refusal phrased as "the evidence does not contain it" is scored as a refusal.** The agent eval's
  `REFUSAL_MARKERS` held no member of that family, so `c08` — where the library really does not hold
  The Adventures of Tom Sawyer — scored FAIL for both local models although neither narrated the fence
  scene from memory and both said in plain words that the evidence does not hold it. The list gains
  three verbs whose subject can only be the evidence or the library — contain, include, cover — in both
  voices and both numbers, so that which one a model reaches for is not what decides the score, plus
  `не містить` / `не містять`. Deliberately not "does not mention", which an answer that answers may
  say about one chapter. Because that family also covers hedges a model emits constantly ("the
  evidence does not include the exact wording, but ..."), the scorer no longer accepts a marker on its
  own: a refusal is a marker with the answer ENDING there, at most 60 words after it. Otherwise
  "The library does not contain this, but in the novel the captain ..." would score PASS while telling
  the story from model memory, which is the exact failure the item measures. The budget separates two
  measured populations rather than clearing one: the honest `c08` refusals run 11 words after the
  marker on the `qwen3.6` probe, 36 on `qwen2.5:14b`, 37 on `7b`, and 42 in the run where 7b also
  says what the evidence holds instead, while the same refusal that then retells the fence scene from
  memory runs 82 — so 60 leaves 18 words of margin above the longest honest one and 22 below the
  narration. The provenance count is deliberately not part of the rule, because an honest
  refusal quotes the card that says the thing is not in this edition. The metric keeps its meaning:
  an evidence-free answer told from model memory is still a failure, and the manual-correctness
  checkbox in the report is still where a mixed answer is caught. The tail is counted over prose
  only: a bracketed citation is not narration, and now that every evidence line carries a filled
  label, a refusal that ends by naming the chapters it read pays seven to nine whitespace tokens per
  label — 18 of the 60 raw tail tokens of the measured `c08` answer, spent on being more accountable
  rather than less.
- **A local thinking model is told not to think, and no single call outlives the question deadline.**
  Ollama does not count reasoning tokens against `max_tokens`, so `qwen3.6` over its OpenAI-compatible
  endpoint reasoned past `LLM_TIMEOUT_S` without beginning an answer, timed out, retried twice, and the
  question deadline — which the loop consults only between steps — never got the chance to stop it:
  that model finished no question at all. With `LLM_BACKEND=ollama` the client now sends
  `reasoning_effort: "none"`, which is the one form Ollama 0.33.3 honours there (`think`,
  `chat_template_kwargs.enable_thinking` and an `options` block are all accepted and ignored — measured
  on this machine, not assumed) and which is inert for a model without the thinking capability, so it
  goes on every local call and never on a hosted one. Separately, a search-loop call's per-attempt
  timeout is now the smaller of `LLM_TIMEOUT_S` and what is left of `QUESTION_DEADLINE_S`: 600 against
  300 is the local default pair, so one call could outlive the whole question's budget and then retry.
  It is floored at five seconds, so a call the loop did start inside the budget fails on the provider
  rather than instantly on a timeout of zero. The cap belongs to the loop and to nothing else: the
  final `synthesize`, and any call issued once the deadline has already passed, keep the full
  `LLM_TIMEOUT_S`. Capping those would have been the worse bug — the call bounded at the moment the
  budget runs out is the synthesis, `run_question` has no `except` around the stream, and the CLI and
  the web UI both turn the resulting `APITimeoutError` into an error string, so a deadline-stopped run
  would have returned nothing at all instead of the degraded answer the deadline exists to produce.
- **The retry loop is ours, so a retry cannot spend the question's budget a second time.** The cap
  above was handed to the SDK client, which samples its timeout ONCE, when the client is built, and
  reuses that number for every retry it makes: a `reflect` call capped at the 300 s left of the
  question could still take three 300 s attempts plus backoff, which is exactly what the cap exists to
  prevent and what the README paragraph promised it did not. `llm_invoke` now runs the attempts
  itself, with `max_retries=0` on the client, building a client per attempt so the bound is recomputed
  against the budget that is really left; and when a failure and its backoff would leave five seconds
  or less, it stops retrying instead of buying an attempt that could only be given the floor. A capped
  call therefore stays inside the seconds the question had left when it began. Whether the deadline
  caps a call is decided once, before the first attempt, and reused for all of them — asked again
  after the first attempt exhausted the budget, the rule would have read "deadline passed" and handed
  that call an UNCAPPED retry. The exemptions are unchanged: the final `synthesize`, and anything the
  loop issues after the deadline, keep the full `LLM_TIMEOUT_S` per attempt and the full retry count.
  So are the exceptions (the SDK's own rule: connection failures and timeouts, `x-should-retry`,
  408/409/429 and 5xx, never a `Retry-After` longer than two minutes) and the backoff (0.5 s doubling
  to 8 s with jitter, or the server's own `Retry-After`). Usage accounting is untouched — it is read
  off the reply that came back, so `llm_calls` counts what it counted before and every number in a run
  report keeps its meaning. Because that loop speaks the SDK's exception vocabulary and builds each
  attempt's client with an `httpx.Timeout`, `llm.py` imports `openai` and `httpx` at module import
  time: both are declared as the direct dependencies they now are, at the versions the lockfile
  already resolved, so the lock gains the two edges and moves no version.
- **`--print-env-resolution` no longer prints the keys it read.** The flag dumped every value of
  the `.env` verbatim, and a `.env` is where the credentials live: a run of it reproduced
  `OPENROUTER_API_KEY`, `LANGCHAIN_API_KEY` and `CHAINLIT_PASSWORD` on stdout, from the one flag
  whose whole audience is people pasting its output into a bug report. A value whose name has the
  shape of a credential (`*_API_KEY`, `*_KEY`, `*_TOKEN`, `*_SECRET`, `*PASSWORD*`, `*_PASS`,
  folded) is now printed as `<set, N chars>`, and the guard's own summary lines redact by that
  same list instead of a narrower one of their own. The equivalence tests still hold the whole
  file against `dotenv_values()`: names and order, values for everything that is not a credential,
  and for the ones that are, that both readings agree the name is set and on the length of the
  value.
- **A `.env` whose whitespace this parser cannot classify stops the run.** python-dotenv's parser
  is Python's own `\s` class — around the `=`, before an inline `#`, and in the `rstrip()` that
  ends an unquoted value — which is wider than the space and tab the shell reading handles. So
  `LLM_BACKEND=ollama<FF># local` resolved to `ollama` for the application and kept the form feed
  here: `LLM_BACKEND` never equalled `ollama`, the run classified itself as hosted, and the
  `EMBED_BACKEND=openrouter` on the next line walked past the fully local guard under a banner
  that said fully local. Reproducing that class in bash means classifying UTF-8 by hand in
  whatever locale the run inherits, so a vertical tab, a form feed, the four ASCII separators, a
  non-breaking space and every other Unicode space character are refused by line number instead,
  wherever on the line they appear.
- **`OLLAMA_HOST` is judged with the rest of the resolution, before anything is installed.** The
  check stood in step 7, behind `brew install uv` and `uv python install`: on a PATH with no uv —
  a fresh Mac, which is this script's whole audience — a run that was about to be refused for a
  variable pointing a server, and an `ollama pull`, at somebody else's machine had already
  downloaded and written a package manager's worth of software. It reads one exported variable and
  needs no tool, so it now sits with the other refusals, ahead of step 3.
- **The v1 tracing names are read by the rule langchain_core applies to them.** One truth table
  covered all five names, and `langchain_core.utils.env.env_var_is_set` is not that table: it
  counts every value but `""`, `0`, `false` and `False` as set, so `LANGCHAIN_TRACING=off` and
  `LANGCHAIN_HANDLER=off` are set. The installer accepted either, reported tracing off and
  finished, while `CallbackManager.configure()` raised `RuntimeError` on the first model call. The
  two v1 names are now judged by that rule — refused in the local mode with the consequence named,
  and reported in the hosted one as the `RuntimeError` it is rather than as an upload that cannot
  happen — while the three v2-only names keep the wider list of off spellings, deliberately
  stricter than langsmith's own (it uploads on the exact string `true`). Step 12 imports
  `env_var_is_set` rather than keeping a copy of the rule, and reports the v1 names on their own
  line.
- **The installer no longer promises a locality the application does not have.** `config.py` loads
  `.env` through `load_dotenv()`, which never overrides a variable that is already exported, so a
  shell carrying another project's `LLM_BACKEND=openrouter`, `EMBED_BACKEND=openrouter` or tracing
  flag decided the run while every line the script printed — and the `.env` it wrote — still said
  fully local. The script now resolves what the application will actually see, in `config.py`'s own
  order (the exported environment, then the `.env` that is there or the one it is about to write,
  then the default), for the values that decide where data goes: both backends, the Ollama
  endpoint, the hosted base URL, and the five tracing names across both prefixes. In the local mode
  a value that contradicts the mode stops the run at exit 2, naming each variable, where its value
  came from and the two ways to drop it (`unset`, or `env -u`); `--hosted` reports the same values
  instead, because there they are the mode. The dry run refuses in the same place and says it wrote
  nothing. Step 12 then prints the configuration `ask_your_library.config` resolves and ends the
  run when that is not the mode which was set up — a rewritten `.env` is no fix for a variable the
  shell exports, and only the loader can say which of the two won.
- **A LangSmith key is a tracing switch, and the guard reads it as one.** `graph.py` sets
  `LANGCHAIN_TRACING_V2=true` whenever `LANGCHAIN_API_KEY` is present and that name is not set at
  all, so a key inherited from another project traced a "fully local" run while all five flags the
  script reads still said off — and step 12, which read the environment without running that
  function, printed `tracing: off` for a run that traces. The key is now judged in the local mode
  by the rule `graph.py` itself applies, with the two ways out named (drop the key, or set
  `LANGCHAIN_TRACING_V2=false`, which is the line the local `.env` already writes); the two tracing
  endpoints are reported as the destinations they are; and step 12 calls
  `enable_tracing_if_key_present()` — the application's own function, not a second copy of its rule
  — before it reports, then names where the traces would go. A key is never printed: only whether
  it is set.
- **The rest of that guard reads the environment the way `config.py` does.** A URL host is taken
  from the authority with the userinfo removed and the case folded, so
  `http://localhost:11434@ollama.example.com` is the remote host it resolves to and `LOCALHOST` is
  the local one it is; an `OLLAMA_URL` with no scheme is refused by name, because `config.py` uses
  the value as it stands and `localhost:11434/v1` is not an address. Exportedness, not emptiness,
  decides whether a variable is exported: python-dotenv skips a name already in the environment
  even when it is empty, and `config.py._env` reads that blank as its default, so an exported
  `LLM_BACKEND=` resolved to OpenRouter while the guard saw "nothing exported". An empty `.env` is
  judged rather than skipped — it is a real resolution to `config.py`'s own, hosted defaults, not
  the unreadable `.env.example` the skip was written for. A refusal that came from the `.env` no
  longer explains that an exported variable wins over it. `OLLAMA_HOST` is checked before step 8
  rather than only inside the branch that starts a server: the `ollama` CLI reads it as the address
  of the server it talks to, so with a server already answering, `ollama pull` was free to fetch
  this run's models onto whatever machine that variable named. And `--hosted` with an `OLLAMA_URL`
  off this machine says in its own line that every passage of the library would be embedded there,
  since that mode keeps `EMBED_BACKEND=ollama`.
- **The installer reads `.env` the way the application reads it, and decides before it installs
  anything.** The guard's parser was `sed -n "s/^NAME=//p"`, which understands one form and hands
  back every other one as written: `LLM_BACKEND="ollama"` came out with its quotes, was not equal
  to `ollama`, and so classified a fully local `.env` as hosted — the guard was then never applied
  to the rest of the file, and `EMBED_BACKEND="openrouter"` went through, while python-dotenv read
  those same two lines as a local answering model with the whole library embedded on OpenRouter.
  The subset python-dotenv supports is now reproduced in the shell (blank lines and comments, an
  `export` prefix, whitespace around the `=`, unquoted values with an inline `#` comment, single-
  and double-quoted values with the escapes each of them decodes), and everything outside it — an
  unmatched quote, a multi-line value, a `${VAR}` interpolation, a line with no `=` — stops the run
  at exit 2 naming the line number, rather than being read one way here and another way there. It
  is bash and not Python because it has to run before `uv` exists, which is the second half of
  this: the whole resolution now sits directly after the repository-root check, ahead of `brew
  install uv` and `uv python install`. A run that was going to be refused had already downloaded
  and installed both. `--print-env-resolution` prints how the script read the file, and the tests
  hold that output to `dotenv_values()` from the locked library, form by form.
- **One resolver decides every setup step, and an embedder that is not on this machine is named
  with its destination.** Which models step 8 pulls, whether step 12 expects a missing key, and
  which expectation step 12 holds the loaded configuration to now all come from the same
  resolution of what the application will load. So `--hosted` with an exported `LLM_BACKEND=ollama`
  pulls the answering model that run is going to need, instead of finishing at "Done." with the
  first question about to ask Ollama for a model nothing fetched — and step 12 checks the hosted
  expectation as well as the local one. `--hosted` moves the answering model and nothing else, so a
  run whose embeddings resolve off this machine says so whichever way it got there: a remote
  `OLLAMA_URL` as before, and now `EMBED_BACKEND=openrouter`, which warned about nothing at all,
  each naming the endpoint it resolves to. `OLLAMA_HOST` is parsed as an authority and its host
  compared exactly, because `localhost:11434@ollama.example.com` begins with the loopback spelling
  and *is* `ollama.example.com`: a match on a prefix sent this run's `ollama pull` there.
- **`SECURITY.md` describes the branch rules that are actually in force.** The paragraph on
  required checks said the repository was private on the free plan until its first release and that
  a red check was honoured by hand. It is public, and the ruleset on `main` lists all seven checks
  as required, requires code scanning results from CodeQL (no security alert of high severity or
  above, no other alert at error level), wants the branch up to date before it merges, and refuses
  force-pushes and deletion with no bypass. CodeQL runs from GitHub's default setup, so its two
  analyses are not among the seven: what the ruleset requires is the result of the scan.
- **Assertions that read as URL allow-list checks, and a character class that reads wider than it
  is.** Four assertions checked a host name as a substring or a prefix of a URL (`example.org`
  after neutralization, twice; the hosted endpoint; the local one); they now compare whole URLs,
  parsed with `urlsplit` where the text around them varies, or whole printed lines where the
  assertion is about a line of output. `CONTROL_CHARS_RE` is written one block per line with the
  invisible formatting characters spelled out singly instead of as spans, because a span between
  two `\u` escapes reads to a checker as the range between their ASCII characters. The set is
  unchanged, and `test_sanitize.py` now pins it over the whole of Unicode: 43 code points.
- **The demo corpus builds again: five Gutenberg pins had drifted.** `uv run
  scripts/ingest_demo_corpus.py`, the first command a reader runs after the install, stopped at the
  third book with `checksum mismatch for treasure-island`. Project Gutenberg had regenerated five
  of the 31 texts — Treasure Island, Pride and Prejudice, Moby Dick, A Study in Scarlet and Memoirs
  of Napoleon Bonaparte — and the manifest still pinned the previous files. All five drifts are
  cosmetic: every one carries a new "Most recently updated" header line, three also carry small
  corrections in the text (`young-man` -> `young man`, `Mr,` -> `Mr.`, two missing quote marks,
  `soil` -> `soul`), one had four blank lines inserted after the start marker, and one lost both a
  "Produced by ..." transcriber credit and two blank lines before the end marker. The chapter split
  is unchanged: `corpus/toc/*.json` regenerates byte-identical from the new sources, and the corpus
  still prepares 7,285 transcript chunks and 165 card chunks. The five entries are re-pinned
  through the script's own
  `--stage checksums`, each with the re-pin date and one line on what drifted. The reports in
  `docs/eval-results/` keep `manifest@f093bb27dab1`, the manifest their numbers were produced from;
  `eval/run_agent_eval.py` computes that fingerprint from the file at run time, so runs from now on
  carry `manifest@ed94677aa3a3` instead. That value is a SHA-256 over the whole file as it sits on
  disk, comments included — and the re-pin dates and the drift notes are comments — so an edit that
  changes nothing a build reads still moves it. It names one exact file rather than one set of
  checksums, which is the property a provenance line needs.
- **A weekly job now watches the pins.** `.github/workflows/corpus.yml` runs the download-and-verify
  stages — no Ollama, no model, no embedding — every Monday and on every pull request that touches
  `corpus/**`, the ingest script or `ingest/chapters.py`, where the chapter splitter that writes
  those tables of contents actually lives; a change there moves chapter boundaries with nothing
  under `corpus/` edited. The canaries are re-split too: their text is committed rather than
  downloaded, so their two toc files were the only ones the job could never have anything to say
  about, although an edit to a canary matches its path filter. It fails on a mismatch, and then
  diffs `corpus/toc/`: a re-pin makes the checksums green by construction, and the chapter split is
  what still says whether the upstream file is the same book. That diff is taken over the index
  (`git add -A -- corpus/toc` first), because a book added without its toc file writes an
  **untracked** one, which a plain `git diff` cannot see. `corpus/README.md` documents what is
  pinned, what the job checks and what to do when it goes red.
- **The drift recipe now actually re-fetches, and an unpinned book is a failure.** Two holes in the
  paragraph above, found in review before anyone had to hit them. The documented investigation
  (`--stage prepare-text --no-verify`) reused the cached `data/raw/pg<id>.txt` — the script only
  downloads a file it does not have — so it re-prepared the **stale** text, regenerated
  `corpus/toc/` from it, and the toc diff you were told to trust came back clean about the old
  edition. `--refetch` downloads regardless and moves the copy you had to `pg<id>.txt.prev` (kept,
  not deleted: the diff between the two is the point), and the README recipe is now four numbered
  commands. A second `--refetch` over the same book refuses instead of parking this run's download
  on that backup: for a Gutenberg text the `.prev` is the only copy of the pinned edition anywhere
  — nothing here commits those texts and the mirror serves the newer file — and overwriting it
  leaves you diffing one fresh download against another, which comes back clean and says nothing.
  The refusal names the file and the two ways on — read the diff you already have, or move the
  backup aside by hand — and it comes before anything is downloaded or moved, so a run over all 31
  books stops at the check rather than part way through. Separately, `verify_checksum` returned
  early when an entry had no `sha256` at all, so
  deleting a pin removed a book from verification without failing anything; a missing pin now exits
  with the two explicit ways out, and `tests/test_corpus_pins.py` refuses a `books` entry without a
  64-hex digest — and a canary with one — on every pull request, without a network round trip.
- **The corpus job asks Project Gutenberg politely.** 31 sequential downloads left a shared CI
  runner IP as a bare `requests.get` with no identification and no retry, against a host that rate
  limits: one 429 or one dropped connection failed the whole job, and a rerun made the same burst.
  The requests now carry a User-Agent naming the project and its repository, retry three times with
  a doubling backoff on 429, 5xx and connection errors — and only those, so a 404 on a wrong
  `pg_id` still fails on the first attempt — and pause a second between books. Checksum semantics
  are untouched: a retry changes whether a file arrives, never which one. The job also carries a
  20-minute `timeout-minutes`, so a hung request is not a runner held for six hours.
- **A `.env` in the checkout no longer decides what a test measures.** The macOS installer writes
  one, and the README sends contributors to `uv run --group dev pytest -q` right after it, at which
  point `test_llm_factory_bounds_every_call_with_timeout_and_retries` failed: it dropped
  `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES` and `QUESTION_DEADLINE_S` from the child's environment in
  order to read the defaults, but dropping a name FREES it, and `config.load_dotenv()` runs at the
  first package import in the child's working directory — so the installer's `LLM_TIMEOUT_S=600`
  and `QUESTION_DEADLINE_S=1200` came back as the "defaults". Every test that reads configuration
  in a child now goes through `conftest.run_fresh`, which already starts one in an empty directory
  with those inputs scrubbed, and a new test pins both directions of that isolation.
- **The catalogue set re-measured on the released code.** One run of `eval/golden/en-demo-catalog.yaml`
  on `466fc82` with the hosted planner and the 04.09 index: behaviour 10/10, quote provenance
  21 / 0 / 0 on the four research items, $0.1762 for the set and $0.0136 for the six catalogue items —
  the same verdicts and the same routing as the 09.09 run on `50b9347`, with the citations now carrying
  the full index key the evidence label supplies (`docs/eval-results/2026-09-10-catalogue-set.md`).

## 0.2.0 (2026-09-09)

The first public release. Everything below was merged after the `0.2.0-rc1` candidate of 07.09
and measured or reviewed on its own: the catalogue path, the hardening pass, the decision
records in the tree and the macOS install path.

- **A macOS install path.** `scripts/install-mac.sh` takes a fresh clone to a working local setup
  in one command. Homebrew is checked, never installed: the official command is printed and the
  script exits. `uv` and Ollama come from `brew`; the interpreter is whatever `requires-python` in
  `pyproject.toml` asks for, through `uv python install`; the embedding and answering models are
  pulled by the names read out of `config.py`, so the script cannot pull a model the app will not
  ask for, and their approximate sizes are printed first. Ollama is started for the session, with
  `brew services run` and not `start`: the run form registers no login item, so the script leaves
  nothing behind that comes back at every boot, and the one-liner that would make it permanent is
  printed in the next steps instead; when `brew services` cannot start it the fallback is a
  background `ollama serve`, which outlives the script, so that one prints its pid and the two
  commands that stop it rather than the login-item line. Only a loopback `OLLAMA_URL` is ever
  started here, and only while `OLLAMA_HOST` — that variable, not the URL, is what a server
  started here would bind — is empty or one of the spellings of loopback, optionally with a
  scheme and a port. That gate is closed by default: everything else is refused, a bare port
  included, because `:11434` is a host/port pair whose empty host means every interface and `0`
  is `0.0.0.0`. `uv sync --locked --extra ui` installs
  the environment. `.env` is written from `.env.example` only when it does not exist,
  never overwritten, and written through a temporary file that is moved into place only once it
  is complete — `> .env` created the file before the writer produced a byte, so a failure
  halfway (an unreadable `.env.example` is enough) left an empty `.env` that the next run
  refuses to touch and `config.py` resolves to the hosted defaults. It carries
  `LLM_BACKEND=ollama` and `LLM_TIMEOUT_S=600` — the local defaults,
  because a value copied out of the example is an environment value and wins over the per-backend
  default `config.py` would otherwise apply, which would leave a local model on the hosted 120 s
  per-attempt budget. `QUESTION_DEADLINE_S=1200` goes in beside it: the per-question wall clock
  has no per-backend default, and the 300 s in the example is a budget a cold local model can
  spend in the plan node alone. `LANGSMITH_TRACING_V2=false` and `LANGCHAIN_TRACING_V2=false` are
  uncommented in that mode too — the README's own recipe for keeping tracing off whatever the
  shell exported, applied in the mode whose whole point is that nothing leaves the machine. Then
  one confirmation before the ~30-minute demo build, and `check_environment()` at the end: the
  preflight the CLI runs before every question, no model call. Its problems are classified before
  they are reported. A problem this run knowingly left behind — no index yet, or no key yet under
  `--hosted` — is recognised by rendering the same message through `i18n.t` with the same
  arguments and comparing, never by an English fragment, and only those are named back as
  expected; everything else fails the run with exit 1, an unreachable Ollama and a model that is
  not pulled included, as does a pre-existing `.env` whose `LLM_BACKEND` will not import at all.
  The preflight's notices are printed under its problems. A `.env` that is already there is what
  the run is actually setting up, so it — not the flag — decides which answering model is pulled
  and whether a key is expected, and the step that finds it says which mode it selects and, when
  that is not the mode the banner named, that the banner's was not applied.
  `--dry-run` prints the plan and touches
  nothing, `--hosted` writes the OpenRouter configuration and names the variable to set (a key is
  never taken as an argument), `--no-demo` points at `ayl-add` instead, `--yes` skips the
  confirmation. macOS only, never `sudo`, idempotent. What reaches the network: the package
  fetches through `brew`, `uv` and `ollama` and, when you say yes to the demo corpus, the
  checksum-pinned public-domain texts `scripts/ingest_demo_corpus.py` downloads from
  gutenberg.org. The two LibriVox audiobooks are not fetched — their transcripts are committed
  under `corpus/prepared-audio/`, so archive.org is reached only by that script's
  `--retranscribe`. A tool that fails is named
  with its status and ends the run at exit 1, one of the three documented codes, instead of
  aborting through `set -e` with `brew`'s own. Everything `run` does not wrap has the `ERR` trap
  under it, and `set -E` is what carries that trap into functions, subshells and command
  substitutions: without it a `sed` that failed inside one of them ended the script at its own
  status with nothing of the script's own printed.
  `tests/test_install_script.py` runs the dry run against recorders on a scrubbed PATH: the plan
  has to name all twelve steps in order, and not one of `brew`, `ollama`, `uv`, `curl` may record
  a call. The rest are real runs against the same recorders, so a "real" run still installs,
  downloads and starts nothing: two stop at a refusal — a `brew` that exits 17, and an
  `OLLAMA_URL` that is not this machine — and the others walk the whole script, over every
  `OLLAMA_HOST` the gate must refuse and every one it must let through, an `.env.example` that
  cannot be read (exit 1, and no `.env` left behind), and a `.env` that already selects the other
  backend. Step 12's embedded Python is lifted out of the script by a regular expression and run
  on its own, so what its exit codes classify is checked without macOS and without the eleven
  steps in front of it. The file is exercised in CI by the `install-script` job
  on `macos-latest`; the Linux jobs, where it skips itself, now print skip reasons (`pytest -rs`)
  so a file that skipped cannot read as a file that passed.
- **Security: two zero-click image channels in the web UI, and the rest of the hardening pass.**
  The chat renders our own HTML (the provenance badge, the evidence list, the metrics footer),
  and a whole message is one HTML block that a blank line ends: everything after that line is
  chat markdown again, so a markdown image there is fetched by the browser on render, with no
  click and nothing visible. Escaping does not stop it. Both places that only escaped are fixed,
  at both ends:
  the badge's tooltip and headline (built from the quotes that failed provenance, i.e. from
  corpus text) and the metrics footer, whose stop reason came from `reflect`; `reflect` now reads
  the model's `decision` against its schema, so an off-schema value degrades to a fixed phrase
  instead of travelling into the terminal and the footer as free text (the value itself goes to
  the debug log, cut to eighty characters, so a model that keeps answering off-schema is still
  diagnosable). Every form of line break
  counts, not only LF: CommonMark ends a block on a bare CR and on U+2028/U+0085 as well, and one
  regular expression (`sanitize.LINE_BREAK_RE`) now serves the badge, the footer and the block
  headers of the prompt. The preflight, notice and error messages go through the same escaping and
  image neutralization, but as plain Markdown (`safe_markdown`), so their `- item` lists still
  render as lists instead of one paragraph of literal dashes.
  Also in this pass: the web UI answers only to the `Host` headers `localhost` and `127.0.0.1`
  (Starlette's `TrustedHostMiddleware`), which closes the DNS-rebinding route a page in your
  browser otherwise has to a loopback server, and its login cookie is `SameSite=strict` — set on
  Chainlit's cookie module, because `chainlit run` imports `chainlit.cli` (and through it
  `chainlit.auth.cookie`, which reads `CHAINLIT_COOKIE_SAMESITE` once) before it loads `ui.py`, so
  neither an exported variable nor a `.env` entry could have delivered it;
  `allow_origins` in `.chainlit/config.toml` drops the second port pair (ports are not part of a
  site, so listing another port let a page there read the thread endpoints), its comment now
  says what the list actually governs, and a test pins the pair that is left. Terminal escape
  sequences carried by a poisoned book are stripped where corpus text becomes index metadata
  (`book_key`, front matter, and the section title of a row — a heading the file itself supplied,
  which nothing above the row had cleaned), where it becomes prompt text (`data_block`), and where
  it travels beside a passage: the book and section of a hit reach the scratchpad, the block header
  of the prompt and the evidence card of the web UI, which escapes HTML and would leave a bidi
  override free to reverse the citation naming the source. Every line both CLIs print goes
  through one strip, so a crafted title can no longer repaint the reader's terminal. A line break
  is text, and is no longer part of that strip: deleting CR, the vertical tab and the form feed
  joined the words on either side, which reported an honest quote spanning a line break as broken
  and put `MobyDick` in a block header. They are mapped now instead — to a space in a header and
  in a normalized quote, to a plain LF on the way to a terminal, where a bare CR would otherwise
  put the cursor back over the line just printed. The demo
  corpus's audio download names its local file after the chapter number instead of after the name
  archive.org returned. `.chainlit/chat.db`
  and the run scratchpads are created (or narrowed) to 0600 like the auth secret, and the db's
  `-wal`/`-journal` siblings are narrowed again when a chat starts, since they only appear once
  the data layer opens a session. `ayl-add` now reports the hidden files it skips, which the
  README and its own docstring already promised, and its logging filter strips a mapping-style
  call (`"%(book)s"`, one dict) as well as the `%s` tuple it already covered.
  In CI: the gitleaks range is resolved in its own assignment and an empty or unresolvable range
  fails the step instead of scanning zero commits and passing (see SECURITY.md); `setup-uv` is
  pinned to the uv release the lockfile is maintained with; the `test-ui` job asserts the `ui`
  extra is importable and runs the canary's own tests, whose ui-gated half ran nowhere before.
  The injection canary's UI stage now renders the badge tooltip and the metrics footer with a
  hostile broken quote and stop reason, so a regression of either channel fails the canary.
- **Evidence passages are visible again in the web UI.** Each passage was wrapped in a `<pre>`,
  which Chainlit 2.12 renders with its code-snippet component: the block showed "Raw code" and a
  copy button, and the text inside it never reached the DOM, while `chat.db` held it in full. It
  is a `<div>` with the same monospaced, wrapped styling now. The web UI check before a release
  has to confirm the passage under an evidence item is actually readable in the browser, not
  only that the message was sent.
- **An honest quote out of a poisoned passage is confirmed again.** The strip of control and
  invisible characters ran on the way into the prompt only, so `hits_log` still held the raw
  passage: a zero-width space inside a word left the model quoting `the word` while the text the
  provenance check ran against normalized to `the wo rd`, and the quote was reported broken. The
  passage is stripped once now, in `act`, before it is cut — so the log, the scratchpad and the
  prompt are one string — and `provenance._normalize` drops the same class instead of turning it
  into a space, which keeps a quote checked against a `hits_log` written by an older version
  consistent too. The same strip runs before the injection patterns, so a zero-width space can no
  longer hide an instruction line from them.
- **Tests no longer inherit the shell.** `tests/conftest.py` pins every knob `config.py` reads to
  its documented default before the package is imported (`pin_environment()`, with `setdefault`,
  so the CI backend matrix still works), points `LIBRARY_DB_PATH` at a per-process path under the
  system temp dir that no library lives at, switches tracing off and pins the provider and
  LangSmith keys BLANK. Blank, not removed: `config.load_dotenv()` fills in any name that is
  absent, so dropping a key left the repository's own `.env` free to put it straight back, while
  every reader treats a blank value as no key at all. `ASK_LANG=ua` in a shell used to fail eight
  tests, and a LangSmith key made the end-to-end tests upload trace batches while staying green
  (the client swallows the connection error). Tracing is pinned off under its old names too
  (`LANGCHAIN_TRACING`, `LANGCHAIN_HANDLER`): `langchain_core` still reads them and raises when one
  is set while v2 is off, so a shell carrying the v1 flag failed all eighteen end-to-end tests.
  An autouse fixture resets the per-run state (token
  counters, language, the `library` caches), the subprocess tests share one fresh-interpreter
  helper instead of keeping a scrub list each, and the canary's UI stage restores the environment
  it writes and removes its temp directory.
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
  enforced. The set's measured numbers are in the README's Evaluation section: 10/10 on the branch's final commit `50b9347` with the scoring on keys and `expected_total`, and a core run on the same commit (11/11, 48/0/0 quotes, $0.0519 mean against $0.0488 on rc1) shows the research loop's numbers unchanged while three questions that name one book now run with the retrieval filter (`docs/eval-results/2026-09-09-catalogue-{set,branch-core}.md`).
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
  branches and every merge commit's own first-parent diff included), over the pushed range on
  `main`, and over the whole history once a week. `git log -p`, which is what gitleaks parses,
  prints no diff for a merge unless `--diff-merges` asks for one, so a key introduced by a
  conflict resolution was in no patch the scan read, and fourteen of the fifty commits this
  repository then held were merges; a step in the job now builds a repository whose only copy of a
  key is in a merge and fails unless the option strings the real scan uses find it. OSV-Scanner
  runs over `uv.lock`, on every pull request, every push to `main` and once a week. Neither job is
  `continue-on-error`, so a scanner that cannot run is a failed check, not a silent pass. The two
  Chainlit 2.11.1 MCP advisories — `GHSA-w3fx-mc44-mf6j` (CVE-2026-45018, command injection over
  stdio) and `GHSA-hvfh-5mj3-5f3j` (CVE-2026-45019, SSRF over SSE and streamable-http) — were
  recorded in `osv-scanner.toml` as dated exceptions with the mitigation already shipped (MCP off
  in `.chainlit/config.toml`) until the Chainlit 2.12.0 entry above closed them; an advisory
  without an exception fails the job. Every third-party action in both workflows is pinned to a commit SHA with its version in a
  comment, and `.github/dependabot.yml` proposes weekly grouped updates for the uv lockfile and
  for the actions. `SECURITY.md` gains an "Automated checks" section with the policy.

## 0.2.0-rc1 (2026-09-07) — release candidate

- **Measured.** Tag `v0.2.0-rc1` = `33dba3f` (merged 07.09), single runs on 07.09 with
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
  Chevreuse from 2,500 up; provenance clean at all three and behaviour 12/12 at 1,200 and 2,500
  (11/12 at 4,000 through a scorer artefact, not a changed answer); mean cost per core question
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
