# Diagram sources

The two `.excalidraw` files here are the author's course-demo originals from September 2026, kept
as the editable sources; the Mermaid diagrams in this repository — the flow in plain terms on the
[README](../../README.md) front page, the whole system and the loop's control flow in
[`architecture.md`](../architecture.md) — are the current ones and are the drawings to trust.

| File | What it drew |
|---|---|
| `ask-library-flow-simple_en.excalidraw` | The flow in plain terms: ask in your own words, the agent asks back if unclear, searches, answers with citations or says the books do not cover it. |
| `ask-library_en_v5.excalidraw` | The architecture: the offline ingest pipeline, the online LangGraph loop, and the interfaces around the same core. |

They are historical: they were drawn against the author's own audiobook library of 169 books, they
name the tools that demo ran on, and the loop they show predates the catalogue node and the
`validate` step as the code now has them. Three claims in them belong to the demo, not to the
product:

- The demo called the check a **faithfulness guard**. It is not one: the step verifies quote
  provenance — that every quote is verbatim in the passage it cites — and says nothing about
  whether the answer is faithful or correct ([`docs/architecture.md`](../architecture.md)). That
  one label was corrected in `ask-library_en_v5.excalidraw`; the rest of the file is the original.
- The originals name one hosted model (`OpenRouter: Sonnet 4.6`, `AI: Sonnet`), the one that demo
  ran on. The product lets you configure the answering model, and runs fully locally with no
  account at all ([`docs/configuration.md`](../configuration.md)).
- The `~$0.02-0.08 per question` on the simple flow was measured on the author's private 169-book
  library. The figure measured on the demo corpus is $0.04-0.05 per question at v0.2.0-rc1
  ([`docs/cost.md`](../cost.md)).

Where an original and a Mermaid diagram disagree, the Mermaid one is the one reconciled against the
code in this repository.
