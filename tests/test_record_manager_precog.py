"""Verify record_manager consumes Precog.snapshot instead of decide_queue directly."""

import asyncio
import unittest
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


class RecordManagerPrecogConsumption(unittest.TestCase):
    """Verify check_all_live_status reads Precog.snapshot fields."""

    def setUp(self):
        GlobalRecordingState.recordings = []

    def tearDown(self):
        GlobalRecordingState.recordings = []

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_consumes_snapshot_instead_of_decide_queue(
        self, mock_snapshot, mock_metrics
    ):
        """check_all_live_status reads adjusted_interval, likelihood,
        should_check, queue_key from Precog.snapshot."""
        mock_snap = MagicMock(spec=PrecogSnapshot)
        mock_snap.adjusted_interval = 60
        mock_snap.likelihood = 0.95
        mock_snap.should_check = True
        mock_snap.queue_key = "F"
        mock_snapshot.return_value = mock_snap

        async def _run():
            app = MagicMock()
            app.settings.user_config.get = _settings_get
            app.config_manager.config_path = "/tmp"
            app.config_manager.load_recordings_config.return_value = []
            app.language_manager.language = {"recording_manager": {}, "video_quality": {}}
            app.language_manager.add_observer = MagicMock()
            app.event_bus.publish = MagicMock()
            app.event_bus.run_task = MagicMock()

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

            recording = _make_recording(monitor_status=True)
            GlobalRecordingState.recordings = [recording]

            await manager.check_all_live_status()

            mock_snapshot.assert_called_once()
            args, kwargs = mock_snapshot.call_args
            self.assertIs(args[0], recording)
            self.assertIsNone(kwargs.get("now"))
            self.assertEqual(recording.loop_time_seconds, 60)

        asyncio.run(_run())

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_snapshot_should_check_false_skips_dispatch(
        self, mock_snapshot, mock_metrics
    ):
        """When snapshot.should_check is False, no queue dispatch happens."""
        mock_snap = MagicMock(spec=PrecogSnapshot)
        mock_snap.adjusted_interval = 300
        mock_snap.likelihood = 0.05
        mock_snap.should_check = False
        mock_snap.queue_key = "S"
        mock_snapshot.return_value = mock_snap

        async def _run():
            app = MagicMock()
            app.settings.user_config.get = _settings_get
            app.config_manager.config_path = "/tmp"
            app.config_manager.load_recordings_config.return_value = []
            app.language_manager.language = {"recording_manager": {}, "video_quality": {}}
            app.language_manager.add_observer = MagicMock()
            app.event_bus.publish = MagicMock()
            app.event_bus.run_task = MagicMock()

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

            recording = _make_recording(monitor_status=True)
            GlobalRecordingState.recordings = [recording]

            await manager.check_all_live_status()

            mock_snapshot.assert_called_once()
            self.assertEqual(recording.loop_time_seconds, 300)
            # is_checking stays False since not dispatched
            self.assertFalse(recording.is_checking)

        asyncio.run(_run())


def _settings_get(key, default=None):
    return {
        "loop_time_seconds": "300",
        "platform_max_concurrent_requests": "3",
        "ema_alpha_active": "0.1",
        "ema_alpha_offline": "0.01",
    }.get(key, default)
