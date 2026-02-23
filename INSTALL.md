# ClipCommand — Getting Started

Clipboard transform middleware. Sits in the background and passes your
clipboard through a Python script every time you copy something.

---

## First run

### macOS
1. Unzip `ClipCommand-mac.zip`
2. **Right-click** `ClipCommand/ClipCommand` → **Open**
   (required the first time to bypass Gatekeeper on unsigned apps)
3. Click Open in the security dialog

### Windows
1. Unzip `ClipCommand-windows.zip`
2. Double-click `ClipCommand\ClipCommand.exe`
   (Windows may show a SmartScreen warning — click "More info" → "Run anyway")

---

## Folder structure

```
ClipCommand/
├── ClipCommand          (or ClipCommand.exe on Windows)
├── transforms/          ← your transform scripts live here
│   ├── transforms.ini   ← chain definitions and config overrides
│   ├── _word_utils.py   ← Word table helper (used by word transforms)
│   └── *.py             ← individual transform scripts
```

**The `transforms/` folder must stay next to the executable.**
You can add, edit, or remove scripts in `transforms/` at any time —
just click **⟳ Rescan** in the UI to pick up changes.

---

## Optional features

### Word table transforms (macOS / Linux)
If you want to use `word_from_yaml_active` or similar transforms:
- Open the transform script in a text editor
- Set `DOC_PATH` to the full path of your saved `.docx` file
- Make sure the file is closed in Word before running the transform
- Reopen it in Word after to see the changes

### AI-powered transforms (e.g. `aidinsight_email_reply`)
Requires an Anthropic API key. Set it before launching ClipCommand:

**macOS / Linux:**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
./ClipCommand/ClipCommand
```

**Windows (Command Prompt):**
```cmd
set ANTHROPIC_API_KEY=sk-ant-...
ClipCommand\ClipCommand.exe
```

Or set it permanently via Windows → System → Environment Variables.

---

## Adding your own transforms

A transform is any `.py` file with a `transform` function:

```python
"""My transform description — shows as tooltip in the UI."""

def transform(text: str) -> str:
    return text.upper()
```

Drop it in the `transforms/` folder and click **⟳ Rescan**.

---

## Chaining transforms

Use the `[+]` button to add steps to a pipeline. Each step's output
becomes the next step's input.

Save a chain in `transforms/transforms.ini`:

```ini
[chain:my_chain]
description = Clean then convert
steps       = trim_whitespace, json_pretty
```

Load it via the **⛓ Load chain…** button.

---

## Activity log

Click **📋 Log** to browse the full activity history. All events are
stored in `clipcommand.db` next to the executable. Click any row to
see the complete message — useful for debugging transforms.

---

## Support

Raise issues or questions with whoever gave you this build.
