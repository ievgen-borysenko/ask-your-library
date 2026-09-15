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
they carry no absolute path and no credential: every payload and reply goes
through the same `redact_paths` the reports and sidecars use.

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

A `*.jsonl.partial` beside a recording is a run that did not finish. The calls in
it were paid for all the same; rename it by hand if you want to keep them, after
reading what it holds.
