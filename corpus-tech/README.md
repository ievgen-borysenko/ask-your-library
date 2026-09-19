# The engineer's shelf: what is here, from where, under which statements

A second demo corpus, next to the classics in [`corpus/`](../corpus/README.md): thirteen openly
licensed engineering books, guides and papers — the ones an audience of engineers has actually
read. It exists so the demo question can be one the viewer asked themselves this week ("where is
the error-budget formula?") instead of a quiz about 19th-century novels, and so the two behaviours
a per-book assistant cannot show have something to happen on: asking back when two books cover the
same chapter title, and refusing when the book is not on the shelf (#58).

**No text of these works is committed.** `manifest.yaml` is the single source of truth — every work
with its source, its licence, and the SHA-256 of every file fetched to build it — and
`scripts/fetch_tech_shelf.py` downloads them at build time:

```sh
uv run scripts/fetch_tech_shelf.py --stage fetch      # download into corpus-tech/raw/ (gitignored)
uv run scripts/fetch_tech_shelf.py --stage prepare    # one .md per work (gitignored)
uv run scripts/fetch_tech_shelf.py --stage toc        # the chapter lists, committed
uv run scripts/fetch_tech_shelf.py --stage structure-cards  # the ND works' cards, no model
uv run scripts/fetch_tech_shelf.py --stage checksums  # pin what was fetched
uv run scripts/fetch_tech_shelf.py --stage verify     # re-hash the files against those pins
```

What is committed is this file, `manifest.yaml`, `toc/` — the chapter list of each work, which is
what a reviewer reads to see which edition a golden question was written against, and what a
drifted pin is diffed against — and `cards/`, which holds no passage of any work beyond its title,
its chapter list and, for the three NoDerivatives works, its publishing site's own description,
quoted. `raw/`, `prepared/` and `cards-local/` are gitignored.

**The rule behind that split: the repository ships the generator, never the derivative.** Anything
a work's licence lets anybody share is committed; anything it lets a reader make only for
themself — its text, and a summary of a NoDerivatives work — is built on the reader's machine from
`manifest.yaml`, and is never in the tree.

**Using the text is the reader's own use, wherever the model runs.** The boundary is the
repository, not the model. A reader who builds this shelf indexes and queries it for themself, and
a hosted backend (`EMBED_BACKEND=openrouter` to embed it, `LLM_BACKEND=openrouter` to answer from
it) processes passages of the reader's own copy on the reader's behalf — no work, and no
adaptation of one, is shared with anybody by that. So the NoDerivatives works are indexed and
answered from like every other book, on either backend, and the only thing the code enforces
about them is what can leave the reader's machine *as a file*: no model-written card of one is
ever produced (`card_targets()`), and no passage of one is committed. That last one is a check
on the builder's machine, not in CI: a test compares every tracked file, the chapter lists and
cards included, with the prepared text of the three works and fails on any run of eight words or
more that is not a name, a title or a chapter title — and it can only run where that text has been
built, so in CI, which never builds it, it skips and says so. Choosing a hosted backend sends
retrieved passages to that provider, for this shelf as for
any other: [`docs/privacy-and-threat-model.md`](../docs/privacy-and-threat-model.md).

## The shelf

| Work | Licence | Text | Card (`cards:`) |
|---|---|---|---|
| Site Reliability Engineering (2016) | CC BY-NC-ND 4.0 | built | **structure**, committed |
| The Site Reliability Workbook (2018) | CC BY-NC-ND 4.0 | built | **structure**, committed |
| Software Engineering at Google (2020) | CC BY-NC-ND 4.0 | built | **structure**, committed |
| Building Secure and Reliable Systems (2020) | CC BY 4.0 | built | shared, committed |
| The Twelve-Factor App | MIT | built | shared, committed |
| OWASP Top 10 for LLM Applications 2025 | CC BY-SA 4.0 | built | shared, committed, **share-alike** |
| Rules of Machine Learning | CC BY 4.0 | built | shared, committed |
| ReAct (arXiv 2210.03629) | CC BY 4.0 | built | shared, committed |
| Chain-of-Thought Prompting (arXiv 2201.11903) | CC BY 4.0 | built | shared, committed |
| Self-RAG (arXiv 2310.11511) | CC BY 4.0 | built | shared, committed |
| M3-Embedding / bge-m3 (arXiv 2402.03216) | CC BY 4.0 | built | shared, committed |
| Reflexion (arXiv 2303.11366) | CC BY 4.0 | built | shared, committed |
| GraphRAG (arXiv 2404.16130) | CC BY 4.0 | built | shared, committed |

*Built* means fetched from the publisher and converted on your machine by the script, never
committed.

Each entry in `manifest.yaml` carries the licence identifier, the licence text it names, **the page
where the work states it**, and the date that page was read. Every one of the thirteen was checked
against the source itself while it was being fetched, not against a list — the arXiv abstract page
for the six papers, the repository `LICENSE` for the two git works, the page footer for the three
sre.google/abseil.io books and for Rules of Machine Learning, and its own second page for the OWASP
PDF. A claim that could not be confirmed there would be marked `licence_unverified` rather than
guessed; none of the thirteen is.

**The three CC BY-NC-ND works get a structure card and never a summary.** A summary is written
*from* the book — a derivative work — and NoDerivatives withholds exactly the right to distribute
one. What the licence does grant is reproducing the work, in whole or in part, so their card
reproduces three parts of it and adds nothing: the title, the chapter list and the publishing
site's own description, quoted and attributed (see [Book cards](#book-cards)). The text itself is
fetched, converted and indexed, so they answer quote questions ("where is the error-budget
formula?").

**NonCommercial, for the reader.** BY-NC-ND also limits the *use*: fetching and indexing those
three works on your own machine to ask them questions is non-commercial use, and running the demo
shelf inside a business is not something this repository can license you to do. The other ten works
carry no such limit.

**ShareAlike, for anything derived from OWASP.** The OWASP Top 10 for LLM Applications is CC BY-SA
4.0, so a card, a quote table or any other file *derived from it* carries BY-SA rather than this
repository's Apache-2.0 — the shelf's own files (this README, the manifest, the chapter lists) are
not derived from it and are not affected.

## Book cards

A **book card** is one Markdown page per work: what the work is, its key ideas with the chapter
each lives in, its chapter list, the vocabulary it uses in its own way, and the concerns that run
across it. It is the second thing the agent searches — the full text answers "what does this book
say about X", the card answers "which of my books is this" and "which chapter covers X", and the
catalogue is built from the cards. A card holds no passage of the work, which is why the cards
are the one part of this shelf that **is** committed — except a `local` one, below.

```sh
uv run scripts/fetch_tech_shelf.py --stage cards                # every work that may have one
uv run scripts/fetch_tech_shelf.py --stage cards --work twelve  # just that one
uv run scripts/fetch_tech_shelf.py --stage cards --force        # rebuild cards already written
```

**Three kinds of card, and the manifest's `cards:` says which one a work gets:**

| `cards:` | Written by | Where | Committed |
|---|---|---|---|
| `shared` | a model, at `--stage cards` | `cards/` | yes — the licence lets a summary be shared |
| `structure` | code, at `--stage structure-cards`, no model | `cards/` | yes — a verbatim reproduction in part |
| `local` | a model, at `--stage cards` | `cards-local/` | **never** — gitignored |

A **structure card** is what the three CC BY-NC-ND works get: `## About`, the description of the
work on the site that publishes it online, quoted character for character with the page it came
from and the day it was read; `## Structure`, the committed chapter list; and `## Facts` — year,
edition, licence, source — from the manifest. There is no Summary, no Key ideas, no Terms and no
Themes, and nothing in it is in this project's words: that is what keeps it a reproduction of the
work *in part*, which the licence grants, rather than an adaptation, which it withholds. It is
still a card — the same front matter and H1 key, cut by the same `chunk_card` — so an "is this
the book about toil?" question finds the two SRE books' chapter lists on the card side too. The
stage reads only committed files, so it is part of the plain run, and a test rebuilds every
committed structure card and compares it byte for byte.

A **local card** is for a work whose licence lets a reader make a summary for themself but not
share it. No work on this shelf is `local` today; it is the value a work gets when it names none,
because a card nobody decided may be shared is not one to commit. The stage writes it to
`cards-local/`, which `.gitignore` excludes, and nothing else: which folder a card goes to is
decided in one function, and it cannot send a `local` card to `cards/`.

**No model ever writes a card of a NoDerivatives work, whatever its `cards:` says.** The model
stage may only read the list `card_targets()` returns, and that list checks the licence as well as
the manifest value — so a mislabelled ND work is still skipped before its text is read. The rule,
the belt-and-braces check, and the committed ND cards being structure cards and nothing else are
all tests (`tests/test_tech_shelf.py`).

This stage is the only one that calls a model, so it is asked for by name and is never part of
`--stage all`. The call goes through the project's own client, so `LLM_BACKEND=ollama` writes the
cards on the local model and `LLM_BACKEND=openrouter` on the hosted one, under the same egress
rules as everything else the agent does. The model is never shown the whole work: it gets the
front matter, the full chapter list, and the opening of each chapter within a budget — the chapter
list in `## Structure` is copied from the prepared text rather than generated, so the section that
answers "which chapter covers X" cannot rename or invent a chapter.

**Which model wrote a card is recorded in the card**, because a card built locally and one built on
a hosted model are otherwise the same file:

```yaml
card_kind: shared
card_model: openrouter/anthropic/claude-sonnet-4.6
card_built: 2026-09-18
licence: CC-BY-4.0
licence_url: https://creativecommons.org/licenses/by/4.0/
work_url: https://github.com/google/building-secure-and-reliable-systems
adapted: "a model-written summary of the work, not the work itself"
```

The ten committed cards were written through OpenRouter with the model named in each card's
`card_model`, before `LLM_REASONING` existed — so the settings that reproduce them are
`LLM_BACKEND=openrouter ORCHESTRATOR_MODEL=anthropic/claude-sonnet-4.6 LLM_REASONING=provider`, not
the hosted defaults of today. A model's reply is not byte-reproducible anyway; what those settings
reproduce is the same model under the same prompt.

The licence lines are the notice a shared adaptation owes the work (CC BY 4.0 §3(a)): its licence,
where it is, and that the card is a model-written summary rather than the work. A card of a
ShareAlike work adds `card_licence`, because the card itself is under the work's licence — today
that is the OWASP card, under CC BY-SA 4.0. The front matter and the `## Structure` section of a
model-written card are derived rather than generated, so `--stage restamp-cards` rebuilds both from
the manifest and the chapter list without calling a model, and a test holds every committed card to
exactly that.

**A shared card is a paraphrase, and a hand edit says so.** The prompt forbids copying the work,
and on the builder's machine a test compares each shared card with its work's prepared text and
fails on any run of twelve words or more that is not a name, a title or a chapter title. Where a
line slipped through anyway it is reworded by hand, never regenerated silently, and the card
records it in its front matter, so that `card_model` stays a true account of who wrote the rest:

```yaml
edited: "one Terms line (Understandability) reworded by hand to drop a verbatim phrase of the book, 2026-09-19"
```

Two cards carry one today, Building Secure and Reliable Systems and Chain-of-Thought, and
`--stage restamp-cards` keeps the field.

`--force` is what rebuilds one; without it an existing card is left alone, so re-running the stage
over a shelf with one card missing costs one model call.

## Pins, and what a red job means

Every file the fetch downloads is pinned by SHA-256 in the work's `sources:` block — per file, not
per work, because these books are dozens of separately published pages and a failure has to say
*which chapter changed*. `.github/workflows/corpus.yml` re-fetches and re-verifies the shelf every
Monday, so a publisher's edit turns up as a red job here rather than as a surprise in somebody's
first build.

**What the digest is taken of is `pin:` in the manifest, per work, and there is no default.**

| `pin` | Works | What is hashed |
|---|---|---|
| `text` | `html-chapters`, `arxiv-html` | the text the HTML reader extracts from the page |
| `bytes` | `pdf`, `git-markdown`, `git-html` | the file exactly as it was fetched |

The reason is that two of these publishers do not serve the same bytes twice, and neither
difference is text of the book:

- **developers.google.com** (Rules of Machine Learning) stamps every response with a CSP
  `<script nonce="…">` and an analytics JSON blob whose keys are serialised in a different order
  each time. Two fetches three seconds apart gave two different digests.
- **abseil.io** (Software Engineering at Google) is behind Cloudflare's email obfuscation, which
  rewrites the book's "Email … to comment" link with a fresh key on every response. Three digests
  were observed for one unchanged page: the pin, a local fetch and CI's.

A byte pin on those two files was therefore red on every single run — and a job that is red by
construction cannot report the edit it exists to catch in the other 174 files. The reader drops
`<script>` entirely and never sees an attribute, while the obfuscated link's visible text does not
move, so hashing the reader's output pins exactly what the shelf is built from. A changed
paragraph, or a heading that disappears, still changes the digest
(`tests/test_tech_shelf.py`). A PDF and a file served out of a git repository are byte-stable and
keep the stronger rule. The other side of the trade: a `text` pin is taken of the reader's output,
so a change to the reader itself — a tag it now keeps or drops, a different whitespace rule — moves
every text pin with no upstream change at all, and has to be followed by `--stage checksums` in the
same commit.

The weekly job also rebuilds what is built from those pins and committed: after the fetch it runs
`prepare --skip-pdf`, `toc --skip-pdf` and `structure-cards`, and fails if `toc/` or `cards/` then
differ from the tree, new files included. So a change to the reader or the chapter splitter that
moves a chapter title is red on the change itself. `--skip-pdf` leaves out OWASP, the one work read
through `pdftotext`, which the CI image does not carry; its chapter list is the one this does not
re-check.

The pages index the fetch writes beside them (_pages.json) is hashed as bytes whatever a work's
`pin` says: it is this script's record of which pages the publisher's table of contents listed and
in which order, not a page to read, so a chapter that appears, vanishes or moves has to be a
failure. And because `--stage verify` runs the reader
rather than `pdftotext`, the weekly job still needs no poppler.

When it goes red on a work, the pin is not the thing to fix first:

```sh
# 1. fetch that work again, over the cached copy
uv run scripts/fetch_tech_shelf.py --stage fetch --work "Site Reliability" --refetch

# 2. rebuild its text and its chapter list from what just arrived
uv run scripts/fetch_tech_shelf.py --stage prepare --work "Site Reliability"
uv run scripts/fetch_tech_shelf.py --stage toc --work "Site Reliability"

# 3. the chapter list, regenerated from the NEW pages: empty = the same book
git status --porcelain corpus-tech/toc

# 4. only then re-pin
uv run scripts/fetch_tech_shelf.py --stage checksums --work "Site Reliability"
```

Step 3 is the one that matters. A re-pin makes the checksums green by construction; the chapter
list is what still says whether the book changed. Under a `text` pin the job is already past the
noise — a digest that moved is a sentence of the book that moved. A drift that moves or renames chapters is a
different edition, and the golden questions in `eval/golden/en-tech.yaml` have to be re-read
against it.

## Building the second index

The shelf is a second index, not a second column: `LIBRARY_DB_PATH` selects which one the agent
answers from, so every existing golden fingerprint over the classics stays comparable and each
shelf's catalogue stays exhaustive for its own library.

```sh
uv run scripts/fetch_tech_shelf.py                                  # fetch, prepare, toc, structure cards, verify
uv run scripts/fetch_tech_shelf.py --stage cards                    # the cards
export LIBRARY_DB_PATH=~/ayl-tech
uv run ayl-add corpus-tech/prepared                                 # index the prepared folder
uv run scripts/ingest_demo_corpus.py --stage cards --cards-dir corpus-tech/cards \
    --cards-dir corpus-tech/cards-local                             # local cards, if any
uv run ayl-add --doctor                                             # ledger vs index, no writes
uv run ask-library "where is the error budget formula?"
```

`ayl-add` treats every `.md` file under the folder as one book and reads the title and author from
the YAML front matter the prepare stage writes, so nothing about the shelf is special to it — see
[add your own books](../docs/add-your-own-books.md) for what it does with them, and
`--dry-run` for what it would change before it embeds anything. It does not write a cards table (a
card needs a model), which is what the second command is for: `--cards-dir` points the classics'
cards stage at this shelf's cards — repeat it to add the cards built only on this machine; a folder
that does not exist is empty — and `LIBRARY_DB_PATH` decides which index they land in.

The whole shelf, measured on one M3 Pro / 36 GB with `EMBED_BACKEND=ollama` (bge-m3, 1024 dims):
**13 books, 275 sections, 2,590 chunks in 5.4 minutes**, chunker `sentence-pack-2`, with the
full-text index rebuilt in 0.2 s.

## Terms

The project's own files in this directory (this README, the manifest, the chapter lists, the fetch
script) are under the repository's Apache-2.0 license to the extent the project holds rights in
them. The underlying works keep the licences named above, which this project can neither extend nor
restrict, and each work's attribution is its entry in `manifest.yaml`: title, authors, year, source
URL and licence. A card in `cards/` is not the project's alone: a model-written card is an
adaptation of its work and carries that work's licence, link and an adaptation notice in its front
matter (the OWASP card is itself CC BY-SA 4.0), and a structure card reproduces the work's title,
chapter list and its publishing site's description under the work's own licence, stated in the card.
