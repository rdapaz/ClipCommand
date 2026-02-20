#!/usr/bin/env python3
"""
Convert a Mermaid flowchart from the clipboard into a Visio diagram.

Paste any Mermaid graph/flowchart, run this transform, and Visio opens
with all nodes placed on an A4 landscape page.  Shapes are sized from a
single MASTER shape so you can resize the whole diagram by adjusting one
object.  Each shape gets connection points on all four sides.

Windows only — requires pywin32 (pip install pywin32).

Supported Mermaid syntax
------------------------
    graph TD / flowchart TD (or LR, TB, …)
    A[Label] --> B[Label]
    A -->|edge label| B          (edge labels are ignored for layout)
    A --> B & C & D              (multi-target)
    subgraph Name … end          (nodes clustered together per level)
    Styling (classDef, :::) is silently ignored.

Configuration (override via transforms.ini)
-------------------------------------------
    LAYOUT       - 'flow' (hierarchical BFS) or 'hilbert' (space-filling curve)
    H_POINTS     - connection points along top/bottom edges  (default 5)
    V_POINTS     - connection points along left/right edges  (default 3)

Example transforms.ini entry:
    [transform:mermaid_to_visio]
    LAYOUT   = hilbert
    H_POINTS = 7
    V_POINTS = 5

    [chain:mermaid_visio]
    description = Parse Mermaid from clipboard and open in Visio
    steps       = mermaid_to_visio
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from _mermaid_visio import (
    VisioGenerator,
    DEFAULT_HORIZONTAL_CONNECTIONS,
    DEFAULT_VERTICAL_CONNECTIONS,
)

# ── Configuration ──────────────────────────────────────────────────────────────

LAYOUT   = 'flow'                           # 'flow' | 'hilbert'
H_POINTS = DEFAULT_HORIZONTAL_CONNECTIONS   # connection points: top / bottom edges
V_POINTS = DEFAULT_VERTICAL_CONNECTIONS     # connection points: left / right edges

# ──────────────────────────────────────────────────────────────────────────────


def transform(text: str) -> str:
    if not text.strip():
        return "[mermaid_to_visio] Clipboard is empty."

    layout = LAYOUT.strip().lower()
    if layout not in ('flow', 'hilbert'):
        return (
            f"[mermaid_to_visio] Unknown LAYOUT '{LAYOUT}'. "
            "Use 'flow' or 'hilbert'."
        )

    try:
        generator = VisioGenerator(
            layout_engine=layout,
            horizontal_connections=int(H_POINTS),
            vertical_connections=int(V_POINTS),
        )
        shape_map = generator.generate(text.strip())

        n_shapes = len(shape_map)
        return (
            f"[mermaid_to_visio] Done — {n_shapes} shape(s) placed on A4 landscape "
            f"({layout} layout, {H_POINTS}×{V_POINTS} connection points). "
            "Visio is open and ready for manual wiring."
        )

    except ImportError as exc:
        return (
            f"[mermaid_to_visio] Missing dependency: {exc}\n"
            "Install with:  pip install pywin32"
        )
    except ValueError as exc:
        return f"[mermaid_to_visio] Mermaid parse error: {exc}"
    except Exception as exc:
        return f"[mermaid_to_visio] Error: {exc}"
