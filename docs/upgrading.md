# Upgrading, and the backup that survives one

Building an index takes about half an hour for the demo corpus and longer for a real library, and
some upgrades change what a chunk or a vector *is*. The rule this project holds itself to is that
an upgrade never silently invalidates an index — it either migrates it in place, or it says what
it needs and leaves the index answering until you decide to spend the rebuild.

**Before any upgrade, take a backup.** It is the only copy that survives a rebuild:

```bash
uv run ayl backup ~/ayl-backups --db ~/ayl-index
```

`ayl backup`, `ayl restore`, `ayl doctor` and `ayl add` are one program under four verbs, so
every flag on this page is one of its flags; `ayl <verb> --help` lists the ones that verb takes.
`--db <dir>` aims the whole command at that index — the checks it runs and the report it prints
alike. Upgrading from a version before `ayl`: the two names
it replaced, `ask-library` and `ayl-add`, are still installed and still run the same code — each
prints one deprecation line and is removed at `0.6.0`, so a script of your own has one minor
release to change the name it types.

## What an upgrade may change, and what each costs you

| What changed | What it costs | How you find out |
|---|---|---|
| **The chunker** (what a chunk *is*) | a full rebuild: every row is re-chunked and re-embedded | `_index_meta.chunker` differs from this code's — **warned** on every read, **refused** on the next write. Compared per table kind: the sentence packer for transcripts, the card chunker for cards, because they are two rules and a bump to one says nothing about the other |
| **The row schema** (what a row *holds*) | usually nothing: `ayl add` migrates the table in place, re-embedding no row | nothing to see. A *newer* schema than this code knows is warned and refused, which means you downgraded |
| **The embedding model or its width** | a full rebuild: a query vector from one model against document vectors from another is not a search | **fatal on read** — the CLI and the web UI refuse to start against it |
| **The chat database's schema** (the web UI's history) | nothing, usually: SQLite leaves an existing table alone, so an older `chat.db` keeps its columns | the web UI checks the columns it writes against the ones that are there at every start and **warns**, naming the missing ones; the file is stamped with a chat-schema version |

The three are enforced differently on purpose. A wrong embedder makes retrieval meaningless with
nothing to see, so nothing may read the index. A wrong chunker makes it *worse*, not meaningless —
the same text, cut differently, still retrieves and still quotes verbatim — so a read is allowed
and a write is not: one `ayl add` into such a table leaves two chunkers' rows in it with nothing
to tell them apart, and the only repair after that is rebuilding all of it. That is the whole
policy, in one line each: **warn on read, refuse on write** ([ADR-020](adr/README.md)).

## The index moved to `$AYL_HOME/index`

Three defaults moved out of the directory a command was typed in and into the reader's own
folder, `AYL_HOME` (`~/AskYourLibrary` unless set) — [ADR-026](adr/README.md#adr-026-ayl_home-is-the-home-of-everything-built-on-this-machine-the-index-the-scratchpads-the-chat-database-the-private-shelf):

| What | Old default | New default | Set this to keep it elsewhere |
|---|---|---|---|
| the index | `data/lancedb`, relative to the working directory | `$AYL_HOME/index` | `LIBRARY_DB_PATH` |
| the scratchpads of `ayl ask` | `.scratch`, relative to the working directory | `$AYL_HOME/scratch` | `ASK_SCRATCH_DIR` |
| the web chat's database and auth secret | the checkout's `.chainlit/` | `$AYL_HOME/ui/.chainlit/` | `AYL_CHAINLIT_DIR` |

The demo corpus's downloads and prepared texts stay in the checkout's `data/raw/` and
`data/prepared/`; only the index it builds goes to the new place.

**Nothing is moved, copied or deleted for you**, and nothing you already built stops answering.
The index a command opens, when no `--db` names one, is decided by three rules in this order, and
`ayl doctor` prints which one applied and why:

1. **`LIBRARY_DB_PATH` is set** — that path, exactly as written, always, with nothing said about
   it. Check your `.env`: every `.env.example` before this one had the line
   `LIBRARY_DB_PATH=data/lancedb` in it, uncommented, so a `.env` copied from one (or written by
   `scripts/install-mac.sh`) keeps the index in the checkout through this rule, silently. Delete
   the line to take the new default — after the move below, if that is where your index is.
2. **It is unset, and the working directory holds `data/lancedb` with a `transcripts_<backend>`
   table in it** — that index is read where it is, and every process that uses it says so once, on
   stderr:

   ```
   note: reading the index at /…/ask-your-library/data/lancedb, the old default. The default is
   now /Users/…/AskYourLibrary/index ($AYL_HOME/index); the old place is read until 0.5.0, when
   it becomes an error. Nothing is moved for you. To move it: `ayl backup <dir>`, then `ayl
   restore <dir>/<timestamp> --db /Users/…/AskYourLibrary/index --chat-db
   /Users/…/AskYourLibrary/ui/.chainlit/chat.db`, then move data/lancedb out of this directory,
   and the checkout's .chainlit/chat.db (with its -wal/-shm) if there is one; or set
   LIBRARY_DB_PATH=/…/ask-your-library/data/lancedb to keep the index where it is.
   ```

   (one line on the terminal, wrapped here), and never when a command is only asked for its help
   or its version. **This rule is kept for one minor release: from 0.5.0 an index found there is
   an error naming the same two commands.** The chat database has a rule of its own with the same
   sunset: when `AYL_CHAINLIT_DIR` is unset and the checkout the package runs from — not the
   working directory — has any `chat.db` file in its `.chainlit/`, the web chat reads that file
   where it is and says so once when it starts.
3. **Otherwise** — `$AYL_HOME/index`, created by the first write.

`$AYL_HOME/index` is refused when `AYL_HOME` resolves inside a git work tree — the index holds the
full text of the books it was built from — and the refusal names `LIBRARY_DB_PATH`, which is the
way to keep a throwaway index inside a checkout on purpose. The scratchpads and the web chat's
state are not refused there.

**The move**, from the checkout, with the web chat stopped:

```bash
uv run ayl backup ~/ayl-backups                     # takes the index rule 2 found, and the chat db
uv run ayl restore ~/ayl-backups/<timestamp> --db ~/AskYourLibrary/index \
    --chat-db ~/AskYourLibrary/ui/.chainlit/chat.db
uv run ayl doctor --db ~/AskYourLibrary/index      # the same books, the same stamps
mv data/lancedb ~/ayl-old-index                     # out of the working directory, so rule 2
mv .chainlit ~/ayl-old-chainlit                     # no longer applies; delete them when satisfied
uv run ayl doctor                                   # "index: …/AskYourLibrary/index — … the default"
```

A restore refuses an index already at `--db` — `~/AskYourLibrary/index` exists if a demo build has
run since you upgraded — and `--force` moves that one aside rather than deleting it
([Restore](#restore)). The web chat's login secret is not in a backup: the first start after the
move mints a new one, and you log in again. To keep everything where it is instead, set
`LIBRARY_DB_PATH` and `AYL_CHAINLIT_DIR` to the two old directories as absolute paths.

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
before, on the chunks the index already holds. The next `ayl add` write refuses, because one
append would leave two chunkers' rows in one table.

**Your own library, in order:**

```bash
uv run ayl backup ~/ayl-backups --db ~/ayl-index    # 1. the copy that survives step 3
uv run ayl doctor --db ~/ayl-index                  # 2. read the stamps; exits non-zero on the mismatch
uv run ayl add ~/books --rebuild --backup ~/ayl-backups --db ~/ayl-index   # 3. re-chunk and re-embed
uv run ayl add ~/more-books --db ~/ayl-index        # 4. every OTHER folder, plain
```

Step 3 takes its own backup first and then replaces every row, so step 1 is only belt-and-braces
if you are running the two back to back — but take it anyway if the index is the only copy of a
library you spent hours building. It re-embeds everything: budget roughly what the first build
took (about half an hour for the demo corpus on an M3 Pro, longer for a large library), and expect
**around 55% more rows** out of the same text.

**`--rebuild` goes once, whatever the number of folders.** It drops the whole transcripts table,
so it rebuilds the INDEX and not a folder — running it once per folder would leave only the folder
that ran last, each run dropping what the one before it wrote. After the rebuild there is no
mismatch left to refuse, so every other folder goes in with a plain `ayl add <folder>`, which
appends. A `--rebuild` that would drop another folder's books stops before it drops anything and
says exactly this, naming them; `--rebuild --force` goes ahead and reports every book it orphaned
(their ids are kept and their rows are not, so they go back to `requested` until you re-add their
folder).

**The demo corpus** has its own rebuild and does not go through `ayl add`:

```bash
uv run scripts/ingest_demo_corpus.py --stage ingest
```

The cards table is untouched by the bump, so `--stage cards` is not part of this upgrade.

**If you do not want to rebuild yet**, nothing forces you: keep reading the index and postpone
adding books to it. What you must not do is silence the warning by re-stamping the table
(`--stage stamp-meta --chunker …`) — the stamp would then claim something the rows do not have,
which is worse than no stamp at all. Since #75 the command refuses that attempt itself: claiming the
version this code chunks at samples the rows first and refuses when they cannot have come from it.

### What the warning looks like

Once per table per process, in the log, and as a startup notice in the CLI and the web UI:

```
transcripts_ollama was built by chunker 'sentence-pack-1', this code chunks as
'sentence-pack-2'. The index still answers, from the chunks it already holds. The way out
is a rebuild, which replaces every row: `uv run ayl add <folder> --rebuild --backup <dir>`
takes a copy first, drops the table and re-indexes (`--rebuild --force` skips the copy).
For the demo corpus, `uv run scripts/ingest_demo_corpus.py --stage ingest` is already a
full rebuild.
```

### What the refusal looks like

`ayl add` stops before it embeds or deletes anything, so a refused run leaves the index exactly as
it was:

```
refusing to write transcripts_ollama: transcripts_ollama was built by chunker
'sentence-pack-1', this code chunks as 'sentence-pack-2'. A write would leave one table
holding rows from two chunkers, and nothing afterwards can tell which rows came from
which — unlike a read, that cannot be undone except by rebuilding the whole table.
The way out is a rebuild, which replaces every row: `uv run ayl add <folder> --rebuild
--backup <dir>` ...
```

A plain `ayl add <folder>` would hit that same refusal — a rebuild is what gets past it,
and it is one command:

```bash
uv run ayl add ~/books --rebuild --backup ~/ayl-backups --db ~/ayl-index
```

It takes the backup **first** (a failed backup stops the rebuild), drops the transcripts
table, and indexes the folder from scratch. The `books` ledger is kept, so every book
keeps the id it was minted with — re-minting them would turn the whole library into new
books, which is the defect the ledger exists to prevent. Books the ledger holds that this
folder does **not** (another folder's, or the demo corpus's) lose their rows with the
table: they are put back to `requested` and named at the end of the run, so you know to
re-run `ayl add` over their folders too. `--rebuild --force` goes ahead without a backup.

### A cards table is rebuilt on its own

A cards table has its own chunker version (`card-sections-2` since #58, which gave a card built on
your own machine — `card_kind: local` — row keys of its own). A cards table stamped with an older one
reads with a warning, and the warning, the refusal and `--doctor` name the quick way out, which
rebuilds only the cards from the card files and leaves the full text alone:

```bash
uv run scripts/ingest_demo_corpus.py --stage cards
LIBRARY_DB_PATH=~/ayl-tech uv run scripts/ingest_demo_corpus.py --stage cards \
    --cards-dir corpus-tech/cards --cards-dir "${AYL_HOME:-$HOME/AskYourLibrary}/cards/tech"
```

The first is the demo corpus; the second is the engineer's shelf, with its own index.

### Checking before you upgrade

`--doctor` reads every stamp out, agreeing or not, and exits non-zero on a mismatch:

```bash
uv run ayl doctor --db ~/ayl-index
```

```
index /Users/…/ayl-index
ledger: 33 book(s); index (transcripts_ollama, cards_ollama): 33 book key(s)
  stamp: transcripts_ollama: bge-m3 / 1024d, chunker sentence-pack-2, row schema 2, stamped 2026-09-17T05:12:44
  stamp: cards_ollama: bge-m3 / 1024d, chunker card-sections-2, row schema 1, stamped 2026-09-17T05:19:02
  chunks: transcripts_ollama: 11,342 row(s), median 2,287, p95 2,396, longest 2,400 characters (chunker sentence-pack-2 packs to 2,400 and cannot return more than 2,640)
  chunks: cards_ollama: 412 row(s), median 863, p95 1,704, longest 1,988 characters
  no drift: every indexed book has its rows, and every row its book
```

The `chunks:` line is the stamp checked against the rows under it rather than taken on trust
(#75). The ceiling it names is the sentence packer's own arithmetic — the longest chunk it can
return, plus one overlap of slack — and a table holding rows above it is reported as drift and
exits non-zero, because a chunker name that does not describe the rows is the one thing the stamp
exists to prevent:

```
  CHUNK LENGTH        transcripts_ollama holds 6,551 of its 7,285 rows longer than chunker
  'sentence-pack-2' can return — it packs to 2,400 characters and cannot return more than 2,640
  (2,400 plus one 240-character overlap), and the longest here is 10,778. These rows are not
  what that chunker produces. The way out is a rebuild, which replaces every row: …
```

The cards table has no such line: a "## section" with no bullet inside it cannot be split, so a
card chunk is as long as its section and there is no ceiling to check it against. Its distribution
is still printed.

A table stamped with **no chunker** is not a mismatch and never warns. That is every index built
before 0.4.0, and it means "nobody recorded which chunker made these rows" — not "they disagree".
The ledger writes `legacy` for the same absence. If you know which chunker built such an index,
you can say so once and get the checks from then on:

```bash
uv run scripts/ingest_demo_corpus.py --stage stamp-meta --chunker current
```

`--chunker current` claims the version this code chunks at, and that claim is **sampled before it
is written**: the stamp is refused if the longest row is above the ceiling named above, or if a
book holds fewer rows than its prepared text needs chunks. Both bounds are ones a run of this
chunker cannot cross, so an honest index is never refused — the ceiling sits a whole overlap above
the longest chunk the packer can return, and the row floor divides, per chapter, the characters the
packer actually places into chunks (the whitespace between two sentences is in the file and in no
chunk) by the 2,400 that no chunk carries more than. The refusal prints both numbers, names the
books that are short, and writes nothing: neither table is stamped if either one fails.

Naming an **older** version — `--chunker sentence-pack-1` — is an assertion about the past that
nothing here can check, so it is believed as-is; that is the way through for an operator who
really means the old one. Either way it is an assertion, like the embedding model the same command
stamps. Leave it off if you are not sure.

## Backup

```bash
uv run ayl backup ~/ayl-backups --db ~/ayl-index
```

writes `~/ayl-backups/<timestamp>/` holding

- `lancedb/` — the whole index directory: every table, the `books` ledger, the `_index_meta`
  stamps and the BM25 index;
- `chat.db` — the web UI's history, from `AYL_CHAINLIT_DIR`, else `$AYL_HOME/ui/.chainlit/` (or
  a checkout's `.chainlit/` that still holds one, until 0.5.0), or wherever `--chat-db` names. Taken through SQLite's own backup, so it is **one consistent snapshot in one
  file** rather than a main file copied beside somebody else's write-ahead log. Absent if you never
  started the web UI, and the report says so; a file SQLite cannot open is reported and the index
  is still backed up without it;
- `MANIFEST.json` — what was copied, the `_index_meta` rows, the row count per table, the number
  of ledger rows, the version of the code that took it, and a sha256 of every file plus one
  digest over the whole set.

**When a copy is safe.** This is the part a plain `cp -r` cannot give you, and it is the reason
the command exists rather than a line in the README:

1. **No ingest is running.** Both write paths (`ayl add`, the demo corpus's ingest stages) hold an
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

What is **not** backed up: the scratchpads, `$AYL_HOME/scratch/` (the passages as the model saw
them, written per run and not cleaned) and `.env` (a backup of secrets is a second place to lose them from).

## The chat database

The web UI's history has the same two things the index has, for the same reason. The web chat
creates its tables with `CREATE TABLE IF NOT EXISTS`, which by design does nothing to a table
that is already there — so a `chat.db` written by an older release keeps its old columns, looks healthy,
and fails on the first insert naming a column it does not have, in the middle of somebody's
question. At every start the UI now compares the columns its schema declares against the columns
that are actually there and warns, naming them:

```
…/.chainlit/chat.db: the table 'steps' has no column(s) command, defaultOpen, which this
version writes. SQLite leaves an existing table alone, so an older chat database keeps its
old shape and fails on the first insert that names one of them. Move the file aside and let
the UI create a new one (the conversation history in it is lost — back it up first with
`uv run ayl backup <dir>`), or add the column(s) by hand.
```

A warning and not a refusal: the UI works for everything that does not touch the missing column,
and the remedy throws away every past conversation, so it is the reader's decision. The file also
carries a `ayl_schema` row with the chat-schema version, so a database written by a **newer**
release is recognisable as one rather than discovered column by column.

## Restore

```bash
uv run ayl restore ~/ayl-backups/20260917-051244 --db ~/ayl-index          # fresh location
uv run ayl restore ~/ayl-backups/20260917-051244 --db ~/ayl-index --force  # over an index
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
uv run ayl doctor --db ~/ayl-index
```

## The procedure, end to end

```bash
# 1. before pulling: know what you have, and keep it
uv run ayl doctor --db ~/ayl-index
uv run ayl backup ~/ayl-backups --db ~/ayl-index

# 2. upgrade
git pull && uv sync

# 3. what does the new code think of the old index?
uv run ayl doctor --db ~/ayl-index

# 4a. no mismatch: nothing to do. A newer ROW SCHEMA is migrated in place by the next run:
uv run ayl add ~/books --db ~/ayl-index

# 4b. a chunker or embedder mismatch: rebuild, which discards every row it replaces
uv run ayl add ~/books --db ~/ayl-index                       # refused, and it names --rebuild
uv run ayl add ~/books --rebuild --backup ~/ayl-backups --db ~/ayl-index   # copy, drop, re-index
# for the demo corpus, a full rebuild is the repair (it replaces every row):
uv run scripts/ingest_demo_corpus.py --stage ingest

# 5. only now, and only if step 4b succeeded, is the index what the stamp would claim
uv run ayl doctor --db ~/ayl-index

# 6. if the rebuild goes wrong, the backup is the way back
uv run ayl restore ~/ayl-backups/<timestamp> --db ~/ayl-index --force
```

Run steps 4b and 5 from a **script** rather than pasting them into a terminal, so that a failing
line ends the run instead of the next line going ahead on top of it:

```bash
#!/usr/bin/env bash
set -euo pipefail                  # any failing line ends the run

uv run scripts/ingest_demo_corpus.py --stage ingest
uv run ayl doctor --db ~/ayl-index
```

**A failed ingest stops the chain: never stamp after one.** `scripts/ingest_demo_corpus.py --stage ingest`
exits non-zero when it has nothing to ingest — a missing `data/prepared` is the ordinary case, and
it names the directory it looked in — so the `set -euo pipefail` above is what keeps the rest of
the script from running. #75 is what its absence costs: the ingest skipped all 35 books and exited
1, the next line stamped the chunker anyway onto the rows the old one had left, `--doctor` said
"no drift", and an hour of measurement ran on an index that claimed one chunker and held another.
The stamp now samples the rows and would refuse that write — but a chain that runs on after a
failure is the defect, and the refusal is the second line of defence, not the first.

Do not reach for `|| exit 1` when you are pasting the lines into a terminal instead: in an
interactive shell that closes the window. The script above is the version that stops safely.

## See also

- [`docs/add-your-own-books.md`](add-your-own-books.md) — `ayl add` itself, the ledger, `--prune`
- [`docs/known-limits.md`](known-limits.md) — what a rebuild costs, and what the lock does not cover
- [`docs/adr/README.md`](adr/README.md) — ADR-020 (what is stamped and how it is enforced),
  ADR-024 (the ledger and the row schema)
