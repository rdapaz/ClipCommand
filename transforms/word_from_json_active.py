#!/usr/bin/env python3
"""
Parse JSON from the clipboard (a list of lists) and insert the rows into a
bookmarked table in the currently active Word document.

Works on Windows (COM), macOS (AppleScript), and Linux (python-docx / file).

The JSON must be a list of lists:
    [
        ["Alpha", "Bravo",  "Charlie"],
        ["Delta", "Echo",   "Foxtrot"],
        ["Golf",  "Hotel",  "India"]
    ]

Configure the constants below, then drop this file into your ClipCommand
transforms/ folder. On Linux, set DOC_PATH to your .docx file path.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

BOOKMARK     = "bk1"
HEADING_ROWS = 1
DOC_PATH     = ""   # Linux only — leave blank on Windows / macOS

# ─────────────────────────────────────────────────────────────────────────────

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _word_utils import update_table, WordUtilsError


def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return f"[word_from_json] JSON parse error: {exc}"

    if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
        return "[word_from_json] Input must be a JSON list of lists."
    if not data:
        return "[word_from_json] No data rows found — nothing to insert."

    try:
        status = update_table(BOOKMARK, data, HEADING_ROWS,
                              doc_path=DOC_PATH or None)
        return f"[word_from_json] {status}"
    except WordUtilsError as exc:
        return f"[word_from_json] Error: {exc}"
