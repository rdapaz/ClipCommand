#!/usr/bin/env python3
"""
Remove ANSI escape / colour codes from terminal output so the plain text
can be pasted into documents, tickets, or emails without garbage characters.
"""
import re

_ANSI = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def transform(text: str) -> str:
    return _ANSI.sub("", text)
