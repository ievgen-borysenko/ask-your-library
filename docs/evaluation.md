# Evaluation

The harnesses, the golden sets and the runs behind the results table; the README carries the
same table without this text around it.

Every run reported **on this page** was produced on the **hosted** configuration
(`LLM_BACKEND=openrouter`, `anthropic/claude-sonnet-4.6`), which is not the shipped default: the
default is local and free, a different answering model and therefore a different system, and no
number on this page describes it. [`eval-results/`](eval-results/) is not hosted-only, and the two
local reports there say so in their own provenance headers:
[`2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md), two `qwen2.5` sizes on
`LLM_BACKEND=ollama`, and
[`2026-09-10-first-question-local.md`](eval-results/2026-09-10-first-question-local.md), one local
CLI run. Neither feeds the table below. The rule that separates the two kinds at a glance is the
cost line: a hosted run carries the configured rates `$3.0/M in, $15.0/M out`, a local one `$0.0/M
in, $0.0/M out`. From this release the harness fingerprint also names the backend outright — `model
<name> via <backend>` — but every report committed before it prints `model <name>` alone, so for
those the backend is read from the report's provenance header, not from the fingerprint.

**`eval/run_retrieval_eval.py` - component baseline, no LLM calls.** Feeds the *raw* golden
question to the retriever and asks whether the resulting window (top-4 card chunks + top-4
transcript chunks, exactly what `search_both` gives the agent) contains the expected book(s).
Single-book questions score presence; multi-book questions score coverage and whether *all*
expected books are present. Per-corpus hit@k and MRR are diagnostics only. This measures the
retriever with the raw question; the agent rewrites the question into its own queries, so this is a
component baseline, not a bound on agent quality in either direction.

**`eval/run_agent_eval.py` - behavioural scoring of the full loop.** Every golden question runs
through the whole graph (clarify interrupts are auto-answered, so the run is non-interactive),
scored on: expected titles mentioned in the answer (accent-folded substring, not a citation
check), refusal questions answering with an explicit refusal (an evidence-free answer told from
model knowledge fails), `expected_behavior: clarify` questions actually triggering a clarify
interrupt, `expects_chapter_read` questions actually drilling into a chapter of an expected
book, and `catalog` questions on their structured result (the set of books the code listed must
equal the expected set of index keys, "Title — Author", so the right title under a wrong author
fails; the count must be the length of that list, the operation must be the one
the item names, and the catalogue as a whole must hold the `expected_total` the item was written
for, or a run of two or three items could certify a partial index; a research question answered
by the catalogue path fails, and so does a research control the planner did not route itself,
where a planner or catalogue fallback searched instead). Quote provenance totals come from
`validate`.

**Since 2026-09-16 the triple is a proof, not a measurement (#29).** The quote check runs at the
`observe` gate now, before the answer is written: a quote confirmed in the passage it cites is kept,
one found in another retrieved passage of the same step is re-pinned to that passage, one whose only
match is a book card is kept and pinned to the card, and one that is in no retrieved passage of its
step is dropped and never reaches `synthesize`. `validate` still runs last and still reports the
same four outcomes over the same text through the same function — so on a run made after this,
`confirmed == checked_book_text` and `broken == 0` **by construction**. A published triple of
`n / 0 / 0` therefore no longer says "the model quoted honestly n times"; it says "the gate held",
and what the model got wrong is in two counters beside it: `dropped_unverified` (quotes that never
became evidence) and `repinned` (quotes whose citation was corrected). Both are per question and in
totals, in the report line and the sidecar, and both clauses are written only where there was
something to say, so a run that spent neither writes the line the harness has always written.
The gate's own behavioural effect — whether a set answers as well with it as without — is **not
measured yet**: the paired baseline on three local models is being produced, the gate's run comes
after it, and the acceptance agreed in advance is 1.0 confirmed by construction, a published drop
rate, and behaviour at `--repeat` not below that baseline.

**A book card is not the book, and since 2026-09-16 the triple says so.** `validate` splits its
verdicts by the corpus the matching passage came from: `confirmed / unattributed / broken` are
now about the books' own text alone, and a quote whose only verbatim match is inside a book card —
a per-book summary written by one model call at ingest time — is counted apart as `card_only`,
reported in the report line ("N quotes matched only a book card, not the book text", written only
when there are any) and in the sidecar. The confirmed ratio's denominator is `checked_book_text`
(= `checked - card_only`), so a run answered half off cards reads "3/3 of the book text, plus 3
card matches" rather than "6/6 confirmed". **Every report under
[`eval-results/`](eval-results/) predates this split and counts card matches inside the triple**;
the numbers in those files are correct for what they measured and are not comparable, quote for
quote, with a run made after it. Nothing was re-run to change them, and the harness reads a
sidecar written before the split as a run with no card matches in it rather than as a run with
nothing traced.

Scoring is heuristic, no LLM judge -
**answer correctness is still a manual read**, which is why the harness writes every answer
into a report with a per-question correctness checkbox.

**`tests/ui` - the web UI's release walkthrough, in a browser (2026-09-15).** Not an eval: a test,
and the one that replaced a manual pass. `pytest tests/ui` starts a real `chainlit run ui.py
--headless` on a free loopback port and drives it with Playwright at two viewports (1280x800 and
390x844): first start and login, a research question with its live `plan` / `act` / `observe`
steps, the quote-provenance badge with its numbers, an evidence passage opened and readable, the
catalogue answer with its count, a reload that restores the conversation, and a clarify left
unanswered until it times out. The model, the two retrieval functions, the catalogue reader and
the preflight come from `tests/ui/scripted_backend.py`, so the run needs no Ollama, no key and no
index and answers the same way every time; everything else - the server, the compiled graph, the
clarify interrupt, the provenance check and every rendered line - is the shipped code. The browser
binary is not a Python package, so the directory skips itself (with the install command in the
reason) wherever it is missing; CI's `ui-smoke` job is where it runs, and uploads a screenshot of
any failing page. What it proves is that the path works and what the screen says, never that an
answer is good: the answers are written into the script.

**`expected_facts` and the `facts_ok` row (2026-09-15).** Every golden item whose answer has
content carries one to four short, checkable strings - a name, a number, a place, one fact per
string - derived from that item's own `notes` and, where the notes were vague, from the book card
in `corpus/cards/`. The harness reports `facts_found/facts_expected` on the question's report line
and `facts_ok` when every one of them occurs in the answer text: folded and whitespace-normalised
substring presence, no stemming, no synonyms, no edit distance, so a red row means exactly "this
string is not in the answer". Both counts are summed in the totals block **of a `--repeat 1`
run** - a repeated run reports them per attempt instead, as a range (see the sidecar section
below) - and
`eval/summarize_report.py` carries them into the committed summary together with every behaviour
PASS whose answer is missing a fact. It is a **fourth deterministic row, not a fourth term in the
behaviour verdict** (ADR-010: rows that cannot be confused, no composite score). Ten of the 42
items carry no facts, score 0/0 and are counted in neither half of the totals: the five refusals,
which have nothing to narrate; the three clarify items whose two candidate books would each demand
a different answer (c09, q06, h22); k09, which is scored on routing alone and whose answer cannot
be exhaustive; and k04, whose answer is a negative ("War and Peace is not in this library"), which
substring presence cannot check. A fact may also not be a string its own question already contains
- an answer restates its question, so such a fact would score green without measuring anything.
The shape of a golden item is a contract in the harness itself (`ALLOWED_KEYS` per item type,
`REQUIRED_KEYS`, `FIELD_CHECKS` in `eval/run_agent_eval.py`), and the harness checks **every item
of whatever file `GOLDEN_PATH` names** against it when it loads it - before the graph is built and
before the first billed call, reporting every problem in the file at once. It has to be there and
not only in a test: `score()` reads items with `.get()`, so a misspelled `expected_fact:` would
disable this row for that item and the run would end with a green 0/0 that measured nothing, and
`expected_behaviour` would score a clarify item as an ordinary one. Required on every item:
`id`, `question`, `type`, `expected_books`, `expected_facts` (a refusal carries `[]` explicitly),
plus `expected_total` on a catalogue item. `tests/test_golden_schema.py` runs that same check over
the three files in the repository and adds what only holds across a set - ids unique across the
files, no question asked twice, no fact its own question already contains; the facts scoring
itself is pinned by `tests/test_agent_eval_facts.py`, over every branch of `score()`.

**A JSON sidecar per run, and `--repeat N` (2026-09-15).** Every run now writes two files side by
side: the Markdown report a reader reads (`eval/results/answers-<ts>.md`, unchanged) and
`answers-<ts>.json`, the same run as data. The sidecar carries the fingerprint as *fields* rather
than as one line - the code stamp and whether it was a verified clean commit, the golden file's
repo-relative path (never an absolute one: this file is meant to be committed beside a published
number, and a home directory names the reader, not the measurement) and checksum, the manifest and
TOC checksums, the backend, the model, the index stamps, every knob
that changes an answer (hit budgets, step and streak limits, clarify candidates, the question
deadline, strict hit ids, the configured prices), the repeat count and the wall-clock start and
end - and then, per question, its group and *every attempt* exactly as the harness produced it:
the full answer, the provenance triple, steps, chapters read, clarify state, stop reason, planner
and catalogue fallbacks, cost, calls, tokens, seconds, and the `score()` dict computed from that
attempt. The line in the report and the fields in the sidecar are rendered from the same dict, so
they cannot say different things about one run. Written with `ensure_ascii=False` and indent 2 in
a fixed key order, so two runs diff line by line; `--no-json` turns it off.
**The sidecar's shape does not change with N**, so a consumer written against one run reads a
repeated one, and nothing in it is summed across attempts: `totals.per_attempt.<aggregate>` is
`{values: [one per attempt], min, median, max}` (at `--repeat 1` a list of one),
`totals.expected_per_attempt` holds the denominators read off the golden items themselves
(`items`, `titles`, `facts`, `facts_items`, `drill_items`, `groups`) rather than counted up from
the results, `per_group.<type>` is `{of, behavior_ok_per_attempt: [...]}`, and the only summed
figures live under `totals.spent_total` - money, calls and tokens, each spent once. Denominators
come from the golden file for a reason: counted from the results, an item that errored drops out
of the row it belongs to, and an item that errored on every attempt takes its whole row with it.
The same rule governs the per-question `spread` block: which rows exist (`facts_ok`,
`drilldown_ok`) follows the golden item, so an item that never completed reports 0 of N instead of
disappearing. Error text is stored with any path under the home directory or the repository root
replaced by `~` or `<repo>`, in the report as well as here: a `FileNotFoundError` names a file,
and under a home directory that name is the reader's login.
`--repeat N` runs each golden item N times (default 1). Scoring stays per attempt - the scorer
never sees more than one run - and the aggregation is reported beside it: each boolean row
(`behavior_ok`, `facts_ok`, drill-down) as **how many attempts of N passed**, never as an average
of true and false, and cost, seconds, tokens and calls as **min / median / max**. At N > 1 the
totals block is rewritten rather than extended, because **not one figure in it may be a sum across
attempts**: two items run three times have six passes, and "behavior PASS 5/6" describes a
six-question set nobody ran. Every line there is per attempt -
`behavior PASS <min>–<max>/<items> over N attempts (mean ... per attempt)` and one such line per
aggregate, with the per-group ranges beside the headline - and the single figure that *is* summed,
the money the run actually spent, says so in words. `--min-pass` becomes a floor on the *weakest*
attempt rather than on the average. At
`--repeat 1` the Markdown report is byte for byte what the harness has always written, pinned by a
test that compares the *whole* report against one rendered by the pre-sidecar harness (`a6c4ccd`)
from the same fake results and committed as a fixture: every artifact under
[`eval-results/`](eval-results/) and `eval/summarize_report.py` read the same format they always
did. (At N > 1
`summarize_report.py` lists a failing id once per failing attempt; it reads the Markdown only, and
teaching it to read the sidecar is a separate change.)

**The harness runs the shipped runner, and the report carries seconds per node (2026-09-16).**
`run_one` no longer drives the graph itself: it calls `runner.run_question` — the same entry point
the CLI and the web UI call — with an event collector and its own `--clarify-pick` reply policy as
the clarify callback, and reads the run off the `RunResult` the runner returns. The per-question
usage reset, the stream loop, the clarify interrupt and the scratchpad
(`eval/results/scratch-<id>.md`, one per attempt under `--repeat`) belong to the runner now, so what
is measured here is what a reader runs, not a second implementation of it (ADR-009, amended). Two
things follow in the record. A question that fails is still accounted for: the runner reports the
failure on the result and emits its metrics anyway, so the calls a dead question made are in the
ERROR row's "spent before the error" as they always claimed to be. And every attempt carries
`by_role_seconds`, printed under the steps log as `- seconds by role: plan 1.2, observe 8.5` and
stored in the sidecar. A role is a node that calls the model — `plan`, `observe`, `reflect`,
`synthesize` — and the figure is the wall clock of those calls only, retries and a call that timed
out included: `act` issues no model call and appears nowhere in it, and neither does the model
residency a first local question pays before any call (see ADR-009 and `docs/backlog.md`). It is the number a local latency budget needs: hosted, a question is priced in
dollars and the cost line says so; locally it costs $0, and seconds are the only currency there is.
A run that spent no model call writes no such line, which is why the byte-compat fixture above is
unchanged by this.

Three golden sets, reported separately. **Core** (`eval/golden/en-demo.yaml`, 11 questions, the
default `GOLDEN_PATH`): eight questions on books the golden author has read and a two-book
comparison of two of them (Ivanhoe and Don Quixote), all nine reader-verified; h06, one of the two
questions the example traces are built on, verified against the source text by an AI session only;
and one genuinely ambiguous identify (Crusoe or Gulliver), proposed and awaiting the reader's
verdict on the item itself. Each item's notes state its level. The file held twelve questions when
the v0.1.0 column was measured; the reader removed h12 on 06.09, and the v0.2.0-rc1 column is the
eleven-question set (see the note under the table).
**Extended**
(`eval/golden/en-demo-extended.yaml`, 21 questions) is the former v3 draft with near-duplicates
removed; its notes were checked against the source text by an AI session only, so its numbers are
exploratory.
**Catalogue** (`eval/golden/en-demo-catalog.yaml`, 10 questions): six questions about what the
library holds (count, the full list, a title that is there, one that is not, an author, the count
in Ukrainian), scored on the structured result against the manifest's book keys and its size;
three content questions
that look like listings as negative controls (one scored on routing alone); and one hybrid item
that pins the named-book retrieval filter. Measured on `50b9347` (09.09, single run, the branch's
final commit with the scoring on keys and `expected_total`; the earlier 10/10 run of the same day
on `b0d1321` scored titles only and has a different golden checksum, so it is not the same
measurement): 10/10; the six catalogue items with 0 search steps and one model call each; the three
controls through the research loop (1, 2 and 3 steps); the hybrid item with retrieval limited to
Dracula; 22/22 quotes confirmed on the four research items; $0.17 for the set, of which the six
catalogue items cost $0.014 together (`eval-results/2026-09-09-catalogue-set.md`).
Re-measured on `466fc82` (10.09, this repository's `main` at the merge of `#18`, same golden checksum and the same
04.09 index): 10/10 again with the same routing question by question, 21/21 quotes confirmed on the
four research items — one evidence item fewer on the London question — and $0.1762 for the set, of
which the six catalogue items again cost $0.0136
([`eval-results/2026-09-10-catalogue-set.md`](eval-results/2026-09-10-catalogue-set.md)).

Every number on this page was measured **once**, and a single sample of a system whose output
varies is not a number with a spread: on any of these rows a difference of one or two questions
between two runs is not a measured effect, which is why the ablation table below says so in its own
limits and why the reports state the count of runs in their fingerprints. From this release that is
a choice rather than a missing capability - `uv run eval/run_agent_eval.py --repeat 5` reports
every row as "how many attempts of 5 passed" with min / median / max cost and seconds, and the
fingerprint of such a run reads `5 attempts per item` instead of `single run`, so the two kinds
cannot be confused. No repeated run has been made yet: nothing below has been re-measured, and the
numbers in the tables are what they always were.

Two measured trees, both single runs, clean tree (`--require-clean`), strict hit-id mode, the same
bge-m3 index: **v0.1.0**, 2026-09-05 on code `88881ee` (the last code commit before tag `v0.1.0`;
the tag's commit adds documentation only), with a 1,200-character observe window, summarised in
`eval-results/2026-09-05-v0.1.0-*.md`; and **v0.2.0-rc1**, 2026-09-07 on tag `v0.2.0-rc1`
(`33dba3f`), with the 2,500-character window (ADR-012) and the coverage gate (ADR-013) together
plus everything in the 0.2.0-rc1 changelog. The rc1 reports
`eval-results/2026-09-07-v0.2.0-rc1-{core,extended,retrieval-canary}.md` are the harness
output verbatim under a provenance header (the two targeted second-candidate runs are appendices of
the core and extended reports); every agent row carries its stop reason and would say so if the
planner had fallen back or the deadline had cut the search (neither happened on either set). The
window and the gate were introduced and measured one at a time during development (the CHANGELOG
records those steps); the two columns below are the first measurement of both on one run: +39% per
core question and +57% per extended question against v0.1.0 (from the committed totals, $0.5364/11
against $0.4215/12 and $0.9008/21 against $0.5722/21).

A third run of the core set, 2026-09-09 on `50b9347` (the catalogue branch's final commit, this
repository), checks that the catalogue path (ADR-016) left the research loop's numbers where they
were: 11/11 behaviour, 48 / 0 / 0 quotes confirmed / unattributed / broken, $0.0519 mean per
question against $0.0488 on rc1 (73 model calls against 70). What changed is the path, not the
verdicts: the three questions that name one book (c04, c05, c06) now run with retrieval limited to
that book by the catalogue resolver, and the refusal question's answer carries the note that the
named book is not in the catalogue. Single run, not reader-graded; the report is
`eval-results/2026-09-09-catalogue-branch-core.md`. The table below keeps the two tagged
baselines.

A local-backend run of both sets, 2026-09-10 on `qwen2.5:7b` and `qwen2.5:14b` with a `qwen3.6`
probe, records what the loop does with no hosted key present — `$0.0000` on every run, nothing left
the machine; not reader-graded, and only the research subset was re-measured after the last prompt
change, which the report's own coverage caveat states:
[`eval-results/2026-09-10-local-models.md`](eval-results/2026-09-10-local-models.md).

## Plan-only replay

**`eval/run_plan_eval.py` - the planner's decisions, re-measured for nothing (2026-09-15).**
`plan()` is one model call followed by a hundred lines of deterministic post-processing: the
validated mode, the parsed catalogue operation, the mixed-intent gate, the query filter, the
named-book resolution against the catalogue, the planner and catalogue fallbacks, and then the
routing decision `route_after_plan` makes from what came out. Until now the only way to reach that
code with a real planner reply was a full paid run of a golden set, so a one-line change to the
query filter cost the same as a release measurement and was therefore usually not measured at all.
It does not have to be: the model's share of the decision is a string, and a string can be kept.

**Recording.** `uv run eval/run_agent_eval.py --record-plans` writes every `role="plan"`
request/response pair of the run it was going to make anyway into
`eval/recordings/<golden-stem>.<golden-sha12>.<model>.jsonl` - one JSON line per golden id and
`--repeat` attempt (and a second line when `ask_json` had to retry a malformed reply, because a
replay that dropped the bad first one would replay a retry that never happened). Each line holds
the exact user payload, the raw reply text, the hash of the system prompt, the model, the backend
and every knob of the call, the clock, and what that one call cost in money and tokens. It costs
nothing extra: the calls are made either way. The mechanism is a passive observer
(`llm.JSON_CALL_OBSERVER`) that `ask_json` notifies and that cannot change what a call returns -
its own failure is logged and swallowed, because losing a recording is cheap and losing a paid run
is not. `nodes.py` is untouched by any of it, as it is by the replay (`llm.ask_json` and
`nodes.list_books` are rebound by name, the seam `eval/run_ablation.py` already uses).
A call that never came back is recorded too, with an empty reply and its exception's name: without
that line a timed-out planner would be indistinguishable from an item nobody ran. What a line says
it spent is the **planner's own** tokens - `llm_invoke` accounts per node role, and a difference of
the whole-run counters would charge a plan call with whatever `observe` and `reflect` spent between
it and the previous one - and the cost is computed from those tokens at the configured rates
*unrounded*, because a planner call is often under $0.0001 and the report's four decimals would
write a run's worth of them down as free.

The file is written as `.jsonl.partial` and renamed on a clean close, so a file at the final name
is a run that finished and a crashed run still leaves everything it paid for - and a recording
whose own writing failed is **not** finalised either: the recorder latches the first write error,
refuses the rename, keeps the `.partial`, and the run's report tail carries the reason and its exit
code turns non-zero. (The observer itself still swallows its exceptions, because the paid run must
go on; what it must not do is leave a short file wearing the name of a complete one.) Two guards
stand between a run and that file. It **refuses to replace an existing recording** unless
`--overwrite`: that file is the artefact of a run somebody paid for, and the refusal happens before
the graph is built and before the first call rather than after the money is spent. And a run of
*selected ids* records only those ids, so it writes `...<model>.subset-<k>of<n>.jsonl` with
`subset: true` in its header instead of overwriting the complete recording with three items under a
name that still claims the whole set; the replay harness reports such a recording as a subset in
its own report and sidecar.
`eval/recordings/` is **committed** - unlike `eval/results/` - because a recording is the *input* a
replayed number came from, and a number whose input is not in the tree is not reproducible by
anyone who did not pay for the run. Being committed is also why two rules guard what may enter it.
Every payload and reply passes through the main harness's `redact_paths` (the repository becomes
`<repo>`, this machine's home becomes `~`) **and then through a generic absolute-path sweep** -
any POSIX path of two or more segments, any Windows drive path, any UNC share - each replaced by
`<path>`, with URLs left intact, because `redact_paths` only knows this machine's two prefixes and
a payload can carry an external volume, a system file, another account's home or a colleague's
drive. And anything **token-shaped fails the recording closed**: a provider key, an
`Authorization` header, a JWT, a Slack, GitHub, Google or AWS credential, an `api_key = ...`
assignment, a private-key header, or the literal value of any `*_KEY`/`*_TOKEN`/`*_SECRET` set in
the environment of the run. Such a line is **not written at all** and the recording is **not given
its final name**; the error says which line and what tripped it. It is deliberately not
masked-and-written: a masked line still means a credential passed through, and a file that looks
clean is one nobody goes back to check. The gitleaks step in `.github/workflows/security.yml` is
the second net, over whatever is actually committed.

**Replaying.** `uv run eval/run_plan_eval.py` loads a golden set and a recording, and for every
item calls the **real** `plan()` node with `llm.ask_json` replaced by a replayer that returns the
recorded reply - re-parsed by `llm.json_object`, the very function that parsed it live, so a reply
that was malformed twice raises the same error here and the node degrades to its fallback exactly
as it did on the paid run, and a call that timed out raises the same `CallTimeout` so the node
takes its timeout branch and not its fallback branch - they are different states of the node and a
report must not confuse them. Then the real `route_after_plan` over the state it produced. No model is
called, `$0.0000` is spent, and the report's first line says so. Names are resolved against the
index when there is one; without a readable index the harness falls back to `corpus/manifest.yaml`,
read as the catalogue a fully built demo index would hold, and **says which of the two answered**
in the report - they are not the same thing, because a half-built index holds fewer books than its
manifest and a replay against the manifest would not notice.

**Only the FIRST planner call of an item is replayed**, and the report says so in its header. A
second `plan()` of the same question happens only after a clarify, and what it receives is a
function of the graph state at that moment - the evidence collected, the candidates offered, the
reader's reply - which the observer never saw and the recording therefore does not hold. Replaying
it would mean inventing that state. So it is *accounted for* instead: every item reports
`calls_recorded` / `calls_replayed`, an unreplayed call is named in the report, the totals and the
sidecar, and it exits 1 unless `--allow-unreplayed`. Recording that state from the runner, so the
re-plan after a clarify can be replayed too, is a follow-up in [`backlog.md`](backlog.md).

Scored per item and per recorded attempt, with the mapping from a golden item to what the planner
owes it written out in the harness rather than inferred: `mode_ok` is the **route** the golden set
actually pins - the catalogue path for a `catalog` item, the research loop for every other type,
which is exactly where `score()` in the main harness already fails a run (`catalog_misroute`) -
plus, for an `expected_behavior: research` control, that the planner routed it there itself rather
than being rescued by a `catalog_fallback`. A `plan_fallback` fails this row too, whatever route
the state ended on: the planner produced nothing usable and code searched the raw question, so
"not the catalogue path" is true of it only because there was no path to take, and a green
`mode_ok` on it would mark every failed planner correct on the row a reader looks at first. Then
`op_ok` (the catalogue operation is the item's
`expected_op`), `book_filter_ok` (the named book resolved to the item's `expected_book_filter`),
`fallback_ok` (no `plan_fallback`), `queries_ok` (a non-blank query survived the filter) and
`queries_range` (as many queries as `PLAN_RULES` asks for, 2-4). Whether the planner said
`identify` or `answer` is reported as `mode_exact` **beside the verdict and never inside it**: the
golden `type` labels the question, not the planner's reading of it, and an `identify` question
whose book is obvious is legitimately answered. A Markdown report and a JSON sidecar are written
side by side in the shape family of the main harness (`eval/results/plan-replay-<ts>.{md,json}`),
with the run fingerprint as fields and the recording's identity beside it.

**The request is checked, not only the reply.** A recorded reply is replayed whatever question it
answered, so a change to how `plan()` *assembles* its payload - a new data block, a different
history window, a reworded clarification note - would be graded against a reply to a payload this
tree no longer sends, and the run would look clean. **Every attempt** of every replayed call
therefore compares the payload the node builds now with the recorded one (sanitised the way it was
written), the system prompt by its hash, and the order the attempts were recorded in. The retry's
payload is the first plus the retry wording, so it is rebuilt by `llm.retry_payload` - the one
function that writes those words, here and in `ask_json` - rather than by a copy of them, and the
recording's header carries a checksum of that wording next to the prompt's, so a reworded retry is
a stale recording and not a silent difference. A mismatch is reported per item as `payload_drift`,
in the report line, the totals and the sidecar, and exits 1 unless `--allow-drift`. It is deliberately **not** part of
the per-item verdict: drift says the *replay* is questionable, not that the planner decided wrongly.

**What it cannot measure: a change to `PLAN_RULES`.** The recorded reply answers the prompt that
was in the tree when it was recorded; replaying it under a new prompt measures the post-processing
of an answer to a question nobody asked. So the recording's header carries the checksum of the
golden file **and** of `PLAN_RULES` (and of the retry wording, which is the second half of what a
retried call was asked), and the harness **refuses to run** when any of them has moved (exit 2). `--check` answers that question on its own and replays nothing; `--allow-stale` replays
anyway and stamps the report and the sidecar with a block saying that nothing in them measures this
tree - there is no quiet way to do it. **A prompt change needs a new recording, and a new recording
needs a paid run.** Nor does this harness see anything downstream of `plan`: retrieval, the answer,
quote provenance and cost are the full harness's business, and the replay report's tail says so.
An item the recording does not hold exits 1 unless `--allow-missing`, and "missing" means what it
says. A planner call that ran out of time is **recorded** - an empty reply and its exception's
name - and **replayed as a timeout**, on the first attempt and on the retry alike, so `plan()`
takes the call-timeout branch it took on the paid run rather than the fallback branch. The two are
different states of the node (the timeout branch runs no query at all and routes straight to
synthesize; the fallback searches the raw question), and neither is ever mistaken for an item
nobody ran.

The mechanism is proved on fixture recordings (`tests/test_plan_recording.py`,
`tests/test_plan_replay.py`, with the synthetic pair under `tests/fixtures/`), including that a
replay makes **no network attempt at all** under the process-level egress guard.
**No recording of a real golden set has been made yet**, so nothing on this page was produced this
way; the first one will be made by the next paid run of the core set with `--record-plans`.

## Where the measured code lives

The measurements through `v0.2.0-rc1` (2026-09-07) were made in the private development
repository, which was this project's source of truth until the 2026-09-08 export, and the reports
for those runs name that repository's commits (`33dba3f`, `88881ee`, `1222b09`, ...): those
identify the measured trees in that history, they are not commits you can check out here, and
they are kept as recorded because rewriting them would suggest that a different code was
measured. What you can check instead: the first commit of this repository carries the eval
harness (`eval/*.py`) and `scripts/ingest_demo_corpus.py` byte-identical to the measured
`33dba3f`, `src/` and `ui.py` identical up to one comment line each (a review credit removed; the
launch command in the `ui.py` docstring completed with `--host 127.0.0.1`), and
`eval/golden/en-demo.yaml` identical except for one editorial note on c09 (a review credit removed
after the run; the questions are unchanged, and the core report's header records the resulting
checksum change); the other differences are documentation, the eval reports themselves and the
version string. Reports of intermediate development runs are not exported; the ones here are the
tagged baselines the text refers to. That one export — a private allowlist tool (a deny-by-default
file list, a private-marker grep and a gitleaks scan) that is not part of this repository —
produced this repository and has not run again. Every measured run from that export on was made
directly in this tree, on a commit this repository holds, the 2026-09-09 catalogue run on
`50b9347` above included — a day before the `v0.2.0` tag, but already in this tree; ADR-011 in
[`adr/README.md`](adr/README.md) has the fuller account of the switch.

| Measurement | Core v0.1.0 (12 questions, window 1,200) | Core v0.2.0-rc1 (11 questions, 2,500 + gate) | Extended v0.1.0 | Extended v0.2.0-rc1 |
|---|---|---|---|---|
| Retriever window, single-book presence | 9/9 | 8/8 | 12/12 | 12/12 |
| Retriever window, multi-book full coverage | 2/2 | 2/2 | 3/5 | 3/5 |
| Agent eval, questions completed | 12/12 | 11/11 | 21/21 | 21/21 |
| Behavioural compliance (heuristic scorer: titles, refusal, clarify, drill-down) | 12/12 | 11/11 | 17/21 | 18/21 |
| Answer quality, correct / incorrect / incomplete (AI pre-check of that run; the reader's own verdicts on the v0.2.0-rc1 run are in `eval-results/2026-09-07-v0.2.0-rc1-core.md` and confirm the pre-check: 10 correct, c06 incomplete; the v0.1.0 run was not graded by the reader) | 9 / 1 / 2 | 10 / 0 / 1 | not scored | not scored |
| Quote provenance, validator v0.1: confirmed / unattributed / broken | 46 / 0 / 0 | 47 / 0 / 0 | 53 / 0 / 0 | 73 / 0 / 0 |
| Clarify where the golden requires it | 1/1 | 1/1 | 0/2 | 1/2 |
| Chapter drill-down where expected | not in set | not in set | 0/1 | 0/1 |
| Cost per question, mean (Sonnet 4.6 via OpenRouter, configured rates) | $0.035 | $0.049 | $0.027 | $0.043 |

h12 was removed from the core set by the reader on 06.09 (never reader-verified; a character's lie
taken as fact was its failure); the v0.1.0 column is the 12-question run, the v0.2.0-rc1 column the
11-question core, which is also why the retriever row reads 8/8 there (h12's row is gone, nothing
else changed in retrieval: the index is the same).

On v0.1.0, behavioural compliance and provenance are green on all twelve core answers; a read of the
same answers against the golden notes finds one wrong (h12, then still in the set: a character's false
accusation reported as fact) and two incomplete: c03 names Madame Coquenard but not
Madame de Chevreuse, c06 never reaches Passepartout's
"to-day is Saturday" and says so (the committed trace). On v0.2.0-rc1 the AI pre-check of the eleven
answers finds ten correct and one incomplete, and the reader's read of 07.09 agrees row by row: c06 again, in a different shape: it reads Chapter
XXXIV, quotes Fix's apology from it, and supplies the date-line explanation from the book card's
plot summary instead of the discovery scene (Chapter XXXVII was not retrieved), without saying that
the scene itself is missing; Passepartout's "to-day is Saturday" and the Reform Club dash are
absent; c03 names both women this time and hedges Madame de Chevreuse as not
clearly established by the passages; c09, reworded on 05.09 to name both readings of the question,
offers Crusoe and Gulliver as candidates, answers Crusoe
with the harness's "not sure" reply and, with the second candidate chosen (`--clarify-pick second`,
committed as a one-question run), applies the choice and answers from Gulliver's Travels. The
extended failures are the known agent gaps under [Known limits](known-limits.md): on v0.1.0 four (q06 and h22 no
clarify, h17 Doyle side never retrieved, h13 no drill-down), on v0.2.0-rc1 three (h22 now clarifies
and offers Frankenstein and Dracula; q06, h17 and h13 unchanged).

Private cross-lingual library (Ukrainian questions over an English corpus, 10 questions, not in
this repo): single-book presence 6/7, multi-book coverage 1/3. The honest hard case - a
multilingual embedder handles single-target questions across languages, cross-lingual
aggregation does not hold up.

## Where the quality comes from

**`eval/run_ablation.py` - the same twelve core questions under five conditions** (ADR-014; the
architecture decision records are in [`adr/README.md`](adr/README.md)), one run
each on 2026-09-05, code `ab4e458` (`88881ee` plus the ablation harness - `eval/run_ablation.py`,
`tests/test_ablation.py` and their two entries in the private export allowlist - which
changes nothing the agent runs), clean tree, same index and same model as the table above. It
answers "how much of this is the agent loop and how much is the model, the corpus or plain
retrieval?". `no-context` is the orchestrator model with the question and nothing else;
`retrieve-answer` is one `search_both` call feeding one synthesize prompt, no loop; `cards-only`
and `transcripts-only` are the full loop with retrieval restricted to one corpus (a window of 4
hits per step instead of 8); `agent` is the shipped loop.

| condition | behaviour PASS | expected titles | provenance conf/unatt/broken | AI pre-check corr/incorr/incompl | mean cost/question |
|---|---|---|---|---|---|
| `no-context` (no library at all) | 6/12 | 9/13 | n/a | 9 / 1 / 2 | $0.0048 |
| `retrieve-answer` (retrieve once, answer once) | 9/12 | 12/13 | n/a | 7 / 2 / 3 | $0.0122 |
| `cards-only` (loop, cards corpus) | 12/12 | 13/13 | 29 / 0 / 0 of 29 | 8 / 0 / 4 | $0.0240 |
| `transcripts-only` (loop, transcripts corpus) | 11/12 | 12/13 | 33 / 0 / 1 of 34 | 9 / 1 / 2 | $0.0335 |
| `agent` (the shipped loop) | 12/12 | 13/13 | 40 / 0 / 0 of 40 | 9 / 1 / 2 | $0.0328 |

**On this run the full loop is not better than the loop-free conditions on answer content**: it
reads 9 correct / 1 incorrect / 2 incomplete, and so does the model with no library at all. Nine of
the twelve questions are about world-famous classics the model already knows, so on this corpus the
ablation cannot separate the loop from model memory on correctness. What the loop demonstrably buys
is in the other columns - behaviour PASS 6/12 to 12/12, quote provenance, and the clarify interrupt
- at 6.8x the cost of answering from memory. Provenance comes from the evidence-and-validation
contract, which this ablation did not separate from the loop: a single retrieval followed by the same
extraction and check would carry it too; the loop's own contribution is the extra steps and the clarify. Two results
cut the other way: the single-corpus `transcripts-only` condition beats the full agent on c03 (the
mechanism is not established by this run: each corpus keeps its own four hits, so cards do not
displace chapter text in retrieval; the difference is in what `observe` selected from eight hits
instead of four, or plain model variance), and on h12 - a former core item, removed by the reader
on 06.09, whose rows this artifact keeps as the record of the run - the three conditions whose
window carried a character's lie verbatim all repeated it as fact with clean provenance, while the
two that never saw it answered correctly. The `agent` condition reproduces the `v0.1.0` core run's
pre-check exactly - 9 / 1 / 2, the same three questions - which is a consistency check across two
independent runs, not a second measurement. Full table, per-question pre-check and limits:
[`eval-results/2026-09-05-ablation-core.md`](eval-results/2026-09-05-ablation-core.md).
The pre-check column is an AI reading of every answer against the golden notes by the session that
ran the ablation, not a human verdict.

## What the green numbers do NOT prove

- **Not correctness.** A 100% confirmed quote-provenance score means every quote really came
  from a hit of the book it is attributed to. If a character makes a false claim and the agent
  quotes it verbatim from the right chapter, provenance passes and the answer is still wrong; and
  a question whose answering passage was never retrieved scores the same green as one that was.
  Only a correctness read of the report catches either (the AI pre-check did, and on 07.09 the
  reader graded the eleven v0.2.0-rc1 answers in their report: ten correct, c06 incomplete).
- **Not that the answer's own quotation marks are checked.** Since 2026-09-16 every piece of
  evidence the answer is written from has passed the quote check before `synthesize` saw it (#29),
  which is a real narrowing of what can go wrong — and it stops exactly there. The sentences the
  model writes around that evidence, including anything it puts in quotation marks of its own, are
  model output and nothing verifies them. Citing by evidence id and checking those citations against
  the answer's sentences is the other half of #29 and is not built.
- **Not that a confirmed quote is a quote from a book.** It was until 2026-09-16: a quote found
  verbatim inside a book card counted as confirmed, and the card is a model's summary of the book,
  not the book. `validate` now counts those apart (`card_only`, never in the confirmed ratio) and
  every interface labels the passage it opens "book text" or "book card". The reports already
  published counted them in the triple — which is why "quote provenance 73 / 0 / 0" in the table
  below is a claim about retrieval provenance and not about the author's words.
- **Not answer quality.** Behavioural PASS means the expected titles were mentioned, a refusal
  refused, a clarify clarified. It does not grade reasoning or prose. c06 (Fogg's missing day)
  is PASS with provenance 2/2 and does not answer the second half of its question: the scene that
  answers it, Passepartout's "to-day is Saturday" in Chapter XXXVII, never entered the retrieval
  window, so the answer states honestly that the discovery moment is not in the evidence. That
  failure and a clean success are committed as full traces in
  [`examples/`](examples/README.md).
- **Not that the model read what it cites.** c06 in the 05.09 core run cited
  a Chapter XXXVII passage whose 1,200-character window ended one line before Passepartout's
  "to-day is Saturday" and inverted the day of the week; on the v0.1.0 run that chapter is not in
  the window at all and the answer stops short and says the discovery moment is not in the
  evidence; on the v0.2.0-rc1 run it is not in the window either and the answer fills the gap from
  the book card's plot summary without saying so. PASS and green provenance every time. Widening the observe window (measured during
  development, ADR-012) does not fix c06, because the passage is not in the window to widen. c05 (the windmills) once read an empty chapter because `reflect` passed the
  bare title while the index keys rows as "Title — Author"; fixed, and the tagged run quotes the Friston passage.
- **Not that the expected facts are used correctly.** `facts_ok` asks whether each expected string
  occurs in the answer and nothing else. "Saturday" is equally present in "Passepartout burst in:
  to-day is Saturday" and in "he was told it was Saturday, so he had lost the wager" - a fact can
  sit inside a negation, a wrong sentence, or a restatement of the question. It is blind the other
  way too: an answer that is right in other words ("executed" where the golden says "beheaded")
  scores red. The row narrows where a reader should look first; it does not do the reading, which
  is why it stays out of the behaviour verdict and the correctness checkbox stays in the report.
- **Not generalization.** The demo corpus is 33 classics with a golden set written against them.
  Numbers on your own library will differ.
