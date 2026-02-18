#!/usr/bin/env python3
"""
Pretty-print JSON with 2-space indentation and unicode preserved.
Returns an error message (and the original text) if the input is not
valid JSON.
"""
import json


def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
        return json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"[JSON error: {e}]\n{text}"
