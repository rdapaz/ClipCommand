#!/usr/bin/env python3
"""
clipcommand.py - Clipboard transform middleware inspired by the Perl Monks clipcommand.pl
Watches the clipboard for changes, passes content through a user-supplied transform script,
and writes the result back to the clipboard.

Usage:
    python clipcommand.py [--script myscript.py] [--transforms ./transforms]
                          [--hotkey ctrl+shift+v] [--poll 0.5]

Transform script API:
    Your script must define a function:
        def transform(text: str) -> str:
            ...
    An optional module-level docstring is shown as the description in the UI.
    Scripts are loaded from ./transforms/ by default and selected via dropdown.
"""

import argparse
import importlib.util
import sys
import time
import threading
import traceback
from datetime import datetime
from pathlib import Path

try:
    import pyperclip
except ImportError:
    print("Missing dependency: pip install pyperclip")
    sys.exit(1)

try:
    import tkinter as tk
    from tkinter import scrolledtext, ttk
except ImportError:
    print("tkinter not available - install python3-tk")
    sys.exit(1)

# Optional hotkey support
try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False


# ─── Transform script loader ─────────────────────────────────────────────────

def load_transform(script_path: str):
    """
    Dynamically load a transform script.
    Returns (transform_fn, resolved_path, description_str).
    """
    path = Path(script_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    spec = importlib.util.spec_from_file_location("transform_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "transform"):
        raise AttributeError("Script must define a 'transform(text) -> str' function")

    # Pull docstring from the module or from the transform function
    description = (
        (module.__doc__ or "").strip()
        or (module.transform.__doc__ or "").strip()
        or "No description."
    )
    # First non-empty line for compact display
    short_desc = next((ln.strip() for ln in description.splitlines() if ln.strip()), description)

    return module.transform, str(path), short_desc


# ─── Transform folder scanner ─────────────────────────────────────────────────

def scan_transforms(folder: str) -> list:
    """
    Scan a folder for .py files that contain a transform() function.
    Returns a sorted list of dicts: {name, label, path, description, fn}
    """
    results = []
    p = Path(folder)
    if not p.is_dir():
        return results

    for pyfile in sorted(p.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        try:
            fn, path, desc = load_transform(str(pyfile))
            results.append({
                "name":        pyfile.stem,
                "label":       pyfile.stem.replace("_", " ").title(),
                "path":        path,
                "description": desc,
                "fn":          fn,
            })
        except Exception as exc:
            # Broken scripts appear in the list so the user can see the error
            results.append({
                "name":        pyfile.stem,
                "label":       f"⚠ {pyfile.stem}",
                "path":        str(pyfile),
                "description": f"Load error: {exc}",
                "fn":          None,
            })

    return results


# ─── Tooltip helper ──────────────────────────────────────────────────────────

class Tooltip:
    """Simple hover tooltip for any widget."""

    def __init__(self, widget, text_fn):
        self._widget = widget
        self._text_fn = text_fn   # callable → text can update dynamically
        self._win = None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _show(self, _event=None):
        text = self._text_fn()
        if not text:
            return
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._win = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tk.Label(
            tw, text=text, justify=tk.LEFT,
            background="#282a36", foreground="#f8f8f2",
            relief=tk.FLAT, font=("Courier", 9),
            wraplength=440, padx=6, pady=4,
        ).pack()

    def _hide(self, _event=None):
        if self._win:
            self._win.destroy()
            self._win = None


# ─── GUI ─────────────────────────────────────────────────────────────────────

class ClipCommandApp:
    MAX_LOG_LINES = 300

    def __init__(self, root: tk.Tk, transforms_folder: str,
                 initial_script, poll_interval: float, hotkey):

        self.root              = root
        self.transforms_folder = transforms_folder
        self.poll_interval     = poll_interval
        self.hotkey            = hotkey

        self.transform_fn      = None
        self.script_path       = ""
        self.running           = False
        self.last_clip         = ""
        self.transform_count   = 0
        self.error_count       = 0

        # Registry: list of dicts from scan_transforms
        self._registry         = []
        self._selected_label   = tk.StringVar()

        self._build_ui()
        self._refresh_transforms(preselect=initial_script)
        self._register_hotkey()
        self._start_polling()

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.title("ClipCommand")
        self.root.geometry("600x460")
        self.root.minsize(480, 340)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(bg="#1e2127")

        # ── Header ──────────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg="#1e2127", padx=8, pady=6)
        header.pack(fill=tk.X)

        self.status_dot = tk.Label(
            header, text="●", fg="#ff5555", bg="#1e2127", font=("Courier", 14)
        )
        self.status_dot.pack(side=tk.LEFT)

        tk.Label(
            header, text="ClipCommand", fg="#f8f8f2", bg="#1e2127",
            font=("Helvetica", 12, "bold")
        ).pack(side=tk.LEFT, padx=6)

        self.mode_label = tk.Label(
            header, text="[starting…]", fg="#8be9fd", bg="#1e2127",
            font=("Helvetica", 10)
        )
        self.mode_label.pack(side=tk.LEFT)

        # Right-side buttons (pack right-to-left)
        self.toggle_btn = tk.Button(
            header, text="⏸ Pause", command=self._toggle,
            bg="#44475a", fg="#f8f8f2", relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=6
        )
        self.toggle_btn.pack(side=tk.RIGHT, padx=3)

        tk.Button(
            header, text="⟳ Reload", command=self._reload_current,
            bg="#44475a", fg="#f8f8f2", relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=6
        ).pack(side=tk.RIGHT, padx=3)

        # ── Transform selector ───────────────────────────────────────────────
        sel_bar = tk.Frame(self.root, bg="#282a36", padx=8, pady=6)
        sel_bar.pack(fill=tk.X)

        tk.Label(
            sel_bar, text="Transform:", fg="#6272a4", bg="#282a36",
            font=("Courier", 9)
        ).pack(side=tk.LEFT)

        # Style the combobox to match the dark theme
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.TCombobox",
            fieldbackground="#44475a", background="#44475a",
            foreground="#f8f8f2", selectbackground="#6272a4",
            selectforeground="#f8f8f2", arrowcolor="#f8f8f2",
        )
        style.map("Dark.TCombobox", fieldbackground=[("readonly", "#44475a")])

        self.combo = ttk.Combobox(
            sel_bar, textvariable=self._selected_label,
            state="readonly", style="Dark.TCombobox",
            font=("Courier", 9), width=32
        )
        self.combo.pack(side=tk.LEFT, padx=6)
        self.combo.bind("<<ComboboxSelected>>", self._on_combo_select)

        # Hovering over the combobox shows the script's docstring
        Tooltip(self.combo, self._current_description)

        tk.Button(
            sel_bar, text="⟳ Rescan folder", command=lambda: self._refresh_transforms(),
            bg="#44475a", fg="#f8f8f2", relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=4
        ).pack(side=tk.LEFT, padx=4)

        # ── Description strip ────────────────────────────────────────────────
        self.desc_label = tk.Label(
            self.root, text="", fg="#bd93f9", bg="#282a36",
            font=("Courier", 8), anchor="w", padx=10, pady=3,
            wraplength=580, justify=tk.LEFT
        )
        self.desc_label.pack(fill=tk.X)

        # ── Stats bar ────────────────────────────────────────────────────────
        stats_bar = tk.Frame(self.root, bg="#282a36", padx=8, pady=2)
        stats_bar.pack(fill=tk.X)
        self.stats_label = tk.Label(
            stats_bar,
            text="Transforms: 0  |  Errors: 0  |  Active: none",
            fg="#6272a4", bg="#282a36", font=("Courier", 9)
        )
        self.stats_label.pack(side=tk.LEFT)

        # ── Log ──────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg="#21222c")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.log = scrolledtext.ScrolledText(
            log_frame, bg="#21222c", fg="#f8f8f2",
            font=("Courier", 9), state=tk.DISABLED,
            wrap=tk.WORD, relief=tk.FLAT,
            insertbackground="#f8f8f2"
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        self.log.tag_config("ts",      foreground="#6272a4")
        self.log.tag_config("ok",      foreground="#50fa7b")
        self.log.tag_config("err",     foreground="#ff5555")
        self.log.tag_config("info",    foreground="#8be9fd")
        self.log.tag_config("warn",    foreground="#ffb86c")
        self.log.tag_config("preview", foreground="#bd93f9")

        # ── Status bar ───────────────────────────────────────────────────────
        self.statusbar = tk.Label(
            self.root, text="Ready", anchor=tk.W,
            bg="#1e2127", fg="#6272a4", font=("Courier", 9), padx=6
        )
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    # ── Transform registry ───────────────────────────────────────────────────

    def _refresh_transforms(self, preselect=None):
        """Rescan the transforms folder and repopulate the combobox."""
        prev_label = self._selected_label.get()

        self._registry = scan_transforms(self.transforms_folder)
        labels = [t["label"] for t in self._registry]
        self.combo["values"] = labels

        if not self._registry:
            self._log(f"No transform scripts found in '{self.transforms_folder}'", "warn")
            self._set_status("No transforms found — add .py files to ./transforms/")
            self.transform_fn = None
            self._update_stats()
            return

        n = len(self._registry)
        good = sum(1 for t in self._registry if t["fn"] is not None)
        bad  = n - good
        msg  = f"Scanned '{self.transforms_folder}': {good} OK"
        if bad:
            msg += f", {bad} failed to load"
        self._log(msg, "info" if not bad else "warn")

        # Determine what to select:
        #   1. A --script path supplied on the CLI (first call only)
        #   2. Whatever was selected before the rescan
        #   3. First item
        target = None

        if preselect:
            p = Path(preselect).resolve()
            for t in self._registry:
                if Path(t["path"]).resolve() == p:
                    target = t["label"]
                    break

        if not target and prev_label in labels:
            target = prev_label

        if not target:
            target = labels[0]

        self._selected_label.set(target)
        self._activate_selected()

    def _activate_selected(self):
        """Load the entry currently shown in the combobox."""
        label = self._selected_label.get()
        entry = next((t for t in self._registry if t["label"] == label), None)
        if entry is None:
            return

        self.script_path = entry["path"]

        if entry["fn"] is None:
            self._log(f"Cannot activate '{label}': {entry['description']}", "err")
            self.transform_fn = None
            self.desc_label.config(text=f"⚠ {entry['description']}")
            self._update_stats()
            return

        self.transform_fn = entry["fn"]
        self.desc_label.config(text=entry["description"])
        self._log(f"Active transform: {label}", "ok")
        self._log(f"  {entry['path']}", "info")
        self._update_stats()
        self._set_status(f"Transform: {label}")

        # Re-seed so switching won't immediately fire on stale clipboard content
        try:
            self.last_clip = pyperclip.paste()
        except Exception:
            pass

    def _current_description(self):
        label = self._selected_label.get()
        entry = next((t for t in self._registry if t["label"] == label), None)
        return entry["description"] if entry else ""

    def _on_combo_select(self, _event=None):
        self._activate_selected()

    def _reload_current(self):
        """Re-read the currently active script from disk without rescanning the folder."""
        if not self.script_path:
            self._log("No script loaded to reload", "warn")
            return
        try:
            fn, path, desc = load_transform(self.script_path)
            self.transform_fn = fn

            # Update registry entry in place
            label = self._selected_label.get()
            for t in self._registry:
                if t["label"] == label:
                    t["fn"]          = fn
                    t["description"] = desc
                    break

            self.desc_label.config(text=desc)
            self._log(f"Reloaded: {path}", "ok")
            self._set_status("Script reloaded OK")
        except Exception as exc:
            self._log(f"Reload failed: {exc}", "err")

    # ── Logging ──────────────────────────────────────────────────────────────

    def _log(self, message: str, tag: str = "info"):
        def _write():
            self.log.config(state=tk.NORMAL)
            ts = datetime.now().strftime("%H:%M:%S")
            self.log.insert(tk.END, f"[{ts}] ", "ts")
            self.log.insert(tk.END, f"{message}\n", tag)

            line_count = int(self.log.index("end-1c").split(".")[0])
            if line_count > self.MAX_LOG_LINES:
                self.log.delete("1.0", f"{line_count - self.MAX_LOG_LINES}.0")

            self.log.config(state=tk.DISABLED)
            self.log.see(tk.END)

        self.root.after(0, _write)

    def _update_stats(self):
        name = Path(self.script_path).stem if self.script_path else "none"
        text = (
            f"Transforms: {self.transform_count}  |  "
            f"Errors: {self.error_count}  |  "
            f"Active: {name}"
        )
        self.root.after(0, lambda: self.stats_label.config(text=text))

    def _set_status(self, text: str):
        self.root.after(0, lambda: self.statusbar.config(text=text))

    # ── Transform execution ──────────────────────────────────────────────────

    def _run_transform(self, clip_text: str, source: str = "clipboard"):
        if self.transform_fn is None:
            self._log("No transform active — select one from the dropdown", "warn")
            return

        label = self._selected_label.get()
        self._log(f"▶ [{label}] via {source}", "info")

        preview = clip_text[:80].replace("\n", "↵")
        self._log(f"  In:  {preview!r}{'…' if len(clip_text) > 80 else ''}", "preview")

        try:
            result = self.transform_fn(clip_text)
            if not isinstance(result, str):
                result = str(result)

            pyperclip.copy(result)
            self.last_clip = result   # prevent re-triggering on our own write

            preview_out = result[:80].replace("\n", "↵")
            self._log(f"  Out: {preview_out!r}{'…' if len(result) > 80 else ''}", "ok")
            self._log(f"  ✓ {len(result)} chars written to clipboard", "ok")

            self.transform_count += 1
            self._update_stats()
            self._set_status(f"OK [{label}] @ {datetime.now().strftime('%H:%M:%S')}")

        except Exception as exc:
            self.error_count += 1
            self._update_stats()
            self._log(f"  ✗ Error: {exc}", "err")
            self._log(traceback.format_exc(), "err")
            self._set_status(f"Error in [{label}]: {exc}")

    # ── Polling ──────────────────────────────────────────────────────────────

    def _start_polling(self):
        if self.hotkey:
            self.mode_label.config(text=f"[hotkey: {self.hotkey}]")
        else:
            self.mode_label.config(text=f"[polling every {self.poll_interval}s]")

        self.running = True
        self.status_dot.config(fg="#50fa7b")
        self.toggle_btn.config(text="⏸ Pause")

        if not self.hotkey:
            def _poll():
                try:
                    self.last_clip = pyperclip.paste()
                except Exception:
                    pass

                while True:
                    if not self.running:
                        time.sleep(0.2)
                        continue
                    try:
                        current = pyperclip.paste()
                        if current and current != self.last_clip:
                            self.last_clip = current
                            self._run_transform(current, source="clipboard change")
                    except Exception as exc:
                        self._log(f"Clipboard read error: {exc}", "warn")
                    time.sleep(self.poll_interval)

            threading.Thread(target=_poll, daemon=True).start()

    # ── Hotkey ───────────────────────────────────────────────────────────────

    def _register_hotkey(self):
        if not self.hotkey:
            return
        if not KEYBOARD_AVAILABLE:
            self._log(
                "'keyboard' package not installed — hotkey disabled. pip install keyboard", "warn"
            )
            self.hotkey = None
            return

        def _on_hotkey():
            try:
                clip = pyperclip.paste()
                if clip:
                    self._run_transform(clip, source=f"hotkey ({self.hotkey})")
                else:
                    self._log("Hotkey pressed but clipboard is empty", "warn")
            except Exception as exc:
                self._log(f"Hotkey error: {exc}", "err")

        keyboard.add_hotkey(self.hotkey, _on_hotkey)
        self._log(f"Hotkey registered: {self.hotkey}", "ok")

    # ── Controls ─────────────────────────────────────────────────────────────

    def _toggle(self):
        self.running = not self.running
        if self.running:
            self.toggle_btn.config(text="⏸ Pause")
            self.status_dot.config(fg="#50fa7b")
            self._log("Resumed", "ok")
            self._set_status("Running")
            try:
                self.last_clip = pyperclip.paste()   # re-seed on resume
            except Exception:
                pass
        else:
            self.toggle_btn.config(text="▶ Resume")
            self.status_dot.config(fg="#ff5555")
            self._log("Paused", "warn")
            self._set_status("Paused")

    def _on_close(self):
        if KEYBOARD_AVAILABLE and self.hotkey:
            try:
                keyboard.remove_hotkey(self.hotkey)
            except Exception:
                pass
        self.root.destroy()


# ─── Entry point ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Clipboard transform middleware with folder-based transform picker."
    )
    parser.add_argument(
        "--script", "-s", default=None,
        help="Pre-select a specific transform script on launch (optional)."
    )
    parser.add_argument(
        "--transforms", "-t",
        default=str(Path(__file__).parent / "transforms"),
        help="Folder to scan for transform scripts (default: <script dir>/transforms)."
    )
    parser.add_argument(
        "--hotkey", "-k", default=None,
        help="Hotkey to trigger transform on demand instead of auto-polling "
             "(e.g. ctrl+shift+v). Requires: pip install keyboard"
    )
    parser.add_argument(
        "--poll", "-p", type=float, default=0.5,
        help="Clipboard poll interval in seconds (default: 0.5). Ignored when --hotkey is set."
    )
    return parser.parse_args()


def main():
    args = parse_args()
    root = tk.Tk()
    ClipCommandApp(
        root,
        transforms_folder=args.transforms,
        initial_script=args.script,
        poll_interval=args.poll,
        hotkey=args.hotkey,
    )
    root.mainloop()


if __name__ == "__main__":
    main()
