#!/usr/bin/env python3
"""
Sort lines alphabetically (case-insensitive) and remove duplicates.
Useful for tidying lists of hostnames, IPs, tags, or import statements.
"""


def transform(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(sorted(set(lines), key=str.casefold))
