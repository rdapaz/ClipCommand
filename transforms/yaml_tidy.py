#!/usr/bin/env python3
"""
Parse YAML from the clipboard and re-emit it cleanly formatted.
Normalises indentation, quoting style, and key ordering.
Safe for any valid YAML — uses yaml.safe_load so no arbitrary code execution.
"""

import yaml

def transform(text: str) -> str:
    try:
        data = yaml.safe_load(text.strip())
    except yaml.YAMLError as exc:
        return f"[yaml_tidy] YAML parse error: {exc}"

    return yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,   # block style throughout
        sort_keys=False,            # preserve original key order
        indent=2,
    )