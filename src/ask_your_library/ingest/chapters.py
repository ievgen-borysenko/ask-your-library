"""Chapter detection: text -> [(section title, body)].

One implementation for every ingest path, so the demo corpus and a folder of
your own books are cut into sections the same way. Two detectors:

- `split_chapters` — whole-line headings for plain prose ("CHAPTER IV.",
  "STAVE ONE", "LETTER 3"), with optional part-awareness for editions that
  restart numbering per part. This is the demo corpus's detector, moved here
  from scripts/ingest_demo_corpus.py.
- `split_markdown_chapters` — "#" / "##" headings for Markdown files.

`split_book_sections` is the dispatcher used by the generic folder ingest
(`split_book_chapters` is the same call without its merge report):
Markdown headings first, then the prose heuristic, then a single
`FULL_TEXT_SECTION` fallback so a file without any detectable structure is
still one readable section instead of an error.

The two paths differ deliberately. The demo corpus is a curated set of Project
Gutenberg files whose table-of-contents pages match the same heading regex as
real chapters, so its detector drops short bodies (`MIN_CHAPTER_CHARS`) and the
residual contents leftovers. The generic path (`ayl-add`, `split_book_chapters`)
has no manifest and no curation, so it drops **nothing**: no text of the file
ever leaves the index, and the text before the first heading becomes a
`FRONT_MATTER_SECTION` section. A short-but-real "CHAPTER I" in someone's own
file must not disappear from their index without a word.

A contents page is the one thing the generic path still has to recognise, and it
does so without dropping anything: a heading whose body is shorter than
`MIN_CHAPTER_CHARS` **and whose title reappears later in the file** is a
contents line, so its heading line and its body are merged into the preceding
section instead of opening one (see `merge_contents_headings`). Every merge is
reported. A short heading whose title does NOT come back is a genuinely short
chapter and keeps its own section, however short.
"""
import re
from typing import NamedTuple

# A chapter heading is a whole line. The default covers most of the demo corpus;
# a book can override with chapter_regex in the manifest.
DEFAULT_CHAPTER_RE = (
    r"^(?:(?:CHAPTER|Chapter|BOOK|Book|LETTER|Letter|STAVE|ADVENTURE)"
    r"\s+(?:[IVXLCDM]+|[0-9]+)\b[^\n]{0,80}"
    r"|THE [A-Z]+ BOOK"
    r"|[IVXL]+\.\s+[A-Z][A-Z '’,;-]{3,70}\.?)$"
)
MIN_CHAPTER_CHARS = 200  # headings with less body than this (TOC lines) are dropped

# Section name for a file in which no chapter structure was found.
FULL_TEXT_SECTION = "Full text"

# Section name for the text before the first heading of a file that does have
# headings. A user heading could read exactly the same, so the name is not a
# sentinel — it goes through `unique_titles` like any other, and a real
# "Front matter" heading later in the file becomes "Front matter (2)".
FRONT_MATTER_SECTION = "Front matter"

# "# Title" / "## Title", trailing closing hashes allowed.
MARKDOWN_HEADING_RE = re.compile(r"^(#{1,2})[ \t]+(\S.*?)[ \t]*#*[ \t]*$", re.M)


class MergedHeading(NamedTuple):
    """One contents line the generic path folded into the preceding section.

    Reported rather than silent: the user asked for a file to be indexed and
    part of it is not where its heading says it is."""
    title: str          # the heading line, as it would have named the section
    body_chars: int     # how much text followed it (why it was read as a TOC line)
    target: str         # the section its text was merged into


def split_chapters(text: str, heading_re: str, part_re: str | None = None,
                   min_chapter_chars: int = MIN_CHAPTER_CHARS,
                   keep_preamble: bool = False,
                   drop_toc_leftovers: bool = True,
                   *, end_re: str | None = None,
                   end_title: str | None = None) -> list[tuple[str, str]]:
    """[(title, body)] using whole-line headings. Table-of-contents lines match
    the same regex as real headings, but their "body" (text up to the next
    match) is tiny — so headings with a body under min_chapter_chars are
    dropped. Titles may legitimately repeat (several treatises restarting at
    CHAPTER I.), so there is no dedupe; the one residual TOC artifact — the
    LAST contents line, whose body is the front matter before chapter one —
    is removed by dropping a leading heading whose title reappears later. That
    comparison ignores a trailing period on either side: a Gutenberg contents
    page lists "CHAPTER LII" for a heading the book prints as "CHAPTER LII."
    (Don Quixote), and with an exact test the front matter stayed as a section
    named after the last chapter, ahead of chapter one.

    Both of those are contents-page heuristics: right for the curated demo
    corpus, wrong for a stranger's file, where a two-line chapter is a chapter
    and the text before the first heading is text. The generic ingest therefore
    calls this with `min_chapter_chars=0, keep_preamble=True,
    drop_toc_leftovers=False` — nothing is dropped, the preamble comes back as
    the leading untitled section — while the demo pipeline keeps the defaults
    and the behaviour it always had.

    With `part_re`, a part heading after the first real chapter heading (the
    first one the size filter and the contents-leftover test keep) also ends
    the section before it when the part has text of its own (at least
    `min_chapter_chars`: a chapterless essay in an anthology, an act's
    chorus): that text becomes a section named after the part. Everything
    else about parts is as it was — a part heading with little or no text
    of its own stays inside the preceding chapter, and text before the first
    real chapter heading (title page, contents) stays where it was.

    With `end_re`, the heading the book's back matter starts with, that back
    matter becomes a section of its own instead of the tail of the last chapter
    (`cut_back_matter`), named after the matched heading or after `end_title`
    when the heading is a poor name for what follows it. Without it nothing
    moves: a book with no `end_regex` in the manifest splits byte for byte as
    it always did. Both are keyword-only and sit AFTER the three options this
    function already had, so a positional call written before them still means
    what it meant; a caller that needs to know whether the cut happened calls
    `cut_back_matter` itself, which says so.
    """
    pattern = re.compile(heading_re, re.M)
    matches = list(pattern.finditer(text))
    if not matches:
        return [("", text)]

    def title_of(m: re.Match) -> str:
        return heading_title(m.group(0))

    def line_end(m: re.Match) -> int:
        # part_re need not match the whole line ("PART I. A VOYAGE TO" ...);
        # the rest of the heading line is title, not body
        nl = text.find("\n", m.end())
        return len(text) if nl < 0 else nl

    def is_toc_leftover(first: str, later: str) -> bool:
        """The last contents line repeats a real heading with a subtitle
        appended ("CHAPTER XXVII. Mina..." vs the body's bare "CHAPTER XXVII").
        Only a STRICTLY longer first title counts, on a word boundary — equal
        titles are legitimate (several treatises restarting at CHAPTER I.),
        and "BOOK I" must never match "BOOK II"."""
        return (len(first) > len(later) and first.startswith(later)
                and not first[len(later)].isalnum())

    def split(parts: list[re.Match]) -> list[tuple[str, str, int]]:
        """(title, body, heading offset) per section; `parts` are the part
        headings that open a section of their own."""
        bounds = sorted([(m.start(), m.end(), m, False) for m in matches]
                        + [(m.start(), line_end(m), m, True) for m in parts],
                        key=lambda b: b[0])
        sections = []             # (title, body, heading offset, is_part)
        for i, (start, body_start, m, is_part) in enumerate(bounds):
            end = bounds[i + 1][0] if i + 1 < len(bounds) else len(text)
            body = text[body_start:end].strip()
            if len(body) >= min_chapter_chars:
                sections.append((part_title(m) if is_part else title_of(m), body, start, is_part))
        # Parts first: the contents-leftover heuristic below compares titles, and
        # "PART TWO — CHAPTER I." must not look like a repeat of "PART ONE — CHAPTER I.".
        # Only chapter titles get the prefix; a part section already is the part.
        chapters = [(t, b) for t, b, _, is_part in sections if not is_part]
        if part_re:
            chapters = with_parts(text, chapters, part_re,
                                  [pos for _, _, pos, is_part in sections if not is_part])
        named = iter(chapters)
        return [(t, b, pos) if is_part else (*next(named), pos)
                for t, b, pos, is_part in sections]

    # Chapters alone first, exactly as without part sections: the size filter
    # and the contents-leftover heuristic decide which chapter headings are
    # contents lines, and the first heading that survives both is the first
    # real chapter.
    kept = split([])
    while drop_toc_leftovers and len(kept) > 1 and (
            any(is_toc_leftover(kept[0][0], t) for t, _, _ in kept[1:])
            # a contents line identical to a real heading survives only as the
            # book's LAST heading duplicated up front (e.g. "CHAPTER 135."
            # before "CHAPTER 1.") — ascending repeats (Seneca's treatises
            # restarting at CHAPTER I.) never trip this. A trailing period is
            # ignored on both sides: a contents page prints "CHAPTER LII" for a
            # heading the book prints as "CHAPTER LII." (Don Quixote), and the
            # strictly-longer branch above only catches the reverse shape.
            # Only the demo path comes here; drop_toc_leftovers=False (the
            # generic `ayl add`) still keeps every section it always kept.
            or kept[0][0].rstrip(".") == kept[-1][0].rstrip(".")):
        kept.pop(0)

    # A part heading is a section boundary too, not only a title prefix: an
    # anthology part with no chapter headings of its own (Dumas's "*THE
    # CENCI—1598*" essay) otherwise runs on inside the previous part's last
    # chapter, where neither retrieval nor a chapter read by title finds it.
    # Only a part with enough text of its own opens a section. A short one (an
    # epigraph, a wrapped heading line) stays in the preceding chapter as it
    # always did, so no text is lost; so does every part heading before the
    # first real chapter, where title pages and contents pages live (Romeo and
    # Juliet lists "ACT II" above an indented scene list long enough to pass the
    # size test, and a contents page may itself open with a line the chapter
    # regex matches).
    if part_re and kept:
        first_real = kept[0][2]
        chapter_starts = {m.start() for m in matches}
        candidates = [m for m in re.finditer(part_re, text, re.M)
                      if m.start() > first_real and m.start() not in chapter_starts]
        stops = sorted(chapter_starts | {m.start() for m in candidates})
        parts = []
        for m in candidates:
            nxt = next((s for s in stops if s > m.start()), len(text))
            if len(text[line_end(m):nxt].strip()) >= min_chapter_chars:
                parts.append(m)
        if parts:
            # Everything before the first real chapter was settled above; a
            # part section only ever splits text after it.
            kept = [sec for sec in split(parts) if sec[2] >= first_real]
    kept = [(t, b) for t, b, _ in kept]
    if not kept:
        return [("", text)]
    if end_re:
        kept, _ = cut_back_matter(kept, end_re, end_title=end_title)
    # The preamble is prepended AFTER with_parts and the contents heuristics,
    # both of which reason about chapter headings only; it belongs to no part
    # and can never be a contents leftover.
    preamble = text[:matches[0].start()].strip() if keep_preamble else ""
    return ([("", preamble)] if preamble else []) + kept


def heading_title(heading: str) -> str:
    """A heading line as a section name: whitespace collapsed, the stray
    bracket of a wrapped heading dropped."""
    return re.sub(r"\s+", " ", heading).strip(" ]").strip()


def cut_back_matter(chapters: list[tuple[str, str]], end_re: str,
                    *, end_title: str | None = None
                    ) -> tuple[list[tuple[str, str]], bool]:
    """Move a book's back matter — the translator's notes, an appendix and
    glossary, a transcriber's list of bookmarks — out of the last chapter and
    into a section of its own, named after the heading it starts with, or after
    `end_title` when that heading names only the first item of what follows it
    (Ivanhoe's apparatus opens with "NOTE TO CHAPTER I." and holds the notes to
    ten chapters, so a quote from the note to chapter XLI would otherwise carry
    the name of another chapter). A renamed section keeps the heading line at
    the top of its text, where a chapter's heading would have become its title.

    There is no end-of-book boundary in the heading regex, so everything after
    the last chapter heading joined that chapter: Ivanhoe's notes were text of
    "CHAPTER XLIV", and a chapter read of it spent its window on them. Cut
    rather than dropped, because Scott's notes and Marcus Aurelius's appendix
    are worth finding — under their own name, where a citation says what the
    passage is. Neither half is measured against `min_chapter_chars`: the size
    filter is a contents-page heuristic, and this cut only moves a boundary
    inside text that is already kept, so no text is dropped by it.

    The back matter belongs to no part: the section is named for its heading
    alone, without the part prefix `with_parts` puts on chapter titles, because
    an appendix at the end of volume IV is the book's, not that volume's.

    Only the LAST section is searched, so a heading that also reads like back
    matter earlier in the book (a note inside a chapter) cannot cut one of the
    chapters in half. A match with no text after it is not a boundary but the
    book's last line, and nothing moves; a last section that is back matter
    from its first line replaces itself rather than leaving an empty chapter.

    Returns the sections and whether anything was actually cut. The flag is the
    point: every way of missing — an unmatched regex, a heading that sits in
    the contents page or inside a chapter — leaves the sections
    exactly as they came in, and a caller cannot tell those apart by looking at
    the result afterwards. Reading it back off the section titles is worse than
    useless: an `end_title` equal to the last chapter's name would answer "cut"
    to a book nothing happened to."""
    title, body = chapters[-1]
    m = re.search(end_re, body, re.M)
    if not m:
        return chapters, False
    chapter, following = body[:m.start()].strip(), body[m.end():].strip()
    if not following:
        return chapters, False
    # Without a name of its own the section takes the heading's, as a chapter
    # does. With `end_title` the heading is nobody's title any more, so it stays
    # at the top of the section's text instead of being dropped with it.
    back_section = ((end_title, body[m.start():].strip()) if end_title
                    else (heading_title(m.group(0)), following))
    if not chapter:
        return chapters[:-1] + [back_section], True
    return chapters[:-1] + [(title, chapter), back_section], True


def part_title(m: re.Match) -> str:
    """A part heading's name: its capture group if part_re has one, else the line."""
    return (m.group(1) if m.groups() else m.group(0)).strip(" .*")


def with_parts(text: str, chapters: list[tuple[str, str]], part_re: str,
               offsets: list[int]) -> list[tuple[str, str]]:
    """Prefix each chapter title with the part / treatise / act / volume it
    belongs to, so editions that restart numbering per part get unique,
    human-readable sections ("OF ANGER — CHAPTER I." instead of a bare
    "CHAPTER I." three times). A part heading is the last part_re match before
    the chapter's heading offset; a capture group selects the title text,
    otherwise the whole line is used. Contents-page part lines never own a
    chapter body, so they fall away naturally."""
    parts = [(m.start(), part_title(m)) for m in re.finditer(part_re, text, re.M)]
    if not parts:
        return chapters
    out = []
    for (title, body), pos in zip(chapters, offsets, strict=True):
        part = ""
        for start, name in parts:
            if start < pos:
                part = name
        out.append((f"{part} — {title}" if part else title, body))
    return out


def split_markdown_chapters(text: str) -> list[tuple[str, str]]:
    """[(title, body)] from "#" / "##" headings; [] when the text has none.

    A single "#" heading standing before "##" headings is the document title,
    not a chapter, so in that shape only the "##" headings open sections.
    Text before the first section heading is kept as an untitled leading
    section rather than dropped; a heading with no body keeps a section whose
    text is the heading line (nothing in the file is dropped). Unlike the
    prose detector there is no minimum body size: user
    Markdown chapters are legitimately short and there are no table-of-contents
    lines to filter out."""
    matches = list(MARKDOWN_HEADING_RE.finditer(text))
    if not matches:
        return []

    h1s = [m for m in matches if len(m.group(1)) == 1]
    h2s = [m for m in matches if len(m.group(1)) == 2]
    if h2s and len(h1s) <= 1 and (not h1s or h1s[0].start() == matches[0].start()):
        heads = h2s
    else:
        heads = matches

    sections: list[tuple[str, str]] = []
    preamble = MARKDOWN_HEADING_RE.sub("", text[:heads[0].start()]).strip()
    if preamble:
        sections.append(("", preamble))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end].strip()
        title = m.group(2).strip()
        sections.append((title, body or title))
    return sections


def merge_contents_headings(sections: list[tuple[str, str]],
                            min_chapter_chars: int = MIN_CHAPTER_CHARS
                            ) -> tuple[list[tuple[str, str]], list[MergedHeading]]:
    """Fold a book's table-of-contents lines into the section they sit in.

    A raw Gutenberg-style .txt opens with a contents page whose lines match the
    same heading regex as the real chapters. Opening a section per contents line
    is not lossy, but it is wrong twice over: the tiny contents sections take
    the bare names ("CHAPTER I."), so `unique_titles` renames the REAL chapters
    to "CHAPTER I. (2)" — and a chapter is addressed by (book, section), so
    `read_chapter` then lands on a one-line contents entry.

    The contents test is deliberately narrow, because the alternative reading of
    a short body is a genuinely short chapter, which must keep its own section:
    a heading is a contents line only when its body is under min_chapter_chars
    AND the same title reappears later in the file. A short "CHAPTER I" that
    never comes back is a chapter and stays one, however short.

    Nothing is dropped: a contents line's heading text and its body are appended
    to the preceding section's body (to the leading untitled section — the front
    matter — when there is no preceding section), so every line of the file is
    still indexed and still searchable, just under the section it physically
    belongs to. Returns the sections and one `MergedHeading` per merge, for the
    caller to report.

    At least one titled section always survives: the LAST occurrence of a title
    has no later twin, so it can never be merged.
    """
    out, merged, _ = _merge_contents_headings(sections, min_chapter_chars)
    return out, merged


def _merge_contents_headings(sections, min_chapter_chars=MIN_CHAPTER_CHARS):
    """`merge_contents_headings` plus, per merge, the index of the target
    section in the returned list, so a caller that renames sections afterwards
    (`unique_titles`) can report the target by its final name."""
    out: list[tuple[str, str]] = []
    merged: list[MergedHeading] = []
    targets: list[int] = []
    for i, (title, body) in enumerate(sections):
        repeats_later = bool(title) and any(later == title for later, _ in sections[i + 1:])
        if not (repeats_later and len(body.strip()) < min_chapter_chars):
            out.append((title, body))
            continue
        moved = f"{title}\n{body}".strip()
        if out:
            head, previous = out[-1]
            out[-1] = (head, f"{previous}\n\n{moved}".strip())
            target = head or FRONT_MATTER_SECTION
        else:                       # a contents line before any other text
            out.append(("", moved))
            target = FRONT_MATTER_SECTION
        merged.append(MergedHeading(title, len(body.strip()), target))
        targets.append(len(out) - 1)
    return out, merged, targets


def split_book_sections(text: str, markdown: bool
                        ) -> tuple[list[tuple[str, str]], list[MergedHeading]]:
    """Sections for one book file, always non-empty and never lossy, plus the
    contents lines that were merged (`merge_contents_headings`) so the caller
    can report them. `split_book_chapters` is the same thing without the report.

    Markdown headings (Markdown files only), else the whole-line prose
    heuristic, else the whole file as one `FULL_TEXT_SECTION` section.

    No text of the file is dropped. Every heading opens a section however short
    its body — the demo corpus's `MIN_CHAPTER_CHARS` filter is a
    table-of-contents heuristic for curated Gutenberg files, and applying it
    here silently deleted a user's short-but-real "CHAPTER I" — except for a
    contents line, whose text is merged into the preceding section rather than
    dropped. The text before the first heading is kept as `FRONT_MATTER_SECTION`
    instead of being discarded. Titles are then made unique, because a repeated
    section name collides in `chunk_id`, which is the retrieval dedupe key and
    the chapter-ordering key, and is what `read_chapter` resolves a chapter by.

    The contents heuristic runs on the prose path only. Markdown headings have
    no minimum body and no contents-page ambiguity: a "## One" with two words
    under it is a short section the author wrote.
    """
    sections: list[tuple[str, str]] = []
    merged: list[MergedHeading] = []
    targets: list[int] = []
    if markdown:
        sections = split_markdown_chapters(text)
    if not sections:
        detected = split_chapters(text, DEFAULT_CHAPTER_RE, min_chapter_chars=0,
                                  keep_preamble=True, drop_toc_leftovers=False)
        # A titled section means real headings were found; a lone untitled one
        # is the "no matches" return, which the FULL_TEXT_SECTION path handles.
        if any(title for title, _ in detected):
            sections, merged, targets = _merge_contents_headings(detected)
    if not sections:
        sections = [(FULL_TEXT_SECTION, text.strip())]
    # An untitled leading section is the file's front matter; it needs a name
    # because the section string is how a chapter is addressed on the read side.
    # A heading with nothing under it (the last line of a file, an empty
    # chapter) keeps its section too, with the heading line as its text: the
    # heading is part of the file and "nothing is dropped" includes it.
    sections = [(title or FRONT_MATTER_SECTION, body if body.strip() else title)
                for title, body in sections if body.strip() or title.strip()]
    if not sections:
        sections = [(FULL_TEXT_SECTION, text.strip())]
    final = unique_titles(sections)
    # Report each merge by the target's FINAL name (a "CHAPTER I." that
    # `unique_titles` renamed to "CHAPTER I. (2)" is reported as the latter).
    merged = [m._replace(target=final[idx][0]) for m, idx in zip(merged, targets)]
    return final, merged


def split_book_chapters(text: str, markdown: bool) -> list[tuple[str, str]]:
    """`split_book_sections` without the merge report."""
    sections, _ = split_book_sections(text, markdown)
    return sections


def unique_titles(sections: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Disambiguate repeated section titles ("Chapter I" twice -> the second
    becomes "Chapter I (2)"). The demo pipeline refuses repeats instead and
    asks for a part_regex; a folder of someone's own files has no manifest to
    fix, so here the section name is made unique in place.

    Every EMITTED name is reserved, not just the original ones: counting
    originals alone let a generated name collide with a title the file already
    used ("Chapter I", "Chapter I", "Chapter I (2)" all resolved to two
    "Chapter I (2)" sections), and two sections sharing a name are one chapter
    to `read_chapter`, which addresses a chapter by (book, section). The suffix
    is bumped until the name is free, so the first occurrence always keeps its
    bare title and no two sections of a book ever share a name."""
    taken: set[str] = set()
    out = []
    for title, body in sections:
        name, count = title, 1
        while name in taken:
            count += 1
            name = f"{title} ({count})"
        taken.add(name)
        out.append((name, body))
    return out
