"""
Qt Recordings View for StreamCapEvo.

Migrates the Flet GridView of recording cards to a Qt layout.
"""

import os

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QScrollArea,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from app.core.recording.recording_state_logic import RecordingStateLogic
from app.qt.components.recording_card import QtRecordingCard
from app.qt.themes.theme import theme_manager
from app.qt.utils.elevation import apply_elevation
from app.qt.utils.filters import RecordingFilters
from app.qt.utils.iconography import apply_button_icon, icon_pixmap
from app.qt.utils.typography import body_font
from app.utils.i18n import tr
from app.utils.logger import logger

_RECORDING_ROLE = Qt.ItemDataRole.UserRole + 1


class RecordingListModel(QAbstractListModel):
    """Lightweight virtualized model for the default recordings list view."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recordings: list = []

    def rowCount(self, parent: QModelIndex | None = None) -> int:  # noqa: N802
        parent = parent or QModelIndex()
        return 0 if parent.isValid() else len(self._recordings)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._recordings):
            return None
        rec = self._recordings[index.row()]
        if role == _RECORDING_ROLE:
            return rec
        if role == Qt.ItemDataRole.DisplayRole:
            return rec.streamer_name or "Unknown"
        return None

    def set_recordings(self, recordings: list) -> None:
        self.beginResetModel()
        self._recordings = list(recordings)
        self.endResetModel()

    def recordings(self) -> list:
        return list(self._recordings)

    def refresh_all(self) -> None:
        if not self._recordings:
            return
        top_left = self.index(0, 0)
        bottom_right = self.index(len(self._recordings) - 1, 0)
        self.dataChanged.emit(top_left, bottom_right, [_RECORDING_ROLE, Qt.ItemDataRole.DisplayRole])


class RecordingListDelegate(QStyledItemDelegate):
    """Paints recording rows without creating one QWidget tree per stream."""

    ROW_HEIGHT = 82
    ACTIONS = [
        ("folder", "folder"),
        ("play", "play"),
        ("stop_monitoring", "pause"),
        ("favorite", "favorite_off"),
        ("preview", "preview"),
        ("edit", "edit"),
        ("info", "info"),
        ("delete", "delete"),
    ]

    def __init__(self, app_context, parent=None):
        super().__init__(parent)
        self.app = app_context
        self._card_l = self.app.language_manager.language.get("recording_card", {})
        self.hovered_action: tuple[str, str] | None = None

    def action_tooltip(self, action: str, rec) -> str:
        if action == "play":
            if RecordingStateLogic.is_actively_recording(rec):
                return self._card_l.get("stop_record", "Stop Recording")
            if rec.monitor_status:
                return self._card_l.get("stop_monitor", "Stop Monitoring")
            return self._card_l.get("start_monitor", "Start Monitoring")

        tooltips = {
            "folder": self._card_l.get("open_folder", "Open Folder"),
            "stop_monitoring": self._card_l.get("stop_monitor", "Stop Monitoring"),
            "favorite": (
                self._card_l.get("unfavorite", "Remove from favorites")
                if bool(getattr(rec, "is_favorite", False))
                else self._card_l.get("favorite", "Mark as favorite")
            ),
            "preview": "Preview",
            "edit": self._card_l.get("edit_record_config", "Edit"),
            "info": self._card_l.get("recording_info", "Info"),
            "delete": self._card_l.get("delete_monitor", "Delete"),
        }
        return tooltips.get(action, "")

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:  # noqa: N802
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        rec = index.data(_RECORDING_ROLE)
        if rec is None:
            return

        from app.qt.components.recording_card import _STATUS_COLOR

        state = RecordingStateLogic.get_card_state(rec)
        status_color = _STATUS_COLOR.get(state, "#546E7A")
        colors = theme_manager.colors
        row = option.rect.adjusted(8, 5, -8, -5)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        bg_color = colors["card_hover"] if hovered else colors["card"]
        border_color = colors["accent"] if hovered else colors["border"]
        painter.setPen(QPen(QColor(border_color), 1.2 if hovered else 1.0))
        painter.setBrush(QBrush(QColor(bg_color)))
        painter.drawRoundedRect(row, 10, 10)

        pill_h = int(row.height() * 0.42)
        pill_y = row.y() + (row.height() - pill_h) // 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(status_color)))
        painter.drawRoundedRect(row.x() + 8, pill_y, 4, pill_h, 2, 2)

        avatar_size = 36
        avatar_x = row.x() + 32
        avatar_y = row.y() + (row.height() - avatar_size) // 2
        painter.setBrush(QBrush(QColor(status_color)))
        painter.drawEllipse(avatar_x, avatar_y, avatar_size, avatar_size)
        painter.setPen(QColor("#FFFFFF"))
        painter.setFont(body_font(11, QFont.Weight.Bold))
        letter = (rec.streamer_name or "?")[0].upper()
        painter.drawText(QRect(avatar_x, avatar_y, avatar_size, avatar_size), Qt.AlignmentFlag.AlignCenter, letter)

        text_x = avatar_x + avatar_size + 16
        action_rects = self.action_rects(row, rec)
        action_left = min((rect.x() for _, _, rect in action_rects), default=row.right() - 34)
        name = rec.streamer_name or "Unknown"
        if RecordingStateLogic.should_show_live_title(rec):
            name = f"{name} — {rec.live_title}"

        # Keep text strictly before action buttons to avoid overlap in narrow widths
        name_right = max(text_x + 40, action_left - 20)

        painter.setFont(body_font(10, QFont.Weight.Bold))
        painter.setPen(QColor(colors["text"]))
        name_rect = QRect(text_x, row.y() + 18, max(0, name_right - text_x), 22)
        painter.drawText(
            name_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width()),
        )

        status_text = rec.status_info or "Idle"
        status_rect = QRect(text_x, row.y() + 41, max(0, name_right - text_x), 18)
        painter.setFont(body_font(9, QFont.Weight.DemiBold))
        painter.setPen(QColor(status_color))
        painter.drawText(status_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, status_text)

        duration_text = ""
        if RecordingStateLogic.should_show_duration(rec):
            duration = self.app.record_manager.get_duration(rec)
            if duration != "00:00:00":
                duration_text = f"  {duration}"

        if duration_text:
            status_metrics = painter.fontMetrics()
            duration_x = text_x + status_metrics.horizontalAdvance(status_text)
            duration_rect = QRect(duration_x, status_rect.y(), max(0, name_right - duration_x), status_rect.height())
            painter.setFont(body_font(8))
            painter.setPen(QColor("#777777"))
            painter.drawText(
                duration_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                painter.fontMetrics().elidedText(duration_text, Qt.TextElideMode.ElideRight, duration_rect.width()),
            )

        for action, icon_name, rect in action_rects:
            is_action_hovered = self.hovered_action == (getattr(rec, "rec_id", ""), action)
            if is_action_hovered:
                painter.setPen(Qt.PenStyle.NoPen)
                hover_color = QColor(colors["accent"])
                hover_color.setAlpha(45)
                painter.setBrush(QBrush(hover_color))
                painter.drawRoundedRect(rect, 6, 6)

            if action == "favorite":
                icon_color = "#C62828" if is_action_hovered else "#E53935"
            else:
                icon_color = colors["accent"] if is_action_hovered else colors["text_sec"]
            pix = icon_pixmap(icon_name, size=16, color=icon_color)
            if not pix.isNull():
                icon_rect = QRect(rect.x() + 11, rect.y() + 6, 16, 16)
                painter.drawPixmap(icon_rect, pix)

        painter.restore()

    @classmethod
    def action_rects(cls, row_rect: QRect, rec=None) -> list[tuple[str, str, QRect]]:
        x = row_rect.right() - 34
        rects: list[tuple[str, str, QRect]] = []
        for action, icon_name in reversed(cls.ACTIONS):
            should_skip = (
                action == "stop_monitoring"
                and (rec is None or not RecordingStateLogic.should_show_stop_monitoring_action(rec))
            )
            if should_skip:
                continue
            actual_icon = icon_name
            if action == "play" and rec is not None:
                if RecordingStateLogic.is_actively_recording(rec):
                    actual_icon = "stop"
                elif getattr(rec, "monitor_status", False):
                    actual_icon = "pause"
            elif action == "favorite" and rec is not None:
                actual_icon = "favorite_on" if bool(getattr(rec, "is_favorite", False)) else "favorite_off"
            rects.append((action, actual_icon, QRect(x, row_rect.y() + 23, 38, 28)))
            x -= 62
        rects.reverse()
        return rects

    @classmethod
    def action_at(cls, row_rect: QRect, pos, rec=None) -> str | None:
        for action, _, rect in cls.action_rects(row_rect, rec):
            if rect.contains(pos):
                return action
        return None




class QtRecordingsView(QWidget):
    """
    Shows the grid or list of recordings currently being monitored/recorded.
    """

    def __init__(self, app_context):
        super().__init__()
        self.app = app_context
        self.language = self.app.language_manager.language
        self._l = self.language.get("recordings_page", {})
        self._cards: dict = {}
        self._all_recordings: list = []
        self._visible_recordings: list = []
        self._view_mode = "list"   # list is default; user can switch to grid
        self._current_status_filter = "all"
        self._current_platform_filter = "all"
        self._search_query = ""
        
        self._setup_ui()
        self._load_data()
        self._update_platform_list()
        self._subscribe_events()
        
        # 1-second timer for real-time card updates (timer/status)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._on_refresh_tick)
        self._refresh_timer.start(1000)

        theme_manager.themeChanged.connect(self._on_theme_changed)

        # Apply filters initially to make cards visible and redraw the grid
        self._apply_filters()

    def resizeEvent(self, event):  # noqa: N802
        """Handle resize to adjust grid columns."""
        self._redraw_grid()
        super().resizeEvent(event)

    def showEvent(self, event):  # noqa: N802
        """Triggered when the view becomes visible (e.g. first show or tab switch).
        
        We defer _redraw_grid() with QTimer.singleShot(0) so it runs AFTER Qt
        has finished laying out the window and scroll.viewport().width() returns
        the real width. Without this, the initial grid layout computed during
        __init__ uses width=0 (viewport not yet sized) and all cards stack at
        the top-left corner.
        """
        super().showEvent(event)
        QTimer.singleShot(0, self._redraw_grid)

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Header: Title + Actions
        header = QHBoxLayout()
        title = QLabel(self._l.get("recording_list", "Recordings"))
        title.setProperty("class", "heading")
        header.addWidget(title)
        
        header.addStretch()

        # View Mode Toggle
        self.view_toggle_btn = QPushButton()
        self.view_toggle_btn.setStyleSheet("font-size: 20px;")
        self.view_toggle_btn.setToolTip(self._l.get("toggle_view", "Toggle Grid/List View"))
        self.view_toggle_btn.setProperty("class", "icon")
        self.view_toggle_btn.setFixedSize(36, 36)
        self.view_toggle_btn.clicked.connect(self._toggle_view_mode)
        apply_button_icon(self.view_toggle_btn, "grid", size=16, color=theme_manager.get_color("text_sec"))
        header.addWidget(self.view_toggle_btn)
        
        # Refresh button
        self.refresh_btn = QPushButton()
        self.refresh_btn.setToolTip(self._l.get("refresh", "Refresh List"))
        self.refresh_btn.setProperty("class", "icon")
        self.refresh_btn.setFixedSize(36, 36)
        self.refresh_btn.clicked.connect(self.refresh)
        apply_button_icon(self.refresh_btn, "refresh", size=16, color=theme_manager.get_color("text_sec"))
        header.addWidget(self.refresh_btn)

        # Add button
        self.add_btn = QPushButton()
        self.add_btn.setToolTip(self._l.get("add_record", "Add New Stream"))
        self.add_btn.setProperty("class", "primary-btn") # Keep it prominent but smaller
        self.add_btn.setFixedSize(36, 36)
        self.add_btn.setStyleSheet("font-size: 20px; font-weight: bold; padding: 0;")
        self.add_btn.clicked.connect(self._on_add_stream_clicked)
        apply_button_icon(self.add_btn, "add", size=16, color="#FFFFFF")
        header.addWidget(self.add_btn)

        # Batch Start Button
        self.batch_start_btn = QPushButton()
        self.batch_start_btn.setToolTip(self._l.get("batch_start", "Start Monitor (Visible Streams)"))
        self.batch_start_btn.setProperty("class", "icon")
        self.batch_start_btn.setFixedSize(36, 36)
        self.batch_start_btn.clicked.connect(self._on_batch_start_clicked)
        apply_button_icon(self.batch_start_btn, "play", size=16, color=theme_manager.get_color("text_sec"))
        header.addWidget(self.batch_start_btn)

        # Batch Stop Button
        self.batch_stop_btn = QPushButton()
        self.batch_stop_btn.setToolTip(self._l.get("batch_stop", "Stop Monitor (Visible Streams)"))
        self.batch_stop_btn.setProperty("class", "icon")
        self.batch_stop_btn.setFixedSize(36, 36)
        self.batch_stop_btn.clicked.connect(self._on_batch_stop_clicked)
        apply_button_icon(self.batch_stop_btn, "stop", size=16, color=theme_manager.get_color("text_sec"))
        header.addWidget(self.batch_stop_btn)
        
        main_layout.addLayout(header)

        # ── Filter Bar ────────────────────────────────────────────────
        # Use two rows to handle long translated strings gracefully
        filter_bar_frame = QFrame()
        filter_bar_frame.setProperty("class", "card")
        filter_bar_layout = QVBoxLayout(filter_bar_frame)
        filter_bar_layout.setContentsMargins(14, 12, 14, 12)
        filter_bar_layout.setSpacing(12)
        
        top_filter_row = QHBoxLayout()
        top_filter_row.setSpacing(10)
        
        # 1. Search Box
        self.search_box = QLineEdit()
        # Use simple "Search..." instead of long "Enter search keyword"
        placeholder = self._l.get("search", "Search")
        self.search_box.setPlaceholderText(f"{placeholder}...")
        self.search_box.setMinimumWidth(250)
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._on_search_changed)
        top_filter_row.addWidget(self.search_box)

        top_filter_row.addStretch()
        
        bottom_filter_row = QHBoxLayout()
        bottom_filter_row.setSpacing(10)

        # Status Filter Label
        status_label = QLabel(self._l.get("status_filter", "Status:").split(':')[0] + ":")
        status_label.setProperty("class", "secondary")
        bottom_filter_row.addWidget(status_label)
        
        # 2. Status Filters
        self.status_grp = QButtonGroup(self)
        self.status_grp.setExclusive(True)
        
        status_filters = [
            (self._l.get("filter_all", "Todos"), "all", theme_manager.get_color("accent")),
            (self._l.get("filter_recording", "Grabando"), "recording", "#F44336"),
            (self._l.get("filter_living", "En Vivo"), "living", "#4CAF50"),
            (self._l.get("filter_offline", "Offline"), "offline", "#9E9E9E"),
            (self._l.get("filter_error", "Error"), "error", "#FF9800"),
            (self._l.get("filter_stopped", "Detenido"), "stopped", "#607D8B"),
            (self._l.get("filter_stale", "+30 días"), "stale", "#EF6C00"),
        ]
        
        self.filter_btns = []
        for i, (label, key, color) in enumerate(status_filters):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("class", "filter-btn")
            if key == "all": 
                btn.setChecked(True)
            
            # Elite Premium Styling: Active state uses the specific status color
            btn.setStyleSheet(f"""
                QPushButton[class="filter-btn"]:checked {{
                    background-color: {color};
                    border-color: {color};
                    color: white;
                }}
            """)
            
            btn.setProperty("filter_key", key)
            btn.setProperty("base_color", color)
            btn.clicked.connect(self._on_filter_clicked)
            self.status_grp.addButton(btn, i)
            bottom_filter_row.addWidget(btn)
            self.filter_btns.append(btn)
            
        bottom_filter_row.addStretch()
        filter_bar_layout.addLayout(bottom_filter_row)
        
        # 3. Platform Dropdown
        self.platform_combo = QComboBox()
        self.platform_combo.setMinimumWidth(140)
        self.platform_combo.addItem(self.language.get("recording_card", {}).get("all", "Todas"), "all")
        self.platform_combo.currentIndexChanged.connect(self._on_platform_changed)
        
        platform_label = QLabel(self._l.get("platform_filter", "Plataforma:").split(':')[0] + ":")
        platform_label.setProperty("class", "secondary")
        top_filter_row.addWidget(platform_label)
        top_filter_row.addWidget(self.platform_combo)
        
        filter_bar_layout.insertLayout(0, top_filter_row)
        main_layout.addWidget(filter_bar_frame)
        apply_elevation(filter_bar_frame, level=1)
        self._filter_bar_frame = filter_bar_frame

        # Scrollable Area for cards
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("background: transparent;")
        
        self.card_container = QWidget()
        self.card_container.setObjectName("cardContainer")
        self.card_container.setStyleSheet("#cardContainer { background: transparent; }")
        
        self.grid_layout = QGridLayout(self.card_container)
        self.grid_layout.setSpacing(15)
        self.grid_layout.setContentsMargins(10, 10, 10, 10)
        # Fix alignment to Top-Left
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        
        self.scroll.setWidget(self.card_container)
        self.scroll.hide()
        main_layout.addWidget(self.scroll)

        self.list_model = RecordingListModel(self)
        self.list_delegate = RecordingListDelegate(self.app, self)
        self.list_view = QListView()
        self.list_view.setModel(self.list_model)
        self.list_view.setItemDelegate(self.list_delegate)
        self.list_view.setMouseTracking(True)
        self._hovered_list_action: tuple[str, str] | None = None
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list_view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_view.setFrameShape(QFrame.Shape.NoFrame)
        self.list_view.setStyleSheet("background: transparent; border: none;")
        self.list_view.viewport().installEventFilter(self)
        main_layout.addWidget(self.list_view)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj is self.list_view.viewport() and event.type() == QEvent.Type.MouseMove:
            self._update_list_cursor(event.position().toPoint(), event.globalPosition().toPoint())
        elif obj is self.list_view.viewport() and event.type() in {
            QEvent.Type.Leave,
            QEvent.Type.HoverLeave,
        }:
            self._set_hovered_list_action(None)
            self.list_view.viewport().unsetCursor()
            QToolTip.hideText()
        elif obj is self.list_view.viewport() and event.type() == QEvent.Type.MouseButtonRelease:
            index = self.list_view.indexAt(event.position().toPoint())
            if index.isValid():
                rec = index.data(_RECORDING_ROLE)
                row_rect = self.list_view.visualRect(index).adjusted(8, 5, -8, -5)
                action = RecordingListDelegate.action_at(row_rect, event.position().toPoint(), rec)
                if action:
                    self._on_recording_action(rec, action)
                    return True
        return super().eventFilter(obj, event)

    def _update_list_cursor(self, pos, global_pos) -> None:
        index = self.list_view.indexAt(pos)
        if not index.isValid():
            self._set_hovered_list_action(None)
            self.list_view.viewport().unsetCursor()
            QToolTip.hideText()
            return

        rec = index.data(_RECORDING_ROLE)
        row_rect = self.list_view.visualRect(index).adjusted(8, 5, -8, -5)
        action = RecordingListDelegate.action_at(row_rect, pos, rec)
        if action:
            self._set_hovered_list_action((rec.rec_id, action))
            self.list_view.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
            tooltip = self.list_delegate.action_tooltip(action, rec)
            if tooltip:
                QToolTip.showText(global_pos, tooltip, self.list_view.viewport())
            else:
                QToolTip.hideText()
        else:
            self._set_hovered_list_action(None)
            self.list_view.viewport().unsetCursor()
            QToolTip.hideText()

    def _set_hovered_list_action(self, hovered_action: tuple[str, str] | None) -> None:
        if self._hovered_list_action == hovered_action:
            return

        old_hovered = self._hovered_list_action
        self._hovered_list_action = hovered_action
        self.list_delegate.hovered_action = hovered_action
        self._update_hovered_action_row(old_hovered)
        self._update_hovered_action_row(hovered_action)

    def _update_hovered_action_row(self, hovered_action: tuple[str, str] | None) -> None:
        if hovered_action is None:
            return

        rec_id, _ = hovered_action
        for row, rec in enumerate(self.list_model.recordings()):
            if rec.rec_id == rec_id:
                index = self.list_model.index(row, 0)
                self.list_view.viewport().update(self.list_view.visualRect(index))
                return

    def _toggle_view_mode(self) -> None:
        self._view_mode = "grid" if self._view_mode == "list" else "list"
        
        # Update icon and tooltip only (no text to avoid clipping in 36x36 btn)
        icon = "grid" if self._view_mode == "list" else "list"
        tip = self._l.get("toggle_view", "Switch View")

        apply_button_icon(self.view_toggle_btn, icon, size=16, color=theme_manager.get_color("text_sec"))
        self.view_toggle_btn.setToolTip(tip)

        if self._view_mode == "grid":
            self.list_view.hide()
            self.scroll.show()
            self._ensure_grid_cards()
            for card in self._cards.values():
                card.set_view_mode("grid")
        else:
            self.scroll.hide()
            self.list_view.show()
            self._clear_grid_cards()

        self._apply_filters()
        self._redraw_grid()

    def _on_search_changed(self, text):
        self._search_query = text
        self._apply_filters()

    def _on_filter_clicked(self):
        btn = self.sender()
        self._current_status_filter = btn.property("filter_key")
        self._apply_filters()

    def _on_platform_changed(self, index):
        self._current_platform_filter = self.platform_combo.itemData(index)
        self._apply_filters()

    def _apply_filters(self):
        """Apply search, status and platform filters to the active view."""
        visible = []
        for rec in self._all_recordings:
            match_status = RecordingFilters.matches_status(rec, self._current_status_filter)
            match_platform = RecordingFilters.matches_platform(rec, self._current_platform_filter)
            match_search = RecordingFilters.matches_search(rec, self._search_query)
            if match_status and match_platform and match_search:
                visible.append(rec)

        self._visible_recordings = self._sort_recordings(visible)

        if self._view_mode == "list":
            self.list_model.set_recordings(self._visible_recordings)
            self._update_badge_cache()
            self.list_view.viewport().update()
            return

        self._ensure_grid_cards()
        visible_ids = {rec.rec_id for rec in self._visible_recordings}
        for rec_id, card in self._cards.items():
            card.setVisible(rec_id in visible_ids)

        self._redraw_grid()

    def _on_theme_changed(self):
        for btn in self.filter_btns:
            if btn.property("filter_key") == "all":
                color = theme_manager.get_color("accent")
                btn.setStyleSheet(f"""
                    QPushButton[class="filter-btn"]:checked {{
                        background-color: {color};
                        border-color: {color};
                        color: white;
                    }}
                """)
        if hasattr(self, "_filter_bar_frame"):
            apply_elevation(self._filter_bar_frame, level=1)
        apply_button_icon(
            self.view_toggle_btn,
            "grid" if self._view_mode == "list" else "list",
            size=16,
            color=theme_manager.get_color("text_sec"),
        )
        apply_button_icon(self.refresh_btn, "refresh", size=16, color=theme_manager.get_color("text_sec"))
        apply_button_icon(self.batch_start_btn, "play", size=16, color=theme_manager.get_color("text_sec"))
        apply_button_icon(self.batch_stop_btn, "stop", size=16, color=theme_manager.get_color("text_sec"))
        apply_button_icon(self.add_btn, "add", size=16, color="#FFFFFF")
        self.list_view.viewport().update()

    def _update_platform_list(self):
        """Populate platform combo with existing platforms."""
        prev_data = self.platform_combo.currentData()
        self.platform_combo.blockSignals(True)
        self.platform_combo.clear()
        self.platform_combo.addItem(self.language.get("recording_card", {}).get("all", "All Platforms"), "all")
        
        platforms = {}
        for rec in self.app.record_manager.recordings:
            if rec.platform and rec.platform_key:
                platforms[rec.platform_key] = rec.platform
        
        for key, name in platforms.items():
            self.platform_combo.addItem(name, key)
            
        # Try to restore selection
        idx = self.platform_combo.findData(prev_data)
        if idx != -1:
            self.platform_combo.setCurrentIndex(idx)
            
        self.platform_combo.blockSignals(False)

    def refresh(self):
        """Force reload data from disk and rebuild cards."""
        # Stop any ongoing incremental loading
        if hasattr(self, "_load_timer") and self._load_timer.isActive():
            self._load_timer.stop()
            
        # Cleanup existing
        self._clear_grid_cards()
        
        # Load again (manager reload)
        self.app.record_manager.load_recordings()
        
        # Re-build UI
        self._load_data()
        self._update_platform_list()
        self._apply_filters()

    def _load_data(self):
        """Load recordings into the virtualized model; grid cards are created lazily."""
        self._all_recordings = self._sort_recordings(self.app.record_manager.recordings)
        logger.info(f"QtRecordingsView: Loaded {len(self._all_recordings)} recordings into virtual list model.")
        self._apply_filters()

    @staticmethod
    def _sort_recordings(recordings):
        return sorted(
            recordings,
            key=lambda r: (r.is_live, getattr(r, "priority_score", 0.0), r.streamer_name),
            reverse=True,
        )

    def _process_load_batch(self, batch_size=10):
        """Create and add a batch of cards to the view."""
        if not hasattr(self, "_pending_recordings") or not self._pending_recordings:
            if hasattr(self, "_load_timer"):
                self._load_timer.stop()
            return

        batch = self._pending_recordings[:batch_size]
        self._pending_recordings = self._pending_recordings[batch_size:]
        
        start_index = len(self._cards)
        for i, rec in enumerate(batch):
            self._add_card(rec, start_index + i)
            
        # Update layout and filters for the new cards
        self._apply_filters()
        
        if not self._pending_recordings and hasattr(self, "_load_timer"):
            self._load_timer.stop()
            logger.debug("QtRecordingsView: Incremental loading finished.")

    def _add_card(self, recording, index):
        """Create and add a card for a recording."""
        # IMPORTANT: pass self.card_container as the parent.
        # Without a parent, Qt treats the card as a top-level window.
        # Calling setVisible(True) on a parentless widget SHOWS it as a
        # floating window -- causing the 'popup storm' on startup.
        card = QtRecordingCard(recording, self.app, parent=self.card_container)
        card.set_view_mode(self._view_mode)
        card.hide()  # Start hidden; _apply_filters will show as needed
        self._cards[recording.rec_id] = card

    def _ensure_grid_cards(self) -> None:
        """Create QWidget cards only when the user actually enters grid mode."""
        known_ids = {rec.rec_id for rec in self._all_recordings}
        for rec_id in list(self._cards):
            if rec_id not in known_ids:
                card = self._cards.pop(rec_id)
                self.grid_layout.removeWidget(card)
                card.deleteLater()

        for index, recording in enumerate(self._all_recordings):
            if recording.rec_id not in self._cards:
                self._add_card(recording, index)

    def _clear_grid_cards(self) -> None:
        """Drop heavy card widgets when returning to the virtualized list mode."""
        for card in list(self._cards.values()):
            self.grid_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        self._last_grid_state = None

    def _subscribe_events(self):
        """Subscribe to EventBus to react to data changes."""
        self.app.event_bus.subscribe("update", self._on_recording_updated)
        self.app.event_bus.subscribe("add", self._on_recording_added)
        self.app.event_bus.subscribe("delete", self._on_recording_deleted)

    def _on_recording_updated(self, topic, recording):
        """Handle 'update' event from EventBus."""
        for idx, existing in enumerate(self._all_recordings):
            if existing.rec_id == recording.rec_id:
                self._all_recordings[idx] = recording
                break
        else:
            self._all_recordings.append(recording)

        if recording.rec_id in self._cards:
            card = self._cards[recording.rec_id]
            card.recording = recording
            card.update_content()

        # Automatically re-apply filters so if a row no longer matches, it hides
        self._apply_filters()

    def _on_refresh_tick(self):
        """Called every second to update durations/status of visible cards."""
        self._update_badge_cache()
        if self._view_mode == "list":
            self.list_model.refresh_all()

    def _update_badge_cache(self) -> None:
        """Refresh visible cards; badge cache is populated by operational cycle events."""
        for card in self._cards.values():
            if card.isVisible():
                card.update_content()

    def _on_recording_added(self, topic, recording):
        """Handle 'add' event from EventBus."""
        if not any(rec.rec_id == recording.rec_id for rec in self._all_recordings):
            self._all_recordings.append(recording)
            self._all_recordings = self._sort_recordings(self._all_recordings)
        if self._view_mode == "grid":
            self._add_card(recording, len(self._cards))
        self._update_platform_list()
        self._apply_filters()

    def _on_recording_deleted(self, topic, recordings):
        """Handle 'delete' event from EventBus."""
        # Remove deleted cards
        if not isinstance(recordings, list):
            recordings = [recordings]
            
        for rec in recordings:
            rec_id = getattr(rec, "rec_id", rec)
            self._all_recordings = [item for item in self._all_recordings if item.rec_id != rec_id]
            if rec_id in self._cards:
                card = self._cards.pop(rec_id)
                self.grid_layout.removeWidget(card)
                card.deleteLater()
        
        # Redraw grid to fill gaps
        self._update_platform_list()
        self._apply_filters()

    def _on_add_stream_clicked(self):
        """Open the Add Stream dialog."""
        from app.qt.components.add_stream_dialog import QtAddStreamDialog
        dialog = QtAddStreamDialog(self.app, self)
        if dialog.exec():
            # Data should be added via the dialog and published to EventBus
            pass

    def _redraw_grid(self) -> None:
        """Rearrange visible cards in the grid layout."""
        if self._view_mode == "list":
            return

        width = self.scroll.viewport().width()
        if width < 100:
            width = self.width() or 1000

        cols   = max(1, (width - 10) // 335)
        card_w = 320
        card_h = 165

        visible = [c for c in self._cards.values() if c.isVisible()]

        # Sort the visible cards to guarantee the desired order
        visible.sort(
            key=lambda c: (c.recording.is_live, getattr(c.recording, 'priority_score', 0.0), c.recording.streamer_name),
            reverse=True
        )

        # Check if we need to redraw by comparing state
        current_state = (cols, card_w, self._view_mode, [id(c) for c in visible])
        if getattr(self, "_last_grid_state", None) == current_state:
            return
        self._last_grid_state = current_state

        self.card_container.setUpdatesEnabled(False)
        try:
            for i, card in enumerate(visible):
                self.grid_layout.removeWidget(card)
                if self._view_mode == "list":
                    card.setFixedWidth(card_w)
                    card.setFixedHeight(card_h)
                else:
                    card.setFixedSize(card_w, card_h)
                row = i // cols
                col = i % cols
                self.grid_layout.addWidget(card, row, col)
        finally:
            self.card_container.setUpdatesEnabled(True)

    def _visible_recording_items(self) -> list:
        if self._view_mode == "list":
            return list(self._visible_recordings)
        return [card.recording for card in self._cards.values() if card.isVisible()]

    def _on_recording_action(self, rec, name: str) -> None:
        logger.debug(f"Virtual row {rec.rec_id}: '{name}'")

        if name == "folder":
            path = getattr(rec, "recording_dir", None) or self.app.settings.get_video_save_path()
            from app.utils import utils

            utils.open_folder(path)

        elif name == "play":
            if RecordingStateLogic.is_actively_recording(rec):
                self.app.record_manager.stop_recording(rec, manually_stopped=True)
                self.app.event_bus.publish("update", rec)
                self.app.event_bus.run_task(self.app.record_manager.persist_recordings)
            elif RecordingStateLogic.has_active_session(rec):
                self.app.event_bus.run_task(self.app.record_manager.stop_monitor_recording, rec)
            else:
                self.app.event_bus.run_task(self.app.record_manager.start_monitor_recording, rec)

        elif name == "stop_monitoring":
            if RecordingStateLogic.should_show_stop_monitoring_action(rec):
                self.app.event_bus.run_task(self.app.record_manager.stop_monitor_recording, rec)

        elif name == "favorite":
            rec.is_favorite = not bool(getattr(rec, "is_favorite", False))
            self.app.event_bus.publish("update", rec)
            self.app.event_bus.run_task(self.app.record_manager.persist_recordings)

        elif name == "preview":
            self._preview_recording(rec)

        elif name == "delete":
            from app.qt.components.confirm_dialog import QtConfirmDialog

            if QtConfirmDialog.confirm(
                self,
                "Confirm Delete",
                f"Are you sure you want to delete '{rec.streamer_name}'?",
                "This will stop any active recordings for this stream.",
                type="danger",
            ):
                self.app.event_bus.run_task(self.app.record_manager.remove_recording, rec)
                self.app.event_bus.publish("delete", rec)
                if hasattr(self.app.main_window, "show_toast"):
                    self.app.main_window.show_toast(
                        tr("toast.deleted_stream", default="Deleted: {streamer_name}").format(
                            streamer_name=rec.streamer_name
                        ),
                        "info",
                    )

        elif name == "edit":
            self._open_edit_dialog(rec)

        elif name == "info":
            self._open_info_dialog(rec)

    def _preview_recording(self, rec) -> None:
        path = getattr(rec, "recording_dir", None)
        if not path or not os.path.exists(path):
            return

        from app.utils import utils

        prefix = utils.clean_name(rec.streamer_name)
        videos = []
        for root, _, files in os.walk(path):
            for file_name in files:
                if utils.is_valid_video_file(file_name) and prefix in file_name:
                    videos.append(os.path.join(root, file_name))
        if videos:
            videos.sort(key=os.path.getmtime, reverse=True)
            player = self.app.main_window.get_video_player()
            self.app.event_bus.run_task(player.preview_video, videos[0], room_url=rec.url)

    def _open_edit_dialog(self, rec) -> None:
        try:
            from app.qt.components.add_stream_dialog import QtAddStreamDialog

            dialog = QtAddStreamDialog(self.app, self, recording=rec)
            dialog.exec()
        except Exception as exc:
            logger.warning(f"Edit dialog error: {exc}")

    def _open_info_dialog(self, rec) -> None:
        try:
            from app.qt.components.recording_info_dialog import QtRecordingInfoDialog

            dialog = QtRecordingInfoDialog(self.app, rec, self)
            dialog.exec()
        except Exception as exc:
            logger.warning(f"Info dialog error: {exc}")

    def _on_batch_start_clicked(self):
        """Start monitoring for all currently visible recordings."""
        visible_recordings = self._visible_recording_items()
        if not visible_recordings:
            return
            
        import asyncio

        from PySide6.QtCore import QTimer
        
        # Disable buttons temporarily
        self.batch_start_btn.setEnabled(False)
        self.batch_stop_btn.setEnabled(False)
        QTimer.singleShot(1500, lambda: self.batch_start_btn.setEnabled(True))
        QTimer.singleShot(1500, lambda: self.batch_stop_btn.setEnabled(True))
        
        # Show toast
        from app.qt.main_window import MainWindow
        main_window = self.window()
        if isinstance(main_window, MainWindow):
            message = tr(
                "toast.starting_monitor",
                default="Starting monitor for {count} visible stream(s)...",
            ).format(count=len(visible_recordings))
            main_window.show_toast(message, duration=3000)
            
        asyncio.ensure_future(self.app.record_manager.start_monitor_recordings(visible_recordings))

    def _on_batch_stop_clicked(self):
        """Stop monitoring for all currently visible recordings."""
        visible_recordings = self._visible_recording_items()
        if not visible_recordings:
            return
            
        import asyncio

        from PySide6.QtCore import QTimer
        
        # Disable buttons temporarily
        self.batch_start_btn.setEnabled(False)
        self.batch_stop_btn.setEnabled(False)
        QTimer.singleShot(1500, lambda: self.batch_start_btn.setEnabled(True))
        QTimer.singleShot(1500, lambda: self.batch_stop_btn.setEnabled(True))
        
        # Show toast
        from app.qt.main_window import MainWindow
        main_window = self.window()
        if isinstance(main_window, MainWindow):
            message = tr(
                "toast.stopping_monitor",
                default="Stopping monitor for {count} visible stream(s)...",
            ).format(count=len(visible_recordings))
            main_window.show_toast(message, duration=3000)
            
        asyncio.ensure_future(self.app.record_manager.stop_monitor_recordings(visible_recordings))
