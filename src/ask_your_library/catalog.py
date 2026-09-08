"""The catalogue path (ADR-016): questions about what the library HOLDS — how
many books, which titles, whether a title or an author is in it — answered by
code from the index tables, exhaustively, with no model reading the list.

Sent through the research loop, such a question gets a sample: top-k search
returns the neighbours of a phrase, `observe` keeps hits by the text of a
chunk while the answer sits in its metadata, and the count is written by a
model over a list it saw (the owner's first question to the web UI got 14
titles under a heading that said 17, of 33). Here the planner only names the
operation; the list is `library.list_books()`, the count is `len()` of the very
list the answer shows, and a title or an author in the question is resolved
against that list by code, so nothing can be "found" that is not in it.
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass, field

from .i18n import t
from .library import BookEntry, list_books

CATALOG_OPS = ("count", "list", "has", "by_author")
CLOSE_MATCH_CUTOFF = 0.8      # a typo still resolves ("Ivanho" -> Ivanhoe)
SUGGESTION_CUTOFF = 0.5       # what "closest titles" may name when nothing resolves
MAX_SUGGESTIONS = 3
MIN_CONTAINED_CHARS = 4       # "It" must not resolve by being contained in every title
STRICT_CONTAINED_SHARE = 0.6  # strict mode: a one-word name inside a longer title must be most of it


# Words a question about HOLDINGS does not carry: they ask about content. The
# planner may still label such a question "catalog" (it did, once, for "Do I have
# Dracula, and why does Harker stay?"); code then sends it to the research loop
# as a mixed intent, with the named book as the retrieval filter. Conservative
# on purpose: a false positive costs a search where a listing would have done,
# never the reverse. A title hidden inside a question ("the names of the three
# musketeers") is beyond this gate: that routing stays the planner's reading,
# measured by the controls of the catalogue eval set.
CONTENT_CLUES = re.compile(
    r"(?<!\w)(?:why|how(?!\s+many)|who|whom|whose|where|when|what happens|explain|describe|"
    r"tell me about|summar\w*|plot|character\w*|about|mention\w*|discuss\w*|deals? with|"
    r"чому|як(?!\s+багато)|хто|кого|де|коли|про що|про|поясни|розкажи|опиши|сюжет|згаду\w*|йдеться)(?!\w)",
    re.I,
)


def content_clue(question: str) -> str:
    """The first content word of a question, or "" when it reads as a pure
    holdings question (how many, which titles, do I have X, what do I have by Y).
    Case-folded only: `fold` would strip the breve off "й" and the pattern's
    Ukrainian words would never match."""
    found = CONTENT_CLUES.search(" ".join(question.casefold().split()))
    return found.group(0) if found else ""


def parse_catalog_request(decision: dict) -> dict | None:
    """The planner's "catalog" object, validated by CODE: {"op": one of
    CATALOG_OPS, "title": str, "author": str}. None when it is absent, not an
    object, names an operation that is not ours, or asks "has" without a title
    or "by_author" without an author — the question then takes the research
    loop, never the other way round."""
    raw = decision.get("catalog")
    if not isinstance(raw, dict):
        return None
    op = raw.get("op")
    if not isinstance(op, str) or op not in CATALOG_OPS:
        return None
    title = raw.get("title") if isinstance(raw.get("title"), str) else ""
    author = raw.get("author") if isinstance(raw.get("author"), str) else ""
    title, author = title.strip(), author.strip()
    if op == "has" and not title:
        return None
    if op == "by_author" and not author:
        return None
    return {"op": op, "title": title, "author": author}


def fold(text: str) -> str:
    """Case, accents, curly apostrophes and runs of whitespace folded away:
    what two spellings of one title have in common."""
    text = unicodedata.normalize("NFKD", text).casefold().replace("\u2019", "'")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(text.split())


def _without_article(text: str) -> str:
    return re.sub(r"^(?:the|a|an) ", "", text)


def _contains_words(haystack: str, needle: str) -> bool:
    return bool(needle) and re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", haystack) is not None


def _resolve(name: str, entries: list[BookEntry], field_of,
             last_word_too: bool = False, strict: bool = False) -> tuple[list[BookEntry], list[str]]:
    """Entries whose `field_of(entry)` the reader means by `name`, and, when
    none, up to MAX_SUGGESTIONS closest values for the "not found" line.
    Exact (folded, a leading article ignored) first; then the name contained in
    the field as whole words, or the field in the name (a title inside a
    longer phrase), each at least MIN_CONTAINED_CHARS long; then close matches
    (difflib, CLOSE_MATCH_CUTOFF) so a typo still resolves — for authors also
    against the surname alone (`last_word_too`), because "Melvile" is a typo of
    "Melville", not of "Herman Melville". Several matches are returned as
    several: "Holmes" is every Holmes book. `strict` (the retrieval filter of
    the hybrid) accepts a name contained in a longer title only when it is
    several words or most of the title: "Time" is not The Time Machine."""
    wanted = fold(name)
    if not wanted:
        return [], []
    values = {e: fold(field_of(e)) for e in entries}
    exact = [e for e, v in values.items() if v == wanted or _without_article(v) == _without_article(wanted)]
    if exact:
        return exact, []
    def contained_in(v: str) -> bool:
        if len(wanted) >= MIN_CONTAINED_CHARS and _contains_words(v, wanted):
            return (not strict or len(wanted.split()) >= 2
                    or len(wanted) >= STRICT_CONTAINED_SHARE * len(v))
        return len(v) >= MIN_CONTAINED_CHARS and _contains_words(wanted, v)

    contained = [e for e, v in values.items() if contained_in(v)]
    if contained:
        return contained, []
    variants = {e: ({v, v.split()[-1]} if last_word_too and " " in v else {v}) for e, v in values.items()}
    pool = sorted({variant for vs in variants.values() for variant in vs})
    close = set(difflib.get_close_matches(wanted, pool, n=MAX_SUGGESTIONS, cutoff=CLOSE_MATCH_CUTOFF))
    matches = [e for e, vs in variants.items() if vs & close]
    if matches:
        return matches, []
    near = difflib.get_close_matches(wanted, list(values.values()), n=MAX_SUGGESTIONS,
                                     cutoff=SUGGESTION_CUTOFF)
    suggestions: list[str] = []
    for v in near:
        display = next(field_of(e) for e, folded in values.items() if folded == v)
        if display not in suggestions:
            suggestions.append(display)
    return [], suggestions


def resolve_title(name: str, entries: list[BookEntry],
                  strict: bool = False) -> tuple[list[BookEntry], list[str]]:
    """Books the reader means by a title (or a full "Title — Author" key)."""
    by_title, suggestions = _resolve(name, entries, lambda e: e.title, strict=strict)
    if by_title:
        return by_title, []
    by_key, _ = _resolve(name, entries, lambda e: e.key, strict=strict)
    return (by_key, []) if by_key else ([], suggestions)


def resolve_author(name: str, entries: list[BookEntry]) -> tuple[list[BookEntry], list[str]]:
    """Books by an author named in full, by surname, or with a typo."""
    return _resolve(name, entries, lambda e: e.author, last_word_too=True)


@dataclass
class CatalogResult:
    op: str
    books: list[BookEntry]          # the answer set; count = len(books), never a separate number
    total: int                      # books in the catalogue (canaries excluded)
    query: str = ""                 # the title or author asked about (has / by_author)
    resolved: bool = True           # has / by_author: something matched
    suggestions: list[str] = field(default_factory=list)   # closest names when nothing did

    def as_state(self) -> dict:
        """What the state, the events and the eval carry."""
        return {"op": self.op, "count": len(self.books), "total": self.total,
                "books": [b.key for b in self.books], "query": self.query,
                "resolved": self.resolved, "suggestions": list(self.suggestions)}


def run_catalog(request: dict, entries: list[BookEntry] | None = None) -> CatalogResult:
    """One validated request against the catalogue (list_books unless given)."""
    entries = list_books() if entries is None else entries
    op = request["op"]
    if op in ("count", "list"):
        return CatalogResult(op, list(entries), len(entries))
    if op == "has":
        matches, suggestions = resolve_title(request["title"], entries)
        return CatalogResult(op, matches, len(entries), request["title"], bool(matches), suggestions)
    matches, suggestions = resolve_author(request["author"], entries)
    return CatalogResult(op, matches, len(entries), request["author"], bool(matches), suggestions)


def render_catalog(result: CatalogResult) -> str:
    """The answer, from templates and the result only: the number in the text
    is len() of the list under it. Titles are index metadata, i.e. data; the
    interfaces neutralize markup in this text as they do for model answers."""
    items = "\n".join(f"- {b.key}" for b in result.books)
    n = len(result.books)
    if result.op == "count":
        return t("catalog_count", n=n)
    if result.op == "list":
        return t("catalog_list", n=n, items=items)
    if result.op == "has":
        if result.resolved:
            return t("catalog_has_yes", items=items)
        text = t("catalog_has_no", q=result.query)
        return text + (t("catalog_closest_titles", items="; ".join(result.suggestions)) if result.suggestions else "")
    if result.resolved:
        authors = ", ".join(sorted({b.author for b in result.books if b.author}))
        return t("catalog_by_author", n=n, author=authors or result.query, items=items)
    text = t("catalog_by_author_none", q=result.query)
    return text + (t("catalog_closest_authors", items="; ".join(result.suggestions)) if result.suggestions else "")
