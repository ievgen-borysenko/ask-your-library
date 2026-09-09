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

# Card sections longer than MAX are split on bullet boundaries, packing up to TARGET.
MAX_CHUNK_CHARS = 2000
TARGET_CHUNK_CHARS = 1400

# Transcript chunks: ~1000 tokens, overlap ~15% carried as whole trailing sentences.
TRANSCRIPT_TARGET_CHARS = 4000
TRANSCRIPT_OVERLAP_CHARS = 400

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


def rows_for(chunks: list[Chunk], vectors: list[list[float]]) -> list[dict]:
    # strict: an embedder returning fewer vectors must fail here, not silently
    # drop the tail chunks
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    return [{
        "chunk_id": c.chunk_id, "note": c.note, "book": c.book,
        "source": c.source, "section": c.section, "text": c.text,
        "vector": v,
    } for c, v in zip(chunks, vectors)]


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


def pack_sentences(sentences: list[str]) -> list[str]:
    """Greedy packing: fill a chunk with sentences up to TRANSCRIPT_TARGET_CHARS,
    then start the next chunk from the tail sentences of the previous one until
    TRANSCRIPT_OVERLAP_CHARS of overlap is collected."""
    chunks = []
    buffer: list[str] = []
    buffer_len = 0
    for sentence in sentences:
        if buffer and buffer_len + len(sentence) > TRANSCRIPT_TARGET_CHARS:
            chunks.append(" ".join(buffer))
            overlap: list[str] = []
            overlap_len = 0
            for prev_sentence in reversed(buffer):
                if overlap_len >= TRANSCRIPT_OVERLAP_CHARS:
                    break
                overlap.insert(0, prev_sentence)
                overlap_len += len(prev_sentence)
            buffer = overlap
            buffer_len = overlap_len
        buffer.append(sentence)
        buffer_len += len(sentence)
    if buffer:
        chunks.append(" ".join(buffer))
    return chunks
