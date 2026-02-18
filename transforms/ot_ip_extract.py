#!/usr/bin/env python3
"""
Extract all IPv4 addresses from the clipboard text and return them sorted
and deduplicated, one per line. Handy when reviewing OT/ICS network
diagrams, firewall rules, or Nmap output to quickly gather IP lists.
"""
import re

_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def transform(text: str) -> str:
    ips = sorted(set(_IP.findall(text)))
    if not ips:
        return "[no IP addresses found]"
    return "\n".join(ips)
