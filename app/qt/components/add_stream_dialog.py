"""
Qt Add Stream Dialog for StreamCapEvo — Expanded Version.
"""

import ctypes
import os
import sys
import uuid
from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QFrame, QMessageBox, QCheckBox,
    QSpinBox, QTimeEdit, QTabWidget, QWidget, QFileDialog,
    QGroupBox, QFormLayout
)

from app.utils.logger import logger
from app.models.recording.recording_model import Recording
from app.core.platforms.platform_handlers import get_platform_info
from app.qt.themes.theme import theme_manager
from app.qt.utils.elevation import apply_elevation
from app.utils.i18n import tr


class QtAddStreamDialog(QDialog):
    def __init__(self, app_context, parent=None, recording=None):
        super().__init__(parent)
        self.app = app_context
        self.recording = recording
        self.is_edit = self.recording is not None
        self.setObjectName("addStreamDialog")
        
        self.setWindowTitle(
            tr("add_stream_dialog.window_title_edit", default="Edit Stream")
            if self.is_edit else
            tr("add_stream_dialog.window_title_add", default="Add New Stream")
        )
        self.setMinimumWidth(500)
        self.setMinimumHeight(450)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        apply_elevation(self, level=2)
        
        self._setup_ui()
        self._apply_styles()
        theme_manager.themeChanged.connect(self._on_theme_changed)
        if self.is_edit:
            self._fill_data()
        else:
            # Set default path
            self.dir_input.setText(self.app.settings.get_video_save_path())

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # Title
        title_lbl = QLabel(
            tr("add_stream_dialog.title_edit", default="Edit Stream Settings")
            if self.is_edit else
            tr("add_stream_dialog.title_add", default="Add New Stream")
        )
        title_lbl.setProperty("class", "heading")
        layout.addWidget(title_lbl)

        # Tabs
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tab_general = QWidget()
        self.tab_recording = QWidget()
        self.tab_scheduling = QWidget()

        self.tabs.addTab(self.tab_general, tr("add_stream_dialog.tab_general", default="General"))
        self.tabs.addTab(self.tab_recording, tr("add_stream_dialog.tab_recording", default="Recording"))
        self.tabs.addTab(self.tab_scheduling, tr("add_stream_dialog.tab_scheduling", default="Scheduling & Extra"))

        self._setup_general_tab()
        self._setup_recording_tab()
        self._setup_scheduling_tab()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.cancel_btn = QPushButton(tr("base.cancel", default="Cancel"))
        self.cancel_btn.setProperty("class", "secondary")
        self.cancel_btn.clicked.connect(self.reject)
        
        self.save_btn = QPushButton(
            tr("add_stream_dialog.save_edit", default="Save Changes")
            if self.is_edit else
            tr("add_stream_dialog.save_add", default="Add Stream")
        )
        self.save_btn.setProperty("class", "primary")
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        
        layout.addLayout(btn_layout)

    def _on_theme_changed(self) -> None:
        apply_elevation(self, level=2)
        self._apply_styles()

    def _setup_general_tab(self):
        lay = QVBoxLayout(self.tab_general)
        form = QFormLayout()
        form.setSpacing(12)

        # URL
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://twitch.tv/example")
        form.addRow(f"{tr('add_stream_dialog.stream_url', default='Stream URL')}:", self.url_input)

        # Streamer Name
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(tr("add_stream_dialog.streamer_name_placeholder", default="Optional: Custom Name"))
        form.addRow(f"{tr('add_stream_dialog.streamer_name', default='Streamer Name')}:", self.name_input)

        # Directory
        self.dir_input = QLineEdit()
        self.dir_browse_btn = QPushButton(tr("add_stream_dialog.browse", default="Browse..."))
        self.dir_browse_btn.setFixedWidth(80)
        self.dir_browse_btn.clicked.connect(self._on_browse_dir)
        
        dir_lay = QHBoxLayout()
        dir_lay.addWidget(self.dir_input)
        dir_lay.addWidget(self.dir_browse_btn)
        form.addRow(f"{tr('add_stream_dialog.save_folder', default='Save Folder')}:", dir_lay)

        lay.addLayout(form)
        lay.addStretch()

    def _setup_recording_tab(self):
        lay = QVBoxLayout(self.tab_recording)
        form = QFormLayout()
        form.setSpacing(12)

        # Quality
        self.quality_combo = QComboBox()
        from PySide6.QtWidgets import QListView
        self.quality_combo.setView(QListView())
        self.qualities = {
            tr("add_stream_dialog.quality_best", default="Best (Original)"): "OD",
            tr("add_stream_dialog.quality_uhd", default="1080p60 / 1080p"): "UHD",
            tr("add_stream_dialog.quality_hd", default="720p60  / 720p"):  "HD",
            tr("add_stream_dialog.quality_sd", default="480p / 360p"):     "SD",
            tr("add_stream_dialog.quality_audio", default="Audio Only"):   "AUDIO"
        }
        self.quality_combo.addItems(list(self.qualities.keys()))
        form.addRow(f"{tr('add_stream_dialog.preferred_quality', default='Preferred Quality')}:", self.quality_combo)

        # Format
        self.format_combo = QComboBox()
        self.format_combo.setView(QListView())
        self.format_combo.addItems(["ts", "mp4", "mkv", "flv"])
        form.addRow(f"{tr('add_stream_dialog.video_format', default='Video Format')}:", self.format_combo)

        # Segmenting
        self.segment_check = QCheckBox(tr("recording_dialog.is_segment_enabled", default="Enable Segmented Recording"))
        form.addRow("", self.segment_check)

        self.segment_time = QSpinBox()
        self.segment_time.setRange(60, 86400)
        self.segment_time.setSuffix(f" {tr('add_stream_dialog.seconds', default='seconds')}")
        self.segment_time.setValue(3600)
        self.segment_time.setEnabled(False)
        self.segment_check.toggled.connect(self.segment_time.setEnabled)
        form.addRow(f"{tr('recording_dialog.segment_record_time', default='Segment Duration')}:", self.segment_time)

        lay.addLayout(form)
        lay.addStretch()

    def _setup_scheduling_tab(self):
        lay = QVBoxLayout(self.tab_scheduling)
        form = QFormLayout()
        form.setSpacing(12)

        # Monitor Status
        self.monitor_check = QCheckBox(tr("add_stream_dialog.monitor_auto", default="Automatically Monitor this stream"))
        self.monitor_check.setChecked(True)
        form.addRow("", self.monitor_check)

        # Favorite
        self.favorite_check = QCheckBox(tr("add_stream_dialog.favorite_stream", default="Mark as favorite"))
        form.addRow("", self.favorite_check)

        # Scheduled Recording
        self.schedule_group = QGroupBox(tr("recording_dialog.scheduled_recording", default="Scheduled Recording"))
        self.schedule_group.setCheckable(True)
        self.schedule_group.setChecked(False)
        
        s_lay = QFormLayout(self.schedule_group)
        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm:ss")
        s_lay.addRow(f"{tr('recording_dialog.scheduled_start_time', default='Start Time')}:", self.start_time)

        self.monitor_hours = QSpinBox()
        self.monitor_hours.setRange(1, 24)
        self.monitor_hours.setSuffix(f" {tr('add_stream_dialog.hours', default='hours')}")
        self.monitor_hours.setValue(2)
        s_lay.addRow(f"{tr('recording_dialog.monitor_hours', default='Duration')}:", self.monitor_hours)
        
        lay.addWidget(self.schedule_group)

        # Extra
        self.push_check = QCheckBox(tr("recording_dialog.enable_message_push", default="Enable Notifications (Push)"))
        form.addRow("", self.push_check)

        lay.addLayout(form)
        lay.addStretch()

    def _fill_data(self):
        rec = self.recording
        self.url_input.setText(rec.url)
        self.name_input.setText(rec.streamer_name)
        self.dir_input.setText(getattr(rec, "recording_dir", "") or "")
        
        # Quality
        q_val = getattr(rec, "quality", "OD")
        for label, key in self.qualities.items():
            if key == q_val:
                self.quality_combo.setCurrentText(label)
                break
        
        # Format
        fmt = getattr(rec, "record_format", "ts")
        self.format_combo.setCurrentText(fmt)

        # Segments
        self.segment_check.setChecked(bool(getattr(rec, "segment_record", False)))
        self.segment_time.setValue(self._coerce_int(getattr(rec, "segment_time", 3600), 3600))

        # Monitoring
        self.monitor_check.setChecked(bool(getattr(rec, "monitor_status", True)))
        self.favorite_check.setChecked(bool(getattr(rec, "is_favorite", False)))
        self.push_check.setChecked(bool(getattr(rec, "enabled_message_push", False)))

        # Schedule
        self.schedule_group.setChecked(bool(getattr(rec, "scheduled_recording", False)))
        from PySide6.QtCore import QTime
        time_str = getattr(rec, "scheduled_start_time", "00:00:00") or "00:00:00"
        self.start_time.setTime(QTime.fromString(time_str))
        self.monitor_hours.setValue(self._coerce_int(getattr(rec, "monitor_hours", 2), 2))

    @staticmethod
    def _coerce_int(value, default: int) -> int:
        """Safely convert *value* to int, stripping locale noise (commas, spaces, suffixes)."""
        import re
        if value is None:
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        cleaned = re.sub(r"[^\d-]", "", str(value))
        try:
            return int(cleaned) if cleaned and cleaned != "-" else default
        except (ValueError, OverflowError):
            return default

    def _on_browse_dir(self):
        path = QFileDialog.getExistingDirectory(
            self,
            tr("add_stream_dialog.select_save_directory", default="Select Save Directory"),
            self.dir_input.text(),
        )
        if path:
            self.dir_input.setText(path)

    def _on_save_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(
                self,
                tr("add_stream_dialog.validation_title", default="Validation"),
                tr("recording_dialog.input_live_link", default="Enter Live Room URL"),
            )
            return

        quality_label = self.quality_combo.currentText()
        data = {
            "url": url,
            "streamer_name": self.name_input.text().strip() or tr("recording_dialog.live_room", default="Live Room"),
            "recording_dir": self.dir_input.text().strip(),
            "quality": self.qualities.get(quality_label, "OD"),
            "record_format": self.format_combo.currentText(),
            "segment_record": self.segment_check.isChecked(),
            "segment_time": self.segment_time.value(),
            "monitor_status": self.monitor_check.isChecked(),
            "is_favorite": self.favorite_check.isChecked(),
            "enabled_message_push": self.push_check.isChecked(),
            "scheduled_recording": self.schedule_group.isChecked(),
            "scheduled_start_time": self.start_time.time().toString("HH:mm:ss"),
            "monitor_hours": self.monitor_hours.value(),
        }

        if self.is_edit:
            if self.recording.url != url:
                # Re-validate platform if URL changed
                platform, platform_key = get_platform_info(url)
                if not platform:
                    QMessageBox.warning(
                        self,
                        tr("add_stream_dialog.unsupported_platform_title", default="Unsupported Platform"),
                        tr("add_stream_dialog.unsupported_platform_message", default="The platform for this URL is not supported yet: {url}").format(url=url),
                    )
                    return
                # Duplicate check (excluding current rec_id)
                if any(r.url == url and r.rec_id != self.recording.rec_id for r in self.app.record_manager.recordings):
                    QMessageBox.information(
                        self,
                        tr("add_stream_dialog.duplicate_stream_title", default="Duplicate Stream"),
                        tr("add_stream_dialog.duplicate_stream_edit_message", default="This stream URL is already in use by another entry."),
                    )
                    return
                data["platform"] = platform
                data["platform_key"] = platform_key

            logger.info(f"Updating stream: {url}")
            self.recording.update(data)
            # Ensure title is updated too
            self.recording.update_title(tr(f"video_quality.{data['quality']}"))
            
            self.app.event_bus.run_task(self.app.record_manager.persist_recordings)
            
            if hasattr(self.app.main_window, "show_toast"):
                self.app.main_window.show_toast(tr("toast.updated_stream", default="Updated: {streamer_name}").format(streamer_name=self.recording.streamer_name), "success")
            self.accept()
            return

        # NEW STREAM LOGIC
        # Validate platform
        platform, platform_key = get_platform_info(url)
        if not platform:
            QMessageBox.warning(
                self,
                tr("add_stream_dialog.unsupported_platform_title", default="Unsupported Platform"),
                tr("add_stream_dialog.unsupported_platform_message", default="The platform for this URL is not supported yet: {url}").format(url=url),
            )
            return

        # Check for duplicates
        if any(rec.url == url for rec in self.app.record_manager.recordings):
            QMessageBox.information(
                self,
                tr("add_stream_dialog.duplicate_stream_title", default="Duplicate Stream"),
                tr("add_stream_dialog.duplicate_stream_add_message", default="This stream is already in your list."),
            )
            return

        logger.info(f"Adding stream: {url}")
        
        # Get default loop time from settings
        loop_time_seconds = int(self.app.settings.user_config.get("loop_time_seconds", 300))
        
        new_rec = Recording(
            rec_id=str(uuid.uuid4()),
            url=url,
            streamer_name=data["streamer_name"],
            record_format=data["record_format"],
            quality=data["quality"],
            segment_record=data["segment_record"],
            segment_time=data["segment_time"],
            monitor_status=data["monitor_status"],
            scheduled_recording=data["scheduled_recording"],
            scheduled_start_time=data["scheduled_start_time"],
            monitor_hours=data["monitor_hours"],
            recording_dir=data["recording_dir"],
            enabled_message_push=data["enabled_message_push"],
            is_favorite=data["is_favorite"],
            only_notify_no_record=False,
            flv_use_direct_download=False,
            added_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        new_rec.loop_time_seconds = loop_time_seconds
        
        self.app.event_bus.run_task(self.app.record_manager.add_recording, new_rec)
        self.app.event_bus.publish("add", new_rec)

        if data["monitor_status"]:
            self.app.event_bus.run_task(self.app.record_manager.check_if_live, new_rec)
        
        if hasattr(self.app.main_window, "show_toast"):
            self.app.main_window.show_toast(tr("toast.stream_added", default="Stream added: {streamer_name}").format(streamer_name=data['streamer_name']), "success")
            
        self.accept()

    def _apply_styles(self):
        self.setStyleSheet(
            f"""
            QDialog#addStreamDialog {{
                background: {theme_manager.get_color('surface')};
                border: 1px solid {theme_manager.get_color('border')};
                border-radius: 0px;
            }}
            QTabWidget::pane {{
                border: 1px solid {theme_manager.get_color('border')};
                background: {theme_manager.get_color('surface')};
                border-radius: 0px;
            }}
            QTabBar::tab {{
                background: {theme_manager.get_color('card')};
                color: {theme_manager.get_color('text_sec')};
                border: 1px solid {theme_manager.get_color('border')};
                padding: 6px 10px;
            }}
            QTabBar::tab:selected {{
                color: {theme_manager.get_color('text')};
                border-bottom-color: {theme_manager.get_color('surface')};
            }}
            """
        )

    def showEvent(self, event):
        super().showEvent(event)
        self._disable_native_rounded_corners()

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
