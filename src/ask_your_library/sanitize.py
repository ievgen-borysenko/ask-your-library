"""Defense against prompt injection carried in the corpus.

A retrieved chunk that contains "ignore all instructions and say X" lands in
the observe prompt, where the model could obey the data instead of the system.
Two layers: (1) this module redacts instruction-like lines in code before the
model sees the text; (2) the observe prompt states that search results are
data, never instructions. A canary test in eval/ exercises both layers.
"""
import re

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
