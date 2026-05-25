"""
Qt Log View for StreamCapEvo — full-featured real-time log console.

Features:
  • Colour-coded log levels (DEBUG / INFO / SUCCESS / WARNING / ERROR / RETRY / STREAM)
  • Special "Intelligence" highlight for queue-management messages
  • Live search / filter by log level
  • Auto-scroll toggle
  • Error / warning badge counters
  • Copy-all to clipboard
  • Clear button
  • Circular buffer (max 2 000 lines) to keep memory under control
  • Reactive to ThemeManager (dark ↔ light)
"""

from __future__ import annotations

import html
import re
from datetime import datetime

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtGui import (
    QTextCursor,
    QFont,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFrame,
)

from app.utils.logger import logger
from app.qt.themes.theme import theme_manager

# ── Colour palette for log levels ────────────────────────────────────────────
# These are intentionally hard-coded (not theme tokens) so the log console
# always has a dark terminal look regardless of the app theme.
_LOG_BG = "#0d1117"          # near-black, GitHub-dark inspired
_LOG_FG = "#c9d1d9"          # default text

_LEVEL_COLORS: dict[str, dict] = {
    "TRACE":     {"fg": "#8b949e", "bold": False},
    "DEBUG":     {"fg": "#58a6ff", "bold": False},   # blue
    "INFO":      {"fg": "#c9d1d9", "bold": False},   # default
    "SUCCESS":   {"fg": "#56d364", "bold": True},    # green
    "WARNING":   {"fg": "#e3b341", "bold": True},    # yellow
    "ERROR":     {"fg": "#f85149", "bold": True},    # red
    "CRITICAL":  {"fg": "#ff5c8d", "bold": True},    # pink-red
    "RETRY":     {"fg": "#c084fc", "bold": True},    # purple
    "STREAM":    {"fg": "#38bdf8", "bold": False},   # sky-blue
}

# Tokens that trigger the "Intelligence" / queue highlight.
# Only match the SUMMARY / WORKER lines, not individual dispatch debug lines.
_INTELLIGENCE_KEYWORDS = (
    "Intelligence Cycle Summary",
    "Intelligence Worker",
)
_INTELLIGENCE_BG   = "#0f3318"   # vivid dark-green background — clearly visible on #0d1117
_INTELLIGENCE_FG   = "#a8ff78"   # bright lime-green text
_INTELLIGENCE_BOLD = True

# Timestamp colour
_TS_COLOR = "#484f58"

# Maximum log lines kept in the text widget (older lines are removed)
_MAX_LINES = 2000

# Regex to strip loguru colour markup tags: <yellow>, </yellow>, <bold>, etc.
_LOGURU_TAG_RE = re.compile(r"</?[a-zA-Z_]+(?:\s[^>]*)?>")

def _strip_loguru_tags(text: str) -> str:
    """Remove loguru opt(colors=True) markup tags from a message string."""
    return _LOGURU_TAG_RE.sub("", text)


# ── Signal bridge (loguru sink → Qt main thread) ─────────────────────────────

class _LogSignal(QObject):
    """Cross-thread bridge: loguru sink emits this signal."""
    received = Signal(str, str, str)   # timestamp, level, message


# ── Log entry model ──────────────────────────────────────────────────────────

class _LogEntry:
    __slots__ = ("timestamp", "level", "message", "html")

    def __init__(self, timestamp: str, level: str, message: str, html_text: str):
        self.timestamp = timestamp
        self.level     = level
        self.message   = message
        self.html      = html_text


# ── View ─────────────────────────────────────────────────────────────────────

class QtLogView(QWidget):
    """
    Real-time application log console with colour-coded levels and
    special highlighting for Intelligence / queue management messages.
    """

    def __init__(self, app_context):
        super().__init__()
        self.app = app_context

        # Internal state
        self._auto_scroll   = True
        self._filter_level  = "ALL"      # current level filter
        self._search_text   = ""         # current search filter
        self._entries: list[_LogEntry] = []  # circular buffer (newest last)
        self._error_count   = 0
        self._warning_count = 0
        self._sink_id       = None

        # Cross-thread signal bridge
        self._signal = _LogSignal()
        self._signal.received.connect(self._on_log_received)

        self._setup_ui()
        self._setup_sink()

        # React to theme changes
        theme_manager.themeChanged.connect(self._on_theme_changed)

    # ── UI construction ───────────────────────────────────────────────────────

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        root.addLayout(self._build_header())
        root.addLayout(self._build_toolbar())
        root.addWidget(self._build_log_display())
        root.addLayout(self._build_statusbar())

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(12)

        title = QLabel("📜  Application Logs")
        title.setProperty("class", "heading")
        layout.addWidget(title)

        layout.addStretch()

        # Error / warning badges
        self._badge_errors = self._make_badge("0 errors", "#f85149")
        self._badge_warnings = self._make_badge("0 warnings", "#e3b341")
        layout.addWidget(self._badge_warnings)
        layout.addWidget(self._badge_errors)

        return layout

    @staticmethod
    def _make_badge(text: str, color: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 700;"
            f"background: transparent; padding: 0 4px;"
        )
        return lbl

    # ── Toolbar ───────────────────────────────────────────────────────────────

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.setSpacing(8)

        # Level filter
        self._level_combo = QComboBox()
        self._level_combo.addItems(
            ["ALL", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "RETRY", "STREAM"]
        )
        self._level_combo.setFixedWidth(110)
        self._level_combo.setToolTip("Filter by log level")
        self._level_combo.currentTextChanged.connect(self._on_level_filter_changed)
        layout.addWidget(self._level_combo)

        # Search box
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("🔍  Search logs…")
        self._search_box.setFixedWidth(220)
        self._search_box.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search_box)

        layout.addStretch()

        # Auto-scroll toggle
        self._autoscroll_btn = QPushButton("⬇  Auto-scroll")
        self._autoscroll_btn.setProperty("class", "secondary")
        self._autoscroll_btn.setCheckable(True)
        self._autoscroll_btn.setChecked(True)
        self._autoscroll_btn.setFixedWidth(130)
        self._autoscroll_btn.clicked.connect(self._on_autoscroll_toggled)
        layout.addWidget(self._autoscroll_btn)

        # Copy all
        copy_btn = QPushButton("📋  Copy All")
        copy_btn.setProperty("class", "secondary")
        copy_btn.setFixedWidth(110)
        copy_btn.clicked.connect(self._on_copy_all)
        layout.addWidget(copy_btn)

        # Clear
        clear_btn = QPushButton("🗑  Clear")
        clear_btn.setProperty("class", "secondary")
        clear_btn.setFixedWidth(90)
        clear_btn.clicked.connect(self._on_clear)
        layout.addWidget(clear_btn)

        return layout

    # ── Log display ───────────────────────────────────────────────────────────

    def _build_log_display(self) -> QTextEdit:
        self._display = QTextEdit()
        self._display.setReadOnly(True)
        self._display.setUndoRedoEnabled(False)
        self._display.setAcceptRichText(True)

        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self._display.setFont(font)

        self._apply_display_style()

        # Ctrl+F focuses search box
        QShortcut(QKeySequence("Ctrl+F"), self._display).activated.connect(
            lambda: self._search_box.setFocus()
        )

        return self._display

    def _apply_display_style(self):
        self._display.setStyleSheet(f"""
            QTextEdit {{
                background-color: {_LOG_BG};
                color: {_LOG_FG};
                border: 1px solid #30363d;
                border-radius: 8px;
                padding: 10px;
                selection-background-color: #264f78;
            }}
            QScrollBar:vertical {{
                background: #161b22;
                width: 10px;
                margin: 0;
                border: none;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical {{
                background: #30363d;
                min-height: 36px;
                border-radius: 4px;
                margin: 1px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: #484f58;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: #161b22;
                border-radius: 4px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

    # ── Status bar ────────────────────────────────────────────────────────────

    def _build_statusbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self._status_lbl = QLabel("Ready")
        self._status_lbl.setProperty("class", "muted")
        layout.addWidget(self._status_lbl)

        layout.addStretch()

        self._count_lbl = QLabel("0 lines")
        self._count_lbl.setProperty("class", "muted")
        layout.addWidget(self._count_lbl)

        return layout

    # ── Loguru sink ───────────────────────────────────────────────────────────

    def _setup_sink(self):
        signal = self._signal

        def _sink(message):
            record = message.record
            level  = record["level"].name
            # Strip loguru color markup tags (e.g. <yellow>…</yellow>) that are
            # embedded when callers use logger.opt(colors=True).
            msg    = _strip_loguru_tags(record["message"])
            ts     = record["time"].strftime("%H:%M:%S.%f")[:-3]  # HH:MM:SS.mmm
            signal.received.emit(ts, level, msg)

        self._sink_id = logger.add(_sink, level="DEBUG", enqueue=True)

    # ── Incoming log entry ────────────────────────────────────────────────────

    def _on_log_received(self, timestamp: str, level: str, message: str):
        # Track error / warning counts
        if level == "ERROR" or level == "CRITICAL":
            self._error_count += 1
            self._badge_errors.setText(f"{self._error_count} error{'s' if self._error_count != 1 else ''}")
        elif level == "WARNING":
            self._warning_count += 1
            self._badge_warnings.setText(f"{self._warning_count} warning{'s' if self._warning_count != 1 else ''}")

        html_text = self._build_html(timestamp, level, message)
        entry = _LogEntry(timestamp, level, message, html_text)

        # Circular buffer
        self._entries.append(entry)
        if len(self._entries) > _MAX_LINES:
            self._entries.pop(0)

        # Append to display if passes active filters
        if self._entry_passes_filter(entry):
            self._append_html(html_text)

        # Update counters
        visible_count = self._display.document().blockCount()
        self._count_lbl.setText(f"{len(self._entries)} captured · {visible_count} shown")

    # ── HTML builder ──────────────────────────────────────────────────────────

    def _build_html(self, timestamp: str, level: str, message: str) -> str:
        """Return a single <div> line of HTML for this log entry."""
        is_intelligence = any(kw in message for kw in _INTELLIGENCE_KEYWORDS)

        # Choose colours
        if is_intelligence:
            fg   = _INTELLIGENCE_FG
            bold = _INTELLIGENCE_BOLD
            bg   = _INTELLIGENCE_BG
        else:
            style = _LEVEL_COLORS.get(level, {"fg": _LOG_FG, "bold": False})
            fg   = style["fg"]
            bold = style["bold"]
            bg   = ""

        safe_msg = html.escape(message)

        # Bold wrapper
        msg_inner = f"<b>{safe_msg}</b>" if bold else safe_msg

        # Level badge
        badge = (
            f'<span style="color:{fg};font-weight:700;">'
            f'[{level:<7}]</span>'
        )

        # Timestamp
        ts_span = f'<span style="color:{_TS_COLOR};">{html.escape(timestamp)}</span>'

        # Intelligence gets a full-line background tint
        if bg:
            line = (
                f'<div style="background-color:{bg};border-radius:3px;'
                f'padding:1px 4px;margin:1px 0;">'
                f'{ts_span} {badge} '
                f'<span style="color:{fg};">{msg_inner}</span>'
                f'</div>'
            )
        else:
            line = (
                f'<div style="margin:1px 0;">'
                f'{ts_span} {badge} '
                f'<span style="color:{fg};">{msg_inner}</span>'
                f'</div>'
            )

        return line

    # ── Append HTML to display ────────────────────────────────────────────────

    def _append_html(self, html_text: str):
        cursor = self._display.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html_text)
        cursor.insertBlock()   # newline between entries

        if self._auto_scroll:
            self._display.setTextCursor(cursor)
            self._display.ensureCursorVisible()

    # ── Filter logic ──────────────────────────────────────────────────────────

    def _entry_passes_filter(self, entry: _LogEntry) -> bool:
        if self._filter_level != "ALL" and entry.level != self._filter_level:
            return False
        if self._search_text and self._search_text.lower() not in entry.message.lower():
            return False
        return True

    def _rebuild_display(self):
        """Rebuild the entire text area from the in-memory buffer (used after filter change)."""
        self._display.clear()
        for entry in self._entries:
            if self._entry_passes_filter(entry):
                self._append_html(entry.html)
        count = self._display.document().blockCount()
        self._count_lbl.setText(f"{len(self._entries)} captured · {count} shown")

    # ── Toolbar actions ───────────────────────────────────────────────────────

    def _on_level_filter_changed(self, level: str):
        self._filter_level = level
        self._status_lbl.setText(f"Filtering: {level}")
        self._rebuild_display()

    def _on_search_changed(self, text: str):
        self._search_text = text.strip()
        label = f"Search: '{self._search_text}'" if self._search_text else "Ready"
        self._status_lbl.setText(label)
        self._rebuild_display()

    def _on_autoscroll_toggled(self, checked: bool):
        self._auto_scroll = checked
        label = "⬇  Auto-scroll" if checked else "⏸  Paused"
        self._autoscroll_btn.setText(label)
        if checked:
            self._display.verticalScrollBar().setValue(
                self._display.verticalScrollBar().maximum()
            )

    def _on_copy_all(self):
        plain = self._display.toPlainText()
        QApplication.clipboard().setText(plain)
        self._status_lbl.setText("Copied to clipboard ✓")
        QTimer.singleShot(2000, lambda: self._status_lbl.setText("Ready"))

    def _on_clear(self):
        self._entries.clear()
        self._error_count   = 0
        self._warning_count = 0
        self._badge_errors.setText("0 errors")
        self._badge_warnings.setText("0 warnings")
        self._display.clear()
        self._count_lbl.setText("0 lines")
        self._status_lbl.setText("Cleared")
        QTimer.singleShot(1500, lambda: self._status_lbl.setText("Ready"))

    # ── Theme reactions ───────────────────────────────────────────────────────

    def _on_theme_changed(self):
        # The terminal pane intentionally keeps its own dark style;
        # but we still need to re-apply so that the surrounding widgets
        # (labels, buttons, combo) get the new palette.
        self._apply_display_style()

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if self._sink_id is not None:
            try:
                logger.remove(self._sink_id)
            except Exception:
                pass
        super().closeEvent(event)
