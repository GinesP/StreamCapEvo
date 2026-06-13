"""
Qt Recording Card — StreamCapEvo.

Architecture:
  ┌─────────────────────────────────────────────────────────────────────┐
  │ QFrame (card)                                                       │
  │  ├─ stripe: QFrame (4px coloured left border)                      │
  │  └─ body: QWidget                                                   │
  │      ├─ [GRID LAYOUT - QVBoxLayout]  shown in grid mode            │
  │      │   ├─ top_row (avatar / name / status / badges)              │
  │      │   ├─ dates_lbl                                               │
  │      │   └─ action_bar (always created, shown/hidden on hover)     │
  │      └─ [LIST LAYOUT - QHBoxLayout]  shown in list mode            │
  │          ├─ avatar                                                   │
  │          ├─ info_col (name / status) ── stretch                    │
  │          ├─ badge_row                                               │
  │          └─ btn_row  (always visible)                               │
  └─────────────────────────────────────────────────────────────────────┘

Key design decisions
────────────────────
• Two inner QWidgets (grid_w / list_w) are show/hidden.  No effects on self.
• Shadow is drawn only in paintEvent to avoid QGraphicsEffect conflicts.
• Hover in grid  → show/hide action_bar via setVisible (no opacity effect).
• Hover in list  → card background colour shift via setProperty + repaint.
• _is_hovered initialised in __init__ so leaveEvent never crashes.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.recording.precog import Precog
from app.core.recording.recording_state_logic import RecordingStateLogic
from app.models.recording.recording_status_model import CardStateType
from app.qt.themes.theme import QUEUE_COLORS, theme_manager
from app.qt.utils.iconography import apply_button_icon
from app.qt.utils.typography import body_font
from app.utils.i18n import tr
from app.utils.logger import logger

# ── Palette ───────────────────────────────────────────────────────────────────

# These are state-specific accents
_STATUS_COLOR: dict[CardStateType, str] = {
    CardStateType.RECORDING: "#F44336",
    CardStateType.ERROR:     "#FF9800",
    CardStateType.LIVE:      "#4CAF50",
    CardStateType.OFFLINE:   "#9E9E9E",
    CardStateType.STOPPED:   "#607D8B",
    CardStateType.CHECKING:  "#2196F3",
}

_QUEUE_BADGE_COLORS: dict[str, str] = {
    "F": QUEUE_COLORS["fast"],
    "M": QUEUE_COLORS["medium"],
    "S": QUEUE_COLORS["slow"],
}


# ── Helpers ───────────────────────────────────────────────────────────────────

class _Avatar(QLabel):
    """40 px circular avatar widget with letter placeholder."""

    def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sz  = size
        self._bg  = "#4A4A6A"
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(body_font(max(8, size // 3), QFont.Weight.Bold))
        self._refresh_style()

    def _refresh_style(self) -> None:
        r = self._sz // 2
        self.setStyleSheet(
            f"border-radius:{r}px; background:{self._bg};"
            f" color:#E1E1E1; border:none;"
        )

    def set_letter(self, char: str, bg: str = "#4A4A6A") -> None:
        self._bg = bg
        self._refresh_style()
        self.setText(char.upper())


class _Badge(QFrame):
    """Small coloured pill badge: text on a solid colour."""

    def __init__(
        self, text: str, color: str, tip: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setToolTip(tip)
        self.setFixedHeight(20)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(7, 0, 7, 0)
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#fff; font-size:10px; font-weight:700; background:transparent;"
        )
        lay.addWidget(lbl)
        self.setStyleSheet(
            f"background:{color}; border-radius:5px; border:none;"
        )


def _mk_btn(icon_name: str, tip: str, parent: QWidget) -> QPushButton:
    """Create a small icon action button with premium styling."""
    b = QPushButton(parent)
    b.setToolTip(tip)
    b.setFixedSize(38, 26)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    apply_button_icon(b, icon_name, size=14, color=theme_manager.get_color("text_sec"))
    
    accent = theme_manager.get_color("accent")
    text_sec = theme_manager.get_color("text_sec")
    border = theme_manager.get_color("border")
    surface = theme_manager.get_color("surface2")
    
    b.setStyleSheet(f"""
        QPushButton {{
            background: transparent;
            color: {text_sec};
            border: none;
            border-radius: 4px;
            padding: 4px;
            margin: 0;
        }}
        QPushButton:hover {{
            background: {accent}33;
            color: {accent};
        }}
        QPushButton:pressed {{
            background: {accent}66;
        }}
    """)
    return b


# ── Card ──────────────────────────────────────────────────────────────────────

_ACTION_DEFS = [
    ("folder", "folder"),
    ("play", "play"),
    ("stop_monitoring", "pause"),
    ("favorite", "favorite_off"),
    ("preview", "preview"),
    ("edit", "edit"),
    ("info", "info"),
    ("delete", "delete"),
]


def _action_tip(name: str) -> str:
    tips = {
        "folder":          tr("recording_card.open_folder", default="Open Folder"),
        "play":            tr("recording_card.start_monitor", default="Start Monitoring"),
        "stop_monitoring": tr("recording_card.stop_monitor", default="Stop Monitoring"),
        "favorite":        tr("recording_card.favorite", default="Mark as favorite"),
        "preview":         tr("recording_card.preview", default="Preview"),
        "edit":            tr("recording_card.edit_record_config", default="Edit Recording Configuration"),
        "info":            tr("recording_card.recording_info", default="Recording Information"),
        "delete":          tr("recording_card.delete_monitor", default="Delete Monitoring"),
    }
    return tips.get(name, "")


class QtRecordingCard(QFrame):
    """
    Dual-mode recording card (list / grid).

    Call ``set_view_mode("list")`` or ``set_view_mode("grid")`` to switch.
    The card starts in list mode.
    """

    def __init__(
        self,
        recording,
        app_context,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.recording   = recording
        self.app         = app_context
        self._hovered    = False
        self._mode       = "list"
        self._status_color = theme_manager.get_color("card")
        self._play_icon_key = "play"
        
        # Subscribe to theme changes
        theme_manager.themeChanged.connect(self.update)

        self._build()
        self.update_content()

    # ─────────────────────────────────────────────────────────────────────────
    # Build
    # ─────────────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self.setObjectName(f"rec_card_{self.recording.rec_id}")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._grid_w = self._build_grid()
        self._list_w = self._build_list()

        root.addWidget(self._grid_w)
        root.addWidget(self._list_w)

        # Initial: list mode
        self._grid_w.hide()
        self._list_w.show()

    # ── Grid body ─────────────────────────────────────────────────────────────

    def _build_grid(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 12, 12, 10) # 18px left margin to make room for indicator
        lay.setSpacing(5)

        # Top row
        top = QHBoxLayout()
        top.setSpacing(10)
        self._g_av = _Avatar(40, w)
        top.addWidget(self._g_av)

        info = QVBoxLayout()
        info.setSpacing(2)
        self._g_name   = QLabel(parent=w)
        self._g_name.setStyleSheet(
            "font-weight:700; font-size:13px; background:transparent; color:#E1E1E1;"
        )
        self._g_name.setWordWrap(False)
        info.addWidget(self._g_name)

        status_row = QHBoxLayout()
        self._g_status = QLabel(parent=w)
        self._g_status.setStyleSheet(
            "font-size:11px; font-weight:600; background:transparent;"
        )
        self._g_dur = QLabel(parent=w)
        self._g_dur.setStyleSheet(
            "font-size:10px; color:#777; background:transparent;"
        )
        status_row.addWidget(self._g_status)
        status_row.addWidget(self._g_dur)
        status_row.addStretch()
        info.addLayout(status_row)
        top.addLayout(info, 1)

        self._g_badge_row = QHBoxLayout()
        self._g_badge_row.setSpacing(4)
        top.addLayout(self._g_badge_row)
        lay.addLayout(top)

        # Dates
        self._g_dates = QLabel(parent=w)
        self._g_dates.setStyleSheet(
            "font-size:10px; color:#666; background:transparent;"
        )
        lay.addWidget(self._g_dates)
        lay.addStretch()

        # Action bar — hidden initially, shown on hover
        self._g_actions = QWidget(w)
        self._g_actions.setStyleSheet("background:transparent;")
        ab = QHBoxLayout(self._g_actions)
        ab.setContentsMargins(0, 0, 0, 0)
        ab.setSpacing(3)

        self._g_btns: dict[str, QPushButton] = {}
        for name, icon_key in _ACTION_DEFS:
            btn = _mk_btn(icon_key, _action_tip(name), self._g_actions)
            btn.clicked.connect(lambda _, n=name: self._on_action(n))
            ab.addWidget(btn)
            self._g_btns[name] = btn
        ab.addStretch()

        self._g_actions.hide()   # hidden until hover
        lay.addWidget(self._g_actions)
        return w

    # ── List body ─────────────────────────────────────────────────────────────

    def _build_list(self) -> QWidget:
        w = QWidget()
        w.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(16, 0, 10, 0) # 16px left margin
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self._l_av = _Avatar(36, w)
        lay.addWidget(self._l_av)

        # Info
        info = QVBoxLayout()
        info.setSpacing(1)
        self._l_name = QLabel(parent=w)
        self._l_name.setStyleSheet(
            "font-weight:700; font-size:13px; background:transparent; color:#E1E1E1;"
        )
        info.addWidget(self._l_name)

        status_row = QHBoxLayout()
        self._l_status = QLabel(parent=w)
        self._l_status.setStyleSheet(
            "font-size:11px; font-weight:600; background:transparent;"
        )
        self._l_dur = QLabel(parent=w)
        self._l_dur.setStyleSheet(
            "font-size:10px; color:#777; background:transparent;"
        )
        status_row.addWidget(self._l_status)
        status_row.addWidget(self._l_dur)
        status_row.addStretch()
        info.addLayout(status_row)
        lay.addLayout(info, 1)

        # Badges
        self._l_badge_row = QHBoxLayout()
        self._l_badge_row.setSpacing(4)
        self._l_badge_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(self._l_badge_row)

        # Action buttons — always visible in list mode
        btn_w = QWidget(w)
        btn_w.setStyleSheet("background:transparent;")
        btn_lay = QHBoxLayout(btn_w)
        btn_lay.setContentsMargins(4, 0, 4, 0)
        btn_lay.setSpacing(3)

        self._l_btns: dict[str, QPushButton] = {}
        for name, icon_key in _ACTION_DEFS:
            btn = _mk_btn(icon_key, _action_tip(name), btn_w)
            btn.clicked.connect(lambda _, n=name: self._on_action(n))
            btn_lay.addWidget(btn)
            self._l_btns[name] = btn

        lay.addWidget(btn_w)
        return w

    # ─────────────────────────────────────────────────────────────────────────
    # Mode
    # ─────────────────────────────────────────────────────────────────────────

    def set_view_mode(self, mode: str) -> None:
        """Switch between 'list' (default) and 'grid'."""
        self._mode = mode
        if mode == "list":
            self._grid_w.hide()
            self._list_w.show()
            self.setFixedHeight(72)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)
        else:
            self._list_w.hide()
            self._grid_w.show()
            self._g_actions.hide()
            self.setFixedSize(320, 165)

    # ─────────────────────────────────────────────────────────────────────────
    # Content
    # ─────────────────────────────────────────────────────────────────────────

    def update_content(self) -> None:
        rec = self.recording

        state = RecordingStateLogic.get_card_state(rec)
        color = _STATUS_COLOR.get(state, "#546E7A")
        self._status_color = color

        # Title
        name = rec.streamer_name or tr("recording_card.unknown", default="Unknown")
        if RecordingStateLogic.should_show_live_title(rec):
            name = f"{name} — {rec.live_title}"

        if self._g_name.text() != name:
            self._g_name.setText(name)
            self._l_name.setText(name)

        # Duration
        dur = self.app.record_manager.get_duration(rec)
        show_duration = RecordingStateLogic.should_show_duration(rec)
        dur_t = f"  {dur}" if show_duration and dur != "00:00:00" else ""

        # Avatar letter
        letter = rec.streamer_name[0].upper() if rec.streamer_name else "?"

        if getattr(self, "_last_av_state", None) != (letter, color):
            self._g_av.set_letter(letter, color)
            self._l_av.set_letter(letter, color)
            self._last_av_state = (letter, color)

        status_text = rec.status_info or tr("recording_card.idle", default="Idle")
        if self._g_status.text() != status_text:
            self._g_status.setText(status_text)
            self._l_status.setText(status_text)
            
        status_style = f"color:{color}; font-size:11px; font-weight:600; background:transparent;"
        if getattr(self, "_last_status_style", None) != status_style:
            self._g_status.setStyleSheet(status_style)
            self._l_status.setStyleSheet(status_style)
            self._last_status_style = status_style

        if self._g_dur.text() != dur_t:
            self._g_dur.setText(dur_t)
            self._l_dur.setText(dur_t)

        added = getattr(rec, "added_at", "")
        added_text = f"{tr('recording_card.added_at', default='Added at')}: {added}" if added else ""
        if self._g_dates.text() != added_text:
            self._g_dates.setText(added_text)

        # play button
        play_btn_g = self._g_btns.get("play")
        play_btn_l = self._l_btns.get("play")
        stop_monitor_btn_g = self._g_btns.get("stop_monitoring")
        stop_monitor_btn_l = self._l_btns.get("stop_monitoring")
        
        if RecordingStateLogic.is_actively_recording(rec):
            icon_key, tip = "stop", tr("recording_card.stop_record", default="Stop Recording")
        elif rec.monitor_status:
            icon_key, tip = "pause", tr("recording_card.stop_monitor", default="Stop Monitoring")
        else:
            icon_key, tip = "play", tr("recording_card.start_monitor", default="Start Monitoring")
            
        if play_btn_g:
            apply_button_icon(play_btn_g, icon_key, size=14, color=theme_manager.get_color("text_sec"))
            play_btn_g.setToolTip(tip)
        if play_btn_l:
            apply_button_icon(play_btn_l, icon_key, size=14, color=theme_manager.get_color("text_sec"))
            play_btn_l.setToolTip(tip)

        show_stop_monitoring = RecordingStateLogic.should_show_stop_monitoring_action(rec)
        if stop_monitor_btn_g:
            stop_monitor_btn_g.setVisible(show_stop_monitoring)
            stop_monitor_btn_g.setToolTip(tr("recording_card.stop_monitor", default="Stop Monitoring"))
        if stop_monitor_btn_l:
            stop_monitor_btn_l.setVisible(show_stop_monitoring)
            stop_monitor_btn_l.setToolTip(tr("recording_card.stop_monitor", default="Stop Monitoring"))

        favorite_btn_g = self._g_btns.get("favorite")
        favorite_btn_l = self._l_btns.get("favorite")
        is_favorite = bool(getattr(rec, "is_favorite", False))
        fav_icon = "favorite_on" if is_favorite else "favorite_off"
        fav_tip = (
            tr("recording_card.unfavorite", default="Remove from favorites")
            if is_favorite
            else tr("recording_card.favorite", default="Mark as favorite")
        )
        fav_color = "#E53935"
        if favorite_btn_g:
            apply_button_icon(favorite_btn_g, fav_icon, size=14, color=fav_color)
            favorite_btn_g.setToolTip(fav_tip)
        if favorite_btn_l:
            apply_button_icon(favorite_btn_l, fav_icon, size=14, color=fav_color)
            favorite_btn_l.setToolTip(fav_tip)

        # Badges
        self._fill_badges(rec, self._g_badge_row, self, "grid")
        self._fill_badges(rec, self._l_badge_row, self, "list")


    @staticmethod
    def _fill_badges(rec, layout: QHBoxLayout, card_instance: QtRecordingCard, prefix: str) -> None:
        snap = getattr(rec, "_last_snapshot", None)
        if snap is not None:
            q_t = snap.queue_key
            q_c = _QUEUE_BADGE_COLORS.get(q_t, "#9E9E9E")
            score = snap.likelihood
            is_stale = snap.is_stale
        else:
            q_t = Precog.stable_queue_key(rec)
            q_c = _QUEUE_BADGE_COLORS.get(q_t, "#9E9E9E")
            score = 0.0
            is_stale = RecordingStateLogic.is_stale(rec)

        cache_attr = f"_badge_state_{prefix}"
        current_state = (q_t, q_c, score, is_stale)
        if getattr(card_instance, cache_attr, None) == current_state:
            return
        setattr(card_instance, cache_attr, current_state)

        while layout.count():
            item = layout.takeAt(0)
            if w := item.widget():
                w.setParent(None)  # safe deletion in layout context
                w.deleteLater()

        layout.addWidget(_Badge(q_t, q_c, tr("recording_card.queue_badge_tip", default="Queue speed")))

        if score > 0:
            l_t = (
                tr("recording_card.likelihood_high", default="High")
                if score >= 0.8
                else tr("recording_card.likelihood_normal", default="Normal")
            )
            l_c = "#4CAF50" if score >= 0.8 else "#42A5F5"
            badge_tip = tr(
                "recording_card.likelihood_with_score",
                default="Likelihood {score}",
            ).format(score=f"{score:.0%}")
            layout.addWidget(_Badge(l_t, l_c, badge_tip))

        if is_stale:
            layout.addWidget(
                _Badge(
                    tr("recording_card.stale_badge", default="30D"),
                    "#EF6C00",
                    tr(
                        "recording_card.stale_badge_tip",
                        default="Not seen live for over 30 days",
                    ),
                )
            )


    # ─────────────────────────────────────────────────────────────────────────
    # Painting  (card background + shadow drawn here to avoid effect conflicts)
    # ─────────────────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:                    # noqa: N802
        p = QPainter(self)
        p.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.TextAntialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )
        
        c = theme_manager.colors
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2) # Leave space for focus/hover glow
        radius = 10.0

        # Hover logic
        bg_color = c["card_hover"] if self._hovered else c["card"]
        border_color = c["accent"] if self._hovered else c["border"]
        border_width = 1.5 if self._hovered else 1.0
        
        # 1. Shadow (Subtle lift on hover)
        if self._hovered:
            shadow_color = QColor(0, 0, 0, 80)
            for i in range(1, 4):
                p.setPen(QPen(QColor(0, 0, 0, 20 // i), 1))
                p.drawRoundedRect(r.adjusted(i, i, -i, -i), radius, radius)

        # 2. Main background
        p.setPen(QPen(QColor(border_color), border_width))
        p.setBrush(QBrush(QColor(bg_color)))
        p.drawRoundedRect(r, radius, radius)
        
        # 3. Glow effect on hover (Brand color glow)
        if self._hovered:
            glow = QColor(c["accent"])
            glow.setAlpha(30)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(glow))
            p.drawRoundedRect(r, radius, radius)

        # 4. Status indicator pill (The modern way)
        # Instead of a chunky bar, we draw a subtle floating vertical pill
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(self._status_color)))

        # Determine pill geometry based on mode
        if self._mode == "list":
            # Narrow vertical pill centered on the left
            pill_w = 4
            pill_h = r.height() * 0.4
            pill_x = r.x() + 6
            pill_y = r.y() + (r.height() - pill_h) / 2
        else:
            # Slightly longer pill for grid cards
            pill_w = 4
            pill_h = r.height() * 0.3
            pill_x = r.x() + 6
            pill_y = r.y() + 20
        
        p.drawRoundedRect(pill_x, pill_y, pill_w, pill_h, 2, 2)

    # ─────────────────────────────────────────────────────────────────────────
    # Hover
    # ─────────────────────────────────────────────────────────────────────────

    def enterEvent(self, event) -> None:                    # noqa: N802
        self._hovered = True
        self.update()                       # repaint for bg change
        if self._mode == "grid":
            self._g_actions.show()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:                    # noqa: N802
        self._hovered = False
        self.update()
        if self._mode == "grid":
            self._g_actions.hide()
        super().leaveEvent(event)

    # ─────────────────────────────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────────────────────────────

    def _on_action(self, name: str) -> None:
        rec = self.recording
        logger.debug(f"Card {rec.rec_id}: '{name}'")

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
                self.app.event_bus.run_task(
                    self.app.record_manager.stop_monitor_recording, rec
                )
            else:
                self.app.event_bus.run_task(
                    self.app.record_manager.start_monitor_recording, rec
                )

        elif name == "stop_monitoring":
            if RecordingStateLogic.should_show_stop_monitoring_action(rec):
                self.app.event_bus.run_task(
                    self.app.record_manager.stop_monitor_recording, rec
                )

        elif name == "favorite":
            rec.is_favorite = not bool(getattr(rec, "is_favorite", False))
            self.app.event_bus.publish("update", rec)
            self.app.event_bus.run_task(self.app.record_manager.persist_recordings)

        elif name == "preview":
            path = getattr(rec, "recording_dir", None)
            if path and os.path.exists(path):
                from app.utils import utils
                prefix = utils.clean_name(rec.streamer_name)
                videos = []
                for root, _, files in os.walk(path):
                    for f in files:
                        if utils.is_valid_video_file(f) and prefix in f:
                            videos.append(os.path.join(root, f))
                if videos:
                    videos.sort(key=os.path.getmtime, reverse=True)
                    player = self.app.main_window.get_video_player()
                    self.app.event_bus.run_task(
                        player.preview_video, videos[0], room_url=rec.url
                    )

        elif name == "delete":
            from app.qt.components.confirm_dialog import QtConfirmDialog
            if QtConfirmDialog.confirm(
                self,
                tr("recording_card.confirm_delete_title", default="Confirm Delete"),
                tr(
                    "recording_card.confirm_delete_body",
                    default="Are you sure you want to delete '{streamer_name}'?",
                ).format(streamer_name=rec.streamer_name),
                tr(
                    "recording_card.confirm_delete_detail",
                    default="This will stop any active recordings for this stream.",
                ),
                type="danger"
            ):
                self.app.event_bus.run_task(
                    self.app.record_manager.remove_recording, rec
                )
                self.app.event_bus.publish("delete", rec)
                if hasattr(self.app.main_window, "show_toast"):
                    msg = tr(
                        "toast.deleted_stream",
                        default="Deleted: {streamer_name}",
                    ).format(streamer_name=rec.streamer_name)
                    self.app.main_window.show_toast(msg, "info")

        elif name == "edit":
            self._open_edit_dialog()

        elif name == "info":
            self._open_info_dialog()

    def _open_edit_dialog(self) -> None:
        try:
            from app.qt.components.add_stream_dialog import QtAddStreamDialog
            dialog = QtAddStreamDialog(self.app, self, recording=self.recording)
            dialog.exec()
        except Exception as exc:
            logger.warning(f"Edit dialog error: {exc}")

    def _open_info_dialog(self) -> None:
        try:
            from app.qt.components.recording_info_dialog import QtRecordingInfoDialog
            dialog = QtRecordingInfoDialog(self.app, self.recording, self)
            dialog.exec()
        except Exception as exc:
            logger.warning(f"Info dialog error: {exc}")
