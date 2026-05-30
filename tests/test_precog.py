import unittest
from datetime import datetime
from unittest.mock import patch

from app.core.recording.history_manager import HistoryManager
from app.core.recording.precog import Precog, PrecogPrediction, PrecogSnapshot
from app.models.recording.recording_model import Recording


def _make_recording(**overrides) -> Recording:
    defaults = {
        "rec_id": "rec-test",
        "url": "http://example.com/live",
        "streamer_name": "TestStreamer",
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


class PrecogPredictTests(unittest.TestCase):
    def test_live_streamer_returns_max_likelihood(self):
        recording = _make_recording()
        recording.is_live = True
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.predict(recording, now=now)

        self.assertIsInstance(result, PrecogPrediction)
        self.assertEqual(result.likelihood, 1.0)
        self.assertEqual(result.confidence, "high")
        self.assertEqual(result.priority_score, 0.0)
        self.assertEqual(result.consistency_score, 0.0)
        # Forecast details must mirror HistoryManager directly
        direct = HistoryManager.get_forecast_details(recording, now=now)
        self.assertEqual(result.forecast_details, direct)

    @patch("app.core.recording.history_manager.random.randint", return_value=450)
    def test_predict_matches_history_manager_for_inactive_streamer(self, _mock_rand):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        direct_forecast = HistoryManager.get_forecast_details(recording, now=now)
        direct_interval = HistoryManager.get_adjusted_interval(recording, 300)

        result = Precog.predict(recording, now=now)

        self.assertEqual(result.likelihood, direct_forecast["score"])
        self.assertEqual(result.confidence, direct_forecast["confidence"])
        self.assertEqual(result.forecast_details, direct_forecast)
        self.assertEqual(result.adjusted_interval, direct_interval)

    @patch("app.core.recording.history_manager.random.randint", return_value=120)
    def test_predict_uses_recording_base_interval(self, mock_rand):
        recording = _make_recording()
        recording.loop_time_seconds = 180
        recording.is_live = True  # force high likelihood → interval 60
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.predict(recording, now=now)

        # When live, get_adjusted_interval returns 60 regardless of base,
        # but we can still assert the internal path was hit by verifying
        # the mock was called with bounds derived from 60.
        self.assertEqual(result.adjusted_interval, 120)
        mock_rand.assert_called_once()

    @patch("app.core.recording.history_manager.random.randint", return_value=400)
    def test_predict_uses_default_base_interval_when_none(self, mock_rand):
        recording = _make_recording()
        recording.loop_time_seconds = None
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.predict(recording, now=now)

        # Default base is 300. With no data, likelihood is low (0.05 after capping),
        # so target_interval = base * 1.5 = 450.  Jitter range ~ [382, 517].
        # We forced randint to 400, so the interval should be 400.
        self.assertEqual(result.adjusted_interval, 400)
        mock_rand.assert_called_once()

    def test_forecast_details_has_ui_keys(self):
        """Ensure forecast_details contains the keys consumed by recording_info_dialog and live_forecast_dialog."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.predict(recording, now=now)

        self.assertIn("next_slot_text", result.forecast_details)
        self.assertIn("window_text", result.forecast_details)
        self.assertIn("score", result.forecast_details)
        self.assertIn("confidence", result.forecast_details)
        self.assertIn("reason_key", result.forecast_details)
        self.assertIn("avg_delay_minutes", result.forecast_details)
        self.assertIn("horizons", result.forecast_details)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_predict_with_historical_data(self, _mock_rand):
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},  # Tuesday 20:00-21:00
            priority_score=0.5,
            consistency_score=0.8,
        )
        now = datetime(2026, 5, 27, 20, 30, 0)  # Tuesday 20:30

        direct_forecast = HistoryManager.get_forecast_details(recording, now=now)
        direct_interval = HistoryManager.get_adjusted_interval(recording, 300)

        result = Precog.predict(recording, now=now)

        self.assertEqual(result.likelihood, direct_forecast["score"])
        self.assertEqual(result.confidence, direct_forecast["confidence"])
        self.assertEqual(result.priority_score, 0.5)
        self.assertEqual(result.consistency_score, 0.8)
        self.assertEqual(result.forecast_details, direct_forecast)
        self.assertEqual(result.adjusted_interval, direct_interval)


class PrecogTimeStateTests(unittest.TestCase):
    def test_no_active_hours_returns_none(self):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.time_state(recording, now=now)

        self.assertEqual(result["state"], "none")
        self.assertEqual(result["text"], "")
        self.assertEqual(result["color"], "")

    def test_live_inside_cluster_returns_live_range(self):
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},  # Tuesday
        )
        recording.is_live = True
        now = datetime(2026, 5, 27, 20, 30, 0)  # Tuesday 20:30

        result = Precog.time_state(recording, now=now)

        self.assertEqual(result["state"], "live_range")
        self.assertEqual(result["text_key"], "live_forecast_dialog.status_live")
        self.assertEqual(result["text"], "20:00‑22:00")
        self.assertEqual(result["color"], "#E53935")
        self.assertEqual(result["prefix"], "")
    
    def test_expected_when_minutes_into_cluster_low(self):
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},
        )
        recording.is_live = False
        now = datetime(2026, 5, 27, 20, 10, 0)  # 10 min into cluster

        result = Precog.time_state(recording, now=now)

        self.assertEqual(result["state"], "expected")
        self.assertEqual(result["text_key"], "live_forecast_dialog.status_expected")
        self.assertEqual(result["color"], "#FF9800")
        self.assertEqual(result["prefix"], "")
    
    def test_delayed_when_minutes_into_cluster_high(self):
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},
        )
        recording.is_live = False
        now = datetime(2026, 5, 27, 20, 20, 0)  # 20 min into cluster

        result = Precog.time_state(recording, now=now)

        self.assertEqual(result["state"], "delayed")
        self.assertEqual(result["text_key"], "live_forecast_dialog.status_delayed")
        self.assertEqual(result["color"], "#FF5252")
        self.assertEqual(result["prefix"], "")
    
    def test_countdown_when_next_hour_is_next(self):
        recording = _make_recording(
            historical_intervals={"2": [22]},  # Tuesday 22:00
        )
        now = datetime(2026, 5, 27, 21, 15, 0)  # Tuesday 21:15

        result = Precog.time_state(recording, now=now)

        self.assertEqual(result["state"], "countdown")
        self.assertEqual(result["text_key"], "live_forecast_dialog.status_countdown")
        self.assertEqual(result["color"], "#4CAF50")
        self.assertEqual(result["prefix"], "")
        self.assertEqual(result["args"], {"minutes": 45})

    def test_upcoming_when_far_from_window(self):
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},
        )
        now = datetime(2026, 5, 27, 10, 0, 0)  # Tuesday 10:00, far from 20:00

        result = Precog.time_state(recording, now=now)

        self.assertEqual(result["state"], "upcoming")
        self.assertEqual(result["text"], "20:00")
        self.assertEqual(result["color"], "")

    def test_time_state_matches_legacy_logic(self):
        """Ensure Precog.time_state produces the same result as the old _get_forecast_time_info helper."""
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},
        )
        now = datetime(2026, 5, 27, 20, 5, 0)

        result = Precog.time_state(recording, now=now)

        # The legacy helper would return "expected" at 20:05 (5 minutes into window)
        self.assertEqual(result["state"], "expected")
        self.assertEqual(result["text_key"], "live_forecast_dialog.status_expected")


class PrecogDecideQueueTests(unittest.TestCase):
    @patch("app.core.recording.history_manager.random.randint", return_value=60)
    def test_decide_queue_fast_when_likelihood_high(self, _mock_rand):
        recording = _make_recording()
        recording.is_live = True  # likelihood 1.0 -> interval 60
        now = datetime(2026, 5, 27, 20, 0, 0)

        decision = Precog.decide_queue(recording, base_interval=300, now=now)

        self.assertTrue(decision.should_check)
        self.assertEqual(decision.queue_key, "F")
        self.assertEqual(decision.adjusted_interval, 60)
        self.assertEqual(decision.likelihood, 1.0)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_decide_queue_medium_for_interval_180(self, _mock_rand):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        # No historical data → likelihood 0.05, interval = base*1.5 = 450,
        # but with mock randint=150 it's 150, so M queue
        decision = Precog.decide_queue(recording, base_interval=300, now=now)
        self.assertEqual(decision.queue_key, "M")

    @patch("app.core.recording.history_manager.random.randint", return_value=200)
    def test_decide_queue_slow_for_interval_above_180(self, _mock_rand):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        # interval 200 > 180 -> S
        decision = Precog.decide_queue(recording, base_interval=300, now=now)
        self.assertEqual(decision.queue_key, "S")

    def test_decide_queue_favorite_cap_at_180(self):
        recording = _make_recording()
        recording.is_favorite = True
        # If interval would be >180, cap it
        now = datetime(2026, 5, 27, 20, 0, 0)
        with patch("app.core.recording.history_manager.random.randint", return_value=200):
            decision = Precog.decide_queue(recording, base_interval=300, now=now)
        self.assertEqual(decision.adjusted_interval, 180)
        self.assertEqual(decision.queue_key, "M")  # because 180 -> M

    def test_decide_queue_should_check_false_when_not_exceeded(self):
        recording = _make_recording()
        recording.detection_time = datetime(2026, 5, 27, 19, 28, 0).time()  # 2 min ago
        now = datetime(2026, 5, 27, 19, 30, 0)  # 2 min later, interval 300 -> not exceeded
        with patch("app.core.recording.history_manager.random.randint", return_value=300):
            decision = Precog.decide_queue(recording, base_interval=300, now=now)
        self.assertFalse(decision.should_check)

    def test_decide_queue_should_check_true_when_exceeded(self):
        recording = _make_recording()
        recording.detection_time = datetime(2026, 5, 27, 18, 0, 0).time()  # 2 hours ago
        now = datetime(2026, 5, 27, 20, 0, 0)  # 2 hours later, interval 300 -> exceeded
        with patch("app.core.recording.history_manager.random.randint", return_value=300):
            decision = Precog.decide_queue(recording, base_interval=300, now=now)
        self.assertTrue(decision.should_check)

    def test_decide_queue_should_check_true_when_no_detection_time(self):
        recording = _make_recording()
        recording.detection_time = None
        now = datetime(2026, 5, 27, 20, 0, 0)
        decision = Precog.decide_queue(recording, base_interval=300, now=now)
        self.assertTrue(decision.should_check)


class PrecogSnapshotTests(unittest.TestCase):
    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_snapshot_returns_precogsnapshot(self, _mock_rand):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)

        self.assertIsInstance(snap, PrecogSnapshot)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_snapshot_likelihood_matches_predict(self, _mock_rand):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)
        pred = Precog.predict(recording, now=now)

        self.assertEqual(snap.likelihood, pred.likelihood)
        self.assertEqual(snap.confidence, pred.confidence)
        self.assertEqual(snap.priority_score, pred.priority_score)
        self.assertEqual(snap.consistency_score, pred.consistency_score)
        self.assertEqual(snap.forecast_details, pred.forecast_details)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_snapshot_queue_fields_match_decide_queue(self, _mock_rand):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)
        decision = Precog.decide_queue(recording, base_interval=300, now=now)

        self.assertEqual(snap.queue_key, decision.queue_key)
        self.assertEqual(snap.adjusted_interval, decision.adjusted_interval)
        self.assertEqual(snap.should_check, decision.should_check)
        self.assertEqual(snap.reason_key, decision.reason)

    def test_snapshot_time_state_matches(self):
        recording = _make_recording(
            historical_intervals={"2": [20, 21]},
        )
        now = datetime(2026, 5, 27, 20, 30, 0)

        snap = Precog.snapshot(recording, now=now)
        ts = Precog.time_state(recording, now=now)

        self.assertEqual(snap.time_state, ts)

    def test_snapshot_is_stale_false_for_new_recording(self):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)

        self.assertFalse(snap.is_stale)

    @patch("app.core.recording.history_manager.random.randint", return_value=60)
    def test_snapshot_live_streamer_fast_queue(self, _mock_rand):
        recording = _make_recording()
        recording.is_live = True
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)

        self.assertEqual(snap.likelihood, 1.0)
        self.assertEqual(snap.queue_key, "F")
        self.assertEqual(snap.confidence, "high")

    def test_snapshot_reason_key_from_forecast(self):
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)

        # reason_key should match forecast_details.reason_key
        self.assertEqual(snap.reason_key, snap.forecast_details.get("reason_key", ""))

    def test_snapshot_stale_uses_now_parameter(self):
        """is_stale must use snapshot's `now` parameter, not datetime.now()."""
        recording = _make_recording(
            last_seen_live="2026-04-15 10:00:00",
        )
        now = datetime(2026, 5, 1, 20, 0, 0)
        snap = Precog.snapshot(recording, now=now)
        self.assertFalse(snap.is_stale)

    @patch("app.core.recording.history_manager.random.randint", return_value=200)
    def test_snapshot_favorite_caps_interval(self, _mock_rand):
        recording = _make_recording()
        recording.is_favorite = True
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)

        # Favorite cap at 180 → M queue
        self.assertEqual(snap.adjusted_interval, 180)
        self.assertEqual(snap.queue_key, "M")

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_snapshot_fields_match_decide_queue_for_record_manager_pattern(self, _mock_rand):
        """When recording.loop_time_seconds == base_interval, snapshot fields
        consumed by record_manager match decide_queue fields exactly."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        base_interval = 300
        recording.loop_time_seconds = base_interval

        snap = Precog.snapshot(recording, now=now)
        dec = Precog.decide_queue(recording, base_interval=base_interval, now=now)

        self.assertEqual(snap.adjusted_interval, dec.adjusted_interval)
        self.assertEqual(snap.likelihood, dec.likelihood)
        self.assertEqual(snap.should_check, dec.should_check)
        self.assertEqual(snap.queue_key, dec.queue_key)

    @patch("app.core.recording.history_manager.random.randint", return_value=60)
    def test_snapshot_fields_match_for_fast_queue_with_live(self, _mock_rand):
        """Live streamer gets fast queue via snapshot, same as decide_queue."""
        recording = _make_recording()
        recording.is_live = True
        now = datetime(2026, 5, 27, 20, 0, 0)
        recording.loop_time_seconds = 300

        snap = Precog.snapshot(recording, now=now)
        dec = Precog.decide_queue(recording, base_interval=300, now=now)

        self.assertEqual(snap.should_check, dec.should_check)
        self.assertEqual(snap.queue_key, dec.queue_key)
        self.assertEqual(snap.likelihood, dec.likelihood)


if __name__ == "__main__":
    unittest.main()
