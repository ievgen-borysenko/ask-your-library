"""`ayl-add`: chapter detection, book-key rules and the LanceDB write.

No network: the embedder is faked (a deterministic vector per text), the
database is a tmp_path LanceDB.
"""
import lancedb
import pytest

from ask_your_library.index_meta import read_index_meta, vector_dims, write_index_meta
from ask_your_library.ingest import add_folder
from ask_your_library.ingest.chapters import (FRONT_MATTER_SECTION, FULL_TEXT_SECTION,
                                              split_book_chapters, split_book_sections,
                                              split_chapters, unique_titles)

PARA = ("The lighthouse keeper counted the ships that passed the headland. "
        "He wrote each name in a ledger bound in green cloth. ") * 3


class FakeEmbedder:
    """Deterministic 4-dim vectors: no Ollama, no OpenRouter, no network."""
    name = "ollama"
    model = "fake-embed"
    dims = 4

    def __init__(self, model: str = "fake-embed"):
        self.model = model
        self.seen: list[str] = []

    def embed_docs(self, texts):
        self.seen += texts
        return [[float(len(t) % 7), 1.0, 0.5, 0.25] for t in texts]

    def embed_query(self, text):
        return self.embed_docs([text])[0]


@pytest.fixture
def fake_embedder(monkeypatch):
    embedder = FakeEmbedder()
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: embedder)
    return embedder


def write(folder, name, text):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")
    return folder / name


# --- chapter splitting -------------------------------------------------------

def test_markdown_h2_headings_become_sections():
    text = "# The Green Ledger\n\n## One\n\nfirst body\n\n## Two\n\nsecond body\n"
    assert split_book_chapters(text, markdown=True) == [
        ("One", "first body"), ("Two", "second body")]


def test_markdown_h1_headings_split_when_there_is_no_h2():
    text = "# One\n\nfirst body\n\n# Two\n\nsecond body\n"
    assert split_book_chapters(text, markdown=True) == [
        ("One", "first body"), ("Two", "second body")]


def test_markdown_text_before_the_first_heading_is_kept():
    text = "# Title\n\nan opening note\n\n## One\n\nfirst body\n"
    assert split_book_chapters(text, markdown=True) == [
        (FRONT_MATTER_SECTION, "an opening note"), ("One", "first body")]


def test_repeated_markdown_headings_are_disambiguated():
    text = "## One\n\nfirst\n\n## One\n\nsecond\n"
    assert [t for t, _ in split_book_chapters(text, markdown=True)] == ["One", "One (2)"]


def test_plain_text_uses_the_prose_chapter_heuristic():
    text = "CHAPTER I.\n" + PARA + "\nCHAPTER II.\n" + PARA
    assert [t for t, _ in split_book_chapters(text, markdown=False)] == [
        "CHAPTER I.", "CHAPTER II."]


def test_file_without_headings_becomes_one_full_text_section():
    sections = split_book_chapters(PARA, markdown=True)
    assert len(sections) == 1
    assert sections[0][0] == FULL_TEXT_SECTION
    assert sections[0][1] == PARA.strip()


def test_markdown_file_without_headings_still_falls_back_to_prose_headings():
    text = "CHAPTER I.\n" + PARA + "\nCHAPTER II.\n" + PARA
    assert [t for t, _ in split_book_chapters(text, markdown=True)] == [
        "CHAPTER I.", "CHAPTER II."]


# --- nothing is dropped from the user's file ---------------------------------

SHORT = "A short but real first chapter. It is only two sentences long."


def joined_bodies(sections) -> str:
    return "\n".join(body for _, body in sections)


def assert_no_line_lost(text: str, sections, headings=()) -> None:
    """Every non-heading line of the source survives into some section body."""
    joined = joined_bodies(sections)
    for line in text.splitlines():
        line = line.strip()
        if not line or line in headings:
            continue
        assert line in joined, f"line lost from the index: {line!r}"


def test_a_short_chapter_and_the_preamble_both_reach_the_index():
    """The reproduced report: a .txt with a short CHAPTER I and a long
    CHAPTER II indexed only chapter II, and the text before CHAPTER I was
    dropped as well — silently, because one recognised chapter is enough to
    skip the Full text fallback."""
    text = ("A note from the translator about this edition.\n\n"
            "CHAPTER I.\n" + SHORT + "\n\nCHAPTER II.\n" + PARA)
    sections = split_book_chapters(text, markdown=False)
    assert [t for t, _ in sections] == [FRONT_MATTER_SECTION, "CHAPTER I.", "CHAPTER II."]
    assert sections[0][1] == "A note from the translator about this edition."
    assert sections[1][1] == SHORT
    assert_no_line_lost(text, sections, headings=("CHAPTER I.", "CHAPTER II."))


def test_markdown_preamble_is_named_and_nothing_is_lost():
    text = ("# The Green Ledger\n\nan opening note the author wrote\n\n"
            "## One\n\ntiny\n\n## Two\n\n" + PARA)
    sections = split_book_chapters(text, markdown=True)
    assert [t for t, _ in sections] == [FRONT_MATTER_SECTION, "One", "Two"]
    assert_no_line_lost(text, sections,
                        headings=("# The Green Ledger", "## One", "## Two"))


GUTENBERG = ("CONTENTS\nCHAPTER I.\nCHAPTER II.\nCHAPTER III.\n\n"
             "A preface paragraph.\n\n"
             "CHAPTER I.\n" + PARA + "\nCHAPTER II.\n" + PARA +
             "\nCHAPTER III.\n" + PARA)


def test_a_contents_page_does_not_take_the_real_chapters_names():
    """A raw Gutenberg .txt: its contents lines match the same heading regex as
    the chapters. Opening a section per contents line lost nothing, but the
    tiny contents sections took the bare names and unique_titles renamed the
    REAL chapters to "CHAPTER I. (2)" — and read_chapter addresses a chapter by
    (book, section), so drilling into chapter one landed on a one-line contents
    entry. The contents lines are now merged into the section above them."""
    sections = split_book_chapters(GUTENBERG, markdown=False)
    assert [t for t, _ in sections] == [
        FRONT_MATTER_SECTION, "CHAPTER I.", "CHAPTER II.", "CHAPTER III."]
    for _, body in sections[1:]:
        assert body == PARA.strip()                     # the real chapters, intact
    front = sections[0][1]
    for line in ("CONTENTS", "CHAPTER I.", "CHAPTER II.", "CHAPTER III.",
                 "A preface paragraph."):
        assert line in front                            # the contents page, kept
    assert_no_line_lost(GUTENBERG, sections)            # every line, headings included
    assert len({t for t, _ in sections}) == len(sections)


def test_a_short_chapter_is_not_a_contents_line_when_its_title_never_returns():
    """The distinction the merge rests on: a short body alone means nothing. A
    heading is read as a contents line only when the same title reappears later
    in the file; a two-sentence CHAPTER I that never comes back is a chapter."""
    text = "CHAPTER I.\n" + SHORT + "\n\nCHAPTER II.\n" + PARA
    sections, merged = split_book_sections(text, markdown=False)
    assert [t for t, _ in sections] == ["CHAPTER I.", "CHAPTER II."]
    assert sections[0][1] == SHORT
    assert merged == []


def test_the_merge_is_reported_per_heading():
    sections, merged = split_book_sections(GUTENBERG, markdown=False)
    assert [m.title for m in merged] == ["CHAPTER I.", "CHAPTER II.", "CHAPTER III."]
    assert [m.target for m in merged] == [FRONT_MATTER_SECTION] * 3
    assert merged[0].body_chars == 0                     # nothing followed it
    assert merged[-1].body_chars == len("A preface paragraph.")


def test_a_contents_line_before_any_other_text_opens_the_front_matter():
    """No preceding section to merge into: the contents page becomes the front
    matter itself rather than being dropped."""
    text = "CHAPTER I.\nCHAPTER II.\n\nCHAPTER I.\n" + PARA + "\nCHAPTER II.\n" + PARA
    sections = split_book_chapters(text, markdown=False)
    assert [t for t, _ in sections] == [FRONT_MATTER_SECTION, "CHAPTER I.", "CHAPTER II."]
    assert sections[0][1] == "CHAPTER I.\n\nCHAPTER II."


def test_the_demo_detector_keeps_its_contents_filtering():
    """The generic relaxation is opt-in: the demo pipeline's own call keeps
    dropping table-of-contents lines and the contents leftover."""
    text = ("CONTENTS\nCHAPTER I.\nCHAPTER II.\n\nA preface paragraph.\n\n"
            "CHAPTER I.\n" + PARA + "\nCHAPTER II.\n" + PARA)
    chapters = split_chapters(text, r"^CHAPTER [IVX]+\.$")
    assert [t for t, _ in chapters] == ["CHAPTER I.", "CHAPTER II."]
    assert "A preface paragraph." not in joined_bodies(chapters)


def test_a_file_of_pure_prose_is_still_one_full_text_section():
    """The relaxed minimum must not turn the no-headings fallback into an
    untitled Front matter section."""
    sections = split_book_chapters(PARA, markdown=False)
    assert [t for t, _ in sections] == [FULL_TEXT_SECTION]


def test_dry_run_lists_the_sections_it_would_index(tmp_path, capsys):
    write(tmp_path / "books", "Ledger - A. Keeper.txt",
          "An opening note.\n\nCHAPTER I.\n" + SHORT + "\n\nCHAPTER II.\n" + PARA)
    books = add_folder.read_folder(tmp_path / "books")
    assert add_folder.dry_run(books, "ollama", tmp_path / "db") == 0
    printed = capsys.readouterr().out
    for name in (FRONT_MATTER_SECTION, "CHAPTER I.", "CHAPTER II."):
        assert f"- {name}" in printed
    assert "3 sections" in printed
    assert "merged" not in printed          # nothing was merged in this file


def test_dry_run_reports_the_merged_contents_lines(tmp_path, capsys):
    write(tmp_path / "books", "Ledger - A. Keeper.txt", GUTENBERG)
    books = add_folder.read_folder(tmp_path / "books")
    assert add_folder.dry_run(books, "ollama", tmp_path / "db") == 0
    printed = capsys.readouterr().out
    assert "3 short headings merged into their preceding section" in printed
    assert "4 sections" in printed          # front matter + the three real chapters


def test_each_merged_contents_line_is_warned_about(tmp_path, caplog):
    write(tmp_path / "books", "Ledger - A. Keeper.txt", GUTENBERG)
    with caplog.at_level("WARNING"):
        books = add_folder.read_folder(tmp_path / "books")
    assert len(books[0].merged_headings) == 3
    assert caplog.text.count("table-of-contents line") == 3
    assert "'CHAPTER I.'" in caplog.text and f"{FRONT_MATTER_SECTION!r}" in caplog.text


def test_the_run_summary_counts_the_merged_headings(tmp_path, fake_embedder, capsys):
    write(tmp_path / "books", "Ledger - A. Keeper.txt", GUTENBERG)
    code = add_folder.main([str(tmp_path / "books"), "--db", str(tmp_path / "db")])
    assert code == 0
    out = capsys.readouterr().out
    assert "added 1 books, 4 sections" in out
    assert "3 short headings merged into their preceding section" in out


# --- section names are unique within a book ----------------------------------

def test_a_generated_name_never_collides_with_a_name_the_file_already_uses():
    """Counting the ORIGINAL titles only, ["Chapter I", "Chapter I",
    "Chapter I (2)"] produced "Chapter I (2)" twice — and two sections with one
    name are one chapter to read_chapter."""
    titles = ["Chapter I", "Chapter I", "Chapter I (2)"]
    out = [t for t, _ in unique_titles([(t, f"body {i}") for i, t in enumerate(titles)])]
    assert out == ["Chapter I", "Chapter I (2)", "Chapter I (2) (2)"]


def test_emitted_section_names_are_always_unique_and_the_first_keeps_its_name():
    """Property-style over generated lists of colliding titles: whatever the
    input, the emitted names are unique, a title whose name is still free keeps
    it bare, and a renamed section is a suffixed form of its own title."""
    import itertools
    pool = ["Chapter I", "Chapter I (2)", "Chapter I (3)", "Front matter", "One"]
    for length in (3, 4):
        for titles in itertools.product(pool, repeat=length):
            sections = [(t, f"body {i}") for i, t in enumerate(titles)]
            out = [t for t, _ in unique_titles(sections)]
            assert len(set(out)) == len(out), (titles, out)
            emitted: set[str] = set()
            for title, name in zip(titles, out, strict=True):
                if title not in emitted:
                    assert name == title, (titles, out)
                else:
                    assert name.startswith(f"{title} ("), (titles, out)
                emitted.add(name)


def test_two_sections_that_would_have_collided_are_read_as_two_chapters(monkeypatch):
    """Read side: read_chapter addresses a chapter by (book, section), so the
    names ingest emits must resolve one section each. Fake rows, no LanceDB."""
    from ask_your_library import library

    book = "The Green Ledger — A. Keeper"
    sections = unique_titles([("Chapter I", "first body"), ("Chapter I", "second body"),
                              ("Chapter I (2)", "third body")])
    rows = [{"book": book, "section": title, "chunk_id": f"note#{i}.{title}/1", "text": body}
            for i, (title, body) in enumerate(sections, 1)]

    # Stand-ins for lancedb.expr: they keep the literal read_chapter passed and
    # evaluate it against a row in Python, so this fake matches on the VALUES in
    # the filter, not on fragments of a re-rendered SQL string (to_sql() is a
    # lossy debugging rendering; a title with a quote in it would not survive
    # the round trip). What LanceDB makes of the real expression is tested
    # against a real table in test_library.py; here only the section names matter.
    class FakeLit:
        def __init__(self, value):
            self.value = value

    def value_of(operand):
        return operand.value if isinstance(operand, FakeLit) else operand

    class FakePredicate:
        def __init__(self, matches):
            self.matches = matches

        def __and__(self, other):
            return FakePredicate(lambda row: self.matches(row) and other.matches(row))

    class FakeCol:
        def __init__(self, name):
            self.name = name

        def __eq__(self, other):
            return FakePredicate(lambda row: row[self.name] == value_of(other))

        def contains(self, substring):
            return FakePredicate(lambda row: value_of(substring) in row[self.name])

    class FakeTable:
        """Just enough of a LanceDB table for read_chapter's (section, book) filter."""
        def search(self):
            return self

        def where(self, predicate):
            self.predicate = predicate
            return self

        def limit(self, n):
            self.cap = n
            return self

        def to_list(self):
            return [r for r in rows if self.predicate.matches(r)][:self.cap]

    monkeypatch.setattr(library, "col", FakeCol)
    monkeypatch.setattr(library, "lit", FakeLit)
    monkeypatch.setattr(library, "lancedb",
                        type("L", (), {"connect": staticmethod(lambda p: object())})())
    monkeypatch.setattr(library, "has_table", lambda db, name: True)
    monkeypatch.setattr(library, "open_table", lambda db, name: FakeTable())

    read = [library.read_chapter(book, title) for title, _ in sections]
    assert [status for _, _, status in read] == ["found", "found", "found"]
    assert [text for text, _, _ in read] == ["first body", "second body", "third body"]


# --- book key ----------------------------------------------------------------

def read_one(tmp_path, name, text):
    path = write(tmp_path / "books", name, text)
    return add_folder.read_book(path, tmp_path / "books")


def test_key_from_front_matter_wins(tmp_path):
    book = read_one(tmp_path, "whatever.md",
                    "---\ntitle: The Green Ledger\nauthor: A. Keeper\n---\n\n"
                    "Some Other Title by Nobody\n\n" + PARA)
    assert book.book == "The Green Ledger — A. Keeper"


def test_key_from_front_matter_without_author(tmp_path):
    book = read_one(tmp_path, "x.md", "---\ntitle: The Green Ledger\n---\n\n" + PARA)
    assert book.book == "The Green Ledger — Unknown"


def test_key_from_first_line_dash(tmp_path):
    book = read_one(tmp_path, "x.txt", "The Green Ledger — A. Keeper\n\n" + PARA)
    assert book.book == "The Green Ledger — A. Keeper"
    assert "A. Keeper" not in book.sections[0][1]   # the title line leaves the body


def test_key_from_first_line_by(tmp_path):
    book = read_one(tmp_path, "x.md", "# The Green Ledger by A. Keeper\n\n" + PARA)
    assert book.book == "The Green Ledger — A. Keeper"


def test_prose_first_line_is_not_mistaken_for_a_title(tmp_path):
    # "walked by the harbour" must not make "the harbour" an author.
    book = read_one(tmp_path, "Sea Notes - A. Keeper.txt",
                    "He walked by the harbour that morning.\n" + PARA)
    assert book.book == "Sea Notes — A. Keeper"


def test_key_from_filename_with_author(tmp_path):
    book = read_one(tmp_path, "The Green Ledger - A. Keeper.txt", PARA)
    assert book.book == "The Green Ledger — A. Keeper"


def test_key_from_bare_filename_gets_unknown_author(tmp_path):
    book = read_one(tmp_path, "The Green Ledger.txt", PARA)
    assert book.book == "The Green Ledger — Unknown"


def test_two_files_resolving_to_the_same_book_are_refused(tmp_path):
    folder = tmp_path / "books"
    write(folder, "a.md", "---\ntitle: Same\nauthor: Me\n---\n\n" + PARA)
    write(folder, "Same - Me.txt", PARA)
    with pytest.raises(add_folder.IngestError, match="same book"):
        add_folder.read_folder(folder)


def test_hidden_files_are_skipped_and_reported(tmp_path, caplog):
    """Skipping them silently made the docstring and docs/add-your-own-books.md
    ("Skipped, and reported on stderr: hidden files and directories") describe
    something the code did not do: a book under a hidden directory simply never
    appeared. One summary line, not one per file: a hidden directory can hold
    hundreds, and they would bury the per-file warnings."""
    folder = tmp_path / "books"
    write(folder, "Real.txt", PARA)
    write(folder, ".Draft.md", PARA)
    for name in ("Hidden.txt", "Second.txt", "Third.txt", "Fourth.txt"):
        write(folder / ".cache", name, PARA)
    with caplog.at_level("WARNING"):
        found = add_folder.book_files(folder)
    assert [p.name for p in found] == ["Real.txt"]
    assert "5 hidden files skipped" in caplog.text
    assert ".Draft.md" in caplog.text and "and 2 more" in caplog.text


def test_a_hidden_directory_of_other_file_types_is_not_reported(tmp_path, caplog):
    """The count names files that would otherwise have been indexed: a .git
    full of objects is not a report of five hundred skipped books."""
    folder = tmp_path / "books"
    write(folder, "Real.txt", PARA)
    write(folder / ".git", "HEAD", "ref: refs/heads/main\n")
    with caplog.at_level("WARNING"):
        assert [p.name for p in add_folder.book_files(folder)] == ["Real.txt"]
    assert "hidden" not in caplog.text


def test_a_book_key_carries_no_control_or_invisible_characters(tmp_path):
    """The key is cited by the agent, printed by both interfaces and sent to
    the model as a block attribute. A front matter title with an ANSI escape,
    a zero-width space or a bidi override would otherwise be carried, verbatim,
    everywhere the book is named."""
    assert add_folder.book_key("Moby\x1b]0;pwned\x07 Dick\u200b", "H\u202eM") == \
        "Moby]0;pwned Dick — HM"
    folder = tmp_path / "books"
    front = '---\ntitle: "Moby\x1b[2J Dick"\nauthor: "H\ufeffM"\n---\n\n'
    write(folder, "Poisoned.md", front + PARA)
    book = add_folder.read_folder(folder)[0]
    assert book.book == "Moby[2J Dick — HM"
    assert "\x1b" not in book.book and "\ufeff" not in book.book


def test_a_section_title_carries_no_control_or_invisible_characters(tmp_path):
    """The other half of a citation, and the half nothing above the row cleaned:
    front matter goes through `parse_frontmatter` and the key through
    `book_key`, but a chapter heading comes straight out of the file into the
    section field, and from there into the scratchpad, the block header of the
    prompt and the evidence card of the web UI, which escapes HTML and leaves a
    bidi override alone. Every ingest path writes its rows through `rows_for`."""
    folder = tmp_path / "books"
    write(folder, "Poisoned - A Writer.md", f"## Chapter ‮One\x1b]0;pwned\x07\n\n{PARA}")
    chunks = add_folder.chunks_for(add_folder.read_folder(folder)[0])
    rows = add_folder.rows_for(chunks, [[0.0, 1.0, 0.5, 0.25]] * len(chunks))
    assert [r["section"] for r in rows] == ["Chapter One]0;pwned"]
    assert all("\x1b" not in r["section"] and "‮" not in r["section"] for r in rows)


def test_the_log_filter_strips_a_mapping_style_call_too(caplog):
    """The filter runs on the logger, so a warning added later is safe by
    construction — but only the %s tuple was cleaned. logging keeps a lone
    mapping argument as `record.args` itself, so `log.warning("%(book)s ...",
    {"book": key})` walked past the tuple branch and put the escape on screen."""
    with caplog.at_level("WARNING", logger=add_folder.log.name):
        add_folder.log.warning("skipped %(book)s", {"book": "Moby\x1b]0;pwned\x07 Dick\u200b"})
        add_folder.log.warning("skipped %s", "Moby\x1b[2J Dick")
    assert caplog.messages == ["skipped Moby]0;pwned Dick", "skipped Moby[2J Dick"]


def test_symlink_pointing_outside_the_folder_is_skipped(tmp_path, caplog):
    # is_file() follows symlinks: without the check, this file's text would be
    # read and sent to the embedding backend.
    folder = tmp_path / "books"
    write(folder, "Real.txt", PARA)
    outside = write(tmp_path / "private", "secret.md", "SSH KEY MATERIAL\n" + PARA)
    (folder / "secret.md").symlink_to(outside)

    with caplog.at_level("WARNING"):
        found = add_folder.book_files(folder)
    assert [p.name for p in found] == ["Real.txt"]
    assert "symlink" in caplog.text

    books = add_folder.read_folder(folder)
    assert [b.path.name for b in books] == ["Real.txt"]


def test_symlink_pointing_inside_the_folder_is_also_skipped(tmp_path):
    # Policy: every symlink is skipped, in or out — a link inside the folder is
    # either a duplicate of a file already indexed or a retarget waiting to
    # happen. Copy the file in to index it.
    folder = tmp_path / "books"
    real = write(folder, "Real.txt", PARA)
    (folder / "Alias.txt").symlink_to(real)
    assert [p.name for p in add_folder.book_files(folder)] == ["Real.txt"]


def test_file_under_a_symlinked_directory_is_skipped(tmp_path):
    folder = tmp_path / "books"
    write(folder, "Real.txt", PARA)
    write(tmp_path / "elsewhere", "Other.txt", PARA)
    (folder / "linked").symlink_to(tmp_path / "elsewhere", target_is_directory=True)
    assert [p.name for p in add_folder.book_files(folder)] == ["Real.txt"]


def test_a_non_utf8_file_is_skipped_not_fatal(tmp_path, caplog):
    # Consistency with every other unreadable file (hidden, symlink, empty): one
    # stray latin-1 or binary file must not abort a folder of good books.
    folder = tmp_path / "books"
    write(folder, "Real.txt", PARA)
    (folder / "Broken.txt").write_bytes(b"\xff\xfe not utf-8 at all \x00\x80")

    with caplog.at_level("WARNING"):
        books = add_folder.read_folder(folder)
    assert [b.path.name for b in books] == ["Real.txt"]
    assert "not UTF-8" in caplog.text and "Broken.txt" in caplog.text


def test_a_folder_of_only_unreadable_files_is_one_error_line(tmp_path):
    folder = tmp_path / "books"
    (folder).mkdir(parents=True)
    (folder / "Broken.txt").write_bytes(b"\xff\xfe\x00\x80")
    with pytest.raises(add_folder.IngestError, match="no readable text"):
        add_folder.read_folder(folder)


# --- chunk ids ---------------------------------------------------------------

def test_the_front_matter_and_a_heading_of_the_same_name_get_distinct_ids(tmp_path):
    # "# Title" then prose (the front matter), then a chapter literally called
    # "Front matter": the section name is not a sentinel, so the heading is
    # renamed rather than merged, and the section ordinal keeps the ids apart
    # even before that.
    book = read_one(tmp_path, "x.md",
                    "# The Green Ledger\n\n" + PARA + "\n\n## Front matter\n\n" + PARA)
    titles = [t for t, _ in book.sections]
    assert titles == [FRONT_MATTER_SECTION, f"{FRONT_MATTER_SECTION} (2)"]
    chunks = add_folder.chunks_for(book)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    assert len({c.section for c in chunks}) == 2


def test_chunk_id_still_ends_with_the_position_in_the_section(tmp_path):
    # library.join_chapter orders a chapter by int(chunk_id.rsplit("/", 1)[1]).
    book = read_one(tmp_path, "x.md", "## One\n\n" + PARA * 30)
    positions = [int(c.chunk_id.rsplit("/", 1)[1]) for c in add_folder.chunks_for(book)]
    assert positions == list(range(1, len(positions) + 1))
    assert len(positions) > 1               # the text really was split


# --- writing the index -------------------------------------------------------

def make_folder(tmp_path):
    folder = tmp_path / "books"
    write(folder, "The Green Ledger - A. Keeper.md",
          "# The Green Ledger\n\n## One\n\n" + PARA + "\n\n## Two\n\n" + PARA)
    write(folder, "Sea Notes - B. Mate.txt", PARA)
    return folder


def test_add_writes_a_stamped_transcripts_table(tmp_path, fake_embedder):
    counts = add_folder.add_books(add_folder.read_folder(make_folder(tmp_path)),
                                  "ollama", tmp_path / "db")
    db = lancedb.connect(tmp_path / "db")
    table = db.open_table("transcripts_ollama")
    assert counts["books"] == 2 and counts["sections"] == 3
    assert counts["chunks"] == table.count_rows()
    rows = table.search().limit(100).to_list()
    assert {r["book"] for r in rows} == {"The Green Ledger — A. Keeper", "Sea Notes — B. Mate"}
    assert {r["section"] for r in rows} == {"One", "Two", FULL_TEXT_SECTION}
    meta = read_index_meta(db, "transcripts_ollama")
    assert meta["model"] == "fake-embed" and meta["dims"] == 4


def test_re_adding_replaces_a_books_rows(tmp_path, fake_embedder):
    folder = make_folder(tmp_path)
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")
    before = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama").count_rows()

    # same book, much longer text (past the chunk target): rows are replaced,
    # never appended, and the other book is untouched
    (folder / "Sea Notes - B. Mate.txt").write_text(PARA * 20, encoding="utf-8")
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    table = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama")
    rows = table.search().limit(1000).to_list()
    ids = [r["chunk_id"] for r in rows]
    assert len(ids) == len(set(ids)), "re-adding duplicated rows"
    assert table.count_rows() > before   # only because the text really grew
    ledger = [r for r in rows if r["book"].startswith("The Green Ledger")]
    assert len(ledger) == len([r for r in rows if r["note"] == ledger[0]["note"]])
    # the merged rebuild carries the untouched book over in Arrow: its schema,
    # and with it the fixed-size vector column, must survive the round trip
    assert vector_dims(table) == 4


def test_adding_with_another_embedding_model_is_refused(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder("model-a"))
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: FakeEmbedder("model-b"))
    with pytest.raises(add_folder.IngestError, match="model-a"):
        add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    # nothing was written by the refused run
    db = lancedb.connect(tmp_path / "db")
    assert read_index_meta(db, "transcripts_ollama")["model"] == "model-a"


def test_mismatch_is_refused_before_any_embedding_call(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama",
                    [{"chunk_id": "x", "note": "n", "book": "b", "source": "s",
                      "section": "", "text": "t", "vector": [0.0] * 4}])
    write_index_meta(db, "transcripts_ollama", "ollama", "model-a", 4)

    embedder = FakeEmbedder("model-b")
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: embedder)
    with pytest.raises(add_folder.IngestError):
        add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")
    assert embedder.seen == []


def test_unstamped_table_is_refused_even_when_the_dims_match(tmp_path, monkeypatch):
    # Same dims prove nothing about the model: writing into an unstamped table
    # would mix two embedding models and then stamp the whole table.
    folder = make_folder(tmp_path)
    db = lancedb.connect(tmp_path / "db")
    db.create_table("transcripts_ollama",
                    [{"chunk_id": "x", "note": "n", "book": "b", "source": "s",
                      "section": "", "text": "t", "vector": [0.0] * 4}])

    embedder = FakeEmbedder("fake-embed")
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: embedder)
    with pytest.raises(add_folder.IngestError, match="no embedding fingerprint") as raised:
        add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")
    assert embedder.seen == []                       # refused before any embedding call
    assert "stamp-meta" in str(raised.value)         # and it says how to fix it
    assert db.open_table("transcripts_ollama").count_rows() == 1


def test_slugs_that_collide_on_ascii_keep_both_books(tmp_path, fake_embedder):
    # "Книга А" and "Книга Б" both reduce to the ASCII slug "book"; without the
    # key digest the second add would delete the first book's rows.
    first = tmp_path / "a"
    write(first, "one.md", "---\ntitle: Книга А\nauthor: Автор\n---\n\n" + PARA)
    second = tmp_path / "b"
    write(second, "two.md", "---\ntitle: Книга Б\nauthor: Автор\n---\n\n" + PARA)

    add_folder.add_books(add_folder.read_folder(first), "ollama", tmp_path / "db")
    add_folder.add_books(add_folder.read_folder(second), "ollama", tmp_path / "db")

    rows = lancedb.connect(tmp_path / "db").open_table(
        "transcripts_ollama").search().limit(1000).to_list()
    assert {r["book"] for r in rows} == {"Книга А — Автор", "Книга Б — Автор"}
    assert len({r["note"] for r in rows}) == 2
    ids = [r["chunk_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_a_failed_embedding_batch_leaves_the_index_untouched(tmp_path, monkeypatch):
    folder = make_folder(tmp_path)
    good = FakeEmbedder()
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: good)
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    db = lancedb.connect(tmp_path / "db")
    before_rows = db.open_table("transcripts_ollama").search().limit(1000).to_list()

    class DiesOnSecondBook(FakeEmbedder):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def embed_docs(self, texts):
            self.calls += 1
            if self.calls > 1:
                raise RuntimeError("embedding backend died mid-run")
            return super().embed_docs(texts)

    # the books really changed, so a partial write would be visible
    (folder / "Sea Notes - B. Mate.txt").write_text(PARA * 20, encoding="utf-8")
    monkeypatch.setattr(add_folder, "get_embedder", lambda backend: DiesOnSecondBook())
    with pytest.raises(RuntimeError, match="died mid-run"):
        add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    db = lancedb.connect(tmp_path / "db")
    assert "transcripts_ollama__staging" not in db.table_names()
    table = db.open_table("transcripts_ollama")
    after_rows = table.search().limit(1000).to_list()
    assert sorted(r["chunk_id"] for r in after_rows) == sorted(r["chunk_id"] for r in before_rows)
    assert sorted(r["text"] for r in after_rows) == sorted(r["text"] for r in before_rows)
    # the fingerprint and the FTS index survived too
    assert read_index_meta(db, "transcripts_ollama")["model"] == "fake-embed"
    assert table.search("lighthouse", query_type="fts").limit(1).to_list()


def test_the_existing_index_is_read_in_batches_not_all_at_once(tmp_path, fake_embedder,
                                                               monkeypatch):
    # The kept rows must never be materialized as one Arrow table: the memory
    # cost of adding one book would then grow with the whole library.
    folder = make_folder(tmp_path)
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    def no_to_arrow(self, *args, **kwargs):
        raise AssertionError("the live table was materialized with to_arrow()")

    monkeypatch.setattr(lancedb.table.LanceTable, "to_arrow", no_to_arrow)

    batch_sizes = []
    real_batches = add_folder.table_batches

    def tiny_batches(table, batch_rows):
        for batch in real_batches(table, 2):          # two rows at a time
            batch_sizes.append(batch.num_rows)
            yield batch

    monkeypatch.setattr(add_folder, "table_batches", tiny_batches)

    (folder / "Sea Notes - B. Mate.txt").write_text(PARA * 4, encoding="utf-8")
    add_folder.add_books(add_folder.read_folder(folder), "ollama", tmp_path / "db")

    assert len(batch_sizes) > 1 and max(batch_sizes) <= 2   # really streamed
    table = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama")
    assert vector_dims(table) == 4                   # schema survived the batch round trip
    rows = table.search().limit(1000).to_list()
    assert {r["book"] for r in rows} == {"The Green Ledger — A. Keeper", "Sea Notes — B. Mate"}
    ids = [r["chunk_id"] for r in rows]
    assert len(ids) == len(set(ids))


def test_a_run_that_produces_no_chunks_is_one_line_not_a_traceback(tmp_path, fake_embedder,
                                                                   monkeypatch, capsys):
    # publish.rebuild_table raises when the batches yield nothing, and main()
    # only catches IngestError — so without the conversion the user gets a
    # traceback. split_book_chapters always produces a section today, so the
    # empty book is forced here; the contract ("one readable line, never a
    # traceback") is what the test pins.
    monkeypatch.setattr(add_folder, "chunks_for", lambda book: [])
    code = add_folder.main([str(make_folder(tmp_path)), "--db", str(tmp_path / "db")])
    err = capsys.readouterr().err
    assert code == 1
    assert "nothing to index" in err and "Traceback" not in err
    assert "transcripts_ollama" not in lancedb.connect(tmp_path / "db").table_names()


def test_a_book_that_chunks_to_nothing_is_skipped_not_embedded(tmp_path, fake_embedder,
                                                               monkeypatch):
    real_chunks_for = add_folder.chunks_for
    monkeypatch.setattr(add_folder, "chunks_for",
                        lambda book: [] if book.book.startswith("Sea Notes")
                        else real_chunks_for(book))

    counts = add_folder.add_books(add_folder.read_folder(make_folder(tmp_path)),
                                  "ollama", tmp_path / "db")
    assert counts["books"] == 1                       # the hollow one was skipped
    table = lancedb.connect(tmp_path / "db").open_table("transcripts_ollama")
    assert counts["chunks"] == table.count_rows()     # and its counts stayed honest
    rows = table.search().limit(1000).to_list()
    assert {r["book"] for r in rows} == {"The Green Ledger — A. Keeper"}


# --- CLI ---------------------------------------------------------------------

def test_cards_flag_is_refused_with_an_explanation(tmp_path, capsys):
    assert add_folder.main([str(make_folder(tmp_path)), "--cards"]) == 2
    assert "not implemented" in capsys.readouterr().err


def test_dry_run_writes_nothing(tmp_path, capsys):
    folder = make_folder(tmp_path)
    assert add_folder.main([str(folder), "--db", str(tmp_path / "db"), "--dry-run"]) == 0
    assert not (tmp_path / "db").exists()
    assert "would index 2 books" in capsys.readouterr().out


def test_missing_folder_is_reported(tmp_path, capsys):
    assert add_folder.main([str(tmp_path / "nope")]) == 2
    assert "not a folder" in capsys.readouterr().err


def test_empty_folder_is_reported(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert add_folder.main([str(tmp_path / "empty")]) == 1
    assert "no .txt or .md files" in capsys.readouterr().err


def test_main_reports_books_sections_chunks_table_and_model(tmp_path, fake_embedder, capsys):
    code = add_folder.main([str(make_folder(tmp_path)), "--db", str(tmp_path / "db")])
    out = capsys.readouterr().out
    assert code == 0
    assert "added 2 books, 3 sections" in out
    assert "table transcripts_ollama" in out and "fake-embed" in out
    assert "no cards_ollama table" in out


def test_a_heading_with_nothing_under_it_keeps_a_section(tmp_path):
    """The last heading of a file (or an empty chapter) is part of the file:
    it keeps a section whose text is the heading line (review of #52)."""
    from ask_your_library.ingest.chapters import split_book_sections

    prose = "CHAPTER I.\n\n" + "Real text. " * 40 + "\n\nCHAPTER II.\n"
    sections, _ = split_book_sections(prose, markdown=False)
    assert [t for t, _ in sections] == ["CHAPTER I.", "CHAPTER II."]
    assert sections[-1][1] == "CHAPTER II."
    md = "# One\n\nbody\n\n# Two\n"
    sections, _ = split_book_sections(md, markdown=True)
    assert [t for t, _ in sections] == ["One", "Two"] and sections[-1][1] == "Two"


def test_merge_report_names_the_target_by_its_final_unique_name():
    """A contents line merged into a section that unique_titles later renames
    is reported under the renamed section (review of #52)."""
    from ask_your_library.ingest.chapters import split_book_sections

    long = "Real chapter text. " * 15
    prose = ("CHAPTER I.\n" + long + "\n\nCHAPTER I.\n" + long + "\n\nCHAPTER II.\ncontents line\n\nCHAPTER II.\n" + long)
    sections, merged = split_book_sections(prose, markdown=False)
    titles = [t for t, _ in sections]
    assert titles == ["CHAPTER I.", "CHAPTER I. (2)", "CHAPTER II."]
    assert [m.target for m in merged] == ["CHAPTER I. (2)"]
