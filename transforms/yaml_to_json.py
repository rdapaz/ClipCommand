#!/usr/bin/env python3
"""
Convert YAML from the clipboard to pretty-printed JSON.
"""

import json
import yaml

def transform(text: str) -> str:
    try:
        data = yaml.safe_load(text.strip())
    except yaml.YAMLError as exc:
        return f"[yaml_to_json] YAML parse error: {exc}"

    try:
        return json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        return f"[yaml_to_json] JSON serialisation error: {exc}"