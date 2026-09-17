"""Reconcile the ledger against the index tables, and report the drift.

Two writes per book that must agree is what ADR-024 accepted when it chose a
ledger, and the failure mode it named is a ledger that no longer describes the
index: a book marked `indexed` whose rows are not there, rows whose `book_id`
no ledger row claims, a key the ledger has never heard of. None of that is
visible from either side alone — the index cannot say what was requested, and
the ledger cannot say what is searchable — so it is checked explicitly rather
than assumed.

This does not repair anything. A repair is a write, the right repair depends on
which side is wrong, and a check that silently rewrites the thing it is
checking is worth nothing as evidence. `ayl-add` re-indexes; `--prune` deletes;
this reports.

The catalogue is deliberately not consulted: it answers from the index tables
(ADR-016), which is one of the two sides being compared here.
"""
import logging
from dataclasses import dataclass, field

from .ledger import INDEXED, TABLE, open_ledger

log = logging.getLogger(__name__)


@dataclass
class LedgerReport:
    """What the ledger and the index disagree about, in the terms a reader can
    act on. Every list holds display strings, not rows: the point of the report
    is what to do next."""
    checked_tables: list[str] = field(default_factory=list)
    books_in_ledger: int = 0
    books_in_index: int = 0
    # A ledger row says `indexed`, and the index holds no row for that id.
    indexed_but_absent: list[str] = field(default_factory=list)
    # A book is in the index and the ledger has no row for its key.
    in_index_but_not_in_ledger: list[str] = field(default_factory=list)
    # Rows whose `book_id` is empty or names no ledger row.
    orphan_row_counts: dict[str, int] = field(default_factory=dict)
    # Requested or failed: asked for, never confirmed indexed.
    never_indexed: list[str] = field(default_factory=list)
    # One key, two minted ids — the shape a pre-ledger correction leaves.
    duplicate_keys: list[str] = field(default_factory=list)
    # The ledger's own row count against the index's, per book.
    row_count_drift: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.indexed_but_absent or self.in_index_but_not_in_ledger
                    or self.orphan_row_counts or self.never_indexed
                    or self.duplicate_keys or self.row_count_drift)

    def lines(self) -> list[str]:
        out = [f"ledger: {self.books_in_ledger} book(s); index "
               f"({', '.join(self.checked_tables) or 'no tables'}): "
               f"{self.books_in_index} book key(s)"]
        for note in self.notes:
            out.append(f"  note: {note}")
        for key in self.indexed_but_absent:
            out.append(f"  INDEXED BUT ABSENT  {key} — the ledger says it is indexed and the "
                       f"index holds no rows for it; re-run ayl-add over its folder")
        for key in self.never_indexed:
            out.append(f"  NEVER INDEXED       {key} — requested, never confirmed; re-run "
                       f"ayl-add over its folder")
        for key in self.in_index_but_not_in_ledger:
            out.append(f"  NOT IN THE LEDGER   {key} — searchable, but nothing records where "
                       f"it came from; the next ayl-add over its folder adopts it")
        for name, count in sorted(self.orphan_row_counts.items()):
            out.append(f"  ORPHAN ROWS         {count} row(s) in {name} carry a book_id no "
                       f"ledger row claims")
        for key in self.duplicate_keys:
            out.append(f"  DUPLICATE KEY       {key} — two minted ids for one book key; the "
                       f"older one's rows are stale")
        for line in self.row_count_drift:
            out.append(f"  ROW COUNT           {line}")
        if self.ok:
            out.append("  no drift: every indexed book has its rows, and every row its book")
        return out


def check_ledger(db, table_names: list[str], ledger_table: str = TABLE) -> LedgerReport:
    """Compare the ledger with the index tables named, and report.

    Reads only the two metadata columns of each table, so the cost is a
    projection over the rows and never the vectors."""
    report = LedgerReport()
    ledger = open_ledger(db, ledger_table)
    names = db.list_tables() if hasattr(db, "list_tables") else db.table_names()
    present = list(getattr(names, "tables", names))
    report.checked_tables = [name for name in table_names if name in present]

    rows_by_id: dict[str, int] = {}
    keys_in_index: set[str] = set()
    for name in report.checked_tables:
        table = db.open_table(name)
        count = table.count_rows()
        if not count:
            continue
        columns = ["book"] + (["book_id"] if "book_id" in table.schema.names else [])
        if "book_id" not in columns:
            report.notes.append(f"{name} has no book_id column yet (an index built before the "
                                f"ledger); the next ayl-add over it adds one")
        for row in table.search().select(columns).limit(count).to_list():
            if row.get("book"):
                keys_in_index.add(row["book"])
            book_id = row.get("book_id") or ""
            rows_by_id[book_id] = rows_by_id.get(book_id, 0) + 1

    ledger_rows = ledger.all_rows()
    report.books_in_ledger = len(ledger_rows)
    report.books_in_index = len(keys_in_index)
    if not ledger.exists():
        report.notes.append("no books ledger in this index yet; the next ingest backfills one")
        return report

    by_id = {row["book_id"]: row for row in ledger_rows}
    seen_keys: dict[str, str] = {}
    for row in sorted(ledger_rows, key=lambda r: r.get("indexed_at") or ""):
        key = row.get("key") or "(no key)"
        if key in seen_keys and seen_keys[key] != row["book_id"]:
            report.duplicate_keys.append(key)
        seen_keys[key] = row["book_id"]
        present_rows = rows_by_id.get(row["book_id"], 0)
        if row.get("status") != INDEXED:
            report.never_indexed.append(f"{key} ({row.get('status')}"
                                        + (f": {row['error']}" if row.get("error") else "") + ")")
        elif not present_rows:
            report.indexed_but_absent.append(key)
        elif int(row.get("rows", 0) or 0) and int(row["rows"]) != present_rows:
            report.row_count_drift.append(
                f"{key}: the ledger says {row['rows']} rows, the index holds {present_rows}")

    for key in sorted(keys_in_index):
        if key not in seen_keys:
            report.in_index_but_not_in_ledger.append(key)

    for book_id, count in rows_by_id.items():
        if book_id and book_id not in by_id:
            report.orphan_row_counts["unknown book_id"] = \
                report.orphan_row_counts.get("unknown book_id", 0) + count
    # Rows with an EMPTY book_id are only an orphan once the table has the
    # column at all: before that every row has one, and the note above says so.
    if "" in rows_by_id and not report.notes:
        report.orphan_row_counts["no book_id"] = rows_by_id[""]
    return report
