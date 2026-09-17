"""Chunking for the two corpora.

Cards (markdown distillates of a book): one chunk per "## section"; oversized
sections split on top-level bullets / "###" headings.

Transcripts / full text: chunks packed from WHOLE sentences (never cut
mid-sentence) with a sentence-level overlap between neighbours. Chapter
boundaries are the caller's responsibility (see scripts/ingest_demo_corpus.py).
"""
import re
from dataclasses import dataclass
from pathlib import Path

from ..sanitize import strip_control_chars

# What a chunk IS, as one name that can be written down and compared.
#
# `sentence-pack-2` is this module's rule: whole sentences packed to
# TRANSCRIPT_TARGET_CHARS with a sentence-level overlap, a hard cap on a
# "sentence" that carries no punctuation, and chapter boundaries supplied by
# the caller. Bump it whenever a change here would make the chunks of a
# re-ingest different text from the chunks already in an index — not for a
# refactor that produces the same chunks.
#
# `sentence-pack-1` was the same packer at a 4,000-character target with no
# sentence cap, which is what every index built before #28 holds: 90% of its
# transcript chunks were longer than the window `observe` reads (2,500), so
# ranking scored text the model never saw. The bump is what makes such an index
# detectable — warn on read, refuse on write until `--rebuild` (ADR-020 as #27
# amended it).
#
# It lives HERE, in the module that decides what a chunk is, and is imported by
# everything that records it: `_index_meta.chunker` on both ingest paths, the
# `chunker` column of every ledger row, and the mismatch policy that reads them
# back (`index_meta.version_mismatch`). One constant, because a version written
# from two places is two versions.
CHUNKER_VERSION = "sentence-pack-2"

# And the OTHER chunker in this module, which is a different rule over a
# different corpus: a book card is cut on its "## section" headings
# (`chunk_card`), never by the sentence packer, so a change to the packer says
# nothing about a cards table. One constant per rule is what keeps #28's bump
# from refusing every card write for a reason that is not true of cards. The
# policy picks the one that belongs to the table it is checking
# (`index_meta.expected_chunker`).
CARD_CHUNKER_VERSION = "card-sections-1"

# Card sections longer than MAX are split on bullet boundaries, packing up to TARGET.
MAX_CHUNK_CHARS = 2000
TARGET_CHUNK_CHARS = 1400

# Transcript chunks: the chunk and the observation window are ONE decision
# (ADR-025, superseding ADR-012). A chunk is what the retriever ranks, and
# `observe` reads at most SEARCH_HIT_CHARS (2,500 by default) of the hit it
# returns, so a chunk longer than that window is text the ranking counted and
# the model never saw. The target is set BELOW the window rather than at it, so
# that the overlap a chunk carries from its predecessor still fits inside it.
#
# These numbers are not read from `config`: a chunker whose output depends on
# an environment variable would write chunks no version string could describe.
# The relation between the two is asserted instead, once, in
# `tests/test_observation_window.py`.
TRANSCRIPT_TARGET_CHARS = 2400
TRANSCRIPT_OVERLAP_CHARS = 240        # ~10%, carried as whole trailing sentences

# A "sentence" the splitter could not end, because the text carries no
# punctuation to end it on: raw Whisper output is the case that matters, and
# the demo corpus holds one of 10,140 characters (`time-machine`, Chapter 3).
# The packer cannot break such a run into whole sentences, so it breaks it on
# whitespace instead — the only boundary left that is not mid-word. Below the
# target, so a capped piece can never be the thing that pushes a chunk over it.
MAX_SENTENCE_CHARS = 2000

# The hard ceiling every transcript chunk is under, derived from the three
# numbers above rather than asserted beside them: a chunk is flushed at the
# target, and the one shape that can exceed it is the first sentence after a
# flush landing on top of the overlap. Nothing in this module may return a
# longer string, and the window test checks it against SEARCH_HIT_CHARS.
TRANSCRIPT_MAX_CHARS = max(TRANSCRIPT_TARGET_CHARS,
                           TRANSCRIPT_OVERLAP_CHARS + 1 + MAX_SENTENCE_CHARS)

# Sentence end: . ! ? … optionally followed by a closing quote/bracket, then whitespace.
_SENTENCE_END = re.compile(r'(?<=[.!?…])["\')\]]*[ \n]+')


@dataclass
class Chunk:
    chunk_id: str
    note: str      # source document id (file stem)
    book: str      # display title used for citations
    source: str    # provenance (frontmatter "source" for cards, "transcript" for text)
    section: str
    text: str


def embedding_text(chunk: Chunk) -> str:
    """What the embedder sees: book + section as context in front of the text,
    so bullets and quotes stay attributable after retrieval."""
    header = f"{chunk.book} — {chunk.section}" if chunk.section else chunk.book
    return f"{header}\n{chunk.text}"


def rows_for(chunks: list[Chunk], vectors: list[list[float]],
             book_id: str | None = None, book_rev: str | None = None) -> list[dict]:
    """Chunks plus their vectors as index rows — the one place every ingest
    path (cards, transcripts, `ayl-add`) writes through.

    The book key and the section title are the metadata that gets printed,
    cited and sent to the model, and a section title is corpus text like any
    other: it is a heading the file itself supplied, and nothing above strips
    it (front matter is cleaned by `parse_frontmatter`, the key by `book_key`,
    but a `# Chapter One` carrying an escape sequence reaches the row intact).
    So the strip happens on the row, for every path at once.

    `book_id` is the ledger's minted identity and `book_rev` the version of the
    book these rows were built from — a short prefix of the ledger row's
    `sha256`, so that rows being present under a book also says WHICH version of
    it they are. They are carried BESIDE `note` rather than instead of it: `note` is inside every `chunk_id` already written, and
    the id is what an update deletes by, so a corrected author still finds the
    rows it has to replace. It is last in the row, which is where a migrated
    table has it too (`publish.add_book_id_column`). Omitted — the demo
    corpus's cards table, and any caller predating the ledger — the column is
    simply absent, and the readers never look at it."""
    # strict: an embedder returning fewer vectors must fail here, not silently
    # drop the tail chunks
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    rows = [{
        "chunk_id": c.chunk_id, "note": c.note, "book": strip_control_chars(c.book),
        "source": c.source, "section": strip_control_chars(c.section), "text": c.text,
        "vector": v,
    } for c, v in zip(chunks, vectors)]
    if book_id is not None:
        for row in rows:
            row["book_id"] = book_id
            row["book_rev"] = book_rev or ""
    return rows


# --- cards -------------------------------------------------------------------

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """A leading "---" YAML-ish block -> (fields, body). Shared with the folder
    ingest, which reads `title:` / `author:` from the same block.

    Field values become index metadata (the book key, a card's source), which
    is printed, cited and sent to the model, so control and invisible
    formatting characters are dropped here rather than carried along."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = {}
    for line in text[3:end].splitlines():
        m = re.match(r'^(\w+):\s*"?(.*?)"?\s*$', line.strip())
        if m:
            meta[m.group(1)] = strip_control_chars(m.group(2))
    return meta, text[end + 4:]


def _split_long(section_text: str) -> list[str]:
    """Split an oversized section on top-level bullets / ### headings,
    packing pieces up to TARGET_CHUNK_CHARS.

    A bullet starts a new piece only when it begins with a capital (Latin or
    Cyrillic incl. Ukrainian І/Ї/Є/Ґ) or an opening quote: cards may be
    written in Ukrainian, and lower-case continuation bullets stay attached."""
    pieces = re.split(r"\n(?=- \*\*|- \"|- [A-ZА-ЯІЇЄҐ«\"']|### )", section_text)
    parts, buf = [], ""
    for piece in pieces:
        if buf and len(buf) + len(piece) > TARGET_CHUNK_CHARS:
            parts.append(buf.strip())
            buf = piece
        else:
            buf = f"{buf}\n{piece}" if buf else piece
    if buf.strip():
        parts.append(buf.strip())
    return parts


def chunk_card(path: Path) -> list[Chunk]:
    """Markdown card -> one chunk per "## section" (long sections split)."""
    raw = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(raw)
    note = path.stem
    m = re.search(r"^# (.+)$", body, re.M)
    book = m.group(1).strip() if m else note
    source = meta.get("source", "")

    chunks: list[Chunk] = []
    # Text before the first "## " is only the H1 and is skipped.
    sections = re.split(r"^## ", body, flags=re.M)[1:]
    for sec in sections:
        header, _, sec_body = sec.partition("\n")
        header, sec_body = header.strip(), sec_body.strip()
        if not sec_body:
            continue
        parts = [sec_body] if len(sec_body) <= MAX_CHUNK_CHARS else _split_long(sec_body)
        for i, part in enumerate(parts):
            suffix = f"/{i + 1}" if len(parts) > 1 else ""
            chunks.append(Chunk(
                chunk_id=f"{note}#{header}{suffix}",
                note=note,
                book=book,
                source=source,
                section=header,
                text=part,
            ))
    return chunks


# --- transcripts / full text ---------------------------------------------------

def split_sentences(text: str) -> list[str]:
    """Text -> whole sentences. Line breaks inside a sentence become spaces."""
    flat = text.replace("\n", " ")
    sentences = []
    for piece in _SENTENCE_END.split(flat):
        piece = piece.strip()
        if piece:
            sentences.append(piece)
    return sentences


def cap_sentence(sentence: str) -> list[str]:
    """One "sentence" as pieces of at most MAX_SENTENCE_CHARS.

    A sentence shorter than the cap is returned untouched, which is every
    sentence of every book that has punctuation. What this exists for is the
    other kind: an hour of speech transcribed as one run with no full stop in
    it. The packer's promise is that it never cuts mid-sentence, and it keeps
    it — but a "sentence" the splitter could not end is not a sentence, it is
    the absence of one, and packing it whole is what put a 10,778-character
    chunk into the index (#28).

    The break is on whitespace, the only boundary below a sentence that is not
    mid-word; a single "word" longer than the cap (a run of digits, a URL) is
    cut where the cap falls, because nothing else is left.

    **Every piece is a SLICE of the text it came from.** The tab, the double
    space, the non-breaking space a book actually prints stay exactly as the
    book printed them — an earlier version of this split on whitespace and
    re-joined the words with ASCII spaces, which rewrote the inside of a
    passage the index then stored and the reader is later shown. The quote
    check would not have noticed (it normalizes both sides), which is precisely
    why it had to be fixed here: what is stored has to be the book's text, not
    a version of it this function found convenient. The one thing not
    preserved is the whitespace AT a break, which belongs to neither piece;
    the packer joins pieces with a single space."""
    if len(sentence) <= MAX_SENTENCE_CHARS:
        return [sentence]
    pieces: list[str] = []
    start: int | None = None      # where the piece being filled begins
    end: int | None = None        # just past the last whole word it holds
    for word in re.finditer(r"\S+", sentence):
        first, last = word.span()
        if start is None:
            start = first
        if last - start > MAX_SENTENCE_CHARS:
            if end is not None:           # close the piece on the words that fit
                pieces.append(sentence[start:end])
                start, end = first, None
            while last - first > MAX_SENTENCE_CHARS:   # a single word over the cap
                pieces.append(sentence[first:first + MAX_SENTENCE_CHARS])
                first = start = first + MAX_SENTENCE_CHARS
        end = last
    if start is not None and end is not None and end > start:
        pieces.append(sentence[start:end])
    return pieces


def _overlap_tail(buffer: list[str]) -> tuple[list[str], int]:
    """The trailing sentences of a finished chunk that open the next one, and
    the length of the string they join into.

    A sentence is taken only while the whole tail still fits in
    TRANSCRIPT_OVERLAP_CHARS, never one past it. The old rule stopped AFTER
    crossing the budget, so the overlap could be a whole sentence longer than
    the number said — which is one of the two ways a chunk used to exceed its
    target, and the reason the ceiling here is arithmetic rather than a hope."""
    tail: list[str] = []
    tail_len = 0
    for sentence in reversed(buffer):
        cost = len(sentence) + (1 if tail else 0)
        if tail_len + cost > TRANSCRIPT_OVERLAP_CHARS:
            break
        tail.insert(0, sentence)
        tail_len += cost
    return tail, tail_len


def pack_sentences(sentences: list[str]) -> list[str]:
    """Greedy packing: fill a chunk with whole sentences up to
    TRANSCRIPT_TARGET_CHARS, then start the next chunk from the tail sentences
    of the previous one until TRANSCRIPT_OVERLAP_CHARS of overlap is collected.

    Every returned chunk is at most TRANSCRIPT_MAX_CHARS characters long, and
    that is the point of the two changes #28 made here: the length counted is
    the length of the string this returns — the joining spaces included, which
    the old count left out, so 600 four-character sentences packed to 2,400
    "characters" and came back 3,000 long — and a sentence that cannot fit is
    capped before it is packed (`cap_sentence`) rather than carried whole."""
    chunks = []
    buffer: list[str] = []
    buffer_len = 0      # length of " ".join(buffer), not the sum of its parts
    for sentence in (piece for s in sentences for piece in cap_sentence(s)):
        cost = len(sentence) + (1 if buffer else 0)
        if buffer and buffer_len + cost > TRANSCRIPT_TARGET_CHARS:
            chunks.append(" ".join(buffer))
            buffer, buffer_len = _overlap_tail(buffer)
            cost = len(sentence) + (1 if buffer else 0)
        buffer.append(sentence)
        buffer_len += cost
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks
