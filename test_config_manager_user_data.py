import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.config.config_manager import ConfigManager


class ConfigManagerUserDataTests(unittest.TestCase):
    def write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def create_bundle_config(self, bundle_path: Path):
        config_dir = bundle_path / "config"
        self.write_json(config_dir / "default_settings.json", {"language": "English", "quality": "best"})
        self.write_json(config_dir / "language.json", {"English": "en", "Español": "es"})
        self.write_json(config_dir / "version.json", {"version_updates": [{"version": "1.0.0"}]})

    def test_default_user_data_path_uses_localappdata_on_windows(self):
        with mock.patch("sys.platform", "win32"), mock.patch.dict(
            os.environ,
            {"LOCALAPPDATA": r"C:\Users\tester\AppData\Local"},
            clear=False,
        ):
            self.assertEqual(
                ConfigManager.get_default_user_data_path(r"C:\Program Files\StreamCapEvo"),
                r"C:\Users\tester\AppData\Local\StreamCapEvo",
            )

    def test_uses_user_data_for_mutable_files_and_bundle_for_readonly_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_path = root / "install"
            bundle_path = root / "bundle"
            user_data_path = root / "user-data"
            run_path.mkdir()
            self.create_bundle_config(bundle_path)

            config_manager = ConfigManager(
                str(run_path),
                bundle_path=str(bundle_path),
                user_data_path=str(user_data_path),
            )

            self.assertEqual(Path(config_manager.config_path), user_data_path / "config")
            self.assertEqual(Path(config_manager.default_config_path), bundle_path / "config" / "default_settings.json")
            self.assertEqual(Path(config_manager.language_config_path), bundle_path / "config" / "language.json")
            self.assertTrue((user_data_path / "config" / "user_settings.json").exists())
            self.assertFalse((user_data_path / "config" / "default_settings.json").exists())
            self.assertEqual(config_manager.load_default_config()["quality"], "best")

    def test_migrates_legacy_mutable_files_without_overwriting_existing_user_data(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_path = root / "install"
            legacy_config = run_path / "config"
            bundle_path = root / "bundle"
            user_data_path = root / "user-data"
            user_config = user_data_path / "config"
            legacy_config.mkdir(parents=True)
            user_config.mkdir(parents=True)
            self.create_bundle_config(bundle_path)

            self.write_json(legacy_config / "user_settings.json", {"source": "legacy"})
            self.write_json(user_config / "user_settings.json", {"source": "existing"})
            self.write_json(legacy_config / "cookies.json", {"token": "legacy-cookie"})
            self.write_json(legacy_config / "accounts.json", {"platform": {"user": "legacy"}})
            self.write_json(legacy_config / "web_auth.json", {"auth": True})

            db_path = legacy_config / "recordings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE recordings (rec_id TEXT PRIMARY KEY, data TEXT)")
            conn.execute(
                "INSERT INTO recordings (rec_id, data) VALUES (?, ?)",
                ("rec-1", json.dumps({"rec_id": "rec-1", "title": "Legacy"})),
            )
            conn.commit()
            conn.close()

            config_manager = ConfigManager(
                str(run_path),
                bundle_path=str(bundle_path),
                user_data_path=str(user_data_path),
            )

            self.assertEqual(config_manager.load_user_config(), {"source": "existing"})
            self.assertEqual(config_manager.load_cookies_config(), {"token": "legacy-cookie"})
            self.assertEqual(config_manager.load_accounts_config(), {"platform": {"user": "legacy"}})
            self.assertEqual(config_manager.load_web_auth_config(), {"auth": True})
            self.assertEqual(config_manager.load_recordings_config(), [{"rec_id": "rec-1", "title": "Legacy"}])


if __name__ == "__main__":
    unittest.main()
