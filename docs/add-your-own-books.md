# Add your own books

```bash
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books          # index a folder
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books --dry-run  # what it would index, no writes
LIBRARY_DB_PATH=~/ayl-index uv run ask-library "..."        # ask it
```

Every `.txt` / `.md` file under the folder (recursively) is **one book**. Skipped, and reported
on stderr: hidden files and directories; **symlinks** — in or out of the folder, including files
under a symlinked directory; files that are not UTF-8 text; and files with nothing but a front
matter block or a title line. A link is not followed, so nothing outside the folder is ever read
or embedded; copy the file in if you want it indexed. One bad file never aborts the run — the
others are still indexed, and every skip is named on stderr (hidden ones as a single line with
the count and the first few names, so one hidden directory cannot bury the rest). Only a folder
in which *nothing* is indexable is an error, and then the existing index is left untouched.

Re-running the command re-indexes: a book's rows are replaced, never appended, so `ayl-add` on
the same folder twice leaves the index unchanged, and adding a folder to an existing index leaves
the books already in it alone. The update is **staged**: every book of the run is embedded into a
staging table, together with the rows of the books that stay, and the live table is only replaced
once that staging table is complete, with the FTS index and the fingerprint rebuilt right after.
An embedder that dies on book 7 of 20 therefore leaves the index exactly as it was — the price is
that an update rewrites the whole table, so adding one book to a large library costs a full
rewrite (embeddings are only computed for the books of the run). That rewrite is **streamed**:
the existing rows are read and republished in Arrow record batches of 2,000 rows, so the run
holds one batch plus the current book's chunks in memory, not the index. The disk and time cost
still scale with the index — a rewrite copies every row — and LanceDB keeps the previous table
files until its own cleanup, so a large index briefly needs room for both copies.

**The book key** is `Title — Author` — the string the agent cites and filters chapter reads on.
It is taken from, in priority order:

1. a YAML front matter block at the top of the file (`title:`, `author:`);
2. the first line, when it is a standalone title line — a Markdown heading, or a short line
   followed by a blank one — in the form `Title — Author` or `Title by Author`; that line is then
   dropped from the book text;
3. the file name: `Title - Author.txt` → `Title — Author`; a plain `Title.txt` →
   `Title — Unknown`.

Two files that resolve to the same key are refused rather than merged; give one of them front
matter. The row key derived from the key keeps a short digest of it (`the-green-ledger-…-9f2c1b04`),
so two titles that reduce to the same ASCII slug — two Cyrillic titles, say — stay two books
instead of one silently overwriting the other.

**Chapters** come from Markdown `#` / `##` headings (a lone `#` above `##` headings is read as
the book title, not a chapter), else from the same whole-line prose heuristic the demo corpus
uses (`CHAPTER IV.`, `STAVE ONE`, `LETTER 3`, …), else the file becomes a single section named
`Full text`.

**Nothing in your file is dropped, and nothing spurious is added.** Every heading becomes a
section, however short its text — a two-line `CHAPTER I` is a chapter — and the text before the
first heading is kept as a section named `Front matter`; a heading with nothing under it keeps a
section too, with the heading line as its text. The one exception is a table-of-contents line in
a `.txt` file (Markdown headings are taken as written), and it is still not dropped: a prose
heading whose text runs to fewer than
200 characters **and whose title reappears later in the file** is read as a contents entry, so
its heading line and its text are merged into the section above it (into `Front matter` when it
comes before the first real section) instead of opening one. That test is deliberately narrow —
a short heading whose title never comes back is a genuinely short chapter and keeps its own
section — and it is a heuristic, not a parser of book structure: a short real `CHAPTER I` in a
volume whose numbering restarts in the next volume is read as a contents line and merged (reported,
never lost); if that shape matters to you, split the volumes into files. Both halves of the rule
matter: without the merge, the contents page of a raw Gutenberg `.txt`
took the bare names `CHAPTER I`, `CHAPTER II`, … for its one-line entries and the real chapters
were renamed `CHAPTER I (2)`, so drilling into chapter one landed on a line of the contents
page. Every merge is reported: one warning per heading (its title, how much text followed it,
where the text went) and a `N short headings merged into their preceding section` count in the
run summary and in `--dry-run`.

Section names are then made unique within the book (`Chapter I`, `Chapter I (2)`, and so on
until the name is free, so a file that already contains a `Chapter I (2)` still gets three
distinct sections). Uniqueness is not cosmetic: the section name is part of the chunk id and is
how the agent addresses a chapter when it drills down, so two sections sharing a name would read
as one. The demo corpus is cut more aggressively — it *discards* contents lines and short
chapters, with a pinned manifest behind that — but your own files lose no text, and `--dry-run`
lists every section that would be indexed.

**Local vs paid.** `ayl-add` makes no paid calls by default (`EMBED_BACKEND=openrouter` is the
exception): chunking is local, embeddings are computed by your local Ollama (`bge-m3`), and the
LanceDB is written on your machine. Asking questions is free too in the shipped default, which
answers on that same local Ollama. Only `LLM_BACKEND=openrouter` costs money — the orchestrator
LLM, roughly $0.04-0.05 per question on the demo set at `v0.2.0-rc1`, the figure and the run
[`cost.md`](cost.md) works through. (An earlier `v0.1.0` measurement, before the 2,500-character
window and the coverage gate, read $0.03-0.04; this page used to quote that one.)
`EMBED_BACKEND=openrouter` would send your book text to the embedding API too; the default does
not.

**What you do not get:** book cards. The demo corpus carries a distilled card per book (plot,
characters, takeaways) as a second corpus, and generating one costs an LLM call per book, so
`ayl-add` does not make them — `--cards` prints that and exits. An index without a
`cards_<backend>` table is fully supported: the agent searches full text only and says so — the
preflight reports it as a notice (not an error) at CLI start-up and in the web chat welcome, and `library.search` logs it once
per process. Answers are still cited and quote-checked; broad "what is this book about" questions
are simply weaker without cards.

`ayl-add` writes into an existing table only when the table's fingerprint (`index_meta`) matches
the configured embedder exactly — same model, same dims. A table built by another model, and a
table with **no** fingerprint at all (matching dims prove nothing about the model), are both
refused before anything is embedded: one table, one model. Stamp a known-good unstamped table
with `uv run scripts/ingest_demo_corpus.py --stage stamp-meta`, or rebuild it.

Prefer to build the index yourself? The table contract is unchanged: `transcripts_<backend>`
(and optionally `cards_<backend>`) with columns `chunk_id, note, book, source, section, text,
vector`, stamped via `index_meta.write_index_meta`. `ayl-add` is that contract with a CLI in
front of it.
