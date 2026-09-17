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
uv run scripts/fetch_tech_shelf.py --stage checksums  # pin what was fetched
uv run scripts/fetch_tech_shelf.py --stage verify     # re-hash the files against those pins
```

What is committed is this file, `manifest.yaml`, and `toc/` — the chapter list of each work, which
is what a reviewer reads to see which edition a golden question was written against, and what a
drifted pin is diffed against. Both `raw/` and `prepared/` are gitignored.

## The shelf

| Work | Licence | Handling |
|---|---|---|
| Site Reliability Engineering (2016) | CC BY-NC-ND 4.0 | fetched, text only, **no card** |
| The Site Reliability Workbook (2018) | CC BY-NC-ND 4.0 | fetched, text only, **no card** |
| Software Engineering at Google (2020) | CC BY-NC-ND 4.0 | fetched, text only, **no card** |
| Building Secure and Reliable Systems (2020) | CC BY 4.0 | fetched, card allowed |
| The Twelve-Factor App | MIT | fetched, card allowed |
| OWASP Top 10 for LLM Applications 2025 | CC BY-SA 4.0 | fetched, card allowed, **share-alike** |
| Rules of Machine Learning | CC BY 4.0 | fetched, card allowed |
| ReAct (arXiv 2210.03629) | CC BY 4.0 | fetched, card allowed |
| Chain-of-Thought Prompting (arXiv 2201.11903) | CC BY 4.0 | fetched, card allowed |
| Self-RAG (arXiv 2310.11511) | CC BY 4.0 | fetched, card allowed |
| M3-Embedding / bge-m3 (arXiv 2402.03216) | CC BY 4.0 | fetched, card allowed |
| Reflexion (arXiv 2303.11366) | CC BY 4.0 | fetched, card allowed |
| GraphRAG (arXiv 2404.16130) | CC BY 4.0 | fetched, card allowed |

Each entry in `manifest.yaml` carries the licence identifier, the licence text it names, **the page
where the work states it**, and the date that page was read. Every one of the thirteen was checked
against the source itself while it was being fetched, not against a list — the arXiv abstract page
for the six papers, the repository `LICENSE` for the two git works, the page footer for the three
sre.google/abseil.io books and for Rules of Machine Learning, and its own second page for the OWASP
PDF. A claim that could not be confirmed there would be marked `licence_unverified` rather than
guessed; none of the thirteen is.

**The three CC BY-NC-ND works get no book card.** A card is a summary written *from* the book — a
derivative work — and NoDerivatives withholds exactly the right to distribute one. They are fetched,
converted to text and indexed, so they answer quote questions ("where is the error-budget
formula?"), and they are absent from the card side of the catalogue, which is the price this shelf
pays for carrying the three titles its audience knows by name. The rule is not a convention in a
document: `cards: false` in the manifest, and a card-generating stage may only read the list
`card_targets()` returns, which those three are not in (`tests/test_tech_shelf.py`).

**NonCommercial, for the reader.** BY-NC-ND also limits the *use*: fetching and indexing those
three works on your own machine to ask them questions is non-commercial use, and running the demo
shelf inside a business is not something this repository can license you to do. The other ten works
carry no such limit.

**ShareAlike, for anything derived from OWASP.** The OWASP Top 10 for LLM Applications is CC BY-SA
4.0, so a card, a quote table or any other file *derived from it* carries BY-SA rather than this
repository's Apache-2.0 — the shelf's own files (this README, the manifest, the chapter lists) are
not derived from it and are not affected.

## Pins, and what a red job means

Every file the fetch downloads is pinned by SHA-256 in the work's `sources:` block — per file, not
per work, because these books are dozens of separately published pages and a failure has to say
*which chapter changed*. `.github/workflows/corpus.yml` re-fetches and re-verifies the shelf every
Monday, so a publisher's edit turns up as a red job here rather than as a surprise in somebody's
first build.

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
list is what still says whether the book changed. A drift that moves or renames chapters is a
different edition, and the golden questions in `eval/golden/en-tech.yaml` have to be re-read
against it.

## Building the second index

The shelf is a second index, not a second column: `LIBRARY_DB_PATH` selects which one the agent
answers from, so every existing golden fingerprint over the classics stays comparable and each
shelf's catalogue stays exhaustive for its own library.

```sh
uv run scripts/fetch_tech_shelf.py                                  # fetch, prepare, toc, verify
LIBRARY_DB_PATH=~/ayl-tech uv run ayl-add corpus-tech/prepared      # index the prepared folder
LIBRARY_DB_PATH=~/ayl-tech uv run ask-library "where is the error budget formula?"
```

`ayl-add` treats every `.md` file under the folder as one book and reads the title and author from
the YAML front matter the prepare stage writes, so nothing about the shelf is special to it — see
[add your own books](../docs/add-your-own-books.md) for what it does with them, and
`--dry-run` for what it would change before it embeds anything.

## Terms

The project's own files in this directory (this README, the manifest, the chapter lists, the fetch
script) are under the repository's Apache-2.0 license to the extent the project holds rights in
them. The underlying works keep the licences named above, which this project can neither extend nor
restrict, and each work's attribution is its entry in `manifest.yaml`: title, authors, year, source
URL and licence.
