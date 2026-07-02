"""
transform_editor.py — lightweight built-in editor for ClipCommand transforms.

Not a full IDE — just enough to browse the transform scripts, fix typos, add a
new stub, or delete one, with live Python syntax highlighting and an inline
syntax-error check. Heavy editing is still expected to happen in Neovim/Sublime.

Uses a native QSyntaxHighlighter (no Pygments dependency) so highlighting is
live as you type.
"""

import ast
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QPlainTextEdit, QSplitter, QWidget, QMessageBox,
    QInputDialog, QLineEdit,
)
from PySide6.QtGui import (
    QSyntaxHighlighter, QTextCharFormat, QColor, QFont, QTextDocument,
)
from PySide6.QtCore import Qt, QRegularExpression, Signal

# ── Palette (mirrors clipcommand.py / log_browser.py — kept local to avoid a
#    circular import between clipcommand and this module) ──────────────────────
C = {
    "bg_main":  "#F5F6FA",
    "bg_card":  "#FFFFFF",
    "navy":     "#1F3864",
    "accent":   "#4E79A7",
    "fg":       "#1A1A2E",
    "fg_dim":   "#6B7280",
    "ok":       "#15803D",
    "err":      "#B91C1C",
    "border":   "#E5E7EB",
}

# ── Code colours (tuned for readability on a white editor background) ─────────
CODE = {
    "keyword":   "#0033B3",   # def, return, if, import, ...
    "builtin":   "#00627A",   # str, len, print, self, ...
    "string":    "#067D17",   # "..." '...' """..."""
    "comment":   "#8C8C8C",   # # ...
    "number":    "#1750EB",   # 42, 3.14
    "decorator": "#9E880D",   # @staticmethod
    "defname":   "#7A3E9D",   # the name after def/class
}

TEMPLATE = '''#!/usr/bin/env python3
"""
One-line description shown in the transform picker.
"""


def transform(text: str) -> str:
    # TODO: implement
    return text
'''


class PythonHighlighter(QSyntaxHighlighter):
    """Minimal regex-based Python highlighter for a light background."""

    KEYWORDS = [
        "and", "as", "assert", "async", "await", "break", "class", "continue",
        "def", "del", "elif", "else", "except", "finally", "for", "from",
        "global", "if", "import", "in", "is", "lambda", "nonlocal", "not",
        "or", "pass", "raise", "return", "try", "while", "with", "yield",
        "True", "False", "None",
    ]
    BUILTINS = [
        "abs", "bool", "bytes", "dict", "enumerate", "float", "format", "int",
        "isinstance", "len", "list", "map", "max", "min", "open", "print",
        "range", "repr", "reversed", "round", "set", "sorted", "str", "sum",
        "tuple", "type", "zip", "self", "cls",
    ]

    def __init__(self, document: QTextDocument):
        super().__init__(document)
        self._rules = []

        def fmt(colour, bold=False, italic=False):
            f = QTextCharFormat()
            f.setForeground(QColor(colour))
            if bold:
                f.setFontWeight(QFont.Weight.Bold)
            if italic:
                f.setFontItalic(True)
            return f

        kw_fmt = fmt(CODE["keyword"], bold=True)
        for w in self.KEYWORDS:
            self._rules.append((QRegularExpression(rf"\b{w}\b"), kw_fmt))

        bi_fmt = fmt(CODE["builtin"])
        for w in self.BUILTINS:
            self._rules.append((QRegularExpression(rf"\b{w}\b"), bi_fmt))

        # Numbers
        self._rules.append((
            QRegularExpression(r"\b[0-9]+\.?[0-9]*\b"), fmt(CODE["number"])
        ))
        # Decorators
        self._rules.append((
            QRegularExpression(r"^\s*@\w+"), fmt(CODE["decorator"])
        ))
        # def / class name
        self._rules.append((
            QRegularExpression(r"\b(?:def|class)\s+(\w+)"),
            fmt(CODE["defname"], bold=True),
        ))
        # Single-line strings (single and double quoted)
        self._str_fmt = fmt(CODE["string"])
        self._rules.append((
            QRegularExpression(r"'[^'\\]*(?:\\.[^'\\]*)*'"), self._str_fmt
        ))
        self._rules.append((
            QRegularExpression(r'"[^"\\]*(?:\\.[^"\\]*)*"'), self._str_fmt
        ))
        # Comments (last so they win over anything above)
        self._comment_fmt = fmt(CODE["comment"], italic=True)
        self._rules.append((QRegularExpression(r"#[^\n]*"), self._comment_fmt))

        # Triple-quoted string delimiters for multi-line handling
        self._tri_double = QRegularExpression(r'"""')
        self._tri_single = QRegularExpression(r"'''")

    def highlightBlock(self, text: str):
        for rule, fmt in self._rules:
            it = rule.globalMatch(text)
            while it.hasNext():
                m = it.next()
                # For def/class capture group, colour only the name
                if m.lastCapturedIndex() >= 1:
                    self.setFormat(m.capturedStart(1), m.capturedLength(1), fmt)
                else:
                    self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

        # Multi-line triple-quoted strings (state 1 = inside """ , 2 = inside ''')
        self.setCurrentBlockState(0)
        self._match_multiline(text, self._tri_double, 1)
        self._match_multiline(text, self._tri_single, 2)

    def _match_multiline(self, text, delim, state):
        # Continuing a string opened in a previous block: the whole line begins
        # inside the string, so look for the CLOSING delimiter from column 0.
        if self.previousBlockState() == state:
            start = 0
            close_from = 0
        else:
            m = delim.match(text)
            if not m.hasMatch():
                return
            start = m.capturedStart()
            close_from = start + 3   # skip past the opening delimiter

        while start >= 0:
            m_end = delim.match(text, close_from)
            if m_end.hasMatch():
                end = m_end.capturedEnd()
                self.setFormat(start, end - start, self._str_fmt)
                # Another string may open later on the same line
                m_next = delim.match(text, end)
                if m_next.hasMatch():
                    start = m_next.capturedStart()
                    close_from = start + 3
                else:
                    start = -1
            else:
                # No closing delimiter → rest of the line stays in the string
                self.setCurrentBlockState(state)
                self.setFormat(start, len(text) - start, self._str_fmt)
                start = -1


class TransformEditorDialog(QDialog):
    """Browse / edit / add / delete transform scripts."""

    saved = Signal()   # emitted whenever a file is written or deleted

    def __init__(self, transforms_folder: str, stylesheet: str = "", parent=None):
        super().__init__(parent)
        self.folder = Path(transforms_folder)
        self._current: Path | None = None
        self._dirty = False

        self.setWindowTitle("ClipCommand — Manage Transforms")
        if stylesheet:
            self.setStyleSheet(stylesheet)
        self.resize(920, 620)
        self.setModal(False)

        self._build_ui()
        self._reload_list()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header row
        header = QHBoxLayout()
        title = QLabel("Manage Transforms")
        title.setStyleSheet(f"color: {C['navy']}; font-size: 15pt; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        new_btn = QPushButton("＋ New")
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(self._btn_style(C["ok"]))
        new_btn.clicked.connect(self._on_new)
        header.addWidget(new_btn)
        layout.addLayout(header)

        # Split: list | editor
        splitter = QSplitter(Qt.Horizontal)

        self.list = QListWidget()
        self.list.setMinimumWidth(220)
        self.list.setMaximumWidth(300)
        self.list.currentItemChanged.connect(self._on_select)
        splitter.addWidget(self.list)

        editor_side = QWidget()
        es = QVBoxLayout(editor_side)
        es.setContentsMargins(0, 0, 0, 0)
        es.setSpacing(6)

        self.path_label = QLabel("Select a transform to edit")
        self.path_label.setStyleSheet(f"color: {C['fg_dim']}; font-size: 9pt;")
        es.addWidget(self.path_label)

        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {C['bg_card']}; color: {C['fg']};"
            f" border: 1px solid {C['border']}; border-radius: 8px; padding: 6px; }}"
        )
        mono = QFont("Cascadia Code", 10)
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.editor.setFont(mono)
        self.editor.setTabStopDistance(4 * self.editor.fontMetrics().horizontalAdvance(" "))
        self.editor.textChanged.connect(self._on_text_changed)
        self._highlighter = PythonHighlighter(self.editor.document())
        es.addWidget(self.editor, stretch=1)

        self.status = QLabel("")
        self.status.setStyleSheet(f"color: {C['fg_dim']}; font-size: 9pt;")
        es.addWidget(self.status)

        splitter.addWidget(editor_side)
        splitter.setSizes([250, 670])
        layout.addWidget(splitter, stretch=1)

        # Button row
        btn_row = QHBoxLayout()
        self.delete_btn = QPushButton("🗑 Delete")
        self.delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.delete_btn.setStyleSheet(self._btn_style(C["err"]))
        self.delete_btn.clicked.connect(self._on_delete)
        self.delete_btn.setEnabled(False)
        btn_row.addWidget(self.delete_btn)

        btn_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {C['fg_dim']};"
            f" border: 1px solid {C['border']}; border-radius: 6px;"
            f" padding: 6px 16px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: #F3F4F6; }}"
        )
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        self.save_btn = QPushButton("💾 Save")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setStyleSheet(self._btn_style(C["navy"]))
        self.save_btn.clicked.connect(self._on_save)
        self.save_btn.setEnabled(False)
        btn_row.addWidget(self.save_btn)

        layout.addLayout(btn_row)

    @staticmethod
    def _btn_style(bg: str) -> str:
        return (
            f"QPushButton {{ background-color: {bg}; color: white; border: none;"
            f" border-radius: 6px; padding: 6px 16px; font-weight: 600; }}"
            f"QPushButton:disabled {{ background-color: #9CA3AF; }}"
        )

    # ── List ──────────────────────────────────────────────────────────────────

    def _reload_list(self):
        self.list.blockSignals(True)
        self.list.clear()
        if self.folder.is_dir():
            for py in sorted(self.folder.glob("*.py")):
                if py.name.startswith("_"):
                    continue
                item = QListWidgetItem(py.stem)
                item.setData(Qt.UserRole, str(py))
                self.list.addItem(item)
        self.list.blockSignals(False)

    def _on_select(self, current, _previous):
        if current is None:
            return
        if self._dirty and not self._confirm_discard():
            # revert selection
            self._reselect(self._current)
            return
        path = Path(current.data(Qt.UserRole))
        self._load_file(path)

    def _reselect(self, path):
        if not path:
            return
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == str(path):
                self.list.blockSignals(True)
                self.list.setCurrentRow(i)
                self.list.blockSignals(False)
                return

    def _load_file(self, path: Path):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Read error", f"Could not read {path.name}:\n{exc}")
            return
        self._current = path
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self.path_label.setText(str(path))
        self.delete_btn.setEnabled(True)
        self._dirty = False
        self.save_btn.setEnabled(False)
        self._check_syntax(text)

    # ── Editing ─────────────────────────────────────────────────────────────

    def _on_text_changed(self):
        if self._current is None:
            return
        self._dirty = True
        self.save_btn.setEnabled(True)
        self._check_syntax(self.editor.toPlainText())

    def _check_syntax(self, text: str) -> bool:
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            self.status.setText(f"✗ SyntaxError line {exc.lineno}: {exc.msg}")
            self.status.setStyleSheet(f"color: {C['err']}; font-size: 9pt; font-weight: 600;")
            return False
        has_transform = any(
            isinstance(n, ast.FunctionDef) and n.name == "transform"
            for n in tree.body
        )
        if not has_transform:
            self.status.setText("⚠ No top-level  def transform(text) -> str  found")
            self.status.setStyleSheet(f"color: #B45309; font-size: 9pt; font-weight: 600;")
            return True
        self.status.setText("✓ Syntax OK — defines transform()")
        self.status.setStyleSheet(f"color: {C['ok']}; font-size: 9pt; font-weight: 600;")
        return True

    # ── Actions ─────────────────────────────────────────────────────────────

    def _on_new(self):
        if self._dirty and not self._confirm_discard():
            return
        name, ok = QInputDialog.getText(
            self, "New Transform", "File name (without .py):", QLineEdit.Normal, ""
        )
        if not ok or not name.strip():
            return
        stem = name.strip().replace(" ", "_")
        if stem.startswith("_"):
            QMessageBox.warning(self, "Invalid name", "Name cannot start with '_'.")
            return
        path = self.folder / f"{stem}.py"
        if path.exists():
            QMessageBox.warning(self, "Exists", f"{path.name} already exists.")
            return
        try:
            path.write_text(TEMPLATE, encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Write error", str(exc))
            return
        self._reload_list()
        self._reselect(path)
        self._load_file(path)
        self.saved.emit()

    def _on_save(self):
        if self._current is None:
            return
        text = self.editor.toPlainText()
        if not self._check_syntax(text):
            resp = QMessageBox.question(
                self, "Save anyway?",
                "This file has a syntax error and won't load as a transform.\n"
                "Save anyway?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resp != QMessageBox.Yes:
                return
        try:
            self._current.write_text(text, encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "Write error", str(exc))
            return
        self._dirty = False
        self.save_btn.setEnabled(False)
        self.status.setText(f"✓ Saved {self._current.name}")
        self.status.setStyleSheet(f"color: {C['ok']}; font-size: 9pt; font-weight: 600;")
        self.saved.emit()

    def _on_delete(self):
        if self._current is None:
            return
        resp = QMessageBox.question(
            self, "Delete transform",
            f"Delete {self._current.name}? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if resp != QMessageBox.Yes:
            return
        try:
            self._current.unlink()
        except Exception as exc:
            QMessageBox.warning(self, "Delete error", str(exc))
            return
        self._current = None
        self._dirty = False
        self.editor.blockSignals(True)
        self.editor.clear()
        self.editor.blockSignals(False)
        self.path_label.setText("Select a transform to edit")
        self.status.setText("")
        self.delete_btn.setEnabled(False)
        self.save_btn.setEnabled(False)
        self._reload_list()
        self.saved.emit()

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _confirm_discard(self) -> bool:
        resp = QMessageBox.question(
            self, "Unsaved changes",
            "You have unsaved changes. Discard them?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        return resp == QMessageBox.Yes

    def closeEvent(self, event):
        if self._dirty and not self._confirm_discard():
            event.ignore()
            return
        event.accept()
