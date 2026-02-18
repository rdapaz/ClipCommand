#!/usr/bin/env python3
"""
Strip leading/trailing whitespace, remove trailing spaces from every line,
and collapse runs of 3+ blank lines down to 2. Useful for cleaning up
copied code, log output, or document text before pasting.
"""
import re


def transform(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    return text
