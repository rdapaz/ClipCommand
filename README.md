# ClipCommand

> Clipboard transform middleware for Python — inspired by the Perl Monks
> [`clipcommand.pl`](https://www.perlmonks.org/?node_id=494942).

ClipCommand sits quietly in the background and passes your clipboard through a
Python script of your choice every time you copy something. Switch transforms
on the fly from a dropdown, drop new scripts into a folder and rescan — no
restart required.

---

## Features

- **Auto-polling** — detects clipboard changes and transforms them instantly
- **Hotkey mode** — trigger on demand instead of on every copy
- **Folder-based transform picker** — all `.py` files in `./transforms/` appear
  in a dropdown; select and switch without restarting
- **Live rescan** — drop a new script into the folder and hit *Rescan* to pick
  it up immediately
- **Hot-reload** — edit the active script and reload it without changing selection
- **Docstring descriptions** — the script's module docstring shows as a tooltip
  and description strip so you always know what's active
- **Dark-themed Tkinter UI** with colour-coded activity log, pause/resume, and
  a stats bar
- 16 ready-to-use example transforms included

---

## Screenshot

```
┌─────────────────────────────────────────────────────────────┐
│ ● ClipCommand  [polling every 0.5s]       ⟳ Reload  ⏸ Pause│
├─────────────────────────────────────────────────────────────┤
│ Transform: [Json Pretty          ▾]  ⟳ Rescan folder        │
│ Pretty-print / minify JSON                                   │
├─────────────────────────────────────────────────────────────┤
│ Transforms: 3  |  Errors: 0  |  Active: json_pretty         │
├─────────────────────────────────────────────────────────────┤
│ [14:22:01] Scanned './transforms': 16 OK                    │
│ [14:22:01] Active transform: Json Pretty                    │
│ [14:22:04] ▶ [Json Pretty] via clipboard change             │
│ [14:22:04]   In:  '{"name":"Ric","role":"OT engineer"}'     │
│ [14:22:04]   Out: '{\n  "name": "Ric",\n  "role": …'       │
│ [14:22:04]   ✓ 38 chars written to clipboard                │
└─────────────────────────────────────────────────────────────┘
```

---

## Requirements

- Python 3.10+
- `pyperclip` (clipboard access)
- `tkinter` (usually bundled with Python; on Linux: `sudo apt install python3-tk`)
- `keyboard` *(optional — hotkey mode only)*

---

## Installation

```bash
git clone https://github.com/your-username/clipcommand.git
cd clipcommand

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

# Generate the example transforms folder
python make_transforms.py
```

---

## Usage

```bash
# Basic — auto-polls clipboard, uses ./transforms/ folder
python clipcommand.py

# Pre-select a specific transform on launch
python clipcommand.py --script transforms/json_pretty.py

# Point at a different transforms folder
python clipcommand.py --transforms ~/my-transforms

# Hotkey mode — only fires when you press the combo (requires: pip install keyboard)
python clipcommand.py --hotkey ctrl+shift+v

# Faster polling (default is 0.5 s)
python clipcommand.py --poll 0.2
```

### CLI flags

| Flag | Default | Description |
|---|---|---|
| `--script`, `-s` | *(first found)* | Pre-select a transform script on launch |
| `--transforms`, `-t` | `./transforms` | Folder to scan for transform scripts |
| `--hotkey`, `-k` | *(none)* | Hotkey to trigger manually (e.g. `ctrl+shift+v`) |
| `--poll`, `-p` | `0.5` | Clipboard poll interval in seconds (polling mode only) |

---

## Writing a transform script

A transform script is any `.py` file that defines one function:

```python
def transform(text: str) -> str:
    ...
```

ClipCommand calls `transform()` with the current clipboard text and writes the
return value back to the clipboard.

Add an optional **module-level docstring** and it will appear as the description
in the UI:

```python
"""Reverse every line in the clipboard."""

def transform(text: str) -> str:
    return "\n".join(line[::-1] for line in text.splitlines())
```

Place the file in `./transforms/` (or your custom folder) and click **Rescan**
— it will appear in the dropdown immediately.

### Error handling

If your transform raises an exception the error is shown in the log and the
clipboard is left unchanged. For user-facing error messages, return a string:

```python
import json

def transform(text: str) -> str:
    try:
        return json.dumps(json.loads(text), indent=2)
    except json.JSONDecodeError as e:
        return f"[JSON error: {e}]\n{text}"
```

---

## Included transforms

Run `python make_transforms.py` to generate these into `./transforms/`:

| Script | What it does |
|---|---|
| `trim_whitespace.py` | Strip trailing spaces, normalise blank lines |
| `upper.py` | Convert to UPPERCASE |
| `lower.py` | Convert to lowercase |
| `title_case.py` | Convert To Title Case |
| `base64_encode.py` | Base64-encode the text |
| `base64_decode.py` | Base64-decode the text |
| `url_encode.py` | Percent-encode for URLs |
| `url_decode.py` | Decode percent-encoded URLs |
| `json_pretty.py` | Pretty-print JSON (2-space indent) |
| `json_minify.py` | Minify JSON |
| `strip_ansi.py` | Remove ANSI colour codes from terminal output |
| `csv_to_markdown.py` | Convert a CSV snippet to a Markdown table |
| `line_sort.py` | Sort lines alphabetically, deduplicate |
| `hex_dump.py` | Produce a hex dump of the clipboard text |
| `ot_ip_extract.py` | Extract all IP addresses (one per line) |
| `iec62443_slugify.py` | Normalise asset descriptions to an IEC 62443-style slug |

---

## Platform notes

### Windows
Works out of the box. For hotkey mode, run the terminal as Administrator or the
`keyboard` package may not capture global keypresses.

### macOS
`pyperclip` uses `pbcopy`/`pbpaste` which are built in. Hotkey mode requires
Accessibility permissions for the terminal app
(*System Settings → Privacy & Security → Accessibility*).

### Linux
```bash
# tkinter
sudo apt install python3-tk   # Debian/Ubuntu
sudo dnf install python3-tkinter  # Fedora

# pyperclip needs xclip or xsel (X11) or wl-clipboard (Wayland)
sudo apt install xclip
# or
sudo apt install wl-clipboard

# keyboard (hotkey mode) needs uinput access
sudo usermod -aG input $USER   # then log out and back in
```

---

## Project structure

```
clipcommand/
├── clipcommand.py        # Main application
├── make_transforms.py    # Generates the example transforms/ folder
├── transforms/           # Drop your .py transform scripts here
│   ├── json_pretty.py
│   ├── upper.py
│   └── ...
├── requirements.txt
├── CHANGELOG.md
├── CONTRIBUTING.md
├── LICENSE
└── README.md
```

---

## Acknowledgements

Inspired by the Perl Monks community and the original
[`clipcommand.pl`](https://www.perlmonks.org/?node_id=494942) — the idea that
your clipboard can be a programmable pipe is still as useful today as it was
then.

---

## License

[MIT](LICENSE)
