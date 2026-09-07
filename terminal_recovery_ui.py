"""Browsable live terminal inventory and retained boot snapshots."""

from datetime import datetime
import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QPushButton, QSplitter, QTextEdit, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout,
)


def local_time(stamp):
    return datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M:%S") if stamp else "—"


def recovery_details(row):
    state = "Live at latest scan" if row["live"] else (
        "Present at final scan of this boot" if row["at_boot_end"] else "Closed"
    )
    return "\n".join([
        f"Terminal: {row['tty']} · {row['terminal']}",
        f"Status: {state}",
        f"Directory: {row['cwd'] or '(unavailable)'}",
        f"Programs: {', '.join(row['programs']) or '(unavailable)'}",
        f"First recorded: {local_time(row['first_seen'])}",
        f"Last recorded: {local_time(row['last_seen'])}",
        f"Observed closed: {local_time(row['closed_at'])}",
        f"Boot: {row['boot_id']}",
        f"Terminal process: {row['pid']} · start tick {row['starttime']}",
        "",
        "Program names and directories only; commands are not restarted.",
    ])


class TerminalRecoveryDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Terminal recovery")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        self.resize(min(960, available.width() - 40) if available else 960,
                    min(620, available.height() - 60) if available else 620)
        self._entries = []
        self._boots = []
        self._boot_id = ""
        self._error = ""
        self._initial_view = True
        self.setStyleSheet("""
            QDialog { background: #171722; color: #dedeea; }
            QLabel { color: #dedeea; }
            QTreeWidget, QTextEdit, QLineEdit, QComboBox {
                background: #222231; color: #e4e4ee;
                border: 1px solid #45455e; border-radius: 4px; padding: 5px;
            }
            QHeaderView::section { background: #303044; color: #e4e4ee; padding: 6px; }
            QTreeWidget::item { padding: 5px; }
            QTreeWidget::item:selected { background: #454568; }
            QPushButton { background: #35354d; color: #eeeeff;
                border: 1px solid #555574; border-radius: 4px; padding: 6px 12px; }
            QPushButton:disabled { color: #85859c; }
        """)
        layout = QVBoxLayout(self)
        title = QLabel("All terminals & recovery")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #e0b68d;")
        layout.addWidget(title)
        description = QLabel(
            "Saved every 5 seconds while Indicator runs. After a reboot, review the last boot snapshot.\n"
            "Includes ordinary shells and programs. Keeps directories and program names; no scrollback or command replay."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self._status = QLabel("Waiting for the first saved inventory…")
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status)
        controls = QHBoxLayout()
        self._view = QComboBox()
        self._view.addItems(["Live", "Last boot snapshot", "All saved"])
        self._view.setAccessibleName("Terminal history view")
        self._view.currentIndexChanged.connect(self._render)
        controls.addWidget(self._view)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search directory, program, terminal, or date")
        self._search.setAccessibleName("Search saved terminals")
        self._search.textChanged.connect(self._render)
        controls.addWidget(self._search, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_requested.emit)
        controls.addWidget(refresh)
        layout.addLayout(controls)
        self._context = QLabel()
        self._context.setWordWrap(True)
        layout.addWidget(self._context)
        splitter = QSplitter(Qt.Orientation.Vertical)
        self._table = QTreeWidget()
        self._table.setAccessibleName("Recorded terminals")
        self._table.setHeaderLabels(["Terminal", "Program", "Directory", "Last recorded", "Status"])
        self._table.setRootIsDecorated(False)
        self._table.setUniformRowHeights(True)
        self._table.setColumnWidth(0, 85)
        self._table.setColumnWidth(1, 130)
        self._table.setColumnWidth(3, 155)
        self._table.setColumnWidth(4, 110)
        self._table.header().setStretchLastSection(False)
        self._table.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._selection_changed)
        splitter.addWidget(self._table)
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setAccessibleName("Selected terminal recovery details")
        splitter.addWidget(self._details)
        splitter.setSizes([300, 155])
        layout.addWidget(splitter, 1)
        bottom = QHBoxLayout()
        self._copy = QPushButton("Copy details")
        self._copy.setEnabled(False)
        self._copy.clicked.connect(lambda: QApplication.clipboard().setText(self._details.toPlainText()))
        bottom.addWidget(self._copy)
        bottom.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        bottom.addWidget(close)
        layout.addLayout(bottom)

    def set_data(self, entries, boots, boot_id, error=""):
        self._entries, self._boots = list(entries), list(boots)
        self._boot_id, self._error = boot_id, error
        if self._initial_view and boots:
            self._initial_view = False
            if self._previous_boot():
                self._view.setCurrentIndex(1)
        self._render()

    def _previous_boot(self):
        return next((boot for boot in self._boots if boot["boot_id"] != self._boot_id), None)

    def _render(self, *_):
        selected = self._table.currentItem()
        key = selected.data(0, Qt.ItemDataRole.UserRole)["key"] if selected else None
        scroll = self._table.verticalScrollBar().value()
        current_boot = next((b for b in self._boots if b["boot_id"] == self._boot_id), None)
        saved = local_time(current_boot["captured"]) if current_boot else "not yet"
        self._status.setText(
            f"Recording error: {self._error}\nLast successful save: {saved}. Displayed records may be stale."
            if self._error else f"Recording · last successful save: {saved} (local time)"
        )
        self._status.setStyleSheet("color: #ffb0a8;" if self._error else "color: #a8d8b2;")
        mode = self._view.currentIndex()
        previous = self._previous_boot()
        if mode == 0:
            rows = [r for r in self._entries if r["live"]]
            rows.sort(key=lambda r: [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", r["tty"])])
            explanation = "Terminals present at the latest successful scan."
        elif mode == 1:
            rows = [r for r in self._entries if previous and r["boot_id"] == previous["boot_id"] and r["at_boot_end"]]
            explanation = (
                f"Final snapshot from the previous recorded boot · {local_time(previous['captured'])}."
                if previous else "No previous boot recorded yet. Recording begins with this version."
            )
        else:
            rows = self._entries
            explanation = "All retained terminals, including earlier closed sessions."
        query = self._search.text().strip().casefold()
        if query:
            rows = [r for r in rows if query in "\n".join([
                r["cwd"], r["tty"], r["terminal"], *r["programs"],
                local_time(r["first_seen"]), local_time(r["last_seen"]),
            ]).casefold()]
        self._context.setText(f"{len(rows)} terminals · {explanation}" + (" No matches." if query and not rows else ""))
        self._table.blockSignals(True)
        self._table.clear()
        selected_item = None
        for row in rows:
            state = ("Last seen" if self._error else "Live") if row["live"] else (
                "Boot snapshot" if row["at_boot_end"] else "Closed"
            )
            item = QTreeWidgetItem([
                row["tty"], row["programs"][0] if row["programs"] else "?",
                row["cwd"] or "(unavailable)", local_time(row["last_seen"]), state,
            ])
            item.setData(0, Qt.ItemDataRole.UserRole, row)
            for column in range(5):
                item.setToolTip(column, recovery_details(row))
            self._table.addTopLevelItem(item)
            if row["key"] == key:
                selected_item = item
        if selected_item is not None:
            self._table.setCurrentItem(selected_item)
        elif rows:
            self._table.setCurrentItem(self._table.topLevelItem(0))
        self._table.blockSignals(False)
        self._table.verticalScrollBar().setValue(scroll)
        self._selection_changed()

    def _selection_changed(self):
        item = self._table.currentItem()
        self._copy.setEnabled(item is not None)
        self._details.setPlainText(
            recovery_details(item.data(0, Qt.ItemDataRole.UserRole)) if item else
            "Select a terminal to view its saved directory, programs, and observation times."
        )
