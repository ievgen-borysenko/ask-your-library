# Diagram sources

The two `.excalidraw` files here are the author's course-demo originals from September 2026, kept
as the editable sources; the Mermaid diagrams in the [README](../../README.md) are the current
ones and are the drawings to trust.

| File | What it drew |
|---|---|
| `ask-library-flow-simple_en.excalidraw` | The flow in plain terms: ask in your own words, the agent asks back if unclear, searches, answers with citations or says the books do not cover it. |
| `ask-library_en_v5.excalidraw` | The architecture: the offline ingest pipeline, the online LangGraph loop, and the interfaces around the same core. |

They are historical: they were drawn against the author's own audiobook library of 169 books, they
name the tools that demo ran on, and the loop they show predates the catalogue node and the
`validate` step as the code now has them. Where an original and a Mermaid diagram disagree, the
Mermaid one is the one reconciled against the code in this repository.
