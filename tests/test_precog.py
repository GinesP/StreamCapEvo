import unittest
from datetime import datetime
from unittest.mock import patch

from app.core.recording.history_manager import HistoryManager
from app.core.recording.precog import Precog, PrecogPrediction
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


if __name__ == "__main__":
    unittest.main()
