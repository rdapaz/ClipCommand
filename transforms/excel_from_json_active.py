#!/usr/bin/env python3
"""
Parse a JSON list-of-lists (or list-of-dicts) from the clipboard and write
it into the active Excel workbook starting at START_CELL of the active (or
named) sheet.

Input  : JSON array of arrays  →  written directly as rows/columns
         JSON array of objects →  keys become header row, values become data rows
Output : Status message; data written directly into Excel via COM / AppleScript

Configuration
-------------
SHEET_NAME    : str | None  — target sheet name; None = active sheet
START_CELL    : str         — top-left destination cell, default "A1"
WRITE_HEADERS : bool        — True = emit dict keys as first row (default True)
WORKBOOK_PATH : str | None  — path to .xlsx for Linux fallback only
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _excel_utils import update_sheet, ExcelUtilsError

# ── Configuration ─────────────────────────────────────────────────────────────

SHEET_NAME    = None     # None = active sheet
START_CELL    = "A1"
WRITE_HEADERS = True     # Emit dict keys as header row when input is list-of-dicts
WORKBOOK_PATH = None     # Required on Linux only

# ─────────────────────────────────────────────────────────────────────────────

def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return f"[excel_from_json] JSON parse error: {exc}"

    if not isinstance(data, list):
        return "[excel_from_json] Expected a JSON array at the top level."

    if not data:
        return "[excel_from_json] JSON array is empty."

    # ── Normalise to list-of-lists ────────────────────────────────────────────
    if isinstance(data[0], dict):
        # list-of-dicts → header row + value rows
        headers = list(data[0].keys())
        rows    = ([headers] if WRITE_HEADERS else []) + [
            [row.get(h, "") for h in headers] for row in data
        ]
    elif isinstance(data[0], list):
        rows = data
    else:
        # Flat array of scalars → single column
        rows = [[item] for item in data]

    try:
        status = update_sheet(
            data=rows,
            sheet_name=SHEET_NAME,
            start_cell=START_CELL,
            workbook_path=WORKBOOK_PATH,
        )
        return f"[excel_from_json] {status}"
    except ExcelUtilsError as exc:
        return f"[excel_from_json] Error: {exc}"
