"""Verify Recording.to_dict() excludes hot-path telemetry fields.

These fields (live_check_count, priority_score) change every monitoring cycle
and were causing per-cycle persistence churn. They are runtime heuristics that
naturally rebuild via increment_live_counts() on restart.

from_dict() remains backward-compatible to read old persisted data that still
contains these fields.
"""

import unittest

from app.models.recording.recording_model import Recording


def _make(**overrides):
    defaults = {
        "rec_id": "test-1",
        "url": "http://example.com/stream",
        "streamer_name": "TestStreamer",
        "record_format": "mp4",
        "quality": "HD",
        "segment_record": False,
        "segment_time": 3600,
        "monitor_status": True,
        "scheduled_recording": False,
        "scheduled_start_time": None,
        "monitor_hours": 2,
        "recording_dir": "/tmp",
        "enabled_message_push": False,
        "only_notify_no_record": False,
        "flv_use_direct_download": False,
    }
    defaults.update(overrides)
    return Recording(**defaults)


class TestRecordingToDictHotFields(unittest.TestCase):
    """to_dict must NOT include live_check_count or priority_score."""

    def test_to_dict_excludes_live_check_count(self):
        """live_check_count must NOT appear in to_dict output."""
        rec = _make(live_check_count=42)
        d = rec.to_dict()
        self.assertNotIn("live_check_count", d)

    def test_to_dict_excludes_priority_score(self):
        """priority_score must NOT appear in to_dict output."""
        rec = _make(priority_score=0.85)
        d = rec.to_dict()
        self.assertNotIn("priority_score", d)

    def test_to_dict_still_includes_live_found_count(self):
        """live_found_count must still be persisted (not a hot field)."""
        rec = _make(live_found_count=7)
        d = rec.to_dict()
        self.assertIn("live_found_count", d)
        self.assertEqual(d["live_found_count"], 7)

    def test_to_dict_includes_durable_fields(self):
        """Core durable fields must still be present."""
        rec = _make()
        d = rec.to_dict()
        for key in ("rec_id", "url", "streamer_name", "monitor_status", "is_favorite"):
            self.assertIn(key, d)

    def test_from_dict_backward_compat_with_hot_fields(self):
        """from_dict must still read live_check_count and priority_score from old data."""
        data = {
            "rec_id": "test-2",
            "url": "http://example.com/old",
            "streamer_name": "OldStream",
            "record_format": "mp4",
            "quality": "HD",
            "segment_record": False,
            "segment_time": 3600,
            "monitor_status": True,
            "scheduled_recording": False,
            "scheduled_start_time": None,
            "monitor_hours": 2,
            "recording_dir": "/tmp",
            "enabled_message_push": False,
            "only_notify_no_record": False,
            "flv_use_direct_download": False,
            "live_check_count": 99,
            "priority_score": 0.75,
        }
        rec = Recording.from_dict(data)
        self.assertEqual(rec.live_check_count, 99)
        self.assertEqual(rec.priority_score, 0.75)

    def test_from_dict_defaults_when_hot_fields_missing(self):
        """from_dict must default live_check_count=0 and priority_score=0.0 when missing."""
        data = {
            "rec_id": "test-3",
            "url": "http://example.com/new",
            "streamer_name": "NewStream",
            "record_format": "mp4",
            "quality": "HD",
            "segment_record": False,
            "segment_time": 3600,
            "monitor_status": True,
            "scheduled_recording": False,
            "scheduled_start_time": None,
            "monitor_hours": 2,
            "recording_dir": "/tmp",
            "enabled_message_push": False,
            "only_notify_no_record": False,
            "flv_use_direct_download": False,
        }
        rec = Recording.from_dict(data)
        self.assertEqual(rec.live_check_count, 0)
        self.assertEqual(rec.priority_score, 0.0)

    def test_no_save_churn_when_only_hot_fields_change(self):
        """Simulate the save path: to_dict differences must NOT come from hot fields.

        This proves that changing live_check_count or priority_score at runtime
        does NOT cause the persist/diff logic to flag the record as changed.
        """
        rec = _make(live_check_count=5, priority_score=0.3)
        d1 = rec.to_dict()

        # Simulate a monitoring cycle updating only hot fields
        rec.live_check_count = 10
        rec.priority_score = 0.7
        d2 = rec.to_dict()

        # to_dict should be identical since hot fields are excluded
        self.assertEqual(d1, d2)


if __name__ == "__main__":
    unittest.main()
