#!/usr/bin/env python3
"""
Remove duplicate lines while preserving first-seen order.
Unlike line_sort (which sorts and dedups), this keeps the original ordering —
useful for de-duping logs, playlists, or config lines without reshuffling them.
"""


def transform(text: str) -> str:
    seen = set()
    result = []
    for line in text.splitlines():
        if line not in seen:
            seen.add(line)
            result.append(line)
    return "\n".join(result)
