#!/usr/bin/env python3
"""
clipcommand.py - Clipboard transform middleware inspired by the Perl Monks clipcommand.pl

Watches the clipboard for changes, passes content through a pipeline of user-supplied
transform scripts, and writes the result back to the clipboard.

Features:
  - Single transforms or multi-step chains
  - Chain definitions loaded from transforms.ini
  - Per-transform config overrides via transforms.ini
  - Dry run mode with a dedicated preview pane
  - Folder-based transform picker with live rescan

Usage:
    python clipcommand.py [--script myscript.py] [--transforms ./transforms]
                          [--hotkey ctrl+shift+v] [--poll 0.5]

Transform script API:
    def transform(text: str) -> str: ...
    Module-level docstring shown as description in UI.

transforms.ini format:
    [transform:my_script]          # matches filename stem my_script.py
    bookmark = bk2
    heading_rows = 2

    [chain:my_chain]
    description = Clean, convert, insert
    steps = trim_whitespace, csv_to_yaml, word_from_yaml_active
"""

import argparse
import configparser
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

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

# ── Colours ───────────────────────────────────────────────────────────────────
C = {
    "bg_dark":   "#1e2127",
    "bg_mid":    "#282a36",
    "bg_input":  "#44475a",
    "bg_log":    "#21222c",
    "fg":        "#f8f8f2",
    "fg_dim":    "#6272a4",
    "fg_accent": "#8be9fd",
    "fg_purple": "#bd93f9",
    "fg_yellow": "#f1fa8c",
    "ok":        "#50fa7b",
    "err":       "#ff5555",
    "warn":      "#ffb86c",
    "dry":       "#ffb86c",   # orange dot in dry-run mode
    "chain":     "#bd93f9",   # purple for chain labels
}


# ─── INI loader ──────────────────────────────────────────────────────────────

def load_ini(folder: str) -> configparser.ConfigParser:
    """Load transforms.ini from the transforms folder if it exists."""
    cfg = configparser.ConfigParser()
    ini_path = Path(folder) / "transforms.ini"
    if ini_path.exists():
        cfg.read(ini_path, encoding="utf-8")
    return cfg


def get_transform_overrides(cfg: configparser.ConfigParser, stem: str) -> dict:
    """Return key/value overrides for a transform script from transforms.ini."""
    section = f"transform:{stem}"
    if cfg.has_section(section):
        return dict(cfg[section])
    return {}


def get_chains(cfg: configparser.ConfigParser) -> list:
    """
    Return chain definitions from transforms.ini.
    Each item: {name, label, description, steps: [str]}
    """
    chains = []
    for section in cfg.sections():
        if section.startswith("chain:"):
            name  = section[len("chain:"):]
            label = f"⛓ {name.replace('_', ' ').title()}"
            desc  = cfg.get(section, "description", fallback="")
            raw   = cfg.get(section, "steps", fallback="")
            steps = [s.strip() for s in raw.split(",") if s.strip()]
            chains.append({
                "name":        name,
                "label":       label,
                "description": desc,
                "steps":       steps,
                "is_chain":    True,
            })
    return chains


# ─── Transform loader ─────────────────────────────────────────────────────────

def load_transform(script_path: str, overrides: dict = None):
    """
    Dynamically load a transform script.
    Returns (transform_fn, resolved_path, description_str).
    Applies overrides as module-level attributes before returning.
    """
    path = Path(script_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")

    spec   = importlib.util.spec_from_file_location("transform_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "transform"):
        raise AttributeError("Script must define a 'transform(text) -> str' function")

    # Apply ini overrides as module-level attributes (type-coerced where possible)
    if overrides:
        for key, value in overrides.items():
            # Try int, then float, then leave as string
            for cast in (int, float):
                try:
                    value = cast(value)
                    break
                except (ValueError, TypeError):
                    pass
            setattr(module, key, value)

    description = (
        (module.__doc__ or "").strip()
        or (module.transform.__doc__ or "").strip()
        or "No description."
    )
    short_desc = next(
        (ln.strip() for ln in description.splitlines() if ln.strip()), description
    )

    return module.transform, str(path), short_desc


# ─── Transform folder scanner ─────────────────────────────────────────────────

def scan_transforms(folder: str, cfg: configparser.ConfigParser) -> list:
    """
    Scan folder for .py transform scripts and merge in chain definitions from ini.
    Returns list of registry dicts sorted alphabetically (scripts first, chains appended).
    """
    results = []
    p = Path(folder)
    if not p.is_dir():
        return results

    for pyfile in sorted(p.glob("*.py")):
        if pyfile.name.startswith("_"):
            continue
        overrides = get_transform_overrides(cfg, pyfile.stem)
        try:
            fn, path, desc = load_transform(str(pyfile), overrides)
            results.append({
                "name":        pyfile.stem,
                "label":       pyfile.stem.replace("_", " ").title(),
                "path":        path,
                "description": desc,
                "fn":          fn,
                "is_chain":    False,
                "steps":       [],
            })
        except Exception as exc:
            results.append({
                "name":        pyfile.stem,
                "label":       f"⚠ {pyfile.stem}",
                "path":        str(pyfile),
                "description": f"Load error: {exc}",
                "fn":          None,
                "is_chain":    False,
                "steps":       [],
            })

    # Append chains from ini
    for chain in get_chains(cfg):
        results.append(chain)

    return results


# ─── Tooltip ──────────────────────────────────────────────────────────────────

class Tooltip:
    def __init__(self, widget, text_fn):
        self._widget  = widget
        self._text_fn = text_fn
        self._win     = None
        widget.bind("<Enter>",       self._show)
        widget.bind("<Leave>",       self._hide)
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
            background=C["bg_mid"], foreground=C["fg"],
            relief=tk.FLAT, font=("Courier", 9),
            wraplength=460, padx=6, pady=4,
        ).pack()

    def _hide(self, _event=None):
        if self._win:
            self._win.destroy()
            self._win = None

    def update_text_fn(self, fn):
        self._text_fn = fn


# ─── Chain row widget ─────────────────────────────────────────────────────────

class ChainRow:
    """One row in the chain builder: [label] [combobox] [+] [-]"""

    def __init__(self, parent, app, row_index: int):
        self.app       = app
        self._var      = tk.StringVar()
        self._tooltip  = None

        self.frame = tk.Frame(parent, bg=C["bg_mid"])
        self.frame.pack(fill=tk.X, padx=0, pady=1)

        # Step label (e.g. "Step 1:", "Then:", "Then:")
        self._step_lbl = tk.Label(
            self.frame,
            text=self._step_text(row_index),
            fg=C["fg_dim"], bg=C["bg_mid"],
            font=("Courier", 9), width=8, anchor="e"
        )
        self._step_lbl.pack(side=tk.LEFT, padx=(8, 2))

        # Combobox
        self.combo = ttk.Combobox(
            self.frame, textvariable=self._var,
            state="readonly", style="Dark.TCombobox",
            font=("Courier", 9), width=30
        )
        self.combo.pack(side=tk.LEFT, padx=4)
        self.combo.bind("<<ComboboxSelected>>", self._on_select)
        self._tooltip = Tooltip(self.combo, self._desc)

        # [+] button
        self._btn_add = tk.Button(
            self.frame, text="+", command=self._on_add,
            bg=C["bg_input"], fg=C["ok"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2",
            font=("Courier", 10, "bold"), width=2
        )
        self._btn_add.pack(side=tk.LEFT, padx=2)

        # [-] button
        self._btn_del = tk.Button(
            self.frame, text="−", command=self._on_del,
            bg=C["bg_input"], fg=C["err"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2",
            font=("Courier", 10, "bold"), width=2
        )
        self._btn_del.pack(side=tk.LEFT, padx=2)

    @staticmethod
    def _step_text(index: int) -> str:
        return "Step 1:" if index == 0 else "  Then:"

    def update_step_label(self, index: int):
        self._step_lbl.config(text=self._step_text(index))

    def update_del_visibility(self, is_only_row: bool):
        """Hide [-] when this is the only row."""
        self._btn_del.config(state=tk.DISABLED if is_only_row else tk.NORMAL,
                             fg=C["fg_dim"] if is_only_row else C["err"])

    def set_values(self, values):
        self.combo["values"] = values

    def get(self) -> str:
        return self._var.get()

    def set(self, label: str):
        self._var.set(label)

    def _desc(self) -> str:
        label = self._var.get()
        entry = next((t for t in self.app._registry if t["label"] == label), None)
        return entry["description"] if entry else ""

    def _on_select(self, _event=None):
        self.app._on_row_select()

    def _on_add(self):
        self.app._insert_row_after(self)

    def _on_del(self):
        self.app._remove_row(self)

    def destroy(self):
        self.frame.destroy()


# ─── Main application ─────────────────────────────────────────────────────────

class ClipCommandApp:
    MAX_LOG_LINES = 300

    def __init__(self, root: tk.Tk, transforms_folder: str,
                 initial_script, poll_interval: float, hotkey):

        self.root              = root
        self.transforms_folder = transforms_folder
        self.poll_interval     = poll_interval
        self.hotkey            = hotkey

        self.running           = False
        self.dry_run           = False
        self.last_clip         = ""
        self.transform_count   = 0
        self.error_count       = 0

        self._registry: list   = []
        self._rows: list       = []   # list of ChainRow

        self._build_ui()
        self._refresh_transforms(preselect=initial_script)
        self._register_hotkey()
        self._start_polling()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.root.title("ClipCommand")
        self.root.geometry("640x560")
        self.root.minsize(500, 400)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.configure(bg=C["bg_dark"])

        self._apply_styles()

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self.root, bg=C["bg_dark"], padx=8, pady=6)
        header.pack(fill=tk.X)

        self.status_dot = tk.Label(
            header, text="●", fg=C["err"], bg=C["bg_dark"], font=("Courier", 14)
        )
        self.status_dot.pack(side=tk.LEFT)

        tk.Label(
            header, text="ClipCommand", fg=C["fg"], bg=C["bg_dark"],
            font=("Helvetica", 12, "bold")
        ).pack(side=tk.LEFT, padx=6)

        self.mode_label = tk.Label(
            header, text="[starting…]", fg=C["fg_accent"], bg=C["bg_dark"],
            font=("Helvetica", 10)
        )
        self.mode_label.pack(side=tk.LEFT)

        # Right-side header buttons
        self.toggle_btn = tk.Button(
            header, text="⏸ Pause", command=self._toggle,
            bg=C["bg_input"], fg=C["fg"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=6
        )
        self.toggle_btn.pack(side=tk.RIGHT, padx=3)

        tk.Button(
            header, text="⟳ Reload", command=self._reload_all,
            bg=C["bg_input"], fg=C["fg"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=6
        ).pack(side=tk.RIGHT, padx=3)

        self.dryrun_btn = tk.Button(
            header, text="🔍 Dry Run", command=self._toggle_dry_run,
            bg=C["bg_input"], fg=C["fg"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=6
        )
        self.dryrun_btn.pack(side=tk.RIGHT, padx=3)

        # ── Chain builder panel ───────────────────────────────────────────────
        self._chain_panel = tk.Frame(self.root, bg=C["bg_mid"], pady=4)
        self._chain_panel.pack(fill=tk.X)

        # Rescan button lives at top-right of chain panel
        rescan_bar = tk.Frame(self._chain_panel, bg=C["bg_mid"])
        rescan_bar.pack(fill=tk.X, padx=8, pady=(0, 2))
        tk.Button(
            rescan_bar, text="⟳ Rescan folder", command=lambda: self._refresh_transforms(),
            bg=C["bg_input"], fg=C["fg"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=4
        ).pack(side=tk.RIGHT)

        # Container for ChainRow widgets
        self._rows_frame = tk.Frame(self._chain_panel, bg=C["bg_mid"])
        self._rows_frame.pack(fill=tk.X)

        # ── Stats bar ─────────────────────────────────────────────────────────
        stats_bar = tk.Frame(self.root, bg=C["bg_mid"], padx=8, pady=2)
        stats_bar.pack(fill=tk.X)
        self.stats_label = tk.Label(
            stats_bar,
            text="Transforms: 0  |  Errors: 0  |  Chain: —",
            fg=C["fg_dim"], bg=C["bg_mid"], font=("Courier", 9)
        )
        self.stats_label.pack(side=tk.LEFT)

        # ── Log ───────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg=C["bg_log"])
        log_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        self.log = scrolledtext.ScrolledText(
            log_frame, bg=C["bg_log"], fg=C["fg"],
            font=("Courier", 9), state=tk.DISABLED,
            wrap=tk.WORD, relief=tk.FLAT,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        for tag, colour in [
            ("ts", C["fg_dim"]), ("ok", C["ok"]), ("err", C["err"]),
            ("info", C["fg_accent"]), ("warn", C["warn"]),
            ("preview", C["fg_purple"]), ("chain", C["chain"]),
        ]:
            self.log.tag_config(tag, foreground=colour)

        # ── Preview pane (hidden until dry run) ───────────────────────────────
        self._preview_frame = tk.Frame(self.root, bg=C["bg_dark"])
        # not packed yet — shown on dry run toggle

        preview_header = tk.Frame(self._preview_frame, bg=C["bg_dark"], padx=8, pady=3)
        preview_header.pack(fill=tk.X)

        tk.Label(
            preview_header, text="🔍 Dry Run Preview",
            fg=C["dry"], bg=C["bg_dark"], font=("Courier", 9, "bold")
        ).pack(side=tk.LEFT)

        tk.Button(
            preview_header, text="📋 Copy to clipboard",
            command=self._copy_preview,
            bg=C["bg_input"], fg=C["fg"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=4, font=("Courier", 9)
        ).pack(side=tk.RIGHT)

        tk.Button(
            preview_header, text="✕ Clear",
            command=self._clear_preview,
            bg=C["bg_input"], fg=C["fg"], relief=tk.FLAT,
            activebackground="#6272a4", cursor="hand2", padx=4, font=("Courier", 9)
        ).pack(side=tk.RIGHT, padx=4)

        self.preview_text = scrolledtext.ScrolledText(
            self._preview_frame, bg="#1a1b26", fg=C["ok"],
            font=("Courier", 9), wrap=tk.WORD, relief=tk.FLAT,
            height=8,
        )
        self.preview_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # ── Status bar ────────────────────────────────────────────────────────
        self.statusbar = tk.Label(
            self.root, text="Ready", anchor=tk.W,
            bg=C["bg_dark"], fg=C["fg_dim"], font=("Courier", 9), padx=6
        )
        self.statusbar.pack(fill=tk.X, side=tk.BOTTOM)

    def _apply_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure(
            "Dark.TCombobox",
            fieldbackground=C["bg_input"], background=C["bg_input"],
            foreground=C["fg"], selectbackground="#6272a4",
            selectforeground=C["fg"], arrowcolor=C["fg"],
        )
        style.map("Dark.TCombobox", fieldbackground=[("readonly", C["bg_input"])])

    # ── Chain row management ──────────────────────────────────────────────────

    def _all_labels(self) -> list:
        return [t["label"] for t in self._registry]

    def _add_row(self, label: str = "") -> ChainRow:
        row = ChainRow(self._rows_frame, self, len(self._rows))
        row.set_values(self._all_labels())
        if label:
            row.set(label)
        elif self._all_labels():
            row.set(self._all_labels()[0])
        self._rows.append(row)
        self._refresh_row_labels()
        return row

    def _insert_row_after(self, after_row: ChainRow):
        idx = self._rows.index(after_row)
        # Destroy and rebuild all rows after insertion point
        new_order = self._rows[:idx + 1]
        labels_after = [r.get() for r in self._rows[idx + 1:]]
        for r in self._rows[idx + 1:]:
            r.destroy()
        self._rows = new_order

        # Insert blank row
        new_row = ChainRow(self._rows_frame, self, idx + 1)
        new_row.set_values(self._all_labels())
        if self._all_labels():
            new_row.set(self._all_labels()[0])
        self._rows.append(new_row)

        # Re-add the rows that were after
        for lbl in labels_after:
            r = ChainRow(self._rows_frame, self, len(self._rows))
            r.set_values(self._all_labels())
            r.set(lbl)
            self._rows.append(r)

        self._refresh_row_labels()
        self._on_row_select()

    def _remove_row(self, row: ChainRow):
        if len(self._rows) <= 1:
            return
        idx = self._rows.index(row)
        row.destroy()
        self._rows.pop(idx)
        self._refresh_row_labels()
        self._on_row_select()

    def _refresh_row_labels(self):
        only = len(self._rows) == 1
        for i, row in enumerate(self._rows):
            row.update_step_label(i)
            row.update_del_visibility(only)

    def _set_chain_rows(self, labels: list):
        """Replace all rows with a specific list of labels (for loading a chain)."""
        for r in self._rows:
            r.destroy()
        self._rows = []
        for lbl in labels:
            self._add_row(lbl)
        if not self._rows:
            self._add_row()
        self._refresh_row_labels()

    def _on_row_select(self):
        """Called when any combobox changes — check if a chain was selected on row 0."""
        if not self._rows:
            return
        first_label = self._rows[0].get()
        entry = next((t for t in self._registry if t["label"] == first_label), None)
        if entry and entry.get("is_chain"):
            self._load_chain(entry)
        self._update_stats()

    def _load_chain(self, chain_entry: dict):
        """Expand a chain definition into individual rows."""
        steps = chain_entry.get("steps", [])
        labels = []
        for step_name in steps:
            match = next(
                (t["label"] for t in self._registry
                 if t["name"] == step_name and not t.get("is_chain")),
                None
            )
            if match:
                labels.append(match)
            else:
                self._log(f"Chain step '{step_name}' not found in registry", "warn")
        if labels:
            self._set_chain_rows(labels)
            self._log(
                f"Loaded chain '{chain_entry['name']}': "
                + " → ".join(labels), "chain"
            )

    # ── Transform registry ────────────────────────────────────────────────────

    def _refresh_transforms(self, preselect=None):
        prev_labels = [r.get() for r in self._rows]
        cfg = load_ini(self.transforms_folder)
        self._registry = scan_transforms(self.transforms_folder, cfg)

        all_labels = self._all_labels()
        good  = sum(1 for t in self._registry if not t.get("is_chain") and t["fn"] is not None)
        bad   = sum(1 for t in self._registry if not t.get("is_chain") and t["fn"] is None)
        nchai = sum(1 for t in self._registry if t.get("is_chain"))

        msg = f"Scanned '{self.transforms_folder}': {good} transforms"
        if nchai:
            msg += f", {nchai} chain(s)"
        if bad:
            msg += f", {bad} failed"
        self._log(msg, "info" if not bad else "warn")

        # Update all existing row comboboxes
        for row in self._rows:
            row.set_values(all_labels)

        # If no rows yet, build the initial row
        if not self._rows:
            if preselect:
                p = Path(preselect).resolve()
                lbl = next(
                    (t["label"] for t in self._registry
                     if not t.get("is_chain") and Path(t["path"]).resolve() == p),
                    None
                )
                self._add_row(lbl or (all_labels[0] if all_labels else ""))
            else:
                self._add_row(all_labels[0] if all_labels else "")
        else:
            # Try to restore previous selections
            for row, prev in zip(self._rows, prev_labels):
                if prev in all_labels:
                    row.set(prev)

        self._refresh_row_labels()
        self._update_stats()
        self._reseed_clipboard()

    def _get_active_steps(self) -> list:
        """
        Return the list of registry entries for the current chain rows.
        Filters out chain entries (they were already expanded on selection).
        """
        steps = []
        for row in self._rows:
            label = row.get()
            entry = next(
                (t for t in self._registry if t["label"] == label and not t.get("is_chain")),
                None
            )
            if entry:
                steps.append(entry)
        return steps

    def _reload_all(self):
        """Hot-reload all scripts in the current chain from disk."""
        cfg = load_ini(self.transforms_folder)
        reloaded = 0
        for step in self._get_active_steps():
            try:
                overrides = get_transform_overrides(cfg, step["name"])
                fn, path, desc = load_transform(step["path"], overrides)
                step["fn"]          = fn
                step["description"] = desc
                reloaded += 1
            except Exception as exc:
                self._log(f"Reload failed [{step['name']}]: {exc}", "err")
        self._log(f"Reloaded {reloaded} script(s)", "ok")
        self._set_status("Reloaded OK")

    # ── Logging ───────────────────────────────────────────────────────────────

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
        steps = self._get_active_steps()
        if len(steps) == 1:
            chain_str = steps[0]["name"] if steps else "—"
        elif len(steps) > 1:
            chain_str = " → ".join(s["name"] for s in steps)
        else:
            chain_str = "—"
        text = (
            f"Transforms: {self.transform_count}  |  "
            f"Errors: {self.error_count}  |  "
            f"Chain: {chain_str}"
        )
        self.root.after(0, lambda: self.stats_label.config(text=text))

    def _set_status(self, text: str):
        self.root.after(0, lambda: self.statusbar.config(text=text))

    # ── Preview pane ──────────────────────────────────────────────────────────

    def _show_preview(self, text: str):
        def _write():
            self.preview_text.config(state=tk.NORMAL)
            self.preview_text.delete("1.0", tk.END)
            self.preview_text.insert(tk.END, text)
            self.preview_text.config(state=tk.DISABLED)
        self.root.after(0, _write)

    def _clear_preview(self):
        self.preview_text.config(state=tk.NORMAL)
        self.preview_text.delete("1.0", tk.END)
        self.preview_text.config(state=tk.DISABLED)

    def _copy_preview(self):
        content = self.preview_text.get("1.0", tk.END).rstrip("\n")
        if content:
            pyperclip.copy(content)
            self.last_clip = content
            self._log("Preview content copied to clipboard", "ok")
            self._set_status("Preview copied to clipboard")

    def _toggle_dry_run(self):
        self.dry_run = not self.dry_run
        if self.dry_run:
            self.dryrun_btn.config(bg="#6d4c00", fg=C["warn"])
            self.status_dot.config(fg=C["dry"])
            self._preview_frame.pack(fill=tk.BOTH, padx=4, pady=(0, 4),
                                     before=self.statusbar)
            self._log("Dry run ON — output goes to preview pane, not clipboard", "warn")
            self._set_status("DRY RUN active")
        else:
            self.dryrun_btn.config(bg=C["bg_input"], fg=C["fg"])
            self.status_dot.config(fg=C["ok"] if self.running else C["err"])
            self._preview_frame.pack_forget()
            self._log("Dry run OFF — output goes to clipboard", "info")
            self._set_status("Running" if self.running else "Paused")

    # ── Chain execution ───────────────────────────────────────────────────────

    def _run_chain(self, clip_text: str, source: str = "clipboard"):
        steps = self._get_active_steps()

        if not steps:
            self._log("No transforms active — add steps to the chain", "warn")
            return

        is_chain = len(steps) > 1
        chain_label = " → ".join(s["name"] for s in steps)

        if is_chain:
            self._log(f"▶ Chain [{chain_label}] via {source}", "chain")
        else:
            self._log(f"▶ [{steps[0]['name']}] via {source}", "info")

        current = clip_text
        for i, step in enumerate(steps):
            if step["fn"] is None:
                self._log(f"  ✗ Step {i+1} [{step['name']}] has no function (load error)", "err")
                self.error_count += 1
                self._update_stats()
                return

            preview_in = current[:80].replace("\n", "↵")
            if is_chain:
                self._log(f"  [{i+1}/{len(steps)}] {step['name']}", "chain")
            self._log(f"   In:  {preview_in!r}{'…' if len(current) > 80 else ''}", "preview")

            try:
                result = step["fn"](current)
                if not isinstance(result, str):
                    result = str(result)

                preview_out = result[:80].replace("\n", "↵")
                self._log(f"   Out: {preview_out!r}{'…' if len(result) > 80 else ''}", "ok")
                current = result

            except Exception as exc:
                self._log(f"  ✗ Error in [{step['name']}]: {exc}", "err")
                self._log(traceback.format_exc(), "err")
                self.error_count += 1
                self._update_stats()
                self._set_status(f"Error in [{step['name']}]: {exc}")
                return

        # All steps completed
        if self.dry_run:
            self._log(
                f"  🔍 Dry run — {len(current)} chars sent to preview pane", "warn"
            )
            self._show_preview(current)
            self._set_status(
                f"Dry run OK [{chain_label}] @ {datetime.now().strftime('%H:%M:%S')}"
            )
        else:
            pyperclip.copy(current)
            self.last_clip = current
            self._log(f"  ✓ {len(current)} chars written to clipboard", "ok")
            self._set_status(
                f"OK [{chain_label}] @ {datetime.now().strftime('%H:%M:%S')}"
            )

        self.transform_count += 1
        self._update_stats()

    # ── Polling ───────────────────────────────────────────────────────────────

    def _reseed_clipboard(self):
        try:
            self.last_clip = pyperclip.paste()
        except Exception:
            pass

    def _start_polling(self):
        if self.hotkey:
            self.mode_label.config(text=f"[hotkey: {self.hotkey}]")
        else:
            self.mode_label.config(text=f"[polling every {self.poll_interval}s]")

        self.running = True
        self.status_dot.config(fg=C["ok"])
        self.toggle_btn.config(text="⏸ Pause")

        if not self.hotkey:
            def _poll():
                self._reseed_clipboard()
                while True:
                    if not self.running:
                        time.sleep(0.2)
                        continue
                    try:
                        current = pyperclip.paste()
                        if current and current != self.last_clip:
                            self.last_clip = current
                            self._run_chain(current, source="clipboard change")
                    except Exception as exc:
                        self._log(f"Clipboard read error: {exc}", "warn")
                    time.sleep(self.poll_interval)

            threading.Thread(target=_poll, daemon=True).start()

    # ── Hotkey ────────────────────────────────────────────────────────────────

    def _register_hotkey(self):
        if not self.hotkey:
            return
        if not KEYBOARD_AVAILABLE:
            self._log("'keyboard' not installed — hotkey disabled. pip install keyboard", "warn")
            self.hotkey = None
            return

        def _on_hotkey():
            try:
                clip = pyperclip.paste()
                if clip:
                    self._run_chain(clip, source=f"hotkey ({self.hotkey})")
                else:
                    self._log("Hotkey pressed but clipboard is empty", "warn")
            except Exception as exc:
                self._log(f"Hotkey error: {exc}", "err")

        keyboard.add_hotkey(self.hotkey, _on_hotkey)
        self._log(f"Hotkey registered: {self.hotkey}", "ok")

    # ── Controls ──────────────────────────────────────────────────────────────

    def _toggle(self):
        self.running = not self.running
        if self.running:
            self.toggle_btn.config(text="⏸ Pause")
            self.status_dot.config(fg=C["dry"] if self.dry_run else C["ok"])
            self._log("Resumed", "ok")
            self._set_status("Running")
            self._reseed_clipboard()
        else:
            self.toggle_btn.config(text="▶ Resume")
            self.status_dot.config(fg=C["err"])
            self._log("Paused", "warn")
            self._set_status("Paused")

    def _on_close(self):
        if KEYBOARD_AVAILABLE and self.hotkey:
            try:
                keyboard.remove_hotkey(self.hotkey)
            except Exception:
                pass
        self.root.destroy()


# ─── Entry point ──────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Clipboard transform middleware with chaining, dry run, and ini config."
    )
    parser.add_argument("--script", "-s", default=None,
                        help="Pre-select a transform on launch (optional).")
    parser.add_argument("--transforms", "-t",
                        default=str(Path(__file__).parent / "transforms"),
                        help="Folder to scan (default: <script dir>/transforms).")
    parser.add_argument("--hotkey", "-k", default=None,
                        help="Hotkey to trigger manually (e.g. ctrl+shift+v). "
                             "Requires: pip install keyboard")
    parser.add_argument("--poll", "-p", type=float, default=0.5,
                        help="Poll interval in seconds (default: 0.5).")
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
