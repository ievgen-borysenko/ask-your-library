# Changelog

## Unreleased

- **The chunker stamp is checked against the rows before it is written, and `--doctor` measures
  them** (#75, [upgrading](upgrading.md)). `--stage stamp-meta --chunker current` claims the
  version this code chunks at; it now samples the table first and refuses, with the numbers, when
  the rows cannot have come from it. Two bounds, both from the sentence packer's own arithmetic and
  both one-sided, so that only an impossible table is refused: a row longer than the packer's
  ceiling plus one overlap (2,640 characters), and a book holding fewer rows than its prepared text
  needs chunks of 2,400 (`transcript_chunk_floor`). The count is compared per book and only over
  books the table and the prepared texts share, so a second index built from other books is not
  judged by this corpus's numbers. Naming an **older** version (`--chunker sentence-pack-1`) stays
  an unchecked assertion about the past, which is the way through for an operator who means it; a
  refusal writes nothing, and every table is sampled before any of them is stamped.

  `ayl-add --doctor` prints a `chunks:` line per table — rows, median, p95, longest, against the
  target and ceiling of the chunker stamped on it — and reports a table whose rows are above that
  ceiling as **drift**, so the exit code is non-zero. The lengths are collected in the pass the
  reconciliation already makes, so the check costs no extra scan, and a table stamped with a
  chunker this code does not implement is left to `version_mismatch`, which already says the only
  true thing about it. A cards table has no ceiling (a "## section" with no bullet in it cannot be
  split) and gets the distribution without a verdict.

  `--stage ingest` says where it looked when there is nothing prepared (`data/prepared/`, relative
  to the checkout, and whether the directory is missing or empty); it exited non-zero before and
  still does. The documented procedure in [upgrading](upgrading.md) now stops on a failed ingest
  instead of stamping after one — the chain that produced #75 — and the `--doctor` example shows
  the new lines. Chunking itself is unchanged: nothing here re-chunks or re-embeds a row.

- **The hosted default graded by hand, and its limit written down**
  ([`eval-results/2026-09-19-hosted-default-quality.md`](eval-results/2026-09-19-hosted-default-quality.md)).
  `deepseek/deepseek-v4-flash-0731` with thinking off, core and extended sets at `--repeat 3`, is
  fully correct on about 6 of 11 core questions per attempt against 9 for
  `anthropic/claude-sonnet-4.6` and `google/gemini-3.8-flash` on one attempt, at about 1/65 of
  Sonnet 4.6's cost. Thinking on (5.0 correct, 2.8× slower) and an unmerged prompt change (4.3, and
  the `c09` clarify lost) did not help; four other DeepSeek models did not beat it by more than the
  spread between attempts, so the default stays. The report records the shared failure class — an
  answer that calls a detail missing that the retrieved passages hold (#81) — and
  [Known limits](known-limits.md) gains the entry, with the backup settings for readers who need
  depth. Documentation only; manual, single-grader grades on the index before #80.

- **What `observe` kept is logged at every step, and where a chapter read looked** (#81, step 1).
  Under each step's passages the scratchpad now lists the evidence `observe` kept (hit id, book,
  section, quote, why), the quotes the provenance gate refused with their reason, and any item the
  clarify filter took off; a chapter read adds one line with the characters of its section the window
  covered, the section's length, how much of it the scan reached, and the `looking_for` it was aimed
  with. The agent eval's `answers-*.json` gains two fields per attempt beside `evidence_items`:
  `evidence` (the list `synthesize` was given: hit id, book, section, quote) and `chapter_windows`
  (the same window record as the scratchpad line). The Markdown report is unchanged and the sidecar
  keeps `schema_version` 1: fields are added, none renamed. Logging only: no prompt, decision or event
  of an existing step changes; a step that reads a chapter carries one new key, `chapter_windows`.

- **Local cards live in `AYL_HOME`, outside the checkout, and the three NoDerivatives works get
  one** (#58, [`corpus-tech/README.md`](../corpus-tech/README.md#local-cards-and-ayl_home)). A new
  setting, `AYL_HOME` (default `~/AskYourLibrary`), is the reader's own folder for what is built on
  this machine and never shared; a local card of the engineer's shelf is
  `$AYL_HOME/cards/tech/<id>.md`. `corpus-tech/cards-local/` and its `.gitignore` line are gone:
  `.gitignore` is not a boundary, so the script refuses to write a local card when `AYL_HOME`
  resolves inside any git work tree (`ask_your_library.home.private_dir`, tested with a `.git`
  directory, a worktree's `.git` file and a symlink into a checkout). The later private shelf of the
  reader's own books (ADR-026) reuses the same variable.

  The manifest gains `local_card: true`, valid only beside `cards: structure`: the three CC BY-NC-ND
  works keep their committed, code-built structure card and also get a model-written card on the
  reader's machine, which the licence allows a reader to make (2(a)(1)(B)) and withholds sharing. A
  second field and not a fourth `cards:` value, because `cards:` says what the repository ships and
  `local_card` what the reader's machine builds besides it. The guarantee changes from "no model
  writes a card of an ND work" to **"no model-written card of an ND work is ever written inside the
  repository tree"**: `card_targets()` still reads ND off the licence string and skips an ND work
  labelled `shared`, and `card_dir()` sends every model-written card of an ND work to `AYL_HOME`
  whatever `cards:` says. Either backend may write them. A local card says `card_kind: local`,
  and its rows are keyed `<id>@local`, so it sits beside the structure card of the same book
  without sharing a chunk id; `ingest_demo_corpus.py --cards-dir` expands `~` and refuses only two
  cards with one row key.

  A local card is written atomically: a fresh file in the checked folder, fsynced and renamed over
  the name, so a symlink or a hard link planted at `$AYL_HOME/cards/tech/<id>.md` is replaced rather
  than written through, and the folder is checked again right before the rename.

  **Rebuild the cards table of an existing index.** The new row key is a change in what the card
  chunker writes, so `CARD_CHUNKER_VERSION` is now `card-sections-2`, and a cards table stamped
  `card-sections-1` reads with a warning (the preflight notice, `ayl-add --doctor`) until it is
  rebuilt. That is the quick cards stage, which leaves the full text alone:
  `uv run scripts/ingest_demo_corpus.py --stage cards` for the demo index, and for the engineer's
  shelf the same with its `LIBRARY_DB_PATH` and `--cards-dir corpus-tech/cards --cards-dir
  "${AYL_HOME:-$HOME/AskYourLibrary}/cards/tech"` ([upgrading](upgrading.md)). The warning, the
  refusal and the doctor name that command for a cards table instead of `ayl-add --rebuild`.

  **Quotations in committed cards.** The card prompt now lets a card of a work that allows
  adaptations quote sparingly — at most three quotations, each at most 25 words, each in quotation
  marks and followed by its chapter title in parentheses — and asks a NoDerivatives work's local card
  for paraphrase only. The card stage checks a model's reply against that rule before writing it and
  refuses a reply that breaks it, leaving no file. The shared-card test follows: a verbatim run of
  twelve words or more passes only inside such a quotation, and fails outside one; quotation marks
  are paired left to right, and unpaired straight marks or reversed, nested or unbalanced curly ones
  are reported. The eight-word test over every tracked file for the NoDerivatives works is unchanged
  and exempts no quotation.

- **Three golden items are scored by the owner's verdicts of 2026-09-19; reports made before this
  change scored them more strictly.** `c09-shipwreck-first-person` (Robinson Crusoe or Gulliver's
  Travels, "I might be mixing two of them up") moves from `clarify` to the existing
  `clarify_or_answer`: asking back passes, and so does an answer that names both books; naming one
  book with confidence fails. That the answer also tells the two apart is left to the
  manual-correctness checkbox. The same rule applies to `h22-gothic-chase-ambiguous` (Frankenstein
  or Dracula, "i keep mixing two of them up"); `q06`, with no such framing, stays `clarify`. `q16-refusal-casino-royale` now passes when the catalogue answers
  `No book titled "Casino Royale" is in your library.`: in `score()` a `refusal` item answered by a
  catalogue "has" that resolved to nothing, listed nothing and says so in words is a pass, not
  `catalog_misroute`. Every other catalogue result on a non-catalogue item, including a "has" that
  confirmed some other book, is still a misroute. The phrase is not added to the general refusal
  markers, because the research loop puts the same wording in front of answers that go on to
  answer. `eval/run_plan_eval.py` accepts the same route (`mode_ok` for a refusal item sent to
  "has"). The checksums moved: `en-demo.yaml` `edc15194` → `2c43defa`, `en-demo-extended.yaml`
  `836d3870` → `338002f3`. **Old runs are not re-scored automatically**: a committed report that
  shows c09, h22 or q16 as FAIL for these reasons keeps that verdict until the run is scored again.

- **A part heading now ends the section before it: Dumas's Celebrated Crimes gains the eleven
  essays that had no chapters of their own.** With a manifest `part_regex`, part headings only
  prefixed chapter titles, so a part without CHAPTER headings ran on inside the previous part's last
  chapter: the whole Cenci essay sat in "THE BORGIAS — CHAPTER XVI" (90k characters), and
  "ALI PACHA — CHAPTER XI" carried six more essays (585k). Retrieval filtered to the book never
  reached them and a chapter read by title could not find them. A part heading after the first
  chapter heading whose own text passes the chapter size filter now opens a section named after the
  part ("THE CENCI—1598"); a shorter one (an epigraph) and anything before the first real chapter
  heading (title page, contents, including a contents line the chapter regex matches) stay where
  they were. Three books change, each only by moving the
  run-on text into its own sections: celebrated-crimes (75 → 86 sections), senecas-morals
  (+ "OF CLEMENCY", previously inside "OF ANGER — CHAPTER XII.") and romeo-and-juliet (+ the Act II
  chorus). Re-prepare and re-ingest those three with `--book`; `corpus/toc/` and the book-identity
  fixture are regenerated. The generic `ayl-add` path does not use parts and is unchanged.

- **The hosted default is `deepseek/deepseek-v4-flash-0731` with its thinking off, with
  `google/gemini-3.8-flash` as the documented backup; `LLM_REASONING` is new.** Only
  `LLM_BACKEND=openrouter` changes; the shipped default stays local. `ORCHESTRATOR_MODEL` defaults
  to the new model and `PRICE_IN_PER_MTOK` / `PRICE_OUT_PER_MTOK` to its $0.06 / $0.12, in
  `config.py` and in the three commented lines of `.env.example` that `install-mac.sh --hosted`
  uncomments; the backup sits under them as `## ` lines the installer leaves alone.
  `LLM_REASONING` (`off` by default, or `provider`; anything else refuses to start) sends
  OpenRouter's `reasoning: {"enabled": false}` on the hosted backend, which is how the new default
  was measured; the eval fingerprint names it (`via openrouter (reasoning off)`) and the planner
  recording header carries it as `reasoning`. On the same commit and index as a Sonnet 4.6
  baseline (11/11 core at $0.0456, 10/10 catalogue at $0.0164), the new default scored 11/11 at
  $0.0006 and 10/10 at $0.0002, Gemini 10/11 at $0.0202 and 10/10 at $0.0103. Single runs:
  [`eval-results/2026-09-18-hosted-models.md`](eval-results/2026-09-18-hosted-models.md), which also
  carries the candidates that were not chosen. **If you set your own `ORCHESTRATOR_MODEL`, set
  `LLM_REASONING=provider`** to keep its previous behaviour: `off` is now sent to every hosted model,
  and some refuse it while on others it changes the answers. The backup block in `.env.example`
  carries `provider` for that reason. The README's results table and every earlier hosted
  figure stay labelled Sonnet 4.6, and the README now says they predate the change.

- **A refused quote is told to the model that wrote it, the answer names the book, and a run of
  all-dropped steps has a ceiling** (#29, [ADR-004 amended 2026-09-17](adr/README.md)). Three small
  changes against what the gate's first measurement showed on `mistral-small3.2:24b-ctx20k`: 10-11
  quotes refused per run, and on one question an answer that stopped naming the book once a second
  quote was dropped.

  **`observe` is told what it lost.** The gate now returns the refusals in words beside the counters
  — the quote as the model wrote it (cut at 120 characters), the book it named, the rule that
  stopped it — and the last `DROPPED_QUOTES_SHOWN` (6) of them travel on the state as
  `dropped_quotes`. The next `observe` prompt carries them in a `<quotes_dropped_earlier>` block,
  untrusted like any other model-written text, with one sentence saying why they were refused. Until
  now a model that paraphrased was refused in silence and paraphrased again. `OBSERVE_RULES` says
  the check is character by character and that fewer items beat a reworded one. The counters are
  untouched and still sum. **Said exactly, because it is nearly a stronger claim than it is:** the
  USER message of an `observe` step that lost nothing is byte for byte what it was, and its update
  carries no new key — but the SYSTEM message changed for every run, `OBSERVE_RULES` being where the
  two new sentences live. No run of this release is prompt-identical to a run of the last one; what
  is unchanged is the data half of the message, so a difference in the numbers is a difference the
  rules made and not one the block made.

  **The answer names the book.** `SYNTHESIZE_RULES` asks for the title in the answer's own text, not
  only in the `[book, chapter]` label, even where the evidence is thin — a reader who sees the first
  sentence should know which book is being spoken of.

  **A run of all-dropped steps now ends.** `MAX_DROPPED_STREAK` (2, a new setting) bounds the hold
  decided on 16.09: the first all-dropped step still does not advance the CRAG gate, but the
  `MAX_DROPPED_STREAK`th in a row — the second, at the default — is itself counted dry. A run of
  them says the model cannot copy, not that the library has more to give, and each one costs a
  search and two model calls. `dropped_streak` is the new state channel; it counts CONSECUTIVE
  such steps, so any other step resets it — a dry one included, a dry step being the library
  silent rather than the model failing to copy — and it is written only when it says something.

  `PLAN_RULES` is untouched by this entry; what makes the committed plan recordings stale for this
  tree is `#70` below, and not anything `#29` changed.

  **Measured on both local models, on the re-chunked index, one attempt each**
  ([`eval-results/2026-09-18-rechunk-and-observe-feedback.md`](eval-results/2026-09-18-rechunk-and-observe-feedback.md),
  part B). `mistral-small3.2:24b-ctx20k` is **10/11** with **0 broken quotes** out of 32 checked —
  its baseline was 11/11, 10/11, 10/11 over three attempts, so this run matches two of those three
  and is one item below the best of them — and `c03`, the regression this change was written for,
  now PASSES with `titles 1/1` on *fewer* evidence items than the attempts it failed on (6 against
  9): the answer opens by naming *The Three Musketeers* while hedging exactly as before. **The failure moved rather than disappeared.**
  `c05-quixote-windmills`, which passed all three baseline attempts, now fails with `titles 0/1`,
  5 quotes refused as not character-exact and **zero** evidence surviving — and with no evidence
  `synthesize` returns the fixed refusal by code, so the new naming rule is never even sent.
  `qwen2.5:14b`, against the same index, goes **9/11 -> 10/11** and is below its baseline on no
  item, at 0 broken out of 34 and one extra dropped quote; that pair is the closest on the page but
  is not a one-change pair either, since #29 is only in the branch column and #71 only in the other.
  **One attempt is not three**: the baseline measured low variability on both models and low
  variability is not determinism, so neither number here carries a spread, and `c03` is one of the
  items that did vary across the baseline's attempts. Whether `MAX_DROPPED_STREAK` ever fired is
  **not** decidable from these runs either: no artifact records the streak or the per-step refusals,
  and the report says so rather than claiming the cap.

- **The engineer's shelf has cards and an index of its own** (#58,
  [`corpus-tech/README.md`](../corpus-tech/README.md), [add your own books](add-your-own-books.md)).
  `scripts/fetch_tech_shelf.py --stage cards` writes one book card per work through the project's
  own client, so `LLM_BACKEND` picks the backend and the egress rules of ADR-017 apply unchanged.
  The front matter and the H1 are the shape `corpus/cards/*.md` already has, so `chunk_card` cuts a
  tech card and a classics card identically and the card lands under the same book key `ayl-add`
  minted for the work's text; the sections are the ones a technical work has — Key ideas, Structure
  and Terms in place of Plot and Characters. The model is shown the chapter list and the opening of
  each chapter within a budget, never the whole work, and `## Structure` is copied from the prepared
  text rather than generated, so the section that answers "which chapter covers X" cannot rename or
  invent a chapter. **No model-written card of a CC BY-NC-ND work is committed**: the stage may
  read only `card_targets()`, which checks the licence as well as the manifest, asserted in the
  code and in tests (and, since the entry above, writes such a card only under `AYL_HOME`). Each model-written card records `card_model` and `card_built`, because a card written
  on the local model and one written on a hosted model are otherwise the same file. The ten
  licence-clean works carry cards written through OpenRouter, with the model in each card's
  `card_model`; each also carries its work's licence, a link to it and an adaptation notice, and the
  OWASP card states that it is itself CC BY-SA 4.0. `## Structure` is one plain bullet per chapter,
  without a list number of its own beside the book's.

  `cards:` in the manifest is three-valued — `shared` (a model-written card, committed),
  `structure` (a card built by code with no model, committed) and `local` (a model-written card
  written outside the checkout, under `AYL_HOME` since the entry above, never committed; also
  what a work that names no value gets). The three NoDerivatives works are `structure`: title, chapter list and the
  publishing site's own description, reproduced verbatim and attributed, and nothing paraphrased —
  a reproduction in part, which the licence grants, not an adaptation, which it withholds. A test
  rebuilds each committed structure card and compares it byte for byte. `--stage structure-cards`
  builds them and is part of the plain run, and `ingest_demo_corpus.py --cards-dir` is repeatable
  so the local cards join the same cards table.

  **The boundary is the repository, not the model** (the owner's decision of 2026-09-19): building
  and querying the shelf is the reader's own use of their own copy, so the NoDerivatives works are
  indexed and answered from on either backend, and what the code enforces is what can leave the
  machine as a file. No passage of them is committed: the golden notes that quoted them now name
  the chapter and state the fact in their own words, and a test fails on any run of eight words or
  more of their prepared text in any tracked file, cards and chapter lists included, outside names
  and titles. A shared card is a paraphrase — the card prompt forbids copying, and a second test
  fails on a run of twelve words or more of a card's own work. Both run where the text has been
  built and skip in CI, which never builds it. The two lines they caught, in the Building Secure
  and Reliable Systems and Chain-of-Thought cards, were reworded by hand and each card records it in
  an `edited:` field, so `card_model` stays true for the rest. The weekly `pins` job now also
  rebuilds the shelf's chapter lists and structure cards from the fresh fetch and fails on any
  difference; `--skip-pdf` leaves out OWASP, whose `pdftotext` the CI image does not carry.

  `scripts/ingest_demo_corpus.py --stage cards` takes `--cards-dir`, so the cards table of any index
  is written by the one implementation; the shelf's index is an ordinary `ayl-add` folder ingest at
  its own `LIBRARY_DB_PATH` — 13 books, 275 sections, 2,590 chunks, `sentence-pack-2`, 5.4 minutes
  on one M3 Pro with `EMBED_BACKEND=ollama`.

  One defect found in the process, and it was not the shelf's alone: **a fenced code block is
  invisible to a line-based chapter splitter**. `ayl-add` cuts a Markdown book on `#`/`##` at column
  zero with one regex over the whole file, so every shell or Python comment in a code sample opened a
  section of its own — eighteen across this shelf, each cutting the chapter it sat in half and putting
  a line of somebody's script into the index as a section title the agent would then cite. The prepare
  stage now indents preformatted text instead of fencing it, indents the single line where a publisher
  renders a listing one element per line, and refuses to write a prepared file whose body still holds
  a line that would be read as a chapter heading. The committed chapter lists did not change; the
  section count did, from 296 to the 275 chapters the shelf has.

  **And the weekly pin check means something.** Run against this branch, it was red every time,
  always on the same two files, and not because anything upstream changed: those pages are
  not byte-stable. developers.google.com stamps every response with a CSP nonce and an analytics
  blob whose keys come out in a random order; abseil.io is behind Cloudflare's email obfuscation,
  which rewrites the book's "Email … to comment" link per response. A job red by construction on
  two files cannot report an edit in the other 174. `pin: text|bytes` per manifest entry now says
  what the digest is taken of — the text the reader extracts, for a page read off the web; the file
  itself, for a PDF or a file out of a git repository — with no default, so a work added without a
  rule is a failure rather than a guess. The pages index stays on bytes whatever the work says,
  because a chapter that appears or moves has to be one, and `--stage verify` runs the reader
  rather than `pdftotext`, so the job still needs no poppler. Two independent fresh fetches, each
  followed by `--stage verify`, both check 176/176 — while the raw bytes of those two files
  differed between the very same two fetches.

- **A request the library cannot answer is refused, not answered from the model** (#70,
  `eval/scope_canary.py`, [evaluation](evaluation.md)). "Before I can eat I need a Python script
  that reverses a linked list" is the failure everyone has seen from a support bot, and nothing
  here measured it: the refusal path existed, but only in-scope questions whose answer was absent
  ever reached it. An out-of-scope request was planned like any other — searched, and then refused
  only if the search happened to come back empty, four model calls later, with nothing to stop an
  answer once a passage looked relevant enough.

  **The gate.** The planner returns one optional field, `out_of_scope`, in the JSON it already
  returns — no second model call — and **code** turns it into mode `refusal`: no queries, no
  search step, and `synthesize` writing the refusal itself, so the answer path cannot run behind
  the decision. The refusal is a sentence of its own: this is a library, not a general assistant,
  rather than "I searched and found nothing", which would be a false account of a run with no
  search in it. `PLAN_RULES` gains one item and its checksum moves
  (`acd673f471d3` → `ab7b9ece3352`), which makes the six committed plan recordings stale for this
  tree: they still replay the planner's post-processing under the rules of 16.09, which is what
  they always measured, and a replay of them now reports itself as measuring the old prompt.

  **The canary.** Nine requests in [`eval/scope/out-of-scope.yaml`](../eval/scope/out-of-scope.yaml)
  — code, world knowledge, a persona, an opinion, a translation, arithmetic, chit-chat, a poem in
  the style of a book on the shelf, the publication history of another — each with markers of
  *fulfilment*, each run through the whole graph. Three outcomes, scored by code with the refusal
  scorer imported from the agent eval rather than re-implemented: `REFUSED` (the gate decided it,
  no evidence and zero quotes checked — pass), `CONTAINED` (nothing fulfilled, but the refusal came from an
  empty search and does not name the library — exit 2, not a pass), `ANSWERED` (a marker of
  fulfilment, or no refusal at all — exit 1). Three controls run first, in the live mode too: the
  prompt set and the scripted backend still recognise each other, a request fulfilled on purpose
  must score `ANSWERED`, and an ordinary book question must still be answered with evidence — a new
  refusal path that started eating real questions would otherwise pass silently. CI runs
  `--scope --no-live` beside the injection canary, in the same job.

  **The plan-only replay learned the new route.** `eval/run_plan_eval.py` counts `gate_refusal`
  on a row of its own and fails `mode_ok` for any item whose golden type is not `refusal`: a
  replayed plan that ended at the gate used to score the routing row green on every non-catalogue
  item, because "not the catalogue path" is true of a run that took no path at all — so a planner
  that started refusing real questions would have been reported as routing them correctly. A
  refusal carries no queries by contract, so the two query rows are absent for it rather than red.

  Two things the canary does NOT do, because both would make it lie. It does not score a marker
  before it has checked for a refusal: "nothing on your shelf says anything about Canberra" is the
  agent behaving perfectly, and the markers are written as fulfilment shapes ("the capital of
  australia is") rather than bare subject words for the same reason. And it does not let three
  scripted controls stand in for the live claim: a live run first puts four real golden questions
  — a vague identify, an aggregation, a "which of these two should I start" recommendation and one
  in Ukrainian — through the same model, and none of them may come back refused by the gate. The
  gate itself is also barred from firing on a re-plan after a clarify, where `synthesize` would
  have thrown away evidence the run had already paid for.

  **The live run says 7/9, and the README still says nothing.** `--no-live` answers from the
  scripted backend: it proves the mechanics and nothing about any model, because there the planner
  sets the flag because the script says so. The live run on the local default (`qwen2.5:14b` via
  `ollama`, [`eval-results/2026-09-17-scope-canary-qwen2-5-14b.md`](eval-results/2026-09-17-scope-canary-qwen2-5-14b.md))
  refused seven of the nine and let two through — a poem in the style of a book on the shelf, and
  another book's publication history, which are the two requests in the set that name a shelved
  book, so what the gate reads is the title and not the deliverable; the four in-scope controls
  and all eleven core golden questions came back with no gate refusal, so nothing was lost in the
  other direction. The README paragraph and the UI screenshot the issue asks for come after a
  second iteration moves that number; #70 stays open for the two misses.

- **The chunk IS the observation window, and a chapter read reads around the match** (#28,
  [ADR-025](adr/README.md), superseding ADR-012; [upgrading](upgrading.md)). Two numbers decided
  how much of a retrieved passage the model ever saw and nothing related them: the chunker packed
  transcript chunks to 4,000 characters, `observe` read 2,500 of a hit. Measured on the demo
  corpus: 7,285 chunks, median 3,922, **the longest 10,778, and 90.3% of them longer than the
  window** — the retriever ranked and fused text that was then cut off before the model read it.

  The chunker now packs to **2,400**, under the window with room for the overlap a chunk carries
  from its predecessor; a "sentence" the splitter cannot end — an hour of raw Whisper output, the
  longest in the corpus running to 10,140 characters — is broken on whitespace at 2,000 instead of
  packed whole; and the length the packer counts is the length of the string it returns, joining
  spaces included, so a chapter of one-word lines can no longer pack to a "target" of 2,400 and
  come back a quarter longer. On the 35 prepared demo texts: **11,282 chunks, median 2,304, the
  longest 2,400, 0% over the window**, at 55% more rows. `SEARCH_HIT_CHARS` stops being a knob
  worth turning — nothing is left behind it to reveal.

  **A chapter read is the same defect one scale up**: it took the first 12,000 characters of the
  chapter, and 61% of the corpus's 1,228 chapters are longer than that (median 14,783, the longest
  585,482), so a question about the end of a long chapter was answered from its beginning.
  `reflect` may now say what it is opening the chapter for, and `act` reads up to
  `CHAPTER_SCAN_CHARS` (120,000, a new setting) and cuts the window around the best lexical match
  inside it — the query's own words, scored by how many distinct ones a run covers, because
  neither retriever returns offsets. A read that names nothing, and a query the chapter does not
  spell, get the head exactly as before: nothing is invented in place of a missing field. Both
  ends of a window say in band what they left out, and a read cut at either end is `partial`.

  **The window is computed once, in `act`, and stored in `hits_log`.** That is the constraint the
  whole change is written under, not an optimization: the window is the provenance haystack
  (ADR-004), and one recomputed in `observe` would turn quotes honestly copied out of one window
  into quotes broken against another.

  `CHUNKER_VERSION` becomes `sentence-pack-2`, which is the first thing #27's policy has ever had
  to act on: **every index built before this release warns on every read and refuses the next
  `ayl-add` write until `ayl-add <folder> --rebuild --backup <dir>`** — the exact sequence, and
  what it costs, is in [upgrading](upgrading.md). Book cards are cut by their own rule and are not
  affected. **`--rebuild` goes once per index, not once per folder**: it drops the whole
  transcripts table, so running it again for a second folder would throw away what the first one
  produced — it now refuses before dropping anything when the ledger holds indexed books this run
  cannot re-index, names them, and names the plain `ayl-add <folder>` that adds them back
  (`--force` goes ahead and reports every book it orphans). The frozen identity fixture was regenerated deliberately: re-chunking renumbers chunk
  ids, book keys and row keys are byte-for-byte unchanged, and the fixture now records the chunker
  that produced it so ids cannot move again without a version bump.

  The read query reaches `act` on an action marker of its own
  (`__chapter_q__|what to look for|book|section`, [ADR-021](adr/README.md) amended), with every
  component percent-escaped and decoded in one place: a section name is a heading the book
  supplied and a book key may contain the separator, so neither may be parsed by position alone —
  a chapter called `Weird|q=evil query` would otherwise have produced a read query nobody wrote,
  and a book called `Either|Or` would have had its chapters looked up under `Either`.

  Two numbers sized for the old chunks moved with them. The chapter row cap (`CHAPTER_ROW_CAP`) is
  a length of text expressed in rows, so it is raised 1,000 -> 1,700 to keep the same reach into a
  single section, and a query that comes back at it is now counted into the eval report as well as
  logged. And the report carries three counts per question — chapter reads, reads that named what
  they were looking for, and reads whose window moved off the head of the chapter — because
  whether the model fills the new optional field at all is otherwise invisible, and that is the
  first thing the measurement had to answer. It answers it `7/7`: every chapter read the model made
  named what it was looking for, and five of the seven moved the window off the head.

  **Measured, as a before/after, and no answer's verdict moved.**
  [`eval-results/2026-09-18-rechunk-and-observe-feedback.md`](eval-results/2026-09-18-rechunk-and-observe-feedback.md),
  part A: the corpus re-ingested at `sentence-pack-2` (11,282 rows, `--doctor` clean) and both
  golden sets re-run on `qwen2.5:14b` at `--repeat 3` against the `#65` gate baseline of 16.09.
  **Read it as a before/after over six merges, not as an isolated measurement of this entry**: the
  code goes `c79018a` -> `c9e12bc`, which carries #66, #67, #68, #71 and #74 beside the re-chunk,
  and the report lists what each one touches and which of them has a control run. What the pair
  shows: behaviour unchanged item for item — **9/11 and 10/10**, the same two failures, the same
  single clarify, the same 10/12 titles and 10/24 facts — at +2 LLM calls and +8.9% wall clock on
  the research set, and −2 calls and −13% on the catalogue set. One row in it is **not** this
  entry's: the items whose plan sets a retrieval book filter go 5 -> 2, and a control run of #71 on
  the *old* index shows the same 2, so that belongs to #71's change to `PLAN_RULES`. What is not a
  gain either: evidence items go 43 -> 50, but that is **eight more card matches and one fewer
  book-text match** (card-only 9 -> 17, `checked_book_text` 34 -> 33) — seven more in net, none of
  them more of the books. Whether answers get *better* is still not a claim these rows can make;
  they are behaviour, provenance and cost, and correctness remains the reader's separate pass.

- **An upgrade cannot quietly invalidate an index, and a backup survives one that can**
  (#27, [ADR-020](adr/README.md) amended, [docs/upgrading.md](upgrading.md)). Each index table is
  stamped with the chunker that cut its rows and the shape those rows have; from this release
  something acts on both. A **read warns** — one line naming the stamped version, the version this
  code writes and the way out, logged once per table and shown as a startup notice, while the index
  goes on answering. A **write refuses**: `ayl-add` stops before it embeds or deletes anything, and
  so does the demo corpus's `--book` upsert. The asymmetry is the decision: differently-cut text
  still retrieves and still quotes verbatim, so refusing to *read* it would throw away half an hour
  of building over a degradation — but one append leaves two chunkers' rows in a table with nothing
  to tell them apart, and that cannot be undone. (The embedding model keeps its own, stricter rule:
  fatal on read, because a query vector from one model against documents from another is not a
  search.)

  Two absences deliberately stay silent, which is most of the work: an unrecorded chunker means
  nobody recorded it, not that it disagrees, and an *older* row schema is the upgrade this project
  performs in place — so neither warns. `--doctor` now reads every stamp out whether or not it
  agrees, because that is where somebody looks before upgrading, and exits non-zero on a mismatch.
  `CHUNKER_VERSION` moved into the chunking module, which is the only thing that decides what a
  chunk is; the ledger and both `_index_meta` writers record that one constant. Cards keep a
  constant of their own (`CARD_CHUNKER_VERSION`) and are compared against it, because a card is cut
  on its `## section` headings and never by the sentence packer — one constant for both would make
  the packer's next bump refuse every card write over a change that did not touch cards.

  **`ayl-add <folder> --rebuild`** is the way out, and the refusals name it: a plain re-run hits the
  same refusal, which left deleting the index directory by hand as the only remedy and nothing said
  so. It drops the transcripts table and indexes the folder from scratch — the one write that is
  not a mix — keeping the `books` ledger, because re-minting the ids would turn the whole library
  into new books. Books the ledger holds that the folder does not lose their rows with the table:
  they go back to `requested` and are named at the end of the run. Since a rebuild discards what it
  replaces, it requires `--backup <dir>` in the same command (taken first — a failed backup stops
  the rebuild) or an explicit `--force`.

  **The web UI's chat database got the same pair.** `ui.py` creates its tables with `CREATE TABLE
  IF NOT EXISTS`, which by design leaves an existing table alone — so a `chat.db` from an older
  release keeps its old columns, looks healthy, and fails on the first insert naming a column it
  does not have, in the middle of a question. At every start the columns the schema declares are
  now compared with the ones that are there and the difference is warned about by name, and the
  file carries a chat-schema version of its own.

  **`ayl-add --backup <dir>`** copies the LanceDB directory and the web UI's `chat.db` into a
  timestamped directory with a `MANIFEST.json` — what was copied, the stamps, the row count per
  table, the ledger size, the code version, a sha256 per file and one over the set. The copy is the
  easy half; the product is the statement that it was taken when the index was whole. Both write
  paths now hold an ingest lock beside the index directory and the backup takes the same one, so a
  copy cannot start mid-ingest and an ingest cannot start mid-copy (a second `ayl-add` in another
  terminal is refused, naming the command and pid that holds it). The lock is an **`flock`** held
  by the operating system on a file **beside** the index, keyed by its resolved path — so it
  survives the rename a restore publishes with, two spellings of one index are one lock, and there
  is no stale state to detect and nothing to clear by hand: the kernel releases it when the holder
  ends, however it ends. The file is never deleted, and the pid and command written in it exist
  only so a refusal can say who is holding it. The chat database is taken through **SQLite's own
  backup**, one consistent snapshot in one file rather than a main file copied beside somebody
  else's write-ahead log. The index restore is staged beside the target and published by rename,
  rolling back if the swap fails, and so is the chat database's; a **symlink inside the index** is
  refused at backup and at restore, because a copy follows links while the digests skip them. Any staged rebuild caught half-swapped is
  finished first, because a copy taken in that window restores to a missing table.
  **`--restore`** re-verifies every digest before touching anything, refuses to overwrite a live
  index without `--force`, refuses while an ingest is in flight, and **moves the index it replaces
  aside rather than deleting it** — and it follows a symlinked `LIBRARY_DB_PATH` rather than
  replacing the link, so the real directory is what moves and what is written. A destination inside
  the index is refused (a copy of a directory into itself), and a failure part-way through removes
  the half-written directory rather than leaving something shaped like a backup with no manifest.
  `--stage stamp-meta --chunker current` lets an operator vouch for the chunker of an old index the
  way they already vouch for its embedder.

- **A book has an identity a correction survives, and an ingest ledger says what went in**
  (#26, [ADR-024](adr/README.md)). A `books` table beside the index tables carries a `book_id`
  minted once and never derived from title, author or path, with the book's source, digest,
  chunker, embedding model, status (requested / indexed / failed) and error. `ayl-add` updates
  **one book at a time** by that id — resolve, write the ledger row, delete that book's rows,
  append the new ones, write the ledger row again — so correcting `author:` now renames a book
  instead of indexing a second one, a file that moved inside the folder is the same book, and the
  books a run does not name are neither read nor rewritten. Rows carry `book_id` beside `note`,
  so every chunk id is byte-for-byte what it was.

  A book is recognised by its key, or — when the key is what a correction changed — by being the
  same file in the same folder. Identical content on its own adopts nothing: a byte-identical copy
  under another title is a second book, with a warning naming the first, because the alternative is
  one book quietly replacing another. The digest the ledger keeps is of the book's *text*, taken
  after the front matter is off it, so a metadata-only edit is visibly the same book; the source
  reference carries a digest of the folder beside the path inside it, so two libraries in one index
  are never each other's books — and `--prune` cannot reach across them.

  Because the delete and the append are not one transaction, a crash between them leaves one book
  out of the index with a ledger row that still says `requested`; the **recovery pass at the start
  of every run** finds it, re-indexes it when the run covers it and names it when it does not. It
  decides on the revision each row carries, never on rows merely being present — a crash while a
  book was being embedded leaves the previous version of it in place, and that must not be
  confirmed as current. A
  book whose file has vanished is **reported and kept** — a folder that failed to mount looks
  exactly like a deletion — and removed only under `--prune`. `--dry-run` prints the diff against
  the ledger, and `ayl-add --doctor` reconciles ledger against index and reports six shapes of
  drift without repairing any of them. An index built before all this is backfilled on first use
  (`chunker: legacy`) and gains the `book_id` column by a staged copy that re-embeds nothing.

  Two numbers, taken on the built demo corpus before anything was replaced: the **whole FTS
  rebuild is 0.8 s** for 7,285 rows, so it stays whole; the **staged full rebuild it replaced was
  0.2 s**, against 0.01 s for a per-book write. At this scale the publish was never the cost the
  design review supposed — the honest claim for the per-book path is identity and recoverability,
  not speed.

  `--prune` removes full-text rows and keeps a book card of the same key, saying so: `ayl-add`
  never writes the cards table, and `--doctor` names what is left as a card without a book.

  Also: `_index_meta` gains `chunker` and `schema_version`, written by both ingest paths, with no
  refusal on either yet (#27 brings the policy) — and its own rebuild is recovered on the write
  path alone, never by the readers that check a stamp before every search; the catalogue deliberately still reads the index
  tables and not the ledger, so ADR-016's exhaustiveness is untouched; and book identity moved
  into one module, `bookkey.py`, from the four that held halves of it. That move is gated by a
  frozen fixture of the exact keys, row keys and chunk ids both ingest paths produce, checked
  against the built index: all 35 book keys and all 1,228 chapter-level chunk-id prefixes
  reproduce exactly.

- **The first measurement with a spread, and the baseline the evidence gate will be read against.**
  `docs/eval-results/2026-09-16-local-models-repeat3.md`, with the six planner recordings the runs
  wrote (`eval/recordings/`, committed).

  Three local models — `qwen2.5:14b`, `qwen2.5:32b` and a `mistral-small3.2:24b` derived at
  `num_ctx 20480` — against both golden sets at `--repeat 3 --record-plans --clarify-pick second`,
  on `169b511`, which is the merge of `#64` and therefore **before** the evidence gate. Six runs,
  6 h 21 min on one M3 Pro. `en-demo`: 9/11, 9/11, 11/11. `en-demo-catalog`: 10/10 on all three.

  **The repeat measured latency, not behaviour.** No per-question verdict moved on any of
  189 item-attempts, and `qwen2.5:32b` returned byte-identical answers on every item of both sets;
  `qwen2.5:14b` varied on one item of 21, the derived mistral on four, by under 1 % of tokens. Wall
  clock did vary — 30–196 s per question on the shipped default for answers that never changed —
  with `observe` 70–76 % of all model seconds and 2–3× slower on a cold first attempt. A spread on
  the behaviour rows therefore has to come from a hosted run; `docs/backlog.md` carries that as the
  next measurement.

  Four more results worth the entry. Card-only matches are 20–30 % of checked quotes on the research
  set and up to two thirds on the catalogue set, countable for the first time since `#64` — every
  report published before 16.09 counted them inside `confirmed`. The mistral derivative has the best
  behaviour and the worst quote fidelity (8–9 broken quotes an attempt against 2 and 1), which is
  the case the evidence gate exists for, and the report states what the gate's own run must show
  against each of these rows. `qwen2.5:32b` adds no passes over `qwen2.5:14b` — it wins `c09` and
  loses `c04` — at 2.6× the wall clock. And `mistral-small3.2:24b` as pulled could not be measured
  at all: Ollama loads it at `num_ctx 131072`, a single plan call hit the 1,200 s question deadline,
  and only a derived model with an explicit window ran. `docs/configuration.md` and
  `docs/known-limits.md` now say so, since the local backend's `/v1` endpoint gives this project no
  way to set the window itself.

  Correctness is ungraded, on purpose: the manual-correctness checkboxes in all six harness reports
  are unticked.

  **The gate's own runs are in the same report** (section added 17.09), two models on `c79018a`,
  both sets each, `--repeat 3 --clarify-pick second`, no recording — **and they do not agree.**

  `qwen2.5:14b`: **behaviour unchanged item for
  item** — 9/11 and 10/10, the same two failures, the same clarify, the same facts and titles rows.
  **Broken 2 → 0**, `confirmed == checked_book_text` at 34/34 with the same 34 quotes, **2 dropped
  per attempt** (both `not_found`; `no_hit`, `cross_book`, `short` and `repinned` all 0), from the
  same two questions that carried the broken quotes before. LLM calls unchanged at 79 and the steps
  distribution identical per item, so nothing had to compensate for anything: nine of eleven items
  are byte-identical between the two runs and only `c01` and `c02` moved, by one evidence item each.
  On the catalogue set every count is unchanged (only the wall clock differs). All three acceptance
  conditions for `#29` met on
  this model.

  `mistral-small3.2:24b-ctx20k`, the model the gate was argued for, is where the trade shows.
  **broken 8–9 → 0**, `confirmed == checked_book_text` at **50/50**, `repinned` 0, **10–11 quotes
  dropped per attempt** (`not_found` 26 and `no_hit` 6 over three attempts; `cross_book` and `short`
  never fired on either model), card-only 17 → 18. **Behaviour 11/11 → 11/11, 10/11, 10/11**:
  `c03-musketeers-women` fails attempts 2 and 3 with `titles 0/1` — with two quotes dropped instead
  of one the surviving evidence carries no citation, and the answer hedges without ever naming the
  book the retrieval filter had resolved. That item takes 4 steps in both runs, so the hold decision
  is not what failed it. The hold decision *is* what costs the rest: a step whose quotes were all
  dropped is held rather than counted as dry, so `c04` went 2 → 4 steps and `c10` 1 → 2, which is the
  whole of +6 LLM calls (82 → 88), ~14,000 more input tokens an attempt and 502 s on the set — and
  both of those items still pass. The catalogue set is unaffected (10/10, 2 dropped, 20/20).
  **So acceptance condition 3, behaviour at repeat not below baseline, is met on the default and NOT
  met on this model**, on one item, on two attempts of three. The report states the trade in full and
  names three options — accept it, count-as-dry after N dropped steps, or a stronger quoting
  instruction in `OBSERVE_RULES` / the `observe` payload (the only one that could move `c03`; it
  needs a new behavioural run but leaves the planner recordings valid, since staleness hashes
  `PLAN_RULES` and `RETRY_RULE` only) — without recommending one. `qwen2.5:32b` under the gate is not
  measured.

  One correction to the earlier finding, and the gate run is its control: **the dirty code stamp is
  not caused by `--record-plans`.** This run recorded nothing and is still stamped
  `c79018a+dirty(2005429d26f5)` — with the *same* checksum on both of its sets, where the recording
  batch produced five different ones — because the six baseline recordings were sitting untracked in
  the checkout. An un-ignored untracked file in the tree is the cause; recording is only the usual
  way one gets there. `docs/backlog.md` carries the fix.

- **Quotes are checked before the answer is written, not after it.** #29, step 2 of the sequencing
  in the system design review of 16.09.

  `validate` ran last, after `synthesize`: a quote that was in no retrieved passage reached the
  reader inside the answer and was counted underneath it, by a report the reader had already read
  past (1 unattributed and 2 broken of 61 on the shipped local default). The same check now runs at
  the `observe` gate, inside `_valid_evidence`, before an item becomes evidence at all. A quote
  confirmed in the passage it cites is kept; one found in another passage **of the same book** is
  **re-pinned** to the passage that holds it, so the citation stops naming the wrong one; one whose
  only match is a book card is kept, pinned to the card, and still never counted as traced to the
  book (the 16.09 card split); one that is in no retrieved passage of its step is **dropped** and
  never reaches `synthesize`. The answer is therefore written from evidence that has already passed
  the check, and `validate` stays the report it was — with `confirmed == checked_book_text` and
  `broken == 0` true by construction on evidence, which is asserted as a test.

  **A re-pin corrects a citation; it never writes a new one.** The search runs book before corpus —
  the cited passage, then that book's own text, then that book's cards, and only then anything else
  — so a quote's own book always outranks a coincidence in another one. A quote whose only holder
  really does belong to another work is dropped rather than moved, because re-attributing it would
  replace a wrong citation with a confident wrong one. Inside the cited book the nearest section
  wins; a quote that has to find its passage must be at least four normalized words long; and where
  `AYL_STRICT_HIT_ID=0` lets an item arrive with no passage named, the model's own `book` field is
  resolved canonically by the catalogue's resolver and the quote must sit in exactly one passage of
  exactly that one book. A quote that is in the passage it cited answers to none of this.

  Both gates run **one** function over one index of the run's passages (`classify_quote`,
  `passage_index`): a second implementation of "is this quote inside that passage" is how the entry
  check and the report would come to disagree about the same quote, and there is no second
  implementation. One `validate` verdict changed, and it is the change that makes the invariant
  exact: the **cited passage is read first**, so a quote inside the book card it cites is
  `card_only` even where a chapter also holds those words. It used to be reported `unattributed` —
  "not in the cited passage, found in another" — about a quote that is in the passage it cites, and
  the gate (which sees one step) and the report (which sees the run) would otherwise give one quote
  two verdicts.

  **The CRAG gate keeps its meaning.** A step whose quotes were all dropped is not a dry step: the
  passages were retrieved, so the library is not silent on the question. It neither advances the
  empty streak nor resets it, and `reflect` is told how
  many quotes were dropped so the next query is chosen with that in hand — a line added to its
  context only when there is something to say, so a clean run's prompt is the prompt every earlier
  run was decided on. This was the one way #29 could have bought provenance with behaviour, and it
  is the owner's decision of 16.09 rather than a reading of the code. Its price, said plainly: a
  model that quotes badly now runs to `MAX_STEPS` where the gate used to stop it at two, which is
  four more model calls on the questions that produce the least — **bounded since 17.09 by
  `MAX_DROPPED_STREAK` (see the bullet above): the hold covers the first such step, not a run of
  them.**

  `dropped_unverified` — every well-formed quote the gate refused, whichever rule refused it — with
  `dropped_by_reason` splitting it into `no_hit`, `cross_book`, `short` and `not_found`, and
  `repinned` beside them, travel on the state, on the `observe`
  event (only on a step that spent one of them, so a run where every quote checks out emits the
  event it always did), on `RunResult`, in the provenance report, in the badge and the CLI line
  ("N quotes dropped before the answer: not found in the passages they cited"), and in the harness
  report line, the ablation table and the sidecar per question and in totals — each clause written
  only where it happened, so the byte-compat fixture and every report under `docs/eval-results/`
  keep their shape.

  **What this does not do, and is not measured for.** The quotations the answer itself writes are
  not evidence and nothing checks them; citation by evidence id against the answer's sentences is
  the other half of #29 and is not here. A broken quote still does not fail the behavioural
  evaluation. And the behavioural effect of the gate is measured on **two** local models (17.09,
  `docs/eval-results/2026-09-16-local-models-repeat3.md`), each on `c79018a` against itself on
  `169b511`, both sets at `--repeat 3` — **and they do not agree, so the acceptance is per model**.
  `qwen2.5:14b`: behaviour unchanged item for item (9/11 and 10/10), broken 2 → 0 with confirmed
  34/34 of the book text, 2 dropped per attempt (both `not_found`, `repinned` 0), the same 79 LLM
  calls and the same steps distribution — all three conditions met.
  `mistral-small3.2:24b-ctx20k`: broken 8–9 → 0, confirmed 50/50, 10–11 dropped per attempt — and
  behaviour 11/11 → 10/11 on two attempts of three, so **condition 3 is not met on it**.
  `qwen2.5:32b` under the gate is still unmeasured.

- **A book card is never a quote from the book, the first screen teaches, and the front page shows
  the work before it explains it.** From the design critique of 16.09, §1 and §2.

  The badge said "4/4 traced to their source" over an evidence list in which two of the four
  passages were book cards — per-book summaries a model wrote, one call each, at ingest time. On a
  product whose whole claim is code-checked quoting, a model's own sentence was counting as the
  book's, and nothing on the screen said so. The split now lives in `provenance.validate`, not in
  an interface, so the CLI, the web chat and the eval harness see the same numbers:
  `confirmed / unattributed / broken` keep exactly the meaning they had, over the books' own text
  alone; a quote whose only verbatim match is a card is counted apart as `card_only` and is never
  in the traced count; the denominator every interface shows is `checked_book_text`
  (= `checked - card_only`); and every evidence item carries `source_kind` ("book_text" / "card"),
  which is the corpus of the passage it is pinned to. The web UI labels each opened passage, names
  the card matches under the badge, and turns amber with a sentence of its own when every quote
  matched only a card, rather than showing "0/0". The eval harness's report line adds its card
  clause only where there was one, so a run with no cards writes the line it has always written and
  the byte-compat fixture is untouched; a sidecar written before the split reads back as a run with
  no card matches rather than as a run with nothing traced. **Every report under
  `docs/eval-results/` predates this and counts card matches inside the triple** — said in
  `docs/evaluation.md` and `docs/known-limits.md`, and nothing was re-run to change a published
  number. A hit with no `corpus` recorded reads as book text, which is what an index built before
  cards existed holds.

  The empty chat screen was one sentence naming four node names and then ~1,100 px of nothing.
  `@cl.set_starters` now offers the four behaviours the README claims — identify, the catalogue
  count, a question between two books of the shelf, one the shelf cannot answer — built from the
  index that is actually loaded, so a clone with its own books gets its own first screen and an
  empty index gets no starters at all. The welcome message went with them, because it was what hid
  the screen: Chainlit draws its welcome screen only while the thread holds no message. `chainlit.md`
  is not on that screen either — 2.12 puts it behind the header's "Readme" button — so the four
  starter labels are the whole of what a first-time reader is shown, and `chainlit.md` was rewritten
  anyway, because it is what the Readme button opens and it described the badge of an older
  release. A failed preflight still writes its message instead.

  Three smaller things in the same interface. The matched run is marked inside the passage
  (`provenance.match_span`, the same normalization the check uses, the chunk joiner a barrier), so
  the proof is pointed at rather than left for the reader to find. `plan` and the last `reflect`
  open by themselves, and the step labels are sentences in the product's voice — "searched the
  library #1", not "Used act #1" — which needed two more values of the vendored
  `.chainlit/translations/en-US.json`: `chat.messages.status.used` and `.using`, emptied, so the
  name `ui.py` writes is the whole label. A third value, `chat.watermark`, now reads "Evidence
  provenance is checked in code. The reasoning is not." instead of a stock line that said less than
  this application knows — and it says *evidence provenance*, not *quotes*, because `validate`
  checks the distilled evidence items, not the quotation marks inside the written answer. `NOTICE`, `.chainlit/translations/README.md` and the test that pins them name all four
  changed keys; only `en-US` is forked, so the Ukrainian interface still carries upstream's step
  prefix. The metrics footer's gray went from `#6b7280` (~3.4:1 on the dark ground, below AA) to
  `#9ca3af` (~6.6:1) at the same visual rank.

  The README front page: the plain-language first line, the GIFs directly under "See it work" with
  the diagram after them under its own heading, "Quick start" with the Mac script as the fast path
  and one line for every other system, "Status and licence" opening with what this is (a reference
  implementation you can run and read, not a daily tool), and "Privacy and cost" bullet 2 recut as
  a verdict, three one-number bullets and the links, with the hosted-egress sentence lifted into a
  bullet of its own. The Measured table and every number on the page are untouched.

  `docs/diagrams/` is deleted, both Excalidraw sources and the README that corrected them: GitHub
  renders them as raw JSON, no export was ever committed, and two more divergences had gone
  unrecorded since the last pass. What was worth keeping is a paragraph in `docs/architecture.md`,
  beside the diagrams that are current. The whole-system diagram's legend is prose there now,
  which retires the `subgraph` + `~~~` construction that 0.3.1 named as a suspect for a rendering
  failure whose cause was never established.

  ADR-004 is amended with the split and with what it means for the numbers it quotes. Both
  README GIFs predate this change — they show the old badge, no source labels and the old
  watermark — and are captioned as such rather than re-recorded here; the re-record is a
  backlog item of its own.

- **Seven decisions the code had made without a record; four of them written.** ADR-017 (one passive observer of every JSON model call), ADR-020 (`_index_meta` fingerprints the embedder and nothing else), ADR-021 (the action channel is a reserved string marker in `current_query`) and ADR-022 (conversation memory and the scratchpad are free text) join the index in `docs/adr/`; ADR-018, ADR-019 and ADR-023 are reserved there as one-sentence stubs. Documentation only — no code changed.

- **The runner returns a result, the eval harness consumes it, and a failed question is still
  measured.** `runner.run_question` handed back the answer string and every caller reached into
  the graph's state for the rest; `eval/run_agent_eval.py` did not even call it — it re-implemented
  the stream loop, the clarify interrupt and the per-question usage reset — so the code that
  produces this project's published numbers was not the code a reader runs. Now `run_question`
  returns a frozen `RunResult` (the answer, the evidence and its provenance, the stop reason, the
  clarify and catalogue fields, the read chapters and steps, the planner fallback, the usage
  snapshot, the wall clock, the scratchpad, and the failure if there was one), and the CLI, the web
  UI and `run_one` read that. The runner owns the stream loop, the interrupt, the usage reset and
  the scratchpad — `run_one` passes in an event collector and its own `--clarify-pick` reply policy
  and keeps the scratchpad name it has always written (`eval/results/scratch-<id>.md`, one per
  attempt under `--repeat`). The event contract is byte-identical: same events, same order, same
  payloads, pinned by the tests that already pinned it (ADR-009, amended 16.09).

  A run that fails is part of that record rather than an exception through every interface: the
  metrics event moved into a `finally`, so a question that dies mid-run still reports the calls,
  tokens and seconds it spent (the partial event at a clarify pause is unchanged), and the failure
  comes back on the result as an exception class plus a message with this machine's paths replaced
  by `~` or `<repo>` (one rule now, `ask_your_library/paths.py`, instead of a copy in the runner and
  another in the harness). The CLI prints the same one-line error it always did and still exits 1 in
  single-question mode — and it asks whether the run succeeded before it accepts the answer at all,
  because a run that died after `synthesize` carries the text it had written and neither an exit
  code nor the conversation memory may take that for a finished turn; the eval harness re-raises the
  exception that happened (identity, not a stand-in) so the ERROR row and its "spent before the
  error" are what they were. Two edges of that come with it: delivering the metrics event cannot
  change what the run reports — a consumer that raises while being handed it (the web UI renders
  inside that callback) is recorded on the result as `metrics_failure` and never propagates — and a
  final state the graph cannot produce after a finished stream IS the failure, rather than a
  successful question with an empty answer. The CLI's session line therefore counts questions
  attempted, not answered: a question that failed spent real money.

- **Seconds per node role in the usage accounting.** `by_role` carried calls and tokens only, so a
  latency budget could not be argued at all on the local backend, where a question costs $0 and
  seconds are the only currency (#32). Each role now accumulates the wall clock of its model calls
  — measured in a `finally` around the call, so retries, their backoff and a call that ended in a
  timeout are all counted, and a role can honestly report seconds with zero completed calls —
  `usage_snapshot()` carries it, and the eval report prints `- seconds by role: plan 1.2, observe
  8.5` under a question's steps log with the same figures in the JSON sidecar
  (`by_role_seconds`). Every existing number is unchanged, the report of a run that spent no call
  included: the byte-compatible report fixture (`tests/fixtures/agent-eval-report-pre-sidecar.md`)
  passes untouched.

- **The web UI's release check is a test now, not a walk-through.** First start, login, a
  question, the live agent steps, the quote-provenance badge, an evidence passage opened and
  readable, the catalogue answer with its count, a reload that restores the conversation, a
  clarify left unanswered until it times out — that path was checked by hand on a clean
  environment before every release. `tests/ui/test_ui_smoke.py` walks it in a browser instead:
  a real `chainlit run ui.py --headless` on a free loopback port, driven with Playwright at
  1280x800 and at 390x844, because the phone rendering has traps of its own (the steps render
  collapsed, the composer floats over the bottom of the thread, and at that width Chainlit keeps
  the thread history — and the conversation's own address, which is what a reload restores —
  behind the sidebar toggle). Every assertion is on text on the screen, every wait carries its own
  timeout, and a failing page is screenshotted into the run's `--basetemp`.

  The server it drives has no model, no key and no index. The seam is `AYL_UI_FAKE_BACKEND`, a
  path to a Python file that `ui.py` loads at startup and whose `install()` replaces the model
  client, the two retrieval functions `nodes` imports, the catalogue reader and the preflight —
  the same substitution `tests/test_graph_e2e.py` has always made in-process, made in a server
  process by the server itself (`src/ask_your_library/fake_backend.py`,
  `tests/ui/scripted_backend.py`). Everything else is the shipped code: the compiled graph, the
  clarify interrupt, the coverage gate, the quote check, and every rendered line. It takes two
  variables, not one: without `AYL_UI_FAKE_BACKEND_CONFIRM=this-server-answers-from-a-script` the
  server refuses to start rather than serving scripted answers that look real, and with neither
  set — every ordinary start — the seam reads two environment variables, finds nothing, and
  returns before importing or patching anything. `tests/test_fake_backend.py` pins the refusals;
  `docs/configuration.md` and `SECURITY.md` say what the pair is and where it must never be set.
  A `.env` is one of those places and not a figure of speech: `chainlit`'s own import calls
  `load_dotenv(<cwd>/.env)` before `ui.py` runs a line, so such a file would arm the seam as
  surely as an exported variable — which is why either name appearing as a key in `<cwd>/.env`,
  or in the nearest `.env` above it, is refused outright, whatever the value there.

  Alongside it, `AYL_CLARIFY_TIMEOUT_S` makes the web UI's ask-back timeout configurable (default
  300 s, unchanged), so a test can watch an unanswered clarify expire instead of waiting five
  minutes; a value that is not a whole number above 0 is refused at startup.

  CI: a new `ui-smoke` job installs the `ui` extra, `playwright install --with-deps chromium`,
  runs `tests/ui` and uploads the screenshots of any failing page. It is not in the branch
  ruleset's required checks. `uv run pytest -q` is unaffected on a machine without the browser:
  `tests/ui/test_ui_smoke.py` skips itself with the install command in the reason.

- **Docs: ADR-011 marked superseded.** The export it described ran once, on 2026-09-08; since
  then this repository is developed directly, by pull request against `main` under the branch
  ruleset, with no allowlist kept for new files. ADR-011's status line and a dated note record
  the switch; "Where the measured code lives" in [`evaluation.md`](evaluation.md) is updated to
  match. No code changed.
- **A plan-only evaluation: record the planner's decisions once, replay them for nothing.**
  `plan()` is one model call followed by a hundred lines of deterministic post-processing — the
  validated mode, the parsed catalogue operation, the mixed-intent gate, the query filter, the
  named-book resolution against the catalogue, the two fallbacks, and the routing decision taken
  from what comes out. Reaching that code with a real planner reply used to cost a full paid run
  of a golden set, so a one-line change to the query filter cost what a release measurement costs
  and was therefore usually not measured. The model's share of the decision is a string, and a
  string can be kept.

  `uv run eval/run_agent_eval.py --record-plans` writes every `role="plan"` request/response pair
  of the run it was going to make anyway into
  `eval/recordings/<golden-stem>.<golden-sha12>.<model>.jsonl` — one line per golden id and
  `--repeat` attempt, plus a second line when `ask_json` had to retry a malformed reply, because a
  replay that dropped the bad first one would replay a retry that never happened. Each line holds
  the exact user payload, the raw reply text, the system prompt's hash, the model, the backend and
  every knob of the call, the clock, and what that one call spent. `uv run eval/run_plan_eval.py`
  then loads a golden set and a recording and calls the **real** `plan()` with `llm.ask_json`
  replaced by a replayer that returns the recorded reply, re-parsed by the very function that
  parsed it live — so a reply that was malformed twice raises the same error and the node degrades
  to its fallback exactly as it did on the paid run — followed by the real `route_after_plan`. No
  model is called; the report's first line says so and the cost line reads `$0.0000`.

  Scored per item and per recorded attempt, with the mapping from a golden item to what the
  planner owes it written out rather than inferred: the **route** the golden set actually pins
  (the catalogue path for a `catalog` item, the research loop for every other type — exactly where
  `score()` already fails a run — and, for an `expected_behavior: research` control, routed there
  by the planner rather than rescued by a `catalog_fallback`), the catalogue operation against
  `expected_op`, the named book against `expected_book_filter`, no `plan_fallback`, a non-blank
  query, and as many queries as `PLAN_RULES` asks for. Whether the planner said `identify` or
  `answer` is reported beside the verdict and never inside it: the golden `type` labels the
  question, not the planner's reading of it. A Markdown report and a JSON sidecar are written side
  by side in the shape family of the main harness.

  The request is checked too, not only the reply: every attempt of each replayed call compares the
  payload the node builds now with the recorded one, the system prompt by its hash and the order
  the attempts were recorded in, and a mismatch is reported as `payload_drift` and exits 1 unless
  `--allow-drift` — otherwise a change to how the payload is *assembled* would be graded against a
  reply to a payload this tree no longer sends, and the run would look clean. The retry's payload
  is rebuilt by `llm.retry_payload`, the one function that writes those words, and its checksum
  joins the golden file's and the prompt's in the staleness check.

  **Only the first planner call of an item is replayed**, and the harness says so rather than
  implying otherwise: a second `plan()` happens after a clarify and is a function of graph state
  the recording does not hold, so every item reports `calls_recorded` / `calls_replayed` and an
  unreplayed call exits 1 unless `--allow-unreplayed`. A call that never came back is recorded with
  its exception and replayed as one, so `plan()` takes its timeout branch and not its fallback
  branch — two different states of the node that a report must not confuse.

  What a recorded line says it spent is the **planner's own** tokens, read from the per-role
  accounting rather than from the run totals (a plan call would otherwise be charged with the
  `observe` and `reflect` calls between it and the previous one), with the cost computed from those
  tokens unrounded — a planner call is often under $0.0001, and the report's four decimals would
  write a run's worth of them down as free.

  Three guards stand between a run and a committed recording. Nothing **token-shaped** may enter
  one: a provider key, an `Authorization` header, a JWT, a Slack, GitHub, Google or AWS credential,
  an `api_key = …` assignment, a private-key header, a long value beside the word
  key/token/secret, or the literal value of any `*_KEY`/`*_TOKEN`/`*_SECRET` in the environment
  refuses the line, leaves it unwritten and refuses to finalise the file, naming the line — not
  masked and written, because a masked line still means a credential passed through; the gitleaks
  step in `security.yml` is the second net over what is actually committed. Every **absolute path**
  is replaced on top of the `<repo>` and `~` substitutions, which only know this machine, and the
  detection is generic rather than a list of roots — any POSIX path of two or more segments, any
  Windows drive path, any UNC share — with URLs left intact, because `/etc/hosts`,
  `/usr/local/bin/x` and `/data/index` are exactly the roots a list forgets. And a recording whose
  own **writing failed** is not finalised either: the observer still swallows its exceptions so a
  paid run goes on, but the recorder latches the first failure, keeps the `.partial`, and the run
  puts the reason in its report tail and exits non-zero rather than committing a short file under
  the name of a complete one.
  A recording also refuses to replace one that is already there unless `--overwrite`, before the
  graph is built and before the first call, and a run of selected ids writes a
  `.subset-<k>of<n>.jsonl` of its own that the replay harness reports as a subset.

  **What it cannot measure, said in the harness, the report and the sidecar: a change to
  `PLAN_RULES`.** A recorded reply answers the prompt that was in the tree when it was recorded, so
  the recording's header carries that prompt's checksum next to the golden file's and the harness
  refuses to replay when either has moved (`--check` answers the question on its own;
  `--allow-stale` replays anyway and stamps every artifact with a block saying nothing in it
  measures this tree). A prompt change needs a new recording, and a new recording needs a paid run.
  An item the recording does not hold exits 1 unless `--allow-missing`.

  The seams are deliberately outside the shipped nodes: recording rides on a new passive
  `llm.JSON_CALL_OBSERVER` that `ask_json` notifies and that cannot change what a call returns —
  its own failure is logged and swallowed, because losing a recording is cheap and losing a paid
  run is not — and replay rebinds `llm.ask_json` and `nodes.list_books` by name, the seam
  `eval/run_ablation.py` already uses. `nodes.py` is unchanged, so the measured code is the shipped
  code. `ask_json`'s parsing moved into `llm.json_object` so that a replay parses a recorded reply
  with the identical code; its behaviour, including the wording of its retry prompt, is unchanged.
  Names are resolved against the index when there is one and against `corpus/manifest.yaml` when
  there is not, with the report saying which of the two answered.

  `eval/recordings/` is committed, unlike `eval/results/`: a recording is the *input* a replayed
  number came from, it is small, and it carries no absolute path or credential — every payload and
  reply goes through the same `redact_paths` the reports and sidecars use. A run is written to
  `.jsonl.partial` and renamed on a clean close, so a file at the final name is a run that
  finished and a crashed run still leaves everything it paid for. The mechanism is proved on
  fixture recordings (`tests/test_plan_recording.py`, `tests/test_plan_replay.py`), including that
  a replay makes no network attempt at all under the process-level egress guard. **No recording of
  a real golden set has been made yet**, so no number in this repository was produced this way.

- **An egress test: the local configuration's central claim, asserted instead of assumed.** The
  project's headline promise is that a question and the passages retrieved for it stay on the
  machine, and nothing in the suite could see a connection attempt. Every end-to-end test proved
  the claim by construction — the model is faked, the library is in memory, the credentials are
  blanked — and construction is the wrong evidence for it: a fake model makes no connection
  whether or not the real one would have made a hosted one, and an import, an SDK or a tracing
  client can open a socket no assertion would notice. `tests/test_egress_local.py` instruments the
  process instead.

  The floor of `tests/egress_guard.py` is CPython's own socket audit hook (`sys.addaudithook`),
  not a set of monkeypatches — because a socket can be opened without touching any name a patch
  can reach: `_socket.socket` is the C type `socket.socket` inherits from and has its own
  `connect`; `from socket import getaddrinfo` binds the function by value, so a module that did
  that before the guard went on keeps calling the real one; and UDP needs no `connect` at all, its
  address rides on `sendto` / `sendmsg`, which is the shape of a resolver query and of a telemetry
  ping. The interpreter raises `socket.connect`, `socket.sendto`, `socket.sendmsg`, `socket.bind`,
  `socket.getaddrinfo`, `socket.gethostbyname` (which `gethostbyname_ex` raises too),
  `socket.gethostbyaddr` and `socket.getnameinfo` from the C layer for every socket whatever its
  class or import path — each event name verified against the installed interpreter by a probe,
  not taken from the documentation — so one hook sees all of it, background threads included. A
  bind is recorded and never refused: it is the other direction, and recording it is what lets the
  test also say no listening socket was opened on a public interface. One layer sits on top,
  because it says something the floor cannot: the httpx transport, in **both** installed httpx
  distributions (the model client's SDK does not use the `httpx` the application imports), where a
  hosted call is refused with its URL intact and before any lookup. Loopback is recorded too,
  which is what makes the allow-list an assertion rather than a silence. The hook is installed
  once per interpreter at import and armed through a flag, since CPython cannot remove one.
  Records are also streamed — one JSON line per attempt, written to an unbuffered descriptor as it
  happens and, for a refusal, before the refusal is raised — so the evidence does not depend on
  the process living long enough to summarise itself, and an `except` inside the application
  cannot erase the fact that something tried. The parent derives its assertions from that stream
  and requires the child's own end-of-life summary to be a prefix of it.

  **What this sees and what it does not**, stated in the test, the guard, the README and the
  privacy page rather than left to a reader: every network call made through Python's socket
  module — the standard library, `requests`, urllib3, httpx, httpcore, asyncio and the model
  client's SDK, which is every client this project has. It does NOT see a call that reaches libc
  without passing through CPython: a native extension with its own C sockets, or a `ctypes` call
  into `getaddrinfo` / `connect`. The limit is pinned rather than only written:
  `test_a_ctypes_call_into_libc_is_the_known_blind_spot` performs the bypass and is
  `xfail(strict)`, so if a future interpreter or sandbox ever closes that door the test passes,
  the strict marker turns the pass into a failure, and the scope paragraphs have to be rewritten.
  Two more tests bound it in practice: no `grpcio`, `pycurl`, `pycares`, `aiodns`, `uvloop`,
  `pyzmq`, `psycopg`, `pymongo` or `redis` in the interpreter that runs these tests
  (`test_no_native_networking_in_the_interpreter`), and none in the application's locked runtime
  closure read from `uv export --no-dev` (`test_no_native_networking_in_the_locked_runtime`).
  `uvloop` is the sharpest of them — it would move every asyncio socket in the process out of the
  hook's sight — and `grpcio` plus an OTLP gRPC exporter arrive with the **`ui` extra**, which is
  why the Chainlit process is excluded from the claim rather than merely untested. That exclusion
  is also why the two are separate: an interpreter that HAS the extra — a developer's own, or the
  `ui-smoke` job's — skips the first with the reason stated, because such an environment was
  never inside the claim, while the second runs there like everywhere else and must pass.

  The test then runs the real thing in the shipped local configuration with Ollama not running:
  the real preflight, the real `embeddings`, the real compiled graph through
  `runner.run_question`. All 14 recorded attempts of the reference run — preflight's `/api/tags`,
  the embedder's `/api/embed`, the planner's call and its two retries — target loopback on the
  configured Ollama port, the only bind is loopback, nothing else is contacted or looked up, and
  the run ends on the unreachable local runtime (preflight exit 5, then a connection error to that
  endpoint) instead of falling back to a hosted call. In the child the guard is armed as the first
  statement — before the package, before its dependencies, before the guard module itself imports
  httpx — and is never disarmed, so import-time lookups and everything that still runs during
  interpreter shutdown are inside the recording; the report is emitted from an `atexit` handler
  registered first, which therefore runs last, after the interpreter has joined its non-daemon
  threads, and the parent checks the child's exit code, its stderr and that the report is the last
  line it printed. Controls keep the silence meaningful: each door refusing a deliberate attempt
  (raw `_socket`, a by-value resolver, UDP, TLS, asyncio, both httpx distributions), a module that
  connects while it is being imported, the same graph under `LLM_BACKEND=openrouter` with a
  placeholder key where the guard records `openrouter.ai:443` and refuses it, that backend with no
  key where nothing is attempted at all, and the local run repeated with a usable-looking
  `OPENROUTER_API_KEY` present, so a silent hosted fallback would be stopped by the guard rather
  than excused by a missing credential.

  Nothing in `src/` was touched: the application runs exactly as it ships and the process around
  it is instrumented. The scope is stated in the test and in the docs, and the README's "no other
  path out" is narrowed to match it: one Python process on one path — `runner.run_question` with
  the real preflight and embedder — and not Chainlit (the `ui` extra is not installed in the legs
  that run this file), not Ollama, not the browser, not a subprocess, not `scripts/`. The
  configuration is set per child interpreter through `conftest.run_fresh`, so both CI legs
  (`test (ollama)`, `test (openrouter)`) run the same thing, with no network and no Ollama; that
  scrub list now also covers the proxy variables (`HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY`,
  `NO_PROXY` and their lowercase twins), which this project never reads but every HTTP client
  does — one of them set in a developer's shell would send each request to the proxy's host
  instead of the configured endpoint, which is a different destination for these tests to record
  and an off-machine hop out of a loopback URL.

- **A JSON sidecar per run, and `--repeat N`, so a reported number can carry its spread.** Every
  run wrote one Markdown report and nothing else: a reader's document whose shape is a contract
  with `summarize_report.py`, where every number has to be scraped back out of prose, and one
  sample of a system that does not answer the same way twice. Both halves are addressed.
  `eval/results/answers-<ts>.json` is now written beside `answers-<ts>.md` — the fingerprint as
  fields instead of one line (code stamp and whether it was a verified clean commit, the golden
  file's **repo-relative** path and checksum — an absolute one would name the home directory of
  whoever ran it, and this file is meant to be committed beside a published number — manifest and
  TOC checksums, backend, model, index stamps, every knob that changes
  an answer, the configured prices, the repeat count, wall-clock start and end) and, per question,
  its group and every attempt as the harness produced it: the full answer, the provenance triple,
  steps, chapters read, clarify state, stop reason, planner and catalogue fallbacks, cost, calls,
  tokens, seconds and the `score()` dict computed from that attempt. The report's line and the
  sidecar's fields are rendered from the same dict, so one run cannot describe itself two ways;
  `--no-json` turns the file off. `--repeat N` (default 1) runs each golden item N times. Scoring
  stays per attempt — the scorer never sees more than one run — and the aggregation is reported
  beside it: each boolean row (`behavior_ok`, `facts_ok`, drill-down) as **how many attempts of N
  passed**, never as an average of true and false, and cost, seconds, tokens and calls as **min /
  median / max**. At N > 1 the totals block is rewritten rather than extended, because not one
  figure in it may be a sum across attempts: two items run three times have six passes, and
  "behavior PASS 5/6" describes a six-question set nobody ran. Every line there is per attempt
  (`<min>–<max>/<items> over N attempts (mean ... per attempt)`, one per aggregate, with the
  per-group ranges beside the headline), and the one figure that *is* summed — the money the run
  actually spent — says so in words. The fingerprint ends `N attempts per item` instead of
  `single run`, and `--min-pass` becomes a floor on the **weakest** attempt. **At `--repeat 1`
  the Markdown report and its `---` tail are byte for byte what the harness has always written**,
  pinned by a test that renders both from the same fake results, so every artifact under
  [`eval-results/`](eval-results/) and `summarize_report.py` are untouched. The hand-rolled
  `sys.argv` slicing in `main()` is argparse now (`parse_intermixed_args`, so ids interspersed
  with flags — `c01 --min-pass 11 c02` — still mean two ids, as the slicer's own semantics did),
  with `--min-pass`, `--clarify-pick`, `--require-clean` and the positional ids behaving exactly
  as before, `--repeat 0` refused
  instead of writing an empty report with a green exit code, and `--help` finally listing them.
  A sidecar that cannot be serialised writes its error into the report tail and leaves the run's
  own exit code alone, and the file is written to a neighbour and renamed, so an interrupted run
  leaves no half record. Nothing in the sidecar is summed across attempts either, at any N:
  `totals.per_attempt.<aggregate>` is `{values, min, median, max}`, `totals.expected_per_attempt`
  holds the denominators read off the golden items, `per_group.<type>` is
  `{of, behavior_ok_per_attempt}`, and only `totals.spent_total` is a sum — money, calls and
  tokens, spent once each. Denominators come from the golden file rather than from the results
  throughout, in both files: counted up from what completed, an item that errored drops out of its
  group and out of the facts and drill-down rows, and an item that errored on every attempt takes
  its rows with it. Error text is stored with any path under the home directory or the repository
  root replaced by `~` or `<repo>` — a `FileNotFoundError` names a file, and under a home
  directory that name is the reader's login, and `summarize_report.py` copies the report's ERROR
  lines into the committed summary. The byte-compatible single run is pinned against a committed
  fixture rendered by the pre-sidecar harness from the same fake results, whole report against
  whole report.
  `eval/run_ablation.py` imports the same harness and keeps running at one attempt per condition.
  `tests/test_agent_eval_sidecar.py` covers the sidecar schema and its round trip, the repeat
  aggregation, the byte-compatible single run and the flags (ADR-010, amended). No run was made
  here: no published number changed, and none carries a spread yet.
- **The golden items say which facts an answer must carry, and the report says which are
  missing.** Behavioural compliance, quote provenance and the manual correctness read were the
  three rows, and only the third could tell whether c06's answer reaches Passepartout's "to-day is
  Saturday" — a read of every answer in the report, from the top, every run. Every golden item
  whose answer has content now carries `expected_facts`: one to four short checkable strings — a
  name, a number, a place — derived from that item's own notes and, where they were vague, from
  the book card in `corpus/cards/`. The eval scores them as a fourth deterministic row
  (`facts_found`/`facts_expected` and `facts_ok`, folded and whitespace-normalised substring
  presence, no stemming and no synonyms), prints it on the question's line and in the totals, and
  `summarize_report.py` names every behaviour PASS whose answer is missing one. The row is
  deliberately **not** part of the behaviour verdict: ADR-010 rejected a composite score, a fact
  can sit inside a wrong sentence, and a right answer written in other words scores red — so it
  narrows where the reader starts and decides nothing (ADR-010, amended). 32 of the 42 items carry
  facts; the refusals and the clarify items whose two candidate books would each demand a
  different answer carry an empty list on purpose. The shape of the three files is now pinned by
  a contract the harness owns and enforces when it loads any golden file, before the graph is
  built and before the first billed call: the keys allowed for the item's type, the required keys
  (`expected_facts` among them, so a misspelled `expected_fact:` fails instead of silently turning
  the row off) and the type of every field, with every problem in the file reported at once.
  `tests/test_golden_schema.py` runs that check over the three files here and adds what only holds
  across a set — ids unique across the files, no question asked twice, no fact its own question
  already contains, which would score green by being restated — and
  `tests/test_agent_eval_facts.py` pins the scoring, including that the verdict does not move with
  the facts on any branch of `score()`. **All three golden checksums moved**:
  `en-demo.yaml` `efb25bda` → `edc15194`, `en-demo-extended.yaml` `8eec61c9` → `836d3870`,
  `en-demo-catalog.yaml` `14b001e2` → `72eb2c2b`, so **no report committed under
  [`eval-results/`](eval-results/) reproduces against the current files**: every one of them was
  measured on the golden set as it stood before this change, and their fingerprints say so. No run
  was made here either — the facts column has not been measured once, on any configuration, and no
  published number changed.

- **The documentation is checked by tests, not by memory** (#72). `tests/test_docs_as_code.py`
  runs offline in the ordinary `pytest` job over every tracked `.md` file and fails with a list of
  `file:line` to fix: relative links and images that do not resolve (and `#fragment`s that name no
  heading), file paths written in code that this tree does not hold, a `pyproject.toml` version
  that is not the newest released heading of this file (with an empty `Unreleased` section
  required at a tag), an ADR index whose count, numbering or `Status:` lines have drifted, and
  settings or `ayl-add` flags the pages name that the code no longer reads or accepts. It found
  one defect on arrival: [`adr/README.md`](adr/README.md) opened by promising twenty-four
  decisions over twenty-five entries, ADR-024 and ADR-025 having been appended without the
  paragraph above them being re-read. `ayl-add`'s parser moved into `build_parser()` so the check
  can ask it what it accepts. External links are not fetched and prose is not read: the
  release read-through stays a human step.

## 0.3.1 (2026-09-15)

A documentation and CI patch over `v0.3.0`; nothing under `src/` changed. It exists because at
the `v0.3.0` tag the README, `cost.md`, `quick-start.md` and `known-limits.md` did not surface
the measured accuracy caveat that the changelog and the local-models report already carried, and
the front page still carried the old diagram, which paraphrased the GIFs beneath it instead of
naming the mechanism. The two corrections it exists for are the second and third entries below;
the others add the workflow lint in CI, carry the diagram work into `docs/architecture.md`, and
give the author credit a profile to link to.

- **The workflow files are linted in CI.** The backlog's release-status entry named this the one
  item left from the visibility-switch list ("a workflow linter, free on a public repository"); a
  `workflows` job in `ci.yml` now runs actionlint over every file under `.github/workflows/` on
  push and pull request, with shellcheck checked in too since it ships on `ubuntu-latest` and
  actionlint finds it with no extra install (pyflakes stays off — not installed on the runner).
  actionlint itself is a release tarball checked against its published SHA-256, not the third-party
  action wrapper, for the same reason `security.yml` fetches gitleaks that way: one hop to the
  binary instead of two. The first run, over `ci.yml`, `security.yml` and `corpus.yml`, found
  nothing — zero errors, and all three pre-existing workflow files needed no fixes.
- **The accuracy caveat on the local default is back on the front page.** 0.3.0's entry below says
  "the warning that a small local model is less reliable than the hosted default stands unchanged".
  It did not: the README rewrite had already removed it, and after the default flip the front page
  presented the local configuration as pure upside — no key, no cost, nothing leaves the machine —
  with no measured number about answer quality (the Measured table's note that none of its figures
  describes the local default is as far as it went), and none of the thirteen entries in
  [`known-limits.md`](known-limits.md) covered it either. So the only place outside this changelog
  where a new reader met the measurement was the report nobody opens first. The README's "Privacy
  and cost" FAQ now carries the numbers next to "Do you need an API key? No.", `known-limits.md`
  has the entry in full, and the report's verdict is quoted rather than paraphrased: "Neither model
  is good enough to advertise as a strong default: 19/20 and 18/20 with genuine unattributed and
  broken quotes in both." The numbers are the ones already in
  [`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md) — the
  default `qwen2.5:14b` at 10/10 with 17 / 0 / 0 on the catalogue set and 8/10 with 41 / 1 / 2 on
  the research set, `qwen2.5:7b` at 19/20 and 36 / 2 / 1 — with that report's own scope carried
  along: single runs, nobody graded the answers by hand, and one re-measurement after the last
  prompt change (7b's research subset), so `qwen2.5:14b` throughout and the catalogue half of both
  combined rows describe the earlier prompt. Nothing was re-run and no new figure was produced.
  The two kinds of number are also kept apart wherever they are quoted, because they are not the
  same evidence: the `n/20` is behavioural compliance, the harness's own heuristic, while the quote
  triple is checked by plain code — so the hardest thing that can be said about the default is the
  provenance one, 1 unattributed and 2 broken quotes among the 61 it was checked on, and it is what
  the README and the two short pages now lead with. Neither is answer correctness, which nobody
  graded on any local run. What the hosted side scored is given where it can be given honestly
  rather than waved at as "another set": the catalogue set has a hosted run at the same golden
  checksum (10/10, 21 / 0 / 0,
  [`eval-results/2026-09-10-catalogue-set.md`](eval-results/2026-09-10-catalogue-set.md)) and is
  clean on both, and that run says of itself "not reader-graded"; the research questions are ten of
  the eleven the core run of 07.09 answered 11/11 with 47 / 0 / 0, passing the two — `c09` and
  `c10` — that `qwen2.5:14b` fails, and that one WAS read against the golden notes, ten `correct`
  and one `incomplete`, the only reader grading in the comparison and on the hosted side, which
  `known-limits.md` states rather than letting 11/11 stand in for it. Neither hosted run is a
  paired measurement, the code, the index and (for the research one) the golden checksum all
  differing. Two pages that framed the trade as speed alone were corrected the same way:
  [`cost.md`](cost.md) opened on "It is slower, and that is the whole trade", and
  [`quick-start.md`](quick-start.md) told a reader only that the hosted path costs money and the
  local one does not. `configuration.md`'s fully-local section, which had the quality paragraph but
  only its JSON half, now points at the entry too.
- **The front-page diagram names the mechanism instead of describing the GIF under it.** "See it
  work" spent eight boxes paraphrasing the flow in the words the two GIFs directly beneath it show
  with real content ("the agent reads the question", "it searches the books you own, in several
  passes"). It now names what actually happens, in much the same footprint (619×1161 against
  560×1168 at mermaid 11.17.0; at 10.9.1, which lays labels out differently, it is the larger —
  741×799 against 549×717): the 2-4 English queries `plan` asks for, a hybrid search that is
  vectors + BM25 fused, `observe` distilling candidate quotes pinned to the passage they came
  from, the loop back into search, the ask-back that returns to `plan`, the budget that ends the
  loop whether or not the model is satisfied, and a validator that is plain code with three
  outcomes. Every claim in it was checked against the code, not against the diagram it replaces,
  and two claims the README and `docs/architecture.md` between them overstated are now stated as
  they are: the planner is **asked** for 2-4 English queries and degrades to the raw question when
  it returns no usable JSON twice, and `observe` does not establish that a quote is verbatim —
  `_valid_evidence` pins an item to its hit and drops the rest, and `validate` is the step that
  checks the words. Both corrections were carried into the two diagrams of `docs/architecture.md`,
  the prose summary under them and `docs/overview.md`, which said the same two things and would
  otherwise have contradicted the README. A line under the block says what the three colours mean
  — the front page was the only diagram in the repo colouring nodes without saying why — and blue
  is defined as **no answering-model call** rather than "deterministic code", because `act` is
  blue while the search embeds its query with the embedding model, which
  `EMBED_BACKEND=openrouter` sends off the machine. The block draws one path: the catalogue route
  and the deterministic gate behind the ask-back are in `docs/architecture.md`, which the line
  points at.
- **The step-by-step diagram in `docs/architecture.md` is written the way the ones that render
  are.** It rendered on GitHub with no colour coding and no legend at all. Its labels are now
  quoted and its classes attached inline with `:::` like the other diagrams in the tree, and the
  legend is a line of prose under the block instead of a `subgraph` wired with `~~~`, so the part
  that went missing no longer depends on a construction that can go missing. **The cause is not
  established:** mermaid 10.9.1 and 11.17.0 both render the old source with all three classes
  applied and the legend present, in dark theme and with html labels off, so this is a convergence
  on a form known to work rather than a diagnosed fix. Neither suspect construction was removed
  elsewhere: `docs/privacy-and-threat-model.md` still attaches its class with a trailing statement
  and the whole-system diagram above still wires its legend with `~~~`, so if either is what
  fails, those two fail the same way. One defect in the same diagram **is** diagnosed and fixed: a
  label read "hit ids sh", because GitHub un-escapes a mermaid block before the renderer sees it,
  so the escaped `s<step>h<n>` arrives as markup and the browser swallows both tags. It carries a
  real id now, `s2h4`. No escaped angle bracket is left in any mermaid block in the tree. Both
  edges into `synthesize`, re-quoted here, also gained the two stop reasons each was missing,
  against a paragraph that promises every edge is a branch the graph really takes (the lists are
  still not exhaustive — a repeated clarify request and an off-schema decision are among what is
  not on them): the question deadline and a timed-out `observe`/`reflect` call on the one out of
  `reflect`, and the planner's own timed-out call and the deadline (not only the step budget) on
  the one out of `plan`. A call that runs out of time became a stop reason of its own in 0.3.0,
  below.
- **The author credit links to a profile.** The README's "please credit Ievgen Borysenko" is the
  one line addressed to a reader who arrived from a link and liked what they found, and it pointed
  nowhere. NOTICE names him too, with the repository URL rather than a profile, and needs no
  equivalent line.

## 0.3.0 (2026-09-10)

A minor release, not a patch: the shipped default changed. A clone answers on a
local model through Ollama, with no account and nothing to pay, where it used to
need an OpenRouter key. The hosted path is unchanged and opt-in.

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
  mode writes it out as it stands. The dry run says so: its hosted plan read `would copy
  .env.example to .env unchanged` — the one line of the plan describing something the script does
  not do — and now reads `would write .env from .env.example with these values`, with every line
  either writer rewrites listed under it, `ORCHESTRATOR_MODEL` and the two `PRICE_*` included. A
  test pins the wording and the values. An invalid `LLM_BACKEND` still refuses to start rather than
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
  indistinguishable from a free local run. **No measured number was touched.** The reports behind
  the README's results table were produced on the hosted configuration, and that table,
  `docs/evaluation.md` and `docs/cost.md` now say so where they present them, together with the
  fact that the default configuration is local and free and is not what any of them measures. Not
  every report in `docs/eval-results/` is hosted — `2026-09-10-local-models.md` and
  `2026-09-10-first-question-local.md` are local runs — and the fingerprint carries the backend only
  from this release onward, so for the reports committed before it the backend is read from the
  provenance header (or from the `$0.0/M` rates on the cost line). `docs/evaluation.md` and
  `.env.example` say that instead of claiming every report is hosted.
- **The question deadline is per backend, like the per-call timeout — and a call that runs out of
  time ends the loop, not the run.** `QUESTION_DEADLINE_S` used to be one flat `300`, which no
  recommended path ever ran with: `.env.example` and `scripts/install-mac.sh` both write `1200`
  for the local mode, and a value in a copied `.env` wins over `config.py`, so the only
  configuration that got 300 s was the bare clone-and-ask path this release advertises as
  equivalent — where the quick start's own first question, measured from a clean clone in
  `docs/eval-results/2026-09-10-first-question-local.md`, takes 160.8 s of it, and where the per-call
  read timeout was capped at what was left of the 300 s rather than the 600 s `LLM_TIMEOUT_S`
  names. The default is now `1200` under `LLM_BACKEND=ollama` and `300` under `openrouter`, by the
  same rule and in the same line shape as `LLM_TIMEOUT_S`. Separately: a loop call (plan, observe,
  reflect) that hits its own timeout used to raise through the graph, and `run_question` has no
  `except`, so `ask-library --deadline 20 "..."` printed `Run failed: ... Request timed out.` and
  no answer at all — the opposite of what the deadline exists to produce. Such a timeout is now a
  stop reason of its own: the loop ends, the evidence already distilled stands, and `synthesize`,
  which the budget never caps, writes the answer from it. Only a timeout is caught; every other
  failure of a model call is raised exactly as before, and a `synthesize` that fails is unchanged.
- **The trade the default makes is stated where the choice is made, per kind of question.** The
  README and `docs/cost.md` said the local default costs nothing and did not say it is slower. Both
  now say it in one place, and each figure is computed from the rows of one kind of question rather
  than from a set mean that mixes six catalogue items with four research controls: a local
  `qwen2.5:14b` answers a catalogue question in 1-12 s and a research one in 61-217 s at $0, a
  hosted `claude-sonnet-4.6` in 1-2 s and 8-61 s for about $0.002 and $0.05, and `cost.md` names the
  run **and the rows** behind every figure. The first-question latency the quick start's reader
  actually meets is measured for the first time and committed as a report of its own,
  `docs/eval-results/2026-09-10-first-question-local.md`: 160.8 s cold and 62.7 s warm, from a clean
  clone at this branch's head over the demo index. `docs/add-your-own-books.md`'s "only asking
  questions costs money" is qualified with `LLM_BACKEND=openrouter` and its $0.03-0.04 aligned
  with `cost.md`'s $0.04-0.05 (the older figure was the `v0.1.0` measurement, and says so).
- **The "model not pulled" notice carries the same remedy as the unreachable-Ollama one.** An
  interrupted install used to get less help than a machine with no Ollama at all: the exact
  `ollama pull` and nothing else. It now says the download is several GB and has to finish, and
  names `bash scripts/install-mac.sh` as the one command that pulls what this configuration opens.
  No size in gigabytes per model: `ollama list` cannot be read for a model that is not there.
- **`MAX_OUTPUT_TOKENS` and the non-negative knobs read blanks like everything else.** They used
  `os.environ.get` where the rest of `config.py` uses `_env`, so a name left blank in a copied
  `.env` raised instead of meaning the default. Unreachable today — `.env.example` ships values —
  and now consistent.

## 0.2.1 (2026-09-10)

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
- **The grouped weekly lockfile update.** `langchain-openai` 1.5.1 -> 1.6.0, `lancedb` 0.37.1 ->
  0.38.0 and `python-dotenv` 1.2.2 -> 1.2.3, with `langchain-core` following from 1.5.5 to 1.6.2.
  Nothing else in the lock moves and no constraint in `pyproject.toml` changes; the suite passes on
  the new versions, and the parity tests that hold the installer's shell reader against
  `dotenv_values()` run against the python-dotenv the lockfile now resolves.
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
