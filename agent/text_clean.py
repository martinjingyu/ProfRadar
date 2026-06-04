from __future__ import annotations

import re


TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
EXCESS_NEWLINES = re.compile(r"\n{4,}")
LONG_DASHES = re.compile(r"^-{5,}$", re.MULTILINE)
LONG_EQUALS = re.compile(r"^={5,}$", re.MULTILINE)


def clean_text(text: str) -> str:
    """Normalize low-information whitespace and divider noise in tool results."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = TRAILING_SPACE.sub("", text)
    text = EXCESS_NEWLINES.sub("\n\n\n", text)
    text = LONG_DASHES.sub("---", text)
    text = LONG_EQUALS.sub("===", text)
    return text
