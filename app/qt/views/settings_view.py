"""
Qt Settings View for StreamCapEvo.

Migrates the complex Flet settings page to a modern Qt layout.
Uses SettingsLogic for framework-agnostic data persistence.
Supports tabs for: Recording, Push, Cookies, Accounts.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QPushButton,
    QFrame,
    QComboBox,
    QLineEdit,
    QCheckBox,
    QGroupBox,
    QTabWidget
)

from app.utils.logger import logger
from app.utils.i18n import tr
from app.core.data_import.import_engine import ImportEngine


class SettingsGroup(QGroupBox):
    """A visually distinct group of settings with a title and optional description."""
    def __init__(self, title, description="", parent=None):
        super().__init__(parent)
        self.setTitle(title)
        self.setObjectName("settingsGroup")
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 30, 20, 20)
        self.layout.setSpacing(15)
        
        if description:
            desc_label = QLabel(description)
            desc_label.setProperty("class", "muted")
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("font-size: 11px; margin-bottom: 10px; color: #888;")
            self.layout.addWidget(desc_label)

    def add_setting(self, label, widget, tooltip=""):
        row = QHBoxLayout()
        row.setSpacing(20)
        
        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: 500; font-size: 13px;")
        if tooltip:
            lbl.setToolTip(tooltip)
            
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(widget)
        
        self.layout.addLayout(row)


class QtSettingsView(QWidget):
    """
    Main settings view with tabs for Recording, Push, Cookies, and Accounts.
    """

    def __init__(self, app_context):
        super().__init__()
        self.app = app_context
        self.settings = self.app.settings # SettingsLogic instance
        self.language = self.app.language_manager.language
        self._l = self.language.get("settings_page", {})
        
        self.initial_load = True
        self.app.event_bus.subscribe("language_changed", self._on_language_changed)

        self._setup_ui()
        self._load_settings()

    def _on_language_changed(self, topic, new_language) -> None:
        self.language = new_language
        self._l = self.language.get("settings_page", {})
        
        # Rebuild tabs entirely since there are too many dynamic labels to track
        self.tabs.clear()
        self.tabs.addTab(self._create_recording_tab(), self._l.get("basic_settings", "Recording"))
        self.tabs.addTab(self._create_push_tab(), self._l.get("push_notifications", "Notifications"))
        self.tabs.addTab(self._create_cookies_tab(), self._l.get("cookies_settings", "Cookies"))
        self.tabs.addTab(self._create_accounts_tab(), self._l.get("accounts_settings", "Accounts"))
        self.tabs.addTab(self._create_data_tab(), self._l.get("data_settings", "Data"))
        
        self.title_lbl.setText(self.language.get("sidebar", {}).get("settings", "Settings"))
        self.restore_btn.setText(self._l.get("restore_defaults", "Restore Defaults"))
        
        self._load_settings()

    def _retranslate_ui(self) -> None:
        pass

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(20)

        # Header
        header = QHBoxLayout()
        self.title_lbl = QLabel(self.language.get("sidebar", {}).get("settings", "Settings"))
        self.title_lbl.setProperty("class", "heading")
        header.addWidget(self.title_lbl)
        header.addStretch()
        
        self.restore_btn = QPushButton(self._l.get("restore_defaults", "Restore Defaults"))
        self.restore_btn.setProperty("class", "secondary")
        self.restore_btn.clicked.connect(self._on_restore_clicked)
        header.addWidget(self.restore_btn)
        
        main_layout.addLayout(header)

        # Tab Widget
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        
        # 1. Recording Tab
        self.tabs.addTab(self._create_recording_tab(), self._l.get("basic_settings", "Recording"))
        
        # 2. Push Tab
        self.tabs.addTab(self._create_push_tab(), self._l.get("push_notifications", "Notifications"))
        
        # 3. Cookies Tab
        self.tabs.addTab(self._create_cookies_tab(), self._l.get("cookies_settings", "Cookies"))
        
        # 4. Accounts Tab
        self.tabs.addTab(self._create_accounts_tab(), self._l.get("accounts_settings", "Accounts"))
        
        # 5. Data Tab
        self.tabs.addTab(self._create_data_tab(), self._l.get("data_settings", "Data"))
        
        main_layout.addWidget(self.tabs)

    def _on_restore_clicked(self):
        from app.qt.components.confirm_dialog import QtConfirmDialog
        if QtConfirmDialog.confirm(
            self,
            "Confirm Restore",
            "Are you sure you want to restore all settings to their default values?",
            "This will not affect your cookies or accounts.",
            type="warning"
        ):
            self.app.event_bus.run_task(self.settings.restore_default_config)
            
            if hasattr(self.app.main_window, "show_toast"):
                self.app.main_window.show_toast(tr("toast.settings_restored", default="Settings restored to defaults"), "success")
                
            QTimer.singleShot(200, self._load_settings)


    def _create_scroll_wrapper(self, widget):
        """Wraps a widget in a scroll area."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(widget)
        return scroll

    def _create_recording_tab(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(25)
        
        # Basic
        rec_group = SettingsGroup(self._l.get("basic_settings", "Basic Settings"), self._l.get("program_config", ""))
        
        from PySide6.QtWidgets import QListView
        self.lang_combo = QComboBox()
        self.lang_combo.setView(QListView())
        for lang_name in self.settings.language_option.keys():
            self.lang_combo.addItem(lang_name)
        self.lang_combo.currentTextChanged.connect(lambda v: self._save_setting("language", v))
        rec_group.add_setting(self._l.get("program_language", "Program Language") + ":", self.lang_combo)
        
        from app.qt.themes.theme import ACCENT_COLORS
        self.color_combo = QComboBox()
        self.color_combo.setView(QListView())
        for color_name in ACCENT_COLORS.keys():
            self.color_combo.addItem(color_name.capitalize(), color_name)
        self.color_combo.currentIndexChanged.connect(self._on_color_changed)
        rec_group.add_setting(self.language.get("sidebar", {}).get("theme_color", "Accent Color") + ":", self.color_combo)
        
        self.path_input = QLineEdit()
        self.path_input.setReadOnly(True)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_input)
        self.browse_btn = QPushButton(self._l.get("select", "Browse"))
        self.browse_btn.setMinimumWidth(120)
        self.browse_btn.clicked.connect(self._on_browse_clicked)
        path_row.addWidget(self.browse_btn)
        path_widget = QWidget()
        path_widget.setLayout(path_row)
        rec_group.add_setting(self._l.get("live_recording_path", "Save Path") + ":", path_widget)

        # Folder Naming Rules
        naming_group = SettingsGroup(self._l.get("name_rules", "Folder Naming Rules"), "")
        
        self.name_plat = QCheckBox()
        self.name_plat.stateChanged.connect(lambda s: self._save_setting("folder_name_platform", s == Qt.CheckState.Checked.value))
        naming_group.add_setting(self._l.get("platform", "Platform") + ":", self.name_plat)

        self.name_auth = QCheckBox()
        self.name_auth.stateChanged.connect(lambda s: self._save_setting("folder_name_author", s == Qt.CheckState.Checked.value))
        naming_group.add_setting(self._l.get("author", "Author") + ":", self.name_auth)

        self.name_time = QCheckBox()
        self.name_time.stateChanged.connect(lambda s: self._save_setting("folder_name_time", s == Qt.CheckState.Checked.value))
        naming_group.add_setting(self._l.get("time", "Time") + ":", self.name_time)

        self.name_title = QCheckBox()
        self.name_title.stateChanged.connect(lambda s: self._save_setting("folder_name_title", s == Qt.CheckState.Checked.value))
        naming_group.add_setting(self._l.get("title", "Title") + ":", self.name_title)

        layout.addWidget(naming_group)

        self.quality_combo = QComboBox()
        self.quality_combo.setView(QListView())
        self.quality_combo.addItems(["OD", "UHD", "HD", "SD", "LD"])
        self.quality_combo.currentTextChanged.connect(lambda v: self._save_setting("record_quality", v))
        rec_group.add_setting(self._l.get("recording_quality", "Default Quality") + ":", self.quality_combo)
        
        self.title_check = QCheckBox()
        self.title_check.stateChanged.connect(lambda s: self._save_setting("filename_includes_title", s == Qt.CheckState.Checked.value))
        rec_group.add_setting(self._l.get("filename_includes_title", "Include Title in Filename") + ":", self.title_check)
        
        layout.addWidget(rec_group)
        
        # Monitoring
        monitor_group = SettingsGroup("Monitoring", "")
        self.loop_input = QLineEdit()
        self.loop_input.setFixedWidth(80)
        self.loop_input.textChanged.connect(lambda v: self._save_setting("loop_time_seconds", v))
        monitor_group.add_setting(self._l.get("loop_time", "Check Interval") + ":", self.loop_input)
        layout.addWidget(monitor_group)

        # Proxy
        proxy_group = SettingsGroup(self._l.get("proxy_settings", "Proxy Settings"), self._l.get("is_proxy_enabled", ""))
        self.proxy_enabled = QCheckBox()
        self.proxy_enabled.stateChanged.connect(lambda s: self._save_setting("enable_proxy", s == Qt.CheckState.Checked.value))
        proxy_group.add_setting(self._l.get("enable_proxy", "Enable Proxy") + ":", self.proxy_enabled)
        
        self.proxy_addr = QLineEdit()
        self.proxy_addr.setPlaceholderText("http://user:pass@host:port")
        self.proxy_addr.textChanged.connect(lambda v: self._save_setting("proxy_address", v))
        proxy_group.add_setting(self._l.get("proxy_address", "Proxy Address") + ":", self.proxy_addr)
        layout.addWidget(proxy_group)

        # Advanced / Post-Processing
        adv_group = SettingsGroup(self._l.get("advanced_config", "Advanced Recording"), "")
        
        self.seg_check = QCheckBox()
        self.seg_check.stateChanged.connect(lambda s: self._save_setting("segmented_recording_enabled", s == Qt.CheckState.Checked.value))
        adv_group.add_setting(self._l.get("is_segmented_recording_enabled", "Enable Segmented Recording") + ":", self.seg_check)
        
        self.seg_time = QLineEdit()
        self.seg_time.setFixedWidth(80)
        self.seg_time.textChanged.connect(lambda v: self._save_setting("video_segment_time", v))
        adv_group.add_setting(self._l.get("segment_time", "Segment Time") + ":", self.seg_time)

        self.mp4_check = QCheckBox()
        self.mp4_check.stateChanged.connect(lambda s: self._save_setting("convert_to_mp4", s == Qt.CheckState.Checked.value))
        adv_group.add_setting(self._l.get("convert_mp4", "Convert to MP4") + ":", self.mp4_check)

        self.del_check = QCheckBox()
        self.del_check.stateChanged.connect(lambda s: self._save_setting("delete_original", s == Qt.CheckState.Checked.value))
        adv_group.add_setting(self._l.get("delete_original", "Delete Original") + ":", self.del_check)
        
        layout.addWidget(adv_group)
        
        return self._create_scroll_wrapper(content)

    def _create_push_tab(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(25)
        
        notif_group = SettingsGroup(self._l.get("push_notifications", "Push Notifications"), "")
        
        self.notif_enabled = QCheckBox()
        self.notif_enabled.stateChanged.connect(lambda s: self._save_setting("system_notification_enabled", s == Qt.CheckState.Checked.value))
        notif_group.add_setting(self._l.get("system_status_bar_notification_enabled", "Enable System Notifications") + ":", self.notif_enabled)
        
        self.start_notif = QCheckBox()
        self.start_notif.stateChanged.connect(lambda s: self._save_setting("stream_start_notification_enabled", s == Qt.CheckState.Checked.value))
        notif_group.add_setting(self._l.get("open_broadcast_push_enabled", "Stream Start Alert") + ":", self.start_notif)
        
        self.end_notif = QCheckBox()
        self.end_notif.stateChanged.connect(lambda s: self._save_setting("stream_end_notification_enabled", s == Qt.CheckState.Checked.value))
        notif_group.add_setting(self._l.get("close_broadcast_push_enabled", "Stream End Alert") + ":", self.end_notif)
        
        layout.addWidget(notif_group)
        
        custom_group = SettingsGroup(self._l.get("custom_push_settings", "Custom Content"), "")
        self.notif_title = QLineEdit()
        self.notif_title.textChanged.connect(lambda v: self._save_setting("custom_notification_title", v))
        custom_group.add_setting(self._l.get("custom_push_title", "Custom Title") + ":", self.notif_title)
        layout.addWidget(custom_group)

        # Telegram
        tg_group = SettingsGroup("Telegram", "")
        self.tg_token = QLineEdit()
        self.tg_token.setPlaceholderText("Token (5555:AAAA...)")
        self.tg_token.textChanged.connect(lambda v: self._save_setting("telegram_bot_token", v))
        tg_group.add_setting(self._l.get("telegram_api_token", "Bot Token") + ":", self.tg_token)
        
        self.tg_chat = QLineEdit()
        self.tg_chat.setPlaceholderText("Chat ID (-100123...)")
        self.tg_chat.textChanged.connect(lambda v: self._save_setting("telegram_chat_id", v))
        tg_group.add_setting(self._l.get("telegram_chat_id", "Chat ID") + ":", self.tg_chat)
        layout.addWidget(tg_group)

        # Generic Webhook
        hook_group = SettingsGroup("Discord / Webhook", "")
        self.hook_url = QLineEdit()
        self.hook_url.setPlaceholderText("https://discord.com/api/webhooks/...")
        self.hook_url.textChanged.connect(lambda v: self._save_setting("discord_webhook_url", v))
        hook_group.add_setting("Webhook URL:", self.hook_url)
        layout.addWidget(hook_group)
        
        return self._create_scroll_wrapper(content)

    def _create_cookies_tab(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        cookie_group = SettingsGroup(self._l.get("cookies_settings", "Platform Cookies"), "")
        
        self.cookie_fields = {}
        platforms = ["douyin", "tiktok", "twitch", "youtube", "bilibili"]
        
        for p in platforms:
            field = QLineEdit()
            field.setPlaceholderText(self._l.get(f"{p}_cookie", f"Enter {p} cookies..."))
            field.textChanged.connect(lambda v, plat=p: self._save_cookie(plat, v))
            self.cookie_fields[p] = field
            
            if p == "tiktok":
                row = QHBoxLayout()
                row.addWidget(field)
                btn = QPushButton("Import JSON")
                btn.setMinimumWidth(140)
                btn.clicked.connect(lambda _, f=field, plat=p: self._on_browse_cookie_clicked(f, plat))
                row.addWidget(btn)
                wrapper = QWidget()
                wrapper.setLayout(row)
                cookie_group.add_setting(self._l.get(f"{p}_cookie", f"{p.capitalize()}:"), wrapper)
            else:
                cookie_group.add_setting(self._l.get(f"{p}_cookie", f"{p.capitalize()}:"), field)
            
        layout.addWidget(cookie_group)
        return self._create_scroll_wrapper(content)

    def _on_browse_cookie_clicked(self, target_line_edit, plat):
        from PySide6.QtWidgets import QFileDialog
        from app.utils.cookie_importer import load_json_cookies, convert_json_to_cookie_string
        
        path, _ = QFileDialog.getOpenFileName(self, "Select JSON Cookie File", "", "JSON Files (*.json);;Text Files (*.txt);;All Files (*)")
        if path:
            try:
                cookies_json = load_json_cookies(path)
                if cookies_json:
                    cookie_string = convert_json_to_cookie_string(cookies_json)
                    if cookie_string:
                        target_line_edit.setText(cookie_string)
                        self._save_cookie(plat, cookie_string) # Automatically save
                        
                        if hasattr(self.app.main_window, "show_toast"):
                            self.app.main_window.show_toast(tr("toast.cookies_imported", default="Cookies imported successfully from {filename}").format(filename=path.split('/')[-1]), "success")
                    else:
                        if hasattr(self.app.main_window, "show_toast"):
                            self.app.main_window.show_toast(tr("toast.cookies_conversion_failed", default="Failed to convert cookies from JSON."), "error")
                else:
                    if hasattr(self.app.main_window, "show_toast"):
                        self.app.main_window.show_toast(tr("toast.no_cookies_found", default="No cookies found in file."), "error")
            except Exception as e:
                logger.error(f"Error importing cookies: {e}")
                if hasattr(self.app.main_window, "show_toast"):
                    self.app.main_window.show_toast(tr("toast.cookies_import_error", default="Error importing cookies: {error}").format(error=e), "error")

    def _create_accounts_tab(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        acc_group = SettingsGroup(self._l.get("accounts_settings", "Credential Storage"), "")
        
        self.acc_fields = {}
        fields = [
            ("sooplive_username", self._l.get("sooplive_username", "SoopLive Username")),
            ("sooplive_password", self._l.get("sooplive_password", "SoopLive Password"))
        ]
        
        for key, label in fields:
            field = QLineEdit()
            if "password" in key: field.setEchoMode(QLineEdit.EchoMode.Password)
            field.textChanged.connect(lambda v, k=key: self._save_account(k, v))
            acc_group.add_setting(f"{label}:", field)
            self.acc_fields[key] = field
            
        layout.addWidget(acc_group)
        return self._create_scroll_wrapper(content)

    def _create_data_tab(self):
        """Create the Data tab for importing from original StreamCap."""
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(25)
        
        # Import Group
        import_group = SettingsGroup(
            self._l.get("data_import_settings", "Data Import"),
            self._l.get("data_import_description", "Import data from original StreamCap (optional, one-time)")
        )
        
        # Status label
        self.import_status_label = QLabel(self._l.get("import_status_checking", "Checking for StreamCap data..."))
        self.import_status_label.setWordWrap(True)
        self.import_status_label.setStyleSheet("font-size: 12px; color: #666;")
        import_group.layout.addWidget(self.import_status_label)
        
        # Import button
        self.import_btn = QPushButton(self._l.get("import_from_streamcap", "Import from StreamCap"))
        self.import_btn.setMinimumWidth(200)
        self.import_btn.clicked.connect(self._on_import_clicked)
        import_group.layout.addWidget(self.import_btn)
        
        # Result label
        self.import_result_label = QLabel("")
        self.import_result_label.setWordWrap(True)
        self.import_result_label.setStyleSheet("font-size: 11px; margin-top: 10px;")
        import_group.layout.addWidget(self.import_result_label)
        
        layout.addWidget(import_group)
        
        # Check import status on creation
        self._check_import_status()
        
        return self._create_scroll_wrapper(content)

    def _check_import_status(self):
        """Check if import is available and update UI accordingly."""
        import os
        import sys
        
        # Determine source and destination paths
        if sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            source_path = os.path.join(local_app_data, "StreamCap")
            dest_config = os.path.join(local_app_data, "StreamCapEvo", "config")
        else:
            # Non-Windows: import not supported
            self.import_btn.setEnabled(False)
            self.import_status_label.setText(self._l.get("import_not_available", "Import not available on this platform"))
            return
        
        # Check if already imported
        user_config = self.settings.user_config
        if user_config.get("import_completed"):
            self.import_btn.setEnabled(False)
            self.import_btn.setText(self._l.get("import_completed", "Import Completed"))
            self.import_status_label.setText(self._l.get("import_already_done", "Data has already been imported"))
            return
        
        # Check if source data exists
        engine = ImportEngine(source_path, dest_config)
        if not engine.has_importable_data():
            self.import_btn.setEnabled(False)
            self.import_status_label.setText(self._l.get("import_no_data_found", "No StreamCap data found to import"))
            return
        
        # Check if StreamCap is running
        if engine.is_source_running():
            self.import_btn.setEnabled(False)
            self.import_status_label.setText(self._l.get("import_streamcap_running", "Please close StreamCap before importing"))
            return
        
        # Import is available
        self.import_btn.setEnabled(True)
        self.import_status_label.setText(self._l.get("import_ready", "StreamCap data detected. Click to import."))

    def _on_import_clicked(self):
        """Handle the import button click."""
        import os
        import sys
        
        if sys.platform != "win32":
            return
        
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        source_path = os.path.join(local_app_data, "StreamCap")
        dest_config = os.path.join(local_app_data, "StreamCapEvo", "config")
        
        engine = ImportEngine(source_path, dest_config)
        
        # Perform import
        result = engine.import_all()
        
        if result.success:
            # Mark import as completed
            self.app.event_bus.run_task(self.settings.update_setting, "import_completed", True)
            
            # Update UI
            self.import_btn.setEnabled(False)
            self.import_btn.setText(self._l.get("import_completed", "Import Completed"))
            
            files_msg = ", ".join(result.files_copied)
            self.import_result_label.setText(
                self._l.get("import_success", "Successfully imported: {files}").format(files=files_msg)
            )
            self.import_result_label.setStyleSheet("font-size: 11px; color: #28a745; margin-top: 10px;")
            
            if hasattr(self.app.main_window, "show_toast"):
                self.app.main_window.show_toast(
                    self._l.get("import_toast_success", "Data imported successfully"), "success"
                )
        else:
            # Show errors
            error_msg = "; ".join(result.errors) if result.errors else self._l.get("import_failed", "Import failed")
            self.import_result_label.setText(error_msg)
            self.import_result_label.setStyleSheet("font-size: 11px; color: #dc3545; margin-top: 10px;")
            
            if hasattr(self.app.main_window, "show_toast"):
                self.app.main_window.show_toast(error_msg, "error")

    def _on_browse_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select Download Directory", self.path_input.text())
        if path:
            self.path_input.setText(path)
            self._save_setting("live_save_path", path)

    def _on_color_changed(self, index):
        if self.initial_load: return
        color_key = self.color_combo.itemData(index)
        self._save_setting("theme_color", color_key)
        
        from app.qt.themes.theme import ACCENT_COLORS, theme_manager
        if color_key in ACCENT_COLORS:
            theme_manager.set_accent(ACCENT_COLORS[color_key])

    def _load_settings(self):
        self.initial_load = True
        s = self.settings
        
        # Recording
        current_lang = s.user_config.get("language")
        idx = self.lang_combo.findText(current_lang if current_lang else "")
        if idx >= 0: self.lang_combo.setCurrentIndex(idx)
        
        color_val = s.get_config_value("theme_color", "orange")
        idx_c = self.color_combo.findData(color_val)
        if idx_c >= 0: self.color_combo.setCurrentIndex(idx_c)
        
        self.path_input.setText(s.get_video_save_path())
        
        self.name_plat.setChecked(s.get_config_value("folder_name_platform", False))
        self.name_auth.setChecked(s.get_config_value("folder_name_author", False))
        self.name_time.setChecked(s.get_config_value("folder_name_time", False))
        self.name_title.setChecked(s.get_config_value("folder_name_title", False))
        
        idx_q = self.quality_combo.findText(s.get_config_value("record_quality", "OD"))
        if idx_q >= 0: self.quality_combo.setCurrentIndex(idx_q)
        self.title_check.setChecked(s.get_config_value("filename_includes_title", False))
        self.loop_input.setText(str(s.get_config_value("loop_time_seconds", "60")))
        
        # Proxy
        self.proxy_enabled.setChecked(s.get_config_value("enable_proxy", False))
        self.proxy_addr.setText(s.get_config_value("proxy_address", ""))
        
        # Advanced
        self.seg_check.setChecked(s.get_config_value("segmented_recording_enabled", False))
        self.seg_time.setText(str(s.get_config_value("video_segment_time", "3600")))
        self.mp4_check.setChecked(s.get_config_value("convert_to_mp4", False))
        self.del_check.setChecked(s.get_config_value("delete_original", False))
        
        # Push
        self.notif_enabled.setChecked(s.get_config_value("system_notification_enabled", False))
        self.start_notif.setChecked(s.get_config_value("stream_start_notification_enabled", False))
        self.end_notif.setChecked(s.get_config_value("stream_end_notification_enabled", False))
        self.notif_title.setText(s.get_config_value("custom_notification_title", "StreamCapEvo"))
        
        # Telegram & Webhook
        self.tg_token.setText(s.get_config_value("telegram_bot_token", ""))
        self.tg_chat.setText(s.get_config_value("telegram_chat_id", ""))
        self.hook_url.setText(s.get_config_value("discord_webhook_url", ""))
        
        # Cookies
        for p, field in self.cookie_fields.items():
            field.setText(s.get_cookies_value(p, ""))
            
        # Accounts
        for k, field in self.acc_fields.items():
            field.setText(s.get_accounts_value(k, ""))
            
        self.initial_load = False

    def _save_setting(self, key, value):
        if self.initial_load: return
        self.app.event_bus.run_task(self.settings.update_setting, key, value)

    def _save_cookie(self, key, value):
        if self.initial_load: return
        self.app.event_bus.run_task(self.settings.update_cookie, key, value)

    def _save_account(self, key, value):
        if self.initial_load: return
        plat, k = key.split("_", 1)
        self.app.event_bus.run_task(self.settings.update_account, plat, k, value)
