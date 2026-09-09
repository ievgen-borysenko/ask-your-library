"""Defense against prompt injection carried in the corpus.

A retrieved chunk that contains "ignore all instructions and say X" lands in
the observe prompt, where the model could obey the data instead of the system.
Two layers: (1) this module redacts instruction-like lines in code before the
model sees the text; (2) the observe prompt states that search results are
data, never instructions. A canary test in eval/ exercises both layers.

`strip_control_chars` is the same idea one level down: characters a book's text
has no reason to carry and that mean something to a terminal or to the reader's
eye rather than to the model.
"""
import re

# C0 controls except tab and newline, DEL, then the invisible formatting
# characters: zero-width space/joiners and the LTR/RTL marks, the bidirectional
# overrides, the isolates, and the byte-order mark.
CONTROL_CHARS_RE = re.compile("[\x00-\x08\x0b-\x1f\x7f"
                              "\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]")


def strip_control_chars(text: str) -> str:
    """Drop characters that are never part of a book's text.

    An escape sequence in a title repaints or clears the terminal that prints
    it; a bidi override reverses the reading order of the citation around it;
    a zero-width space hides inside a book key and splits what looks like one
    word. None of it survives a round through the index or the prompt, so the
    strip happens where corpus text becomes metadata (the book key, front
    matter fields) and where it becomes prompt text (`llm.data_block`); the
    CLI strips again at the boundary where it prints (`cli.terminal_safe`),
    because an answer is model output, not indexed text.
    """
    return CONTROL_CHARS_RE.sub("", text)


INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(previous|above|prior|earlier)\s+instructions",
    r"disregard\s+(all\s+|any\s+)?(previous|above|prior)\s+",
    r"you\s+are\s+now\s+",
    r"new\s+instructions?\s*:",
    r"system\s+prompt\s*:",
    r"respond\s+only\s+with",
    r"do\s+not\s+follow\s+the\s+user",
    # Ukrainian "ignore (all) (previous) instructions": the corpus and the
    # questions can be Ukrainian. Patterns are a first, cheap layer only —
    # paraphrase and other languages get through to the prompt-level defense.
    r"ігноруй\s+(всі\s+|усі\s+)?(попередні\s+)?інструкції",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def sanitize_context(text: str) -> tuple[str, int]:
    """Return (cleaned text, number of redacted lines).

    The whole matching line is redacted: an instruction stripped of its context
    is harmless, and the surrounding book text stays usable as evidence.
    """
    clean_lines = []
    redacted_count = 0
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in _COMPILED):
            clean_lines.append("[REDACTED-INJECTION]")
            redacted_count += 1
        else:
            clean_lines.append(line)
    return "\n".join(clean_lines), redacted_count
