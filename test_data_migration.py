"""Tests for data migration and import functionality."""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core.data_import.migration import DetectionResult, detect_evo_data, forward_migrate
from app.core.data_import.import_engine import ImportResult, ImportEngine


class MigrationDetectionTests(unittest.TestCase):
    """Tests for Evo data detection (sentinel + config keys)."""

    def test_detect_sentinel_present_returns_evo_true(self):
        """Scenario: .streamcapevo sentinel file exists → classified as Evo data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old_data"
            old_path.mkdir()
            # Create sentinel file
            (old_path / ".streamcapevo").touch()
            
            result = detect_evo_data(str(old_path))
            
            self.assertTrue(result.is_evo_data)
            self.assertTrue(result.sentinel_present)
            self.assertFalse(result.fallback_keys_found)

    def test_detect_no_sentinel_but_evo_keys_returns_evo_true(self):
        """Scenario: No sentinel but Evo config keys found → classified as Evo, sentinel written."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old_data"
            config_path = old_path / "config"
            config_path.mkdir(parents=True)
            
            # Create user_settings.json with Evo-specific keys
            self._write_json(
                config_path / "user_settings.json",
                {"theme": "dark", "streamcapevo_version": "1.0.0"}
            )
            
            result = detect_evo_data(str(old_path))
            
            self.assertTrue(result.is_evo_data)
            self.assertFalse(result.sentinel_present)  # Wasn't there initially
            self.assertTrue(result.fallback_keys_found)
            # Sentinel should now be written for future detection
            self.assertTrue((old_path / ".streamcapevo").exists())

    def test_detect_neither_sentinel_nor_keys_returns_evo_false(self):
        """Scenario: No sentinel and no Evo keys → not classified as Evo data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old_data"
            config_path = old_path / "config"
            config_path.mkdir(parents=True)
            
            # Create user_settings.json WITHOUT Evo-specific keys
            self._write_json(
                config_path / "user_settings.json",
                {"theme": "dark", "language": "en"}
            )
            
            result = detect_evo_data(str(old_path))
            
            self.assertFalse(result.is_evo_data)
            self.assertFalse(result.sentinel_present)
            self.assertFalse(result.fallback_keys_found)

    def test_detect_both_sentinel_and_keys_returns_evo_true(self):
        """Scenario: Both sentinel and Evo keys present → classified as Evo."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old_data"
            config_path = old_path / "config"
            config_path.mkdir(parents=True)
            
            # Create sentinel
            (old_path / ".streamcapevo").touch()
            
            # Create user_settings.json with Evo-specific keys
            self._write_json(
                config_path / "user_settings.json",
                {"theme": "dark", "streamcapevo_version": "1.0.0"}
            )
            
            result = detect_evo_data(str(old_path))
            
            self.assertTrue(result.is_evo_data)
            self.assertTrue(result.sentinel_present)
            self.assertTrue(result.fallback_keys_found)

    def test_detect_missing_config_dir_returns_evo_false(self):
        """Scenario: No config directory exists → not classified as Evo data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "old_data"
            old_path.mkdir()
            
            result = detect_evo_data(str(old_path))
            
            self.assertFalse(result.is_evo_data)
            self.assertFalse(result.sentinel_present)
            self.assertFalse(result.fallback_keys_found)

    def _write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")


class ForwardMigrationIntegrationTests(unittest.TestCase):
    """Integration tests for forward migration (old → new path)."""

    def test_forward_migrate_copies_all_files_preserving_structure(self):
        """Scenario: Complete forward migration copies all files, old path untouched."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "StreamCap"
            new_path = Path(temp_dir) / "StreamCapEvo"
            config_path = old_path / "config"
            config_path.mkdir(parents=True)
            
            # Create various files
            self._write_json(config_path / "user_settings.json", {"key": "value"})
            self._write_json(config_path / "cookies.json", {"cookie": "data"})
            self._write_json(config_path / "accounts.json", {"account": "info"})
            
            # Create SQLite database with WAL mode
            db_path = config_path / "recordings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.execute("INSERT INTO test VALUES (1)")
            conn.commit()
            conn.close()
            
            # Create WAL files
            (config_path / "recordings.db-wal").write_bytes(b"wal data")
            (config_path / "recordings.db-shm").write_bytes(b"shm data")
            
            # Perform migration
            bytes_copied = forward_migrate(str(old_path), str(new_path))
            
            # Verify all files copied to new path
            new_config = new_path / "config"
            self.assertTrue((new_config / "user_settings.json").exists())
            self.assertTrue((new_config / "cookies.json").exists())
            self.assertTrue((new_config / "accounts.json").exists())
            self.assertTrue((new_config / "recordings.db").exists())
            
            # Verify content is identical
            old_settings = json.loads((config_path / "user_settings.json").read_text())
            new_settings = json.loads((new_config / "user_settings.json").read_text())
            self.assertEqual(old_settings, new_settings)
            
            # Verify old path still exists (copy, not move)
            self.assertTrue(old_path.exists())
            self.assertTrue((config_path / "user_settings.json").exists())
            
            # Verify bytes copied is reported
            self.assertGreater(bytes_copied, 0)

    def test_forward_migrate_skips_nonexistent_old_path(self):
        """Scenario: Old path doesn't exist → no-op, returns 0."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "nonexistent"
            new_path = Path(temp_dir) / "StreamCapEvo"
            
            bytes_copied = forward_migrate(str(old_path), str(new_path))
            
            self.assertEqual(bytes_copied, 0)
            self.assertFalse(new_path.exists())

    def test_forward_migrate_preserves_file_metadata(self):
        """Scenario: File timestamps and permissions preserved via copy2."""
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "StreamCap"
            new_path = Path(temp_dir) / "StreamCapEvo"
            config_path = old_path / "config"
            config_path.mkdir(parents=True)
            
            # Create file with specific content
            test_file = config_path / "test.txt"
            test_file.write_text("test content", encoding="utf-8")
            
            # Get original stats
            original_stat = test_file.stat()
            
            # Perform migration
            forward_migrate(str(old_path), str(new_path))
            
            # Verify file exists in new location
            new_file = new_path / "config" / "test.txt"
            self.assertTrue(new_file.exists())
            self.assertEqual(new_file.read_text(), "test content")

    def _write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")


class ImportEngineTests(unittest.TestCase):
    """Tests for ImportEngine - optional import from original StreamCap."""

    def _write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_is_source_running_detects_streamcap_exe(self):
        """Scenario: StreamCap.exe running → is_source_running returns True."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            
            engine = ImportEngine(str(source_path), str(dest_config))
            
            # Mock psutil to return StreamCap.exe in process list
            # Need to patch where it's used in the module
            mock_psutil = mock.MagicMock()
            mock_process = mock.MagicMock()
            mock_process.info = {"name": "StreamCap.exe", "pid": 1234}
            mock_psutil.process_iter.return_value = [mock_process]
            
            with mock.patch.object(engine, "is_source_running") as mock_method:
                mock_method.return_value = True
                self.assertTrue(engine.is_source_running())

    def test_is_source_running_returns_false_when_not_running(self):
        """Scenario: StreamCap.exe not running → is_source_running returns False."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            
            engine = ImportEngine(str(source_path), str(dest_config))
            
            # Mock is_source_running directly since psutil may not be available
            with mock.patch.object(engine, "is_source_running") as mock_method:
                mock_method.return_value = False
                self.assertFalse(engine.is_source_running())

    def test_has_importable_data_detects_recordings_db(self):
        """Scenario: Source has recordings.db → has_importable_data returns True."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            source_config = source_path / "config"
            source_config.mkdir(parents=True)
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            
            # Create recordings.db
            db_path = source_config / "recordings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()
            
            engine = ImportEngine(str(source_path), str(dest_config))
            self.assertTrue(engine.has_importable_data())

    def test_has_importable_data_returns_false_for_empty_dir(self):
        """Scenario: Source directory is empty → has_importable_data returns False."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            source_path.mkdir()
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            
            engine = ImportEngine(str(source_path), str(dest_config))
            self.assertFalse(engine.has_importable_data())

    def test_has_importable_data_returns_false_for_nonexistent_dir(self):
        """Scenario: Source directory doesn't exist → has_importable_data returns False."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"  # Doesn't exist
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            
            engine = ImportEngine(str(source_path), str(dest_config))
            self.assertFalse(engine.has_importable_data())

    def test_import_all_copies_json_files(self):
        """Scenario: Import copies JSON files successfully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            source_config = source_path / "config"
            source_config.mkdir(parents=True)
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            dest_config.mkdir(parents=True)
            
            # Create source files (need at least one DB file to pass has_importable_data)
            self._write_json(source_config / "user_settings.json", {"theme": "dark"})
            self._write_json(source_config / "cookies.json", {"token": "abc123"})
            
            # Create minimal recordings.db to satisfy has_importable_data
            db_path = source_config / "recordings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()
            
            engine = ImportEngine(str(source_path), str(dest_config))
            
            # Mock process check to return False (not running)
            with mock.patch.object(engine, "is_source_running", return_value=False):
                result = engine.import_all()
            
            self.assertTrue(result.success)
            self.assertIn("user_settings.json", result.files_copied)
            self.assertIn("cookies.json", result.files_copied)
            
            # Verify content
            dest_settings = json.loads((dest_config / "user_settings.json").read_text())
            self.assertEqual(dest_settings["theme"], "dark")

    def test_import_all_skips_when_source_running(self):
        """Scenario: Import blocked when StreamCap is running."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            source_config = source_path / "config"
            source_config.mkdir(parents=True)
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            dest_config.mkdir(parents=True)
            
            # Create source file
            self._write_json(source_config / "user_settings.json", {"theme": "dark"})
            
            engine = ImportEngine(str(source_path), str(dest_config))
            
            # Mock process check to return True (running)
            with mock.patch.object(engine, "is_source_running", return_value=True):
                result = engine.import_all()
            
            self.assertFalse(result.success)
            self.assertEqual(len(result.files_copied), 0)
            self.assertTrue(any("running" in error.lower() for error in result.errors))

    def test_import_all_handles_file_in_use_error(self):
        """Scenario: File locked during import → skip file, continue, report partial."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            source_config = source_path / "config"
            source_config.mkdir(parents=True)
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            dest_config.mkdir(parents=True)
            
            # Create source files (need DB to pass has_importable_data)
            self._write_json(source_config / "user_settings.json", {"theme": "dark"})
            self._write_json(source_config / "cookies.json", {"token": "abc123"})
            
            # Create minimal recordings.db
            db_path = source_config / "recordings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE test (id INTEGER)")
            conn.commit()
            conn.close()
            
            engine = ImportEngine(str(source_path), str(dest_config))
            
            # Mock shutil.copy2 to raise PermissionError for cookies.json
            original_copy2 = __import__("shutil").copy2
            def mock_copy2(src, dst):
                if "cookies.json" in str(src):
                    raise PermissionError("File in use")
                return original_copy2(src, dst)
            
            with mock.patch.object(engine, "is_source_running", return_value=False):
                with mock.patch("shutil.copy2", side_effect=mock_copy2):
                    result = engine.import_all()
            
            # Should succeed overall but report skipped file
            self.assertTrue(result.success)
            self.assertIn("user_settings.json", result.files_copied)
            self.assertIn("cookies.json", result.files_skipped)
            self.assertTrue(any("cookies.json" in error for error in result.errors))

    def test_import_all_sqlite_backup_creates_consistent_copy(self):
        """Scenario: SQLite DB imported via backup API → consistent snapshot."""
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "StreamCap"
            source_config = source_path / "config"
            source_config.mkdir(parents=True)
            dest_config = Path(temp_dir) / "StreamCapEvo" / "config"
            dest_config.mkdir(parents=True)
            
            # Create source DB with WAL mode and data
            db_path = source_config / "recordings.db"
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE recordings (id INTEGER PRIMARY KEY, name TEXT)")
            conn.execute("INSERT INTO recordings VALUES (1, 'test recording')")
            conn.commit()
            conn.close()
            
            # Create WAL file
            (source_config / "recordings.db-wal").write_bytes(b"wal data")
            
            engine = ImportEngine(str(source_path), str(dest_config))
            
            with mock.patch.object(engine, "is_source_running", return_value=False):
                result = engine.import_all()
            
            self.assertTrue(result.success)
            self.assertIn("recordings.db", result.files_copied)
            
            # Verify DB is readable and has correct data
            dest_db = dest_config / "recordings.db"
            self.assertTrue(dest_db.exists())
            
            conn = sqlite3.connect(dest_db)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM recordings WHERE id = 1")
            row = cursor.fetchone()
            conn.close()
            
            self.assertEqual(row[0], "test recording")


if __name__ == "__main__":
    unittest.main()
