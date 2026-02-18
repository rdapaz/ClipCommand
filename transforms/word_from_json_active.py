#!/usr/bin/env python3
"""
Parse JSON from the clipboard (a list of lists) and insert the rows into a
bookmarked table in the currently active Word document.

The Word document must already be open. The JSON must be a list of lists:
    [
        ["Alpha", "Bravo",  "Charlie"],
        ["Delta", "Echo",   "Foxtrot"],
        ["Golf",  "Hotel",  "India"]
    ]

Configure BOOKMARK and HEADING_ROWS below, then drop this file into your
ClipCommand transforms/ folder and select it from the dropdown.
"""

# ── Configuration ─────────────────────────────────────────────────────────────

BOOKMARK     = "bk1"
HEADING_ROWS = 1

# ─────────────────────────────────────────────────────────────────────────────

import json
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
        data = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return f"[word_from_json] JSON parse error: {exc}"

    if not isinstance(data, list) or not all(isinstance(row, list) for row in data):
        return "[word_from_json] Input must be a JSON list of lists."

    if not data:
        return "[word_from_json] No data rows found — nothing to insert."

    # ── Write to active Word document ─────────────────────────────────────────
    try:
        app = _get_win32com_word()
        doc = app.ActiveDocument

        if doc is None:
            return "[word_from_json] No Word document is currently open."

        _update_table(app, doc, BOOKMARK, data, HEADING_ROWS)

        return (
            f"[word_from_json] OK — {len(data)} row(s) written to "
            f"bookmark '{BOOKMARK}' in '{doc.Name}'"
        )
    except Exception as exc:
        return f"[word_from_json] Word error: {exc}"
