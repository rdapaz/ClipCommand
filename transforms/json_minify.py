#!/usr/bin/env python3
"""
Minify JSON by removing all unnecessary whitespace. Useful for compacting
JSON before embedding in config files or API calls.
Returns an error message (and the original text) if the input is not
valid JSON.
"""
import json


def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"[JSON error: {e}]\n{text}"
