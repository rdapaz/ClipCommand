#!/usr/bin/env python3
"""
Convert JSON from the clipboard to cleanly formatted YAML.
"""

import json
import yaml

def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
    except json.JSONDecodeError as exc:
        return f"[json_to_yaml] JSON parse error: {exc}"

    return yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        indent=2,
    )