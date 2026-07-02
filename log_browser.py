"""
log_browser.py — Log browser dialog for ClipCommand (PySide6).

Opens as a non-modal window showing all log entries from the SQLite DB,
with full message display on row click, session filter, tag filter,
and auto-refresh.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QTextEdit,
    QSplitter, QWidget, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont

C = {
    "bg_main":  "#F5F6FA",   # BG_MAIN
    "bg_dark":  "#1F3864",   # NAVY
    "bg_mid":   "#FFFFFF",   # BG_CARD
    "bg_input": "#1F3864",   # NAVY
    "fg":       "#1A1A2E",   # TEXT_PRIMARY
    "fg_dim":   "#6B7280",   # TEXT_SECONDARY
    "fg_accent":"#4E79A7",   # ACCENT
    "ok":       "#22C55E",   # POSITIVE
    "err":      "#EF4444",   # NEGATIVE
    "warn":     "#F59E0B",   # WARNING
    "chain":    "#4E79A7",   # ACCENT
    "preview":  "#4E79A7",   # ACCENT
    "info":     "#4E79A7",   # ACCENT
    "ts":       "#6B7280",   # TEXT_SECONDARY
    "border":   "#E5E7EB",   # BORDER
}

# Darker, text-safe variants — the bright semantic colours in C fail contrast
# as small foreground text on the white table/detail-pane background.
TAG_COLOURS = {
    "ok":      "#15803D",
    "err":     "#B91C1C",
    "warn":    "#B45309",
    "info":    "#2C5282",
    "chain":   "#2C5282",
    "preview": "#2C5282",
    "ts":      C["ts"],
}

STYLESHEET = f"""
QDialog, QWidget {{
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
    font-weight: 600;
}}
QPushButton:hover {{ background-color: #2B4A8C; }}
QComboBox {{
    background-color: white;
    color: {C["fg"]};
    border: 1px solid {C["border"]};
    border-radius: 6px;
    padding: 5px 10px;
}}
QComboBox:hover, QComboBox:focus {{ border-color: {C["bg_dark"]}; }}
QComboBox QAbstractItemView {{
    background-color: white;
    color: {C["fg"]};
    selection-background-color: #E8EDF5;
    selection-color: {C["bg_dark"]};
    border: 1px solid {C["border"]};
}}
QTableWidget {{
    background-color: {C["bg_mid"]};
    color: {C["fg"]};
    gridline-color: transparent;
    border: 1px solid {C["border"]};
    border-radius: 8px;
    selection-background-color: #E8EDF5;
    selection-color: {C["bg_dark"]};
}}
QTableWidget::item {{ padding: 4px 8px; border-bottom: 1px solid #F3F4F6; }}
QHeaderView::section {{
    background-color: #F9FAFB;
    color: {C["bg_dark"]};
    font-weight: 600;
    border: none;
    border-bottom: 2px solid {C["border"]};
    padding: 6px 8px;
    font-size: 9pt;
}}
QTextEdit {{
    background-color: {C["bg_mid"]};
    color: {C["fg"]};
    border: 1px solid {C["border"]};
    border-radius: 8px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 9pt;
}}
QSplitter::handle {{ background-color: {C["bg_main"]}; height: 4px; }}
QLabel#section_label {{
    color: {C["fg_dim"]};
    font-size: 9pt;
    padding: 2px 4px;
}}
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


class LogBrowserDialog(QDialog):
    def __init__(self, db_logger, current_session_id: str, parent=None):
        super().__init__(parent)
        self._db      = db_logger
        self._session = current_session_id
        self._entries = []

        self.setWindowTitle("ClipCommand — Log Browser")
        self.setStyleSheet(STYLESHEET)
        self.resize(900, 600)
        self.setModal(False)

        self._build_ui()
        self._load_sessions()
        self._refresh()

        # Auto-refresh every 2 seconds
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(2000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = QWidget()
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(0, 0, 0, 0)
        tb_layout.setSpacing(8)

        tb_layout.addWidget(QLabel("Session:"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(220)
        self.session_combo.currentIndexChanged.connect(self._refresh)
        tb_layout.addWidget(self.session_combo)

        tb_layout.addWidget(QLabel("Tag:"))
        self.tag_combo = QComboBox()
        self.tag_combo.addItems(["all", "err", "warn", "ok", "info", "chain", "preview"])
        self.tag_combo.currentIndexChanged.connect(self._refresh)
        tb_layout.addWidget(self.tag_combo)

        tb_layout.addStretch()

        self.count_label = QLabel("")
        self.count_label.setObjectName("section_label")
        tb_layout.addWidget(self.count_label)

        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh)
        tb_layout.addWidget(refresh_btn)

        clear_btn = QPushButton("🗑 Clear session")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setStyleSheet(
            f"background-color: {C['err']}; color: white; border-radius: 6px;"
            f"padding: 6px 14px; font-weight: 600;"
        )
        clear_btn.clicked.connect(self._clear_session)
        tb_layout.addWidget(clear_btn)

        layout.addWidget(toolbar)

        # ── Splitter: table top, detail bottom ────────────────────────────────
        splitter = QSplitter(Qt.Vertical)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Time", "Tag", "Transform", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.horizontalHeader().resizeSection(0, 80)
        self.table.horizontalHeader().resizeSection(1, 60)
        self.table.horizontalHeader().resizeSection(2, 140)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_row_selected)
        splitter.addWidget(self.table)

        # Detail pane
        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.setSpacing(2)

        detail_label = QLabel("Full message:")
        detail_label.setObjectName("section_label")
        detail_layout.addWidget(detail_label)

        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setMinimumHeight(120)
        detail_layout.addWidget(self.detail_text)
        splitter.addWidget(detail_widget)

        splitter.setSizes([400, 200])
        layout.addWidget(splitter)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_sessions(self):
        sessions = self._db.get_sessions(limit=50)
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        self.session_combo.addItem("Current session", self._session)
        self.session_combo.addItem("All sessions", None)
        for s in sessions:
            ts = s["started_at"][:19].replace("T", " ")
            label = f"{ts}  [{s['id']}]"
            self.session_combo.addItem(label, s["id"])
        self.session_combo.blockSignals(False)

    def _refresh(self):
        session_id = self.session_combo.currentData()
        tag_text   = self.tag_combo.currentText()
        tag        = None if tag_text == "all" else tag_text

        self._entries = self._db.get_entries(
            session_id=session_id, tag=tag, limit=500
        )
        self._populate_table()

    def _populate_table(self):
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(self._entries))

        for row, entry in enumerate(self._entries):
            ts_str    = entry["timestamp"][11:19]  # HH:MM:SS
            tag       = entry["tag"]
            colour    = QColor(TAG_COLOURS.get(tag, C["fg"]))
            # Truncate message for table — full version shown in detail pane
            msg_short = entry["message"].split("\n")[0][:120]

            for col, text in enumerate([
                ts_str,
                tag,
                entry["transform_name"] or "",
                msg_short,
            ]):
                item = QTableWidgetItem(text)
                item.setForeground(colour)
                self.table.setItem(row, col, item)

            self.table.setRowHeight(row, 20)

        self.table.setUpdatesEnabled(True)
        self.count_label.setText(f"{len(self._entries)} entries")

        # Scroll to bottom (newest)
        if self._entries:
            self.table.scrollToBottom()

    def _on_row_selected(self):
        rows = self.table.selectedItems()
        if not rows:
            return
        row = self.table.currentRow()
        if 0 <= row < len(self._entries):
            entry = self._entries[row]
            colour = TAG_COLOURS.get(entry["tag"], C["fg"])
            self.detail_text.setTextColor(QColor(colour))
            ts = entry["timestamp"].replace("T", " ")
            header = f"[{ts}]  tag={entry['tag']}"
            if entry["transform_name"]:
                header += f"  transform={entry['transform_name']}"
            header += f"  id={entry['id']}\n{'─' * 60}\n"
            self.detail_text.setPlainText(header + entry["message"])

    def _clear_session(self):
        session_id = self.session_combo.currentData()
        if not session_id:
            return
        import sqlite3
        with sqlite3.connect(self._db.db_path) as conn:
            conn.execute(
                "DELETE FROM log_entries WHERE session_id = ?", (session_id,)
            )
        self._refresh()

