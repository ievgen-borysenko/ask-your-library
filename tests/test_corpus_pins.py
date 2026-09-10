"""CI guard: every fetched source in the demo manifest carries a pin.

`verify_checksum` can only compare against what the manifest holds, so a
`sha256:` line removed by hand — or never added when a book was appended —
used to be the quietest possible change: nothing failed, the download went
ahead, and that book was simply no longer verified against anything while the
eval reports kept naming the manifest fingerprint as their provenance. The
stages now exit on a missing pin (see `verify_checksum`), and this says the
same thing without a network round trip, on every pull request rather than
only on the ones the corpus job runs for.

Canaries are the manifest's own exception, stated in corpus/README.md: their
text is committed to this repository, so there is no fetched file to pin.
"""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "corpus" / "manifest.yaml"

SHA256 = re.compile(r"[0-9a-f]{64}")


def manifest() -> dict:
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


def test_every_fetched_source_carries_a_sha256():
    """A Gutenberg entry pins the downloaded text, a LibriVox entry pins the
    transcript committed under prepared-audio/ — both are entries of `books`,
    and both are what a build reads. `isinstance(str)`, because an all-digit
    digest would come back from YAML as an int and never match anything."""
    problems = []
    for entry in manifest()["books"]:
        pin = entry.get("sha256")
        if not isinstance(pin, str) or not SHA256.fullmatch(pin):
            problems.append(f"  {entry['id']} ({entry['source']}): {pin!r}")
    assert not problems, (
        "manifest entries without a 64-hex sha256 — an unpinned source is not verified "
        "against anything:\n" + "\n".join(problems)
        + "\npin them with `uv run scripts/ingest_demo_corpus.py --stage checksums`")


def test_canaries_carry_no_sha256():
    """The other half of the rule, so "pin everything" is not read as licence to
    pin a file this repository writes itself: a canary checksum would only ever
    restate the working tree, and corpus/README.md says they carry none."""
    pinned = [e["id"] for e in manifest().get("canaries", []) if e.get("sha256")]
    assert not pinned, (f"canaries are committed text, not fetched sources, and pin nothing: "
                        f"{pinned}")
