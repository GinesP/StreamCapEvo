"""
Main Qt window for StreamCapEvo.

This is the Qt equivalent of main.py + app_manager.py.
It provides the application shell: sidebar + content area.
"""

import asyncio
import ctypes
import sys

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QIcon, QFont, QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.qt.navigation.sidebar import Sidebar
from app.qt.themes.theme import theme_manager, apply_theme, DARK_COLORS, LIGHT_COLORS
from app.qt.views.recordings_view import QtRecordingsView
from app.qt.views.settings_view import QtSettingsView
from app.qt.views.home_view import QtHomeView
from app.qt.views.log_view import QtLogView
from app.qt.components.toast import QtToastManager
from app.utils.i18n import tr
# NOTE: QtAboutView, QtVideoPlayer are imported lazily
# to avoid loading PySide6.QtMultimedia at module level, which activates
# the DirectShow backend on Windows and causes a brief spurious window.


class MainWindow(QMainWindow):
    """
    The main application window.

    Provides:
    - Left sidebar navigation
    - Stacked content area (one widget per page)
    - Theme toggling (dark/light)
    """

    MIN_WIDTH = 950
    MIN_HEIGHT = 600
    WINDOW_TITLE = "StreamCapEvo"
    SIDEBAR_COLLAPSE_BREAKPOINT = 1024

    def __init__(self, app_context):
        super().__init__()
        self.app = app_context
        self.app.main_window = self
        self.setWindowTitle(self.WINDOW_TITLE)
        app_icon = QApplication.windowIcon()
        if not app_icon.isNull():
            self.setWindowIcon(app_icon)
        self.setMinimumSize(QSize(self.MIN_WIDTH, self.MIN_HEIGHT))
        self.resize(1200, 750)

        self._dark_mode = self.app.settings.user_config.get("theme_mode", "dark") == "dark"
        self._sidebar_user_collapsed = bool(self.app.settings.user_config.get("sidebar_collapsed", False))
        self._pages: dict[str, QWidget] = {}

        self._setup_ui()
        self._setup_shortcuts()
        self._apply_theme()
        self._enable_dwm_shadow()
        self.toast_manager = QtToastManager(self)

        # Subscribe to external theme changes (hot-reload via theme.json)
        theme_manager.themeChanged.connect(self._on_theme_manager_changed)

        # Start periodic runtime diagnostics (suspect memory growth)
        self._setup_diagnostics()

    # ── Shortcuts ────────────────────────────────────────────────────

    def _setup_shortcuts(self):
        """Register global keyboard shortcuts (Design Guide §7.2)."""
        from PySide6.QtGui import QKeySequence, QShortcut

        # Navigation
        shortcuts = {
            "Ctrl+1": "home",
            "Ctrl+2": "recordings",
            "Ctrl+3": "settings",
            "Ctrl+4": "about",
            "Ctrl+5": "logs",
            "Ctrl+6": "stats",
        }
        for key, page in shortcuts.items():
            s = QShortcut(QKeySequence(key), self)
            s.activated.connect(lambda p=page: self.show_page(p))

        # Actions
        QShortcut(QKeySequence("Ctrl+T"), self).activated.connect(self._toggle_theme)

        # Context-aware: Focus search
        self.search_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        self.search_shortcut.activated.connect(self._on_search_shortcut)

        # Context-aware: Add stream
        self.add_shortcut = QShortcut(QKeySequence("Alt+N"), self)
        self.add_shortcut.activated.connect(self._on_add_shortcut)

        # Context-aware: Refresh
        self.refresh_shortcut = QShortcut(QKeySequence("Ctrl+R"), self)
        self.refresh_shortcut.activated.connect(self._on_refresh_shortcut)

    def _on_search_shortcut(self):
        """Global Search shortcut — focus search box if in Recordings View."""
        self.show_page("recordings")
        view = self._pages.get("recordings")
        if view and hasattr(view, "search_box"):
            view.search_box.setFocus()
            view.search_box.selectAll()

    def _on_add_shortcut(self):
        """Global Add shortcut — open dialog if relevant."""
        if self.sidebar.current_page == "recordings":
            view = self._pages.get("recordings")
            if view and hasattr(view, "_on_add_stream_clicked"):
                view._on_add_stream_clicked()
        elif self.sidebar.current_page == "home":
            self.show_page("recordings")  # Shift to recordings
            QTimer.singleShot(100, self._on_add_shortcut)

    def _on_refresh_shortcut(self):
        """Global Refresh shortcut — refresh current view if applicable."""
        view = self.content_stack.currentWidget()
        if view and hasattr(view, "refresh") and callable(view.refresh):
            view.refresh()
        elif view and hasattr(view, "_load_data"):  # Common pattern in our views
            view._load_data()

    # ── UI Setup ─────────────────────────────────────────────────────

    def _setup_ui(self):
        """Build the main layout: sidebar | divider | content stack."""
        central = QWidget()
        self.setCentralWidget(central)

        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar(self.app)
        self.sidebar.page_changed.connect(self._on_page_changed)
        self.sidebar.collapsed_changed.connect(self._on_sidebar_collapsed_changed)
        self.sidebar.theme_btn.clicked.connect(self._toggle_theme)
        main_layout.addWidget(self.sidebar)

        # Register EventBus listeners
        self.app.event_bus.subscribe("language_changed", self._on_language_changed)

        # Content stack
        self.content_stack = QStackedWidget()
        self.content_stack.setProperty("class", "shell-surface")
        self.content_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        main_layout.addWidget(self.content_stack)

        self._sync_sidebar_layout(animate=False)

        # Show initial page
        self.show_page("home")

    def _register_pages(self):
        """No longer used for eager loading. Pages are created lazily in show_page."""
        pass

    def _create_page(self, name: str) -> QWidget:
        """Factory method to create page widgets lazily."""
        if name == "home":
            from app.qt.views.home_view import QtHomeView

            return QtHomeView(self.app)
        elif name == "stats":
            from app.qt.views.stats_view import QtStatsView

            return QtStatsView(self.app)
        elif name == "recordings":
            from app.qt.views.recordings_view import QtRecordingsView

            return QtRecordingsView(self.app)
        elif name == "settings":
            from app.qt.views.settings_view import QtSettingsView

            return QtSettingsView(self.app)
        elif name == "logs":
            from app.qt.views.log_view import QtLogView

            return QtLogView(self.app)
        elif name == "about":
            from app.qt.views.about_view import QtAboutView

            return QtAboutView(self.app)
        return self._create_placeholder(name)

    def _create_placeholder(self, name: str) -> QWidget:
        """Create a simple placeholder widget for a page not yet migrated."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel(f"📦  {name.capitalize()} Page")
        label.setProperty("class", "heading")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        sub = QLabel("This page will be migrated from Flet to Qt.")
        sub.setProperty("class", "secondary")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        return widget

    # ── Page Management ──────────────────────────────────────────────

    def register_page(self, name: str, widget: QWidget):
        """Register a page widget into the content stack."""
        if name in self._pages:
            old = self._pages[name]
            index = self.content_stack.indexOf(old)
            self.content_stack.removeWidget(old)
            old.deleteLater()

        self.content_stack.addWidget(widget)
        self._pages[name] = widget

    def show_page(self, name: str):
        """Switch the visible page in the content stack, creating it if needed."""
        if name not in self._pages:
            widget = self._create_page(name)
            self.register_page(name, widget)

        self.content_stack.setCurrentWidget(self._pages[name])
        self.sidebar.select_page(name)

    def _on_page_changed(self, name: str):
        """Handle sidebar navigation click."""
        self.show_page(name)

    def resizeEvent(self, event):
        self._sync_sidebar_layout(animate=True)
        super().resizeEvent(event)

    # ── Video Player (lazy) ──────────────────────────────────────────

    def get_video_player(self):
        """Return the shared video player, creating it on first use."""
        if self.app.video_player is None:
            from app.qt.components.video_player import QtVideoPlayer  # lazy: QtMultimedia

            self.app.video_player = QtVideoPlayer(self.app, parent=self)
        return self.app.video_player

    # ── Events ───────────────────────────────────────────────────────

    def _on_language_changed(self, topic, language_data):
        """Update the UI when the language changes."""
        sidebar_labels = language_data.get("record_sidebar", {})
        keys_map = {
            "home": "home",
            "stats": "stats",
            "recordings": "recordings",
            "settings": "settings",
            "logs": "logs",
            "about": "about",
        }
        translated = {page_name: sidebar_labels[key] for key, page_name in keys_map.items() if key in sidebar_labels}
        self.sidebar.update_labels(translated)

        # Hot-reload all views with new language
        current_page = None
        current_widget = self.content_stack.currentWidget()
        for name, widget in self._pages.items():
            if widget == current_widget:
                current_page = name
                break

        self._register_pages()

        if current_page:
            self.show_page(current_page)
        else:
            self.show_page("home")

    # ── Theme ────────────────────────────────────────────────────────

    def _toggle_theme(self):
        """Toggle between dark and light mode via the ThemeManager singleton."""
        self._dark_mode = not self._dark_mode
        theme_manager.set_mode(self._dark_mode)  # emits themeChanged
        self._update_theme_btn()

    def _apply_theme(self):
        """Apply the current theme at startup."""
        from app.qt.themes.theme import ACCENT_COLORS, theme_manager

        self._dark_mode = self.app.settings.user_config.get("theme_mode", "dark") == "dark"
        theme_manager._dark = self._dark_mode

        theme_color = self.app.settings.user_config.get("theme_color", "orange")
        theme_manager._accent = ACCENT_COLORS.get(theme_color, "#FF6428")

        theme_manager._rebuild_colors()
        theme_manager._apply_to_app()
        theme_manager._emit_theme_changed()
        self._update_theme_btn()

    def _update_theme_btn(self):
        label = "Light" if self._dark_mode else "Dark"
        self.sidebar.set_theme_text(label)

        # ensure we save the preference
        mode_str = "dark" if self._dark_mode else "light"
        if self.app and self.app.settings and self.app.settings.user_config.get("theme_mode") != mode_str:
            self.app.settings.user_config["theme_mode"] = mode_str
            self.app.event_bus.run_task(self.app.config_manager.save_user_config, self.app.settings.user_config)

    def _on_theme_manager_changed(self):
        """Called by ThemeManager when theme.json changes (hot-reload)."""
        self._dark_mode = theme_manager.is_dark
        self._update_theme_btn()

    # ── Runtime Diagnostics ───────────────────────────────────────────

    def _setup_diagnostics(self):
        """Start periodic diagnostics logging if enabled.

        Controlled by the ``STREAMCAP_DIAGNOSTICS_INTERVAL`` environment
        variable (in seconds).  Default: 300 (5 minutes).  Set to 0 to
        disable.
        """
        import os

        interval = int(os.environ.get("STREAMCAP_DIAGNOSTICS_INTERVAL", "300"))
        if interval <= 0:
            return

        self._diag_timer = QTimer(self)
        self._diag_timer.timeout.connect(self._log_diagnostics)
        self._diag_timer.start(interval * 1000)

        # Also log once after the window is fully up (6 s delay)
        QTimer.singleShot(6000, self._log_diagnostics)

    def _log_diagnostics(self):
        """Collect and log a diagnostics snapshot."""
        from app.utils.logger import logger as _log

        try:
            # Late import avoids circular dep at module level
            from app.utils import diagnostics as _diag

            report = _diag.collect_report(
                event_bus=self.app.event_bus,
                language_manager=self.app.language_manager,
                predictor_store=(
                    self.app.record_manager.predictor_metrics
                    if hasattr(self.app, "record_manager")
                    and self.app.record_manager is not None
                    and hasattr(self.app.record_manager, "predictor_metrics")
                    else None
                ),
            )
            _log.info("=== DIAGNOSTICS ===")
            for section, data in report.items():
                if data is None:
                    continue
                _log.info(f"  {section}: {data}")
        except Exception as exc:
            _log.warning(f"Diagnostics error: {exc}")

    @property
    def is_dark_mode(self) -> bool:
        return self._dark_mode

    def show_toast(self, message, toast_type="info", duration=4000):
        """Show a floating notification."""
        self.toast_manager.show_toast(message, toast_type, duration)

    # ── Native DWM Shadow (Windows §4) ──────────────────────────────

    def _enable_dwm_shadow(self):
        """Enable the native DWM drop shadow for this window (guide §4).

        Uses DwmExtendFrameIntoClientArea with 1-px margins — the simplest
        approach that activates the GPU-accelerated DWM shadow without
        intercepting any native messages.  Safe no-op on non-Windows.
        """
        if sys.platform != "win32":
            return
        try:

            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            hwnd = int(self.winId())
            margins = MARGINS(1, 1, 1, 1)
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        except Exception:
            pass  # DWM unavailable (RDP, VM, older Windows)

    # ── Window Events ────────────────────────────────────────────────

    def closeEvent(self, event: QCloseEvent):
        """Handle window close: show confirmation and cleanup."""
        # If we are already shutting down, just accept and let Qt close the window
        if getattr(self, "_is_shutting_down", False):
            event.accept()
            return

        from app.qt.components.confirm_dialog import QtConfirmDialog
        from app.utils.i18n import tr

        if QtConfirmDialog.confirm(
            self,
            tr("app_close_handler.confirm_exit"),
            tr("app_close_handler.confirm_exit_content"),
            tr("app_close_handler.minimize_to_tray_tip"),
            type="warning",
        ):
            self._is_shutting_down = True
            event.ignore()

            # Prevent new recordings and tell StreamManager we are closing
            if hasattr(self.app, "recording_enabled"):
                self.app.recording_enabled = False

            if hasattr(self.app, "event_bus") and self.app.event_bus:
                self.app.event_bus.publish("app_closing")

            if hasattr(self.app, "record_manager") and self.app.record_manager:
                # Stop the monitoring engine without persisting recordings as
                # manually disabled. Users expect monitor_status to survive an
                # app shutdown and resume on next launch.
                self.app.record_manager.predictor_metrics.interrupt_pending_operations()

            # Stop all active recordings
            if hasattr(self.app, "record_manager") and self.app.record_manager:
                active_recs = [
                    rec
                    for rec in self.app.record_manager.recordings
                    if getattr(rec, "is_recording", False) or getattr(rec, "monitor_status", False)
                ]
                for rec in active_recs:
                    self.app.record_manager.stop_recording(rec, manually_stopped=True)

            # Update UI to show shutdown state
            self.setEnabled(False)
            self.show_toast(tr("main_window.shutting_down"), duration=15000)

            # Launch async sequence to wait for transcoding tasks
            import asyncio

            asyncio.ensure_future(self._perform_shutdown())
        else:
            event.ignore()

    def _sync_sidebar_layout(self, animate: bool) -> None:
        forced_compact = self.width() < self.SIDEBAR_COLLAPSE_BREAKPOINT
        self.sidebar.set_auto_forced(forced_compact)

        if forced_compact:
            self.sidebar.set_collapsed(True, source="auto", animate=animate)
        else:
            self.sidebar.set_collapsed(self._sidebar_user_collapsed, source="auto", animate=animate)

    def _on_sidebar_collapsed_changed(self, collapsed: bool, source: str) -> None:
        if source != "manual":
            return

        # Under the compact breakpoint we enforce collapsed mode.
        if self.width() < self.SIDEBAR_COLLAPSE_BREAKPOINT:
            self.sidebar.set_collapsed(True, source="auto", animate=False)
            return

        self._sidebar_user_collapsed = collapsed
        current = self.app.settings.user_config.get("sidebar_collapsed")
        if current == collapsed:
            return

        self.app.settings.user_config["sidebar_collapsed"] = collapsed
        self.app.event_bus.run_task(
            self.app.config_manager.save_user_config,
            self.app.settings.user_config,
        )

    async def _perform_shutdown(self):
        """Wait for recordings and background tasks to finish, then quit."""
        from app.utils.logger import logger
        import asyncio

        logger.info("Starting graceful shutdown sequence...")

        # Sleep briefly to ensure "stop" signals propagate and transcoding background tasks spawn
        await asyncio.sleep(2.0)

        # Wait up to 30 seconds for active ffmpeg processes to clear
        for _ in range(60):
            active_processes = 0
            if hasattr(self.app, "process_manager") and self.app.process_manager:
                active_processes = len([p for p in self.app.process_manager.ffmpeg_processes if p.returncode is None])

            active_recorders = 0
            if hasattr(self.app, "record_manager") and self.app.record_manager:
                active_recorders = len(self.app.record_manager.active_recorders)

            bg_tasks = 0
            try:
                from app.core.runtime.process_manager import BackgroundService

                bg_tasks = BackgroundService.get_instance().tasks.unfinished_tasks
            except Exception:
                pass

            # Check for active asyncio tasks related to recording or transcoding
            asyncio_tasks_active = 0
            for task in asyncio.all_tasks():
                coro = task.get_coro()
                if coro and hasattr(coro, "__name__"):
                    if coro.__name__ in ["start_ffmpeg", "converts_mp4", "_do_converts_mp4", "start_recording"]:
                        asyncio_tasks_active += 1

            if active_processes == 0 and active_recorders == 0 and bg_tasks == 0 and asyncio_tasks_active == 0:
                logger.info("All background tasks and recordings finished. Safe to exit.")
                break

            logger.info(
                f"Waiting for shutdown... Recorders: {active_recorders}, FFMpeg: {active_processes}, BG_Tasks: {bg_tasks}, AsyncTasks: {asyncio_tasks_active}"
            )
            await asyncio.sleep(1.0)

        logger.info("Shutdown delay completed, quitting application.")
        from PySide6.QtWidgets import QApplication

        QApplication.instance().quit()


def run_qt_app():
    # Deprecated for main_qt.py approach
    pass
