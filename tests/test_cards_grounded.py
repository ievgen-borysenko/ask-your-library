"""Cards must not invent contents of the edition they describe.

The Kobzar card once claimed the collection includes "Kateryna"; the Gutenberg
edition in the corpus does not. Every work title a card names - in bold
(**"Title"**) or introduced by words like poem/story/chapter/titled - must
occur in the book: in the prepared text when it is present locally, otherwise
in the committed chapter titles under corpus/toc/ (so CI checks it too).
"""
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CARDS = REPO / "corpus" / "cards"
PREPARED = REPO / "data" / "prepared"
TOC = REPO / "corpus" / "toc"

BOLD = re.compile(r'\*\*"([^"]{3,80})"\*\*')
INTRODUCED = re.compile(
    r'(?:poems?|stories|story|tales?|chapters?|essays?|treatises?|entitled|titled|called)'
    r'(?:\s+(?:such\s+as|like|include|including|named))?\s+"([^"]{3,80})"', re.I)


def quoted_titles(card_text: str) -> list[str]:
    return sorted(set(BOLD.findall(card_text)) | set(INTRODUCED.findall(card_text)))


def title_key(title: str) -> str:
    words = re.sub(r"[^a-z0-9 ]", " ", title.lower()).split()
    return " ".join(words[:4])


def haystack_for(book_id: str) -> str | None:
    prepared = PREPARED / f"{book_id}.json"
    if prepared.exists():
        doc = json.loads(prepared.read_text(encoding="utf-8"))
        return " ".join(c["title"] + " " + c["text"] for c in doc["chapters"]).lower()
    toc = TOC / f"{book_id}.json"
    if toc.exists():
        return " ".join(json.loads(toc.read_text(encoding="utf-8"))).lower()
    return None


def test_quoted_work_titles_exist_in_the_book():
    missing, checked = [], 0
    for card in sorted(CARDS.glob("*.md")):
        haystack = haystack_for(card.stem)
        if haystack is None:
            continue
        checked += 1
        for title in quoted_titles(card.read_text(encoding="utf-8")):
            key = title_key(title)
            if key and key not in haystack:
                missing.append(f"{card.stem}: {title!r}")
    assert checked >= 30, f"only {checked} cards had a text or TOC to check against"
    assert not missing, "cards quote works absent from the edition:\n" + "\n".join(missing)


def test_toc_is_committed_for_every_manifest_book():
    import yaml
    manifest = yaml.safe_load((REPO / "corpus" / "manifest.yaml").read_text(encoding="utf-8"))
    ids = [b["id"] for b in manifest["books"]]
    absent = [i for i in ids if not (TOC / f"{i}.json").exists()]
    assert not absent, f"corpus/toc missing for: {absent}"


def test_title_key_normalizes_punctuation_and_length():
    assert title_key('Naimechka; or The Servant') == "naimechka or the servant"
    assert title_key("A Scandal in Bohemia — part one") == "a scandal in bohemia"


def test_toc_titles_are_unique_within_each_book():
    """Repeated chapter titles collide in chunk_id (the RRF dedupe key) and in
    the get_chapter lookup; the prepare stage must disambiguate them."""
    dupes = []
    for toc in sorted(TOC.glob("*.json")):
        titles = json.loads(toc.read_text(encoding="utf-8"))
        seen = set()
        for t in titles:
            if t in seen:
                dupes.append(f"{toc.stem}: {t!r}")
            seen.add(t)
    assert not dupes, "duplicate chapter titles in corpus/toc:\n" + "\n".join(dupes[:10])
