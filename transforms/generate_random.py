"""
gen_test_yaml_3x100.py — generates a 3-column × 100-row YAML test dataset.

Ignores clipboard input entirely. Copy anything to trigger it.
Output is one YAML flow-sequence per line, ready for word_from_yaml_active.

Chain it before word_from_yaml_active to do a full end-to-end Word table test.
"""

import random

# NATO alphabet for variety
NATO = [
    "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf",
    "hotel", "india", "juliet", "kilo", "lima", "mike", "november",
    "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform",
    "victor", "whiskey", "xray", "yankee", "zulu",
]

COLS = 3
ROWS = 100


def transform(text: str) -> str:
    random.seed(42)  # fixed seed for reproducibility
    lines = []
    for i in range(1, ROWS + 1):
        cells = [f"{random.choice(NATO)}_{i:03d}" for _ in range(COLS)]
        lines.append(f"- [{', '.join(cells)}]")
    return "\n".join(lines)