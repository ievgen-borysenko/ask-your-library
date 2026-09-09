# Ask Your Library

Agentic RAG over a personal book library: you ask in your own words, a LangGraph agent answers
from the books you own with `[book, chapter]` citations, and plain code re-checks every quote it
used against the passage it was copied from.

- You remember the idea, not the book.
- The agent finds the passage in the books you own and quotes it verbatim — checked by code, not
  by another model.
- When the question is ambiguous it asks back, and when your books do not cover it, it says so
  instead of inventing.

## See it work

```mermaid
flowchart TB
    R(["you: a half-remembered idea,<br/>asked in your own words"]):::human
    R --> AG["the agent reads the question"]:::ai
    AG --> SE["it searches the books you own,<br/>in several passes"]:::code
    SE -->|"still ambiguous after<br/>a pass: which book do you mean?"| CQ["it asks back: is it X or Y?"]:::human
    CQ --> AG
    SE --> EV["it keeps verbatim quotes<br/>from those books, nothing else"]:::ai
    EV --> CK["code re-checks every quote against<br/>the passage it was copied from"]:::code
    CK --> A(["an answer with book, chapter citations<br/>or an honest 'your books do not cover this'"]):::ai
    classDef code fill:#dbeafe,stroke:#1d4ed8,color:#000
    classDef ai fill:#fed7aa,stroke:#c2410c,color:#000
    classDef human fill:#bbf7d0,stroke:#15803d,color:#000
```

<!-- demo GIF: docs/img/ask-library-demo.gif, added when recorded -->

## Quick start on a Mac

```bash
git clone https://github.com/ievgen-borysenko/ask-your-library.git && cd ask-your-library
bash scripts/install-mac.sh --dry-run    # the plan, printed; nothing is changed
bash scripts/install-mac.sh              # mostly download time, + ~30 min for the demo corpus
```

Then the first question:

```bash
uv run ask-library "What does Marcus Aurelius say about anger?"
```

Every other system, the manual steps, your own books, the web UI and the eval commands:
[`docs/quick-start.md`](docs/quick-start.md).

## How it works

```mermaid
flowchart TB
    subgraph offline["OFFLINE — build the index, on your machine"]
        direction LR
        BK["your .txt / .md books<br/>or the demo corpus"]:::code
        CRD["book cards: one model call<br/>per book, demo corpus only"]:::ai
        BK --> CHK["ayl-add: chapters from headings,<br/>chunks packed from whole sentences"]:::code
        CHK --> EMB["bge-m3 embeddings,<br/>local Ollama by default"]:::ai
        EMB --> DB[("LanceDB — transcripts, optional cards<br/>hybrid BM25 + vectors, model fingerprint")]:::code
        CRD --> DB
    end
    subgraph online["ONLINE — LangGraph loop, one question"]
        direction TB
        Q(["question: CLI or web chat"]):::human --> PLAN["plan: mode plus 2-4 English queries"]:::ai
        PLAN -->|"catalogue<br/>question"| CAT["catalog: list_books over the index tables,<br/>count = length of that list, no search"]:::code
        PLAN -->|"steps left"| ACT["act: search_both, hybrid + RRF,<br/>or read_chapter; sanitized, stable hit ids"]:::code
        PLAN -->|"no query left"| SYN
        ACT --> OBS["observe: evidence distillate<br/>book, chapter, verbatim quote, hit id"]:::ai
        OBS --> REF{"reflect:<br/>enough<br/>evidence?"}:::ai
        REF -->|"next query, or a<br/>chapter not read yet"| ACT
        REF -->|"ambiguous,<br/>once per run"| CLR["clarify: the run suspends,<br/>candidates go to the reader"]:::human
        CLR --> PLAN
        REF -->|"enough, step limit, deadline,<br/>CRAG gate after 2 dry steps,<br/>no usable decision"| SYN["synthesize: answer with<br/>book, chapter citations"]:::ai
        SYN --> VAL["validate: plain code, no model —<br/>is each quote in the passage it cites?"]:::code
        CAT --> VAL
        VAL --> OUT(["answer with citations and a provenance badge,<br/>or an honest 'not found'"]):::ai
    end
    subgraph legend["CODE = deterministic code · AI = a model call: the answering model you configure, and the embedding model · HUMAN = human in the loop"]
        direction LR
        L1["CODE"]:::code ~~~ L2["AI"]:::ai ~~~ L3["HUMAN"]:::human
    end
    DB --> ACT
    DB --> CAT
    classDef code fill:#dbeafe,stroke:#1d4ed8,color:#000
    classDef ai fill:#fed7aa,stroke:#c2410c,color:#000
    classDef human fill:#bbf7d0,stroke:#15803d,color:#000
```

- Two corpora in one LanceDB, each table stamped with the embedding model that built it.
- Each corpus is searched twice, vectors and BM25, and the lists are fused with Reciprocal Rank Fusion.
- Only `observe` sees retrieved text, sanitized and cut to a budget; the loop sees distilled evidence.
- `validate` is plain code: a quote must be a contiguous whole-token run of the passage it names.
- Catalogue questions skip retrieval; the count is the length of the list read from the tables (ADR-016).
- A 4-step budget, a CRAG-style stop after 2 dry steps, drill-down, one clarify interrupt per run.
- Per-node calls, tokens and USD after every question, with selectivity and redaction counts.
- Node by node, with the decision records behind it: [`docs/architecture.md`](docs/architecture.md).

## Measured

| Measurement | Core v0.1.0 (12 questions, window 1,200) | Core v0.2.0-rc1 (11 questions, 2,500 + gate) | Extended v0.1.0 | Extended v0.2.0-rc1 |
|---|---|---|---|---|
| Retriever window, single-book presence | 9/9 | 8/8 | 12/12 | 12/12 |
| Retriever window, multi-book full coverage | 2/2 | 2/2 | 3/5 | 3/5 |
| Agent eval, questions completed | 12/12 | 11/11 | 21/21 | 21/21 |
| Behavioural compliance (heuristic scorer: titles, refusal, clarify, drill-down) | 12/12 | 11/11 | 17/21 | 18/21 |
| Answer quality, correct / incorrect / incomplete ([how each run was graded](docs/evaluation.md)) | 9 / 1 / 2 | 10 / 0 / 1 | not scored | not scored |
| Quote provenance, validator v0.1: confirmed / unattributed / broken | 46 / 0 / 0 | 47 / 0 / 0 | 53 / 0 / 0 | 73 / 0 / 0 |
| Clarify where the golden requires it | 1/1 | 1/1 | 0/2 | 1/2 |
| Chapter drill-down where expected | not in set | not in set | 0/1 | 0/1 |
| Cost per question, mean (Sonnet 4.6 via OpenRouter, configured rates) | $0.035 | $0.049 | $0.027 | $0.043 |

Quote provenance is not faithfulness, and not correctness: a green row says every quote is
verbatim in the passage it cites, not that the answer reasons well from it. Single runs on tagged
trees, what the green numbers do not prove, the ablation that separates the loop from the model's
own memory, and the catalogue set: [`docs/evaluation.md`](docs/evaluation.md). The reports
themselves are in [`docs/eval-results/`](docs/eval-results/).

## Privacy and cost

- **Do you need an API key?** Only for the answering model: the default is hosted (OpenRouter), and
  a key covers it. Indexing and embeddings are local and need no account, and with
  `LLM_BACKEND=ollama` nothing needs one at all —
  [`docs/configuration.md`](docs/configuration.md), [`docs/cost.md`](docs/cost.md).
- Run this on your own machine, over books you legally own.
- The question **and retrieved corpus fragments** go to the answering model's provider; embeddings are computed **locally** by Ollama by default.
- With `LLM_BACKEND=ollama`, local embeddings and tracing off, nothing leaves the machine at all.
- A typical question costs roughly **$0.04-0.05 on the demo set** at v0.2.0-rc1; `validate` is free, it is plain code.
- Designed for **localhost, single user**, not for internet exposure — the full text, the four injection layers and their limits: [`docs/privacy-and-threat-model.md`](docs/privacy-and-threat-model.md), [`docs/cost.md`](docs/cost.md).

## Docs

| Page | What is in it |
|---|---|
| [`docs/overview.md`](docs/overview.md) | What the project is, in full, and what it does |
| [`docs/quick-start.md`](docs/quick-start.md) | Install on any system, the demo corpus, the CLI, the web UI, the eval commands |
| [`docs/configuration.md`](docs/configuration.md) | Every environment variable, and the fully local, no-account setup |
| [`docs/add-your-own-books.md`](docs/add-your-own-books.md) | `ayl-add`: book keys, chapters, what is skipped, staged re-indexing |
| [`docs/evaluation.md`](docs/evaluation.md) | The two harnesses, three golden sets, the measured runs and the ablation |
| [`docs/privacy-and-threat-model.md`](docs/privacy-and-threat-model.md) | Data flow, threat model, the four injection layers and their limits |

Everything else is under [`docs/`](docs/): the architecture and its decision records, what a
question costs, the known limits, two end-to-end example traces, every eval report verbatim, the
diagram sources, the backlog and the changelog.

## Status and licence

`v0.2.0`, the first public release; the release history is in
[`docs/CHANGELOG.md`](docs/CHANGELOG.md) and the open gaps in
[`docs/backlog.md`](docs/backlog.md).

The code and the project's own files are under Apache-2.0 (`LICENSE`, attribution in `NOTICE`).
The demo corpus is built from Project Gutenberg texts and LibriVox recordings, public domain in the
United States by their sources' own statements; what that means for a given edition or translation
in your country, and what exactly is committed here (machine transcripts, book cards, tables of
contents, two synthetic canaries), is in [`corpus/README.md`](corpus/README.md).

If this project helps your work, please credit Ievgen Borysenko and link to this repository.
