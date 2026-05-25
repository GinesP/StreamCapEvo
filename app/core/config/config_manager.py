import asyncio
import json
import os
import shutil
import sqlite3
import sys
import uuid
from typing import TypeVar

import aiofiles
import aiosqlite

from ...utils.logger import logger
from ..data_import.migration import detect_evo_data, forward_migrate

T = TypeVar("T")

RECORDINGS_DB_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
)


MUTABLE_CONFIG_FILES = (
    "user_settings.json",
    "cookies.json",
    "accounts.json",
    "web_auth.json",
    "recordings.db",
    "recordings.db-journal",
    "recordings.db-shm",
    "recordings.db-wal",
    "recordings.json",
    "recordings.json.bak",
)


class ConfigManager:
    def __init__(self, run_path, bundle_path=None, user_data_path=None):
        self.run_path = run_path
        self.user_data_path = user_data_path or self.get_default_user_data_path(run_path)

        # User-writable data dir. In packaged Windows installs this lives under
        # %LOCALAPPDATA%\StreamCap instead of beside StreamCap.exe, so updates can
        # replace program files without touching user configuration or recordings.
        self.config_path = os.path.join(self.user_data_path, "config")
        # read-only bundled resources dir (sys._MEIPASS when frozen, else same as run_path)
        bundle_config_path = os.path.join(bundle_path or run_path, "config")

        self.language_config_path = os.path.join(bundle_config_path, "language.json")
        self.language_config_bundle_path = os.path.join(bundle_config_path, "language.json")
        self.default_config_path = os.path.join(bundle_config_path, "default_settings.json")
        self.default_config_bundle_path = os.path.join(bundle_config_path, "default_settings.json")
        self.user_config_path = os.path.join(self.config_path, "user_settings.json")
        self.cookies_config_path = os.path.join(self.config_path, "cookies.json")
        self.about_config_path = os.path.join(bundle_config_path, "version.json")
        self.recordings_config_path = os.path.join(self.config_path, "recordings.json")
        self.recordings_db_path = os.path.join(self.config_path, "recordings.db")
        self.accounts_config_path = os.path.join(self.config_path, "accounts.json")
        self.web_auth_config_path = os.path.join(self.config_path, "web_auth.json")

        self._cache = {}
        self._recordings_state_cache = {}
        
        # Check for forward migration from Evo 1.x data directory
        self._check_and_perform_forward_migration()
        
        os.makedirs(self.config_path, exist_ok=True)
        self.migrate_legacy_config()
        self.init()

    def _check_and_perform_forward_migration(self):
        """Check for Evo 1.x data and perform forward migration if needed.
        
        If the new StreamCapEvo path doesn't exist but the old StreamCap path does,
        and it contains Evo data (sentinel or config keys), migrate it forward.
        """
        # Skip if user_data_path was explicitly overridden
        if os.environ.get("STREAMCAPEVO_USER_DATA_DIR") or os.environ.get("STREAMCAP_USER_DATA_DIR"):
            return
        
        # Skip if we're not on Windows
        if sys.platform != "win32":
            return
        
        # Skip if new path already exists
        if os.path.exists(self.user_data_path):
            return
        
        # Calculate old path (StreamCap)
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            return
        
        old_path = os.path.join(local_app_data, "StreamCap")
        
        # Check if old path exists
        if not os.path.exists(old_path):
            return
        
        # Detect if old path contains Evo data
        detection = detect_evo_data(old_path)
        
        if detection.is_evo_data:
            logger.info(f"Evo 1.x data detected at {old_path}, performing forward migration")
            try:
                forward_migrate(old_path, self.user_data_path)
                logger.info(f"Forward migration completed successfully to {self.user_data_path}")
            except Exception as e:
                logger.error(f"Forward migration failed: {e}")
                # Continue with fresh directory if migration fails

    @staticmethod
    def get_default_user_data_path(run_path):
        override = os.environ.get("STREAMCAPEVO_USER_DATA_DIR") or os.environ.get("STREAMCAP_USER_DATA_DIR")
        if override:
            return override

        if sys.platform == "win32":
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data:
                return os.path.join(local_app_data, "StreamCapEvo")

        return run_path

    def migrate_legacy_config(self):
        legacy_config_path = os.path.join(self.run_path, "config")
        if os.path.abspath(legacy_config_path) == os.path.abspath(self.config_path):
            return
        if not os.path.isdir(legacy_config_path):
            return

        for filename in MUTABLE_CONFIG_FILES:
            source_path = os.path.join(legacy_config_path, filename)
            dest_path = os.path.join(self.config_path, filename)
            if not os.path.exists(source_path) or os.path.exists(dest_path):
                continue

            try:
                shutil.copy2(source_path, dest_path)
                logger.info(f"Migrated legacy configuration file to user data dir: {filename}")
            except Exception as e:
                logger.error(f"Failed to migrate legacy configuration file {filename}: {e}")

    def init(self):
        self.init_default_config()
        self.init_language_config()
        self.init_user_config()
        self.init_cookies_config()
        self.init_accounts_config()
        self.init_recordings_config()
        self.init_web_auth_config()
        # Warm up cache
        self.load_all_to_cache()

    def load_all_to_cache(self):
        """Pre-load all configurations into cache."""
        self._cache["default"] = self._load_config(self.default_config_path, "Error loading default config")
        self._cache["user"] = self._load_config(self.user_config_path, "Error loading user config")
        self._cache["recordings"] = self._load_recordings_db()
        self._cache["accounts"] = self._load_config(self.accounts_config_path, "Error loading accounts config")
        self._cache["cookies"] = self._load_config(self.cookies_config_path, "Error loading cookies config")
        self._cache["web_auth"] = self._load_config(self.web_auth_config_path, "Error loading web auth config")

    @staticmethod
    def _init_config(config_path, default_config=None):
        """Initialize a configuration file with default values if it does not exist."""
        if not os.path.exists(config_path):
            if default_config is None:
                default_config = {}
            try:
                with open(config_path, "w", encoding="utf-8") as file:
                    json.dump(default_config, file, ensure_ascii=False, indent=4)
                logger.info(f"Initialized configuration file: {config_path}")
            except Exception as e:
                logger.error(f"Failed to initialize configuration file {config_path}: {e}")

    def init_default_config(self):
        """Validate bundled default_settings exists; it is not user-mutable."""
        if not os.path.exists(self.default_config_path):
            logger.warning(f"Bundled default settings not found: {self.default_config_path}")

    def init_language_config(self):
        """Validate bundled language.json exists; it is not user-mutable."""
        if not os.path.exists(self.language_config_path):
            logger.warning(f"Bundled language config not found: {self.language_config_path}")

    def init_user_config(self):
        if os.path.exists(self.user_config_path) and self._load_config(self.user_config_path, "Check user config"):
            return
        if os.path.exists(self.default_config_path):
            shutil.copy(self.default_config_path, self.user_config_path)
        elif os.path.exists(self.default_config_bundle_path):
            shutil.copy(self.default_config_bundle_path, self.user_config_path)

    def init_cookies_config(self):
        cookies_config = {}
        self._init_config(self.cookies_config_path, cookies_config)

    def init_accounts_config(self):
        cookies_config = {}
        self._init_config(self.accounts_config_path, cookies_config)

    def init_recordings_config(self):
        self._init_recordings_db()

    @staticmethod
    def _configure_recordings_db(conn):
        """Apply SQLite settings for the recordings database connection."""
        for pragma in RECORDINGS_DB_PRAGMAS:
            conn.execute(pragma)

    @staticmethod
    async def _configure_recordings_db_async(db):
        """Apply SQLite settings for the async recordings database connection."""
        for pragma in RECORDINGS_DB_PRAGMAS:
            await db.execute(pragma)

    def _init_recordings_db(self):
        """Initialize SQLite database for recordings and migrate from JSON if needed."""
        conn = sqlite3.connect(self.recordings_db_path)
        try:
            self._configure_recordings_db(conn)
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS recordings (
                    rec_id TEXT PRIMARY KEY,
                    data TEXT
                )
            ''')
            conn.commit()
            
            # Check if migration from JSON is needed
            if os.path.exists(self.recordings_config_path):
                try:
                    with open(self.recordings_config_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    if data:
                        for rec in data:
                            rec_id = rec.get("rec_id")
                            if rec_id:
                                cursor.execute(
                                    "INSERT OR IGNORE INTO recordings (rec_id, data) VALUES (?, ?)",
                                    (rec_id, json.dumps(rec, ensure_ascii=False))
                                )
                        conn.commit()
                        logger.info("Migrated recordings.json to recordings.db")
                    
                    # Backup the old JSON file
                    backup_path = self.recordings_config_path + ".bak"
                    if not os.path.exists(backup_path):
                        shutil.move(self.recordings_config_path, backup_path)
                        logger.info(f"Backed up old recordings.json to {backup_path}")
                    else:
                        os.remove(self.recordings_config_path)
                        
                except Exception as e:
                    logger.error(f"Error migrating recordings.json: {e}")
        finally:
            conn.close()

    def _load_recordings_db(self):
        """Load all recordings from the SQLite database."""
        try:
            conn = sqlite3.connect(self.recordings_db_path)
            try:
                self._configure_recordings_db(conn)
                cursor = conn.cursor()
                cursor.execute("SELECT rec_id, data FROM recordings")
                rows = cursor.fetchall()
            finally:
                conn.close()
            
            recordings = []
            for row in rows:
                try:
                    rec_id, data_str = row
                    self._recordings_state_cache[rec_id] = data_str
                    recordings.append(json.loads(data_str))
                except Exception as e:
                    logger.error(f"Error parsing recording row from DB: {e}")
            return recordings
        except Exception as e:
            logger.error(f"Error loading recordings from DB: {e}")
            return []

    def init_web_auth_config(self):
        cookies_config = {}
        self._init_config(self.web_auth_config_path, cookies_config)

    @staticmethod
    def _load_config(config_path, error_message):
        """Load configuration from a JSON file with backup for corruption."""
        try:
            if not os.path.exists(config_path):
                return {}
            with open(config_path, encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON format in file: {config_path}")
            # Backup corrupted file
            try:
                import shutil
                backup_path = config_path + ".bak"
                shutil.copy2(config_path, backup_path)
                logger.info(f"Corrupted config backed up to: {backup_path}")
            except Exception as e:
                logger.error(f"Failed to backup corrupted config: {e}")
            return {}
        except Exception as e:
            logger.error(f"{error_message}: {e}")
            return {}

    def load_default_config(self):
        if "default" not in self._cache:
            self._cache["default"] = self._load_config(self.default_config_path, "An error occurred while loading default config")
        return self._cache["default"]

    def load_user_config(self):
        if "user" not in self._cache:
            self._cache["user"] = self._load_config(self.user_config_path, "An error occurred while loading user config")
        return self._cache["user"]

    def load_recordings_config(self):
        if "recordings" not in self._cache:
            self._cache["recordings"] = self._load_recordings_db()
        return self._cache["recordings"]

    def load_accounts_config(self):
        if "accounts" not in self._cache:
            self._cache["accounts"] = self._load_config(self.accounts_config_path, "An error occurred while loading accounts config")
        return self._cache["accounts"]

    def load_cookies_config(self):
        if "cookies" not in self._cache:
            self._cache["cookies"] = self._load_config(self.cookies_config_path, "An error occurred while loading cookies config")
        return self._cache["cookies"]

    def load_about_config(self):
        # About config might change on update, maybe don't cache or clear cache on need
        return self._load_config(self.about_config_path, "An error occurred while loading about config")

    def load_language_config(self):
        return self._load_config(self.language_config_path, "An error occurred while loading language config")

    def load_i18n_config(self, path):
        """Load i18n configuration from a JSON file."""
        return self._load_config(path, "An error occurred while loading i18n config")

    def load_web_auth_config(self):
        if "web_auth" not in self._cache:
            self._cache["web_auth"] = self._load_config(self.web_auth_config_path, "An error occurred while loading web auth config")
        return self._cache["web_auth"]

    @staticmethod
    async def _save_config(config_path, config, success_message, error_message):
        """Save configuration to a JSON file atomically using a temporary file."""
        tmp_path = config_path + f".{uuid.uuid4().hex}.tmp"
        try:
            # Write to temporary file first
            async with aiofiles.open(tmp_path, "w", encoding="utf-8") as file:
                await file.write(json.dumps(config, ensure_ascii=False, indent=4))
            
            # Atomic rename (on Windows, os.replace is atomic)
            os.replace(tmp_path, config_path)
            logger.info(success_message)
        except Exception as e:
            logger.error(f"{error_message}: {e}")
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except:
                    pass

    _db_lock = asyncio.Lock()

    async def save_recordings_config(self, config):
        self._cache["recordings"] = config
        
        # 1. Quick check for changes before acquiring lock or opening DB
        current_ids = {rec["rec_id"] for rec in config if "rec_id" in rec}
        existing_ids_in_cache = set(self._recordings_state_cache.keys())
        
        ids_to_delete = existing_ids_in_cache - current_ids
        batch_data = []
        
        for rec in config:
            rec_id = rec.get("rec_id")
            if rec_id:
                data_str = json.dumps(rec, ensure_ascii=False)
                if self._recordings_state_cache.get(rec_id) != data_str:
                    batch_data.append((rec_id, data_str))

        if not ids_to_delete and not batch_data:
            return

        async with self._db_lock:
            try:
                async with aiosqlite.connect(self.recordings_db_path) as db:
                    await self._configure_recordings_db_async(db)

                    # Execute deletions
                    if ids_to_delete:
                        await db.executemany(
                            "DELETE FROM recordings WHERE rec_id = ?", 
                            [(del_id,) for del_id in ids_to_delete]
                        )
                        for del_id in ids_to_delete:
                            self._recordings_state_cache.pop(del_id, None)
                    
                    # Execute upserts
                    if batch_data:
                        await db.executemany(
                            "INSERT OR REPLACE INTO recordings (rec_id, data) VALUES (?, ?)",
                            batch_data
                        )
                        for rec_id, data_str in batch_data:
                            self._recordings_state_cache[rec_id] = data_str
                    
                    await db.commit()
                
                change_summary = []
                if ids_to_delete: change_summary.append(f"{len(ids_to_delete)} deleted")
                if batch_data: change_summary.append(f"{len(batch_data)} updated/inserted")
                
                logger.info(f"Recordings database saved successfully ({', '.join(change_summary)}).")
            except Exception as e:
                logger.error(f"An error occurred while saving recordings config: {e}")

    async def save_accounts_config(self, config):
        self._cache["accounts"] = config
        await self._save_config(
            self.accounts_config_path,
            config,
            success_message="Accounts configuration saved.",
            error_message="An error occurred while saving accounts config",
        )

    async def save_web_auth_config(self, config):
        self._cache["web_auth"] = config
        await self._save_config(
            self.web_auth_config_path,
            config,
            success_message="Web auth configuration saved.",
            error_message="An error occurred while saving web auth config",
        )

    async def save_user_config(self, config):
        self._cache["user"] = config
        await self._save_config(
            self.user_config_path,
            config,
            success_message="User configuration saved.",
            error_message="An error occurred while saving user config",
        )

    async def save_cookies_config(self, config):
        self._cache["cookies"] = config
        await self._save_config(
            self.cookies_config_path,
            config,
            success_message="Cookies configuration saved.",
            error_message="An error occurred while saving cookies config",
        )

    def get_config_value(self, key: str, default: T = None) -> T:
        user_config = self.load_user_config()
        default_config = self.load_default_config()
        return user_config.get(key, default_config.get(key, default))
