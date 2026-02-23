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
- **Chain builder** — wire multiple transforms into a pipeline with `[+]` / `[−]`
  buttons; save chains to `transforms.ini` for instant recall
- **Docstring descriptions** — the script's module docstring shows as a tooltip
  and description strip so you always know what's active
- **Dry run mode** — preview transform output before it hits the clipboard;
  status dot turns orange as a reminder
- **SQLite activity log** — every event stored in `clipcommand.db` with full
  message content; browse via the **📋 Log** button, filter by session and tag,
  click any row to see the complete message
- **Native PySide6 UI** — dark-themed, colour-coded log, works correctly on
  macOS, Windows, and Linux
- 29+ ready-to-use example transforms included

---

## Screenshot

```
┌─────────────────────────────────────────────────────────────────┐
│ ● ClipCommand  [polling every 0.5s]    ⟳ Reload  ⏸ Pause 📋 Log│
├─────────────────────────────────────────────────────────────────┤
│ Transform: [Json Pretty          ▾]  ⟳ Rescan   ⛓ Load chain…  │
│ Pretty-print / minify JSON                                       │
├─────────────────────────────────────────────────────────────────┤
│ Transforms: 3  |  Errors: 0  |  Chain: json_pretty              │
├─────────────────────────────────────────────────────────────────┤
│ [14:22:01] Scanned './transforms': 29 OK                        │
│ [14:22:01] Active transform: Json Pretty                        │
│ [14:22:04] ▶ [Json Pretty] via clipboard change                 │
│ [14:22:04]   In:  '{"name":"Ric","role":"OT engineer"}'         │
│ [14:22:04]   Out: '{\n  "name": "Ric",\n  "role": …'           │
│ [14:22:04]   ✓ 38 chars written to clipboard                    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Requirements

- Python 3.10+
- `PySide6` (UI framework)
- `pyperclip` (clipboard access)
- `pyyaml` (YAML transform support)
- `keyboard` *(optional — hotkey mode only)*
- `python-docx` *(optional — Word table transforms on macOS / Linux)*

---

## Installation

```bash
git clone https://github.com/your-username/clipcommand.git
cd clipcommand

# Create and activate a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
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

## Chaining transforms

Build a multi-step pipeline using the `[+]` and `[−]` buttons in the UI. Each
step feeds its output as the next step's input. The stats bar shows the full
chain: `trim_whitespace → csv_to_markdown → word_from_yaml_active`.

Save a chain in `transforms/transforms.ini` and load it instantly via the
**⛓ Load chain…** button:

```ini
[chain:firewall_review]
description = Extract IPs, sort, insert into Word
steps       = ot_ip_extract, line_sort, word_from_yaml_active
```

---

## Per-transform configuration

Override module-level constants (like `BOOKMARK` or `HEADING_ROWS`) without
editing the script itself:

```ini
[transform:word_from_yaml_active]
bookmark     = bk2
heading_rows = 1
```

Values are auto-coerced to `int` or `float` where possible.

---

## Dry run mode

Click **🔍 Dry Run** to send the final pipeline output to a preview pane
instead of the clipboard. The status dot turns orange as a reminder.
The preview pane has **Copy to clipboard** and **Clear** buttons.

---

## Activity log

All events are stored in `clipcommand.db` (SQLite, project root). Click
**📋 Log** to open the log browser:

- Filter by session or tag (`err`, `warn`, `ok`, `info`, `chain`)
- Click any row to see the **full message** in the detail pane — no truncation
- Auto-refreshes every 2 seconds while open
- Entries older than 30 days are purged automatically

The log browser is particularly useful for debugging transform errors where
the main window only shows a truncated preview.

---

## Word table transforms (`_word_utils.py`)

`_word_utils.py` provides a cross-platform `update_table()` helper for writing
data into a bookmarked Word table. Used by `word_from_yaml_active.py` and
similar transforms.

### Platform behaviour

| Platform | Method | Requires |
|---|---|---|
| Windows | win32com COM automation | Word open with active document |
| macOS | python-docx (file on disk) | `DOC_PATH` set; file saved and closed in Word |
| Linux | python-docx (file on disk) | `DOC_PATH` set; file saved and closed in Word |

### macOS / Linux workflow

1. Save your document in Word (File → Save)
2. Close it in Word
3. Set `DOC_PATH` in the transform config to the full `.docx` path
4. Run the transform — it writes the data and saves the file
5. Reopen the file in Word to see the changes

> **Note:** JXA and AppleScript automation of Word table cells is unreliable
> on current versions of Word for Mac — cell write operations are silently
> ignored regardless of API used. python-docx on a saved file is the only
> reliable approach on non-Windows platforms.

### transforms.ini example

```ini
[transform:word_from_yaml_active]
bookmark     = bk1
heading_rows = 1
doc_path     = /Users/yourname/Documents/MyReport.docx
```

---

## Project structure

```
clipcommand/
├── clipcommand.py        # Main application (PySide6)
├── db_logger.py          # SQLite logging backend
├── log_browser.py        # Log browser dialog
├── clipcommand.db        # SQLite activity log (auto-created, gitignored)
├── transforms/           # Drop your .py transform scripts here
│   ├── transforms.ini    # Chain definitions and per-transform config overrides
│   ├── _word_utils.py    # Cross-platform Word table helper
│   ├── word_from_yaml_active.py
│   ├── json_pretty.py
│   ├── upper.py
│   └── ...
├── requirements.txt
└── README.md
```

---

## Platform notes

### Windows

Works out of the box. For hotkey mode, run the terminal as Administrator or the
`keyboard` package may not capture global keypresses.

For Word table transforms, win32com is used automatically — no configuration
needed beyond having a document open with the correct bookmark.

### macOS

`pyperclip` uses `pbcopy`/`pbpaste` which are built in. Hotkey mode requires
Accessibility permissions for the terminal app
(*System Settings → Privacy & Security → Accessibility*).

For Word table transforms, set `DOC_PATH` in `transforms.ini` — see above.

### Linux

```bash
# PySide6
pip install PySide6

# pyperclip needs xclip or xsel (X11) or wl-clipboard (Wayland)
sudo apt install xclip
# or
sudo apt install wl-clipboard

# keyboard (hotkey mode) needs uinput access
sudo usermod -aG input $USER   # then log out and back in
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