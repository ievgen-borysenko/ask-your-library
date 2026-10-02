"""Which books in an index the demo corpus did not build — the one rule the
demo script refuses a rebuild on and `ayl init` calls a demo folder foreign by.

Two signals, and a book either names is foreign; neither stands in for the
other:

- the ROWS: every book key in every transcripts and cards table — staging
  tables included, because `recover_staging` promotes one whose live table is
  gone — against the keys the manifest produces (`bookkey.book_key`,
  the function the ingest mints them with). A table holding rows with no
  book key at all is foreign as a whole;
- the LEDGER: a row whose `source_ref` is not `manifest:<id>` is a book
  `ayl add` indexed.

The ledger is not trusted alone: `Ledger._put` documents that a crash between
its delete and its add leaves table rows with no ledger row, so an empty or
partial `books` table says nothing about what the tables hold. Read, never
written.
"""
from ..index_meta import rows_by_book
from ..sanitize import strip_control_chars
from .ledger import open_ledger
from .publish import table_names

NO_KEY = "(rows with no book key)"


def foreign_books(db, manifest_keys: set[str]) -> list[str]:
    """The books in `db` that are not the demo corpus's, by either signal,
    sorted and printable; empty when every row and every ledger row is."""
    found: set[str] = set()
    for name in table_names(db):
        if not name.startswith(("transcripts_", "cards_")):
            continue
        try:
            table = db.open_table(name)
            keyless = table.count_rows() and "book" not in table.schema.names
            keys = set() if keyless else set(rows_by_book(db, name))
        except Exception:
            # A table that cannot be read cannot be shown to be the demo
            # corpus's: counted as foreign, the safe way round.
            found.add(f"{name} (unreadable)")
            continue
        if keyless:
            found.add(NO_KEY)
            continue
        found |= {key or NO_KEY for key in keys} - set(manifest_keys)
    for row in open_ledger(db).all_rows():
        if not str(row.get("source_ref") or "").startswith("manifest:"):
            found.add(str(row.get("key") or row.get("title") or NO_KEY))
    return sorted(strip_control_chars(book) for book in found)
