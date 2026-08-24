"""Verify record_manager consumes Precog.snapshot instead of decide_queue directly."""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

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


class ShutdownDisablesMonitoringBeforeCheck(unittest.TestCase):
    """Verify that disabling monitoring (as done during shutdown) prevents
    check_all_live_status from dispatching checks."""

    def setUp(self):
        GlobalRecordingState.recordings = []

    def tearDown(self):
        GlobalRecordingState.recordings = []

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    def test_monitor_status_false_skips_all_dispatch(self, mock_metrics):
        """When all recordings have monitor_status=False, check_all_live_status
        dispatches nothing — simulating the shutdown fix."""
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

            # Simulate shutdown: all recordings have monitor_status=False
            rec1 = _make_recording(rec_id="rec-a", monitor_status=False)
            rec2 = _make_recording(rec_id="rec-b", monitor_status=False)
            GlobalRecordingState.recordings = [rec1, rec2]

            with patch(
                "app.core.recording.precog.Precog.snapshot",
            ) as mock_snapshot:
                await manager.check_all_live_status()

            # No Precog.snapshot calls because all recordings are skipped
            mock_snapshot.assert_not_called()

        asyncio.run(_run())


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
            # Hot path must NOT request the TEMP-DIAG debug payload
            self.assertNotIn("include_debug", kwargs)
            self.assertEqual(recording.loop_time_seconds, 300)

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

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_does_not_retain_full_snapshot_on_recording(
        self, mock_snapshot, mock_metrics
    ):
        """check_all_live_status does NOT store PrecogSnapshot on recording (memory regression fix).
        Only lightweight fallback fields are persisted. The full snapshot is used
        immediately for operational decisions but is no longer published."""
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

            # Full snapshot NOT retained on recording object
            self.assertFalse(hasattr(recording, "_last_snapshot"),
                             "PrecogSnapshot must not be stored on recording")
            # Lightweight fallback fields ARE persisted
            self.assertEqual(recording._last_queue_key, "F")
            self.assertEqual(recording._last_likelihood, 0.95)
            # Full snapshot is NOT published anywhere (dead code removed)
            published_events = [
                call.args[0] for call in app.event_bus.publish.call_args_list
            ]
            self.assertNotIn("precog_snapshot_batch", published_events)

        asyncio.run(_run())


    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    def test_stop_monitor_preserves_fallback_values(self, mock_metrics):
        """stop_monitor_recording preserves _last_queue_key and _last_likelihood
        for UI fallback."""
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
            recording._last_queue_key = "S"
            recording._last_likelihood = 0.42
            GlobalRecordingState.recordings = [recording]

            await manager.stop_monitor_recording(recording)

            # Fallback values preserved for UI badge display
            self.assertEqual(recording._last_queue_key, "S")
            self.assertEqual(recording._last_likelihood, 0.42)

        asyncio.run(_run())

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    @patch("app.core.recording.record_manager.LiveStreamRecorder")
    @patch("app.core.recording.record_manager.get_platform_info")
    def test_check_if_live_fetch_failure_clears_predictor_bookkeeping(
        self, mock_platform_info, mock_recorder_cls, mock_metrics
    ):
        async def _run():
            app = MagicMock()
            app.settings.user_config.get = _settings_get
            app.settings.get_video_save_path.return_value = "/tmp"
            app.recording_enabled = True
            app.config_manager.config_path = "/tmp"
            app.config_manager.load_recordings_config.return_value = []
            app.language_manager.language = {"recording_manager": {}, "video_quality": {"HD": "HD"}}
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
            manager._predictor_dispatched_at[recording.rec_id] = {"at": datetime.now(), "likelihood": 0.9}
            manager._predictor_last_offline_result_at[recording.rec_id] = MagicMock()
            manager.active_recorders[recording.rec_id] = MagicMock(should_stop=True)
            manager.check_free_space = AsyncMock()

            mock_platform_info.return_value = ("test-platform", "test-platform")
            mock_recorder = MagicMock()
            mock_recorder.fetch_stream = AsyncMock(return_value=None)
            mock_recorder_cls.return_value = mock_recorder

            await manager.check_if_live(recording)

            self.assertNotIn(recording.rec_id, manager._predictor_dispatched_at)
            self.assertNotIn(recording.rec_id, manager._predictor_last_offline_result_at)
            self.assertNotIn(recording.rec_id, manager.active_recorders)

        asyncio.run(_run())

    @patch("app.core.recording.record_manager.PredictorMetricsStore")
    def test_remove_recording_clears_predictor_and_active_recorder_bookkeeping(
        self, mock_metrics
    ):
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
            manager._predictor_dispatched_at[recording.rec_id] = {"at": datetime.now(), "likelihood": 0.5}
            manager._predictor_last_offline_result_at[recording.rec_id] = MagicMock()
            manager.active_recorders[recording.rec_id] = MagicMock()

            await manager.remove_recording(recording)

            self.assertNotIn(recording.rec_id, manager._predictor_dispatched_at)
            self.assertNotIn(recording.rec_id, manager._predictor_last_offline_result_at)
            self.assertNotIn(recording.rec_id, manager.active_recorders)
            self.assertNotIn(recording, GlobalRecordingState.recordings)

        asyncio.run(_run())


def _settings_get(key, default=None):
    return {
        "loop_time_seconds": "300",
        "platform_max_concurrent_requests": "3",
        "ema_alpha_active": "0.1",
        "ema_alpha_offline": "0.01",
    }.get(key, default)
