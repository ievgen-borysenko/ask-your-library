"""How a URL-valued setting is printed (F8-url-allowlist): an allowlist, not a
redaction. `dataflow.shown_url` and the installer's bash `shown_url` print only
`scheme://host[:port]` rebuilt from a strict full match, "(path not shown)"
when anything followed, and fixed words for a value with an `@` anywhere or
one the pattern does not match whole. The two are held to one table of
inputs, to the same pattern text, and to a property: whatever is inserted as
user name, password, path or query, no slice of four characters of it reaches
the printed form unless that slice is in the scheme, host or port.
"""
import random
import re
import shutil
import string
import subprocess

import pytest

from ask_your_library import dataflow
from conftest import REPO

SCRIPT = REPO / "scripts" / "install-mac.sh"
BASH = shutil.which("bash")
NS = dataflow.NOT_SHOWN

CASES = [
    ("http://localhost:11434", "http://localhost:11434"),
    ("http://127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("https://openrouter.ai/api/v1", "https://openrouter.ai (path not shown)"),
    ("http://[::1]:11434", "http://[::1]:11434"),
    ("http://127.0.0.1:11434/?key=Tq9Wz3Lm", "http://127.0.0.1:11434 (path not shown)"),
    ("http://127.0.0.1:11434/Pz8Xk2Nj/api", "http://127.0.0.1:11434 (path not shown)"),
    ("http://127.0.0.1:11434#Fr4g", "http://127.0.0.1:11434 (path not shown)"),
    ("http://reader:Gx7Rk2Tq@127.0.0.1:11434", NS),
    ("http://reader:Gx7/Rk2@127.0.0.1:11434", NS),
    ("http://reader:Gx7?Rk2@127.0.0.1:11434", NS),
    ("http://reader:Gx7#Rk2@127.0.0.1:11434", NS),
    ("http://reader:Gx7@Rk2@127.0.0.1:11434", NS),
    ("uQ7zK9:Zq8Lr2Vx@127.0.0.1:11434/via/http://gw", NS),
    ("uQ7zK9:Kp4v://Yz6w@127.0.0.1:11434", NS),
    ("http://uQ7%40zK9:Mv5%40Rq3@127.0.0.1:11434", NS),
    ("http://uQ7zK9:Hn3Bv7Qs@[::1]:11434", NS),
    ("http://host/path@x", NS),
    ("127.0.0.1:11434", NS),
    ("localhost:11434", NS),
    ("http://", NS),
    ("http://:11434", NS),
    ("http://h st", NS),
    ("1http://h", NS),
    ("", NS),
]


def bash_shown(values):
    """The installer's own function, sourced from the script, over `values`
    (one per line, none holding a newline)."""
    program = ("eval \"$(sed -n '/^NOT_SHOWN=/,/^}/p' \"$1\")\"\n"
               "while IFS= read -r value; do shown_url \"$value\"; done\n")
    result = subprocess.run([BASH, "-c", program, "-", str(SCRIPT)],
                            input="".join(f"{v}\n" for v in values),
                            capture_output=True, text=True, check=True)
    return result.stdout.splitlines()


@pytest.mark.parametrize("value, printed", CASES)
def test_the_python_function(value, printed):
    assert dataflow.shown_url(value) == printed
    assert dataflow.carries_credential(value) is (printed == NS)


@pytest.mark.skipif(BASH is None, reason="no bash on this system")
def test_the_bash_function_prints_exactly_what_the_python_one_does():
    values = [value for value, _ in CASES]
    assert bash_shown(values) == [printed for _, printed in CASES]


def test_the_two_patterns_and_words_are_the_same_text():
    text = SCRIPT.read_text(encoding="utf-8")
    bash_pattern = re.search(r"^PLAIN_URL_RE='\^(.*)\$'$", text, re.M).group(1)
    assert bash_pattern == dataflow.PLAIN_URL.pattern
    assert f'NOT_SHOWN="{NS}"' in text


ALPHABET = string.ascii_letters + string.digits + "/?#@:%.-_~+=&[]!$'()*,;"


def _random(rng, length):
    return "".join(rng.choice(ALPHABET) for _ in range(length))


def _leaks(printed, inserted, allowed):
    return sorted({inserted[at:at + 4] for at in range(len(inserted) - 3)
                   if inserted[at:at + 4] in printed and inserted[at:at + 4] not in allowed})


@pytest.mark.parametrize("seed", range(5))
def test_nothing_inserted_reaches_the_printed_form(seed):
    """Random user names, passwords, paths and queries: a slice of four of
    them is printed only where it is also part of the scheme, host or port."""
    rng = random.Random(seed)
    built = []
    for _ in range(80):
        host = rng.choice(["127.0.0.1", "localhost", "ollama.example", "[::1]"])
        port = rng.choice(["", ":11434", ":8080"])
        user, password, path, query = (_random(rng, rng.randint(4, 16)) for _ in range(4))
        # our own words are not the value's: a random "path" is not a leak
        allowed = f"http://{host}{port}{dataflow.PATH_NOT_SHOWN} {NS}"
        for value in (f"http://{user}:{password}@{host}{port}/{path}?{query}",
                      f"http://{host}{port}/{path}?{query}",
                      f"{user}:{password}@{host}{port}",
                      f"http://{user}@{host}{port}"):
            built.append((value, (user, password, path, query), allowed))
    printed_py = [dataflow.shown_url(value) for value, _, _ in built]
    printed_sh = bash_shown([value for value, _, _ in built]) if BASH else printed_py
    assert printed_sh == printed_py
    for (value, inserted, allowed), printed in zip(built, printed_py):
        for piece in inserted:
            assert not _leaks(printed, piece, allowed), (value, printed)
