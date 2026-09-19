"""CI guards for the engineer's shelf (#58): the manifest, the converter, the
shape of a prepared file, and the rule that three of the works never get a card.

Nothing here fetches anything. The shelf's text is not in this repository and
the suite is offline by construction (tests/egress_guard.py), so the reading
paths are exercised on small inline fixtures — a page with a navigation bar
around it, a PDF's text layer with its page furniture — and the checks against
the real shelf are limited to what IS committed: corpus-tech/manifest.yaml and
corpus-tech/toc/.

The licence checks here are about completeness, not about truth: a test cannot
read sre.google. What it can do is refuse an entry that claims a licence without
saying where the work states it and when that page was read, which is the shape
of the claim corpus-tech/README.md makes on the repository's behalf.
"""
import contextlib
import inspect
import importlib.util
import json
import re
import subprocess
import sys
import types
from datetime import date
from pathlib import Path

import pytest
import yaml

from ask_your_library import config, llm
from ask_your_library.ingest import chunking

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "corpus-tech" / "manifest.yaml"
TOC_DIR = REPO / "corpus-tech" / "toc"

spec = importlib.util.spec_from_file_location(
    "fetch_tech_shelf", REPO / "scripts" / "fetch_tech_shelf.py")
shelf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shelf)

SHA256 = re.compile(r"[0-9a-f]{64}")
URL = re.compile(r"https://\S+$")
FETCH_KINDS = {"html-chapters", "git-markdown", "git-html", "pdf", "arxiv-html", "arxiv-pdf"}
KINDS = {"book", "paper", "guide"}
# The works whose licence forbids sharing a derivative: no model-written card of
# them is ever committed, and the one they get is written under AYL_HOME only.
NO_CARD = {"sre-book", "sre-workbook", "swe-at-google"}
CARDS_DIR = REPO / "corpus-tech" / "cards"


def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def works() -> list[dict]:
    return manifest()["works"]


# --- 1. the manifest ---------------------------------------------------------

def test_every_work_carries_the_fields_a_build_and_a_reader_need():
    """id, title, author, year, kind, source and fetch are what the script
    reads; `note` is what a reviewer reads. A missing one is not a smaller
    entry — it is an entry that either cannot be built or cannot be judged."""
    problems = []
    for work in works():
        where = work.get("id", work.get("title", "<unnamed>"))
        for field in ("id", "title", "author", "year", "kind", "source", "fetch",
                      "pin", "cards", "note"):
            if work.get(field) in (None, "", []):
                problems.append(f"  {where}: no {field}")
        if work.get("kind") not in KINDS:
            problems.append(f"  {where}: kind {work.get('kind')!r} is not one of {sorted(KINDS)}")
        if work.get("fetch") not in FETCH_KINDS:
            problems.append(f"  {where}: fetch {work.get('fetch')!r} is not a kind the "
                            f"script knows ({sorted(FETCH_KINDS)})")
        if work.get("pin") not in shelf.PIN_KINDS:
            problems.append(f"  {where}: pin {work.get('pin')!r} is not one of "
                            f"{list(shelf.PIN_KINDS)} — it decides what the sha256 is "
                            f"taken of")
        if work.get("cards") not in shelf.CARD_POLICIES:
            problems.append(f"  {where}: cards must be one of {list(shelf.CARD_POLICIES)}, "
                            f"not {work.get('cards')!r} — it decides whether a derivative "
                            f"may be distributed")
        if work.get("cards") == "structure":
            for field in shelf.STRUCTURE_FIELDS:
                if not work.get(field):
                    problems.append(f"  {where}: a structure card needs {field}")
            if not URL.fullmatch(str(work.get("about_source", ""))):
                problems.append(f"  {where}: about_source is not an https URL")
            if not isinstance(work.get("about_checked"), date):
                problems.append(f"  {where}: about_checked is not a date")
    assert not problems, "corpus-tech/manifest.yaml entries that cannot be built or judged:\n" \
                         + "\n".join(problems)


def test_every_licence_claim_says_what_where_and_when():
    """A licence identifier on its own is a claim with nothing behind it. Each
    entry also names the licence text, the page where the work itself states the
    licence, and the date that page was read — so the claim can be re-checked by
    somebody who was not there. A work whose statement could not be confirmed
    carries `licence_unverified: true` and is then allowed to have no statement
    page, because saying so is the honest form of not knowing."""
    problems = []
    for work in works():
        where = work["id"]
        if not work.get("licence"):
            problems.append(f"  {where}: no licence")
        elif not shelf.LICENCE_ID.fullmatch(str(work["licence"])):
            problems.append(f"  {where}: licence {work['licence']!r} is not an SPDX-style "
                            f"identifier (CC-BY-NC-ND-4.0, not CC BY-NC-ND 4.0)")
        for field in ("licence_url", "licence_statement"):
            value = work.get(field)
            if work.get("licence_unverified") and field == "licence_statement":
                continue
            if not isinstance(value, str) or not URL.fullmatch(value):
                problems.append(f"  {where}: {field} is {value!r}, not an https URL")
        if not work.get("licence_unverified") and not work.get("licence_checked"):
            problems.append(f"  {where}: no licence_checked date — a licence nobody dated "
                            f"is a licence nobody checked")
    assert not problems, "licence claims that cannot be re-checked:\n" + "\n".join(problems)


def test_every_work_pins_every_file_it_was_built_from():
    """The shelf's text is fetched, not committed, so the pins are the only
    thing that says which edition the golden answers were written against. Per
    file, and each one a 64-hex digest: an all-digit digest would come back from
    YAML as an int and never match anything."""
    problems = []
    for work in works():
        pins = work.get("sources") or {}
        if not pins:
            problems.append(f"  {work['id']}: no sources pinned")
            continue
        for name, digest in pins.items():
            if not isinstance(digest, str) or not SHA256.fullmatch(digest):
                problems.append(f"  {work['id']}/{name}: {digest!r} is no sha256")
    assert not problems, ("unpinned sources — an unpinned fetch is verified against nothing:\n"
                          + "\n".join(problems)
                          + "\npin them with `uv run scripts/fetch_tech_shelf.py "
                            "--stage checksums`")


def test_ids_and_title_author_pairs_are_unique():
    """A duplicate id overwrites another work's prepared file and its chapter
    list; a duplicate (title, author) collides in the index's book field, which
    is the key the agent cites and filters on."""
    entries = works()
    ids = [work["id"] for work in entries]
    assert len(ids) == len(set(ids)), \
        f"duplicate ids: {sorted({i for i in ids if ids.count(i) > 1})}"
    pairs = [(work["title"], work["author"]) for work in entries]
    assert len(pairs) == len(set(pairs)), "duplicate (title, author) — the index's book key"


# --- 2. no card for a NoDerivatives work -------------------------------------

def test_the_no_derivatives_works_get_a_model_card_only_under_ayl_home(tmp_path, monkeypatch):
    """The owner's decision of 2026-09-19: a model-written card of a CC BY-NC-ND
    work may exist on the reader's machine (the licence grants making an
    adaptation, 2(a)(1)(B)) and never in the repository (it withholds sharing
    one). So the three are offered to the card stage, and every one of them is
    routed to AYL_HOME — never to corpus-tech/cards/."""
    monkeypatch.setattr(config, "AYL_HOME", tmp_path / "home")
    offered = {work["id"]: work for work in shelf.card_targets(manifest())}
    assert set(offered) == {work["id"] for work in works()}, \
        "every work of the shelf may carry a model-written card somewhere"
    for key in sorted(NO_CARD):
        folder = shelf.card_dir(offered[key])
        assert folder == (tmp_path / "home" / "cards" / "tech").resolve(), key
        assert not folder.is_relative_to(REPO), f"{key}: a model card inside the repository"
    committed = {key for key, work in offered.items() if shelf.card_dir(work) == shelf.CARDS_DIR}
    assert committed == {work["id"] for work in works() if work["cards"] == "shared"}
    assert not (committed & NO_CARD)


def test_the_cards_value_and_the_licence_agree():
    """Read the other way round: a work that says ND in its licence is
    `structure` with `local_card: true`, whoever adds it later and whatever they
    meant — not `shared`, whose card is committed."""
    # Read off the licence string here, independently of the script's helper
    # and of NO_CARD, so a new ND work is caught the day it is added.
    nd = {work["id"] for work in works()
          if "ND" in re.split(r"[-\s_]+", work["licence"].upper())}
    by_id = {work["id"]: work for work in works()}
    wrong = sorted(key for key in nd if by_id[key]["cards"] != "structure")
    assert not wrong, f"NoDerivatives works not marked `cards: structure`: {wrong}"
    no_local = sorted(key for key in nd if by_id[key].get("local_card") is not True)
    assert not no_local, f"NoDerivatives works without `local_card: true`: {no_local}"
    assert nd == {work["id"] for work in works() if shelf.no_derivatives(work)} == NO_CARD
    stray = sorted(work["id"] for work in works() if "local_card" in work
                   and work["cards"] != "structure")
    assert not stray, f"`local_card` beside something other than `cards: structure`: {stray}"


@pytest.mark.parametrize("licence", ["CC-BY-NC-ND-4.0", "CC BY-NC-ND 4.0", "CC BY-ND 4.0",
                                     "cc-by-nd-4.0", "CC BY NC ND 4.0", ""])
def test_a_no_derivatives_licence_is_recognised_in_any_spelling(licence):
    """The check fails closed: a spaced or lower-case form is still ND, and a
    work with no licence at all is treated as one."""
    assert shelf.no_derivatives({"licence": licence})


@pytest.mark.parametrize("licence", ["CC-BY-4.0", "CC BY-SA 4.0", "MIT", "Apache-2.0"])
def test_a_licence_that_allows_adaptation_is_not_read_as_no_derivatives(licence):
    assert not shelf.no_derivatives({"licence": licence})


def test_a_spaced_no_derivatives_work_is_never_offered_as_a_shared_card(tmp_path, monkeypatch):
    """The licence is read in any spelling: an ND work mislabelled `shared` is
    not offered at all, and one labelled `local` is offered and routed to
    AYL_HOME."""
    spaced = {"id": "spaced", "licence": "CC BY-NC-ND 4.0", "cards": "shared"}
    assert shelf.card_targets({"works": [spaced]}) == []
    monkeypatch.setattr(config, "AYL_HOME", tmp_path / "home")
    local = dict(spaced, cards="local")
    assert shelf.card_targets({"works": [local]}) == [local]
    assert shelf.card_dir(local).is_relative_to(tmp_path / "home")
    # and even asked directly, an ND work's model card is never the committed folder
    assert shelf.model_card_is_local(spaced)


def test_a_licence_nobody_confirmed_is_never_shared():
    """A card committed to the repository is distributed by it. A work whose
    licence could not be confirmed on the source may still be read and carded on
    the reader's machine, but nothing of it goes into the tree on a guess."""
    wrong = [work["id"] for work in works()
             if work.get("licence_unverified") and work["cards"] != "local"]
    assert not wrong, f"works with an unverified licence and a committed card: {wrong}"


def committed_cards() -> dict[str, str]:
    return {path.stem: path.read_text(encoding="utf-8") for path in CARDS_DIR.glob("*.md")}


def test_every_committed_card_is_for_a_work_that_may_have_one():
    """The rule as it applies to what is actually in the repository. A card is
    the one file of this shelf that IS committed, so a summary of a NoDerivatives
    work would be distributed by this repository the moment it was added — this
    test is what stands between that and a green suite. And a `local` work's
    card never lands here at all: it is written under AYL_HOME."""
    by_policy = {work["id"]: work["cards"] for work in works()}
    written = set(committed_cards())
    assert written <= set(by_policy), \
        f"cards for works the manifest does not know: {sorted(written - set(by_policy))}"
    local = sorted(key for key in written if by_policy[key] == "local")
    assert not local, f"a `local` card is committed: {local}"


def test_a_no_derivatives_work_has_a_structure_card_and_nothing_model_written():
    """The committed card of a NoDerivatives work is its structure card: the
    three code-built sections, `card_model: none`, and none of the sections a
    model writes — a summary committed here would be the derivative the licence
    withholds."""
    cards = committed_cards()
    for key in sorted(NO_CARD):
        assert key in cards, f"{key}: no structure card committed"
        meta, body = chunking.parse_frontmatter(cards[key])
        assert meta["card_kind"] == "structure" and meta["card_model"] == "none", key
        assert re.findall(r"^## (.*)$", body, re.M) == list(shelf.STRUCTURE_SECTIONS), key
        for model_section in shelf.CARD_MODEL_SECTIONS:
            assert f"## {model_section}" not in body, f"{key}: has a {model_section}"


def test_every_committed_structure_card_is_exactly_what_the_code_builds():
    """"Built by code, with no model" as a fact about the files rather than a
    promise: each committed structure card is byte-identical to what
    `structure_card_text` makes from the manifest and the committed chapter
    list. A hand edit — a helpful sentence of summary added later — fails here."""
    cards = committed_cards()
    for work in shelf.structure_targets(manifest()):
        expected = shelf.structure_card_text(work, shelf.committed_chapters(work))
        assert cards.get(work["id"]) == expected, \
            (f"{work['id']}: the committed structure card is not what the code builds — "
             f"run `uv run scripts/fetch_tech_shelf.py --stage structure-cards`")


def test_a_structure_card_quotes_the_description_it_names_and_says_where_from():
    """The About section is the manifest's `about`, verbatim, as a quotation,
    followed by the page it was copied from: the reproduction is attributed, or
    it is not the kind the licence grants."""
    for work in shelf.structure_targets(manifest()):
        text = shelf.structure_card_text(work, ["One", "Two"])
        about = " ".join(work["about"].split())
        assert f"> {about}\n" in text
        assert f"<{work['about_source']}>" in text
        assert f"<{work['licence_url']}>" in text


def test_every_committed_model_card_carries_its_provenance_and_the_toc():
    """The shared cards as committed: which model wrote each and when, the
    manifest's book key as the H1, and a Structure section that is the
    committed chapter list and not the model's."""
    cards = committed_cards()
    shared = [work for work in shelf.card_targets(manifest()) if work["cards"] == "shared"]
    missing = sorted(work["id"] for work in shared if work["id"] not in cards)
    assert not missing, f"`shared` works with no committed card: {missing}"
    for work in shared:
        meta, body = chunking.parse_frontmatter(cards[work["id"]])
        where = work["id"]
        assert meta.get("card_model") and meta["card_model"] != "none", where
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta.get("card_built", ""))), where
        assert meta["source"] == f"{work['author']} — {work['title']}", where
        assert re.findall(r"^# (.*)$", body, re.M) == [f"{work['title']} — {work['author']}"]
        structure = shelf.card_sections(body)["Structure"]
        titles = shelf.committed_chapters(work)
        assert structure == "\n".join(f"- {title}" for title in titles), \
            f"{where}: Structure is not the committed chapter list"
        assert meta["card_kind"] == "shared", where
        assert meta["licence"] == work["licence"] and meta["licence_url"] == work["licence_url"]
        assert meta["adapted"].startswith("a model-written summary"), where
        assert ("card_licence" in meta) == shelf.share_alike(work), where


def test_every_committed_model_card_is_its_own_restamp():
    """The front matter and the chapter list of a model-written card are derived
    by code (`restamp_card`); a committed card that differs from its own restamp
    was edited by hand there, or restamped against an older manifest."""
    cards = committed_cards()
    for work in shelf.card_targets(manifest()):
        if work["cards"] == "shared" and work["id"] in cards:
            assert shelf.restamp_card(cards[work["id"]], work, shelf.committed_chapters(work)) \
                == cards[work["id"]], \
                f"{work['id']}: run `uv run scripts/fetch_tech_shelf.py --stage restamp-cards`"


def test_the_owasp_card_says_it_is_share_alike():
    meta, _ = chunking.parse_frontmatter(committed_cards()["owasp-llm-top-10-2025"])
    assert meta["card_licence"] == "CC-BY-SA-4.0"


def test_a_restamp_touches_no_model_written_section(card_shelf):
    card = (build(card_shelf) / "demo-work.md").read_text(encoding="utf-8")
    old = card.replace("- Introduction\n- III. Config", "- 1. Introduction\n- 2. III. Config")
    old = old.replace("card_kind: shared\n", "")
    new = shelf.restamp_card(old, WORK, ["Introduction", "III. Config"])
    assert new == card
    sections = shelf.card_sections(new.split("\n---\n", 1)[1])
    assert sections["Summary"] == "A demo work about configuration, in two chapters."


def test_there_is_no_local_card_folder_inside_the_repository():
    """Local cards used to go to a gitignored corpus-tech/cards-local/. They now
    live under AYL_HOME, outside the checkout — .gitignore is not a boundary, so
    the old folder and its ignore line are gone, and nothing names them."""
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "cards-local" not in ignored
    assert not hasattr(shelf, "CARDS_LOCAL_DIR")
    for path in (REPO / "scripts" / "fetch_tech_shelf.py",
                 REPO / "scripts" / "ingest_demo_corpus.py",
                 REPO / "corpus-tech" / "manifest.yaml", REPO / "corpus-tech" / "README.md"):
        assert "cards-local" not in path.read_text(encoding="utf-8"), path.name


def test_the_local_cards_folder_is_under_ayl_home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AYL_HOME", tmp_path / "home")
    assert shelf.local_cards_dir() == (tmp_path / "home" / "cards" / "tech").resolve()


def test_local_cards_are_refused_when_ayl_home_is_inside_a_git_work_tree(tmp_path, monkeypatch):
    """An AYL_HOME inside a git work tree — any repository, this checkout above
    all — is where one `git add` would commit what may never be shared, so no
    local card is written there."""
    other = tmp_path / "some-repo"
    (other / ".git").mkdir(parents=True)
    homes = [other / "ayl"]
    if (REPO / ".git").exists():
        homes.append(REPO / "corpus-tech" / "private")
    for home in homes:
        monkeypatch.setattr(config, "AYL_HOME", home)
        with pytest.raises(RuntimeError, match="inside the git work tree"):
            shelf.local_cards_dir()
        with pytest.raises(RuntimeError, match="inside the git work tree"):
            shelf.card_dir(dict(WORK, cards="local"))


# --- 2b. what a pin is taken of ----------------------------------------------

# The pages these publishers serve are not byte-stable, so a byte pin on them is
# red on every run and can never report the edit it exists to catch. Both cases
# below are the real ones, reduced to the smallest page that shows them.
NONCE_PAGE = ('<html><head><script nonce="{nonce}">var a=1;</script></head>'
              '<body><h2>Rule #4</h2><p>Keep the first model simple.</p>'
              '<script type="application/json" analytics>{analytics}</script>'
              '</body></html>')
CLOUDFLARE_PAGE = ('<html><body><h2>Preface</h2><p>Email '
                   '<a class="email" href="/cdn-cgi/l/email-protection#{key}">'
                   '<span class="__cf_email__" data-cfemail="{key}">'
                   '[email&#160;protected]</span></a> to comment.</p></body></html>')

TEXT_WORK = {"id": "pinned-by-text", "fetch": "html-chapters", "pin": "text"}


def digest_of_html(html: str, tmp_path: Path, name: str = "page.html") -> str:
    path = tmp_path / name
    path.write_text(html, encoding="utf-8")
    return shelf.digest_of(TEXT_WORK, path)


def test_a_per_response_nonce_does_not_change_a_text_pin(tmp_path):
    """developers.google.com stamps every response with a CSP nonce and an
    analytics blob whose JSON keys come out in a different order each time. Two
    fetches three seconds apart gave two different digests (#58); neither
    fragment is text of the book, and under the text pin the two hash the
    same."""
    first = digest_of_html(NONCE_PAGE.format(
        nonce="OUM2UctphZr7khAsNUmKlfJAa0bYkN",
        analytics='[{"dimension6": "en", "dimension1": "Signed out"}]'), tmp_path)
    second = digest_of_html(NONCE_PAGE.format(
        nonce="xK4pQ2vLmNrT8wZaYbCdEfGhIjKlMn",
        analytics='[{"dimension1": "Signed out", "dimension6": "en"}]'), tmp_path)
    assert first == second


def test_cloudflares_email_obfuscation_does_not_change_a_text_pin(tmp_path):
    """abseil.io is behind Cloudflare, which rewrites the book's "Email ... to
    comment" link with a fresh key on every response — three digests were
    observed for one unchanged page. The link's visible text does not move."""
    first = digest_of_html(CLOUDFLARE_PAGE.format(key="bddfd2d2d6ccc8d8cec9d4d2d3ce"), tmp_path)
    second = digest_of_html(CLOUDFLARE_PAGE.format(key="0b696464607a7e6e787f62646578"), tmp_path)
    assert first == second


def test_a_changed_paragraph_does_change_a_text_pin(tmp_path):
    """The other half, and the one that matters: a text pin still catches an
    edit to the book. Without this the rule above would be indistinguishable
    from not hashing anything."""
    same = NONCE_PAGE.format(nonce="n", analytics="[]")
    edited = same.replace("Keep the first model simple.",
                          "Keep the first model simple, and get the infrastructure right.")
    assert digest_of_html(same, tmp_path) != digest_of_html(edited, tmp_path)


def test_a_heading_that_disappears_changes_a_text_pin(tmp_path):
    """A chapter heading is text too: a page that loses one is a different
    page, however little of its prose moved."""
    same = NONCE_PAGE.format(nonce="n", analytics="[]")
    assert digest_of_html(same, tmp_path) != digest_of_html(
        same.replace("<h2>Rule #4</h2>", ""), tmp_path)


def test_a_bytes_pinned_work_is_hashed_as_the_file(tmp_path):
    """The other rule, unchanged: a PDF and a file served out of a git
    repository are byte-stable, and hashing them whole says more than hashing
    what a reader made of them."""
    path = tmp_path / "chapter.html"
    path.write_text(NONCE_PAGE.format(nonce="n", analytics="[]"), encoding="utf-8")
    work = dict(TEXT_WORK, pin="bytes")
    assert shelf.digest_of(work, path) == shelf.sha256_of(path)
    assert shelf.digest_of(TEXT_WORK, path) != shelf.sha256_of(path)


def test_the_pages_index_is_hashed_as_bytes_even_under_a_text_pin(tmp_path):
    """It is this script's record of which pages the publisher's table of
    contents listed and in which order, not a page to read: a chapter that
    appears, vanishes or moves has to be a failure."""
    path = tmp_path / shelf.PAGES_INDEX
    path.write_text(json.dumps([{"url": "https://example.invalid/a", "file": "a.html",
                                 "title": "A"}]), encoding="utf-8")
    assert shelf.digest_of(TEXT_WORK, path) == shelf.sha256_of(path)


def test_a_work_with_no_pin_rule_is_a_failure_not_a_guess(tmp_path):
    """The two rules answer different questions, so a work added without saying
    which one it wants must not be pinned by whichever is the fallback."""
    path = tmp_path / "page.html"
    path.write_text("<p>x</p>", encoding="utf-8")
    with pytest.raises(SystemExit, match="pin:"):
        shelf.digest_of({"id": "no-rule", "fetch": "html-chapters"}, path)


def test_the_pin_rule_and_the_fetch_kind_agree():
    """The rule as the shelf applies it: the two shapes fetched from a web page
    are pinned by text, and the ones fetched from a git repository or published
    as a PDF are pinned by bytes."""
    by_text = {"html-chapters", "arxiv-html"}
    wrong = [f"{work['id']}: fetch {work['fetch']}, pin {work['pin']}" for work in works()
             if (work["pin"] == "text") != (work["fetch"] in by_text)]
    assert not wrong, "pin rules that do not follow the fetch kind:\n" + "\n".join(wrong)


# --- 3. the chapter lists ----------------------------------------------------

def test_a_chapter_list_is_committed_for_every_work_and_for_no_other():
    """The text is gitignored, so these files are the whole record of what each
    work's chapters are. One per work, by id — a leftover from a renamed work
    would be a table of contents for a book nobody can fetch."""
    listed = {path.stem for path in TOC_DIR.glob("*.json")}
    expected = {work["id"] for work in works()}
    assert listed == expected, (f"missing chapter lists: {sorted(expected - listed)}; "
                                f"orphaned: {sorted(listed - expected)}")


def test_every_chapter_list_is_a_non_empty_list_of_titles():
    problems = []
    for path in sorted(TOC_DIR.glob("*.json")):
        chapters = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(chapters, list) or not chapters:
            problems.append(f"  {path.name}: not a non-empty list")
            continue
        for chapter in chapters:
            if not isinstance(chapter, str) or not chapter.strip():
                problems.append(f"  {path.name}: {chapter!r} is not a chapter title")
    assert not problems, "\n".join(problems)


def test_the_two_books_the_demo_asks_back_on_both_have_a_toil_chapter():
    """t02 in eval/golden/en-tech.yaml asks "the one about toil" and expects the
    agent to ask back between these two. The question is only honest while both
    books really do have that chapter, and this is where a re-pin that quietly
    changed an edition would be caught."""
    for work_id in ("sre-book", "sre-workbook"):
        chapters = json.loads((TOC_DIR / f"{work_id}.json").read_text(encoding="utf-8"))
        assert any("Eliminating Toil" in chapter for chapter in chapters), \
            f"{work_id} no longer has a chapter called 'Eliminating Toil'; t02 has to be re-read"


# --- 4. the HTML reader ------------------------------------------------------

PAGE = """
<html><head><title>ignored</title><style>.x{color:red}</style></head>
<body>
  <nav><a href="/">Home</a><a href="/next">Next chapter</a></nav>
  <div class="header">Site banner</div>
  <div id="content">
    <h1 class="heading">Eliminating Toil</h1>
    <p>Toil is <em>manual</em>, repetitive work.<sup><a href="#f1">19</a></sup></p>
    <h2>Toil Defined</h2>
    <blockquote><p class="quote">A quoted line of the demo page stays a quote.</p></blockquote>
    <ul><li>Manual</li><li>Repetitive</li></ul>
    <p>Not every task has all of these attributes.</p>
    <figure class="ltx_figure"><object data="diagram.svg"></object>
      <figcaption>Figure 1: toil over time.</figcaption></figure>
    <figure class="ltx_table"><pre>Question: how much toil?\nAnswer: less than 50%.</pre></figure>
    <figure class="ltx_figure"><img src="graph.png" alt="a graph"></figure>
  </div>
  <footer>&copy; Google</footer>
</body></html>
"""


def blocks_of(html: str, container: str | None = "div#content") -> list[tuple]:
    return shelf.read_html(html, container)


def test_the_reader_keeps_the_headings_and_the_paragraphs():
    blocks = blocks_of(PAGE)
    assert blocks[0] == ("heading", 1, "Eliminating Toil")
    assert ("heading", 2, "Toil Defined") in blocks
    text = [block[1] for block in blocks if block[0] == "text"]
    assert "Toil is manual, repetitive work." in text
    assert "> A quoted line of the demo page stays a quote." in text
    assert "- Manual" in text and "- Repetitive" in text


def test_the_reader_drops_the_page_around_the_chapter():
    """Navigation, banner, footer, styles — and the footnote marker, which would
    otherwise be indexed as a digit glued to the last word of a sentence."""
    rendered = shelf.render(blocks_of(PAGE), demote=1)
    for absent in ("Home", "Next chapter", "Site banner", "color:red", "© Google"):
        assert absent not in rendered, f"{absent!r} is page furniture and must not be indexed"
    assert "work.19" not in rendered and "19" not in rendered


def test_a_figure_is_kept_when_it_carries_text_and_dropped_when_it_is_a_picture():
    """arXiv renders a paper's appendices as figures: ReAct's prompt
    trajectories and Chain-of-Thought's exemplars are `<figure>` elements full
    of text, and they are what a reader of those papers quotes. So a figure is
    read like any other block — its listing, its table, its caption — and what
    is dropped is the picture itself, whether it arrives as `<img>` or as an
    `<object>`. A figure that held nothing but the picture leaves no text to
    flush and disappears on its own, with no rule of its own to say so."""
    rendered = shelf.render(blocks_of(PAGE), demote=1)
    assert "Question: how much toil?" in rendered, "a listing inside a figure is text"
    assert "Figure 1: toil over time." in rendered, "a caption is text too"
    for absent in ("diagram.svg", "graph.png", "a graph"):
        assert absent not in rendered, f"{absent!r} is a picture, not text"
    # Nothing is left behind by the image-only figure: no empty block, no stray
    # separator between the caption above it and whatever follows.
    assert "\n\n\n" not in rendered


def test_a_code_sample_is_indented_and_never_fenced():
    """A fence is invisible to a line-based splitter, and every reader of a
    prepared file is line-based: a "# comment" inside one opens a section of its
    own in `ayl-add` and in `write_toc` alike, cutting the chapter in half and
    naming it after a line of shell (#58)."""
    blocks = shelf.read_html(
        "<pre># Get all active machines\nmachines = decom.list()\n</pre>")
    body = shelf.render(blocks)
    assert "```" not in body
    assert not re.search(r"(?m)^#", body)
    assert "    # Get all active machines" in body
    assert "    machines = decom.list()" in body


def test_a_listing_rendered_one_line_per_element_cannot_cut_a_chapter():
    """arXiv wraps each line of a code listing in its own `<div>`, so a comment
    line arrives as a block of its own with "#" at column zero. Only that line is
    indented, and it keeps every character it had (#58)."""
    body = shelf.render(shelf.read_html(
        '<div class="ltx_listingline"># enable gradient-checkpointing</div>'
        '<div class="ltx_listingline">M3.gradient_checkpointing_enable()</div>'))
    assert "    # enable gradient-checkpointing" in body
    assert "M3.gradient_checkpointing_enable()" in body
    assert not re.search(r"(?m)^#{1,2}[ \t]", body)


def test_no_heading_inside_a_chapter_is_rendered_at_the_level_that_splits_chapters():
    """`##` is what ingest/chapters.py cuts sections on, and the chapter's own
    heading is written by the caller. The publishers disagree about levels —
    sre.google gives a chapter title `<h2>` and its sections `<h1>` — so a page
    heading may never come out as `##` however it was marked up."""
    rendered = shelf.render(blocks_of(PAGE), demote=1)
    assert not re.search(r"^## ", rendered, re.M), rendered[:200]
    assert "### Toil Defined" in rendered


def test_a_heading_that_only_repeats_the_chapter_title_is_not_printed_twice():
    rendered = shelf.render(blocks_of(PAGE), demote=1, skip_title="5. Eliminating Toil")
    assert "Eliminating Toil" not in rendered.split("\n\n")[0]


def test_the_container_is_what_decides_what_is_read():
    """Without it the whole body is read, navigation and all; with it, nothing
    outside the chapter can reach the index. Three shapes of selector, because
    the four publishers of this shelf need exactly those."""
    # Without a container the whole body is read: the banner comes with it.
    # (The navigation does not: `nav` is dropped wherever it stands.)
    whole = shelf.render(blocks_of(PAGE, container=None))
    assert "Site banner" in whole
    assert shelf._matches("div", {"id": "content"}, "div#content")
    assert shelf._matches("div", {"class": "devsite-article-body clearfix"},
                          "div.devsite-article-body")
    assert shelf._matches("section", {"data-type": "chapter"}, "section")
    assert not shelf._matches("div", {"id": "sidebar"}, "div#content")


# --- 5. the PDF reader -------------------------------------------------------

# A page break the way pdftotext writes one: the page number, then a form feed
# at the start of the next page, then the running header.
PDF_TEXT = (
    "R E A C T : S YNERGIZING R EASONING\n"
    "\n"
    "A BSTRACT\n"
    "We explore the use of language models.\n"
    "\n"
    "Contents\n"
    "1 I NTRODUCTION . . . . . . . . . . . 1\n"
    "\n"
    "1\n"
    "\n"
    "\x0cPublished as a conference paper at ICLR 2023\n"
    "\n"
    "1\n"
    "\n"
    "I NTRODUCTION\n"
    "\n"
    "A unique feature of human intelligence.\n"
    "\n"
    "2\n"
    "\n"
    "\x0cPublished as a conference paper at ICLR 2023\n"
    "\n"
    "60.4 Act\n"
    "20 Method\n"
    "\n"
    "2\n"
    "\n"
    "R ELATED W ORK\n"
    "\n"
    "Reasoning and acting have been studied.\n"
    "\n"
    "3\n"
    "\n"
    "\x0cPublished as a conference paper at ICLR 2023\n"
    "\n"
    "Prior work is discussed here.\n"
    "\n"
    "4\n"
    "\n"
    "\x0cPublished as a conference paper at ICLR 2023\n"
)


def test_the_pdf_reader_finds_the_sections_and_not_the_page_furniture():
    chapters = shelf.split_pdf_chapters(PDF_TEXT, r"^\d+(?:\.\d+)* [A-Z].{0,68}$", "Abstract")
    assert [title for title, _ in chapters] == ["Abstract", "1 Introduction", "2 Related Work"]
    assert "A unique feature of human intelligence." in chapters[1][1]
    body = "\n".join(text for _, text in chapters)
    assert "Published as a conference paper" not in body, \
        "the running header repeats on every page and is not text of the paper"


def test_a_table_row_and_a_table_of_contents_line_are_not_sections():
    """Both read exactly like a numbered heading. "60.4 Act" carries a measured
    value, and a contents line carries the dots that lead to a page number."""
    titles = [title for title, _ in
              shelf.split_pdf_chapters(PDF_TEXT, r"^\d+(?:\.\d+)* [A-Z].{0,68}$", "Abstract")]
    assert not any("Act" in title or "Method" in title for title in titles)
    assert not any("." * 3 in title for title in titles)


def test_a_missing_heading_does_not_end_the_paper():
    """Chain-of-Thought loses two of its own section headings to the column
    layout, so a run that stopped at the first gap would end that paper after
    four sections of eight."""
    headings = [(0, "1 One", (1,)), (1, "2 Two", (2,)), (2, "4 Four", (4,)),
                (3, "5 Five", (5,))]
    assert [title for _, title in shelf.numbered_chain(headings)] == \
        ["1 One", "2 Two", "4 Four", "5 Five"]


def test_a_table_in_the_middle_of_a_paper_does_not_capture_the_run():
    """A results table whose rows begin "1", "2" reads as a fresh sequence of
    sections. It may not take over the paper's own: the run that started at the
    first section is at least as long, and the earlier one wins."""
    headings = [(0, "1 Introduction", (1,)), (1, "2 Method", (2,)),
                (2, "1 Score", (1,)), (3, "2 Points", (2,)),
                (4, "3 Results", (3,)), (5, "4 Conclusion", (4,))]
    chain = [title for _, title in shelf.numbered_chain(headings)]
    assert chain == ["1 Introduction", "2 Method", "3 Results", "4 Conclusion"]


# --- 6. the shape of a prepared file -----------------------------------------

WORK = {"id": "demo-work", "title": "A Demo Work", "author": "A. Nonymous",
        "year": 2019, "kind": "guide",
        "fetch": "git-markdown", "licence": "MIT", "cards": "shared",
        "licence_url": "https://opensource.org/license/mit", "source": "https://example.invalid/"}


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    """One work fetched into a temporary raw directory, prepared and read back.
    Nothing downloads: the "fetched" files are written here."""
    raw = tmp_path / "raw" / WORK["id"]
    raw.mkdir(parents=True)
    (raw / "intro.md").write_text("Introduction\n============\n\nWhy this exists.\n",
                                  encoding="utf-8")
    (raw / "config.md").write_text("## III. Config\n### Store config in the environment\n\n"
                                   "An app's config is everything that varies.\n",
                                   encoding="utf-8")
    (raw / shelf.PAGES_INDEX).write_text(json.dumps(
        [{"url": "https://example.invalid/intro.md", "file": "intro.md", "title": ""},
         {"url": "https://example.invalid/config.md", "file": "config.md", "title": ""}]),
        encoding="utf-8")
    monkeypatch.setattr(shelf, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(shelf, "PREPARED_DIR", tmp_path / "prepared")
    monkeypatch.setattr(shelf, "TOC_DIR", tmp_path / "toc")
    shelf.prepare_work(WORK)
    return tmp_path


def test_a_prepared_file_is_what_ayl_add_reads_without_being_told_anything(prepared):
    """Front matter with `title:` and `author:` (the book key the agent cites
    and filters on), the work's title as the one `#`, and one `##` per chapter —
    the headings the folder ingest splits sections on."""
    text = (prepared / "prepared" / "demo-work.md").read_text(encoding="utf-8")
    assert text.startswith('---\ntitle: "A Demo Work"\nauthor: "A. Nonymous"\n---\n')
    assert re.findall(r"^# .*$", text, re.M) == ["# A Demo Work"]
    assert re.findall(r"^## .*$", text, re.M) == ["## Introduction", "## III. Config"]
    assert "An app's config is everything that varies." in text
    # The chapter's own heading is written once, above; not repeated in the body.
    assert "Introduction\n============" not in text


def test_a_body_line_that_reads_as_a_chapter_heading_is_refused(tmp_path, monkeypatch):
    """The prepared shape is a promise about where the chapters are. Text that
    would be cut in the wrong place is named, not written: a half-chapter and a
    section titled after a line of shell would otherwise reach the index and be
    cited from it."""
    raw = tmp_path / "raw" / "demo-work"
    raw.mkdir(parents=True)
    (raw / "intro.md").write_text("Introduction\n============\n\n"
                                  "Then a line that is not ours:\n\n## Not a chapter\n",
                                  encoding="utf-8")
    (raw / shelf.PAGES_INDEX).write_text(json.dumps(
        [{"url": "https://example.invalid/intro.md", "file": "intro.md", "title": ""}]),
        encoding="utf-8")
    monkeypatch.setattr(shelf, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(shelf, "PREPARED_DIR", tmp_path / "prepared")
    with pytest.raises(ValueError, match="chapter heading"):
        shelf.prepare_work(WORK)
    assert not (tmp_path / "prepared").exists(), "a file that cannot be cut was written anyway"


def test_the_chapter_list_written_beside_it_is_the_chapters_of_that_file(prepared):
    shelf.write_toc([WORK])
    chapters = json.loads((prepared / "toc" / "demo-work.json").read_text(encoding="utf-8"))
    assert chapters == ["Introduction", "III. Config"]


def test_a_markdown_work_keeps_its_own_subheadings(prepared):
    """`###` under a chapter is the author's structure and is carried across;
    only the chapter heading itself is lifted out."""
    text = (prepared / "prepared" / "demo-work.md").read_text(encoding="utf-8")
    assert "### Store config in the environment" in text


# --- 7. the card generator ---------------------------------------------------
# No network and no model: `llm_invoke` is replaced, so what is exercised is
# what this repository decides — which works are offered a card at all, what the
# model is shown of a work, and the shape of the file that comes back.

ND_WORK = {"id": "nd-work", "title": "A Work Nobody May Summarise", "author": "N. D. Author",
           "year": 2020, "kind": "book", "fetch": "html-chapters",
           "licence": "CC-BY-NC-ND-4.0", "cards": "structure"}

CARD_REPLY = """## Summary
A demo work about configuration, in two chapters.

## Key ideas
- **Config is not code** — everything that varies between deploys lives outside the codebase (III. Config)

## Terms
- **config** — everything that varies between deploys

## Themes
- **Separation** — the codebase says nothing about where it runs
"""


@pytest.fixture
def card_shelf(prepared, monkeypatch):
    """The prepared demo work, a temporary cards directory, and a fake model
    whose last prompt the test can read."""
    monkeypatch.setattr(shelf, "CARDS_DIR", prepared / "cards")
    monkeypatch.setattr(config, "AYL_HOME", prepared / "home")
    calls = []

    def fake_invoke(system, user, role):
        calls.append({"system": system, "user": user, "role": role})
        return types.SimpleNamespace(content=CARD_REPLY)

    monkeypatch.setattr(llm, "llm_invoke", fake_invoke)
    return types.SimpleNamespace(root=prepared, cards=prepared / "cards",
                                 cards_local=(prepared / "home" / "cards" / "tech").resolve(),
                                 calls=calls)


def build(card_shelf, entries=(WORK,), works_in_manifest=None, force=False):
    shelf.build_cards(list(entries), {"works": list(works_in_manifest or (WORK, ND_WORK))},
                      force=force)
    return card_shelf.cards


def test_a_card_is_never_generated_for_a_no_derivatives_work(card_shelf):
    """The rule of #58 enforced in the code that would break it: the stage runs
    over whatever `--work` selected, and a work outside `card_targets` is skipped
    before its text is read and before any model is called at all."""
    cards = build(card_shelf, entries=(WORK, ND_WORK))
    assert sorted(path.name for path in cards.glob("*.md")) == ["demo-work.md"]
    assert len(card_shelf.calls) == 1, "the NoDerivatives work reached the model"


def test_a_card_for_a_work_that_may_have_one_is_written(card_shelf):
    assert (build(card_shelf) / "demo-work.md").exists()


def test_the_card_has_the_front_matter_and_h1_the_classics_cards_have(card_shelf):
    """Same shape as corpus/cards/*.md, because the same `chunk_card` reads both:
    `source` is "Author — Title" and the H1 is "Title — Author", which is the
    book key the agent cites."""
    text = (build(card_shelf) / "demo-work.md").read_text(encoding="utf-8")
    meta, body = chunking.parse_frontmatter(text)
    assert meta["tags"] == "[book, tech-shelf]"
    assert meta["type"] == "book-card"
    assert meta["source"] == "A. Nonymous — A Demo Work"
    assert re.findall(r"^# .*$", body, re.M) == ["# A Demo Work — A. Nonymous"]


def test_the_card_records_which_backend_and_model_wrote_it(card_shelf):
    """A card built on the local model and one built on the hosted model are
    otherwise the same file. `card_model` is what tells the reader which they
    are looking at, and what says a card is due to be rebuilt (#58)."""
    text = (build(card_shelf) / "demo-work.md").read_text(encoding="utf-8")
    meta, _ = chunking.parse_frontmatter(text)
    assert meta["card_model"] == f"{config.LLM_BACKEND}/{config.ORCHESTRATOR_MODEL}"
    assert meta["card_built"] == date.today().isoformat()


def test_the_card_has_the_five_sections_a_non_fiction_card_needs_in_order(card_shelf):
    """Summary and Themes are the classics' cards'; Key ideas, Structure and
    Terms take the place of Plot and Characters, which a technical work has
    none of."""
    text = (build(card_shelf) / "demo-work.md").read_text(encoding="utf-8")
    assert re.findall(r"^## (.*)$", text, re.M) == [
        "Summary", "Key ideas", "Structure", "Terms", "Themes"]


def test_the_structure_section_is_the_prepared_texts_own_chapter_list(card_shelf):
    """The section that lets the card answer "which chapter covers X". It is not
    the model's: it is copied from the prepared file, in its order and its
    spelling, so a chapter can never be renamed or invented here."""
    text = (build(card_shelf) / "demo-work.md").read_text(encoding="utf-8")
    structure = shelf.card_sections(text)["Structure"]
    assert structure == "- Introduction\n- III. Config"


def test_the_card_is_cut_into_chunks_by_the_same_code_as_a_classics_card(card_shelf):
    """The point of matching the shape: `ingest_demo_corpus.py --stage cards
    --cards-dir corpus-tech/cards` indexes this file through `chunk_card`, so
    the shelf's cards land in `cards_<backend>` under the same book key the
    folder ingest minted for the work's text."""
    chunks = chunking.chunk_card(build(card_shelf) / "demo-work.md")
    assert {chunk.section for chunk in chunks} == {
        "Summary", "Key ideas", "Structure", "Terms", "Themes"}
    assert {chunk.book for chunk in chunks} == {"A Demo Work — A. Nonymous"}
    assert {chunk.note for chunk in chunks} == {"demo-work"}


def test_the_model_is_shown_the_chapter_list_whole_and_the_openings_only(card_shelf):
    """The budget of #58: never the whole book. Every chapter is named, so the
    card can list them all; of the text, only the opening of each chapter is
    sent."""
    monkeypatched = card_shelf
    build(monkeypatched)
    user = monkeypatched.calls[0]["user"]
    assert "- Introduction" in user and "- III. Config" in user
    assert "An app's config is everything that varies." in user


def test_a_long_chapter_is_cut_to_the_budget(card_shelf, monkeypatch):
    long_chapter = [("Introduction", "x" * 10_000)]
    excerpts, read = shelf.card_excerpts(long_chapter)
    assert read == 1
    assert len(excerpts) < shelf.CARD_CHAPTER_CHARS + 100
    monkeypatch.setattr(shelf, "CARD_TOTAL_CHARS", 1_000)
    _, read = shelf.card_excerpts(long_chapter * 3)
    assert read == 0, "a chapter opening that does not fit the total budget is left out"


def test_the_work_is_given_to_the_model_as_data_and_not_as_instructions(card_shelf):
    """Every character of a work on this shelf came off a publisher's web page,
    so it is wrapped as untrusted data (ADR-017): text that reaches a model from
    the internet is content, never an instruction."""
    build(card_shelf)
    user = card_shelf.calls[0]["user"]
    assert user.startswith("<work>")
    assert "<chapter_list" in user and "<chapter_openings" in user


def test_an_existing_card_is_kept_unless_force_is_given(card_shelf):
    cards = build(card_shelf)
    (cards / "demo-work.md").write_text("edited by hand\n", encoding="utf-8")
    build(card_shelf)
    assert (cards / "demo-work.md").read_text(encoding="utf-8") == "edited by hand\n"
    assert len(card_shelf.calls) == 1, "the model was called for a card already written"
    build(card_shelf, force=True)
    assert "## Summary" in (cards / "demo-work.md").read_text(encoding="utf-8")
    assert len(card_shelf.calls) == 2


def test_a_reply_missing_a_section_is_not_written_at_all(card_shelf, monkeypatch):
    """Half a card is worse than no card: it would be embedded, retrieved and
    quoted as if it were whole."""
    monkeypatch.setattr(llm, "llm_invoke", lambda system, user, role:
                        types.SimpleNamespace(content="## Summary\nOnly this.\n"))
    with pytest.raises(SystemExit) as raised:
        build(card_shelf)
    assert "Key ideas" in str(raised.value)
    assert not list(card_shelf.cards.glob("*.md"))


def test_a_reply_wrapped_in_a_code_fence_is_still_read(card_shelf, monkeypatch):
    """A small local model fences its Markdown often enough that refusing one
    would mean re-running the card rather than reading it."""
    monkeypatch.setattr(llm, "llm_invoke", lambda system, user, role:
                        types.SimpleNamespace(content=f"```markdown\n{CARD_REPLY}\n```"))
    text = (build(card_shelf) / "demo-work.md").read_text(encoding="utf-8")
    assert "```" not in text
    assert "A demo work about configuration" in text


def test_a_work_that_was_never_prepared_is_named_rather_than_summarised_empty(card_shelf):
    """The text is gitignored, so "prepare first" is the ordinary state of a
    fresh checkout, not an exotic failure."""
    absent = dict(WORK, id="never-prepared")
    with pytest.raises(FileNotFoundError, match="never-prepared"):
        build(card_shelf, entries=(absent,), works_in_manifest=(absent,))


# --- 8. three kinds of card --------------------------------------------------

def test_a_local_card_is_written_under_ayl_home_and_never_the_committed_folder(card_shelf):
    """The generator cannot put a `local` card where it would be committed: the
    folder is chosen in one place, `card_dir`, and a local one is AYL_HOME's."""
    local = dict(WORK, cards="local")
    build(card_shelf, entries=(local,), works_in_manifest=(local,))
    card = card_shelf.cards_local / "demo-work.md"
    assert card.exists()
    assert chunking.parse_frontmatter(card.read_text(encoding="utf-8"))[0]["card_kind"] == "local"
    assert not card_shelf.cards.exists() or not list(card_shelf.cards.glob("*.md"))


ND_LOCAL = dict(ND_WORK, id="demo-work", local_card=True, source="https://example.invalid/",
                licence_url="https://creativecommons.org/licenses/by-nc-nd/4.0/")


def test_a_no_derivatives_work_gets_its_model_card_under_ayl_home_only(card_shelf):
    """`cards: structure` with `local_card: true`: the model writes a card of
    the NoDerivatives work, and it lands under AYL_HOME, marked local — and
    nothing of it in the committed folder. The work's structure card is a
    separate stage and untouched."""
    build(card_shelf, entries=(ND_LOCAL,), works_in_manifest=(ND_LOCAL,))
    assert len(card_shelf.calls) == 1
    card = card_shelf.cards_local / "demo-work.md"
    meta, _ = chunking.parse_frontmatter(card.read_text(encoding="utf-8"))
    assert meta["card_kind"] == "local"
    assert meta["licence"] == "CC-BY-NC-ND-4.0"
    assert not card_shelf.cards.exists() or not list(card_shelf.cards.glob("*.md"))


def test_no_model_card_of_a_no_derivatives_work_is_written_in_the_repository(card_shelf):
    """Belt and braces: whatever `cards:` says, a NoDerivatives work's model card
    goes under AYL_HOME or nowhere. `shared` is a mislabel and is skipped before
    any model call; `local` and `structure` + `local_card` go to AYL_HOME."""
    mislabelled = dict(ND_LOCAL, cards="shared", local_card=False)
    build(card_shelf, entries=(mislabelled,), works_in_manifest=(mislabelled,))
    assert not card_shelf.calls, "a NoDerivatives work labelled shared reached the model"
    for value in ({"cards": "local", "local_card": False}, {"cards": "structure"}):
        work = dict(ND_LOCAL, **value)
        build(card_shelf, entries=(work,), works_in_manifest=(work,), force=True)
    assert len(card_shelf.calls) == 2
    assert not card_shelf.cards.exists() or not list(card_shelf.cards.glob("*.md"))
    assert (card_shelf.cards_local / "demo-work.md").exists()


def test_a_no_derivatives_card_is_not_built_when_ayl_home_is_in_a_repository(card_shelf,
                                                                              monkeypatch):
    """The refusal comes before the model is called and before anything is
    written: the work's text never leaves for a card that could not be kept."""
    monkeypatch.setattr(config, "AYL_HOME", REPO / "corpus-tech" / "private")
    if not (REPO / ".git").exists():
        (card_shelf.root / "repo" / ".git").mkdir(parents=True)
        monkeypatch.setattr(config, "AYL_HOME", card_shelf.root / "repo" / "ayl")
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        build(card_shelf, entries=(ND_LOCAL,), works_in_manifest=(ND_LOCAL,))
    assert not card_shelf.calls
    assert not (REPO / "corpus-tech" / "private").exists()


def test_the_prompt_allows_attributed_quotes_except_for_a_no_derivatives_work(card_shelf):
    """A shared card may quote the way a review does — marked and followed by
    the chapter; a NoDerivatives work's local card is paraphrase only."""
    build(card_shelf)
    build(card_shelf, entries=(ND_LOCAL,), works_in_manifest=(ND_LOCAL,), force=True)
    shared_prompt, nd_prompt = (call["system"] for call in card_shelf.calls)
    assert "You may quote the text sparingly" in shared_prompt
    assert "followed at once by the chapter it comes from" in shared_prompt
    assert "do not quote it" not in shared_prompt
    assert "do not quote it" in nd_prompt and "You may quote" not in nd_prompt
    for prompt in (shared_prompt, nd_prompt):
        assert "{words}" not in prompt and "## Key ideas" in prompt


def test_a_local_card_and_the_committed_card_of_one_book_keep_apart_rows(card_shelf):
    """The structure card and the local card of one ND work share a file name
    and an H1: they stay one book, under two row keys, so no chunk id is
    shared between them."""
    build(card_shelf, entries=(ND_LOCAL,), works_in_manifest=(ND_LOCAL,))
    chunks = chunking.chunk_card(card_shelf.cards_local / "demo-work.md")
    assert {chunk.note for chunk in chunks} == {"demo-work@local"}
    assert all(chunk.chunk_id.startswith("demo-work@local#") for chunk in chunks)
    assert {chunk.book for chunk in chunks} == {"A Work Nobody May Summarise — N. D. Author"}


def test_a_structure_work_is_skipped_by_the_model_stage(card_shelf):
    structure = dict(WORK, cards="structure")
    build(card_shelf, entries=(structure,), works_in_manifest=(structure,))
    assert not card_shelf.calls


def test_a_work_with_no_cards_value_is_local_and_an_unknown_value_is_refused():
    """No value means the conservative one: built where it is read, never
    committed. A value outside the three is a typo, not a fourth kind."""
    assert shelf.card_policy({"id": "x"}) == "local"
    with pytest.raises(ValueError, match="not one of"):
        shelf.card_policy({"id": "x", "cards": True})
    with pytest.raises(ValueError, match="not written by a model"):
        shelf.card_dir({"id": "x", "cards": "structure"})


def test_local_card_beside_shared_or_local_is_refused_by_the_script_itself(card_shelf):
    """Not only the manifest test: the functions the card stage runs through
    refuse `local_card` beside anything but `structure`, before any model call."""
    for value in ("shared", "local"):
        work = dict(WORK, cards=value, local_card=True)
        for call in (lambda: shelf.card_targets({"works": [work]}),
                     lambda: shelf.card_dir(work),
                     lambda: build(card_shelf, entries=(work,), works_in_manifest=(work,))):
            with pytest.raises(ValueError, match="belongs beside cards: structure"):
                call()
    assert not card_shelf.calls


def test_a_symlink_at_the_local_card_path_is_not_written_through(card_shelf, tmp_path):
    """The folder is outside any checkout, but the card's own name is a link
    into one: `write_text` would follow it, so the file is checked too — at
    build and at restamp."""
    repo = tmp_path / "a-checkout"
    (repo / ".git").mkdir(parents=True)
    target = repo / "leaked.md"
    target.write_text("untouched\n", encoding="utf-8")
    card_shelf.cards_local.mkdir(parents=True)
    (card_shelf.cards_local / "demo-work.md").symlink_to(target)
    with pytest.raises(RuntimeError, match="symlink"):
        build(card_shelf, entries=(ND_LOCAL,), works_in_manifest=(ND_LOCAL,), force=True)
    with pytest.raises(RuntimeError, match="symlink"):
        shelf.restamp_cards([ND_LOCAL], {"works": [ND_LOCAL]})
    assert not card_shelf.calls
    assert target.read_text(encoding="utf-8") == "untouched\n"


def test_a_restamp_refuses_a_bad_ayl_home_before_touching_any_card(card_shelf, monkeypatch):
    """Checked once, before the loop: a shared card listed first is not
    restamped and then the run stopped half way."""
    build(card_shelf)
    shared_card = card_shelf.cards / "demo-work.md"
    shared_card.write_text(shared_card.read_text(encoding="utf-8").replace(
        "card_kind: shared\n", ""), encoding="utf-8")
    before = shared_card.read_text(encoding="utf-8")
    repo = card_shelf.root / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setattr(config, "AYL_HOME", repo / "ayl")
    other = dict(ND_LOCAL, id="nd-other")
    with pytest.raises(RuntimeError, match="inside the git work tree"):
        shelf.restamp_cards([WORK, other], {"works": [WORK, other]})
    assert shared_card.read_text(encoding="utf-8") == before


def test_local_card_belongs_beside_structure_and_is_a_boolean():
    assert shelf.local_card({"id": "x", "cards": "structure", "local_card": True})
    assert not shelf.local_card({"id": "x", "cards": "structure"})
    for value in ("shared", "local"):
        with pytest.raises(ValueError, match="belongs beside cards: structure"):
            shelf.local_card({"id": "x", "cards": value, "local_card": True})
    with pytest.raises(ValueError, match="not true or false"):
        shelf.local_card({"id": "x", "cards": "structure", "local_card": "yes"})


STRUCTURE_WORK = dict(ND_WORK, licence_url="https://creativecommons.org/licenses/by-nc-nd/4.0/",
                      licence_statement="https://example.invalid/licence",
                      source="https://example.invalid/toc",
                      about="The publisher's own words,\n  folded over two lines.",
                      about_source="https://example.invalid/about",
                      about_checked=date(2026, 9, 19))


@pytest.fixture
def structure_shelf(tmp_path, monkeypatch):
    toc = tmp_path / "toc"
    toc.mkdir()
    (toc / "nd-work.json").write_text(json.dumps(["Preface", "1. Toil"]), encoding="utf-8")
    monkeypatch.setattr(shelf, "TOC_DIR", toc)
    monkeypatch.setattr(shelf, "CARDS_DIR", tmp_path / "cards")

    def refuse(*args, **kwargs):
        raise AssertionError("a structure card called a model")

    monkeypatch.setattr(llm, "llm_invoke", refuse)
    shelf.build_structure_cards([STRUCTURE_WORK, WORK], {"works": [STRUCTURE_WORK, WORK]})
    return tmp_path / "cards"


def test_a_structure_card_is_built_by_code_for_structure_works_only(structure_shelf):
    assert sorted(path.name for path in structure_shelf.glob("*.md")) == ["nd-work.md"]


def test_a_structure_card_has_about_structure_and_facts_and_nothing_else(structure_shelf):
    text = (structure_shelf / "nd-work.md").read_text(encoding="utf-8")
    meta, body = chunking.parse_frontmatter(text)
    assert meta["card_kind"] == "structure" and meta["card_model"] == "none"
    assert "card_built" not in meta, "a build date would make the card differ run to run"
    assert meta["source"] == "N. D. Author — A Work Nobody May Summarise"
    assert re.findall(r"^# .*$", body, re.M) == ["# A Work Nobody May Summarise — N. D. Author"]
    assert re.findall(r"^## (.*)$", body, re.M) == ["About", "Structure", "Facts"]
    assert "> The publisher's own words, folded over two lines.\n" in body
    assert shelf.card_sections(body)["Structure"] == "- Preface\n- 1. Toil"


def test_a_structure_card_is_cut_into_chunks_under_the_books_key(structure_shelf):
    chunks = chunking.chunk_card(structure_shelf / "nd-work.md")
    assert {chunk.section for chunk in chunks} == {"About", "Structure", "Facts"}
    assert {chunk.book for chunk in chunks} == {"A Work Nobody May Summarise — N. D. Author"}


def test_a_structure_card_without_the_description_is_refused():
    with pytest.raises(ValueError, match="about_source"):
        shelf.structure_card_text(dict(STRUCTURE_WORK, about_source=""), ["One"])


def load_ingest(name: str):
    ingest_spec = importlib.util.spec_from_file_location(
        name, REPO / "scripts" / "ingest_demo_corpus.py")
    ingest = importlib.util.module_from_spec(ingest_spec)
    ingest_spec.loader.exec_module(ingest)
    return ingest


def test_the_cards_table_reads_the_committed_and_the_local_folder_together(tmp_path):
    """`ingest_demo_corpus.py --stage cards --cards-dir A --cards-dir B`: the
    local folder may not exist; a local card (`card_kind: local`) of a book that
    also has a committed card is read beside it; two cards under one row key
    are refused rather than indexed twice under one chunk id."""
    ingest = load_ingest("ingest_demo_corpus_cards")
    shared, local = tmp_path / "cards", tmp_path / "home" / "cards" / "tech"
    shared.mkdir()
    (shared / "a.md").write_text("# A\n", encoding="utf-8")
    assert [p.name for p in ingest.card_files([shared, local])] == ["a.md"]
    local.mkdir(parents=True)
    (local / "b.md").write_text("# B\n", encoding="utf-8")
    assert [p.name for p in ingest.card_files([shared, local])] == ["a.md", "b.md"]
    (local / "a.md").write_text("---\ncard_kind: local\n---\n# A\n", encoding="utf-8")
    assert [p.parent.name for p in ingest.card_files([shared, local])] == ["cards", "tech", "tech"]
    (local / "a.md").write_text("# A again\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="a.md"):
        ingest.card_files([shared, local])


def test_cards_dir_takes_a_folder_under_the_home_directory(monkeypatch, tmp_path):
    """The documented command names `~/AskYourLibrary/cards/tech`; a quoted or
    `--cards-dir=` form reaches the script unexpanded, so the script expands it."""
    ingest = load_ingest("ingest_demo_corpus_home")
    seen = {}
    monkeypatch.setattr(ingest, "ingest_cards_table",
                        lambda backend, dirs: seen.setdefault("dirs", dirs))
    monkeypatch.setattr(ingest, "ingest_lock", lambda *args, **kwargs: contextlib.nullcontext())
    monkeypatch.setattr(sys, "argv", ["ingest_demo_corpus.py", "--stage", "cards",
                                      "--cards-dir", "corpus-tech/cards",
                                      "--cards-dir=~/AskYourLibrary/cards/tech"])
    ingest.main()
    assert seen["dirs"][1] == Path.home() / "AskYourLibrary" / "cards" / "tech"


def test_cards_dir_belongs_to_the_cards_stage(monkeypatch, capsys):
    """Like `--chunker`: a flag another stage would ignore is refused, not
    silently dropped."""
    ingest = load_ingest("ingest_demo_corpus_flags")
    monkeypatch.setattr(sys, "argv", ["ingest_demo_corpus.py", "--stage", "all",
                                      "--cards-dir", "corpus-tech/cards"])
    with pytest.raises(SystemExit) as raised:
        ingest.main()
    assert raised.value.code == 2
    assert "--cards-dir belongs to --stage cards" in capsys.readouterr().err


@pytest.mark.parametrize("toc_title, page_title", [
    ("5. Eliminating Toil", "Eliminating Toil"),
    ("III. Config", "Config"),
    ("Appendix B. A Collection of Best Practices", "A Collection of Best Practices"),
    ("Chapter 2. Culture", "Culture"),
])
def test_same_heading_ignores_the_numbering_the_contents_adds(toc_title, page_title):
    assert shelf.same_heading(toc_title, page_title)


def test_same_heading_does_not_eat_a_title_that_starts_with_a_capital_letter():
    """"Eliminating" is not appendix E, and "A Collection" is not appendix A."""
    assert not shelf.same_heading("Eliminating Toil", "liminating Toil")
    assert not shelf.same_heading("A Collection", "Collection")


# --- 9. no text of a work where the repository would share it ----------------
# These read corpus-tech/prepared/, which is gitignored: on a machine that has
# built the shelf they run, and in CI — where nothing is prepared — they skip
# and say why. The shelf's builder is who they are for: they are what stands
# between a note written with the book open and a passage committed by mistake.

PREPARED = REPO / "corpus-tech" / "prepared"
WORD = re.compile(r"[\w'’]+")


def word_list(text: str) -> list[str]:
    return WORD.findall(text.lower())


def verbatim_runs(text: str, source_grams: set, size: int, allowed) -> list[str]:
    """Every maximal run of `size`+ words of `text` that also stands in the
    source, minus the runs `allowed` accepts (names, titles, chapter titles)."""
    words, runs, i = word_list(text), [], 0
    while i <= len(words) - size:
        if tuple(words[i:i + size]) in source_grams:
            j = i + size
            while j < len(words) and tuple(words[j - size + 1:j + 1]) in source_grams:
                j += 1
            run = words[i:j]
            if not allowed(run):
                runs.append(" ".join(run))
            i = j
        else:
            i += 1
    return runs


def grams_of(words: list[str], size: int) -> set:
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def name_and_title_filter(work_ids: list[str]):
    """A run is a name or a title, not a passage, when every word of it belongs
    to the manifest's titles and author lists, or it sits inside one chapter
    title of the work."""
    vocabulary = {"and", "eds", "title", "author"}  # + the prepared front matter keys
    for work in works():
        vocabulary |= set(word_list(f"{work['title']} {work['author']}"))
    titles = [" ".join(word_list(title))
              for work_id in work_ids for title in json.loads(
                  (TOC_DIR / f"{work_id}.json").read_text(encoding="utf-8"))]

    def allowed(run: list[str]) -> bool:
        joined = " ".join(run)
        return set(run) <= vocabulary or any(joined in title for title in titles)
    return allowed


def tracked_text_files() -> list[Path]:
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                            text=True, check=True).stdout.split("\0")
    files = []
    for name in filter(None, listed):
        path = REPO / name
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, IsADirectoryError, FileNotFoundError):
            continue
        files.append(path)
    return files


ND_RUN_WORDS = 8
SHARED_RUN_WORDS = 12


def test_no_tracked_file_holds_a_passage_of_a_no_derivatives_work():
    """No run of 8 or more words of a CC BY-NC-ND work's text in any tracked
    file. No file is exempt: the chapter lists and the structure cards pass
    because what they reproduce is names, titles and chapter titles, which the
    filter accepts — and an exemption would hide whatever else got into them."""
    nd_ids = [work["id"] for work in works() if shelf.no_derivatives(work)]
    absent = [work_id for work_id in nd_ids if not (PREPARED / f"{work_id}.md").exists()]
    if absent:
        pytest.skip(f"corpus-tech/prepared/ has no text of {absent} (gitignored; run "
                    f"`uv run scripts/fetch_tech_shelf.py` to build it) — nothing to compare")
    if not (REPO / ".git").exists():
        pytest.skip("not a git checkout: no list of tracked files")
    files = tracked_text_files()
    problems = []
    for work_id in nd_ids:
        source = grams_of(word_list((PREPARED / f"{work_id}.md").read_text(encoding="utf-8")),
                          ND_RUN_WORDS)
        allowed = name_and_title_filter([work_id])
        for path in files:
            relative = path.relative_to(REPO).as_posix()
            for run in verbatim_runs(path.read_text(encoding="utf-8"), source,
                                     ND_RUN_WORDS, allowed):
                problems.append(f"  {relative}: {work_id}: \"{run[:120]}\"")
    assert not problems, ("passages of a NoDerivatives work in tracked files — state the "
                          "fact in your own words and name the chapter:\n" + "\n".join(problems))


# A quotation a shared card may carry: text in double quotation marks, straight
# or curly, followed at once (after at most a comma or a full stop) by the
# chapter it comes from in parentheses — at most QUOTE_MAX_WORDS words inside,
# and at most QUOTES_PER_CARD of them per card, the promise the prompt makes.
#
# Quotation marks are PAIRED first, left to right, and only then is a pair asked
# whether a chapter follows it. Matching "quote + chapter" in one pattern would
# let the engine start at a stray closing mark — `the "SLO" term; <copied run>"
# (Ch)` — and exempt the copied run between two quotations that are not one. A
# card whose straight quotation marks do not pair, or whose curly ones do not
# balance, is reported rather than read.
QUOTE_PAIR = re.compile(r'"([^"]*)"|“([^“”]*)”')
ATTRIBUTION = re.compile(r"[,.]?[ \t]*\(([^()\n]+)\)")
QUOTE_MAX_WORDS = 25
QUOTES_PER_CARD = 3
# What an accepted quotation is replaced with before the verbatim check: a word
# no text holds, so the words either side of the quote cannot join into a run.
QUOTE_GAP = " qqquotationqqq "


def outside_attributed_quotes(text: str, titles: list[str]) -> tuple[str, list[str]]:
    """`text` with every attributed quotation cut out, and what is wrong with the
    card's quotation marks.

    Cut: a paired quotation of at most QUOTE_MAX_WORDS words, on one line, whose
    parenthesis right after it is a chapter title of the work. Anything else —
    no chapter after it, something else in the parenthesis, a longer quote —
    stays in the text and is held to the verbatim rule. Reported: straight marks
    that do not pair, curly ones that do not balance, and more than
    QUOTES_PER_CARD attributed quotations."""
    chapters = {" ".join(word_list(title)) for title in titles}
    problems = []
    if text.count('"') % 2:
        problems.append(f'an odd number of straight quotation marks ({text.count(chr(34))})')
    if text.count("“") != text.count("”"):
        problems.append(f"{text.count('“')} opening and {text.count('”')} closing curly "
                        f"quotation marks")
    pieces, last, exempt = [], 0, 0
    for pair in QUOTE_PAIR.finditer(text):
        quoted = pair.group(1) if pair.group(1) is not None else pair.group(2)
        attribution = ATTRIBUTION.match(text, pair.end())
        if (attribution and "\n" not in quoted
                and len(word_list(quoted)) <= QUOTE_MAX_WORDS
                and " ".join(word_list(attribution.group(1))) in chapters):
            exempt += 1
            pieces += [text[last:pair.start()], QUOTE_GAP]
            last = attribution.end()
    pieces.append(text[last:])
    if exempt > QUOTES_PER_CARD:
        problems.append(f"{exempt} attributed quotations, more than {QUOTES_PER_CARD}")
    return "".join(pieces), problems


def test_no_shared_card_copies_a_passage_of_its_work():
    """A shared card is a paraphrase with, at most, short quotations that say
    so. A run of 12 or more words of the work's own text, outside names, titles,
    chapter titles and quotations attributed to a chapter, is an excerpt that
    slipped through the prompt, and is reworded by hand with an `edited:` line.
    A NoDerivatives work has no shared card; its passages are held by the
    stricter test above, which no quotation mark exempts."""
    shared = [work for work in works() if work["cards"] == "shared"]
    assert not [work["id"] for work in shared if shelf.no_derivatives(work)]
    absent = [work["id"] for work in shared if not (PREPARED / f"{work['id']}.md").exists()]
    if absent:
        pytest.skip(f"corpus-tech/prepared/ has no text of {absent} (gitignored) — "
                    f"nothing to compare the cards with")
    problems = []
    for work in shared:
        card = (CARDS_DIR / f"{work['id']}.md").read_text(encoding="utf-8")
        _, body = chunking.parse_frontmatter(card)
        body = re.sub(r"(?ms)^## Structure\n.*?(?=^## |\Z)", "", body.split("\n", 2)[-1])
        body, quote_problems = outside_attributed_quotes(body, shelf.committed_chapters(work))
        problems += [f"  {work['id']}: {problem}" for problem in quote_problems]
        source = grams_of(word_list((PREPARED / f"{work['id']}.md").read_text(encoding="utf-8")),
                          SHARED_RUN_WORDS)
        for run in verbatim_runs(body, source, SHARED_RUN_WORDS,
                                 name_and_title_filter([work["id"]])):
            problems.append(f"  {work['id']}: \"{run[:120]}\"")
    assert not problems, "shared cards that copy their work:\n" + "\n".join(problems)


def test_the_verbatim_check_finds_a_copied_run_and_passes_a_name():
    source = grams_of(word_list("one two three four five six seven eight nine ten"), 8)
    assert verbatim_runs("x one two three four five six seven eight y", source, 8,
                         lambda run: False) == ["one two three four five six seven eight"]
    assert verbatim_runs("x one two three four five six seven eight y", source, 8,
                         lambda run: True) == []
    assert verbatim_runs("one two three four five six seven", source, 8,
                         lambda run: False) == []


SOURCE_TEXT = ("the error budget is the amount of unreliability a service may spend "
               "before the release process has to slow down for everybody")
PASSAGE = "the error budget is the amount of unreliability a service may spend"


@pytest.mark.parametrize("card, flagged", [
    # quoted and followed by a chapter of the work: allowed
    (f'- **Budgets** — "{PASSAGE}" (3. Embracing Risk)', False),
    (f'- **Budgets** — “{PASSAGE}”, (3. Embracing Risk)', False),
    # the same words outside quotation marks: still a copy
    (f"- **Budgets** — {PASSAGE} (3. Embracing Risk)", True),
    # quoted, but no chapter after it
    (f'- **Budgets** — "{PASSAGE}" says the book', True),
    # quoted, but the parenthesis names no chapter of the work
    (f'- **Budgets** — "{PASSAGE}" (page 12)', True),
    # a quotation that is attributed does not excuse a run outside it
    (f'"{PASSAGE}" (3. Embracing Risk) and then {PASSAGE}', True),
])
def test_a_verbatim_run_is_allowed_only_quoted_and_followed_by_its_chapter(card, flagged):
    source = grams_of(word_list(SOURCE_TEXT), SHARED_RUN_WORDS)
    body, problems = outside_attributed_quotes(card, CHAPTERS)
    runs = verbatim_runs(body, source, SHARED_RUN_WORDS, lambda run: False)
    assert bool(runs) == flagged, runs
    assert not problems


CHAPTERS = ["1. Introduction", "3. Embracing Risk"]
LONG_SOURCE = " ".join(f"word{i}" for i in range(60))


def test_a_quotation_longer_than_the_cap_is_not_exempt():
    """The prompt promises under 25 words; a 40-word, many-sentence passage in
    quotation marks with a chapter after it is still a copied passage."""
    source = grams_of(word_list(LONG_SOURCE), SHARED_RUN_WORDS)
    long_quote = ". ".join(" ".join(f"word{i}" for i in range(k, k + 10)) for k in (0, 10, 20, 30))
    body, _ = outside_attributed_quotes(f'- **X** — "{long_quote}" (3. Embracing Risk)', CHAPTERS)
    assert verbatim_runs(body, source, SHARED_RUN_WORDS, lambda run: False)
    at_cap = " ".join(f"word{i}" for i in range(QUOTE_MAX_WORDS))
    body, _ = outside_attributed_quotes(f'"{at_cap}" (3. Embracing Risk)', CHAPTERS)
    assert not verbatim_runs(body, source, SHARED_RUN_WORDS, lambda run: False)


def test_more_quotations_than_the_cap_per_card_are_reported():
    quote = '"a short line" (3. Embracing Risk)'
    _, problems = outside_attributed_quotes("\n".join([quote] * QUOTES_PER_CARD), CHAPTERS)
    assert not problems
    _, problems = outside_attributed_quotes("\n".join([quote] * (QUOTES_PER_CARD + 1)), CHAPTERS)
    assert problems == [f"{QUOTES_PER_CARD + 1} attributed quotations, more than {QUOTES_PER_CARD}"]


def test_a_stray_closing_quotation_mark_does_not_exempt_a_copied_run():
    """`the "SLO" term; <copied run>" (Ch)`: the marks are paired left to right,
    so the run is outside any quotation, and the odd mark is reported."""
    source = grams_of(word_list(SOURCE_TEXT), SHARED_RUN_WORDS)
    card = f'- the "SLO" term; {PASSAGE}" (3. Embracing Risk)'
    body, problems = outside_attributed_quotes(card, CHAPTERS)
    assert verbatim_runs(body, source, SHARED_RUN_WORDS, lambda run: False)
    assert problems == ["an odd number of straight quotation marks (3)"]
    _, problems = outside_attributed_quotes(f"“{PASSAGE} (3. Embracing Risk)", CHAPTERS)
    assert problems == ["1 opening and 0 closing curly quotation marks"]


def test_the_nd_check_exempts_no_quotation():
    """The NoDerivatives test is not relaxed: it reads every tracked file as it
    stands, with no quotation cut out, so an attributed quote of an ND work in
    a tracked file still fails it."""
    source = inspect.getsource(test_no_tracked_file_holds_a_passage_of_a_no_derivatives_work)
    assert "outside_attributed_quotes" not in source
    assert "ND_RUN_WORDS = 8" in inspect.getsource(sys.modules[__name__])
