#!/usr/bin/env python3
"""
Parse CSV from the clipboard and insert the data rows into a bookmarked
table in a specific Word document file.

Works on Windows (COM), macOS (AppleScript), and Linux (python-docx / file).

On Windows and macOS the document is opened if not already, or the running
instance is used. On Linux the file is edited directly on disk (close it in
Word first).

The first row is treated as a header and skipped — set HEADING_ROWS = 0
if your CSV has no header row.

Example:
    Name,Role,Location
    Alice,Engineer,Perth
    Bob,Analyst,Sydney

Configure the constants below, then drop this file into your ClipCommand
transforms/ folder and select it from the dropdown.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

WORD_DOC_PATH = r"C:\path\to\your\document.docx"   # update this
BOOKMARK      = "bk1"
HEADING_ROWS  = 1      # set to 0 if CSV has no header row
DELIMITER     = ","    # change to "\t" for TSV, ";" for European CSV

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

    data = rows[HEADING_ROWS:]
    if not data:
        return "[word_from_csv] Only a header row found — no data rows to insert."

    try:
        status = update_table(BOOKMARK, data, HEADING_ROWS,
                              doc_path=WORD_DOC_PATH)
        return f"[word_from_csv] {status}"
    except WordUtilsError as exc:
        return f"[word_from_csv] Error: {exc}"
