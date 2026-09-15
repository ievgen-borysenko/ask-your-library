# Agent eval — <when> — golden.yaml

run: code abc1234 | single run

## q01-moby (answer, 2 steps, 4s, $0.0100, 3 calls, 1000 in / 100 out tokens) — PASS: titles 1/1, facts 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which whale?

- reflect -> whale

Moby Dick aboard the Pequod

> quote provenance: 2/2 confirmed

## q02-drac (identify, 2 steps, 4s, $0.0100, 3 calls, 1000 in / 100 out tokens) — PASS: titles 1/1, stop: enough evidence

- [ ] manual correctness (facts match the golden notes?)

**Question:** Which castle?

- reflect -> whale

Moby Dick aboard the Pequod

> quote provenance: 2/2 confirmed

---
2 completed, 0 errors, 0 clarify interrupts; quotes verified 4/4 (confirmed / unattributed / broken = 4 / 0 / 0); evidence items 6
behavior PASS 2/2 (answer 1/1, identify 1/1); expected titles mentioned 2/2
expected facts found 1/1; answers carrying every expected fact 1/1 (substring presence, not correctness; not part of behaviour PASS)
cost $0.0200 total, $0.0100 mean per attempted question (6 LLM calls, 2000 in / 200 out tokens; configured rates $0.0/M in, $0.0/M out, cache reads not discounted)
manual correctness: not scored — tick the checkboxes above
