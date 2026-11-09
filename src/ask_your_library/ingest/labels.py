"""How long a label the EPUB and PDF readers take from a book file may be.

A label is the book's title, its author line and each name in it, a contents
or outline entry. The text caps (`MAX_TOTAL_CHARS` in both readers) count the
text and nothing else, and a label is paid once a chunk, not once: the chunker
writes the section title into every chunk id and puts the title, the author and
the section in front of every chunk the embedder reads, so a label the file
made megabytes long cost as much again for every chunk.

One rule for both readers, in a module of its own: it bounds what a reader
returns, and has nothing to do with how a text is split into chapters.
"""
import hashlib

# Well above a real label (a long title with its subtitle, or an older novel's
# chapter title that sums up the chapter, runs to two or three hundred
# characters), and below a chunk's own length.
MAX_LABEL_CHARS = 500
# What a cut label ends with: `… ` and this many hex characters of the SHA-256
# of the whole label, the length `bookkey.slug` gives its digest too.
LABEL_DIGEST_CHARS = 8
CUT_MARK = "… "


def shorten_label(label: str) -> str:
    """`label` itself when it is MAX_LABEL_CHARS long or shorter; else its
    first characters, `… ` and LABEL_DIGEST_CHARS hex characters of the
    SHA-256 of the whole of it, MAX_LABEL_CHARS in all at most.

    Shortened, not refused: both readers take a book's labels as a best effort
    (a book with no title is named by its file, an unusable contents list
    falls back to numbered sections), and the head of a label still names what
    the whole of it did. The digest is what keeps two labels that differ only
    past the cut apart: two volumes whose long titles differ in the last word
    would otherwise be one book key, and `add_folder` stops a run on two files
    that resolve to the same book. A digest of 32 bits makes two different
    labels with one head share a cut by chance about once in four billion; a
    file can still copy another book's title and author outright, as it always
    could. The space keeps the digest a word of its own rather than the end of
    the last word cut. Section titles that come out the same, cut or not, are
    told apart afterwards by `chapters.unique_titles` (` (N)`)."""
    if len(label) <= MAX_LABEL_CHARS:
        return label
    digest = hashlib.sha256(label.encode("utf-8", "surrogatepass")).hexdigest()
    digest = digest[:LABEL_DIGEST_CHARS]
    head = label[:MAX_LABEL_CHARS - len(CUT_MARK) - LABEL_DIGEST_CHARS].rstrip()
    return f"{head}{CUT_MARK}{digest}"
