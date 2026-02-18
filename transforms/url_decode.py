#!/usr/bin/env python3
"""
Decode a percent-encoded (URL-encoded) string back to plain text.
Useful when inspecting encoded URLs or query parameters.
"""
from urllib.parse import unquote


def transform(text: str) -> str:
    return unquote(text)
