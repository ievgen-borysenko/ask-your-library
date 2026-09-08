"""Corpus ingestion: chunking, embedding text, LanceDB rows and the FTS index.

Shared by every ingest path so that all corpora are chunked identically —
eval numbers across corpora are only comparable if the chunks are.
"""
from .chapters import (DEFAULT_CHAPTER_RE, FRONT_MATTER_SECTION, FULL_TEXT_SECTION,
                       MIN_CHAPTER_CHARS, MergedHeading, merge_contents_headings,
                       split_book_chapters, split_book_sections, split_chapters,
                       split_markdown_chapters, unique_titles, with_parts)
from .chunking import (Chunk, chunk_card, embedding_text, pack_sentences, rows_for,
                       split_sentences)
from .fts import build_fts_index

__all__ = ["Chunk", "chunk_card", "embedding_text", "pack_sentences", "rows_for",
           "split_sentences", "build_fts_index",
           "DEFAULT_CHAPTER_RE", "FRONT_MATTER_SECTION", "FULL_TEXT_SECTION",
           "MIN_CHAPTER_CHARS", "MergedHeading", "merge_contents_headings",
           "split_book_chapters", "split_book_sections", "split_chapters",
           "split_markdown_chapters", "unique_titles", "with_parts"]
