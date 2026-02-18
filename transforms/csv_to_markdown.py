#!/usr/bin/env python3
"""
Convert a CSV snippet (first row = headers) into a formatted Markdown table.
Column widths are auto-calculated. Useful for pasting tabular data into
README files, wikis, or Confluence pages.
"""
import csv
import io


def transform(text: str) -> str:
    reader = csv.reader(io.StringIO(text.strip()))
    rows = list(reader)
    if not rows:
        return text

    widths = [
        max(len(r[c]) for r in rows if c < len(r))
        for c in range(len(rows[0]))
    ]

    def fmt_row(r):
        return "| " + " | ".join(
            cell.ljust(widths[i]) for i, cell in enumerate(r)
        ) + " |"

    sep = "|-" + "-|-".join("-" * w for w in widths) + "-|"
    lines = [fmt_row(rows[0]), sep] + [fmt_row(r) for r in rows[1:]]
    return "\n".join(lines)
