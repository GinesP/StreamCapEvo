"""Verify the enable_predictor_metrics toggle disables event generation in the hot path.

The toggle must skip creating/sending predictor metrics events while leaving
Precog decisions, dispatch, and recording behavior fully intact.
"""

import asyncio
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.recording.precog import PrecogSnapshot
from app.core.recording.record_manager import GlobalRecordingState, RecordingManager
from app.models.recording.recording_model import Recording


def _make_recording(**overrides) -> Recording:
    defaults = {
        "rec_id": "rec-test", "url": "http://example.com/live",
        "streamer_name": "TestStreamer", "record_format": "mp4",
        "quality": "HD", "segment_record": False, "segment_time": 0,
        "monitor_status": True, "scheduled_recording": False,
        "scheduled_start_time": "", "monitor_hours": "",
        "recording_dir": "/tmp/records", "enabled_message_push": False,
        "only_notify_no_record": False, "flv_use_direct_download": False,
    }
    defaults.update(overrides)
    return Recording(**defaults)


def _settings_get(user_config: dict):
    def get(key, default=None):
        return user_config.get(key, default)
    return get


async def _build_manager(app) -> RecordingManager:
    """Construct a RecordingManager and tear down its background workers."""
    manager = RecordingManager(app)
    for name in list(manager._pool_workers):
        for task in manager._pool_workers[name]:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, RuntimeError):
                pass
        manager._pool_workers[name] = []
    manager._adaptive_monitor.cancel()
    try:
        await manager._adaptive_monitor
    except (asyncio.CancelledError, RuntimeError):
        pass
    return manager


def _mock_app(user_config: dict):
    app = MagicMock()
    app.settings.user_config.get = _settings_get(user_config)
    app.config_manager.config_path = "/tmp"
    app.config_manager.load_recordings_config.return_value = []
    app.language_manager.language = {"recording_manager": {}, "video_quality": {"HD": "HD"}}
    app.language_manager.add_observer = MagicMock()
    app.event_bus.publish = MagicMock()
    app.event_bus.run_task = MagicMock()
    return app


class PredictorMetricsToggleTests(unittest.TestCase):
    def setUp(self):
        GlobalRecordingState.recordings = []

    def tearDown(self):
        GlobalRecordingState.recordings = []

    def test_default_settings_declares_flag_enabled(self):
        """The bundled default settings ship with metrics enabled by default."""
        defaults = json.loads(Path("config/default_settings.json").read_text(encoding="utf-8"))
        self.assertIs(defaults.get("enable_predictor_metrics"), True)

    def test_record_predictor_metric_noop_when_disabled(self):
        manager = object.__new__(RecordingManager)
        metrics_store = MagicMock()
        manager.predictor_metrics = metrics_store
        manager.settings = SimpleNamespace(user_config={"enable_predictor_metrics": False})

        manager._record_predictor_metric("check_result", {"rec_id": "r-1"})

        metrics_store.record_event.assert_not_called()

    def test_record_predictor_metric_records_when_enabled(self):
        manager = object.__new__(RecordingManager)
        metrics_store = MagicMock()
        manager.predictor_metrics = metrics_store
        manager.settings = SimpleNamespace(user_config={"enable_predictor_metrics": True})

        manager._record_predictor_metric("check_result", {"rec_id": "r-1"})

        metrics_store.record_event.assert_called_once_with("check_result", {"rec_id": "r-1"})

    def test_record_predictor_metric_defaults_to_enabled(self):
        manager = object.__new__(RecordingManager)
        metrics_store = MagicMock()
        manager.predictor_metrics = metrics_store
        manager.settings = SimpleNamespace(user_config={})

        manager._record_predictor_metric("check_dispatched", {"rec_id": "r-1"})

        metrics_store.record_event.assert_called_once_with("check_dispatched", {"rec_id": "r-1"})

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_hot_path_records_event_when_enabled(self, mock_snapshot, mock_metrics):
        """With metrics enabled, check_all_live_status records check_dispatched."""
        mock_snap = MagicMock(spec=PrecogSnapshot)
        mock_snap.adjusted_interval = 60
        mock_snap.likelihood = 0.95
        mock_snap.should_check = True
        mock_snap.queue_key = "F"
        mock_snapshot.return_value = mock_snap

        async def _run():
            manager = await _build_manager(_mock_app({}))
            recording = _make_recording(monitor_status=True)
            GlobalRecordingState.recordings = [recording]

            await manager.check_all_live_status()

            # Event generated and dispatch bookkeeping populated
            self.assertTrue(manager._predictor_dispatched_at)
            mock_metrics.return_value.record_event.assert_called()

        asyncio.run(_run())

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_hot_path_skips_event_creation_when_disabled(self, mock_snapshot, mock_metrics):
        """With metrics disabled, check_all_live_status creates no events but
        still dispatches the check (normal behavior intact)."""
        mock_snap = MagicMock(spec=PrecogSnapshot)
        mock_snap.adjusted_interval = 60
        mock_snap.likelihood = 0.95
        mock_snap.should_check = True
        mock_snap.queue_key = "F"
        mock_snapshot.return_value = mock_snap

        async def _run():
            manager = await _build_manager(_mock_app({"enable_predictor_metrics": False}))
            recording = _make_recording(monitor_status=True)
            GlobalRecordingState.recordings = [recording]

            await manager.check_all_live_status()

            # No event created, no dispatch bookkeeping allocated
            mock_metrics.return_value.record_event.assert_not_called()
            self.assertFalse(manager._predictor_dispatched_at)
            # Normal behavior intact: snapshot consumed and check dispatched
            self.assertEqual(recording._last_queue_key, "F")
            self.assertEqual(recording._last_likelihood, 0.95)
            self.assertTrue(recording.is_checking)

        asyncio.run(_run())
