#!/usr/bin/env python3
"""
Normalise a free-text asset description into a consistent uppercase slug
suitable for use as an IEC 62443 asset ID or zone/conduit label.

Example:
    "PLC - Boiler Feed Pump #3 (Unit 2)" → "PLC-BOILER-FEED-PUMP-3-UNIT-2"

Steps: Unicode normalise → ASCII-only → strip punctuation → collapse
whitespace/hyphens/underscores → uppercase.
"""
import re
import unicodedata


def transform(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.strip())
    text = text.encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.upper()
