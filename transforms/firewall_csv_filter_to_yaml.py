#!/usr/bin/env python3
"""
Filter and reshape a firewall policy CSV export for Word table insertion.

Reads tab-delimited CSV from the clipboard (as exported by Excel), discards
unwanted columns, filters rows by a regex applied to the WEL column, and
outputs a YAML list-of-lists ready for the word_from_yaml_active transform.

Actual tab-delimited column layout (0-based):
    0   Rule #                 ← discarded
    1   Name                   ← kept
    2   (internal)             ← discarded
    3   (internal)             ← discarded
    4   Source Address         ← kept
    5   Destination Address    ← kept
    6   (any)                  ← discarded
    7   (any)                  ← discarded
    8   Source Zone            ← kept
    9   Destination Zone       ← kept
    10  (any)                  ← discarded
    11  Application            ← kept
    12  Service                ← kept
    13  Action                 ← kept
    14  (none)                 ← discarded
    15  Log (may contain ,)    ← discarded
    16  Hit Count              ← discarded
    17  Last Hit               ← discarded
    18  First Hit              ← discarded
    19  Apps Seen              ← discarded
    20  Days No New Apps       ← discarded
    21  (unknown)              ← discarded
    22  (unknown)              ← discarded
    23  WEL                    ← kept, rows filtered by WEL_REGEX
"""

# ── Configuration ─────────────────────────────────────────────────────────────

DELIMITER = "\t"    # tab-delimited (Excel copy)

# Columns to keep — True = keep, False = discard (must have one entry per column)
COLUMN_MASK = [
    True,  #  0  Rule #
    True,   #  1  Name
    False,  #  2  internal
    False,  #  3  internal
    True,   #  4  Source Zone
    True,   #  5  Source Address
    False,  #  6  any
    False,  #  7  any
    True,   #  8  Destination Zone
    True,   #  9  Destination Address
    False,  # 10  any
    True,   # 11  Application
    True,   # 12  Service
    False,   # 13  Action
    False,  # 14  none
    False,  # 15  Log (contains commas — never try to CSV-parse this)
    False,  # 16  Hit Count
    False,  # 17  Last Hit
    False,  # 18  First Hit
    False,  # 19  Apps Seen
    False,  # 20  Days No New Apps
    False,  # 21  unknown
    False,  # 22  unknown
    True,   # 23  WEL
]

# Regex applied to WEL column (col 23). Rows that do NOT match are dropped.
# Examples:
#   r"^Temp"              — keep rules tagged Temp
#   r"^(Temp|Delete)"     — keep Temp or Delete
#   r"^PCN"               — keep PCN-prefixed tags
#   r".*"  or  ""         — keep everything
WEL_REGEX = r"^(Review|Consider|Explain)"

WEL_COL_INDEX  = 23    # 0-based index of WEL in the raw tab-delimited row
SKIP_HEADER    = True   # True = discard the first row (column headers)

# ─────────────────────────────────────────────────────────────────────────────

import csv
import io
import itertools
import re
import yaml


def transform(text: str) -> str:
    # ── Parse tab-delimited input ─────────────────────────────────────────────
    try:
        reader = csv.reader(io.StringIO(text.strip()), delimiter=DELIMITER)
        rows   = list(reader)
    except csv.Error as exc:
        return f"[firewall_csv_filter] CSV parse error: {exc}"

    if not rows:
        return "[firewall_csv_filter] No data found in clipboard."

    if SKIP_HEADER:
        rows = rows[1:]

    if not rows:
        return "[firewall_csv_filter] Only a header row — no data to process."

    # ── Compile WEL regex ─────────────────────────────────────────────────────
    try:
        wel_pattern = re.compile(WEL_REGEX, re.IGNORECASE) if WEL_REGEX else None
    except re.error as exc:
        return f"[firewall_csv_filter] Invalid WEL_REGEX: {exc}"

    # ── Filter and reshape ────────────────────────────────────────────────────
    output_rows = []
    skipped     = 0

    for row in rows:
        if len(row) <= WEL_COL_INDEX:
            skipped += 1
            continue

        wel_value = row[WEL_COL_INDEX]
        if wel_pattern and not wel_pattern.search(wel_value):
            skipped += 1
            continue

        kept = list(itertools.compress(row, COLUMN_MASK))
        output_rows.append(kept)

    if not output_rows:
        return (
            f"[firewall_csv_filter] No rows matched WEL_REGEX={WEL_REGEX!r}. "
            f"{skipped} row(s) dropped."
        )

    # ── Emit YAML ─────────────────────────────────────────────────────────────
    result = yaml.dump(
        output_rows,
        allow_unicode=True,
        default_flow_style=True,
        width=99999,
    )

    summary = (
        f"# firewall_csv_filter: {len(output_rows)} row(s) kept, "
        f"{skipped} dropped, WEL={WEL_REGEX!r}\n"
    )
    return summary + result