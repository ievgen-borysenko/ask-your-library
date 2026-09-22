"""The documentation is checked by code, not by memory (#72).

Every release re-reads all documentation against the release commit. The part
of that pass a machine can do belongs in the test suite, so a stale page fails
before a reader finds it: a link that no longer resolves, a file path a doc
still names, a version that drifted from the changelog, an index that counts
its own entries wrong, a setting documented but no longer read (or read but
never documented), a flag the parser stopped accepting.

Five checks, one test each, and each failure is written as a to-do list: every
offending `file:line` is named, so a green-to-red diff says exactly what to fix
rather than that something somewhere is wrong.

What is deliberately NOT here. External links are never fetched: this suite is
offline (tests/egress_guard.py blocks the socket) and a network check would
make the docs job depend on somebody else's uptime. Prose is not checked — that
a sentence is still TRUE is a reader's judgment and stays a human step of every
release PR. Numbers in the README are not pinned to the reports they cite; that
needs a convention first (#72 leaves it out of scope).

The markdown reader here is deliberately small — fences, links, code spans,
headings — rather than a dependency: the suite installs from a lockfile and a
docs check is not worth a new one. Small is not the same as naive, though, and
the cases where a naive reader silently reads the wrong thing (a destination
carrying balanced parentheses, an angle-bracketed reference definition, an
indented definition, a long fence that a shorter one must not close) are pinned
by fixtures below, on strings rather than on the tree — a check that quietly
stops matching would otherwise report nothing and pass.

The settings check reads the source with `ast` rather than by grepping it: a
variable named in a comment or a docstring is prose about the code, not a read,
and the parse is what tells the two apart.
"""
import ast
import re
import subprocess
import tomllib
from fnmatch import fnmatch
from pathlib import Path

import pytest

from conftest import REPO

# Every path is compared against the real location of the tree, so that a link
# climbing out of it with `../..` is caught whatever symlink the checkout sits
# behind (data/lancedb is one in this project's own dev checkout).
TREE = REPO.resolve()

# --- a very small markdown reader -------------------------------------------

# A fence opens with three or more backticks or tildes, indented at most three
# spaces; what follows on the line is the info string.
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# A link destination: either <angle-bracketed>, or a run of non-space characters
# in which parentheses must balance, which is what lets `path_(1).md` through
# without swallowing the closing bracket of the link itself.
DESTINATION = r"(?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))+"
# [text](target) and ![alt](target), with an optional "title" after the target.
INLINE_LINK = re.compile(r"!?\[[^\]\[]*\]\(\s*(?:<([^<>]*)>|(" + DESTINATION + r"))"
                         r"(?:\s+(?:\"[^\"]*\"|'[^']*'|\([^()]*\)))?\s*\)")
# A reference definition: [label]: target, indented up to three spaces, the
# target optionally in angle brackets (which are not part of the path).
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(?:<([^<>]*)>|(\S+))")
CODE_SPAN = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
# Schemes a relative-path check must not touch.
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "ftp://")


def tracked_files() -> list[str]:
    """Every path git knows about. A file that is not tracked is not published,
    so it is not part of what a release promises."""
    listed = subprocess.run(["git", "ls-files"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout
    return [name for name in listed.splitlines() if name]


def tracked_markdown() -> list[Path]:
    """README.md, docs/**, .github/**, the corpus cards."""
    return [REPO / name for name in tracked_files() if name.endswith(".md")]


def markdown_lines(text: str) -> list[tuple[int, str, bool]]:
    """(line number, text, inside a fenced block) for a markdown document.

    One pass answers both halves of this module: the link checks read the prose
    lines, the path check reads the fenced ones, and neither has to re-learn
    where a fence opened. The fence rules are CommonMark's, because the two that
    a naive reader gets wrong both appear in this tree's docs: a closing fence
    must use the SAME character and be at least as long as the opening one (so
    ``` inside a ```` block is content, not the end of it), and a backtick fence
    cannot carry a backtick in its info string (which is what keeps an inline
    code span out of the fence machinery)."""
    rows: list[tuple[int, str, bool]] = []
    marker: str | None = None       # the character the open fence is made of
    length = 0                      # and how many of them it took
    for number, line in enumerate(text.splitlines(), start=1):
        fence = FENCE.match(line)
        run = fence.group(1) if fence else ""
        if marker is None:
            if fence and not (run[0] == "`" and "`" in fence.group(2)):
                marker, length = run[0], len(run)
                rows.append((number, line, True))
            else:
                rows.append((number, line, False))
            continue
        rows.append((number, line, True))
        if fence and run[0] == marker and len(run) >= length and not fence.group(2).strip():
            marker, length = None, 0
    return rows


_LINES: dict[Path, list[tuple[int, str, bool]]] = {}


def prose_and_code(path: Path) -> list[tuple[int, str, bool]]:
    """markdown_lines over a file, read once per test session."""
    if path not in _LINES:
        _LINES[path] = markdown_lines(path.read_text(encoding="utf-8"))
    return _LINES[path]


def slug(title: str) -> str:
    """GitHub's heading anchor: the text lowercased, punctuation dropped
    (hyphens and underscores survive), spaces turned into hyphens. Backticks in
    a heading are punctuation, so `observe` in a title contributes `observe`."""
    text = title.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text.strip())


def anchors_in(text: str) -> set[str]:
    """Every fragment a link may point at in this document: one slug per
    heading, with GitHub's -1 / -2 suffixes for repeated titles."""
    found: set[str] = set()
    for _, line, in_fence in markdown_lines(text):
        if in_fence:
            continue                # `# comment` in a shell block is not a heading
        heading = HEADING.match(line)
        if not heading:
            continue
        base = slug(heading.group(2))
        if not base:
            continue
        candidate, repeat = base, 0
        while candidate in found:
            repeat += 1
            candidate = f"{base}-{repeat}"
        found.add(candidate)
    return found


_ANCHORS: dict[Path, set[str]] = {}


def anchors_of(path: Path) -> set[str]:
    if path not in _ANCHORS:
        _ANCHORS[path] = anchors_in(path.read_text(encoding="utf-8"))
    return _ANCHORS[path]


def targets_in(text: str) -> list[tuple[int, str]]:
    """(line number, target) for every inline link, image and reference
    definition outside a fenced block. Links inside a fence are samples of
    markdown, not links this tree makes."""
    found: list[tuple[int, str]] = []
    for number, line, in_fence in markdown_lines(text):
        if in_fence:
            continue
        for angled, bare in INLINE_LINK.findall(line):
            found.append((number, angled or bare))
        reference = REFERENCE_LINK.match(line)
        if reference:
            found.append((number, reference.group(1) or reference.group(2)))
    return found


def targets_of(path: Path) -> list[tuple[int, str]]:
    return targets_in(path.read_text(encoding="utf-8"))


def report(problems: list[str], headline: str) -> None:
    """A failure reads as a to-do list: one line per offence, in file order."""
    if problems:
        pytest.fail(f"{headline} ({len(problems)}):\n" + "\n".join(problems), pytrace=False)


# --- 0. the reader itself ----------------------------------------------------

def test_the_markdown_reader_reads_the_shapes_that_break_a_naive_one():
    """Four CommonMark shapes, each of which a simpler reader gets wrong
    silently — it reports nothing and the test above it passes. Pinned on
    strings so they hold whether or not this tree currently writes them."""
    # A destination may carry balanced parentheses; the link's own closing
    # bracket is not one of them.
    assert targets_in("see [x](path_(1).md) now") == [(1, "path_(1).md")]
    # An angle-bracketed reference definition: the brackets delimit the target
    # and are not part of it.
    assert targets_in("[l]: <path.md>") == [(1, "path.md")]
    # A definition may be indented up to three spaces and is still a definition.
    assert targets_in("   [l]: indented.md") == [(1, "indented.md")]
    assert targets_in("    [l]: four-spaces.md") == []      # four is an indented code block
    # A fence is closed only by at least as many of the SAME character, with
    # nothing after it: a shorter run inside a longer fence is content.
    inside = markdown_lines("````\n```\n[x](inside.md)\n````\nafter [y](after.md)")
    assert [in_fence for _, _, in_fence in inside] == [True, True, True, True, False]
    assert targets_in("````\n```\n[x](inside.md)\n````\nafter [y](after.md)") == [(5, "after.md")]
    # A tilde fence is not closed by backticks, and vice versa.
    assert [in_fence for _, _, in_fence in markdown_lines("~~~\n```\n~~~\nout")] == \
        [True, True, True, False]
    # A backtick fence carries no backtick in its info string, so an inline code
    # span on a line of its own never opens a block.
    assert [in_fence for _, _, in_fence in markdown_lines("``` `a` ```\nplain")] == [False, False]


# --- 1. links ----------------------------------------------------------------

def test_every_internal_link_resolves_and_every_fragment_names_a_heading():
    """A relative link or image points at a file this tree holds, and a
    `#fragment` names a heading of the file it points at (or of this file, when
    the link is a bare anchor). "Inside the tree" is part of the claim: an
    absolute path is a path on the author's machine, and a relative one that
    climbs out with `../..` resolves to whatever happens to sit beside the
    checkout — both read as working links on the machine that wrote them and
    reach nothing for anyone else. External links are not fetched — see the
    module docstring."""
    problems: list[str] = []
    checked = 0
    for path in tracked_markdown():
        where = path.relative_to(REPO)
        for number, target in targets_of(path):
            if target.startswith(EXTERNAL):
                continue
            checked += 1
            if target.startswith("#"):
                fragment = target[1:].lower()
                if fragment not in anchors_of(path):
                    problems.append(f"{where}:{number}: #{fragment} is not a heading of this file")
                continue
            file_part, _, fragment = target.partition("#")
            if not file_part:
                continue
            if file_part.startswith("/") or Path(file_part).is_absolute():
                problems.append(f"{where}:{number}: {target} is an absolute path, "
                                f"not a link inside the tree")
                continue
            resolved = (path.parent / file_part).resolve()
            if not resolved.is_relative_to(TREE):
                problems.append(f"{where}:{number}: {target} resolves outside the repository "
                                f"({resolved})")
                continue
            if not resolved.exists():
                problems.append(f"{where}:{number}: {target} -> {file_part} does not exist")
                continue
            if fragment and resolved.suffix == ".md":
                if fragment.lower() not in anchors_of(resolved):
                    problems.append(f"{where}:{number}: {target} -> "
                                    f"#{fragment} is not a heading of {file_part}")
    report(problems, "links that do not resolve")
    # A link pattern that stopped matching would report nothing and pass. The
    # tree holds well over a hundred internal links; this is a floor.
    assert checked > 100, f"only {checked} links were checked: the link pattern stopped matching"


# --- 2. paths named in docs --------------------------------------------------

# A path shaped like a file of this tree: one of the directories this repository
# actually has, and an extension it actually uses.
DOC_PATH = re.compile(r"\b(?:src|tests|eval|scripts|docs|ingest|\.github)"
                      r"/[A-Za-z0-9_./-]+\.(?:py|md|yaml|yml|sh|toml|txt|json)\b")
# A file named without any directory in front of it. Most of what a reader is
# told to open lives at the root — `ui.py`, `pyproject.toml`, `SECURITY.md`,
# `.env.example`, `LICENSE`, `NOTICE` — and the pattern above cannot see any of
# them. The lookarounds keep this from firing on the tail of a longer path
# (`eval/golden/en-demo.yaml` names no root file).
# The trailing `(?!\.\w)` is what keeps a host name out: `ollama.example.com`
# ends in a segment no file extension list has, and without the guard its
# `ollama.example` prefix would read as a file this tree is missing.
ROOT_FILE = re.compile(
    r"(?<![\w./-])(LICENSE|NOTICE|"
    r"\.?[A-Za-z0-9_][A-Za-z0-9_.-]*\.(?:py|md|yaml|yml|sh|toml|txt|json|lock|example)|"
    r"\.env)(?![\w/-])(?!\.\w)")

# Prefixes a doc may name although this tree does not hold them. Each entry says
# why, because an unexplained allowlist is how a broken path survives. It is
# deliberately short: everything else on these pages is a file a reader opens.
PATHS_DOCS_MAY_NAME_WITHOUT_HOLDING = {
    # EVAL_RESULTS_DIR, gitignored: an eval report records the scratch file the
    # run itself wrote ("not committed" is written beside it in the reports),
    # which is a fact about that run and not a file a reader can open. This is
    # also what covers the `answers-<timestamp>.md` names those reports cite.
    "eval/results/": "written by a run, never committed (EVAL_RESULTS_DIR)",
}
# Names (fnmatch patterns) a doc gives as an example of a file that is NOT in
# this tree: one the reader makes, one a run writes, or one that stayed in the
# development repository. Naming such a file is the instruction or the record,
# so a check demanding that it exist would demand the opposite of what the page
# says. Every entry carries the reason it is here.
FILES_THIS_TREE_IS_RIGHT_NOT_TO_HOLD = {
    ".env": "`cp .env.example .env` is the instruction; a committed .env would be a leaked key",
    "MANIFEST.json": "written into each backup directory by `ayl-add --backup`",
    "Title.txt": "a placeholder in the file-naming rules, standing for the reader's own book",
    "Author.txt": "the tail of the `Title - Author.txt` placeholder in the same rules",
    "notes.md": "a hypothetical book in a second library, in ADR-024's source-reference argument",
    "answers-*.md": "the harness's own run report under EVAL_RESULTS_DIR, cited by name and "
                    "never committed",
    "*-pick-second.md": "targeted second-candidate runs made in the development repository; the "
                        "reports that cite them say so where they do it",
}
# The ingest package lives at src/ask_your_library/ingest/, and the docs name its
# modules by the shorthand a developer uses in conversation — `ingest/chapters.py`
# for the chapter splitter. The file is real, so the shorthand is resolved rather
# than reported: what this check is for is a path that points at nothing.
PACKAGE_SHORTHAND = ("ingest/", "src/ask_your_library/")


def _tracked_basenames() -> set[str]:
    """The file names this tree holds, wherever they sit. A bare `config.py` in
    a doc is `src/ask_your_library/config.py` written the way a developer says
    it out loud; what this check is for is a name that matches no file at all."""
    return {name.rsplit("/", 1)[-1] for name in tracked_files()}


_BASENAMES: set[str] = set()


def path_exists(token: str) -> bool:
    """Whether the path a doc wrote names a file this tree holds: at the given
    location, under the package shorthand above, or — for a bare file name —
    anywhere in the tree under that name."""
    global _BASENAMES
    if (REPO / token).exists():
        return True
    prefix, package = PACKAGE_SHORTHAND
    if token.startswith(prefix) and (REPO / package / token).exists():
        return True
    if "/" not in token:
        if not _BASENAMES:
            _BASENAMES = _tracked_basenames()
        return token in _BASENAMES
    return False


def path_tokens(piece: str) -> list[str]:
    """Every file path a fragment of documentation names: paths with a directory
    in front, and bare names of files that would sit at the root."""
    return DOC_PATH.findall(piece) + ROOT_FILE.findall(piece)


def missing_paths(text: str) -> list[tuple[int, str]]:
    """(line number, path) for every file path this document names in a code
    span or a fenced block that the tree does not hold. Prose is left alone on
    purpose: a path in running text is often a shape ("a file under docs/…"),
    while one in code is something to type."""
    missing: list[tuple[int, str]] = []
    for number, line, in_fence in markdown_lines(text):
        haystack = [line] if in_fence else CODE_SPAN.findall(line)
        for piece in haystack:
            for token in path_tokens(piece):
                if any(token.startswith(prefix)
                       for prefix in PATHS_DOCS_MAY_NAME_WITHOUT_HOLDING):
                    continue
                if any(fnmatch(token, pattern)
                       for pattern in FILES_THIS_TREE_IS_RIGHT_NOT_TO_HOLD):
                    continue
                if not path_exists(token):
                    missing.append((number, token))
    return missing


def documented_paths(text: str) -> list[tuple[int, str]]:
    """Every path named in code, missing or not — the denominator of the check
    below, so that a pattern which stopped matching cannot pass as clean."""
    found: list[tuple[int, str]] = []
    for number, line, in_fence in markdown_lines(text):
        haystack = [line] if in_fence else CODE_SPAN.findall(line)
        for piece in haystack:
            found.extend((number, token) for token in path_tokens(piece))
    return found


def test_every_file_path_named_in_the_docs_exists():
    """`eval/run_agent_eval.py`, `docs/eval-results/...`, `scripts/...`, `ui.py`:
    a path written as something to type is a file this tree holds."""
    problems: list[str] = []
    checked = 0
    for path in tracked_markdown():
        where = path.relative_to(REPO)
        text = path.read_text(encoding="utf-8")
        checked += len(documented_paths(text))
        problems.extend(f"{where}:{number}: {token}" for number, token in missing_paths(text))
    report(problems, "file paths named in the docs that do not exist")
    # A pattern that stopped matching would report nothing and pass. The docs
    # name hundreds of paths; this is a floor, not a count to keep up to date.
    assert checked > 100, f"only {checked} paths were checked: the path pattern stopped matching"


def test_a_path_the_tree_does_not_hold_is_reported():
    """The check above is only worth its runtime if it can fail. Both shapes are
    pinned here on a string: a path with a directory in front of it, and a bare
    root file name, which the directory pattern cannot see at all."""
    document = ("Run `scripts/no-such-script.sh` first.\n"
                "\n"
                "Then open `not-a-real-module.py` and read `ui.py`.\n")
    assert missing_paths(document) == [(1, "scripts/no-such-script.sh"),
                                       (3, "not-a-real-module.py")]
    # And the real files beside them are not reported.
    assert ("ui.py" in [token for _, token in documented_paths(document)]
            and path_exists("ui.py") and path_exists("src/ask_your_library/config.py"))


GOLDEN_SET = re.compile(r"\beval/golden/[A-Za-z0-9_.-]+\.yaml\b")


def test_every_golden_set_named_anywhere_in_the_docs_exists():
    """A golden set is named in running prose as often as in a command (the
    eval pages discuss `eval/golden/en-demo.yaml` by name), so this one is not
    limited to code spans — and a renamed set must not leave the pages that
    tell a reader to run it pointing at nothing."""
    problems: list[str] = []
    for path in tracked_markdown():
        where = path.relative_to(REPO)
        for number, text, _ in prose_and_code(path):
            for token in GOLDEN_SET.findall(text):
                if not (REPO / token).exists():
                    problems.append(f"{where}:{number}: {token}")
    report(problems, "golden sets named in the docs that do not exist")


# --- 3. version and changelog ------------------------------------------------

CHANGELOG = REPO / "docs" / "CHANGELOG.md"
# The convention in that file, and the only one supported here: `## 0.3.1
# (2026-09-15)`, plus the `## Unreleased` section on top and the two `## Phase
# N` headings of the pre-release history at the bottom.
RELEASED_HEADING = re.compile(r"^##\s+(\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)\b")


def project_version() -> str:
    return tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def changelog_sections() -> list[tuple[int, str, list[str]]]:
    """(line number, heading text, body lines) for every `## ` section."""
    sections: list[tuple[int, str, list[str]]] = []
    for number, text, in_fence in prose_and_code(CHANGELOG):
        if in_fence:
            if sections:
                sections[-1][2].append(text)
            continue
        if text.startswith("## "):
            sections.append((number, text[3:].strip(), []))
        elif sections:
            sections[-1][2].append(text)
    return sections


def unreleased_sections() -> list[tuple[int, str, list[str]]]:
    return [section for section in changelog_sections() if section[1].lower() == "unreleased"]


def test_the_newest_released_changelog_heading_is_the_version_in_pyproject():
    """The version a wheel carries and the newest version the changelog
    describes are the same number, or one of the two was forgotten."""
    version = project_version()
    released = [(number, heading) for number, heading, _ in changelog_sections()
                if RELEASED_HEADING.match(f"## {heading}")]
    assert released, f"{CHANGELOG.relative_to(REPO)}: no released `## <version>` heading found"
    number, newest = released[0]
    found = RELEASED_HEADING.match(f"## {newest}").group(1)
    assert found == version, (
        f"pyproject.toml says version = \"{version}\", but the newest released heading is "
        f"{CHANGELOG.relative_to(REPO)}:{number} `## {newest}`")


def test_the_changelog_has_exactly_one_unreleased_section():
    """Checked on every commit, not only at a tag. None means the next entry has
    nowhere to go and the release check below has nothing to read; two means
    half the unreleased work is in a section the release pass will not see."""
    sections = unreleased_sections()
    assert len(sections) == 1, (
        f"{CHANGELOG.relative_to(REPO)}: expected exactly one `## Unreleased` section, found "
        f"{len(sections)}" + "".join(f"\n  line {number}: `## {heading}`"
                                     for number, heading, _ in sections))


def test_a_tagged_commit_carries_an_empty_unreleased_section_and_a_matching_tag():
    """At a tag, everything the changelog holds has been released: an
    `## Unreleased` section with anything in it means the tag describes work it
    does not name. Off a tag there is nothing to check — that is the ordinary
    state of a branch, so this skips rather than passes silently, and the
    section's existence is pinned by the test above either way."""
    sections = unreleased_sections()
    assert len(sections) == 1, f"{CHANGELOG.relative_to(REPO)}: {len(sections)} Unreleased sections"
    described = subprocess.run(["git", "describe", "--tags", "--exact-match", "HEAD"],
                               cwd=REPO, capture_output=True, text=True)
    if described.returncode != 0:
        pytest.skip("HEAD is not tagged: an Unreleased section is expected to have content here")
    tag = described.stdout.strip()
    version = project_version()
    assert tag == f"v{version}", (
        f"HEAD is tagged {tag} but pyproject.toml says version = \"{version}\"")
    number, _, body = sections[0]
    assert not "".join(body).strip(), (
        f"{CHANGELOG.relative_to(REPO)}:{number}: the Unreleased section still has content at "
        f"tag {tag} — it belongs under `## {version}`")


# --- 4. the ADR index --------------------------------------------------------

ADR_DIR = REPO / "docs" / "adr"
ADR_INDEX = ADR_DIR / "README.md"
ADR_HEADING = re.compile(r"^##\s+ADR-(\d+)\b")
# "Twenty-five decisions, in the order they were taken." The sentence is prose a
# reader trusts, so the number in it is checked like any other fact here. Not
# anchored to the start of a line: the paragraph is reflowed whenever it is
# edited, and the sentence must stay findable wherever the wrapping puts it.
ADR_COUNT_SENTENCE = re.compile(r"(\S+) decisions, in the order they were taken")
NUMBER_WORDS = {word: value for value, word in enumerate(
    ("one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
     "sixteen seventeen eighteen nineteen twenty twenty-one twenty-two twenty-three twenty-four "
     "twenty-five twenty-six twenty-seven twenty-eight twenty-nine thirty").split(), start=1)}


def adr_entries() -> list[tuple[int, int, list[str]]]:
    """(line number, ADR number, body lines) for every `## ADR-NNN` entry of the
    index, in the order the file holds them."""
    entries: list[tuple[int, int, list[str]]] = []
    for number, text, in_fence in prose_and_code(ADR_INDEX):
        if in_fence:
            if entries:
                entries[-1][2].append(text)
            continue
        heading = ADR_HEADING.match(text)
        if heading:
            entries.append((number, int(heading.group(1)), []))
        elif entries:
            entries[-1][2].append(text)
    return entries


def test_the_adr_index_counts_its_own_entries_correctly():
    """The opening sentence names how many decisions are recorded. It was wrong
    once (twenty-four written, twenty-five held) because two ADRs were appended
    and the paragraph above them was not re-read — which is exactly what this
    file exists to catch."""
    text = ADR_INDEX.read_text(encoding="utf-8")
    sentence = ADR_COUNT_SENTENCE.search(text)
    assert sentence, (f"{ADR_INDEX.relative_to(REPO)}: the sentence "
                      f"\"<N> decisions, in the order they were taken\" is gone")
    written = sentence.group(1).lower().rstrip(",")
    claimed = int(written) if written.isdigit() else NUMBER_WORDS.get(written)
    assert claimed is not None, (
        f"{ADR_INDEX.relative_to(REPO)}: \"{sentence.group(1)}\" is not a number this test "
        f"knows (digits, or one..thirty in words)")
    held = len(adr_entries())
    assert claimed == held, (
        f"{ADR_INDEX.relative_to(REPO)}: the index says {claimed} decisions and holds {held} "
        f"`## ADR-` headings")


def test_the_adr_numbers_are_contiguous_from_one():
    """A gap means a decision was recorded and lost; a repeat means two
    decisions share a number and every reference to it is now ambiguous."""
    entries = adr_entries()
    expected = list(range(1, len(entries) + 1))
    found = [adr for _, adr, _ in entries]
    assert found == expected, (
        f"{ADR_INDEX.relative_to(REPO)}: ADR numbers are "
        f"{found}, expected {expected} (contiguous from 001, in order)")


def test_every_adr_entry_states_its_status():
    """Status is what makes an entry a decision record rather than a note: an
    entry with none does not say whether it still holds."""
    problems = [f"docs/adr/README.md:{number}: ADR-{adr:03d} has no `Status:` line"
                for number, adr, body in adr_entries()
                if not any(line.startswith("Status:") for line in body)]
    report(problems, "ADR entries with no status")


def test_every_adr_written_out_as_its_own_file_is_linked_from_the_index():
    """An ADR too long for the index gets a file of its own; unlinked, it is a
    decision record nobody reading the index can find. "Linked" means a link
    that resolves to the file, not the file name appearing somewhere in the
    text: a name mentioned in a sentence is still a record a reader cannot
    click through to, which is the whole complaint."""
    linked = set()
    for _, target in targets_of(ADR_INDEX):
        if target.startswith(EXTERNAL) or target.startswith("#"):
            continue
        resolved = (ADR_INDEX.parent / target.partition("#")[0]).resolve()
        if resolved.is_relative_to(TREE):
            linked.add(resolved)
    problems = [f"docs/adr/{path.name}: not linked from docs/adr/README.md"
                for path in sorted(ADR_DIR.glob("*.md"))
                if path.name != "README.md" and path.resolve() not in linked]
    report(problems, "ADR files the index does not link")


# --- 5. settings and commands ------------------------------------------------

CONFIGURATION = REPO / "docs" / "configuration.md"
CONFIG_PY = REPO / "src" / "ask_your_library" / "config.py"
# Where a setting may be read from. config.py is the main one, but the UI, the
# ingest package and the eval harness read their own, and a reader does not care
# which file it is in — only that something in this tree acts on the name.
SOURCE_ROOTS = ("src", "eval", "scripts", "ui.py")
# config.py wraps os.environ in three helpers that all take the variable name
# first, so a read through one of them is a read. The list is pinned rather than
# guessed, and the test below fails if config.py grows a fourth.
CONFIG_HELPERS = ("_env", "_positive_int", "_non_negative_int")
# The attributes of os.environ that read (or seed) a name.
ENVIRON_METHODS = ("get", "setdefault", "pop")

# A name in a code span that looks like a setting: SHOUTING_SNAKE_CASE, at least
# four characters, and not a fragment of a longer name or a `NAME_*` wildcard —
# the docs write `OLLAMA_PRICE_*` and `*_TRACING_V2` when they mean a family.
SETTING_NAME = re.compile(r"(?<![A-Z0-9_*])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Z0-9_*])")

# Names configuration.md documents that nothing in this tree reads, with the
# reason each is there. A reader still has to set them, so the page is right to
# carry them; they are simply not ours to read.
SETTINGS_READ_OUTSIDE_THIS_TREE = {
    "LANGSMITH_API_KEY": "read by the LangSmith SDK, not by this package",
    "LANGSMITH_TRACING": "read by the LangSmith SDK (the legacy flag)",
    "LANGSMITH_TRACING_V2": "read by the LangSmith SDK, which takes precedence over LANGCHAIN_*",
    "OLLAMA_CONTEXT_LENGTH": "read by the Ollama server, which decides the context window",
}


def source_files() -> list[Path]:
    files: list[Path] = []
    for root in SOURCE_ROOTS:
        target = REPO / root
        files.extend([target] if target.is_file() else sorted(target.rglob("*.py")))
    return files


def _is_environ(node: ast.AST) -> bool:
    """`os.environ`, however the module was imported."""
    return isinstance(node, ast.Attribute) and node.attr == "environ"


def _name_of(node: ast.AST, constants: dict[str, str]) -> str | None:
    """The variable name an argument stands for: a literal, or a module-level
    constant holding one. fake_backend.py keeps its two names in ENABLE_VAR and
    CONFIRM_VAR rather than spelling them at the call, and a check that only
    read literals would call those two undocumented."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


def environment_reads(source: str) -> set[str]:
    """Every environment variable this module actually reads.

    Parsed, not grepped: `os.environ.get("X")` written inside a comment or a
    docstring is prose about the code — graph.py's docstring names
    LANGCHAIN_ENDPOINT that way — and only the parse tells that apart from a
    read. Three shapes count, because all three appear in this tree: a call
    (`os.environ.get`, `os.getenv`, or one of config.py's helpers), a
    subscript (`os.environ["X"]`), and a membership test (`"X" in os.environ`,
    which is how the fake-backend seam decides it was armed)."""
    tree = ast.parse(source)
    constants = {target.id: node.value.value
                 for node in tree.body if isinstance(node, ast.Assign)
                 for target in node.targets
                 if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant)
                 and isinstance(node.value.value, str)}
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            reads = ((isinstance(func, ast.Attribute) and func.attr in ENVIRON_METHODS
                      and _is_environ(func.value))
                     or (isinstance(func, ast.Attribute) and func.attr == "getenv")
                     or (isinstance(func, ast.Name) and func.id in CONFIG_HELPERS))
            if reads:
                name = _name_of(node.args[0], constants)
                if name:
                    found.add(name)
        elif isinstance(node, ast.Subscript) and _is_environ(node.value):
            name = _name_of(node.slice, constants)
            if name:
                found.add(name)
        elif isinstance(node, ast.Compare):
            for operator, comparator in zip(node.ops, node.comparators):
                if isinstance(operator, (ast.In, ast.NotIn)) and _is_environ(comparator):
                    name = _name_of(node.left, constants)
                    if name:
                        found.add(name)
    return found


def config_variables() -> set[str]:
    """Every environment variable config.py resolves at import time — the file
    that decides what the shipped default is, and therefore the one whose
    settings a reader has the strongest claim to find documented."""
    return environment_reads(CONFIG_PY.read_text(encoding="utf-8"))


def settings_the_tree_reads() -> set[str]:
    """The union over every source root: one set, used in both directions, so
    the two halves of this check can never disagree about what a read is."""
    found: set[str] = set()
    for path in source_files():
        found |= environment_reads(path.read_text(encoding="utf-8"))
    return found


def documented_settings() -> list[tuple[int, str]]:
    """(line number, name) for every setting-shaped name in a code span of
    configuration.md. The table is written with each name in a span, so this is
    the page's own list of what it documents."""
    found: list[tuple[int, str]] = []
    for number, text, in_fence in prose_and_code(CONFIGURATION):
        if in_fence:
            continue                # a Modelfile or a shell sample, not the table
        for span in CODE_SPAN.findall(text):
            for name in SETTING_NAME.findall(span):
                found.append((number, name))
    return found


def test_config_py_has_no_environment_helper_this_check_does_not_know():
    """CONFIG_HELPERS is a list, and a list goes stale. Every module-level
    function in config.py that takes a variable name first is one of these
    wrappers, so a new `_seconds(name, ...)` has to be added here rather than
    silently making its settings invisible to both directions of the check."""
    tree = ast.parse(CONFIG_PY.read_text(encoding="utf-8"))
    wrappers = [node.name for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.args.args and node.args.args[0].arg == "name"]
    assert sorted(wrappers) == sorted(CONFIG_HELPERS), (
        f"config.py's name-first helpers are {sorted(wrappers)}, this check knows "
        f"{sorted(CONFIG_HELPERS)}: add the new one so the settings it reads stay checked")


def test_every_variable_config_reads_is_documented():
    """A setting that exists and is not on the page is a setting nobody can
    find; config.py is the list, docs/configuration.md is the promise."""
    page = CONFIGURATION.read_text(encoding="utf-8")
    variables = config_variables()
    problems = [f"docs/configuration.md: {name} is read by src/ask_your_library/config.py "
                f"and documented nowhere on this page"
                for name in sorted(variables) if f"`{name}`" not in page]
    report(problems, "settings the code reads and the docs do not describe")
    assert len(variables) > 20, (
        f"only {len(variables)} settings were found in config.py: the source parse stopped "
        f"recognising its environment reads")


def test_every_setting_the_docs_describe_is_read_somewhere():
    """The other direction, and the one a rename breaks: a name on the page that
    the code no longer reads is an instruction to set something that does
    nothing. Compared against the parsed reads, not against the text of the
    source: a name that survives only in a comment is exactly the case this is
    looking for."""
    read = settings_the_tree_reads()
    documented = documented_settings()
    problems = [f"docs/configuration.md:{number}: {name} is documented but read nowhere under "
                f"{', '.join(SOURCE_ROOTS)}"
                for number, name in documented
                if name not in read and name not in SETTINGS_READ_OUTSIDE_THIS_TREE]
    report(problems, "settings the docs describe and nothing reads")
    # The page's table is the list; a span pattern that stopped matching would
    # leave this test with nothing to check and still pass.
    assert len({name for _, name in documented}) > 30, (
        "the configuration table yielded almost no names: the code-span pattern stopped matching")


def test_a_setting_read_only_in_a_comment_does_not_count_as_read():
    """What the parse buys over a grep, pinned: the same name in a docstring, a
    comment and a string is prose about the code; only the call is a read."""
    prose = ('"""A docstring naming os.environ.get("ONLY_IN_A_DOCSTRING").\n'
             '"""\n'
             'import os\n'
             '# os.environ.get("ONLY_IN_A_COMMENT")\n'
             'MESSAGE = "set ONLY_IN_A_MESSAGE to change this"\n'
             'REAL = os.environ.get("REALLY_READ", "")\n')
    assert environment_reads(prose) == {"REALLY_READ"}
    # And the three shapes this tree actually uses, including a name held in a
    # module-level constant rather than spelled at the call.
    shapes = ('import os\n'
              'HELD = "IN_A_CONSTANT"\n'
              'a = os.environ["BY_SUBSCRIPT"]\n'
              'b = "BY_MEMBERSHIP" in os.environ\n'
              'c = os.getenv("BY_GETENV")\n'
              'd = os.environ.get(HELD, "")\n'
              'os.environ.setdefault("BY_SETDEFAULT", "x")\n')
    assert environment_reads(shapes) == {"BY_SUBSCRIPT", "BY_MEMBERSHIP", "BY_GETENV",
                                         "IN_A_CONSTANT", "BY_SETDEFAULT"}


# `ayl-add` is the console script pyproject declares; its options are the
# parser's, so the docs are compared against the parser itself rather than
# against a list kept beside it.
AYL_ADD = "ayl-add"
# The `ayl` subcommands that are that same parser under a verb (#30): `ayl add`
# reaches it directly, and `doctor` / `backup` / `restore` reach it with one
# flag prefixed, so a `--db` or a `--force` written after any of them is one of
# its options and this check still covers it. The other subcommands (`ayl ask`,
# `ayl books`, `ayl ui`) have parsers of their own and are named below only so
# that a flag of theirs is not attributed to this one.
AYL_ADD_FORMS = (AYL_ADD, "ayl add", "ayl doctor", "ayl backup", "ayl restore")
# Docs that tell a reader what to type at `ayl add`, plus the front page.
COMMAND_DOCS = ("docs/add-your-own-books.md", "docs/upgrading.md", "README.md")
# The other programs these pages also show, so that a flag is attributed to the
# right one: a flag belongs to the last command named at or before it in the
# file, which is how a reader reads the page. Only names that are a command AND
# carry a flag on these three pages are listed. `chainlit` and `ollama` are
# deliberately absent: they appear as the directory `.chainlit/` and as the value
# of `LLM_BACKEND=ollama` far more often than as a command, and neither may take
# a flag away from the command named above it.
COMMANDS = AYL_ADD_FORMS + ("ayl ask", "ayl books", "ayl ui", "ask-library",
                            "ingest_demo_corpus.py", "install-mac.sh")
FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")


def ayl_add_parser():
    """The parser `ayl-add` actually runs. `main()` used to build it inline, so
    there was no way to ask it what it accepts without running a command;
    `build_parser()` was split out for this check (#72)."""
    from ask_your_library.ingest.add_folder import build_parser
    return build_parser()


def commands_in(text: str) -> list[tuple[int, str]]:
    """(column, command) for every command name on the line, in the order they
    are written. `ayl-add --doctor --db ~/i` names one; "the demo corpus goes
    through `scripts/ingest_demo_corpus.py --stage ingest`" names another."""
    return sorted((match.start(), name)
                  for name in COMMANDS
                  for match in re.finditer(re.escape(name), text))


def flags_attributed_to_ayl_add() -> list[tuple[str, int, str]]:
    """(doc, line number, flag) for every `--flag` whose nearest preceding
    command mention — on the same line, or on the closest line above it — is
    one of AYL_ADD_FORMS, i.e. the ingest parser under any of its names. A flag
    written before any command has been named in the file belongs to nothing
    this test can identify and is left alone."""
    found: list[tuple[str, int, str]] = []
    for doc in COMMAND_DOCS:
        carried: str | None = None      # the last command named on an earlier line
        for number, text, _ in prose_and_code(REPO / doc):
            named = commands_in(text)
            for flag in FLAG.finditer(text):
                earlier = [name for at, name in named if at < flag.start()]
                owner = earlier[-1] if earlier else carried
                if owner in AYL_ADD_FORMS:
                    found.append((doc, number, flag.group(1)))
            if named:
                carried = named[-1][1]
    return found


def test_every_ayl_add_flag_the_docs_mention_is_one_the_parser_accepts():
    """A flag in a doc is something a reader will type. Renamed or dropped, the
    page turns into a command that exits 2."""
    # `_actions` is argparse's own list and the only way to ask a parser what it
    # accepts; there is no public accessor, and re-listing the flags here would
    # be the second copy this test exists to make unnecessary.
    accepted = {option for action in ayl_add_parser()._actions for option in action.option_strings}
    mentioned = flags_attributed_to_ayl_add()
    problems = sorted({f"{doc}:{number}: {flag} is not an option of `{AYL_ADD}`"
                       for doc, number, flag in mentioned if flag not in accepted})
    report(problems, f"`{AYL_ADD}` flags the docs name and the parser does not accept")
    # The attribution above is a heuristic over prose, so it is worth knowing it
    # still finds something: a rewrite that hid every command name would leave
    # this test checking nothing and passing.
    distinct = {flag for _, _, flag in mentioned}
    assert len(distinct) >= 8, (f"only {len(distinct)} distinct flags were attributed to "
                                f"`{AYL_ADD}`: {sorted(distinct)}")
