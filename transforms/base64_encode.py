#!/usr/bin/env python3
"""
Base64-encode the clipboard text (UTF-8). Useful for embedding binary
data in config files, emails, or API payloads.
"""
import base64


def transform(text: str) -> str:
    return base64.b64encode(text.encode()).decode()
