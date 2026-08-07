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
import os
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
from transform_editor import TransformEditorDialog


# ── Colours (pyside6-ux design system) ─────────────────────────────────────────
C = {
    "bg_dark":   "#1F3864",   # NAVY — headings, primary buttons
    "bg_mid":    "#FFFFFF",   # BG_CARD — panel/card surfaces
    "bg_input":  "#1F3864",   # NAVY — default button fill
    "bg_log":    "#FFFFFF",   # BG_CARD — log surface
    "bg_main":   "#F5F6FA",   # BG_MAIN — page background
    "fg":        "#1A1A2E",   # TEXT_PRIMARY
    "fg_dim":    "#6B7280",   # TEXT_SECONDARY
    "fg_accent": "#4E79A7",   # ACCENT
    "fg_purple": "#4E79A7",   # ACCENT (chain highlight, no purple in palette)
    "fg_yellow": "#F59E0B",   # WARNING
    "ok":        "#22C55E",   # POSITIVE
    "err":       "#EF4444",   # NEGATIVE
    "warn":      "#F59E0B",   # WARNING
    "dry":       "#F59E0B",   # WARNING
    "chain":     "#4E79A7",   # ACCENT
    "border":    "#E5E7EB",   # BORDER
}

# Darker, text-safe variants of the semantic colours for use as small text on
# light backgrounds — the bright button/dot colours in C don't meet contrast
# requirements when used as foreground text on white/near-white surfaces.
TAG_COLOURS = {
    "ts":      C["fg_dim"],    # #6B7280 already AA-safe on light bg
    "ok":      "#15803D",      # darker POSITIVE
    "err":     "#B91C1C",      # darker NEGATIVE
    "info":    "#2C5282",      # darker ACCENT
    "warn":    "#B45309",      # darker WARNING
    "preview": "#2C5282",      # darker ACCENT
    "chain":   "#2C5282",      # darker ACCENT
}


# ─── Config manager ──────────────────────────────────────────────────────────
#
# Stores persistent settings (e.g. ANTHROPIC_API_KEY) in config.ini
# next to the executable. Loaded at startup and written when the user
# provides a value via the first-run dialog.

import configparser as _configparser

def _app_root() -> Path:
    """Directory the app runs from — the exe's folder when frozen (PyInstaller),
    otherwise clipcommand.py's folder. __file__ is unreliable once bundled."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).parent


def _config_path() -> Path:
    """config.ini lives next to the executable (or clipcommand.py in dev)."""
    return _app_root() / "config.ini"


def load_config() -> _configparser.ConfigParser:
    cfg = _configparser.ConfigParser()
    cfg.read(str(_config_path()))
    return cfg


def save_config(section: str, key: str, value: str):
    cfg = load_config()
    if section not in cfg:
        cfg[section] = {}
    cfg[section][key] = value
    with open(str(_config_path()), "w") as f:
        cfg.write(f)


def get_config_value(section: str, key: str, fallback: str = "") -> str:
    return load_config().get(section, key, fallback=fallback)


def ensure_api_key() -> str:
    """
    Return the Anthropic API key from environment or config.ini.
    Does NOT show a dialog — call prompt_for_api_key() for that.
    """
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        key = get_config_value("anthropic", "api_key", fallback="")
    if key:
        os.environ["ANTHROPIC_API_KEY"] = key  # make available to subprocesses
    return key


# ─── Stylesheet ───────────────────────────────────────────────────────────────

def build_stylesheet() -> str:
    return f"""
    QMainWindow, QDialog, QWidget {{
        background-color: {C["bg_main"]};
        color: {C["fg"]};
        font-family: "Segoe UI";
        font-size: 10pt;
    }}
    QPushButton {{
        background-color: {C["bg_dark"]};
        color: white;
        border: none;
        border-radius: 6px;
        padding: 6px 14px;
        font-size: 10pt;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: #2B4A8C;
    }}
    QPushButton:pressed {{
        background-color: #16294A;
    }}
    QPushButton:disabled {{
        background-color: #9CA3AF;
    }}
    QPushButton#dryrun_active {{
        background-color: {C["warn"]};
        color: white;
    }}
    QPushButton#add_btn {{
        background-color: {C["ok"]};
        color: white;
        font-weight: bold;
        padding: 3px 10px;
        border-radius: 6px;
    }}
    QPushButton#del_btn {{
        background-color: {C["err"]};
        color: white;
        font-weight: bold;
        padding: 3px 10px;
        border-radius: 6px;
    }}
    QPushButton#del_btn:disabled {{
        background-color: #9CA3AF;
    }}
    QComboBox {{
        background-color: white;
        color: {C["fg"]};
        border: 1px solid {C["border"]};
        border-radius: 6px;
        padding: 5px 10px;
        min-width: 220px;
        font-size: 10pt;
    }}
    QComboBox:hover, QComboBox:focus {{
        border-color: {C["bg_dark"]};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox::down-arrow {{
        width: 10px;
        height: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: white;
        color: {C["fg"]};
        selection-background-color: #E8EDF5;
        selection-color: {C["bg_dark"]};
        border: 1px solid {C["border"]};
        padding: 4px;
    }}
    QLineEdit {{
        background-color: white;
        color: {C["fg"]};
        border: 1px solid {C["border"]};
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 10pt;
    }}
    QLineEdit:focus {{
        border-color: {C["bg_dark"]};
    }}
    QCheckBox {{
        color: {C["fg_dim"]};
    }}
    QTextEdit {{
        background-color: {C["bg_log"]};
        color: {C["fg"]};
        border: 1px solid {C["border"]};
        border-radius: 8px;
        font-family: "Cascadia Code", "Consolas", monospace;
        font-size: 9pt;
    }}
    QTextEdit#preview_text {{
        background-color: #F9FAFB;
        color: {C["fg"]};
        border: 1px solid {C["border"]};
    }}
    QLabel#status_dot_ok  {{ color: {C["ok"]};  font-size: 16px; }}
    QLabel#status_dot_err {{ color: {C["err"]}; font-size: 16px; }}
    QLabel#status_dot_dry {{ color: {C["dry"]}; font-size: 16px; }}
    QLabel#title_label    {{ color: {C["bg_dark"]}; font-size: 13pt; font-weight: 600; }}
    QLabel#mode_label     {{ color: {C["fg_accent"]}; font-size: 9pt; }}
    QLabel#step_label     {{ color: {C["fg_dim"]}; font-size: 9pt; }}
    QLabel#stats_label    {{ color: {C["fg_dim"]}; font-size: 9pt; padding: 2px 8px; }}
    QLabel#statusbar      {{ color: {C["fg_dim"]}; font-size: 9pt; padding: 4px 10px;
                             background-color: {C["bg_main"]}; border-top: 1px solid {C["border"]}; }}
    QLabel#preview_header {{ color: #B45309; font-size: 10pt; font-weight: 600; }}
    QFrame#chain_panel    {{ background-color: {C["bg_mid"]}; border: 1px solid {C["border"]}; border-radius: 10px; }}
    QFrame#stats_bar      {{ background-color: transparent; border: none; }}
    QFrame#preview_frame  {{ background-color: {C["bg_mid"]}; border: 1px solid {C["border"]}; border-radius: 10px; }}
    QFrame#separator      {{ color: {C["border"]}; }}
    QScrollBar:vertical {{
        background: {C["bg_main"]};
        width: 10px;
    }}
    QScrollBar::handle:vertical {{
        background: #C9CED8;
        border-radius: 5px;
        min-height: 20px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    """


# ─── INI loader ───────────────────────────────────────────────────────────────

def _ini_candidates(folder: str) -> list:
    return [
        Path(folder) / "transforms.ini",
        Path(folder).parent / "transforms.ini",
    ]


def resolve_ini_path(folder: str) -> Path:
    """Path of the transforms.ini in use (first that exists, else the default
    location alongside the transforms folder for a freshly-created one)."""
    candidates = _ini_candidates(folder)
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]


def load_ini(folder: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    for ini_path in _ini_candidates(folder):
        if ini_path.exists():
            cfg.read(ini_path, encoding="utf-8-sig")
            break
    return cfg


def upsert_chain(folder: str, name: str, description: str, steps: list) -> Path:
    """Write (or replace) a [chain:name] section in transforms.ini using a
    text-based edit so existing comments and formatting are preserved."""
    ini_path = resolve_ini_path(folder)
    header = f"[chain:{name}]"
    block_lines = [header]
    if description:
        block_lines.append(f"description = {description}")
    block_lines.append(f"steps       = {', '.join(steps)}")
    block = "\n".join(block_lines)

    text = ini_path.read_text(encoding="utf-8-sig") if ini_path.exists() else ""
    lines = text.splitlines()

    # Locate an existing section with this exact header
    start = next((i for i, ln in enumerate(lines)
                  if ln.strip() == header), None)
    if start is not None:
        # Section runs until the next "[section]" line or EOF
        end = len(lines)
        for j in range(start + 1, len(lines)):
            if lines[j].lstrip().startswith("["):
                end = j
                break
        new_lines = lines[:start] + block.splitlines() + lines[end:]
        new_text = "\n".join(new_lines).rstrip() + "\n"
    else:
        sep = "" if text.endswith("\n\n") or not text else \
              ("\n" if text.endswith("\n") else "\n\n")
        new_text = text + sep + "\n" + block + "\n"

    ini_path.write_text(new_text, encoding="utf-8")
    return ini_path


def delete_chain(folder: str, name: str) -> bool:
    """Remove a [chain:name] section from transforms.ini (text-based so other
    sections and comments are untouched). Returns True if a section was removed."""
    ini_path = resolve_ini_path(folder)
    if not ini_path.exists():
        return False
    header = f"[chain:{name}]"
    lines = ini_path.read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, ln in enumerate(lines) if ln.strip() == header), None)
    if start is None:
        return False
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].lstrip().startswith("["):
            end = j
            break
    del lines[start:end]
    new_text = "\n".join(lines).rstrip() + "\n"
    ini_path.write_text(new_text, encoding="utf-8")
    return True


def get_transform_overrides(cfg, stem: str) -> dict:
    section = f"transform:{stem}"
    if not cfg.has_section(section):
        return {}
    # configparser lowercases option names, but transforms expose their settings
    # as ALL_CAPS constants — without this the setattr in load_transform creates
    # a new lowercase attribute and the real constant is never overridden.
    return {key.upper(): value for key, value in cfg[section].items()}


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

def clip_write(text: str, retries: int = 6, delay: float = 0.04) -> None:
    """pyperclip.copy with retries. On Windows the clipboard is an exclusive
    resource; another app briefly holding it makes OpenClipboard fail. A short
    retry loop rides out that contention instead of dropping the write."""
    last_exc = None
    for attempt in range(retries):
        try:
            pyperclip.copy(text)
            return
        except Exception as exc:      # PyperclipWindowsException et al.
            last_exc = exc
            time.sleep(delay)
    raise last_exc if last_exc else RuntimeError("clipboard write failed")


def clip_read(retries: int = 3, delay: float = 0.04) -> str:
    """pyperclip.paste with a couple of retries for transient clipboard locks."""
    last_exc = None
    for attempt in range(retries):
        try:
            return pyperclip.paste()
        except Exception as exc:
            last_exc = exc
            time.sleep(delay)
    raise last_exc if last_exc else RuntimeError("clipboard read failed")


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
            self._last = clip_read()
        except Exception:
            pass

    def set_active(self, active: bool):
        self._active = active

    def set_busy(self, busy: bool):
        self._busy = busy

    def stop(self):
        self._running = False

    def run(self):
        self._busy = False
        self.reseed()
        while self._running:
            if self._active and not self._busy:
                try:
                    current = clip_read()
                    if current and current != self._last:
                        self._last = current
                        # Block further polling until _run_chain (GUI thread)
                        # finishes and releases busy — prevents the transform's
                        # own write-back from being re-detected as a new change.
                        self._busy = True
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
        # Scoped selector so the row's white background does NOT bleed into its
        # child QComboBox / +/- buttons (which have their own styling).
        self.setObjectName("chain_row")
        self.setStyleSheet(f"#chain_row {{ background-color: {C['bg_mid']}; border: none; }}")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(6)

        self.step_label = QLabel("Step 1:")
        self.step_label.setObjectName("step_label")
        self.step_label.setFixedWidth(55)
        self.step_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.step_label)

        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # currentTextChanged passes a str; `changed` is a no-arg signal, so drop
        # the argument (connecting .emit directly raises TypeError and the
        # change is never propagated).
        self.combo.currentTextChanged.connect(lambda _=None: self.changed.emit())
        layout.addWidget(self.combo)

        self.add_btn = QPushButton("+")
        self.add_btn.setObjectName("add_btn")
        self.add_btn.setFixedWidth(28)
        self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_btn.setToolTip("Insert step after this one")
        self.add_btn.clicked.connect(lambda: self.add_after.emit(self))
        layout.addWidget(self.add_btn)

        self.del_btn = QPushButton("−")
        self.del_btn.setObjectName("del_btn")
        self.del_btn.setFixedWidth(28)
        self.del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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
    _log_signal   = Signal(str, str)        # message, tag
    _run_signal   = Signal(str, str)        # clip_text, source — marshals chain
                                            # execution onto the GUI thread

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
        self._editor           = None
        # Name/description of the most recently loaded chain — pre-fills the
        # "Save as chain" dialog so an edit-and-resave updates it in place.
        self._loaded_chain_name = ""
        self._loaded_chain_desc = ""

        # SQLite logger — DB lives next to the executable (or clipcommand.py in dev)
        self._db = DBLogger(str(_app_root()))

        # Load API key from config.ini if not already in environment
        ensure_api_key()

        self._log_signal.connect(self._write_log)
        # Bound-method slot on this main-thread QObject → a queued connection
        # when emitted from the poll/hotkey threads, so _run_chain (and all its
        # GUI calls) always executes on the GUI thread.
        self._run_signal.connect(self._run_chain)

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
        # NOTE: container backgrounds MUST use a scoped #objectName selector.
        # A bare "background-color: X" bleeds into child buttons/combos and
        # overrides their own navy/white styling (Qt stylesheet inheritance).
        header = QWidget()
        header.setObjectName("app_header")
        header.setStyleSheet(f"#app_header {{ background-color: {C['bg_main']}; }}")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 14, 16, 10)
        h_layout.setSpacing(8)

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

        edit_btn = QPushButton("✎ Transforms")
        edit_btn.clicked.connect(self._open_transform_editor)
        h_layout.addWidget(edit_btn)

        log_btn = QPushButton("📋 Log")
        log_btn.clicked.connect(self._open_log_browser)
        h_layout.addWidget(log_btn)

        settings_btn = QPushButton("⚙ Settings")
        settings_btn.clicked.connect(self._open_settings)
        h_layout.addWidget(settings_btn)

        reload_btn = QPushButton("⟳ Reload")
        reload_btn.clicked.connect(self._reload_all)
        h_layout.addWidget(reload_btn)

        self.toggle_btn = QPushButton("⏸ Pause")
        self.toggle_btn.clicked.connect(self._toggle)
        h_layout.addWidget(self.toggle_btn)

        for btn in (self.dryrun_btn, edit_btn, log_btn, settings_btn, reload_btn, self.toggle_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        main_layout.addWidget(header)

        # Body wrapper so cards have breathing room against BG_MAIN
        body = QWidget()
        body.setObjectName("app_body")
        body.setStyleSheet(f"#app_body {{ background-color: {C['bg_main']}; }}")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(16, 0, 16, 10)
        body_layout.setSpacing(10)
        main_layout.addWidget(body, stretch=1)

        # ── Chain panel ───────────────────────────────────────────────────────
        self.chain_panel = QFrame()
        self.chain_panel.setObjectName("chain_panel")
        self.chain_panel.setFrameShape(QFrame.NoFrame)
        cp_layout = QVBoxLayout(self.chain_panel)
        cp_layout.setContentsMargins(0, 8, 0, 8)
        cp_layout.setSpacing(4)

        rescan_bar = QWidget()
        rescan_bar.setObjectName("rescan_bar")
        rescan_bar.setStyleSheet(f"#rescan_bar {{ background-color: {C['bg_mid']}; border: none; }}")
        rb_layout = QHBoxLayout(rescan_bar)
        rb_layout.setContentsMargins(12, 0, 12, 4)

        self.chain_btn = QPushButton("⛓ Load chain…")
        self.chain_btn.setStyleSheet(
            f"color: white; background-color: {C['chain']};"
            f"border-radius: 6px; padding: 6px 14px; font-weight: 600;"
        )
        self.chain_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chain_btn.clicked.connect(self._open_chain_picker)
        rb_layout.addWidget(self.chain_btn)

        rb_layout.addStretch()
        save_chain_btn = QPushButton("💾 Save as chain…")
        save_chain_btn.setStyleSheet(
            f"color: white; background-color: {C['fg_accent']};"
            f"border-radius: 6px; padding: 6px 14px; font-weight: 600;"
        )
        save_chain_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_chain_btn.setToolTip("Save the current steps as a named chain in transforms.ini")
        save_chain_btn.clicked.connect(self._save_as_chain)
        rb_layout.addWidget(save_chain_btn)

        rescan_btn = QPushButton("⟳ Rescan folder")
        rescan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        rescan_btn.clicked.connect(lambda: self._refresh_transforms())
        rb_layout.addWidget(rescan_btn)
        cp_layout.addWidget(rescan_bar)

        self.rows_widget = QWidget()
        self.rows_widget.setObjectName("rows_widget")
        self.rows_widget.setStyleSheet(f"#rows_widget {{ background-color: {C['bg_mid']}; border: none; }}")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(12, 0, 12, 4)
        self.rows_layout.setSpacing(4)
        cp_layout.addWidget(self.rows_widget)

        body_layout.addWidget(self.chain_panel)

        # ── Stats bar ─────────────────────────────────────────────────────────
        stats_bar = QFrame()
        stats_bar.setObjectName("stats_bar")
        sb_layout = QHBoxLayout(stats_bar)
        sb_layout.setContentsMargins(4, 0, 4, 0)
        self.stats_label = QLabel("Transforms: 0  |  Errors: 0  |  Chain: —")
        self.stats_label.setObjectName("stats_label")
        sb_layout.addWidget(self.stats_label)
        body_layout.addWidget(stats_bar)

        # ── Log ───────────────────────────────────────────────────────────────
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setObjectName("log")
        body_layout.addWidget(self.log, stretch=1)

        # ── Preview pane (hidden until dry run) ───────────────────────────────
        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("preview_frame")
        self.preview_frame.setVisible(False)
        pf_layout = QVBoxLayout(self.preview_frame)
        pf_layout.setContentsMargins(12, 10, 12, 12)
        pf_layout.setSpacing(6)

        ph_widget = QWidget()
        ph_layout = QHBoxLayout(ph_widget)
        ph_layout.setContentsMargins(0, 0, 0, 0)
        preview_header_lbl = QLabel("🔍 Dry Run Preview")
        preview_header_lbl.setObjectName("preview_header")
        ph_layout.addWidget(preview_header_lbl)
        ph_layout.addStretch()
        clear_btn = QPushButton("✕ Clear")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_preview)
        ph_layout.addWidget(clear_btn)
        copy_btn = QPushButton("📋 Copy to clipboard")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_preview)
        ph_layout.addWidget(copy_btn)
        pf_layout.addWidget(ph_widget)

        self.preview_text = QTextEdit()
        self.preview_text.setObjectName("preview_text")
        self.preview_text.setReadOnly(True)
        self.preview_text.setFixedHeight(140)
        pf_layout.addWidget(self.preview_text)

        body_layout.addWidget(self.preview_frame)

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
            self._loaded_chain_name = chain_entry.get("name", "")
            self._loaded_chain_desc = chain_entry.get("description", "")
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
                f"color: white; background-color: #9CA3AF;"
                f"border-radius: 6px; padding: 6px 14px; font-weight: 600;"
            )
        else:
            self.chain_btn.setText(f"⛓ Load chain… ({n_valid}/{n_total})")
            self.chain_btn.setEnabled(True)
            self.chain_btn.setStyleSheet(
                f"color: white; background-color: {C['chain']};"
                f"border-radius: 6px; padding: 6px 14px; font-weight: 600;"
            )

    def _open_chain_picker(self):
        """Open a modal dialog listing all chains — load, or delete each."""
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QMessageBox
        )

        if not self._get_all_chains_with_status():
            self._log("No chains defined in transforms.ini", "warn")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle("Chains")
        dlg.setStyleSheet(build_stylesheet())
        dlg.setModal(True)
        dlg.setMinimumWidth(460)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header_lbl = QLabel("Click a chain to load it, or 🗑 to delete:")
        header_lbl.setStyleSheet(
            f"color: {C['bg_dark']}; font-weight: 600; font-size: 11pt; padding-bottom: 4px;"
        )
        layout.addWidget(header_lbl)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"background-color: {C['bg_main']}; border: none;")

        scroll_content = QWidget()
        scroll_content.setStyleSheet(f"background-color: {C['bg_main']};")
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(4, 4, 4, 4)
        scroll_layout.setSpacing(4)
        scroll.setWidget(scroll_content)

        def _clear_layout():
            while scroll_layout.count():
                item = scroll_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()

        def _delete(chain):
            resp = QMessageBox.question(
                dlg, "Delete chain",
                f"Delete chain '{chain['name']}'?\nThis edits transforms.ini and cannot be undone.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return
            try:
                removed = delete_chain(self.transforms_folder, chain["name"])
            except Exception as exc:
                QMessageBox.warning(dlg, "Delete failed", str(exc))
                return
            if removed:
                self._log(f"Deleted chain '{chain['name']}'", "warn")
                self._refresh_transforms()
                _populate()
            else:
                QMessageBox.information(
                    dlg, "Not found",
                    f"Chain '{chain['name']}' was not found in transforms.ini."
                )

        def _load(chain):
            dlg.accept()
            self._load_chain(chain)
            self._log(f"Chain loaded: {chain['name']!r}", "chain")

        def _populate():
            _clear_layout()
            all_chains = self._get_all_chains_with_status()
            if not all_chains:
                empty = QLabel("No chains left. Build steps and use “Save as chain…”.")
                empty.setStyleSheet(f"color: {C['fg_dim']}; font-size: 10pt; padding: 12px;")
                scroll_layout.addWidget(empty)
                scroll_layout.addStretch()
                return
            for chain, missing in all_chains:
                is_valid = len(missing) == 0
                row_widget = QFrame()
                row_widget.setObjectName("card")
                row_widget.setStyleSheet(
                    f"QFrame#card {{ background-color: {C['bg_mid']}; border: 1px solid {C['border']}; border-radius: 8px; }}"
                )
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(10, 8, 10, 8)
                row_layout.setSpacing(8)

                btn = QPushButton(chain["label"])
                btn.setEnabled(is_valid)
                btn.setFixedWidth(200)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setStyleSheet(
                    f"color: white; background-color: {C['chain'] if is_valid else '#9CA3AF'};"
                    f"border-radius: 6px; padding: 6px 10px; text-align: left; font-weight: 600;"
                )
                if is_valid:
                    btn.clicked.connect(lambda _=False, c=chain: _load(c))
                row_layout.addWidget(btn)

                desc = chain.get("description", "")
                if not is_valid:
                    desc = f"⚠ missing: {', '.join(missing)}"
                desc_lbl = QLabel(desc or "")
                desc_lbl.setStyleSheet(
                    f"color: {'#B45309' if not is_valid else C['fg_dim']}; font-size: 10px;"
                )
                desc_lbl.setWordWrap(True)
                row_layout.addWidget(desc_lbl, stretch=1)

                del_btn = QPushButton("🗑")
                del_btn.setFixedWidth(36)
                del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
                del_btn.setToolTip(f"Delete chain '{chain['name']}'")
                del_btn.setStyleSheet(
                    f"color: white; background-color: {C['err']};"
                    f"border-radius: 6px; padding: 6px 8px; font-weight: 600;"
                )
                del_btn.clicked.connect(lambda _=False, c=chain: _delete(c))
                row_layout.addWidget(del_btn)

                scroll_layout.addWidget(row_widget)
            scroll_layout.addStretch()

        _populate()
        layout.addWidget(scroll)

        cancel_btn = QPushButton("Close")
        cancel_btn.setStyleSheet(
            f"background-color: transparent; color: {C['fg_dim']};"
            f"border: 1px solid {C['border']}; border-radius: 6px; padding: 6px 16px; font-weight: 500;"
        )
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
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

    def _open_settings(self):
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QLineEdit, QPushButton, QFormLayout, QCheckBox
        )

        dlg = QDialog(self)
        dlg.setWindowTitle("ClipCommand — Settings")
        dlg.setStyleSheet(build_stylesheet())
        dlg.setModal(True)
        dlg.setMinimumWidth(480)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Title
        title = QLabel("Settings")
        title.setStyleSheet(f"color: {C['bg_dark']}; font-size: 13pt; font-weight: 600;")
        layout.addWidget(title)

        # Form
        form = QFormLayout()
        form.setSpacing(8)

        # API key field
        current_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self._api_key_input = QLineEdit()
        self._api_key_input.setPlaceholderText("sk-ant-...")
        self._api_key_input.setText(current_key)
        self._api_key_input.setEchoMode(QLineEdit.Password)

        # Show/hide toggle
        show_cb = QCheckBox("Show")
        show_cb.setStyleSheet(f"color: {C['fg_dim']};")
        show_cb.toggled.connect(
            lambda checked: self._api_key_input.setEchoMode(
                QLineEdit.Normal if checked else QLineEdit.Password
            )
        )

        key_row = QHBoxLayout()
        key_row.addWidget(self._api_key_input)
        key_row.addWidget(show_cb)

        form.addRow(QLabel("Anthropic API Key:"), key_row)

        # Config file path (info only)
        cfg_path_lbl = QLabel(str(_config_path()))
        cfg_path_lbl.setStyleSheet(f"color: {C['fg_dim']}; font-size: 9pt;")
        cfg_path_lbl.setWordWrap(True)
        form.addRow(QLabel("Config file:"), cfg_path_lbl)

        layout.addLayout(form)

        # Note
        note = QLabel(
            "The API key is stored in plain text in config.ini next to the executable. "
            "Required only for AI-powered transforms (e.g. aidinsight_email_reply)."
        )
        note.setStyleSheet(f"color: {C['fg_dim']}; font-size: 9pt;")
        note.setWordWrap(True)
        layout.addWidget(note)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            f"background-color: transparent; color: {C['fg_dim']};"
            f"border: 1px solid {C['border']}; border-radius: 6px; padding: 6px 16px; font-weight: 500;"
        )
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        def _save():
            key = self._api_key_input.text().strip()
            if key:
                save_config("anthropic", "api_key", key)
                os.environ["ANTHROPIC_API_KEY"] = key
                self._log("Anthropic API key saved to config.ini", "ok")
            else:
                # Clear it
                save_config("anthropic", "api_key", "")
                os.environ.pop("ANTHROPIC_API_KEY", None)
                self._log("Anthropic API key cleared", "warn")
            dlg.accept()

        save_btn.clicked.connect(_save)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        dlg.exec()

    def _open_log_browser(self):
        if self._log_browser is None or not self._log_browser.isVisible():
            self._log_browser = LogBrowserDialog(
                self._db, self._db.session_id, parent=self
            )
        self._log_browser.show()
        self._log_browser.raise_()
        self._log_browser._refresh()

    def _open_transform_editor(self):
        if getattr(self, "_editor", None) is None or not self._editor.isVisible():
            self._editor = TransformEditorDialog(
                self.transforms_folder, stylesheet=build_stylesheet(), parent=self
            )
            # Rescan the folder whenever the editor writes/deletes a file
            self._editor.saved.connect(lambda: self._refresh_transforms())
        self._editor.show()
        self._editor.raise_()
        self._editor.activateWindow()

    def _save_as_chain(self):
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QMessageBox
        )

        steps = self._get_active_steps()
        if len(steps) < 2:
            QMessageBox.information(
                self, "Save as chain",
                "Add at least two steps before saving a chain."
            )
            return
        step_names = [s["name"] for s in steps]

        dlg = QDialog(self)
        dlg.setWindowTitle("Save as chain")
        dlg.setStyleSheet(build_stylesheet())
        dlg.setModal(True)
        dlg.setMinimumWidth(460)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Save current steps as a chain")
        title.setStyleSheet(f"color: {C['bg_dark']}; font-size: 13pt; font-weight: 600;")
        layout.addWidget(title)

        # Editing an existing chain? Pre-fill from the last loaded chain.
        editing = bool(self._loaded_chain_name)
        if editing:
            hint = QLabel(f"Editing chain “{self._loaded_chain_name}” — change the name to save a copy.")
            hint.setStyleSheet(f"color: {C['fg_dim']}; font-size: 9pt;")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(8)

        name_edit = QLineEdit(self._loaded_chain_name)
        name_edit.setPlaceholderText("e.g. clean_and_convert")
        form.addRow(QLabel("Name:"), name_edit)

        desc_edit = QLineEdit(self._loaded_chain_desc)
        desc_edit.setPlaceholderText("Optional description shown in the picker")
        form.addRow(QLabel("Description:"), desc_edit)

        layout.addLayout(form)

        steps_lbl = QLabel("Steps:  " + "  →  ".join(step_names))
        steps_lbl.setStyleSheet(f"color: {C['fg_accent']}; font-size: 9pt;")
        steps_lbl.setWordWrap(True)
        layout.addWidget(steps_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet(
            f"background-color: transparent; color: {C['fg_dim']};"
            f"border: 1px solid {C['border']}; border-radius: 6px; padding: 6px 16px; font-weight: 500;"
        )
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(dlg.reject)
        btn_row.addWidget(cancel_btn)
        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        if dlg.exec() != QDialog.Accepted:
            return

        raw = name_edit.text().strip()
        if not raw:
            QMessageBox.warning(self, "Save as chain", "A chain name is required.")
            return
        chain_name = raw.lower().replace(" ", "_")
        desc = desc_edit.text().strip()

        # Warn if overwriting a DIFFERENT existing chain than the one being edited
        existing = {t["name"] for t in self._registry if t.get("is_chain")}
        if chain_name in existing and chain_name != self._loaded_chain_name:
            resp = QMessageBox.question(
                self, "Overwrite chain?",
                f"A chain named '{chain_name}' already exists. Overwrite it?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return

        try:
            ini_path = upsert_chain(
                self.transforms_folder, chain_name, desc, step_names
            )
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", f"Could not write chain:\n{exc}")
            self._log(f"Save chain failed: {exc}", "err")
            return

        self._loaded_chain_name = chain_name
        self._loaded_chain_desc = desc
        self._log(
            f"Saved chain '{chain_name}' → {', '.join(step_names)}  [{ini_path.name}]",
            "chain",
        )
        self._set_status(f"Chain '{chain_name}' saved")
        self._refresh_transforms()

    def _update_stats(self):
        steps = self._get_active_steps()
        if len(steps) == 1:
            chain_str = steps[0]["name"]
        elif len(steps) > 1:
            chain_str = " → ".join(s["name"] for s in steps)
        else:
            chain_str = "—"
        self.stats_label.setText(
            f"Runs: {self.transform_count}  |  "
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
            try:
                clip_write(content)
            except Exception as exc:
                self._log(f"Clipboard write failed: {exc}", "err")
                self._set_status("Clipboard busy — copy failed, try again")
                return
            if hasattr(self, '_worker'):
                self._worker.update_last(content)
            self._log("Preview content copied to clipboard", "ok")
            self._set_status("Preview copied to clipboard")

    def _toggle_dry_run(self):
        self.dry_run = not self.dry_run
        if self.dry_run:
            self.dryrun_btn.setObjectName("dryrun_active")
            self.dryrun_btn.setStyleSheet(
                f"background-color: {C['warn']}; color: {C['fg']};"
                f"border-radius: 6px; padding: 6px 14px; font-weight: 600;"
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

    def _set_busy(self, busy: bool, label: str = ""):
        if hasattr(self, "_worker"):
            self._worker.set_busy(busy)
        if busy:
            self.status_dot.setStyleSheet(f"color: {C['fg_yellow']}; font-size: 16px;")
            self._set_status(f"⏳ Working: {label}…")
        else:
            dot_colour = C["dry"] if self.dry_run else (C["ok"] if self.running else C["err"])
            self.status_dot.setStyleSheet(f"color: {dot_colour}; font-size: 16px;")

    def _run_chain(self, clip_text: str, source: str = "clipboard"):
        # Always runs on the GUI thread (via _run_signal). The whole body is
        # wrapped so busy is ALWAYS released — the worker sets busy=True before
        # emitting, so any early return here must still clear it or polling stalls.
        try:
            steps = self._get_active_steps()
            if not steps:
                self._log("No transforms active — add steps to the chain", "warn")
                return

            is_chain    = len(steps) > 1
            chain_label = " → ".join(s["name"] for s in steps)

            # Show working indicator (worker is already blocked)
            self._set_busy(True, chain_label)

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
                    self._set_status(f"⏳ [{i+1}/{len(steps)}] {step['name']}…")
                else:
                    self._set_status(f"⏳ {step['name']}…")
                self._log(f"   In:  {preview_in!r}{'…' if len(current) > 80 else ''}", "preview")

                try:
                    result = step["fn"](current)
                    if not isinstance(result, str):
                        result = str(result)
                    preview_out = result[:80].replace("\n", "↵")
                    self._log(f"   Out: {preview_out!r}{'…' if len(result) > 80 else ''}", "ok")
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
                try:
                    clip_write(current)
                except Exception as exc:
                    self._log(f"  ✗ Clipboard write failed after retries: {exc}", "err")
                    self._set_status("Clipboard busy — write failed, copy again")
                    self.error_count += 1
                    self._update_stats()
                    return
                if hasattr(self, '_worker'):
                    self._worker.update_last(current)
                self._log(f"  ✓ {len(current)} chars written to clipboard", "ok")
                self._set_status(
                    f"OK [{chain_label}] @ {datetime.now().strftime('%H:%M:%S')}"
                )

            self.transform_count += 1
            self._update_stats()

        finally:
            # No label arg — chain_label may be unset if we returned on "no steps"
            self._set_busy(False)

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
            # Emit-only lambda runs on the worker thread but merely re-emits a
            # signal; the actual work (_run_chain) is delivered to the GUI thread.
            self._worker.clip_changed.connect(
                lambda text: self._run_signal.emit(text, "clipboard change")
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
            # Runs on the 'keyboard' library's listener thread — must NOT touch
            # the GUI or run the chain directly. Marshal to the GUI thread.
            try:
                clip = clip_read()
            except Exception as exc:
                self._log(f"Hotkey error: {exc}", "err")
                return
            if clip:
                self._run_signal.emit(clip, f"hotkey ({self.hotkey})")
            else:
                self._log("Hotkey pressed but clipboard is empty", "warn")

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
                        default=str(_app_root() / "transforms"))
    parser.add_argument("--hotkey",     "-k", default=None)
    parser.add_argument("--poll",       "-p", type=float, default=0.5)
    return parser.parse_args()


def main():
    args = parse_args()
    app  = QApplication(sys.argv)
    app.setStyle("Fusion")  # windowsvista blends QSS button colours into pale pastels
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