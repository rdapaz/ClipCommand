#!/usr/bin/env python3
"""
clipcommand.py - Clipboard transform middleware (PySide6 edition)

Watches the clipboard for changes, passes content through a pipeline of
user-supplied transform scripts, and writes the result back to the clipboard.

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
    [transform:my_script]
    bookmark = bk2
    heading_rows = 2

    [chain:my_chain]
    description = Clean, convert, insert
    steps = trim_whitespace, csv_to_yaml, word_from_yaml_active
"""

import argparse
import configparser
import importlib.util
import sqlite3
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
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QPushButton, QComboBox, QTextEdit, QFrame, QScrollArea,
        QSizePolicy, QToolTip
    )
    from PySide6.QtCore import Qt, QTimer, Signal, QObject, QThread
    from PySide6.QtGui import QColor, QTextCursor, QFont, QPalette, QAction
except ImportError:
    print("Missing dependency: pip install PySide6")
    sys.exit(1)

try:
    import keyboard
    KEYBOARD_AVAILABLE = True
except ImportError:
    KEYBOARD_AVAILABLE = False

from db_logger import DBLogger
from log_browser import LogBrowserDialog


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
    "dry":       "#ffb86c",
    "chain":     "#bd93f9",
}

TAG_COLOURS = {
    "ts":      C["fg_dim"],
    "ok":      C["ok"],
    "err":     C["err"],
    "info":    C["fg_accent"],
    "warn":    C["warn"],
    "preview": C["fg_purple"],
    "chain":   C["chain"],
}


# ─── Stylesheet ───────────────────────────────────────────────────────────────

def build_stylesheet() -> str:
    return f"""
    QMainWindow, QWidget {{
        background-color: {C["bg_dark"]};
        color: {C["fg"]};
        font-family: "Menlo", "Courier New", monospace;
        font-size: 12px;
    }}
    QPushButton {{
        background-color: {C["bg_input"]};
        color: {C["fg"]};
        border: none;
        border-radius: 4px;
        padding: 5px 10px;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: #6272a4;
    }}
    QPushButton:pressed {{
        background-color: #4a5580;
    }}
    QPushButton#dryrun_active {{
        background-color: #6d4c00;
        color: {C["warn"]};
    }}
    QPushButton#add_btn {{
        color: {C["ok"]};
        font-weight: bold;
        padding: 3px 8px;
    }}
    QPushButton#del_btn {{
        color: {C["err"]};
        font-weight: bold;
        padding: 3px 8px;
    }}
    QPushButton#del_btn:disabled {{
        color: {C["fg_dim"]};
    }}
    QComboBox {{
        background-color: {C["bg_input"]};
        color: {C["fg"]};
        border: 1px solid {C["fg_dim"]};
        border-radius: 4px;
        padding: 3px 8px;
        min-width: 220px;
        font-size: 12px;
    }}
    QComboBox:hover {{
        border-color: {C["fg_accent"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox::down-arrow {{
        width: 10px;
        height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {C["bg_input"]};
        color: {C["fg"]};
        selection-background-color: #6272a4;
        border: 1px solid {C["fg_dim"]};
    }}
    QTextEdit {{
        background-color: {C["bg_log"]};
        color: {C["fg"]};
        border: none;
        font-family: "Menlo", "Courier New", monospace;
        font-size: 11px;
    }}
    QTextEdit#preview_text {{
        background-color: #1a1b26;
        color: {C["ok"]};
    }}
    QLabel#status_dot_ok  {{ color: {C["ok"]};  font-size: 16px; }}
    QLabel#status_dot_err {{ color: {C["err"]}; font-size: 16px; }}
    QLabel#status_dot_dry {{ color: {C["dry"]}; font-size: 16px; }}
    QLabel#title_label    {{ color: {C["fg"]};  font-size: 13px; font-weight: bold; }}
    QLabel#mode_label     {{ color: {C["fg_accent"]}; font-size: 11px; }}
    QLabel#step_label     {{ color: {C["fg_dim"]}; font-size: 11px; }}
    QLabel#stats_label    {{ color: {C["fg_dim"]}; font-size: 10px; padding: 2px 8px; }}
    QLabel#statusbar      {{ color: {C["fg_dim"]}; font-size: 10px; padding: 2px 6px;
                             background-color: {C["bg_dark"]}; }}
    QLabel#preview_header {{ color: {C["dry"]}; font-size: 11px; font-weight: bold; }}
    QFrame#chain_panel    {{ background-color: {C["bg_mid"]}; }}
    QFrame#stats_bar      {{ background-color: {C["bg_mid"]}; }}
    QFrame#preview_frame  {{ background-color: {C["bg_dark"]}; }}
    QFrame#separator      {{ color: {C["fg_dim"]}; }}
    QScrollBar:vertical {{
        background: {C["bg_dark"]};
        width: 8px;
    }}
    QScrollBar::handle:vertical {{
        background: {C["bg_input"]};
        border-radius: 4px;
        min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


# ─── INI loader ───────────────────────────────────────────────────────────────

def load_ini(folder: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    candidates = [
        Path(folder) / "transforms.ini",
        Path(folder).parent / "transforms.ini",
    ]
    for ini_path in candidates:
        if ini_path.exists():
            cfg.read(ini_path, encoding="utf-8-sig")
            break
    return cfg


def get_transform_overrides(cfg, stem: str) -> dict:
    section = f"transform:{stem}"
    return dict(cfg[section]) if cfg.has_section(section) else {}


def get_chains(cfg) -> list:
    chains = []
    for section in cfg.sections():
        if section.startswith("chain:"):
            name  = section[len("chain:"):]
            label = f"⛓ {name.replace('_', ' ').title()}"
            desc  = cfg.get(section, "description", fallback="")
            raw   = cfg.get(section, "steps", fallback="")
            steps = [s.strip() for s in raw.split(",") if s.strip()]
            chains.append({
                "name": name, "label": label, "description": desc,
                "steps": steps, "is_chain": True,
            })
    return chains


# ─── Transform loader ──────────────────────────────────────────────────────────

def load_transform(script_path: str, overrides: dict = None):
    path = Path(script_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Script not found: {path}")
    spec   = importlib.util.spec_from_file_location("transform_module", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "transform"):
        raise AttributeError("Script must define a 'transform(text) -> str' function")
    if overrides:
        for key, value in overrides.items():
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


def scan_transforms(folder: str, cfg) -> list:
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
                "name": pyfile.stem,
                "label": pyfile.stem.replace("_", " ").title(),
                "path": path, "description": desc,
                "fn": fn, "is_chain": False, "steps": [],
            })
        except Exception as exc:
            results.append({
                "name": pyfile.stem,
                "label": f"⚠ {pyfile.stem}",
                "path": str(pyfile),
                "description": f"Load error: {exc}",
                "fn": None, "is_chain": False, "steps": [],
            })
    for chain in get_chains(cfg):
        results.append(chain)
    return results


# ─── Clipboard worker ─────────────────────────────────────────────────────────

class ClipboardWorker(QObject):
    """Runs clipboard polling in a QThread, emits signal on change."""
    clip_changed = Signal(str)

    def __init__(self, poll_interval: float):
        super().__init__()
        self.poll_interval = poll_interval
        self._running      = True
        self._active       = True
        self._last         = ""

    def reseed(self):
        try:
            self._last = pyperclip.paste()
        except Exception:
            pass

    def set_active(self, active: bool):
        self._active = active

    def stop(self):
        self._running = False

    def run(self):
        self.reseed()
        while self._running:
            if self._active:
                try:
                    current = pyperclip.paste()
                    if current and current != self._last:
                        self._last = current
                        self.clip_changed.emit(current)
                except Exception:
                    pass
            time.sleep(self.poll_interval)

    def update_last(self, text: str):
        self._last = text


# ─── Chain row widget ──────────────────────────────────────────────────────────

class ChainRow(QWidget):
    changed  = Signal()
    add_after = Signal(object)   # emits self
    remove    = Signal(object)   # emits self

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {C['bg_mid']};")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 2, 8, 2)
        layout.setSpacing(6)

        self.step_label = QLabel("Step 1:")
        self.step_label.setObjectName("step_label")
        self.step_label.setFixedWidth(55)
        self.step_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.step_label)

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo.currentTextChanged.connect(self.changed.emit)
        layout.addWidget(self.combo)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("add_btn")
        self.add_btn.setFixedWidth(28)
        self.add_btn.setToolTip("Insert step after this one")
        self.add_btn.clicked.connect(lambda: self.add_after.emit(self))
        layout.addWidget(self.add_btn)

        self.del_btn = QPushButton("−")
        self.del_btn.setObjectName("del_btn")
        self.del_btn.setFixedWidth(28)
        self.del_btn.setToolTip("Remove this step")
        self.del_btn.clicked.connect(lambda: self.remove.emit(self))
        layout.addWidget(self.del_btn)

    def set_step_index(self, index: int):
        self.step_label.setText("Step 1:" if index == 0 else "  Then:")

    def set_only_row(self, is_only: bool):
        self.del_btn.setEnabled(not is_only)

    def set_values(self, values: list):
        current = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(values)
        if current in values:
            self.combo.setCurrentText(current)
        self.combo.blockSignals(False)

    def get(self) -> str:
        return self.combo.currentText()

    def set(self, label: str):
        self.combo.setCurrentText(label)

    def description(self, registry: list) -> str:
        label = self.get()
        entry = next((t for t in registry if t["label"] == label), None)
        return entry["description"] if entry else ""


# ─── Main window ──────────────────────────────────────────────────────────────

class ClipCommandWindow(QMainWindow):
    MAX_LOG_LINES = 300
    _log_signal   = Signal(str, str)   # message, tag

    def __init__(self, transforms_folder: str, initial_script,
                 poll_interval: float, hotkey):
        super().__init__()

        self.transforms_folder = transforms_folder
        self.poll_interval     = poll_interval
        self.hotkey            = hotkey

        self.running           = False
        self.dry_run           = False
        self.transform_count   = 0
        self.error_count       = 0
        self._registry: list   = []
        self._rows: list       = []
        self._log_browser      = None

        # SQLite logger — DB lives next to clipcommand.py
        project_root = str(Path(__file__).parent)
        self._db = DBLogger(project_root)

        self._log_signal.connect(self._write_log)

        self._build_ui()
        self._refresh_transforms(preselect=initial_script)
        self._start_polling()
        self._register_hotkey()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.setWindowTitle("ClipCommand")
        self.resize(680, 600)
        self.setMinimumSize(500, 400)
        self.setStyleSheet(build_stylesheet())

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Header ────────────────────────────────────────────────────────────
        header = QWidget()
        header.setStyleSheet(f"background-color: {C['bg_dark']}; padding: 4px;")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(8, 6, 8, 6)

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("status_dot_err")
        h_layout.addWidget(self.status_dot)

        title = QLabel("ClipCommand")
        title.setObjectName("title_label")
        h_layout.addWidget(title)

        self.mode_label = QLabel("[starting…]")
        self.mode_label.setObjectName("mode_label")
        h_layout.addWidget(self.mode_label)

        h_layout.addStretch()

        self.dryrun_btn = QPushButton("🔍 Dry Run")
        self.dryrun_btn.clicked.connect(self._toggle_dry_run)
        h_layout.addWidget(self.dryrun_btn)

        log_btn = QPushButton("📋 Log")
        log_btn.clicked.connect(self._open_log_browser)
        h_layout.addWidget(log_btn)

        reload_btn = QPushButton("⟳ Reload")
        reload_btn.clicked.connect(self._reload_all)
        h_layout.addWidget(reload_btn)

        self.toggle_btn = QPushButton("⏸ Pause")
        self.toggle_btn.clicked.connect(self._toggle)
        h_layout.addWidget(self.toggle_btn)

        main_layout.addWidget(header)

        # ── Chain panel ───────────────────────────────────────────────────────
        self.chain_panel = QFrame()
        self.chain_panel.setObjectName("chain_panel")
        self.chain_panel.setFrameShape(QFrame.NoFrame)
        cp_layout = QVBoxLayout(self.chain_panel)
        cp_layout.setContentsMargins(0, 4, 0, 4)
        cp_layout.setSpacing(2)

        rescan_bar = QWidget()
        rescan_bar.setStyleSheet(f"background-color: {C['bg_mid']};")
        rb_layout = QHBoxLayout(rescan_bar)
        rb_layout.setContentsMargins(8, 0, 8, 0)

        self.chain_btn = QPushButton("⛓ Load chain…")
        self.chain_btn.setStyleSheet(
            f"color: {C['chain']}; background-color: {C['bg_input']};"
            f"border-radius: 4px; padding: 5px 10px;"
        )
        self.chain_btn.clicked.connect(self._open_chain_picker)
        rb_layout.addWidget(self.chain_btn)

        rb_layout.addStretch()
        rescan_btn = QPushButton("⟳ Rescan folder")
        rescan_btn.clicked.connect(lambda: self._refresh_transforms())
        rb_layout.addWidget(rescan_btn)
        cp_layout.addWidget(rescan_bar)

        self.rows_widget = QWidget()
        self.rows_widget.setStyleSheet(f"background-color: {C['bg_mid']};")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(1)
        cp_layout.addWidget(self.rows_widget)

        main_layout.addWidget(self.chain_panel)

        # ── Stats bar ─────────────────────────────────────────────────────────
        stats_bar = QFrame()
        stats_bar.setObjectName("stats_bar")
        sb_layout = QHBoxLayout(stats_bar)
        sb_layout.setContentsMargins(8, 2, 8, 2)
        self.stats_label = QLabel("Transforms: 0  |  Errors: 0  |  Chain: —")
        self.stats_label.setObjectName("stats_label")
        sb_layout.addWidget(self.stats_label)
        main_layout.addWidget(stats_bar)

        # ── Log ───────────────────────────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        main_layout.addWidget(self.log, stretch=1)

        # ── Preview pane (hidden until dry run) ───────────────────────────────
        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("preview_frame")
        self.preview_frame.setVisible(False)
        pf_layout = QVBoxLayout(self.preview_frame)
        pf_layout.setContentsMargins(4, 4, 4, 4)
        pf_layout.setSpacing(4)

        ph_widget = QWidget()
        ph_layout = QHBoxLayout(ph_widget)
        ph_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_lbl = QLabel("🔍 Dry Run Preview")
        preview_header_lbl.setObjectName("preview_header")
        ph_layout.addWidget(preview_header_lbl)
        ph_layout.addStretch()
        clear_btn = QPushButton("✕ Clear")
        clear_btn.clicked.connect(self._clear_preview)
        ph_layout.addWidget(clear_btn)
        copy_btn = QPushButton("📋 Copy to clipboard")
        copy_btn.clicked.connect(self._copy_preview)
        ph_layout.addWidget(copy_btn)
        pf_layout.addWidget(ph_widget)

        self.preview_text = QTextEdit()
        self.preview_text.setObjectName("preview_text")
        self.preview_text.setReadOnly(True)
        self.preview_text.setFixedHeight(140)
        pf_layout.addWidget(self.preview_text)

        main_layout.addWidget(self.preview_frame)

        # ── Status bar ────────────────────────────────────────────────────────
        self.statusbar_label = QLabel("Ready")
        self.statusbar_label.setObjectName("statusbar")
        main_layout.addWidget(self.statusbar_label)

    # ── Chain row management ──────────────────────────────────────────────────

    def _all_labels(self) -> list:
        return [t["label"] for t in self._registry]

    def _make_row(self, label: str = "") -> ChainRow:
        row = ChainRow()
        row.set_values(self._all_labels())
        if label:
            row.set(label)
        elif self._all_labels():
            row.set(self._all_labels()[0])
        row.changed.connect(self._on_row_changed)
        row.add_after.connect(self._insert_row_after)
        row.remove.connect(self._remove_row)
        # Tooltip via combo
        row.combo.setToolTip(row.description(self._registry))
        row.changed.connect(
            lambda: row.combo.setToolTip(row.description(self._registry))
        )
        return row

    def _add_row(self, label: str = "") -> ChainRow:
        row = self._make_row(label)
        self.rows_layout.addWidget(row)
        self._rows.append(row)
        self._refresh_row_labels()
        return row

    def _insert_row_after(self, after_row: ChainRow):
        idx = self._rows.index(after_row)
        row = self._make_row()
        self.rows_layout.insertWidget(idx + 1, row)
        self._rows.insert(idx + 1, row)
        self._refresh_row_labels()
        self._on_row_changed()

    def _remove_row(self, row: ChainRow):
        if len(self._rows) <= 1:
            return
        idx = self._rows.index(row)
        self.rows_layout.removeWidget(row)
        row.deleteLater()
        self._rows.pop(idx)
        self._refresh_row_labels()
        self._on_row_changed()

    def _refresh_row_labels(self):
        only = len(self._rows) == 1
        for i, row in enumerate(self._rows):
            row.set_step_index(i)
            row.set_only_row(only)

    def _set_chain_rows(self, labels: list):
        for row in self._rows:
            self.rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []
        for lbl in labels:
            self._add_row(lbl)
        if not self._rows:
            self._add_row()
        self._refresh_row_labels()

    def _on_row_changed(self):
        if not self._rows:
            return
        first_label = self._rows[0].get()
        entry = next((t for t in self._registry if t["label"] == first_label), None)
        if entry and entry.get("is_chain"):
            self._load_chain(entry)
        self._update_stats()

    def _load_chain(self, chain_entry: dict):
        steps = chain_entry.get("steps", [])
        labels = []
        for step_name in steps:
            match = next(
                (t["label"] for t in self._registry
                 if t["name"] == step_name and not t.get("is_chain")), None
            )
            if match:
                labels.append(match)
            else:
                self._log(f"Chain step '{step_name}' not found", "warn")
        if labels:
            self._set_chain_rows(labels)
            self._log(
                f"Loaded chain '{chain_entry['name']}': " + " → ".join(labels), "chain"
            )

    def _get_all_chains_with_status(self) -> list:
        """Return all chains as (chain_entry, missing_steps) tuples."""
        valid_script_names = {
            t["name"] for t in self._registry
            if not t.get("is_chain") and t["fn"] is not None
        }
        result = []
        for t in self._registry:
            if not t.get("is_chain"):
                continue
            missing = [s for s in t.get("steps", []) if s not in valid_script_names]
            result.append((t, missing))
        return result

    def _refresh_chain_selector(self):
        """Update the chain button label to show count of available chains."""
        if not hasattr(self, "chain_btn"):
            return
        all_chains = self._get_all_chains_with_status()
        n_total = len(all_chains)
        n_valid = sum(1 for _, missing in all_chains if not missing)
        if n_total == 0:
            self.chain_btn.setText("⛓ No chains")
            self.chain_btn.setEnabled(False)
            self.chain_btn.setStyleSheet(
                f"color: {C['fg_dim']}; background-color: {C['bg_input']};"
                f"border-radius: 4px; padding: 5px 10px;"
            )
        else:
            self.chain_btn.setText(f"⛓ Load chain… ({n_valid}/{n_total})")
            self.chain_btn.setEnabled(True)
            self.chain_btn.setStyleSheet(
                f"color: {C['chain']}; background-color: {C['bg_input']};"
                f"border-radius: 4px; padding: 5px 10px;"
            )

    def _open_chain_picker(self):
        """Open a modal dialog listing all chains to load."""
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QScrollArea

        all_chains = self._get_all_chains_with_status()
        if not all_chains:
            self._log("No chains defined in transforms.ini", "warn")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Load Chain")
        dlg.setStyleSheet(build_stylesheet())
        dlg.setModal(True)
        dlg.setMinimumWidth(420)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header_lbl = QLabel("Select a chain to load:")
        header_lbl.setStyleSheet(
            f"color: {C['fg']}; font-weight: bold; font-size: 11px; padding-bottom: 4px;"
        )
        layout.addWidget(header_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background-color: {C['bg_mid']};")

        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {C['bg_mid']};")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(4, 4, 4, 4)
        scroll_layout.setSpacing(4)

        for chain, missing in all_chains:
            is_valid = len(missing) == 0
            row_widget = QWidget()
            row_widget.setStyleSheet(f"background-color: {C['bg_mid']};")
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            btn = QPushButton(chain["label"])
            btn.setEnabled(is_valid)
            btn.setFixedWidth(200)
            btn.setStyleSheet(
                f"color: {C['chain'] if is_valid else C['fg_dim']};"
                f"background-color: {C['bg_input']}; border-radius: 4px; padding: 4px 8px;"
                f"text-align: left;"
            )

            def _make_handler(c=chain):
                def _handler():
                    dlg.accept()
                    self._load_chain(c)
                    self._log(f"Chain loaded: {c['name']!r}", "chain")
                return _handler

            if is_valid:
                btn.clicked.connect(_make_handler())

            row_layout.addWidget(btn)

            desc = chain.get("description", "")
            if not is_valid:
                desc = f"⚠ missing: {', '.join(missing)}"
            if desc:
                desc_lbl = QLabel(desc)
                desc_lbl.setStyleSheet(
                    f"color: {C['warn'] if not is_valid else C['fg_dim']}; font-size: 10px;"
                )
                desc_lbl.setWordWrap(True)
                row_layout.addWidget(desc_lbl, stretch=1)

            scroll_layout.addWidget(row_widget)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(dlg.reject)
        cancel_btn.setFixedWidth(80)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        dlg.exec()

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
        if nchai: msg += f", {nchai} chain(s)"
        if bad:   msg += f", {bad} failed"
        self._log(msg, "info" if not bad else "warn")

        for row in self._rows:
            row.set_values(all_labels)

        if not self._rows:
            if preselect:
                p = Path(preselect).resolve()
                lbl = next(
                    (t["label"] for t in self._registry
                     if not t.get("is_chain") and Path(t["path"]).resolve() == p), None
                )
                self._add_row(lbl or (all_labels[0] if all_labels else ""))
            else:
                self._add_row(all_labels[0] if all_labels else "")
        else:
            for row, prev in zip(self._rows, prev_labels):
                if prev in all_labels:
                    row.set(prev)

        self._refresh_row_labels()
        self._refresh_chain_selector()
        self._update_stats()
        self._reseed_clipboard()

    def _get_active_steps(self) -> list:
        steps = []
        for row in self._rows:
            label = row.get()
            entry = next(
                (t for t in self._registry
                 if t["label"] == label and not t.get("is_chain")), None
            )
            if entry:
                steps.append(entry)
        return steps

    def _reload_all(self):
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

    def _log(self, message: str, tag: str = "info", transform_name: str = ""):
        self._db.log(message, tag, transform_name)
        self._log_signal.emit(message, tag)

    def _write_log(self, message: str, tag: str):
        cursor = self.log.textCursor()
        cursor.movePosition(QTextCursor.End)

        # Timestamp
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.setTextColor(QColor(C["fg_dim"]))
        cursor.insertText(f"[{ts}] ")

        # Message — truncated for display, full version in DB
        display_msg = message.split("\n")[0][:120]
        colour = TAG_COLOURS.get(tag, C["fg"])
        self.log.setTextColor(QColor(colour))
        cursor.insertText(f"{display_msg}\n")

        # Trim old lines
        doc = self.log.document()
        while doc.lineCount() > self.MAX_LOG_LINES:
            cursor2 = self.log.textCursor()
            cursor2.movePosition(QTextCursor.Start)
            cursor2.select(QTextCursor.LineUnderCursor)
            cursor2.removeSelectedText()
            cursor2.deleteChar()

        self.log.moveCursor(QTextCursor.End)

    def _open_log_browser(self):
        if self._log_browser is None or not self._log_browser.isVisible():
            self._log_browser = LogBrowserDialog(
                self._db, self._db.session_id, parent=self
            )
        self._log_browser.show()
        self._log_browser.raise_()
        self._log_browser._refresh()

    def _update_stats(self):
        steps = self._get_active_steps()
        if len(steps) == 1:
            chain_str = steps[0]["name"]
        elif len(steps) > 1:
            chain_str = " → ".join(s["name"] for s in steps)
        else:
            chain_str = "—"
        self.stats_label.setText(
            f"Transforms: {self.transform_count}  |  "
            f"Errors: {self.error_count}  |  "
            f"Chain: {chain_str}"
        )

    def _set_status(self, text: str):
        self.statusbar_label.setText(text)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _show_preview(self, text: str):
        self.preview_text.setPlainText(text)

    def _clear_preview(self):
        self.preview_text.clear()

    def _copy_preview(self):
        content = self.preview_text.toPlainText()
        if content:
            pyperclip.copy(content)
            if hasattr(self, '_worker'):
                self._worker.update_last(content)
            self._log("Preview content copied to clipboard", "ok")
            self._set_status("Preview copied to clipboard")

    def _toggle_dry_run(self):
        self.dry_run = not self.dry_run
        if self.dry_run:
            self.dryrun_btn.setObjectName("dryrun_active")
            self.dryrun_btn.setStyleSheet(
                f"background-color: #6d4c00; color: {C['warn']};"
                f"border-radius: 4px; padding: 5px 10px;"
            )
            self.status_dot.setObjectName("status_dot_dry")
            self.status_dot.setStyleSheet(f"color: {C['dry']}; font-size: 16px;")
            self.preview_frame.setVisible(True)
            self._log("Dry run ON — output goes to preview pane, not clipboard", "warn")
            self._set_status("DRY RUN active")
        else:
            self.dryrun_btn.setObjectName("")
            self.dryrun_btn.setStyleSheet("")
            dot_colour = C["ok"] if self.running else C["err"]
            self.status_dot.setStyleSheet(f"color: {dot_colour}; font-size: 16px;")
            self.preview_frame.setVisible(False)
            self._log("Dry run OFF — output goes to clipboard", "info")
            self._set_status("Running" if self.running else "Paused")

    # ── Chain execution ───────────────────────────────────────────────────────

    def _run_chain(self, clip_text: str, source: str = "clipboard"):
        steps = self._get_active_steps()
        if not steps:
            self._log("No transforms active — add steps to the chain", "warn")
            return

        is_chain    = len(steps) > 1
        chain_label = " → ".join(s["name"] for s in steps)

        if is_chain:
            self._log(f"▶ Chain [{chain_label}] via {source}", "chain", chain_label)
        else:
            self._log(f"▶ [{steps[0]['name']}] via {source}", "info", steps[0]['name'])

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
                # Also log the full result to DB if it looks like an error string
                if len(result) > 80 or "\n" in result:
                    self._log(f"   Full output: {result}", "info", step['name'])
                current = result
            except Exception as exc:
                self._log(f"  ✗ Error in [{step['name']}]: {exc}", "err", step['name'])
                self._log(traceback.format_exc(), "err", step['name'])
                self.error_count += 1
                self._update_stats()
                self._set_status(f"Error in [{step['name']}]: {exc}")
                return

        if self.dry_run:
            self._log(f"  🔍 Dry run — {len(current)} chars sent to preview pane", "warn")
            self._show_preview(current)
            self._set_status(
                f"Dry run OK [{chain_label}] @ {datetime.now().strftime('%H:%M:%S')}"
            )
        else:
            pyperclip.copy(current)
            if hasattr(self, '_worker'):
                self._worker.update_last(current)
            self._log(f"  ✓ {len(current)} chars written to clipboard", "ok")
            self._set_status(
                f"OK [{chain_label}] @ {datetime.now().strftime('%H:%M:%S')}"
            )

        self.transform_count += 1
        self._update_stats()

    # ── Polling ───────────────────────────────────────────────────────────────

    def _reseed_clipboard(self):
        try:
            if hasattr(self, '_worker'):
                self._worker.reseed()
        except Exception:
            pass

    def _start_polling(self):
        if self.hotkey:
            self.mode_label.setText(f"[hotkey: {self.hotkey}]")
        else:
            self.mode_label.setText(f"[polling every {self.poll_interval}s]")

        self.running = True
        self.status_dot.setStyleSheet(f"color: {C['ok']}; font-size: 16px;")
        self.toggle_btn.setText("⏸ Pause")

        if not self.hotkey:
            self._worker = ClipboardWorker(self.poll_interval)
            self._thread = QThread()
            self._worker.moveToThread(self._thread)
            self._worker.clip_changed.connect(
                lambda text: self._run_chain(text, source="clipboard change")
            )
            self._thread.started.connect(self._worker.run)
            self._thread.start()

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
        if hasattr(self, '_worker'):
            self._worker.set_active(self.running)
        if self.running:
            self.toggle_btn.setText("⏸ Pause")
            dot_colour = C["dry"] if self.dry_run else C["ok"]
            self.status_dot.setStyleSheet(f"color: {dot_colour}; font-size: 16px;")
            self._log("Resumed", "ok")
            self._set_status("Running")
            self._reseed_clipboard()
        else:
            self.toggle_btn.setText("▶ Resume")
            self.status_dot.setStyleSheet(f"color: {C['err']}; font-size: 16px;")
            self._log("Paused", "warn")
            self._set_status("Paused")

    def closeEvent(self, event):
        if KEYBOARD_AVAILABLE and self.hotkey:
            try:
                keyboard.remove_hotkey(self.hotkey)
            except Exception:
                pass
        if hasattr(self, '_worker'):
            self._worker.stop()
        if hasattr(self, '_thread'):
            self._thread.quit()
            self._thread.wait(2000)
        if hasattr(self, '_db'):
            self._db.stop()
        event.accept()


# ─── Entry point ──────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Clipboard transform middleware — PySide6 edition."
    )
    parser.add_argument("--script",     "-s", default=None)
    parser.add_argument("--transforms", "-t",
                        default=str(Path(__file__).parent / "transforms"))
    parser.add_argument("--hotkey",     "-k", default=None)
    parser.add_argument("--poll",       "-p", type=float, default=0.5)
    return parser.parse_args()


def main():
    args = parse_args()
    app  = QApplication(sys.argv)
    app.setApplicationName("ClipCommand")
    win  = ClipCommandWindow(
        transforms_folder=args.transforms,
        initial_script=args.script,
        poll_interval=args.poll,
        hotkey=args.hotkey,
    )
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
