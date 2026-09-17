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
    # A book is in the FULL-TEXT table and the ledger has no row for its key.
    in_index_but_not_in_ledger: list[str] = field(default_factory=list)
    # A key that only the cards table holds, with no ledger row: a card whose
    # book was pruned, or one whose heading does not match its book's key.
    cards_without_a_book: list[str] = field(default_factory=list)
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
                    or self.duplicate_keys or self.row_count_drift
                    or self.cards_without_a_book)

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
        for key in self.cards_without_a_book:
            out.append(f"  CARD WITHOUT A BOOK {key} — only the cards table holds this key, and "
                       f"no ledger row does. Either --prune removed the book and left its card "
                       f"(ayl-add never writes the cards table), or the card's heading differs "
                       f"from its book's key. The catalogue lists it as a book with no text; "
                       f"delete the card, or fix its heading to match the book")
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

    # Per table, not merged: only the transcripts table ever carries `book_id`
    # (see the cards note below), and merging the two made the orphan check
    # below unreachable — every index looked clean because the cards rows
    # always supplied a missing column.
    rows_by_id: dict[str, int] = {}
    keys_in_index: set[str] = set()
    rows_without_id = 0
    id_column_missing: list[str] = []
    card_keys: set[str] = set()
    text_keys: set[str] = set()
    for name in report.checked_tables:
        table = db.open_table(name)
        count = table.count_rows()
        if not count:
            continue
        is_cards = name.startswith("cards")
        has_id = "book_id" in table.schema.names
        if not has_id and not is_cards:
            id_column_missing.append(name)
        columns = ["book"] + (["book_id"] if has_id else [])
        for row in table.search().select(columns).limit(count).to_list():
            key = row.get("book")
            if key:
                keys_in_index.add(key)
                (card_keys if is_cards else text_keys).add(key)
            if is_cards:
                continue                # a card is not a book: see the note below
            book_id = row.get("book_id") or ""
            if book_id:
                rows_by_id[book_id] = rows_by_id.get(book_id, 0) + 1
            elif has_id:
                rows_without_id += 1

    for name in id_column_missing:
        report.notes.append(f"{name} has no book_id column yet (an index built before the "
                            f"ledger); the next ayl-add over this index adds one")
    if card_keys:
        # Stated rather than assumed: the ledger's unit is the book, a card is a
        # distillate of one, and no card row carries a book_id. The two tables
        # are joined by the book key STRING alone, which is why a card whose
        # heading differs by one character is two books in the catalogue.
        unmatched = sorted(card_keys - text_keys)
        report.notes.append(
            f"cards are matched to books by their key string, not by book_id "
            f"({len(card_keys)} card key(s)"
            + (f", {len(unmatched)} with no full-text book of the same key: "
               f"{', '.join(unmatched[:3])}" if unmatched else ", all with a full-text book")
            + ")")

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
        if key in seen_keys:
            continue
        # Which table holds it decides what the reader should do about it, and
        # the two hints are opposite: a full-text book with no ledger row is
        # adopted by the next run over its folder, while a card is something no
        # `ayl-add` will ever touch.
        if key in text_keys:
            report.in_index_but_not_in_ledger.append(key)
        else:
            report.cards_without_a_book.append(key)

    for book_id, count in rows_by_id.items():
        if book_id not in by_id:
            report.orphan_row_counts["unknown book_id"] = \
                report.orphan_row_counts.get("unknown book_id", 0) + count
    # A row with an EMPTY book_id in a table that HAS the column: the migration
    # filled it from the ledger and found nothing for this row's `note`.
    if rows_without_id:
        report.orphan_row_counts["no book_id"] = rows_without_id
    return report
