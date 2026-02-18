#!/usr/bin/env python3
"""
Base64-decode the clipboard text back to a UTF-8 string.
Returns an error message (and the original text) if decoding fails.
"""
import base64


def transform(text: str) -> str:
    try:
        return base64.b64decode(text.strip().encode()).decode()
    except Exception as e:
        return f"[base64 decode error: {e}]\n{text}"
