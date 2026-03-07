#!/usr/bin/env python3
"""
Parse CSV from the clipboard and write it into the active Excel workbook
starting at cell A1 (or START_CELL) of the active (or named) sheet.

Input  : CSV text (comma-delimited by default)
Output : Status message; data written directly into Excel via COM / AppleScript

Configuration
-------------
SHEET_NAME   : str | None  — target sheet name; None = active sheet
START_CELL   : str         — top-left destination cell, default "A1"
DELIMITER    : str         — CSV field delimiter, default ","
SKIP_HEADER  : bool        — False = include header row in output (default)
WORKBOOK_PATH: str | None  — path to .xlsx for Linux fallback only
"""

import csv
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _excel_utils import update_sheet, ExcelUtilsError

# ── Configuration ─────────────────────────────────────────────────────────────

SHEET_NAME    = None     # None = active sheet; "Sheet1" to target by name
START_CELL    = "A1"
DELIMITER     = "|"
SKIP_HEADER   = False
WORKBOOK_PATH = None     # Required on Linux only

# ─────────────────────────────────────────────────────────────────────────────

def transform(text: str) -> str:
    try:
        reader = csv.reader(io.StringIO(text.strip()), delimiter=DELIMITER)
        rows   = list(reader)
    except csv.Error as exc:
        return f"[excel_from_csv] CSV parse error: {exc}"

    if not rows:
        return "[excel_from_csv] No data found in clipboard."

    if SKIP_HEADER:
        rows = rows[1:]

    if not rows:
        return "[excel_from_csv] Only a header row — no data to write."

    try:
        status = update_sheet(
            data=rows,
            sheet_name=SHEET_NAME,
            start_cell=START_CELL,
            workbook_path=WORKBOOK_PATH,
        )
        return f"[excel_from_csv] {status}"
    except ExcelUtilsError as exc:
        return f"[excel_from_csv] Error: {exc}"
