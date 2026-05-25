"""
QtApp: Management class for the Qt version of StreamCapEvo.

Mirrors App in app_manager.py but integrates with PySide6.
Handles core logic initialization and links it to the Qt UI.
"""

import asyncio
import os
import time

from app.event_bus import EventBus
from app.core.config.config_manager import ConfigManager
from app.core.config.language_manager import LanguageManager
from app.core.recording.record_manager import RecordingManager
from app.core.runtime.process_manager import AsyncProcessManager
from app.core.update.update_checker import UpdateChecker
from app.initialization.installation_manager import InstallationManager
from app.utils.logger import logger
from app.utils import utils
from app import execute_dir, bundle_dir


class QtApp:
    """
    Main controller for the Qt-based application.
    
    Initializes core services and maintains references needed 
    by various managers.
    """

    def __init__(self, main_window=None):
        self.main_window = main_window
        self.event_bus = EventBus()
        self.event_bus.set_loop(asyncio.get_event_loop())
        
        self.run_path = execute_dir
        self.assets_dir = os.path.join(bundle_dir, "assets")
        
        # Flet compatibility attributes (placeholders) - Must be set BEFORE managers
        self.is_web_mode = False
        self.is_mobile = False
        self.recording_enabled = True
        self.page = None  # None for Qt
        self.subprocess_start_up_info = utils.get_startup_info()
        self.video_player = None

        # Core Services
        self.process_manager = AsyncProcessManager()
        self.config_manager = ConfigManager(self.run_path, bundle_path=bundle_dir)
        
        # Instantiate managers immediately so they are available for the UI
        from app.core.config.settings_logic import SettingsLogic
        self.settings = SettingsLogic(self)
        self.language_manager = LanguageManager(self)
        self.record_manager = RecordingManager(self)
        self.install_manager = InstallationManager(self)
        self.update_checker = UpdateChecker(self)

    @property
    def language_code(self):
        """Proxy property to get language_code from settings."""
        if self.settings:
            return self.settings.language_code
        return "en"

    async def initialize(self):
        """Asynchronously start background tasks and periodic checks."""
        logger.info("Starting QtApp background tasks...")
        
        # Start background tasks
        self.event_bus.run_task(self.install_manager.check_env)
        self.event_bus.run_task(self.record_manager.check_free_space)
        self.event_bus.run_task(self._check_for_updates_periodic)
        
        logger.info("QtApp background tasks started.")

    async def _check_for_updates_periodic(self):
        """Periodic update check logic."""
        try:
            # Reusing the same logic from app_manager.py
            if not self.update_checker.update_config["auto_check"]:
                return
                
            last_check_time = self.settings.user_config.get("last_update_check", 0)
            current_time = time.time()
            check_interval = self.update_checker.update_config["check_interval"]
            
            if current_time - last_check_time >= check_interval:
                update_info = await self.update_checker.check_for_updates()
                self.settings.user_config["last_update_check"] = current_time
                await self.config_manager.save_user_config(self.settings.user_config)

                if update_info.get("has_update", False):
                    logger.debug(f"DEBUG: Update found: {update_info.get('latest_version')}. Publishing update_found.")
                    # In Qt, we emit an event instead of calling show_update_dialog directly
                    self.event_bus.publish("update_found", update_info)
        except Exception as e:
            logger.error(f"Qt update check failed: {e}")

    async def start_periodic_tasks(self):
        """Start all periodic tasks."""
        await self.record_manager.setup_periodic_live_check(30)

    async def cleanup(self):
        """Cleanup before closing."""
        logger.info("Cleaning up QtApp...")
        await self.process_manager.cleanup()

    def add_ffmpeg_process(self, process):
        self.process_manager.add_process(process)
