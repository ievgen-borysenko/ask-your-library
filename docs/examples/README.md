# Example traces

Two end-to-end runs of the agent, kept verbatim from the recorded eval run so a reader can
see what the system actually does before installing anything. One is a clean success, the
other is an answer that every automated check in this repo passes and that still does not
answer the question - it is here on purpose.

| Trace | Golden item | What it shows |
|---|---|---|
| [h06-kobzar-naimechka.md](h06-kobzar-naimechka.md) | `h06-kobzar-mother-servant` (answer) | Vague human recollection -> one hybrid search -> the poem named and quoted verbatim, the rest carried by a book card, and an explicit note of what the window does not cover. |
| [c06-fogg-missing-day.md](c06-fogg-missing-day.md) | `c06-fogg-missing-day` (answer) | Honest incomplete: green checks, the answering passage never retrieved. Behaviour PASS, quote provenance 2/2, and the answer says the discovery moment is not in the evidence - because Chapter XXXVII never entered the window. |

## Where the traces come from

- Run: the agent eval of 2026-09-05 23:34 over the core golden set (`eval/golden/en-demo.yaml`,
  12 questions - the set as it stood at the tag; the reader removed h12 from it on 06.09, so the
  file now holds 11), code `88881ee`, model `anthropic/claude-sonnet-4.6`, bge-m3 index of
  165 card + 7,285 transcript chunks, strict hit-id mode. The full fingerprint and totals are
  committed in
  [`docs/eval-results/2026-09-05-v0.1.0-core.md`](../eval-results/2026-09-05-v0.1.0-core.md).
- The traces stay from the v0.1.0 run. On `v0.2.0-rc1` (07.09, reports in
  `docs/eval-results/2026-09-07-v0.2.0-rc1-*.md`) the two items read as follows: h06 answers after two
  searches with green provenance; c06 again never retrieves Chapter XXXVII, but this time it fills
  the gap from the book card's plot summary (the date line) without saying the discovery scene is
  missing, so the trace below, which says so, is the v0.1.0 shape of the same failure.
- Each trace is assembled from two harness outputs: the per-question scratchpad (the raw
  retrieval window the agent saw, one `<<<hit>>>` block per chunk) and the answers report
  (final answer plus the provenance verdict). Answers are reproduced unedited; retrieved chunks
  are cut to the part the annotation refers to and marked with `[...]`.
- The retrieval windows now show the `hit id` (`s1h1` ... `s1h8`) each chunk was given by `act`.
  In strict hit-id mode an evidence item must name the hit it was copied from, its book and
  section come from that hit record rather than from the model, and the provenance verdict reads
  "found verbatim in the passages they cite" - the cited hit, not the window as a whole.
- The harness does not persist the `observe` step's selected evidence (quote + `why`), so the
  traces show the window and the answer, not the intermediate JSON. `uv run ask-library` prints
  the step events live if you want to watch the loop.

## Caveats

- LLM output is not deterministic. Rerunning either question can produce a different query,
  window or answer - the h06 trace was rewritten against this run because it differs from the
  previous one, and c06 came out wrong in the 05.09 core run and incomplete in both tagged runs
  (see its own analysis section).
- These are two of the core questions of that run, picked by hand: the best-case and the most
  instructive failure. They are not a sample of typical quality; the eval summary is.
