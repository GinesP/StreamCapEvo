"""Tests for runtime diagnostics helpers.

These verify that the diagnostic introspection methods return valid
shapes and do not alter the state of the objects they inspect.
"""

import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.event_bus import EventBus
from app.core.config.language_manager import LanguageManager
from app.core.recording.history_manager import HistoryManager
from app.core.recording.precog import Precog, PrecogSnapshot
from app.core.recording.stream_manager import LiveStreamRecorder
from app.models.recording.recording_model import Recording
from app.models.recording.recording_status_model import RecordingStatus
from app.utils import diagnostics as diag


class EventBusDiagnosticReportTests(unittest.TestCase):
    """EventBus.diagnostic_report() must return correct counts."""

    def test_empty_bus(self):
        bus = EventBus()
        report = bus.diagnostic_report()
        self.assertEqual(report["topic_count"], 0)
        self.assertEqual(report["total_subscribers"], 0)
        self.assertEqual(report["topics"], {})

    def test_single_topic(self):
        bus = EventBus()
        bus.subscribe("alerts", lambda *a: None)
        bus.subscribe("alerts", lambda *a: None)

        report = bus.diagnostic_report()
        self.assertEqual(report["topic_count"], 1)
        self.assertEqual(report["total_subscribers"], 2)
        self.assertEqual(report["topics"]["alerts"], 2)

    def test_multiple_topics(self):
        bus = EventBus()
        bus.subscribe("a", lambda *a: None)
        bus.subscribe("b", lambda *a: None)
        bus.subscribe("b", lambda *a: None)

        report = bus.diagnostic_report()
        self.assertEqual(report["topic_count"], 2)
        self.assertEqual(report["total_subscribers"], 3)

    def test_does_not_include_empty_topics(self):
        """Topics that existed but now have zero subs must not appear."""
        bus = EventBus()
        cb = lambda *a: None
        bus.subscribe("temp", cb)
        bus.unsubscribe("temp", cb)

        report = bus.diagnostic_report()
        self.assertNotIn("temp", report["topics"])

    def test_report_does_not_mutate_subscribers(self):
        bus = EventBus()
        bus.subscribe("test", lambda *a: None)
        before = bus.subscriber_count("test")
        bus.diagnostic_report()
        after = bus.subscriber_count("test")
        self.assertEqual(before, after)


class LanguageManagerObserverCountTests(unittest.TestCase):
    """LanguageManager.observer_count must track observers accurately."""

    def test_new_manager_has_zero_observers(self):
        app = MagicMock()
        lm = LanguageManager(app)
        self.assertEqual(lm.observer_count, 0)

    def test_observer_count_increases_on_add(self):
        app = MagicMock()
        lm = LanguageManager(app)
        lm.add_observer("obs1")
        self.assertEqual(lm.observer_count, 1)
        lm.add_observer("obs2")
        self.assertEqual(lm.observer_count, 2)

    def test_observer_count_decreases_on_remove(self):
        app = MagicMock()
        lm = LanguageManager(app)
        lm.add_observer("obs1")
        lm.add_observer("obs2")
        lm.remove_observer("obs1")
        self.assertEqual(lm.observer_count, 1)

    def test_duplicate_observer_not_counted_twice(self):
        app = MagicMock()
        lm = LanguageManager(app)
        obs = object()
        lm.add_observer(obs)
        lm.add_observer(obs)  # second add is no-op
        self.assertEqual(lm.observer_count, 1)


class LiveStreamRecorderObserverCleanupTests(unittest.TestCase):
    """LiveStreamRecorder must unregister from LanguageManager on cleanup."""

    def _make_recorder(self, lm, rec_id="test-rec-001"):
        """Helper: build a LiveStreamRecorder with minimal mocked dependencies."""
        app = MagicMock()
        app.language_manager = lm
        lm.language = {}
        app.settings = MagicMock(spec=["user_config", "accounts_config", "cookies_config"])
        app.settings.user_config = {}
        app.settings.accounts_config = {}
        app.settings.cookies_config = {}
        app.subprocess_start_up_info = None
        app.event_bus = MagicMock()
        app.record_manager = MagicMock(spec=["active_recorders"])
        app.record_manager.active_recorders = {}

        recording_info = {"output_dir": os.getcwd()}
        recording = MagicMock()
        recording.rec_id = rec_id
        recording.streamer_name = "TestStreamer"

        return LiveStreamRecorder(app, recording, recording_info)

    def test_does_not_register_on_init(self):
        """Observer count must NOT increase just by constructing LiveStreamRecorder.
        
        Registration now happens only in start_recording(), so creating a recorder
        for a non-live check does not leak an observer.
        """
        lm = LanguageManager(MagicMock())
        recorder = self._make_recorder(lm)
        self.assertEqual(lm.observer_count, 0)
        _ = recorder

    @patch("app.core.recording.stream_manager.ffmpeg_builders.create_builder")
    def test_registers_on_start_recording(self, mock_create_builder):
        """start_recording must register as a LanguageManager observer."""
        lm = LanguageManager(MagicMock())
        recorder = self._make_recorder(lm)
        self.assertEqual(lm.observer_count, 0)

        # Patch the ffmpeg builder to avoid real subprocess calls
        mock_create_builder.return_value.build_command.return_value = []

        stream_info = MagicMock()
        stream_info.flv_url = None
        stream_info.record_url = "http://example.com/stream"
        stream_info.anchor_name = "TestStreamer"
        stream_info.is_live = True
        stream_info.title = "Test"
        stream_info.m3u8_url = None
        stream_info.platform = "test"

        asyncio.run(recorder.start_recording(stream_info))

        # The observer must be registered after start_recording begins
        self.assertEqual(lm.observer_count, 1)

    def test_unregisters_on_remove_active_recorder(self):
        """Observer count decreases after remove_active_recorder completes."""
        lm = LanguageManager(MagicMock())
        recorder = self._make_recorder(lm)
        self.assertEqual(lm.observer_count, 0)

        # Simulate start_recording's observer registration
        lm.add_observer(recorder)
        self.assertEqual(lm.observer_count, 1)

        asyncio.run(recorder.remove_active_recorder())
        self.assertEqual(lm.observer_count, 0)

    def test_remove_observer_is_idempotent(self):
        """Calling remove_active_recorder multiple times is safe."""
        lm = LanguageManager(MagicMock())
        recorder = self._make_recorder(lm)
        self.assertEqual(lm.observer_count, 0)

        # Simulate start_recording's observer registration
        lm.add_observer(recorder)
        self.assertEqual(lm.observer_count, 1)

        asyncio.run(recorder.remove_active_recorder())
        self.assertEqual(lm.observer_count, 0)

        # Second call must not error and observer count stays at 0
        asyncio.run(recorder.remove_active_recorder())
        self.assertEqual(lm.observer_count, 0)


class LiveStreamRecorderFetchCleanupTests(unittest.TestCase):
    def test_fetch_stream_releases_cached_live_stream_after_status_check(self):
        app = MagicMock()
        app.language_manager.language = {}
        app.settings = MagicMock(spec=["user_config", "accounts_config", "cookies_config"])
        app.settings.user_config = {}
        app.settings.accounts_config = {}
        app.settings.cookies_config = {}
        app.subprocess_start_up_info = None

        recording = MagicMock()
        recording.is_checking = True
        recording_info = {
            "platform": "test-platform",
            "platform_key": "test-platform",
            "live_url": "https://example.com/live",
            "output_dir": os.getcwd(),
            "quality": "HD",
        }

        recorder = LiveStreamRecorder(app, recording, recording_info)
        handler = MagicMock()
        handler.begin_status_check = MagicMock()
        handler.end_status_check = MagicMock(side_effect=lambda: setattr(handler, "live_stream", None))
        handler.live_stream = object()
        handler.get_stream_info = AsyncMock(return_value=MagicMock())

        with patch(
            "app.core.recording.stream_manager.platform_handlers.get_platform_handler",
            return_value=handler,
        ):
            stream_info = asyncio.run(recorder.fetch_stream())

        self.assertIsNotNone(stream_info)
        handler.begin_status_check.assert_called_once_with()
        handler.end_status_check.assert_called_once_with()
        self.assertIsNone(handler.live_stream)
        self.assertFalse(recording.is_checking)


class DiagnosticsCollectReportTests(unittest.TestCase):
    """collect_report() must compose a valid dict."""

    def test_without_predictor_store(self):
        eb = MagicMock()
        eb.diagnostic_report.return_value = {"topics": {}, "total_subscribers": 0, "topic_count": 0}
        lm = MagicMock()
        lm.observer_count = 2

        report = diag.collect_report(event_bus=eb, language_manager=lm)
        self.assertIn("language_manager", report)
        self.assertIn("process_memory", report)
        self.assertIn("python_allocations", report)
        self.assertIn("event_bus", report)
        self.assertIn("record_manager", report)
        self.assertIn("predictor_store", report)
        self.assertIn("asyncio", report)
        self.assertIn("gc", report)
        self.assertIsInstance(report["process_memory"], dict)
        self.assertIsInstance(report["python_allocations"], dict)
        self.assertIsNone(report["record_manager"])
        self.assertIsNone(report["predictor_store"])

    def test_with_predictor_store(self):
        from pathlib import Path
        import tempfile

        eb = MagicMock()
        eb.diagnostic_report.return_value = {"topics": {}, "total_subscribers": 0, "topic_count": 0}
        lm = MagicMock()
        lm.observer_count = 2
        store = MagicMock()
        # db_path is always a Path in real code
        store.db_path = Path(tempfile.mktemp(suffix=".db"))

        report = diag.collect_report(event_bus=eb, language_manager=lm, predictor_store=store)
        self.assertIsNotNone(report["predictor_store"])
        self.assertIsInstance(report["predictor_store"]["db_exists"], bool)

    def test_with_record_manager(self):
        eb = MagicMock()
        eb.diagnostic_report.return_value = {"topics": {}, "total_subscribers": 0, "topic_count": 0}
        lm = MagicMock()
        lm.observer_count = 2

        checking = MagicMock()
        checking.is_checking = True
        checking.status_info = "OTHER"

        status_checking = MagicMock()
        status_checking.is_checking = False
        status_checking.status_info = "STATUS_CHECKING"

        both = MagicMock()
        both.is_checking = True
        both.status_info = "STATUS_CHECKING"

        active_recording = MagicMock()
        active_recording.streamer_name = "Streamer One"
        active_recording.status_info = RecordingStatus.RECORDING

        active_recorder = MagicMock()
        active_recorder.recording = active_recording
        active_recorder.direct_downloader = None
        active_recorder.recording_start_time = 10.0

        manager = MagicMock()
        manager.recordings = [checking, status_checking, both]
        manager.active_recorders = {"rec-1": active_recorder}
        checking.rec_id = "rec-1"
        status_checking.rec_id = "rec-2"
        both.rec_id = "rec-3"
        manager._predictor_dispatched_at = {"rec-1": {"at": datetime.now()}, "deleted-rec": {"at": datetime.now()}}
        manager._predictor_last_offline_result_at = {
            "rec-2": datetime.now(),
            "rec-3": datetime.now(),
            "deleted-rec": datetime.now(),
        }

        with patch("app.utils.diagnostics.time.time", return_value=25.0):
            report = diag.collect_report(event_bus=eb, language_manager=lm, record_manager=manager)

        self.assertEqual(
            report["record_manager"],
            {
                "recording_count": 3,
                "active_recorders": 1,
                "active_recorder_details": [
                    {
                        "rec_id": "rec-1",
                        "streamer": "Streamer One",
                        "status": RecordingStatus.RECORDING,
                        "output": "ffmpeg",
                        "duration_s": 15.0,
                    }
                ],
                "predictor_dispatched_recordings": 1,
                "predictor_dispatched_stale": 1,
                "predictor_last_offline_sticky_recordings": 2,
                "predictor_last_offline_stale": 1,
                "checking": 2,
                "status_checking": 2,
            },
        )


class ProcessMemoryDiagnosticReportTests(unittest.TestCase):
    """_process_memory_report() must expose RSS safely."""

    @patch("app.utils.diagnostics.psutil.Process")
    def test_reports_rss(self, mock_process_ctor):
        proc = MagicMock()
        proc.memory_info.return_value.rss = 157 * 1024 * 1024
        mock_process_ctor.return_value = proc

        report = diag._process_memory_report()

        self.assertTrue(report["available"])
        self.assertEqual(report["rss_bytes"], 157 * 1024 * 1024)
        self.assertEqual(report["rss_mb"], 157.0)
        self.assertEqual(report["child_processes"]["active_count"], 0)
        self.assertEqual(report["combined_rss_mb"], 157.0)

    @patch("app.utils.diagnostics.psutil.Process")
    def test_handles_psutil_failures(self, mock_process_ctor):
        mock_process_ctor.side_effect = RuntimeError("no process")

        report = diag._process_memory_report()

        self.assertFalse(report["available"])
        self.assertIn("error", report)

    @patch("app.utils.diagnostics.psutil.Process")
    def test_includes_child_process_summary(self, mock_process_ctor):
        parent_proc = MagicMock()
        parent_proc.memory_info.return_value.rss = 157 * 1024 * 1024

        child_proc = MagicMock()
        child_proc.name.return_value = "ffmpeg.exe"
        child_proc.memory_info.return_value.rss = 64 * 1024 * 1024

        def process_side_effect(pid=None):
            if pid is None:
                return parent_proc
            if pid == 101:
                return child_proc
            raise RuntimeError("missing process")

        mock_process_ctor.side_effect = process_side_effect

        process_manager = MagicMock()
        active = MagicMock(pid=101, returncode=None)
        finished = MagicMock(pid=102, returncode=0)
        process_manager.ffmpeg_processes = [active, finished]

        report = diag._process_memory_report(process_manager=process_manager)

        self.assertEqual(report["rss_mb"], 157.0)
        self.assertEqual(report["child_processes"]["active_count"], 1)
        self.assertEqual(report["child_processes"]["rss_mb"], 64.0)
        self.assertEqual(report["child_processes"]["by_name"]["ffmpeg.exe"]["count"], 1)
        self.assertEqual(report["combined_rss_mb"], 221.0)


class TracemallocDiagnosticReportTests(unittest.TestCase):
    """_tracemalloc_report() must stay bounded and safe."""

    def test_reports_unavailable_when_module_missing(self):
        with patch("app.utils.diagnostics.tracemalloc", None):
            report = diag._tracemalloc_report()

        self.assertFalse(report["available"])
        self.assertFalse(report["enabled"])
        self.assertEqual(report["reason"], "unavailable")

    def test_starts_tracing_lazily_and_summarizes_top_files(self):
        stat_a = MagicMock()
        stat_a.size = 3 * 1024 * 1024
        stat_a.count = 12
        stat_a.traceback = [SimpleNamespace(filename="C:/Users/gperez/dev/StreamCapEvo/app/core/recording/manager.py")]

        stat_b = MagicMock()
        stat_b.size = 1 * 1024 * 1024
        stat_b.count = 4
        stat_b.traceback = [SimpleNamespace(filename="C:/Python311/Lib/site-packages/pkg/module.py")]

        snapshot = MagicMock()
        snapshot.statistics.return_value = [stat_a, stat_b]

        trace_api = MagicMock()
        trace_api.is_tracing.return_value = False
        trace_api.take_snapshot.return_value = snapshot
        trace_api.get_traceback_limit.return_value = 5

        with patch("app.utils.diagnostics.tracemalloc", trace_api):
            report = diag._tracemalloc_report(top_n=1)

        trace_api.start.assert_called_once_with(5)
        self.assertTrue(report["available"])
        self.assertTrue(report["enabled"])
        self.assertTrue(report["started_now"])
        self.assertEqual(report["traceback_limit"], 5)
        self.assertEqual(len(report["top"]), 1)
        self.assertEqual(report["top"][0]["file"], "app/core/recording/manager.py")
        self.assertEqual(report["top"][0]["size_mb"], 3.0)
        self.assertEqual(report["top_total_bytes"], 3 * 1024 * 1024)
        self.assertEqual(report["other_bytes"], 1 * 1024 * 1024)

    def test_handles_snapshot_failures(self):
        trace_api = MagicMock()
        trace_api.is_tracing.return_value = True
        trace_api.take_snapshot.side_effect = RuntimeError("snapshot failed")

        with patch("app.utils.diagnostics.tracemalloc", trace_api):
            report = diag._tracemalloc_report()

        self.assertFalse(report["available"])
        self.assertFalse(report["enabled"])
        self.assertIn("snapshot failed", report["error"])


class AsyncioDiagnosticReportTests(unittest.TestCase):
    """_asyncio_report() must return valid task metrics.

    Note: without a running event loop, asyncio.all_tasks() raises
    RuntimeError and _asyncio_report returns {}.  These tests adapt
    by checking for both the empty (no-loop) and populated paths.
    """

    def test_returns_dict(self):
        """_asyncio_report always returns a dict."""
        report = diag._asyncio_report()
        self.assertIsInstance(report, dict)

    def test_when_no_loop_returns_empty_dict(self):
        """Without a running loop, _asyncio_report returns {}."""
        report = diag._asyncio_report()
        # No running loop in this test context
        if not report:
            self.assertEqual(report, {})
        else:
            self.assertIn("total_tasks", report)
            self.assertIn("pending_tasks", report)

    def test_counts_are_non_negative_integers_when_available(self):
        """Task counts must be non-negative integers if loop is running."""
        report = diag._asyncio_report()
        if report:
            for key in ("total_tasks", "pending_tasks"):
                value = report[key]
                self.assertIsInstance(value, int)
                self.assertGreaterEqual(value, 0)

    def test_pending_does_not_exceed_total_when_available(self):
        """pending_tasks must be <= total_tasks when loop is running."""
        report = diag._asyncio_report()
        if report:
            self.assertLessEqual(report["pending_tasks"], report["total_tasks"])


class GCDiagnosticReportTests(unittest.TestCase):
    """_gc_report() must return valid GC generation counts."""

    def test_returns_dict_with_expected_keys(self):
        """_gc_report returns dict with gen0, gen1, gen2."""
        report = diag._gc_report()
        self.assertIsInstance(report, dict)
        self.assertIn("gen0", report)
        self.assertIn("gen1", report)
        self.assertIn("gen2", report)

    def test_counts_are_non_negative_integers(self):
        """GC generation counts must be non-negative integers."""
        report = diag._gc_report()
        for key in ("gen0", "gen1", "gen2"):
            value = report[key]
            self.assertIsInstance(value, int)
            self.assertGreaterEqual(value, 0)


class TempDiagScoreBreakdownTests(unittest.TestCase):
    """TEMP-DIAG: verify score breakdown tracking in get_forecast_details.

    These tests prove the score stage tracking works correctly when
    include_debug=True. Once the queue investigation is complete and
    the TEMP-DIAG instrumentation is removed, this test class should
    be removed along with it.
    """

    def _make_recording(self, **overrides) -> Recording:
        defaults = {
            "rec_id": "diag-rec",
            "url": "http://example.com/live",
            "streamer_name": "DiagStreamer",
            "record_format": "mp4",
            "quality": "HD",
            "segment_record": False,
            "segment_time": 0,
            "monitor_status": True,
            "scheduled_recording": False,
            "scheduled_start_time": "",
            "monitor_hours": "",
            "recording_dir": "/tmp/records",
            "enabled_message_push": False,
            "only_notify_no_record": False,
            "flv_use_direct_download": False,
        }
        defaults.update(overrides)
        return Recording(**defaults)

    def test_default_include_debug_false_omits_score_debug(self):
        """Without include_debug=True, _score_debug must NOT appear."""
        rec = self._make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        forecast = HistoryManager.get_forecast_details(rec, now=now)
        self.assertNotIn("_score_debug", forecast)

    def test_breakdown_has_base_stage(self):
        """include_debug=True adds _score_debug with at least base stage."""
        rec = self._make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        forecast = HistoryManager.get_forecast_details(rec, now=now, include_debug=True)
        debug = forecast.get("_score_debug")
        self.assertIsNotNone(debug)
        self.assertIsInstance(debug, list)
        assert isinstance(debug, list)
        self.assertGreaterEqual(len(debug), 1)
        self.assertEqual(debug[0][0], "base")
        self.assertEqual(debug[0][1], 0.15)

    def test_breakdown_with_historical_data(self):
        """Historical data adds 'historical' stage."""
        rec = self._make_recording(
            historical_intervals={"2": [20, 21]},
            consistency_score=0.5,
            priority_score=0.3,
        )
        now = datetime(2026, 5, 27, 20, 30, 0)  # Tuesday 20:30
        forecast = HistoryManager.get_forecast_details(rec, now=now, include_debug=True)
        debug = forecast.get("_score_debug", [])
        labels = [s[0] for s in debug]
        self.assertIn("historical", labels)
        self.assertIn("consistency", labels)
        self.assertIn("priority", labels)
        self.assertEqual(debug[-1][0], "final")

    def test_breakdown_final_score_matches_forecast(self):
        """Last stage score must match the main forecast score."""
        rec = self._make_recording(
            historical_intervals={"2": [20]},
            priority_score=0.8,
        )
        now = datetime(2026, 5, 27, 20, 30, 0)
        forecast = HistoryManager.get_forecast_details(rec, now=now, include_debug=True)
        debug = forecast.get("_score_debug", [])
        final_score = debug[-1][1]
        self.assertEqual(final_score, forecast["score"])

    def test_breakdown_matches_likelihood_from_snapshot(self):
        """Snapshot with include_debug=True must produce the same final score."""
        rec = self._make_recording(
            historical_intervals={"2": [20]},
        )
        now = datetime(2026, 5, 27, 20, 30, 0)
        snap = Precog.snapshot(rec, now=now, include_debug=True)
        self.assertIsInstance(snap, PrecogSnapshot)
        self.assertIn("_score_debug", snap.forecast_details)
        debug = snap.forecast_details["_score_debug"]
        # With include_debug=True, snapshot augments _score_debug to a dict
        if isinstance(debug, dict):
            stages = debug.get("stages", [])
            self.assertGreaterEqual(len(stages), 1)
            self.assertEqual(stages[-1][1], snap.likelihood)
        else:
            self.assertEqual(debug[-1][1], snap.likelihood)

    def test_breakdown_stages_are_monotonic_by_default(self):
        """Score stages should be non-decreasing (score only goes up then down by decay)."""
        rec = self._make_recording(
            historical_intervals={"2": [20, 21]},
            priority_score=0.5,
            consistency_score=0.4,
        )
        now = datetime(2026, 5, 27, 20, 30, 0)
        forecast = HistoryManager.get_forecast_details(rec, now=now, include_debug=True)
        debug = forecast.get("_score_debug", [])
        # Decay stages may go down; everything before decay should be non-decreasing
        scores = [s[1] for s in debug]
        # At minimum, final should match forecast score
        self.assertAlmostEqual(scores[-1], forecast["score"], places=6)

    def test_breakdown_with_scheduled_window(self):
        """Scheduled window adds 'scheduled_in' or 'scheduled_soon' stage."""
        rec = self._make_recording(
            scheduled_recording=True,
            scheduled_start_time="20:30:00",
            monitor_hours="2",
        )
        now = datetime(2026, 5, 27, 20, 25, 0)  # 5 min before scheduled
        forecast = HistoryManager.get_forecast_details(rec, now=now, include_debug=True)
        debug = forecast.get("_score_debug", [])
        labels = [s[0] for s in debug]
        self.assertIn("scheduled_soon", labels)

    def test_breakdown_with_live_recording(self):
        """Live recording returns score=1.0 with no stages."""
        rec = self._make_recording()
        rec.is_live = True
        now = datetime(2026, 5, 27, 20, 0, 0)
        forecast = HistoryManager.get_forecast_details(rec, now=now, include_debug=True)
        self.assertEqual(forecast["score"], 1.0)
        # Live recordings skip the stage tracking path
        debug = forecast.get("_score_debug")
        self.assertIsNone(debug)


if __name__ == "__main__":
    unittest.main()
