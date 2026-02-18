#!/usr/bin/env python3
"""
Converts tabs to pipes
"""


def transform(text: str) -> str:
    arr = []
    lines = text.splitlines()
    for line in lines:
        arr.append(line.replace("\t", "|"))
    return "\n".join(arr)
