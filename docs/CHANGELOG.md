# Changelog

## 0.2.1 (unreleased)

- **The README is a front page, and the long text is in `docs/`.** What the project is, the
  architecture and the quote check, the manual quick start, the settings table, the evaluation
  narrative, privacy and the threat model, the injection layers, cost and the known limits moved
  out of the README into nine pages under `docs/` — `overview.md`, `architecture.md`,
  `quick-start.md`, `configuration.md`, `add-your-own-books.md`, `evaluation.md`,
  `privacy-and-threat-model.md`, `cost.md` and `known-limits.md` — sentence for sentence, with
  only the relative links rewritten. The README keeps the macOS install, the first question, the
  measured-results table and a five-line privacy-and-cost summary, and gains two Mermaid
  diagrams: the flow in plain terms and the architecture as an offline and an online subgraph,
  both reconciled against `graph.py` and `nodes.py` (the catalogue node and `validate` are in
  them; the CRAG gate sits on the `reflect` edge, where the code puts it). The course-demo
  Excalidraw originals are kept as editable sources in `docs/diagrams/`. Every reference that
  pointed into the README — `SECURITY.md`, the ADRs, the backlog, an example trace, four test
  files and the message `install-mac.sh` prints on a non-macOS system — now names the page
  that holds the text. The README also carries a recorded run: `docs/img/ask-library-demo.gif`
  (100 KB), the windmills question of the demo corpus answered by a local `qwen2.5:14b` — not
  the model `install-mac.sh` pulls — with the quote check reporting all five quotes found
  verbatim. Its 79 s is a warm-cache run, which the metrics line in the frame says outright
  (`cache: 9274 tokens read from cache`); the same question on a cold cache took 128 s.
  `docs/quick-start.md` lists `--print-env-resolution` with the other installer flags.
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
