# Add your own books

```bash
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books            # index a folder
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books --dry-run  # what it would change, no writes
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add --doctor           # ledger vs index, no writes
LIBRARY_DB_PATH=~/ayl-index uv run ayl-add ~/books --prune    # also delete books whose file is gone
LIBRARY_DB_PATH=~/ayl-index uv run ask-library "..."          # ask it
```

Every `.txt` / `.md` file under the folder (recursively) is **one book**. Skipped, and reported
on stderr: hidden files and directories; **symlinks** — in or out of the folder, including files
under a symlinked directory; files that are not UTF-8 text; and files with nothing but a front
matter block or a title line. A link is not followed, so nothing outside the folder is ever read
or embedded; copy the file in if you want it indexed. One bad file never aborts the run — the
others are still indexed, and every skip is named on stderr (hidden ones as a single line with
the count and the first few names, so one hidden directory cannot bury the rest). Only a folder
in which *nothing* is indexable is an error, and then the existing index is left untouched.

Re-running the command re-indexes, **one book at a time**. Each book is resolved to a stable
`book_id` in the index's `books` ledger, its rows are deleted by that id and the new ones
appended, and its ledger row is written before and after — so a run that adds one book to a
library of three hundred touches that book alone, and the other 299 are neither read nor
rewritten. The first build of a table is still a single staged publish (nothing to update yet).

The id is **minted, never derived**. That is what makes a correction cheap: fix `author:` in the
front matter (or on the title line), re-run, and the same book is updated rather than indexed a
second time. Two signals identify a book — its key, and failing that the fact that it is the same
file in the same folder, which is what a correction leaves untouched. Content alone identifies
nothing: a byte-identical copy of a book under another title is a second book, with a warning
naming the first, because the alternative is one book silently replacing another.

One case the rules cannot carry, and it is worth knowing before it surprises you: when the key
comes from the **file name**, renaming the file to correct the author changes the key and the path
in the same move, and nothing is left to tell a correction from a second copy. The new name is
indexed as a new book and the old one is reported as vanished; `--prune` clears it. Put the title
and author in front matter if you expect to correct them.

The ledger also makes an interruption visible. Deleting and appending is not one transaction, so a crash in
between leaves a book out of the index; the ledger row still says `requested`, and the **recovery
pass at the start of the next run** finds it, re-indexes it when that run covers it, and names it
when it does not. Nothing else in the index can tell you that a book you added last month is
quietly absent.

The BM25 (full-text) index is still rebuilt **whole** after every run, because LanceDB drops it
with the table it belongs to. That cost is now measured rather than assumed: **0.8 s for the
7,285 rows of the demo corpus**, about 0.1 ms a row, and the seconds of each run are written into
the ledger rows it wrote. An incremental merge is not worth its complexity at that price.

The index is checked, not trusted:

```
uv run ayl-add --doctor
```

reconciles the ledger against the index tables and reports the drift — a book the ledger calls
indexed with no rows, a book in the index the ledger has no row for, a book requested and never
finished, one key with two ids. It writes nothing and exits non-zero when it finds something, so
it can gate a script. Re-running `ayl-add` is what repairs.

**A book whose file is gone** is reported, not deleted: a folder that failed to mount, a file
being edited in place and a half-finished sync all look exactly like a deletion. `--dry-run` lists
such books as `VANISHED`, a normal run names them at the end, and only `--prune` removes their
rows and their ledger entry. Only books of the folder you named are ever considered: one index can
hold several folders, and the books of the others are not missing merely because this folder does
not have them. `--prune` deletes full-text rows only: a **book card** of the same key is kept and
the run says so, because `ayl-add` never writes the cards table and a card is a model call per book
that usually came from the demo corpus. The catalogue then lists that key as a book with no text
until you delete the card yourself, and `--doctor` names it as a card without a book.

**Upgrading an existing index** needs nothing from you. The first run over an index built before
the ledger backfills one row per book already in it (`chunker: legacy`, because nothing recorded
which chunker wrote them) and adds the `book_id` column to the table by a staged copy that
re-embeds nothing. One caveat, stated because it is invisible otherwise: a backfilled row carries
no content digest, so the *first* author correction after such an upgrade still creates a second
book. The re-ingest records the digest, and every correction after it renames in place.

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
preflight reports it as a notice (not an error) at CLI start-up and as the first message of a web
chat, and `library.search` logs it once
per process. Answers are still cited and quote-checked; broad "what is this book about" questions
are simply weaker without cards.

`ayl-add` writes into an existing table only when the table's fingerprint (`index_meta`) matches
the configured embedder exactly — same model, same dims. A table built by another model, and a
table with **no** fingerprint at all (matching dims prove nothing about the model), are both
refused before anything is embedded: one table, one model. Stamp a known-good unstamped table
with `uv run scripts/ingest_demo_corpus.py --stage stamp-meta`, or rebuild it.

Prefer to build the index yourself? The table contract: `transcripts_<backend>` (and optionally
`cards_<backend>`) with columns `chunk_id, note, book, source, section, text, vector, book_id`,
stamped via `index_meta.write_index_meta` — which now also records the chunker and a schema
version. `book_id` is new and sits *beside* `note` rather than replacing it, so chunk ids are
byte-for-byte what they always were; a table without the column still reads, and the next
`ayl-add` over it adds one. Beside the index tables is the `books` ledger — `book_id`, `key`,
`title`, `author`, `source_ref`, `sha256`, `chunker`, `embedding_model`, `status`, `error`,
`requested_at`, `indexed_at`, `rows`, `fts_seconds` — which is what `--doctor` reads. `sha256` is
a digest of the book's *text*, taken after the front matter and any title line are off it, so
correcting the metadata does not read as a different book; `source_ref` is
`local:<folder digest>:<path inside the folder>`, the folder as a digest rather than a path so
that nothing in the ledger names a directory on your machine. The
catalogue deliberately does not: what your library holds is answered from the rows that can
actually be searched, never from the record of what was ingested. `ayl-add` is that contract with
a CLI in front of it.
