#!/usr/bin/env python3
"""
Produce a classic hex dump of the clipboard text (UTF-8 encoded).
Each row shows: offset  16 hex bytes  ASCII representation.
Useful for inspecting encoding issues, hidden characters, or binary data.
"""


def transform(text: str) -> str:
    data = text.encode("utf-8")
    lines = []
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hex_part = " ".join(f"{b:02x}" for b in chunk).ljust(47)
        asc_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:08x}  {hex_part}  |{asc_part}|")
    return "\n".join(lines)
