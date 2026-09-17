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

The parser here is a deliberately small markdown reader — fences, links, code
spans, headings — rather than a dependency: the suite installs from a lockfile
and a docs check is not worth a new one.
"""
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

from conftest import REPO

# --- a very small markdown reader -------------------------------------------

FENCE = re.compile(r"^\s{0,3}(```|~~~)")
# [text](target) and ![alt](target). The target may carry a "title" after a
# space, which is not part of the path.
INLINE_LINK = re.compile(r"!?\[[^\]\[]*\]\(\s*<?([^)<>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
# A reference definition at the start of a line: [label]: target
REFERENCE_LINK = re.compile(r"^\[[^\]]+\]:\s*<?(\S+)>?")
CODE_SPAN = re.compile(r"`([^`]+)`")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
# Schemes a relative-path check must not touch.
EXTERNAL = ("http://", "https://", "mailto:", "tel:", "ftp://")


def tracked_markdown() -> list[Path]:
    """Every .md file git knows about — README.md, docs/**, .github/**, the
    corpus cards. A file that is not tracked is not published, so it is not
    part of what a release promises."""
    listed = subprocess.run(["git", "ls-files", "*.md"], cwd=REPO,
                            capture_output=True, text=True, check=True).stdout
    return [REPO / name for name in listed.splitlines() if name]


def prose_and_code(path: Path) -> list[tuple[int, str, bool]]:
    """(line number, text, inside a fenced block) for every line of the file.

    One pass over the file answers both halves of this module: the link checks
    read the prose lines, the path check reads the fenced ones, and neither has
    to re-learn where a fence opened."""
    rows: list[tuple[int, str, bool]] = []
    fence: str | None = None
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        opening = FENCE.match(text)
        if fence is None and opening:
            fence = opening.group(1)
            rows.append((number, text, True))
            continue
        if fence is not None:
            rows.append((number, text, True))
            if opening and opening.group(1) == fence:
                fence = None
            continue
        rows.append((number, text, False))
    return rows


def slug(title: str) -> str:
    """GitHub's heading anchor: the text lowercased, punctuation dropped
    (hyphens and underscores survive), spaces turned into hyphens. Backticks in
    a heading are punctuation, so `observe` in a title contributes `observe`."""
    text = title.strip().lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    return re.sub(r"\s+", "-", text.strip())


_ANCHORS: dict[Path, set[str]] = {}


def anchors_of(path: Path) -> set[str]:
    """Every fragment a link may point at in this file: one slug per heading,
    with GitHub's -1 / -2 suffixes for repeated titles."""
    if path not in _ANCHORS:
        found: set[str] = set()
        for _, text, in_fence in prose_and_code(path):
            if in_fence:
                continue            # `# comment` in a shell block is not a heading
            heading = HEADING.match(text)
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
        _ANCHORS[path] = found
    return _ANCHORS[path]


def targets_of(path: Path) -> list[tuple[int, str]]:
    """(line number, target) for every inline link, image and reference
    definition outside a fenced block. Links inside a fence are samples of
    markdown, not links this tree makes."""
    found: list[tuple[int, str]] = []
    for number, text, in_fence in prose_and_code(path):
        if in_fence:
            continue
        for target in INLINE_LINK.findall(text):
            found.append((number, target))
        reference = REFERENCE_LINK.match(text)
        if reference:
            found.append((number, reference.group(1)))
    return found


def report(problems: list[str], headline: str) -> None:
    """A failure reads as a to-do list: one line per offence, in file order."""
    if problems:
        pytest.fail(f"{headline} ({len(problems)}):\n" + "\n".join(problems), pytrace=False)


# --- 1. links ----------------------------------------------------------------

def test_every_internal_link_resolves_and_every_fragment_names_a_heading():
    """A relative link or image points at a file this tree holds, and a
    `#fragment` names a heading of the file it points at (or of this file, when
    the link is a bare anchor). External links are not fetched — see the module
    docstring."""
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
            resolved = (path.parent / file_part).resolve()
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

# Prefixes a doc may name although this tree does not hold them. Each entry says
# why, because an unexplained allowlist is how a broken path survives.
PATHS_DOCS_MAY_NAME_WITHOUT_HOLDING = {
    # EVAL_RESULTS_DIR, gitignored: an eval report records the scratch file the
    # run itself wrote ("not committed" is written beside it in the reports),
    # which is a fact about that run and not a file a reader can open.
    "eval/results/": "written by a run, never committed (EVAL_RESULTS_DIR)",
}
# The ingest package lives at src/ask_your_library/ingest/, and the docs name its
# modules by the shorthand a developer uses in conversation — `ingest/chapters.py`
# for the chapter splitter. The file is real, so the shorthand is resolved rather
# than reported: what this check is for is a path that points at nothing.
PACKAGE_SHORTHAND = ("ingest/", "src/ask_your_library/")


def path_exists(token: str) -> bool:
    """Whether the path a doc wrote names a file this tree holds, at the root or
    under the shorthand above."""
    if (REPO / token).exists():
        return True
    prefix, package = PACKAGE_SHORTHAND
    return token.startswith(prefix) and (REPO / package / token).exists()


def documented_paths(path: Path) -> list[tuple[int, str]]:
    """(line number, path) for every file path named in a code span or a fenced
    block. Prose is left alone on purpose: a path in running text is often a
    shape ("a file under docs/…"), while one in code is something to type."""
    found: list[tuple[int, str]] = []
    for number, text, in_fence in prose_and_code(path):
        haystack = [text] if in_fence else CODE_SPAN.findall(text)
        for piece in haystack:
            for token in DOC_PATH.findall(piece):
                found.append((number, token))
    return found


def test_every_file_path_named_in_the_docs_exists():
    """`eval/run_agent_eval.py`, `docs/eval-results/...`, `scripts/...`: a path
    written as something to type is a file this tree holds."""
    problems: list[str] = []
    checked = 0
    for path in tracked_markdown():
        where = path.relative_to(REPO)
        for number, token in documented_paths(path):
            if any(token.startswith(prefix) for prefix in PATHS_DOCS_MAY_NAME_WITHOUT_HOLDING):
                continue
            checked += 1
            if not path_exists(token):
                problems.append(f"{where}:{number}: {token}")
    report(problems, "file paths named in the docs that do not exist")
    # A parser that stopped matching would report nothing and pass. The docs
    # name hundreds of paths; this is a floor, not a count to keep up to date.
    assert checked > 100, f"only {checked} paths were checked: the path pattern stopped matching"


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


def test_a_tagged_commit_carries_an_empty_unreleased_section_and_a_matching_tag():
    """At a tag, everything the changelog holds has been released: an
    `## Unreleased` section with anything in it means the tag describes work it
    does not name. Off a tag there is nothing to check — that is the ordinary
    state of a branch, so this skips rather than passes silently."""
    described = subprocess.run(["git", "describe", "--tags", "--exact-match", "HEAD"],
                               cwd=REPO, capture_output=True, text=True)
    if described.returncode != 0:
        pytest.skip("HEAD is not tagged: an Unreleased section is expected to have content here")
    tag = described.stdout.strip()
    version = project_version()
    assert tag == f"v{version}", (
        f"HEAD is tagged {tag} but pyproject.toml says version = \"{version}\"")
    for number, heading, body in changelog_sections():
        if heading.lower() == "unreleased":
            assert not "".join(body).strip(), (
                f"{CHANGELOG.relative_to(REPO)}:{number}: the Unreleased section still has "
                f"content at tag {tag} — it belongs under `## {version}`")


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
    decision record nobody reading the index can find."""
    index_text = ADR_INDEX.read_text(encoding="utf-8")
    problems = [f"docs/adr/{path.name}: not linked from docs/adr/README.md"
                for path in sorted(ADR_DIR.glob("*.md"))
                if path.name != "README.md" and path.name not in index_text]
    report(problems, "ADR files the index does not link")


# --- 5. settings and commands ------------------------------------------------

CONFIGURATION = REPO / "docs" / "configuration.md"
# The helpers config.py reads the environment through. _env, _positive_int and
# _non_negative_int all take the variable name first, so one pattern finds them
# all along with the plain os.environ / os.getenv reads.
ENV_READ = re.compile(r"(?:os\.environ\.get|os\.getenv|os\.environ\[|_env|_positive_int|"
                      r"_non_negative_int)\(\s*\"([A-Z][A-Z0-9_]+)\"")
# A name in a code span that looks like a setting: SHOUTING_SNAKE_CASE, at least
# four characters, and not a fragment of a longer name or a `NAME_*` wildcard —
# the docs write `OLLAMA_PRICE_*` and `*_TRACING_V2` when they mean a family.
SETTING_NAME = re.compile(r"(?<![A-Z0-9_*])([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)(?![A-Z0-9_*])")

# Where a setting may be read from. config.py is the main one, but the UI, the
# ingest package and the eval harness read their own, and a reader does not care
# which file it is in — only that something in this tree acts on the name.
SOURCE_ROOTS = ("src", "eval", "scripts", "ui.py")

# Names configuration.md documents that nothing in this tree reads, with the
# reason each is there. A reader still has to set them, so the page is right to
# carry them; they are simply not ours to read.
SETTINGS_READ_OUTSIDE_THIS_TREE = {
    "LANGSMITH_API_KEY": "read by the LangSmith SDK, not by this package",
    "LANGSMITH_TRACING": "read by the LangSmith SDK (the legacy flag)",
    "LANGSMITH_TRACING_V2": "read by the LangSmith SDK, which takes precedence over LANGCHAIN_*",
    "OLLAMA_CONTEXT_LENGTH": "read by the Ollama server, which decides the context window",
}


def config_variables() -> set[str]:
    """Every environment variable config.py resolves at import time — the file
    that decides what the shipped default is, and therefore the one whose
    settings a reader has the strongest claim to find documented."""
    return set(ENV_READ.findall((REPO / "src" / "ask_your_library" / "config.py")
                                .read_text(encoding="utf-8")))


def source_text() -> str:
    """Every Python file that could read a setting, concatenated. A plain search
    over the text, not an import: fake_backend.py holds its two variable names
    in constants (ENABLE_VAR / CONFIRM_VAR), and the question here is whether
    the name appears in the code at all, not how it is spelled at the call."""
    pieces = []
    for root in SOURCE_ROOTS:
        target = REPO / root
        files = [target] if target.is_file() else sorted(target.rglob("*.py"))
        pieces.extend(path.read_text(encoding="utf-8") for path in files)
    return "\n".join(pieces)


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


def test_every_variable_config_reads_is_documented():
    """A setting that exists and is not on the page is a setting nobody can
    find; config.py is the list, docs/configuration.md is the promise."""
    page = CONFIGURATION.read_text(encoding="utf-8")
    problems = [f"docs/configuration.md: {name} is read by src/ask_your_library/config.py "
                f"and documented nowhere on this page"
                for name in sorted(config_variables()) if f"`{name}`" not in page]
    report(problems, "settings the code reads and the docs do not describe")


def test_every_setting_the_docs_describe_is_read_somewhere():
    """The other direction, and the one a rename breaks: a name on the page that
    no longer appears in the code is an instruction to set something that does
    nothing."""
    code = source_text()
    documented = documented_settings()
    problems: list[str] = []
    for number, name in documented:
        if name in SETTINGS_READ_OUTSIDE_THIS_TREE or f'"{name}"' in code or f"'{name}'" in code:
            continue
        problems.append(f"docs/configuration.md:{number}: {name} is documented but read "
                        f"nowhere under {', '.join(SOURCE_ROOTS)}")
    report(problems, "settings the docs describe and nothing reads")
    # The page's table is the list; a span pattern that stopped matching would
    # leave this test with nothing to check and still pass.
    assert len({name for _, name in documented}) > 30, (
        "the configuration table yielded almost no names: the code-span pattern stopped matching")


# `ayl-add` is the console script pyproject declares; its options are the
# parser's, so the docs are compared against the parser itself rather than
# against a list kept beside it.
AYL_ADD = "ayl-add"
# Docs that tell a reader what to type at `ayl-add`, plus the front page.
COMMAND_DOCS = ("docs/add-your-own-books.md", "docs/upgrading.md", "README.md")
# The other programs these pages also show, so that a flag is attributed to the
# right one: a flag belongs to the last command named at or before it in the
# file, which is how a reader reads the page. Only names that are a command AND
# carry a flag on these three pages are listed. `chainlit` and `ollama` are
# deliberately absent: they appear as the directory `.chainlit/` and as the value
# of `LLM_BACKEND=ollama` far more often than as a command, and neither may take
# a flag away from the command named above it.
COMMANDS = (AYL_ADD, "ask-library", "ingest_demo_corpus.py", "install-mac.sh")
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
    `ayl-add`. A flag written before any command has been named in the file
    belongs to nothing this test can identify and is left alone."""
    found: list[tuple[str, int, str]] = []
    for doc in COMMAND_DOCS:
        carried: str | None = None      # the last command named on an earlier line
        for number, text, _ in prose_and_code(REPO / doc):
            named = commands_in(text)
            for flag in FLAG.finditer(text):
                earlier = [name for at, name in named if at < flag.start()]
                owner = earlier[-1] if earlier else carried
                if owner == AYL_ADD:
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
