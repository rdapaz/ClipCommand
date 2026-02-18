#!/usr/bin/env python3
"""
Parse YAML from the clipboard (a list of lists) and insert the rows into a
bookmarked table in a specific Word document file.

Works on Windows (COM), macOS (AppleScript), and Linux (python-docx / file).

On Windows and macOS the document is opened if not already, or the running
instance is used. On Linux the file is edited directly on disk (close it in
Word first).

The YAML must be a sequence of sequences:
    - ["Alpha", "Bravo",  "Charlie"]
    - ["Delta", "Echo",   "Foxtrot"]
    - ["Golf",  "Hotel",  "India"]

Configure the constants below, then drop this file into your ClipCommand
transforms/ folder and select it from the dropdown.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

WORD_DOC_PATH = r"C:\path\to\your\document.docx"   # update this
BOOKMARK      = "bk1"
HEADING_ROWS  = 1

# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from word_utils import update_table, WordUtilsError


def transform(text: str) -> str:
    try:
        import yaml
    except ImportError:
        return "[word_from_yaml] PyYAML not installed — pip install pyyaml"

    try:
        data = yaml.safe_load(text.strip())
    except yaml.YAMLError as exc:
        return f"[word_from_yaml] YAML parse error: {exc}"

    if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
        return "[word_from_yaml] Input must be a YAML sequence of sequences."
    if not data:
        return "[word_from_yaml] No data rows found — nothing to insert."

    try:
        status = update_table(BOOKMARK, data, HEADING_ROWS,
                              doc_path=WORD_DOC_PATH)
        return f"[word_from_yaml] {status}"
    except WordUtilsError as exc:
        return f"[word_from_yaml] Error: {exc}"
