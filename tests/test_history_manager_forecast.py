"""Tests for HistoryManager likelihood forecasting, focusing on evidence-weighted
boosts that prevent weak sample sizes from inflating scores into the medium queue.

Covers:
- _session_stats evidence_weight computation
- confidence_boost suppression under sparse sessions
- consistency_score gating by historical interval breadth
- Full integration: weak evidence should not cross 0.5
- Regression: strong evidence still gets full boosts
"""

import unittest
from datetime import datetime

from app.core.recording.history_manager import HistoryManager
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


def _session(start_time_iso: str) -> dict:
    """Build a live_session dict for testing."""
    return {
        "start_time": start_time_iso,
        "end_time": None,
        "duration_minutes": None,
        "weekday": datetime.fromisoformat(start_time_iso).weekday(),
        "start_hour": datetime.fromisoformat(start_time_iso).hour,
    }


def _consistency_delta(debug_stages: list) -> float:
    """Compute the effective consistency contribution from TEMP-DIAG debug stages.

    Finds the 'consistency' stage and returns its delta from the previous stage.
    Handles cases where 'session_conf' may be absent (no live sessions).
    """
    stage_names = [s[0] for s in debug_stages]
    consistency_idx = stage_names.index("consistency")
    if consistency_idx == 0:
        return debug_stages[0][1]  # unlikely but be safe
    return debug_stages[consistency_idx][1] - debug_stages[consistency_idx - 1][1]


class EvidenceWeightTests(unittest.TestCase):
    """Verify _session_stats returns correct evidence_weight."""

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)  # Wednesday 20:00

    def test_no_sessions_gives_zero_weight(self):
        rec = _make_recording(live_sessions=[])
        stats = HistoryManager._session_stats(rec, self.now)
        self.assertEqual(stats["evidence_weight"], 0.0)

    def test_one_session_gives_low_weight(self):
        rec = _make_recording(live_sessions=[
            _session("2026-05-20T20:00:00"),  # 7 days ago, same time
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        # 1 / 8 = 0.125
        self.assertAlmostEqual(stats["evidence_weight"], 0.125, places=4)
        self.assertLess(stats["evidence_weight"], 0.3)

    def test_three_sessions_gives_moderate_weight(self):
        rec = _make_recording(live_sessions=[
            _session("2026-05-20T20:00:00"),
            _session("2026-05-21T20:00:00"),
            _session("2026-05-22T20:00:00"),
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        # 3 / 8 = 0.375
        self.assertAlmostEqual(stats["evidence_weight"], 0.375, places=4)

    def test_eight_sessions_gives_full_weight(self):
        rec = _make_recording(live_sessions=[
            _session(f"2026-05-{13 + i:02d}T20:00:00") for i in range(8)
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        self.assertEqual(stats["evidence_weight"], 1.0)

    def test_twelve_sessions_stays_full_weight(self):
        rec = _make_recording(live_sessions=[
            _session(f"2026-05-{10 + i:02d}T20:00:00") for i in range(12)
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        self.assertEqual(stats["evidence_weight"], 1.0)


class ConfidenceBoostSuppressionTests(unittest.TestCase):
    """Verify confidence_boost is suppressed when session evidence is weak."""

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)

    def test_one_session_boost_is_tiny(self):
        """One session should contribute almost nothing to confidence_boost."""
        rec = _make_recording(live_sessions=[
            _session("2026-05-20T20:00:00"),
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        # 1 * 0.015 = 0.015, weighted by 1/8 = 0.125 → 0.001875
        self.assertAlmostEqual(stats["confidence_boost"], 0.001875, places=6)
        self.assertLess(stats["confidence_boost"], 0.01)

    def test_two_sessions_boost_is_low(self):
        rec = _make_recording(live_sessions=[
            _session("2026-05-20T20:00:00"),
            _session("2026-05-21T20:00:00"),
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        # 2 * 0.015 = 0.03, weighted by 2/8 = 0.25 → 0.0075
        self.assertAlmostEqual(stats["confidence_boost"], 0.0075, places=4)

    def test_five_sessions_moderate_boost(self):
        rec = _make_recording(live_sessions=[
            _session(f"2026-05-{18 + i:02d}T20:00:00") for i in range(5)
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        # 5 * 0.015 = 0.075, weighted by 5/8 = 0.625 → 0.046875
        self.assertAlmostEqual(stats["confidence_boost"], 0.046875, places=4)

    def test_twelve_sessions_full_boost(self):
        """12+ sessions still get full confidence_boost (0.18)."""
        rec = _make_recording(live_sessions=[
            _session(f"2026-05-{10 + i:02d}T20:00:00") for i in range(12)
        ])
        stats = HistoryManager._session_stats(rec, self.now)
        self.assertEqual(stats["confidence_boost"], 0.18)


class ConsistencyGatingTests(unittest.TestCase):
    """Verify consistency_score contribution is gated by evidence breadth."""

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)

    def _get_consistency_delta(self, historical_intervals: dict,
                               consistency_score: float = 1.0) -> float:
        """Compute the effective consistency contribution from debug stages."""
        rec = _make_recording(
            historical_intervals=historical_intervals,
            consistency_score=consistency_score,
        )
        debug = HistoryManager.get_forecast_details(
            rec, now=self.now, include_horizons=False, include_debug=True
        )
        return _consistency_delta(debug["_score_debug"])

    def test_no_historical_data_gives_zero_consistency(self):
        """Empty historical_intervals → no consistency contribution."""
        delta = self._get_consistency_delta({})
        self.assertAlmostEqual(delta, 0.0, places=6)

    def test_one_day_gates_consistency_heavily(self):
        """1 day of historical_intervals → consistency_weight = 0.2."""
        delta = self._get_consistency_delta({"2": [20]})
        # Full would be 0.12, gated by 1/5 = 0.2 → 0.024
        self.assertAlmostEqual(delta, 0.024, places=4)

    def test_three_days_moderate_gate(self):
        """3 days of historical_intervals → consistency_weight = 0.6."""
        delta = self._get_consistency_delta(
            {"0": [20], "1": [20], "2": [20]}
        )
        # Full would be 0.12, gated by 3/5 = 0.6 → 0.072
        self.assertAlmostEqual(delta, 0.072, places=4)

    def test_five_days_full_consistency(self):
        """5+ days → consistency_weight = 1.0, contribution at full."""
        delta = self._get_consistency_delta(
            {"0": [20], "1": [20], "2": [20], "3": [20], "4": [20]}
        )
        # Full contribution = min(0.12, 1.0 * 0.12) = 0.12
        self.assertAlmostEqual(delta, 0.12, places=4)

    def test_partial_consistency_score_gated_correctly(self):
        """consistency_score of 0.5 * full weight 0.12 * weight 0.6 = 0.036."""
        delta = self._get_consistency_delta(
            {"0": [20], "1": [20], "2": [20]},
            consistency_score=0.5,
        )
        # min(0.12, 0.5 * 0.12) = 0.06, gated by 3/5 = 0.6 → 0.036
        self.assertAlmostEqual(delta, 0.036, places=4)


class WeakEvidenceIntegrationTests(unittest.TestCase):
    """Full integration: weak evidence should not inflate into medium queue."""

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)  # Wednesday 20:00

    def test_single_session_weak_proximity_stays_below_medium(self):
        """One weak-proximity session must NOT push score over 0.45.

        Uses a session at a DIFFERENT time of day so session_score is low,
        then verifies the additive boosts (confidence_boost + consistency)
        do not push the combined score across the medium threshold.
        """
        rec = _make_recording(
            live_sessions=[
                _session("2026-05-20T10:00:00"),  # 10am ≠ 8pm → weak proximity
            ],
            consistency_score=0.0,
            historical_intervals={},
        )
        forecast = HistoryManager.get_forecast_details(rec, now=self.now)
        score = forecast["score"]
        # Session at different hour → low session_score.
        # Before fix: confidence_boost alone gave +0.015 (enough near 0.45).
        # After fix: confidence_boost ~0.0019, so score stays well below.
        self.assertLess(
            score, 0.40,
            f"Score {score:.3f} should stay well below medium with weak-proximity session"
        )

    def test_two_sessions_at_different_time_no_medium_inflation(self):
        """Two sessions at a different time should not inflate into medium.

        This is the pattern seen in production logs (e.g. sharitol017):
        weak proximity session_score + additive boosts that cross 0.5.
        """
        rec = _make_recording(
            live_sessions=[
                _session("2026-05-20T10:00:00"),  # 10am, different from 8pm
                _session("2026-05-21T10:00:00"),
            ],
            consistency_score=0.0,
            historical_intervals={},
        )
        forecast = HistoryManager.get_forecast_details(rec, now=self.now)
        score = forecast["score"]
        self.assertLess(
            score, 0.45,
            f"Score {score:.3f} should stay below medium with 2 weak-proximity sessions"
        )

    def test_three_sessions_scattered_no_hist_intervals_stays_low(self):
        """Three sessions scattered, no historical_intervals (so no historical
        path either), should stay well below medium.

        This isolates the confidence_boost + consistency contribution
        without interference from the historical signal.
        """
        rec = _make_recording(
            live_sessions=[
                _session("2026-05-20T10:00:00"),
                _session("2026-05-21T14:00:00"),
                _session("2026-05-22T18:00:00"),
            ],
            consistency_score=1.0,
            historical_intervals={},  # no hist path at all
        )
        forecast = HistoryManager.get_forecast_details(rec, now=self.now)
        score = forecast["score"]
        # Without historical_intervals, only session path contributes.
        # Session proximity is weak (none at 20:00), so session_score is tiny.
        # Before fix: confidence_boost +0.045 + consistency +0.12 = +0.165
        # After fix: boost 0.045*0.375=0.017 + consistency 0.12*0.0=0.0 → tiny
        self.assertLess(
            score, 0.30,
            f"Score {score:.3f} should be low with scattered data, no hist"
        )


class StrongEvidenceRegressionTests(unittest.TestCase):
    """Regression: strong evidence still produces normal results."""

    def setUp(self):
        self.now = datetime(2026, 5, 27, 20, 0, 0)

    def test_dozen_sessions_with_strong_proximity_gets_full_boost(self):
        """12+ sessions at matching time still get full confidence_boost."""
        rec = _make_recording(
            live_sessions=[
                _session(f"2026-05-{10 + i:02d}T20:00:00") for i in range(12)
            ],
            consistency_score=1.0,
            historical_intervals={
                "0": [20], "1": [20], "2": [20], "3": [20],
                "4": [20], "5": [20], "6": [20],
            },
        )
        forecast = HistoryManager.get_forecast_details(rec, now=self.now)
        score = forecast["score"]
        # With strong proximity + full confidence_boost + full consistency → high
        self.assertGreaterEqual(
            score, 0.75,
            f"Score {score:.3f} should be high (>=0.75) with abundant evidence"
        )
        self.assertEqual(forecast["confidence"], "high")

    def test_historical_window_match_is_unchanged(self):
        """The historical active_hours path is NOT affected by evidence gating."""
        rec = _make_recording(
            historical_intervals={"2": [20]},  # Wednesday 20:00
            live_sessions=[],                   # no live sessions
            consistency_score=0.0,
        )
        forecast = HistoryManager.get_forecast_details(rec, now=self.now)
        score = forecast["score"]
        # During active hour (20:00), historical should push to 0.92
        self.assertGreaterEqual(
            score, 0.90,
            f"Score {score:.3f} should be high (>=0.90) during historical window"
        )

    def test_scheduled_window_override_not_affected(self):
        """Scheduled windows still override to 0.95 regardless of evidence."""
        rec = _make_recording(
            scheduled_recording=True,
            scheduled_start_time="19:30:00",
            monitor_hours="2",
            live_sessions=[],
            consistency_score=0.0,
        )
        forecast = HistoryManager.get_forecast_details(rec, now=self.now)
        score = forecast["score"]
        # now is 20:00, scheduled 19:30+2h → 19:30-21:30, we're inside
        self.assertGreaterEqual(
            score, 0.95,
            f"Score {score:.3f} should be 0.95 during scheduled window"
        )

    def test_debug_stages_contain_evidence_weighted_info(self):
        """TEMP-DIAG debug stages must still reflect the adjusted score
        so logs explain the construction accurately."""
        rec = _make_recording(
            live_sessions=[
                _session("2026-05-20T20:00:00"),  # single session
            ],
            consistency_score=0.8,
            historical_intervals={"2": [20]},  # 1 day
        )
        debug = HistoryManager.get_forecast_details(
            rec, now=self.now, include_horizons=False, include_debug=True
        )
        stages = debug["_score_debug"]
        stage_names = [s[0] for s in stages]
        self.assertIn("session_conf", stage_names)
        self.assertIn("consistency", stage_names)
        self.assertIn("final", stage_names)
        # Verify consistency delta is suppressed (would be ~0.096 at full,
        # should be ~0.0192 with 1 day weight)
        delta = _consistency_delta(stages)
        self.assertLess(delta, 0.05)


if __name__ == "__main__":
    unittest.main()
