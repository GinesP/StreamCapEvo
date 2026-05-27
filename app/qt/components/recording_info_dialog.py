"""
Qt Recording Info Dialog — StreamCapEvo.
Detailed view of stream metadata and intelligence stats.
"""

import ctypes
import sys
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
    QScrollArea,
    QWidget,
    QGridLayout,
    QGroupBox,
)

from app.qt.themes.theme import theme_manager
from app.qt.utils.elevation import apply_elevation
from app.utils.i18n import tr
from app.models.recording.recording_status_model import RecordingStatus
from app.core.recording.precog import Precog


class QtRecordingInfoDialog(QDialog):
    def __init__(self, app_context, recording, parent=None):
        super().__init__(parent)
        self.app = app_context
        self.rec = recording
        self.setObjectName("recordingInfoDialog")

        self.setWindowTitle(f"{tr('recording_info.modal_title', default='Recording Information')} — {self.rec.streamer_name}")
        self.setMinimumWidth(450)
        self.setMinimumHeight(500)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        apply_elevation(self, level=2)

        self._setup_ui()
        self._apply_styles()
        theme_manager.themeChanged.connect(self._on_theme_changed)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(15)

        color = "#4CAF50" if self.rec.is_live else "#757575"
        letter = self.rec.streamer_name[0].upper() if self.rec.streamer_name else "?"

        avatar = QLabel(letter)
        avatar.setFixedSize(60, 60)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            f"""
            background: #4A4A6A;
            color: #E1E1E1;
            border-radius: 30px;
            font-size: 24px;
            font-weight: bold;
            border: 2px solid {color};
            """
        )
        header.addWidget(avatar)

        title_v = QVBoxLayout()
        name_lbl = QLabel(self.rec.streamer_name)
        name_lbl.setStyleSheet(f"font-size: 20px; font-weight: 700; color: {theme_manager.get_color('text')};")
        title_v.addWidget(name_lbl)

        status_lbl = QLabel(self._translate_status(self.rec.status_info))
        status_lbl.setStyleSheet(f"color: {color}; font-weight: 600;")
        title_v.addWidget(status_lbl)
        header.addLayout(title_v)
        header.addStretch()

        layout.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("recordingInfoScroll")

        container = QWidget()
        container.setObjectName("recordingInfoContainer")
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        container_lay = QVBoxLayout(container)
        container_lay.setContentsMargins(0, 0, 0, 0)
        container_lay.setSpacing(15)

        self._add_section(
            container_lay,
            tr("recording_info.config_section", default="Configuration"),
            [
                (tr("recording_card.live_link", default="URL"), self.rec.url),
                (tr("recording_card.platform_name", default="Platform"), getattr(self.rec, "platform", "N/A") or tr("recording_info.unknown", default="Unknown")),
                (tr("recording_card.record_quality", default="Quality"), getattr(self.rec, "quality", "OD")),
                (tr("recording_card.record_format", default="Format"), getattr(self.rec, "record_format", "ts")),
                (tr("recording_card.save_path", default="Save Path"), getattr(self.rec, "recording_dir", None) or tr("recording_info.default_path", default="Default")),
            ],
        )

        added_at = self._format_datetime_for_language(getattr(self.rec, "added_at", None))
        last_seen = self._format_datetime_for_language(getattr(self.rec, "last_seen_live", None))
        if not last_seen:
            last_seen = tr("recording_info.never", default="Never")

        consistency = getattr(self.rec, "consistency_score", 0.0)
        priority = getattr(self.rec, "priority_score", 0.0)

        stats_items = [
            (tr("recording_info.consistency", default="Consistency"), f"{consistency:.1%}"),
            (tr("recording_info.priority_score", default="Priority Score"), f"{priority:.4f}"),
        ]

        if added_at:
            stats_items.append((tr("recording_card.added_at", default="Added at"), added_at))

        avg_min = getattr(self.rec, "avg_session_duration_minutes", None)
        avg_session_str = self._format_duration(avg_min) if avg_min is not None else tr("recording_info.never", default="Never")

        prediction = Precog.predict(self.rec)
        forecast = prediction.forecast_details
        next_slot_text = forecast.get("next_slot_text") or ""
        window_text = forecast.get("window_text") or ""
        if next_slot_text and window_text:
            next_window_str = f"{window_text}"
        elif next_slot_text:
            next_window_str = next_slot_text
        else:
            next_window_str = tr("recording_info.never", default="Never")

        stats_items.extend([
            (tr("recording_info.last_seen_live", default="Last Seen Live"), last_seen),
            (tr("recording_info.checks_count", default="Checks Count"), str(getattr(self.rec, "live_check_count", 0))),
            (tr("recording_info.found_live", default="Found Live"), str(getattr(self.rec, "live_found_count", 0))),
            (tr("recording_info.avg_session", default="Avg Session Duration"), avg_session_str),
            (tr("recording_info.next_window", default="Next Window"), next_window_str),
        ])

        self._add_section(
            container_lay,
            tr("recording_info.stats_section", default="Intelligence & Stats"),
            stats_items,
        )

        scroll.setWidget(container)
        layout.addWidget(scroll)

        btns = QHBoxLayout()

        folder_btn = QPushButton(tr("recording_card.open_folder", default="Open Folder"))
        folder_btn.setProperty("class", "secondary")
        folder_btn.clicked.connect(self._on_open_folder)

        close_btn = QPushButton(tr("recording_info.close", default="Close"))
        close_btn.setProperty("class", "primary")
        close_btn.clicked.connect(self.accept)

        btns.addWidget(folder_btn)
        btns.addStretch()
        btns.addWidget(close_btn)
        layout.addLayout(btns)

    def _add_section(self, parent_lay, title, items):
        group = QGroupBox(title.upper())
        vlay = QVBoxLayout(group)
        vlay.setContentsMargins(15, 36, 15, 15)

        grid = QGridLayout()
        grid.setSpacing(10)

        for i, (key, val) in enumerate(items):
            key_lbl = QLabel(f"{key}:")
            key_lbl.setStyleSheet(f"color: {theme_manager.get_color('text_sec')}; font-weight: 600;")
            value_text = str(val)
            val_lbl = QLabel(value_text)
            val_lbl.setWordWrap(True)

            if key == tr("recording_card.live_link", default="URL") and value_text:
                safe_url = value_text.replace("&", "&amp;").replace('"', "&quot;")
                link_color = theme_manager.get_color("accent")
                val_lbl.setText(
                    f'<a href="{safe_url}" style="color: {link_color}; text-decoration: none;">{safe_url}</a>'
                )
                val_lbl.setTextFormat(Qt.TextFormat.RichText)
                val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
                val_lbl.setOpenExternalLinks(True)
                val_lbl.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            else:
                val_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

            grid.addWidget(key_lbl, i, 0)
            grid.addWidget(val_lbl, i, 1)

        grid.setColumnStretch(1, 1)
        vlay.addLayout(grid)
        parent_lay.addWidget(group)

    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QDialog#recordingInfoDialog {{
                background: {theme_manager.get_color('surface')};
                border: 1px solid {theme_manager.get_color('border')};
                border-radius: 0px;
            }}
            QScrollArea#recordingInfoScroll,
            QScrollArea#recordingInfoScroll > QWidget > QWidget,
            QWidget#recordingInfoContainer {{
                background: {theme_manager.get_color('surface')};
                border: none;
            }}
            QGroupBox {{
                background: {theme_manager.get_color('card')};
                border: 1px solid {theme_manager.get_color('border')};
                border-radius: 8px;
                margin-top: 0px;
            }}
            QGroupBox::title {{
                subcontrol-origin: border;
                subcontrol-position: top left;
                left: 15px;
                top: 10px;
                padding: 0;
                color: {theme_manager.get_color('text_sec')};
                font-weight: 700;
            }}
            """
        )

    def _on_open_folder(self):
        path = getattr(self.rec, "recording_dir", None) or self.app.settings.get_video_save_path()
        from app.utils import utils

        utils.open_folder(path)

    def _translate_status(self, status: str | None) -> str:
        if not status:
            return tr("recording_card.none", default="None")

        status_map = {
            RecordingStatus.STOPPED_MONITORING: tr("recording_card.no_monitor", default="Not Monitored"),
            RecordingStatus.MONITORING: tr("recording_card.offline", default="Offline"),
            RecordingStatus.RECORDING: tr("recording_card.recording", default="Recording"),
            RecordingStatus.NOT_RECORDING: tr("recording_card.not_live", default="Not Live"),
            RecordingStatus.STATUS_CHECKING: tr("recording_card.checking", default="Checking"),
            RecordingStatus.NOT_IN_SCHEDULED_CHECK: tr("recording_card.stopped", default="Stopped"),
            RecordingStatus.PREPARING_RECORDING: tr("recording_card.pre_record_tip", default="Preparing to start recording"),
            RecordingStatus.RECORDING_ERROR: tr("recording_card.recording_error", default="Recording Error"),
            RecordingStatus.NOT_RECORDING_SPACE: tr("recording_card.no_folder_tip", default="Folder does not exist"),
            RecordingStatus.LIVE_STATUS_CHECK_ERROR: tr("recording_card.recording_error", default="Recording Error"),
            RecordingStatus.LIVE_BROADCASTING: tr("recording_card.live_broadcasting", default="Live Broadcasting"),
        }
        return status_map.get(status, status)

    def _format_datetime_for_language(self, date_value: str | None) -> str | None:
        if not date_value:
            return None
        try:
            dt = datetime.fromisoformat(str(date_value).replace("Z", "+00:00"))
            if getattr(self.app, "language_code", "en") == "es":
                return dt.strftime("%d/%m/%Y %H:%M")
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(date_value)

    @staticmethod
    def _format_duration(total_minutes: float) -> str:
        """Format a duration in minutes to a human-friendly string like '1h 15m' or '45m'."""
        total_minutes = int(round(total_minutes))
        hours, minutes = divmod(total_minutes, 60)
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"

    def showEvent(self, event):
        super().showEvent(event)
        self._disable_native_rounded_corners()

    def _on_theme_changed(self):
        apply_elevation(self, level=2)
        self._apply_styles()

    def _disable_native_rounded_corners(self):
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
            if not hwnd:
                return
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_DONOTROUND = 1
            preference = ctypes.c_int(DWMWCP_DONOTROUND)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
        except Exception:
            pass
