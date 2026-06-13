import unittest
from datetime import datetime
from unittest.mock import patch

from app.core.recording.history_manager import HistoryManager
from app.core.recording.precog import Precog, PrecogPrediction, PrecogSnapshot
from app.models.recording.recording_model import Recording


def _session(start_time_iso: str) -> dict:
    """Build a live_session dict for testing."""
    return {
        "start_time": start_time_iso,
        "end_time": None,
        "duration_minutes": None,
        "weekday": datetime.fromisoformat(start_time_iso).weekday(),
        "start_hour": datetime.fromisoformat(start_time_iso).hour,
    }


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
        direct_interval = HistoryManager.get_adjusted_interval(recording, 300, now=now)

        result = Precog.predict(recording, now=now)

        self.assertEqual(result.likelihood, direct_forecast["score"])
        self.assertEqual(result.confidence, direct_forecast["confidence"])
        self.assertEqual(result.forecast_details, direct_forecast)
        self.assertEqual(result.adjusted_interval, direct_interval)

    def test_predict_uses_recording_base_interval(self):
        recording = _make_recording()
        recording.loop_time_seconds = 180
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.predict(recording, now=now)

        # With no history, likelihood <= 0.15 → target = base * 1.5 = 270.
        # With 15% jitter, final interval is in [229, 310].
        self.assertGreaterEqual(result.adjusted_interval, 229)
        self.assertLessEqual(result.adjusted_interval, 310)

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
        direct_interval = HistoryManager.get_adjusted_interval(recording, 300, now=now)

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
        self.assertEqual(result["text"], "20:00-22:00")
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


class PrecogStableQueueKeyTests(unittest.TestCase):
    def test_stable_queue_key_uses_loop_time_seconds(self):
        """stable_queue_key must derive from loop_time_seconds directly."""
        recording = _make_recording()
        recording.loop_time_seconds = 180
        self.assertEqual(Precog.stable_queue_key(recording), "M")

    def test_stable_queue_key_fast_for_60(self):
        recording = _make_recording()
        recording.loop_time_seconds = 60
        self.assertEqual(Precog.stable_queue_key(recording), "F")

    def test_stable_queue_key_slow_for_300(self):
        recording = _make_recording()
        recording.loop_time_seconds = 300
        self.assertEqual(Precog.stable_queue_key(recording), "S")

    def test_stable_queue_key_defaults_to_60_when_none(self):
        """When loop_time_seconds is None, stable_queue_key must fall back to 60 (legacy UI default)."""
        recording = _make_recording()
        recording.loop_time_seconds = None
        self.assertEqual(Precog.stable_queue_key(recording), "F")

    def test_stable_queue_key_medium_for_120(self):
        recording = _make_recording()
        recording.loop_time_seconds = 120
        self.assertEqual(Precog.stable_queue_key(recording), "M")

    def test_stable_queue_key_boundary_61_is_medium(self):
        recording = _make_recording()
        recording.loop_time_seconds = 61
        self.assertEqual(Precog.stable_queue_key(recording), "M")

    def test_stable_queue_key_boundary_181_is_slow(self):
        recording = _make_recording()
        recording.loop_time_seconds = 181
        self.assertEqual(Precog.stable_queue_key(recording), "S")


class PrecogApplyFavoriteCapTests(unittest.TestCase):
    def test_caps_at_180_when_favorite_and_above(self):
        recording = _make_recording()
        recording.is_favorite = True
        self.assertEqual(Precog._apply_favorite_cap(200, recording), 180)

    def test_preserves_180_when_favorite(self):
        recording = _make_recording()
        recording.is_favorite = True
        self.assertEqual(Precog._apply_favorite_cap(180, recording), 180)

    def test_preserves_below_180_when_favorite(self):
        recording = _make_recording()
        recording.is_favorite = True
        self.assertEqual(Precog._apply_favorite_cap(60, recording), 60)

    def test_does_not_cap_when_not_favorite(self):
        recording = _make_recording()
        recording.is_favorite = False
        self.assertEqual(Precog._apply_favorite_cap(200, recording), 200)

    def test_uses_same_rule_as_snapshot_and_decide_queue(self):
        """Prove that snapshot and decide_queue both delegate to the same helper."""
        recording = _make_recording()
        recording.is_favorite = True
        recording.loop_time_seconds = 300
        now = datetime(2026, 5, 27, 20, 0, 0)
        with patch("app.core.recording.history_manager.random.randint", return_value=200):
            snap = Precog.snapshot(recording, now=now)
            dec = Precog.decide_queue(recording, base_interval=300, now=now)
        snap_capped = snap.adjusted_interval
        dec_capped = dec.adjusted_interval
        helper_capped = Precog._apply_favorite_cap(200, recording)
        self.assertEqual(snap_capped, helper_capped)
        self.assertEqual(dec_capped, helper_capped)


class PrecogStableQueueKeyRegressionTests(unittest.TestCase):
    """Regression tests: stable_queue_key must NOT be affected by snapshot's adjusted_interval."""

    def test_stable_queue_key_unaffected_by_snapshot(self):
        """stable_queue_key must return base-based key even after snapshot computes adjusted."""
        recording = _make_recording()
        recording.loop_time_seconds = 300
        now = datetime(2026, 5, 27, 20, 0, 0)
        Precog.snapshot(recording, now=now)
        # recording.loop_time_seconds must NOT have been mutated to the adjusted value
        self.assertEqual(recording.loop_time_seconds, 300)
        self.assertEqual(Precog.stable_queue_key(recording), "S")

    def test_stable_queue_key_matches_base_not_snap_queue_key(self):
        """When snapshot queue_key differs from base, stable_queue_key must still return base."""
        recording = _make_recording()
        recording.loop_time_seconds = 300
        now = datetime(2026, 5, 27, 20, 0, 0)
        with patch("app.core.recording.history_manager.random.randint", return_value=60):
            snap = Precog.snapshot(recording, now=now)
        # snap may have queue_key "F" (if jitter pushed it low) but base is 300 → "S"
        self.assertEqual(Precog.stable_queue_key(recording), "S")


class PrecogSnapshotOptimizationTests(unittest.TestCase):
    def test_snapshot_does_not_delegate_to_predict_nor_decide_queue(self):
        """snapshot must not call predict() or decide_queue() — core values
        are computed directly to eliminate duplicated work."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        with patch.object(Precog, "predict") as mock_predict, \
             patch.object(Precog, "decide_queue") as mock_decide:
            snap = Precog.snapshot(recording, now=now)
            mock_predict.assert_not_called()
            mock_decide.assert_not_called()
        self.assertIsInstance(snap, PrecogSnapshot)
        self.assertGreaterEqual(snap.likelihood, 0.0)
        self.assertLessEqual(snap.likelihood, 1.0)

    def test_snapshot_calls_get_adjusted_interval_once(self):
        """Proves optimization: get_adjusted_interval called 1x (down from 2)."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        orig_ai = HistoryManager.get_adjusted_interval
        with patch.object(HistoryManager, "get_adjusted_interval", wraps=orig_ai) as mock_ai:
            snap = Precog.snapshot(recording, now=now)
            self.assertEqual(mock_ai.call_count, 1)
            self.assertIsInstance(snap, PrecogSnapshot)

    def test_snapshot_top_level_get_forecast_details_calls(self):
        """Proves optimization: 1 get_forecast_details call (no horizon recursion)."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        call_count = [0]
        original = HistoryManager.get_forecast_details

        def counting_side_effect(*args, **kwargs):
            call_count[0] += 1
            return original(*args, **kwargs)

        with patch.object(HistoryManager, "get_forecast_details", side_effect=counting_side_effect):
            snap = Precog.snapshot(recording, now=now)
            self.assertEqual(call_count[0], 1)
            self.assertIsInstance(snap, PrecogSnapshot)

    def test_snapshot_horizons_off_by_default(self):
        """Default snapshot does NOT compute horizon forecasts."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        snap = Precog.snapshot(recording, now=now)
        self.assertEqual(snap.forecast_details.get("horizons", None), {})

    def test_snapshot_horizons_on_when_requested(self):
        """include_horizons=True computes horizon forecasts."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        snap = Precog.snapshot(recording, now=now, include_horizons=True)
        horizons = snap.forecast_details.get("horizons", None)
        self.assertIsNotNone(horizons)
        self.assertIn(15, horizons)
        self.assertIn(30, horizons)
        self.assertIn(60, horizons)

    def test_snapshot_internal_consistency(self):
        """All fields derived from forecast come from the same single call."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)
        snap = Precog.snapshot(recording, now=now)
        self.assertEqual(snap.likelihood, snap.forecast_details["score"])
        self.assertEqual(snap.confidence, snap.forecast_details["confidence"])
        self.assertEqual(snap.reason_key, snap.forecast_details.get("reason_key", ""))


class PrecogTemporalConsistencyTests(unittest.TestCase):
    """Verify that `now` propagates all the way through to get_adjusted_interval.

    Before the fix, Precoq methods ignored `now` when calling get_adjusted_interval,
    which always used datetime.now() internally.  These tests prove the chain is
    complete: now → get_adjusted_interval → get_likelihood_score → get_forecast_details.
    """

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_predict_adjusted_interval_matches_direct_with_same_now(self, _mock_rand):
        """Precog.predict(now=X) must produce same adjusted_interval as direct call with same now=X."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.predict(recording, now=now)
        direct = HistoryManager.get_adjusted_interval(recording, 300, now=now)

        self.assertEqual(result.adjusted_interval, direct)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_snapshot_adjusted_interval_matches_direct_with_same_now(self, _mock_rand):
        """Precog.snapshot(now=X) must produce same adjusted_interval as direct call with same now=X."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        snap = Precog.snapshot(recording, now=now)
        direct = HistoryManager.get_adjusted_interval(recording, 300, now=now)

        self.assertEqual(snap.adjusted_interval, direct)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_decide_queue_adjusted_interval_matches_direct_with_same_now(self, _mock_rand):
        """Precog.decide_queue(now=X) must produce same adjusted_interval as direct call with same now=X."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        decision = Precog.decide_queue(recording, base_interval=300, now=now)
        direct = HistoryManager.get_adjusted_interval(recording, 300, now=now)

        self.assertEqual(decision.adjusted_interval, direct)

    def test_different_now_produces_different_likelihood(self):
        """Different `now` values must produce different likelihoods when temporal
        context (day of week, hour) affects the forecast score."""
        recording = _make_recording(
            historical_intervals={"2": [20]},  # Wednesday 20:00
        )

        # During active hours (Wednesday 20:30) — higher likelihood
        active_now = datetime(2026, 5, 27, 20, 30, 0)   # Wednesday 20:30
        # Outside active hours — lower likelihood
        off_now = datetime(2026, 5, 27, 10, 0, 0)       # Wednesday 10:00

        with patch("app.core.recording.history_manager.random.randint", return_value=150):
            result_active = Precog.predict(recording, now=active_now)
            result_off = Precog.predict(recording, now=off_now)
            direct_active = HistoryManager.get_adjusted_interval(recording, 300, now=active_now)
            direct_off = HistoryManager.get_adjusted_interval(recording, 300, now=off_now)

        # Likelihood must reflect temporal context
        self.assertGreater(result_active.likelihood, result_off.likelihood,
                          "Likelihood should be higher during active window")
        # Adjusted interval must reflect the chain: now → likelihood → interval
        self.assertEqual(result_active.adjusted_interval, direct_active,
                         "now must propagate through predict → get_adjusted_interval")
        self.assertEqual(result_off.adjusted_interval, direct_off,
                         "now must propagate through predict → get_adjusted_interval")

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_backward_compat_no_now(self, _mock_rand):
        """Calling predict/snapshot/decide_queue without now must not crash (backward compat)."""
        recording = _make_recording()

        pred = Precog.predict(recording)
        self.assertIsInstance(pred, PrecogPrediction)

        snap = Precog.snapshot(recording)
        self.assertIsInstance(snap, PrecogSnapshot)

        dec = Precog.decide_queue(recording)
        self.assertGreaterEqual(dec.likelihood, 0.0)


class PrecogForecastTests(unittest.TestCase):
    def test_forecast_matches_predict_details(self):
        """Precog.forecast() must return the same dict as Precog.predict().forecast_details."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        forecast = Precog.forecast(recording, now=now)
        pred_details = Precog.predict(recording, now=now).forecast_details

        self.assertEqual(forecast, pred_details)

    def test_forecast_has_ui_keys(self):
        """Ensure forecast() returns the keys consumed by recording_info_dialog."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        result = Precog.forecast(recording, now=now)

        self.assertIn("next_slot_text", result)
        self.assertIn("window_text", result)
        self.assertIn("score", result)
        self.assertIn("confidence", result)

    def test_forecast_lighter_than_predict(self):
        """forecast() must not call get_adjusted_interval — it's the lightweight path."""
        recording = _make_recording()
        now = datetime(2026, 5, 27, 20, 0, 0)

        with patch.object(
            HistoryManager, "get_adjusted_interval"
        ) as mock_ai:
            Precog.forecast(recording, now=now)
            mock_ai.assert_not_called()


class WindowStateClassificationTests(unittest.TestCase):
    """Verify _classify_window returns correct (state, confidence) for each scenario."""

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)  # Wednesday 20:00

    def test_live_is_inside_high(self):
        """Live streamer → inside, high confidence."""
        rec = _make_recording()
        rec.is_live = True
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "inside")
        self.assertEqual(conf, "high")

    def test_scheduled_window_inside_is_inside_high(self):
        """Inside a scheduled window → inside, high confidence."""
        rec = _make_recording(
            scheduled_recording=True,
            scheduled_start_time="19:30:00",
            monitor_hours="2",
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "inside")
        self.assertEqual(conf, "high")

    def test_scheduled_window_approaching_is_approaching_high(self):
        """30 min before scheduled window → approaching, high confidence."""
        rec = _make_recording(
            scheduled_recording=True,
            scheduled_start_time="20:30:00",
            monitor_hours="2",
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "approaching")
        self.assertEqual(conf, "high")

    def test_historical_inside_with_consistency_gives_medium_conf(self):
        """Inside historical window with moderate consistency → inside, medium."""
        rec = _make_recording(
            historical_intervals={"2": [20, 21]},  # Wednesday 20-21
            consistency_score=0.5,
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "inside")
        # conf_val = 0.5*0.6 + (1/3)*0.4 = 0.30 + 0.13 = 0.43 → medium
        self.assertEqual(conf, "medium")

    def test_historical_inside_low_consistency_gives_low_conf(self):
        """Inside historical window with weak consistency → inside, low."""
        rec = _make_recording(
            historical_intervals={"2": [20]},  # single day, single hour
            consistency_score=0.0,               # no pattern density
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "inside")
        # conf_val = 0.0*0.6 + (1/3)*0.4 = 0.13 → low
        self.assertEqual(conf, "low")

    def test_historical_approaching_with_high_conf_is_approaching_high(self):
        """Approaching historical window with strong data → approaching, high."""
        rec = _make_recording(
            historical_intervals={
                "2": [21],  # Wednesday 21:00 (60 min away)
                "1": [21], "0": [21],  # 3 days breadth
            },
            consistency_score=1.0,
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "approaching")
        # conf_val = 1.0*0.6 + (3/3)*0.4 = 0.6 + 0.4 = 1.0 → high
        self.assertEqual(conf, "high")

    def test_historical_approaching_low_conf_is_approaching_low(self):
        """Approaching historical with weak evidence → approaching, low."""
        rec = _make_recording(
            historical_intervals={"2": [21]},  # Wednesday 21:00, 1 day
            consistency_score=0.0,
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "approaching")
        self.assertEqual(conf, "low")

    def test_degrading_after_window_end(self):
        """15 min after window end → degrading."""
        rec = _make_recording(
            historical_intervals={"2": [20]},
            consistency_score=0.8,
        )
        # 21:15 — 15 min past window end (~20:59)
        after = datetime(2026, 5, 27, 21, 15, 0)
        state, conf = HistoryManager._classify_window(rec, after)
        self.assertEqual(state, "degrading")

    def test_outside_far_from_window(self):
        """Far from any window → outside, low."""
        rec = _make_recording()
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "outside")
        self.assertEqual(conf, "low")

    def test_outside_with_active_hours_but_no_proximity(self):
        """Has historical data but far from current time → outside."""
        rec = _make_recording(
            historical_intervals={"2": [8]},  # Wednesday 08:00, far from 20:00
            consistency_score=1.0,
        )
        state, conf = HistoryManager._classify_window(rec, self.now)
        self.assertEqual(state, "outside")


class WindowBasedQueueIntervalTests(unittest.TestCase):
    """Verify get_adjusted_interval produces correct targets based on window state.

    We mock randint to eliminate jitter for deterministic assertions.
    """

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)  # Wednesday 20:00
        self.base_interval = 300

    @patch("app.core.recording.history_manager.random.randint", return_value=60)
    def test_inside_high_conf_returns_fast(self, _mock_rand):
        """inside + high confidence → target 60s (F queue)."""
        rec = _make_recording(
            scheduled_recording=True,
            scheduled_start_time="19:30:00",
            monitor_hours="2",
        )
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=self.now)
        self.assertEqual(interval, 60)

    @patch("app.core.recording.history_manager.random.randint", return_value=60)
    def test_inside_medium_conf_returns_fast(self, _mock_rand):
        """inside + medium confidence → target 60s (F queue)."""
        rec = _make_recording(
            historical_intervals={"2": [20, 21]},
            consistency_score=0.5,
        )
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=self.now)
        self.assertEqual(interval, 60)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_inside_low_conf_returns_medium(self, _mock_rand):
        """inside + low confidence → target 150s (M queue)."""
        rec = _make_recording(
            historical_intervals={"2": [20]},
            consistency_score=0.0,
        )
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=self.now)
        self.assertEqual(interval, 150)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_approaching_high_conf_returns_medium(self, _mock_rand):
        """approaching + high confidence → target 150s (M queue)."""
        rec = _make_recording(
            scheduled_recording=True,
            scheduled_start_time="20:30:00",
            monitor_hours="2",
        )
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=self.now)
        self.assertEqual(interval, 150)

    @patch("app.core.recording.history_manager.random.randint", return_value=300)
    def test_approaching_low_conf_returns_slow(self, _mock_rand):
        """approaching + low confidence → target base_interval (S queue)."""
        rec = _make_recording(
            historical_intervals={"2": [21]},
            consistency_score=0.0,
        )
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=self.now)
        # base_interval = 300 → S (since > 180)
        self.assertGreater(interval, 180)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_degrading_returns_medium(self, _mock_rand):
        """degrading → target 150s (M queue) — gradual degrade."""
        rec = _make_recording(
            historical_intervals={"2": [20]},
        )
        after = datetime(2026, 5, 27, 21, 15, 0)
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=after)
        self.assertEqual(interval, 150)

    @patch("app.core.recording.history_manager.random.randint", return_value=450)
    def test_outside_returns_slow(self, _mock_rand):
        """outside → target base*1.5 (S queue)."""
        rec = _make_recording()
        interval = HistoryManager.get_adjusted_interval(rec, self.base_interval, now=self.now)
        # base*1.5 = 450 → S
        self.assertGreater(interval, 180)


class SparseEvidenceQueueRegressionTests(unittest.TestCase):
    """REGRESSION: isolated streams with sparse evidence must NOT reach medium queue.

    This is the core behavioral fix: additive boosts no longer inflate queue
    assignment outside trustworthy windows.
    """

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)

    @patch("app.core.recording.history_manager.random.randint", return_value=450)
    def test_sparse_sessions_no_window_returns_slow(self, _mock_rand):
        """One session at wrong time, no historical_intervals → outside → S."""
        rec = _make_recording(
            live_sessions=[_session("2026-05-20T10:00:00")],
            historical_intervals={},
            consistency_score=0.0,
        )
        interval = HistoryManager.get_adjusted_interval(rec, 300, now=self.now)
        self.assertGreater(interval, 180, f"Interval {interval} should be S (>180)")

    @patch("app.core.recording.history_manager.random.randint", return_value=450)
    def test_session_conf_does_not_inflate_outside(self, _mock_rand):
        """Even with session data and consistency, outside window → S queue."""
        rec = _make_recording(
            live_sessions=[_session(f"2026-05-{10+i:02d}T10:00:00") for i in range(8)],
            historical_intervals={},  # no hist_intervals → outside
            consistency_score=1.0,
            priority_score=0.8,
        )
        interval = HistoryManager.get_adjusted_interval(rec, 300, now=self.now)
        self.assertGreater(interval, 180, f"Interval {interval} should be S (>180)")

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_weak_historical_window_stays_cautious(self, _mock_rand):
        """1-day historical with low consistency → inside+low → M (not F)."""
        rec = _make_recording(
            historical_intervals={"2": [20]},
            consistency_score=0.0,
        )
        interval = HistoryManager.get_adjusted_interval(rec, 300, now=self.now)
        # inside + low → 150 → M (NOT F = 60)
        self.assertEqual(interval, 150)

    @patch("app.core.recording.history_manager.random.randint", return_value=150)
    def test_snapshot_window_fields_populated(self, _mock_rand):
        """Precog.snapshot() must include window_state and window_confidence."""
        rec = _make_recording(
            historical_intervals={"2": [20]},
            consistency_score=0.5,
        )
        snap = Precog.snapshot(rec, now=self.now)
        self.assertEqual(snap.window_state, "inside")
        self.assertEqual(snap.window_confidence, "medium")

    def test_snapshot_outside_defaults(self):
        """Streamer with no data → snapshot has outside+low window fields."""
        rec = _make_recording()
        snap = Precog.snapshot(rec, now=self.now)
        self.assertEqual(snap.window_state, "outside")
        self.assertEqual(snap.window_confidence, "low")


if __name__ == "__main__":
    unittest.main()
