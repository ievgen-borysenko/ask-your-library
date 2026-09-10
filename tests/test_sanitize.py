"""The control-character contract, and the line breaks it must leave alone.

Two expressions share this ground: `strip_control_chars` deletes what is never
text, `LINE_BREAK_RE` maps what is text but has to travel as something else — a
space in a block header or a normalized quote, an LF on the way to a terminal, a
<br> inside an HTML block. They used to overlap on CR, the vertical tab and the
form feed, and where they composed the delete won, so a break became nothing at
all and the words around it were joined.
"""
from ask_your_library import nodes
from ask_your_library.cli import terminal_safe
from ask_your_library.ingest.add_folder import terminal_safe as ingest_terminal_safe
from ask_your_library.llm import data_block
from ask_your_library.provenance import _normalize
from ask_your_library.sanitize import strip_control_chars

BREAKS = ("\r", "\r\n", "\n", "\x0b", "\x0c", "\x85", " ", " ")
OSC = "\x1b]0;pwned\x07"


def test_a_line_break_is_text_and_survives_the_strip():
    """Deleting a break joins the words around it: the passage "alpha\\rbeta"
    read "alphabeta", so the honest quote "alpha beta" was reported broken while
    the joined spelling was confirmed."""
    for br in BREAKS:
        assert strip_control_chars(f"alpha{br}beta") == f"alpha{br}beta"
    assert strip_control_chars("alpha\tbeta") == "alpha\tbeta"
    # what is not text still goes, whole classes of it
    assert strip_control_chars(f"alpha{OSC}beta\x00\x1f\x7f") == "alpha]0;pwnedbeta"
    assert strip_control_chars("a​b‮c﻿") == "abc"


def test_the_stripped_set_is_exactly_the_characters_the_comment_names():
    """The class names one block per line, so what it matches is written out
    here code point by code point: a rewrite that widened or narrowed it by a
    single character fails this. The sweep is the whole of Unicode, not a
    sample, because a range is exactly the thing that reaches further than it
    reads."""
    named = ({*range(0x00, 0x09), *range(0x0e, 0x20), 0x7f}     # C0 controls, minus tab
             | {0x200b, 0x200c, 0x200d}                         # zero-width space, joiners
             | {0x200e, 0x200f}                                 # the LTR and RTL marks
             | {0x202a, 0x202b, 0x202c, 0x202d, 0x202e}         # bidi embeddings, pop, overrides
             | {0x2066, 0x2067, 0x2068, 0x2069}                 # bidi isolates and their pop
             | {0xfeff})                                        # BOM
    assert {cp for cp in range(0x110000) if strip_control_chars(chr(cp)) == ""} == named


def test_a_break_inside_a_quote_normalizes_to_a_space():
    """The quote check compares word sequences, so every break form and the tab
    are separators there — the same reading of the text on both sides."""
    for br in BREAKS + ("\t",):
        assert _normalize(f"alpha{br}beta") == "alpha beta"
    assert _normalize("alpha\rbeta") != _normalize("alphabeta")


def test_an_honest_quote_across_a_carriage_return_is_confirmed():
    """A book stored with CR line endings used to lose them in the strip: the
    passage the check ran against held one word where the model had read two."""
    book = "Moby Dick — Herman Melville"
    hits_log = [{"hit_id": "s1h1", "text": "Call me Ishmael\rSome years ago."}]

    def status(quote: str) -> str:
        return nodes.validate({"answer": book, "hits_log": hits_log,
                               "evidence": [{"hit_id": "s1h1", "book": book,
                                             "section": "Chapter 1", "quote": quote}]}
                              )["provenance"]["items"][0]["status"]

    assert status("Ishmael Some years ago.") == "confirmed"
    assert status("IshmaelSome years ago.") == "broken"      # the joined spelling is not the text


def test_a_break_in_a_title_becomes_a_space_in_the_block_header():
    """A block header is one line by construction. With CR deleted before the
    mapping ran, "Moby\\rDick" reached the model as "MobyDick"."""
    for br in BREAKS:
        header = data_block("result", "x", hit_id="s1h1", book=f"Moby{br}Dick").split("\n", 1)[0]
        assert 'book="Moby Dick"' in header


def test_both_ingest_and_agent_clis_print_every_break_as_a_plain_newline():
    """A bare CR puts the cursor back at the start of the line just printed and
    lets what follows overwrite it — a repaint without a single escape."""
    for safe in (terminal_safe, ingest_terminal_safe):
        assert safe("a\rb") == "a\nb"
        assert safe("a\r\nb") == "a\nb"          # CRLF is one break, not two
        assert safe("a\x0bb\x85c d") == "a\nb\nc\nd"
        assert safe(f"a{OSC}b") == "a]0;pwnedb"


def test_a_poisoned_book_and_section_never_reach_the_scratchpad(tmp_path, monkeypatch):
    """The two names travel with the passage everywhere it goes, and the
    scratchpad is read with `cat`: a bidi override reverses the citation line it
    sits in, an OSC sequence retitles the terminal reading the file. Only the
    passage text was stripped, and the heading a section title comes from is not
    stripped at ingest either (in an index built before this release)."""
    book, section = f"Moby Dick{OSC} — Herman Melville", "Chapter ‮One"
    monkeypatch.setattr(nodes, "read_chapter",
                        lambda b, s, max_chars=12000: ("Call me Ishmael.", book, "found"))
    scratchpad = tmp_path / "scratch.md"
    scratchpad.write_text("", encoding="utf-8")
    acted = nodes.act({"current_query": f"__chapter__|{book}|{section}", "steps_taken": 0,
                       "read_chapters": [], "scratchpad_path": str(scratchpad)})

    hit = acted["hits"][0]
    assert hit["book"] == "Moby Dick]0;pwned — Herman Melville"
    assert hit["section"] == "Chapter One"
    assert acted["hits_log"][0]["book"] == hit["book"]
    written = scratchpad.read_text(encoding="utf-8")
    for char in ("\x1b", "\x07", "‮"):
        assert char not in written
    assert f"{hit['book']} | {hit['section']} |" in written


def test_the_query_and_the_read_note_are_stripped_on_their_way_to_the_scratchpad(tmp_path):
    """The step header is the query reflect wrote and the note names the chapter
    it asked for: model output shaped by the corpus, in the same file."""
    scratchpad = tmp_path / "scratch.md"
    scratchpad.write_text("", encoding="utf-8")
    nodes.act({"current_query": f"__chapter__|Nowhere{OSC}", "steps_taken": 0,
               "read_chapters": [], "scratchpad_path": str(scratchpad)})
    written = scratchpad.read_text(encoding="utf-8")
    assert "\x1b" not in written and "\x07" not in written and "]0;pwned" in written
