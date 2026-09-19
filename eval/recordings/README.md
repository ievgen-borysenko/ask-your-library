# Plan recordings

What the planner was asked and what the model said back, one file per golden set
and model:

```
<golden-stem>.<golden-sha12>.<model>.jsonl
```

`eval/run_plan_eval.py` replays these through the real `plan()` node, so a change
to the planner's deterministic half — the mode, the catalogue request, the query
filter, the named-book resolution, the fallbacks, the routing — can be measured
without calling a model. Recording and replaying are documented under
["Plan-only replay" in `docs/evaluation.md`](../../docs/evaluation.md).

**This directory is committed**, unlike `eval/results/`, and that is the point.
A recording is the input a replayed number was produced from: without it in the
tree, "the planner's routing held on 41 of 42 items" is a number nobody else can
reproduce, and the run that produced it costs money. They are small — one line
per item and attempt, a few hundred kilobytes for the largest golden set — and
they carry no absolute path and no credential. Every payload and reply goes
through the same `redact_paths` the reports and sidecars use, then through a
generic absolute-path sweep (POSIX, Windows, UNC; URLs left alone), and anything
token-shaped refuses the line and refuses to finalise the file rather than being
masked into it. The gitleaks step in `.github/workflows/security.yml` is the
second net, over whatever actually gets committed.

Make one with a run you were going to make anyway:

```sh
uv run eval/run_agent_eval.py --record-plans --require-clean
```

A recording goes **stale** by design. Its header carries the golden file's
checksum and the checksum of `PLAN_RULES`, and `eval/run_plan_eval.py` refuses
to replay it when either has moved: different questions are different questions,
and a changed prompt means the recorded replies answer something nobody asks any
more. A prompt change therefore needs a **new recording**, which needs a paid
run. `uv run eval/run_plan_eval.py --check` answers that question on its own.

**Every recording in this directory is stale as of the scope gate (#70).** That
change added one optional field to `PLAN_RULES`, so its checksum moved from
`acd673f471d3` to `ab7b9ece3352` and `--check` now reports these six files as
measuring the old rules. They are kept, not deleted: they are still the exact
input the 16.09 replay numbers were produced from, and a replay of them still
measures what it always measured — `plan()`'s post-processing under the prompt
that was in the tree on 16.09. What they cannot do any more is say anything
about how a model reads the new rule; that needs a new recording from a new run.
The three `en-demo.*` recordings are stale on the golden side too since 2026-09-19:
c09 moved to `clarify_or_answer` (the owner's verdict), so `en-demo.yaml` went from
`edc151948a58` to `2c43defa8bc7`. They were not re-stamped, for the same reason.

A `*.jsonl.partial` beside a recording is a run that did not finish. The calls in
it were paid for all the same; rename it by hand if you want to keep them, after
reading what it holds.
