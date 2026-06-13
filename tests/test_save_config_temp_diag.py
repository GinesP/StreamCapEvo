"""TEMP-DIAG: verify field-level change stats logged by save_recordings_config.

This test confirms that when recordings are saved with field-level changes,
the TEMP-DIAG instrumentation logs the most commonly changed field names.
It does NOT require a real database — it patches aiosqlite so the method
proceeds past the lock without IO.

Remove this file when the TEMP-DIAG instrumentation is cleaned up.
"""

import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from loguru import logger as loguru_logger

from app.core.config.config_manager import ConfigManager


class TestSaveConfigTempDiag(unittest.TestCase):
    """Verify TEMP-DIAG field-change aggregation in save_recordings_config."""

    def setUp(self):
        patcher = patch("app.core.config.config_manager.aiosqlite")
        self.mock_aiosqlite = patcher.start()
        self.addCleanup(patcher.stop)

        self.cm = ConfigManager.__new__(ConfigManager)
        self.cm.recordings_db_path = ":memory:"
        self.cm._recordings_state_cache = {}
        self.cm._cache = {}
        self.cm._db_lock = MagicMock()
        self.cm._db_lock.__aenter__ = AsyncMock()
        self.cm._db_lock.__aexit__ = AsyncMock()

    def _prime_cache(self, rid: str, **fields) -> None:
        """Insert a recording into the in-memory state cache."""
        self.cm._recordings_state_cache[rid] = json.dumps(
            {"rec_id": rid, **fields}, ensure_ascii=False
        )

    def _run_save(self, config: list[dict]) -> None:
        """Run save_recordings_config synchronously with DB mocked."""
        with patch.object(self.cm, "_configure_recordings_db_async", AsyncMock()):
            import asyncio
            asyncio.run(self.cm.save_recordings_config(config))

    def _capture_loguru(self) -> list[str]:
        """Install a loguru sink that records messages; returns the list."""
        lines: list[str] = []
        sink_id = loguru_logger.add(
            lambda msg: lines.append(msg),
            format="{message}",
            filter=lambda r: "TEMP-DIAG save_recordings_config" in r["message"],
        )
        self.addCleanup(loguru_logger.remove, sink_id)
        return lines

    # --- tests ---

    def test_diag_reports_top_changed_fields(self):
        """Single recording with multiple field changes → top fields logged."""
        self._prime_cache(
            "rec-1",
            monitor_status=False,
            quality="HD",
            priority_score=1.0,
            live_check_count=5,
            live_found_count=2,
        )
        new = [
            {
                "rec_id": "rec-1",
                "monitor_status": True,   # changed
                "quality": "HD",           # unchanged
                "priority_score": 2.5,     # changed
                "live_check_count": 5,     # unchanged
                "live_found_count": 3,     # changed
            }
        ]

        lines = self._capture_loguru()
        self._run_save(new)
        self.assertEqual(len(lines), 1, msg="Expected exactly one TEMP-DIAG log line")
        self.assertIn("monitor_status", lines[0])
        self.assertIn("priority_score", lines[0])
        self.assertIn("live_found_count", lines[0])

    def test_diag_aggregates_across_records(self):
        """Multiple changed records → counter aggregates top fields."""
        self._prime_cache("r1", monitor_status=False, quality="HD", priority_score=1.0)
        self._prime_cache("r2", monitor_status=False, quality="SD", priority_score=2.0)
        self._prime_cache("r3", monitor_status=True, quality="FHD", priority_score=3.0)

        new = [
            {"rec_id": "r1", "monitor_status": True, "quality": "HD", "priority_score": 1.5},
            {"rec_id": "r2", "monitor_status": True, "quality": "SD", "priority_score": 2.0},
            {"rec_id": "r3", "monitor_status": True, "quality": "FHD", "priority_score": 3.0},
        ]

        lines = self._capture_loguru()
        self._run_save(new)
        self.assertEqual(len(lines), 1)
        self.assertIn("2 records changed", lines[0])

    def test_no_diag_when_no_changes(self):
        """No changed records → no TEMP-DIAG log at all."""
        self._prime_cache("r1", monitor_status=True, quality="HD")
        new = [{"rec_id": "r1", "monitor_status": True, "quality": "HD"}]

        lines = self._capture_loguru()
        self._run_save(new)
        self.assertEqual(len(lines), 0, msg="No TEMP-DIAG log expected when nothing changes")

    def test_diag_highlights_churning_field(self):
        """Many records changing the same field → that field appears in top."""
        for i in range(5):
            self._prime_cache(f"r{i}", monitor_status=False, priority_score=float(i))

        new = [
            {"rec_id": f"r{i}", "monitor_status": True, "priority_score": float(i)}
            for i in range(5)
        ]

        lines = self._capture_loguru()
        self._run_save(new)
        self.assertEqual(len(lines), 1)
        self.assertIn("monitor_status", lines[0])


if __name__ == "__main__":
    unittest.main()
