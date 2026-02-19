#!/usr/bin/env python3
"""
Convert clipboard text to ASCII art.

The clipboard content becomes the text to render. Each line is rendered
separately so you can pipe multi-line input and get stacked art back.

Configuration (override in transforms.ini):
    STYLE          - Art style. One of: block, shadow, thin, double,
                     small, banner, retro   (default: block)
    CHAR_SPACING   - Spaces between characters (default: 1)
    LINE_SEPARATOR - Blank lines between rendered lines (default: 1)
    MULTILINE      - True  = render each clipboard line separately
                     False = render entire clipboard as one string
                     (default: True)

Example transforms.ini overrides:
    [transform:ascii_art_transform]
    STYLE        = banner
    CHAR_SPACING = 2

    [chain:ascii_banner]
    description = Render clipboard as banner-style ASCII art
    steps       = ascii_art_transform
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from _ascii_art import render, STYLE_NAMES, STYLE_DESCRIPTIONS

# ── Configuration ─────────────────────────────────────────────────────────────

STYLE          = 'retro'   # block | shadow | thin | double | small | banner | retro
CHAR_SPACING   = 1         # spaces between characters
LINE_SEPARATOR = 1         # blank lines between rendered input lines
MULTILINE      = True      # render each line separately vs whole text as one

# ─────────────────────────────────────────────────────────────────────────────

def transform(text: str) -> str:
    if not text.strip():
        return "[ascii_art] Clipboard is empty."

    lines = text.splitlines() if MULTILINE else [text.replace('\n', ' ')]
    lines = [l for l in lines if l.strip()]

    if not lines:
        return "[ascii_art] No renderable text found."

    try:
        blocks = []
        for line in lines:
            rendered = render(line, style_name=STYLE, char_spacing=CHAR_SPACING)
            blocks.append('\n'.join(rendered))

        separator = '\n' * (LINE_SEPARATOR + 1)
        return separator.join(blocks)

    except ValueError as exc:
        available = ', '.join(STYLE_NAMES)
        return (
            f"[ascii_art] {exc}\n"
            f"Available styles: {available}\n\n"
            + '\n'.join(f"  {n:<10} {d}"
                        for n, d in STYLE_DESCRIPTIONS.items())
        )
