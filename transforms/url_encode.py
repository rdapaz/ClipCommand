#!/usr/bin/env python3
"""
Percent-encode (URL-encode) the clipboard text so it is safe to embed in
a URL query string. All characters except unreserved ones are encoded.
"""
from urllib.parse import quote


def transform(text: str) -> str:
    return quote(text, safe="")
