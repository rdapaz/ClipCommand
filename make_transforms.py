#!/usr/bin/env python3
"""
make_transforms.py
Generates the ./transforms/ folder with ready-to-use ClipCommand transform scripts.
Run once to get started:  python make_transforms.py

Each generated script:
  - Has a #!/usr/bin/env python3 shebang
  - Has a module-level docstring (shown in the ClipCommand UI description strip
    and tooltip)
  - Defines transform(text: str) -> str
"""

# ════════════════════════════════════════════════════════════════════════════
# trim_whitespace.py
# ════════════════════════════════════════════════════════════════════════════
TRIM_WHITESPACE = '''\
#!/usr/bin/env python3
"""
Strip leading/trailing whitespace, remove trailing spaces from every line,
and collapse runs of 3+ blank lines down to 2. Useful for cleaning up
copied code, log output, or document text before pasting.
"""
import re


def transform(text: str) -> str:
    text = text.strip()
    text = re.sub(r"\\n{3,}", "\\n\\n", text)
    text = re.sub(r"[ \\t]+$", "", text, flags=re.MULTILINE)
    return text
'''

# ════════════════════════════════════════════════════════════════════════════
# upper.py
# ════════════════════════════════════════════════════════════════════════════
UPPER = '''\
#!/usr/bin/env python3
"""
Convert all text to UPPERCASE.
"""


def transform(text: str) -> str:
    return text.upper()
'''

# ════════════════════════════════════════════════════════════════════════════
# lower.py
# ════════════════════════════════════════════════════════════════════════════
LOWER = '''\
#!/usr/bin/env python3
"""
Convert all text to lowercase.
"""


def transform(text: str) -> str:
    return text.lower()
'''

# ════════════════════════════════════════════════════════════════════════════
# title_case.py
# ════════════════════════════════════════════════════════════════════════════
TITLE_CASE = '''\
#!/usr/bin/env python3
"""
Convert text to Title Case — capitalise the first letter of every word.
Useful for fixing headings or names copied from ALL-CAPS sources.
"""


def transform(text: str) -> str:
    return text.title()
'''

# ════════════════════════════════════════════════════════════════════════════
# base64_encode.py
# ════════════════════════════════════════════════════════════════════════════
BASE64_ENCODE = '''\
#!/usr/bin/env python3
"""
Base64-encode the clipboard text (UTF-8). Useful for embedding binary
data in config files, emails, or API payloads.
"""
import base64


def transform(text: str) -> str:
    return base64.b64encode(text.encode()).decode()
'''

# ════════════════════════════════════════════════════════════════════════════
# base64_decode.py
# ════════════════════════════════════════════════════════════════════════════
BASE64_DECODE = '''\
#!/usr/bin/env python3
"""
Base64-decode the clipboard text back to a UTF-8 string.
Returns an error message (and the original text) if decoding fails.
"""
import base64


def transform(text: str) -> str:
    try:
        return base64.b64decode(text.strip().encode()).decode()
    except Exception as e:
        return f"[base64 decode error: {e}]\\n{text}"
'''

# ════════════════════════════════════════════════════════════════════════════
# url_encode.py
# ════════════════════════════════════════════════════════════════════════════
URL_ENCODE = '''\
#!/usr/bin/env python3
"""
Percent-encode (URL-encode) the clipboard text so it is safe to embed in
a URL query string. All characters except unreserved ones are encoded.
"""
from urllib.parse import quote


def transform(text: str) -> str:
    return quote(text, safe="")
'''

# ════════════════════════════════════════════════════════════════════════════
# url_decode.py
# ════════════════════════════════════════════════════════════════════════════
URL_DECODE = '''\
#!/usr/bin/env python3
"""
Decode a percent-encoded (URL-encoded) string back to plain text.
Useful when inspecting encoded URLs or query parameters.
"""
from urllib.parse import unquote


def transform(text: str) -> str:
    return unquote(text)
'''

# ════════════════════════════════════════════════════════════════════════════
# json_pretty.py
# ════════════════════════════════════════════════════════════════════════════
JSON_PRETTY = '''\
#!/usr/bin/env python3
"""
Pretty-print JSON with 2-space indentation and unicode preserved.
Returns an error message (and the original text) if the input is not
valid JSON.
"""
import json


def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
        return json.dumps(data, indent=2, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"[JSON error: {e}]\\n{text}"
'''

# ════════════════════════════════════════════════════════════════════════════
# json_minify.py
# ════════════════════════════════════════════════════════════════════════════
JSON_MINIFY = '''\
#!/usr/bin/env python3
"""
Minify JSON by removing all unnecessary whitespace. Useful for compacting
JSON before embedding in config files or API calls.
Returns an error message (and the original text) if the input is not
valid JSON.
"""
import json


def transform(text: str) -> str:
    try:
        data = json.loads(text.strip())
        return json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"[JSON error: {e}]\\n{text}"
'''

# ════════════════════════════════════════════════════════════════════════════
# strip_ansi.py
# ════════════════════════════════════════════════════════════════════════════
STRIP_ANSI = '''\
#!/usr/bin/env python3
"""
Remove ANSI escape / colour codes from terminal output so the plain text
can be pasted into documents, tickets, or emails without garbage characters.
"""
import re

_ANSI = re.compile(r"\\x1b\\[[0-9;]*[mGKHF]")


def transform(text: str) -> str:
    return _ANSI.sub("", text)
'''

# ════════════════════════════════════════════════════════════════════════════
# csv_to_markdown.py
# ════════════════════════════════════════════════════════════════════════════
CSV_TO_MARKDOWN = '''\
#!/usr/bin/env python3
"""
Convert a CSV snippet (first row = headers) into a formatted Markdown table.
Column widths are auto-calculated. Useful for pasting tabular data into
README files, wikis, or Confluence pages.
"""
import csv
import io


def transform(text: str) -> str:
    reader = csv.reader(io.StringIO(text.strip()))
    rows = list(reader)
    if not rows:
        return text

    widths = [
        max(len(r[c]) for r in rows if c < len(r))
        for c in range(len(rows[0]))
    ]

    def fmt_row(r):
        return "| " + " | ".join(
            cell.ljust(widths[i]) for i, cell in enumerate(r)
        ) + " |"

    sep = "|-" + "-|-".join("-" * w for w in widths) + "-|"
    lines = [fmt_row(rows[0]), sep] + [fmt_row(r) for r in rows[1:]]
    return "\\n".join(lines)
'''

# ════════════════════════════════════════════════════════════════════════════
# line_sort.py
# ════════════════════════════════════════════════════════════════════════════
LINE_SORT = '''\
#!/usr/bin/env python3
"""
Sort lines alphabetically (case-insensitive) and remove duplicates.
Useful for tidying lists of hostnames, IPs, tags, or import statements.
"""


def transform(text: str) -> str:
    lines = text.splitlines()
    return "\\n".join(sorted(set(lines), key=str.casefold))
'''

# ════════════════════════════════════════════════════════════════════════════
# hex_dump.py
# ════════════════════════════════════════════════════════════════════════════
HEX_DUMP = '''\
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
    return "\\n".join(lines)
'''

# ════════════════════════════════════════════════════════════════════════════
# ot_ip_extract.py
# ════════════════════════════════════════════════════════════════════════════
OT_IP_EXTRACT = '''\
#!/usr/bin/env python3
"""
Extract all IPv4 addresses from the clipboard text and return them sorted
and deduplicated, one per line. Handy when reviewing OT/ICS network
diagrams, firewall rules, or Nmap output to quickly gather IP lists.
"""
import re

_IP = re.compile(r"\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b")


def transform(text: str) -> str:
    ips = sorted(set(_IP.findall(text)))
    if not ips:
        return "[no IP addresses found]"
    return "\\n".join(ips)
'''

# ════════════════════════════════════════════════════════════════════════════
# iec62443_slugify.py
# ════════════════════════════════════════════════════════════════════════════
IEC62443_SLUGIFY = '''\
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
    text = re.sub(r"[^\\w\\s-]", "", text)
    text = re.sub(r"[\\s_-]+", "-", text)
    return text.upper()
'''


# ════════════════════════════════════════════════════════════════════════════
# Writer — run this file directly to write all scripts to ./transforms/
# ════════════════════════════════════════════════════════════════════════════

FILES = {
    "trim_whitespace.py":  TRIM_WHITESPACE,
    "upper.py":            UPPER,
    "lower.py":            LOWER,
    "title_case.py":       TITLE_CASE,
    "base64_encode.py":    BASE64_ENCODE,
    "base64_decode.py":    BASE64_DECODE,
    "url_encode.py":       URL_ENCODE,
    "url_decode.py":       URL_DECODE,
    "json_pretty.py":      JSON_PRETTY,
    "json_minify.py":      JSON_MINIFY,
    "strip_ansi.py":       STRIP_ANSI,
    "csv_to_markdown.py":  CSV_TO_MARKDOWN,
    "line_sort.py":        LINE_SORT,
    "hex_dump.py":         HEX_DUMP,
    "ot_ip_extract.py":    OT_IP_EXTRACT,
    "iec62443_slugify.py": IEC62443_SLUGIFY,
}

if __name__ == "__main__":
    from pathlib import Path
    out = Path(__file__).parent / "transforms"
    out.mkdir(exist_ok=True)
    for name, code in FILES.items():
        p = out / name
        p.write_text(code, encoding="utf-8")
        print(f"  wrote {p}")
    print(f"\nDone. {len(FILES)} transform scripts written to {out}/")
