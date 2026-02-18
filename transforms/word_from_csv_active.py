#!/usr/bin/env python3
"""
Parse CSV from the clipboard and insert the data rows into a bookmarked
table in the currently active Word document.

The Word document must already be open. The first row is treated as a
header and skipped — set HEADING_ROWS = 0 if your CSV has no header row.

Example clipboard content:
    Name,Role,Location
    Alice,Engineer,Perth
    Bob,Analyst,Sydney

Configure the constants below, then drop this file into your ClipCommand
transforms/ folder and select it from the dropdown.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

BOOKMARK     = "bk1"
HEADING_ROWS = 1      # set to 0 if CSV has no header row
DELIMITER    = ","    # change to "\t" for TSV, ";" for European CSV, etc.

# ─────────────────────────────────────────────────────────────────────────────

import csv
import io
import re
import sys


def _get_win32com_word():
    """Return a live Word.Application COM object, clearing the gen_py cache if needed."""
    import shutil
    from win32com import client
    try:
        return client.gencache.EnsureDispatch("Word.Application")
    except AttributeError:
        import os
        for mod in list(sys.modules):
            if re.match(r"win32com\.gen_py\..+", mod):
                del sys.modules[mod]
        shutil.rmtree(
            os.path.join(os.environ.get("LOCALAPPDATA"), "Temp", "gen_py"),
            ignore_errors=True,
        )
        return client.gencache.EnsureDispatch("Word.Application")


def _update_table(app, doc, bookmark, data, heading_rows):
    """Insert *data* (list of lists) into the first table inside *bookmark*."""
    word_range  = doc.Bookmarks(bookmark).Range
    table       = word_range.Tables(1)
    rows_needed = len(data) + heading_rows

    if table.Rows.Count < rows_needed:
        table.Select()
        app.Selection.InsertRowsBelow(NumRows=rows_needed - table.Rows.Count)

    for row_idx, entry in enumerate(data, start=heading_rows + 1):
        for col_idx, value in enumerate(entry, start=1):
            table.Cell(row_idx, col_idx).Range.Text = str(value)


def transform(text: str) -> str:
    # ── Parse ────────────────────────────────────────────────────────────────
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

    # ── Write to active Word document ─────────────────────────────────────────
    try:
        app = _get_win32com_word()
        doc = app.ActiveDocument

        if doc is None:
            return "[word_from_csv] No Word document is currently open."

        _update_table(app, doc, BOOKMARK, data, HEADING_ROWS)

        return (
            f"[word_from_csv] OK — {len(data)} row(s) written to "
            f"bookmark '{BOOKMARK}' in '{doc.Name}'"
        )
    except Exception as exc:
        return f"[word_from_csv] Word error: {exc}"
