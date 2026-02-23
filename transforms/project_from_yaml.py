#!/usr/bin/env python3
"""
Parse a YAML Gantt structure from the clipboard and populate a Microsoft
Project (.mpp) file with the resulting task hierarchy.

Windows only — requires MSProject.Application via win32com.

YAML format
-----------
Top-level keys are phase/section names (summary tasks).
Nested mappings create child summary tasks (unlimited depth).
Leaf values are either:

    "duration|Resource1,Resource2"   → auto-scheduled task
        duration examples:  1d  4hrs  2wk  0d
        resources:          comma-separated names matching Project resource pool

    "start_date|finish_date"         → manually scheduled fixed-date task
        date examples:  2025-04-07|2025-06-30
                        2025-04-07|2025-04-21

Example:
    Project Alpha:
      Planning:
        Draft charter: "3d|Ric"
        Stakeholder review: "2025-05-01|2025-05-14"
      Execution:
        Build phase:
          Component A: "2wk|Alice,Bob"
          Component B: "1wk|Carol"

Configure MPP_PATH below to point at your .mpp file (local or SharePoint URL).
"""

# ── Configuration ─────────────────────────────────────────────────────────────

MPP_PATH = (
    r"https://woodsideenergy-my.sharepoint.com/personal/ricardo_dapaz_woodside_com/Documents/Documents/__Dev__/PyCharmProjects/ClipCommand/transforms/MySchedule.mpp"
)

# ─────────────────────────────────────────────────────────────────────────────

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from _project_utils import populate_project


def transform(text: str) -> str:
    if not text.strip():
        return "[yaml_to_project] Clipboard is empty."

    try:
        status = populate_project(text.strip(), MPP_PATH)
        return f"[yaml_to_project] Done — {status}"
    except ImportError as exc:
        return f"[yaml_to_project] Missing dependency: {exc}"
    except ValueError as exc:
        return f"[yaml_to_project] {exc}"
    except Exception as exc:
        return f"[yaml_to_project] Error: {exc}"
