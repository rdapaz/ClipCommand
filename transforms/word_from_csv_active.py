#!/usr/bin/env python3
"""
Parse CSV from the clipboard and insert the data rows into a bookmarked
table in the currently active Word document.

Works on Windows (COM), macOS (AppleScript), and Linux (python-docx / file).

The first row is treated as a header and skipped — set HEADING_ROWS = 0
if your CSV has no header row.

Example:
    Name,Role,Location
    Alice,Engineer,Perth
    Bob,Analyst,Sydney

Configure the constants below, then drop this file into your ClipCommand
transforms/ folder. On Linux, set DOC_PATH to your .docx file path.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

BOOKMARK     = "bk1"
HEADING_ROWS = 1      # set to 0 if CSV has no header row
DELIMITER    = "|gi"    # change to "\t" for TSV, ";" for European CSV
DOC_PATH     = ""     # Linux only — leave blank on Windows / macOS

# ─────────────────────────────────────────────────────────────────────────────

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from word_utils import update_table, WordUtilsError


def transform(text: str) -> str:
    try:
        reader = csv.reader(io.StringIO(text.strip()), delimiter=DELIMITER)
        rows   = list(reader)
    except csv.Error as exc:
        return f"[word_from_csv] CSV parse error: {exc}"

    if not rows:
        return "[word_from_csv] No data found in clipboard — nothing to insert."

    # All clipboard rows are data — HEADING_ROWS only controls the Word table
    # offset (how many heading rows already exist in the table to skip over).
    data = rows

    try:
        status = update_table(BOOKMARK, data, HEADING_ROWS,
                              doc_path=DOC_PATH or None)
        return f"[word_from_csv] {status}"
    except WordUtilsError as exc:
        return f"[word_from_csv] Error: {exc}"