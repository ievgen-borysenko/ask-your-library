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
| **The chunker** (what a chunk *is*) | a full rebuild: every row is re-chunked and re-embedded | `_index_meta.chunker` differs from this code's — **warned** on every read, **refused** on the next write |
| **The row schema** (what a row *holds*) | usually nothing: `ayl-add` migrates the table in place, re-embedding no row | nothing to see. A *newer* schema than this code knows is warned and refused, which means you downgraded |
| **The embedding model or its width** | a full rebuild: a query vector from one model against document vectors from another is not a search | **fatal on read** — the CLI and the web UI refuse to start against it |

The three are enforced differently on purpose. A wrong embedder makes retrieval meaningless with
nothing to see, so nothing may read the index. A wrong chunker makes it *worse*, not meaningless —
the same text, cut differently, still retrieves and still quotes verbatim — so a read is allowed
and a write is not: one `ayl-add` into such a table leaves two chunkers' rows in it with nothing
to tell them apart, and the only repair after that is rebuilding all of it. That is the whole
policy, in one line each: **warn on read, refuse on write** ([ADR-020](adr/README.md)).

### What the warning looks like

Once per table per process, in the log, and as a startup notice in the CLI and the web UI:

```
transcripts_ollama was built by chunker 'sentence-pack-1', this code chunks as
'sentence-pack-2'. The index still answers, from the chunks it already holds. Back the
index up first (`uv run ayl-add --backup <dir>`), then rebuild it: `uv run ayl-add
<folder>` for your own books, or `uv run scripts/ingest_demo_corpus.py --stage ingest`
for the demo corpus.
```

### What the refusal looks like

`ayl-add` stops before it embeds or deletes anything, so a refused run leaves the index exactly as
it was:

```
refusing to write transcripts_ollama: transcripts_ollama was built by chunker
'sentence-pack-1', this code chunks as 'sentence-pack-2'. A write would leave one table
holding rows from two chunkers, and nothing afterwards can tell which rows came from
which — unlike a read, that cannot be undone except by rebuilding the whole table.
Back the index up first (`uv run ayl-add --backup <dir>`), then rebuild it: ...
```

### Checking before you upgrade

`--doctor` reads every stamp out, agreeing or not, and exits non-zero on a mismatch:

```bash
uv run ayl-add --doctor --db ~/ayl-index
```

```
index /Users/…/ayl-index
ledger: 33 book(s); index (transcripts_ollama, cards_ollama): 33 book key(s)
  stamp: transcripts_ollama: bge-m3 / 1024d, chunker sentence-pack-1, row schema 2, stamped 2026-09-17T05:12:44
  stamp: cards_ollama: bge-m3 / 1024d, chunker sentence-pack-1, row schema 1, stamped 2026-09-17T05:19:02
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
- `chat.db` (and its `-wal` / `-shm` sidecars, when present) — the web UI's history, from
  `AYL_CHAINLIT_DIR` or `.chainlit/`, or wherever `--chat-db` names. Absent if you never started
  the web UI, and the report says so;
- `MANIFEST.json` — what was copied, the `_index_meta` rows, the row count per table, the number
  of ledger rows, the version of the code that took it, and a sha256 of every file plus one
  digest over the whole set.

**When a copy is safe.** This is the part a plain `cp -r` cannot give you, and it is the reason
the command exists rather than a line in the README:

1. **No ingest is running.** Both write paths (`ayl-add`, the demo corpus's ingest stages) hold a
   lock file inside the index directory for the length of a run, and `--backup` takes the same
   lock. A backup started while an ingest is writing is refused, naming the command and pid that
   holds it; an ingest started while a backup is being taken is refused the same way. A lock left
   behind by a crash is taken over automatically — it records the pid, and a pid that is not
   running on this machine is not a lock.
2. **No staged rebuild is half-finished.** LanceDB has no rename, so replacing a table goes
   through a staging copy, and there is a moment with the live table dropped and the staged one
   not yet promoted. A copy taken there restores to an index with a table missing. `--backup`
   finishes or discards any such rebuild before it copies, and the manifest records that it did.
3. **Nothing rotted since.** `--restore` recomputes every digest before it touches anything.

What is **not** backed up: `.scratch/` (the passages as the model saw them, written per run and
not cleaned) and `.env` (a backup of secrets is a second place to lose them from).

## Restore

```bash
uv run ayl-add --restore ~/ayl-backups/20260917-051244 --db ~/ayl-index          # fresh location
uv run ayl-add --restore ~/ayl-backups/20260917-051244 --db ~/ayl-index --force  # over an index
```

The backup is verified against its manifest first, every time. Three things are refused, and
`--force` overrides exactly one of them:

- a backup that no longer matches its manifest — **nothing is touched**, and no flag makes
  overwriting a working index with a corrupt copy safe;
- an index already at `--db` — this is what `--force` is for;
- an ingest in flight on the index being replaced.

The index that `--force` replaces is **moved aside, not deleted**: it stays as
`<index>.replaced-<timestamp>` and the report names it. Delete it yourself once you are satisfied.
The chat database is restored only when the target is absent or `--force` is given, and it is
restored owner-readable only, as the web UI keeps it.

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
uv run ayl-add ~/books --db ~/ayl-index      # refuses until the table is gone or rebuilt whole
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
