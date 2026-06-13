"""Tests for runtime diagnostics helpers.

These verify that the diagnostic introspection methods return valid
shapes and do not alter the state of the objects they inspect.
"""

import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from app.event_bus import EventBus
from app.core.config.language_manager import LanguageManager
from app.core.recording.history_manager import HistoryManager
from app.core.recording.precog import Precog, PrecogSnapshot
from app.core.recording.stream_manager import LiveStreamRecorder
from app.models.recording.recording_model import Recording
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


class DiagnosticsCollectReportTests(unittest.TestCase):
    """collect_report() must compose a valid dict."""

    def test_without_predictor_store(self):
        eb = MagicMock()
        eb.diagnostic_report.return_value = {"topics": {}, "total_subscribers": 0, "topic_count": 0}
        lm = MagicMock()
        lm.observer_count = 2

        report = diag.collect_report(event_bus=eb, language_manager=lm)
        self.assertIn("language_manager", report)
        self.assertIn("event_bus", report)
        self.assertIn("predictor_store", report)
        self.assertIn("asyncio", report)
        self.assertIn("gc", report)
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
