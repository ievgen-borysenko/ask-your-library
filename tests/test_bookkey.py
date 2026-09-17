"""`bookkey`: the rules that decide what a book is called, in one place.

The byte-for-byte gate is `tests/test_book_identity_fixtures.py`; this file is
about the rules themselves, including the ones that used to live in four
modules and could only be read by reading all four.
"""
import pytest

from ask_your_library import bookkey
from ask_your_library.bookkey import (TITLE_SEPARATOR, author_of, book_key, names_book,
                                      read_key, read_status, same_chapter, slug,
                                      split_title_author, title_of)


# --- the key ----------------------------------------------------------------

def test_the_key_is_title_separator_author():
    assert book_key("Moby Dick", "Herman Melville") == "Moby Dick — Herman Melville"


def test_a_missing_author_becomes_unknown():
    assert book_key("Moby Dick", "  ") == "Moby Dick — Unknown"


def test_whitespace_is_collapsed_and_control_characters_dropped():
    # The key reaches a terminal, a prompt and a chunk id; nothing downstream
    # strips it a second time.
    # The escape characters go and the payload stays as inert text — the strip
    # is `sanitize.strip_control_chars`, and this pins that the key goes
    # through it (the same expectation as tests/test_add_folder.py).
    assert book_key("Moby\x1b]0;pwned\x07  Dick​", "H‮M") == "Moby]0;pwned Dick — HM"


def test_the_two_halves_come_back_out():
    key = book_key("Moby Dick", "Herman Melville")
    assert title_of(key) == "Moby Dick" and author_of(key) == "Herman Melville"


def test_a_title_containing_the_separator_keeps_it():
    key = book_key("Crime — and Punishment", "Fyodor Dostoevsky")
    assert title_of(key) == "Crime — and Punishment"
    assert author_of(key) == "Fyodor Dostoevsky"


def test_a_key_without_a_separator_has_no_author():
    assert author_of("Moby Dick") == "" and title_of("Moby Dick") == "Moby Dick"


@pytest.mark.parametrize("raw, expected", [
    ("The Green Ledger — A. Keeper", ("The Green Ledger", "A. Keeper")),
    ("The Green Ledger – A. Keeper", ("The Green Ledger", "A. Keeper")),
    ("The Green Ledger -- A. Keeper", ("The Green Ledger", "A. Keeper")),
    ("The Green Ledger - A. Keeper", ("The Green Ledger", "A. Keeper")),
    ("The Green Ledger by A. Keeper", ("The Green Ledger", "A. Keeper")),
    ("The Ledger - Green - A. Keeper", ("The Ledger - Green", "A. Keeper")),
    ("The Green Ledger", None),
])
def test_a_title_line_is_split_on_the_last_separator(raw, expected):
    assert split_title_author(raw) == expected


# --- the row key ------------------------------------------------------------

def test_the_row_key_is_readable_and_unique_per_key():
    key = book_key("Moby Dick", "Herman Melville")
    note = slug(key)
    assert note.startswith("moby-dick-herman-melville-")
    assert len(note.rsplit("-", 1)[1]) == bookkey.SLUG_DIGEST_CHARS


def test_two_keys_with_the_same_ascii_reduction_stay_two_row_keys():
    # The whole reason the digest is there: without it the second add would
    # delete the first book's rows.
    assert slug(book_key("Книга А", "")) != slug(book_key("Книга Б", ""))


def test_the_row_key_of_a_corrected_author_is_a_different_row_key():
    # Not a defect of `slug` — the defect this issue exists for. The key is
    # derived, so identity that must survive a correction is the ledger's
    # `book_id`, not this.
    assert slug(book_key("Moby Dick", "H. Melville")) != slug(book_key("Moby Dick",
                                                                       "Herman Melville"))


# --- the bare-title rules ---------------------------------------------------

def test_a_full_key_and_its_bare_title_both_name_the_book():
    key = book_key("Don Quixote", "Miguel de Cervantes")
    assert names_book(key, key)
    assert names_book("Don Quixote", key)


def test_a_bare_title_never_matches_as_a_prefix():
    assert not names_book("Emma", book_key("Emma's Diary", "Someone"))


def test_a_read_entry_keeps_a_pipe_inside_a_section_name():
    assert read_key("Book|Chapter 1|2") == "Book|Chapter 1|2"
    assert read_status("Book|Chapter 1|2") == "complete"
    assert read_key("Book|Chapter 1|partial") == "Book|Chapter 1"
    assert read_status("Book|Chapter 1|partial") == "partial"


def test_the_same_chapter_asked_for_by_bare_title_is_a_repeat():
    entry = f"Don Quixote{TITLE_SEPARATOR}Miguel de Cervantes|Chapter 3|complete"
    assert same_chapter("Don Quixote|3", entry)
    assert not same_chapter("Don Quixote|4", entry)


def test_two_different_full_keys_are_never_the_same_chapter():
    assert not same_chapter(f"Emma{TITLE_SEPARATOR}Jane Austen|1",
                            f"Emma{TITLE_SEPARATOR}Other Author|1|complete")


def test_after_an_ambiguous_read_only_the_identical_request_is_a_repeat():
    ambiguous = "Emma|1|ambiguous"
    assert same_chapter("Emma|1", ambiguous)
    assert not same_chapter(f"Emma{TITLE_SEPARATOR}Jane Austen|1", ambiguous)


# --- one home, checked ------------------------------------------------------

def test_every_caller_reads_the_key_from_this_module():
    """`library`, `nodes` and `ingest.add_folder` re-export rather than
    redefine — a second definition is how the four copies happened."""
    from ask_your_library import library, nodes
    from ask_your_library.ingest import add_folder

    assert library.title_of is title_of and library.author_of is author_of
    assert library.TITLE_SEPARATOR is TITLE_SEPARATOR
    assert nodes.same_chapter is same_chapter and nodes.read_key is read_key
    assert add_folder.book_key is book_key and add_folder.slug is slug
