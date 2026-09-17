# Upgrading, and the backup that survives one

Building an index takes about half an hour for the demo corpus and longer for a real library, and
some upgrades change what a chunk or a vector *is*. The rule this project holds itself to is that
an upgrade never silently invalidates an index — it either migrates it in place, or it says what
it needs and leaves the index answering until you decide to spend the rebuild.

**Before any upgrade, take a backup.** It is the only copy that survives a rebuild:

```bash
uv run ayl-add --backup ~/ayl-backups --db ~/ayl-index
```

## What an upgrade may change, and what each costs you

| What changed | What it costs | How you find out |
|---|---|---|
| **The chunker** (what a chunk *is*) | a full rebuild: every row is re-chunked and re-embedded | `_index_meta.chunker` differs from this code's — **warned** on every read, **refused** on the next write. Compared per table kind: the sentence packer for transcripts, the card chunker for cards, because they are two rules and a bump to one says nothing about the other |
| **The row schema** (what a row *holds*) | usually nothing: `ayl-add` migrates the table in place, re-embedding no row | nothing to see. A *newer* schema than this code knows is warned and refused, which means you downgraded |
| **The embedding model or its width** | a full rebuild: a query vector from one model against document vectors from another is not a search | **fatal on read** — the CLI and the web UI refuse to start against it |
| **The chat database's schema** (the web UI's history) | nothing, usually: SQLite leaves an existing table alone, so an older `chat.db` keeps its columns | the web UI checks the columns it writes against the ones that are there at every start and **warns**, naming the missing ones; the file is stamped with a chat-schema version |

The three are enforced differently on purpose. A wrong embedder makes retrieval meaningless with
nothing to see, so nothing may read the index. A wrong chunker makes it *worse*, not meaningless —
the same text, cut differently, still retrieves and still quotes verbatim — so a read is allowed
and a write is not: one `ayl-add` into such a table leaves two chunkers' rows in it with nothing
to tell them apart, and the only repair after that is rebuilding all of it. That is the whole
policy, in one line each: **warn on read, refuse on write** ([ADR-020](adr/README.md)).

## This release: the chunker changed (#28), and every earlier index is one behind it

This is the first chunker bump this project has shipped, so it is also the first time the policy
above does anything. **If you built an index before 2026-09-17, it was cut by `sentence-pack-1`
and this code chunks as `sentence-pack-2`.** What changed: transcript chunks are packed to 2,400
characters instead of 4,000, and a "sentence" with no punctuation in it — an hour of speech
transcribed as one run — is broken on whitespace instead of being carried whole. The reason is
that `observe` reads 2,500 characters of a retrieved passage, and 90% of the old chunks were
longer than that, so the retriever ranked text the model never saw
([ADR-025](adr/README.md), [known limits](known-limits.md)). Book cards are cut by a different
rule and are **not** affected: a cards table built by an earlier release stays valid and is not
re-chunked.

**What your index does until you rebuild it.** It answers. Every read logs one warning line and
the CLI and the web UI show a startup notice; retrieval and the quote check work exactly as
before, on the chunks the index already holds. The next `ayl-add` write refuses, because one
append would leave two chunkers' rows in one table.

**Your own library, in order:**

```bash
uv run ayl-add --backup ~/ayl-backups --db ~/ayl-index          # 1. the copy that survives step 2
uv run ayl-add --doctor --db ~/ayl-index                        # 2. read the stamps; exits non-zero on the mismatch
uv run ayl-add ~/books --rebuild --backup ~/ayl-backups --db ~/ayl-index   # 3. re-chunk and re-embed
```

Step 3 takes its own backup first and then replaces every row, so step 1 is only belt-and-braces
if you are running the two back to back — but take it anyway if the index is the only copy of a
library you spent hours building. It re-embeds everything: budget roughly what the first build
took (about half an hour for the demo corpus on an M3 Pro, longer for a large library), and expect
**around 55% more rows** out of the same text. Feed `--rebuild` **every** folder your library came
from, one run each: a rebuild drops the table, so books from folders this run does not name lose
their rows and are reported by name at the end as `requested`.

**The demo corpus** has its own rebuild and does not go through `ayl-add`:

```bash
uv run scripts/ingest_demo_corpus.py --stage ingest
```

The cards table is untouched by the bump, so `--stage cards` is not part of this upgrade.

**If you do not want to rebuild yet**, nothing forces you: keep reading the index and postpone
adding books to it. What you must not do is silence the warning by re-stamping the table
(`--stage stamp-meta --chunker …`) — the stamp would then claim something the rows do not have,
which is worse than no stamp at all.

### What the warning looks like

Once per table per process, in the log, and as a startup notice in the CLI and the web UI:

```
transcripts_ollama was built by chunker 'sentence-pack-1', this code chunks as
'sentence-pack-2'. The index still answers, from the chunks it already holds. The way out
is a rebuild, which replaces every row: `uv run ayl-add <folder> --rebuild --backup <dir>`
takes a copy first, drops the table and re-indexes (`--rebuild --force` skips the copy).
For the demo corpus, `uv run scripts/ingest_demo_corpus.py --stage ingest` is already a
full rebuild.
```

### What the refusal looks like

`ayl-add` stops before it embeds or deletes anything, so a refused run leaves the index exactly as
it was:

```
refusing to write transcripts_ollama: transcripts_ollama was built by chunker
'sentence-pack-1', this code chunks as 'sentence-pack-2'. A write would leave one table
holding rows from two chunkers, and nothing afterwards can tell which rows came from
which — unlike a read, that cannot be undone except by rebuilding the whole table.
The way out is a rebuild, which replaces every row: `uv run ayl-add <folder> --rebuild
--backup <dir>` ...
```

A plain `ayl-add <folder>` would hit that same refusal — a rebuild is what gets past it,
and it is one command:

```bash
uv run ayl-add ~/books --rebuild --backup ~/ayl-backups --db ~/ayl-index
```

It takes the backup **first** (a failed backup stops the rebuild), drops the transcripts
table, and indexes the folder from scratch. The `books` ledger is kept, so every book
keeps the id it was minted with — re-minting them would turn the whole library into new
books, which is the defect the ledger exists to prevent. Books the ledger holds that this
folder does **not** (another folder's, or the demo corpus's) lose their rows with the
table: they are put back to `requested` and named at the end of the run, so you know to
re-run `ayl-add` over their folders too. `--rebuild --force` goes ahead without a backup.

### Checking before you upgrade

`--doctor` reads every stamp out, agreeing or not, and exits non-zero on a mismatch:

```bash
uv run ayl-add --doctor --db ~/ayl-index
```

```
index /Users/…/ayl-index
ledger: 33 book(s); index (transcripts_ollama, cards_ollama): 33 book key(s)
  stamp: transcripts_ollama: bge-m3 / 1024d, chunker sentence-pack-2, row schema 2, stamped 2026-09-17T05:12:44
  stamp: cards_ollama: bge-m3 / 1024d, chunker card-sections-1, row schema 1, stamped 2026-09-17T05:19:02
  no drift: every indexed book has its rows, and every row its book
```

A table stamped with **no chunker** is not a mismatch and never warns. That is every index built
before 0.4.0, and it means "nobody recorded which chunker made these rows" — not "they disagree".
The ledger writes `legacy` for the same absence. If you know which chunker built such an index,
you can say so once and get the checks from then on:

```bash
uv run scripts/ingest_demo_corpus.py --stage stamp-meta --chunker current
```

That is an assertion, like the embedding model the same command stamps: it is believed, not
verified. Leave it off if you are not sure.

## Backup

```bash
uv run ayl-add --backup ~/ayl-backups --db ~/ayl-index
```

writes `~/ayl-backups/<timestamp>/` holding

- `lancedb/` — the whole index directory: every table, the `books` ledger, the `_index_meta`
  stamps and the BM25 index;
- `chat.db` — the web UI's history, from `AYL_CHAINLIT_DIR` or `.chainlit/`, or wherever
  `--chat-db` names. Taken through SQLite's own backup, so it is **one consistent snapshot in one
  file** rather than a main file copied beside somebody else's write-ahead log. Absent if you never
  started the web UI, and the report says so; a file SQLite cannot open is reported and the index
  is still backed up without it;
- `MANIFEST.json` — what was copied, the `_index_meta` rows, the row count per table, the number
  of ledger rows, the version of the code that took it, and a sha256 of every file plus one
  digest over the whole set.

**When a copy is safe.** This is the part a plain `cp -r` cannot give you, and it is the reason
the command exists rather than a line in the README:

1. **No ingest is running.** Both write paths (`ayl-add`, the demo corpus's ingest stages) hold an
   **`flock`** for the length of a run, on a file **beside** the index directory and named after it
   (`.ayl-ingest-<name>.lock`); `--backup` and `--restore` take the same lock. Beside rather than
   inside, because a restore publishes by renaming the directory and a lock living in it would
   travel with the rename; keyed by the resolved path, so two spellings of one index are one lock.
   A backup started while an ingest is writing is refused, naming the command and pid that holds
   it; an ingest started while a backup or restore is under way is refused the same way.

   The lock is held by the operating system, not by the file's existence, and **there is nothing
   to clear**: the kernel releases it when the holding process ends, however it ends — including a
   crash, a `kill -9` or a power cut. The file is never deleted (it is only what the lock is held
   on) and the line inside it, naming the pid and the command, exists so a refusal can say who is
   holding it; nothing is decided from that line. On a network share `flock` means whatever the
   share implements, and a refusal that names another machine says so rather than promising
   something this code cannot.
2. **No staged rebuild is half-finished.** LanceDB has no rename, so replacing a table goes
   through a staging copy, and there is a moment with the live table dropped and the staged one
   not yet promoted. A copy taken there restores to an index with a table missing. `--backup`
   finishes or discards any such rebuild before it copies, and the manifest records that it did.
3. **Nothing rotted since.** `--restore` recomputes every digest before it touches anything.

And the restore itself is staged: the verified copy is built **beside** the target and only a
complete one is swapped in, by rename. A failure while copying leaves the index that is there
exactly as it was; a failure in the swap puts the moved-aside index back. The chat database is
restored the same way — snapshotted to a file beside the live one and renamed over it — so a
failure there cannot leave you with no history at all.

A **symlink inside the index** is refused, at backup and at restore: a copy follows links while the
manifest's digests skip them, so a linked file would be in the backup and in no digest, and one
pointing outside the index would pull whatever it names into the copy. LanceDB writes none. The
index path itself may of course be a link — that is the case above.

A destination **inside** the index directory is refused: that is a copy of a directory into
itself. A failure part-way through removes the half-written directory rather than leaving something
shaped like a backup with no manifest to say what it is missing.

What is **not** backed up: `.scratch/` (the passages as the model saw them, written per run and
not cleaned) and `.env` (a backup of secrets is a second place to lose them from).

## The chat database

The web UI's history has the same two things the index has, for the same reason. `ui.py` creates
its tables with `CREATE TABLE IF NOT EXISTS`, which by design does nothing to a table that is
already there — so a `chat.db` written by an older release keeps its old columns, looks healthy,
and fails on the first insert naming a column it does not have, in the middle of somebody's
question. At every start the UI now compares the columns its schema declares against the columns
that are actually there and warns, naming them:

```
…/.chainlit/chat.db: the table 'steps' has no column(s) command, defaultOpen, which this
version writes. SQLite leaves an existing table alone, so an older chat database keeps its
old shape and fails on the first insert that names one of them. Move the file aside and let
the UI create a new one (the conversation history in it is lost — back it up first with
`uv run ayl-add --backup <dir>`), or add the column(s) by hand.
```

A warning and not a refusal: the UI works for everything that does not touch the missing column,
and the remedy throws away every past conversation, so it is the reader's decision. The file also
carries a `ayl_schema` row with the chat-schema version, so a database written by a **newer**
release is recognisable as one rather than discovered column by column.

## Restore

```bash
uv run ayl-add --restore ~/ayl-backups/20260917-051244 --db ~/ayl-index          # fresh location
uv run ayl-add --restore ~/ayl-backups/20260917-051244 --db ~/ayl-index --force  # over an index
```

The backup is verified against its manifest first, every time. Three things are refused, and
`--force` overrides exactly one of them:

- a backup that no longer matches its manifest — **nothing is touched**, and no flag makes
  overwriting a working index with a corrupt copy safe;
- an index already at `--db` — this is what `--force` is for, and it covers the **chat database**
  too: without it a `chat.db` already at the target is left alone and the report says so, with it
  that file is replaced as well;
- an ingest in flight on the index being replaced.

The index that `--force` replaces is **moved aside, not deleted**: it stays as
`<index>.replaced-<timestamp>` and the report names it. Delete it yourself once you are satisfied.
The chat database is restored only when the target is absent or `--force` is given, and it is
restored owner-readable only, as the web UI keeps it.

If `--db` is a **symlink** — `data/lancedb` is one in this project's own dev checkout — the link is
followed: the real directory is what is moved aside and what the backup is written into, and the
link goes on pointing at it. Renaming the link instead would leave the real index where it was and
put the restored one on whichever volume the link lives on.

Then check what you have:

```bash
uv run ayl-add --doctor --db ~/ayl-index
```

## The procedure, end to end

```bash
# 1. before pulling: know what you have, and keep it
uv run ayl-add --doctor --db ~/ayl-index
uv run ayl-add --backup ~/ayl-backups --db ~/ayl-index

# 2. upgrade
git pull && uv sync

# 3. what does the new code think of the old index?
uv run ayl-add --doctor --db ~/ayl-index

# 4a. no mismatch: nothing to do. A newer ROW SCHEMA is migrated in place by the next run:
uv run ayl-add ~/books --db ~/ayl-index

# 4b. a chunker or embedder mismatch: rebuild, which discards every row it replaces
uv run ayl-add ~/books --db ~/ayl-index                       # refused, and it names --rebuild
uv run ayl-add ~/books --rebuild --backup ~/ayl-backups --db ~/ayl-index   # copy, drop, re-index
# for the demo corpus, a full rebuild is the repair (it replaces every row):
uv run scripts/ingest_demo_corpus.py --stage ingest

# 5. if the rebuild goes wrong, the backup is the way back
uv run ayl-add --restore ~/ayl-backups/<timestamp> --db ~/ayl-index --force
```

## See also

- [`docs/add-your-own-books.md`](add-your-own-books.md) — `ayl-add` itself, the ledger, `--prune`
- [`docs/known-limits.md`](known-limits.md) — what a rebuild costs, and what the lock does not cover
- [`docs/adr/README.md`](adr/README.md) — ADR-020 (what is stamped and how it is enforced),
  ADR-024 (the ledger and the row schema)
