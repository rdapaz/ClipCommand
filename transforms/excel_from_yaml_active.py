#!/usr/bin/env python3
"""
Parse a YAML list-of-lists from the clipboard and write it into the active
Excel workbook starting at START_CELL of the active (or named) sheet.

Input  : YAML list-of-lists  (e.g. output of firewall_csv_filter)
Output : Status message; data written directly into Excel via COM / AppleScript

Expected YAML shape
-------------------
    - [col1, col2, col3]
    - [val1, val2, val3]
    - ...

Configuration
-------------
SHEET_NAME    : str | None  — target sheet name; None = active sheet
START_CELL    : str         — top-left destination cell, default "A1"
WORKBOOK_PATH : str | None  — path to .xlsx for Linux fallback only
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from _excel_utils import update_sheet, ExcelUtilsError

# ── Configuration ─────────────────────────────────────────────────────────────

SHEET_NAME    = None     # None = active sheet; "Firewall Rules" to target by name
START_CELL    = "A1"
WORKBOOK_PATH = None     # Required on Linux only

# ─────────────────────────────────────────────────────────────────────────────

def transform(text: str) -> str:
    # Strip comment lines emitted by transforms like firewall_csv_filter
    clean = "\n".join(
        line for line in text.splitlines() if not line.startswith("#")
    )

    try:
        data = yaml.safe_load(clean)
    except yaml.YAMLError as exc:
        return f"[excel_from_yaml] YAML parse error: {exc}"

    if not isinstance(data, list):
        return "[excel_from_yaml] Expected a YAML list-of-lists at the top level."

    # Normalise: each row must itself be a list
    rows = [row if isinstance(row, list) else [row] for row in data]

    if not rows:
        return "[excel_from_yaml] No data rows found."

    try:
        status = update_sheet(
            data=rows,
            sheet_name=SHEET_NAME,
            start_cell=START_CELL,
            workbook_path=WORKBOOK_PATH,
        )
        return f"[excel_from_yaml] {status}"
    except ExcelUtilsError as exc:
        return f"[excel_from_yaml] Error: {exc}"
