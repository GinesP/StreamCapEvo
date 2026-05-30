import unittest
from unittest.mock import MagicMock, patch

from app.qt.views.recordings_view import RecordingListDelegate


class RecordingsViewPrecogTests(unittest.TestCase):
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_snapshot_data_stable_queue_key(self, mock_snapshot):
        """Queue key uses stable (base) interval, not snap.queue_key (jittered)."""
        mock_snapshot.return_value = MagicMock(
            queue_key="F", likelihood=0.65, is_stale=False,
        )

        rec = MagicMock()
        rec.loop_time_seconds = 120  # → "M" via stable_queue_key
        qk, qc, likelihood, stale = RecordingListDelegate._snapshot_data(rec)

        mock_snapshot.assert_called_once_with(rec)
        self.assertEqual(qk, "M")   # 120s → M, NOT snap.queue_key which was "F"
        self.assertEqual(likelihood, 0.65)
        self.assertFalse(stale)

    @patch("app.core.recording.precog.Precog.snapshot")
    def test_snapshot_data_default_fallback_60(self, mock_snapshot):
        """When loop_time_seconds is None, stable queue key uses 60 (legacy default)."""
        mock_snapshot.return_value = MagicMock(
            queue_key="S", likelihood=0.0, is_stale=False,
        )

        rec = MagicMock()
        rec.loop_time_seconds = None
        qk, qc, likelihood, stale = RecordingListDelegate._snapshot_data(rec)

        self.assertEqual(qk, "F")   # 60 → F, NOT snap.queue_key which was "S"

    @patch("app.core.recording.precog.Precog.snapshot")
    def test_snapshot_data_fallback_on_error(self, mock_snapshot):
        """When Precog.snapshot raises, _snapshot_data must return safe defaults."""
        mock_snapshot.side_effect = RuntimeError("fail")

        rec = MagicMock()
        qk, qc, likelihood, stale = RecordingListDelegate._snapshot_data(rec)

        self.assertEqual(qk, "?")
        self.assertEqual(likelihood, 0.0)
        self.assertFalse(stale)

    @patch("app.core.recording.precog.Precog.snapshot")
    def test_snapshot_data_zero_likelihood(self, mock_snapshot):
        """When snapshot returns 0 likelihood, _snapshot_data must preserve it."""
        mock_snapshot.return_value = MagicMock(
            queue_key="M", likelihood=0.0, is_stale=False,
        )

        rec = MagicMock()
        rec.loop_time_seconds = 60
        qk, qc, likelihood, stale = RecordingListDelegate._snapshot_data(rec)

        self.assertEqual(likelihood, 0.0)
        self.assertEqual(qk, "F")
        self.assertFalse(stale)

    @patch("app.core.recording.precog.Precog.snapshot")
    def test_snapshot_data_stale_flag(self, mock_snapshot):
        """When snapshot returns is_stale=True, _snapshot_data must propagate it."""
        mock_snapshot.return_value = MagicMock(
            queue_key="S", likelihood=0.0, is_stale=True,
        )

        rec = MagicMock()
        rec.loop_time_seconds = 300  # → "S" via stable_queue_key
        qk, qc, likelihood, stale = RecordingListDelegate._snapshot_data(rec)

        self.assertTrue(stale)
        self.assertEqual(qk, "S")

    @patch("app.core.recording.precog.Precog.snapshot")
    def test_badge_data_reads_from_model_cache(self, mock_snapshot):
        """_badge_data must return cached data when available, avoiding snapshot."""
        mock_snapshot.return_value = MagicMock(
            queue_key="F", likelihood=0.9, is_stale=True,
        )

        rec = MagicMock()
        rec.rec_id = "test-1"
        rec.loop_time_seconds = 60

        model = MagicMock()
        model._badge_cache = {"test-1": ("M", "#FF9800", 0.5, False)}

        index = MagicMock()
        index.model.return_value = model

        delegate = RecordingListDelegate(MagicMock())
        qk, qc, likelihood, stale = delegate._badge_data(rec, index)

        # Cached data returned, not snapshot
        self.assertEqual(qk, "M")
        self.assertEqual(likelihood, 0.5)
        self.assertFalse(stale)
        mock_snapshot.assert_not_called()



class PrecogSnapshotBatchTests(unittest.TestCase):
    """Tests for QtRecordingsView._on_precog_snapshot_batch."""

    def test_populates_badge_cache_from_snapshots(self):
        """_on_precog_snapshot_batch populates list model badge cache without Precog recomputation."""
        from app.qt.views.recordings_view import QtRecordingsView

        rec = MagicMock()
        rec.rec_id = "test-1"
        rec.loop_time_seconds = 60  # → "F" via stable_queue_key

        snap = MagicMock()
        snap.likelihood = 0.85
        snap.is_stale = False

        model = MagicMock()
        model._badge_cache = {}
        model.recordings.return_value = [rec]

        view = MagicMock(spec=QtRecordingsView)
        view.list_model = model
        view._view_mode = "list"
        view.list_view = MagicMock()
        view._cards = {}

        QtRecordingsView._on_precog_snapshot_batch(
            view, "precog_snapshot_batch", {"test-1": snap}
        )

        cached = model._badge_cache.get("test-1")
        self.assertIsNotNone(cached)
        qk, qc, likelihood, stale = cached
        self.assertEqual(qk, "F")
        self.assertEqual(likelihood, 0.85)
        self.assertFalse(stale)

    def test_skips_recordings_not_in_snapshot_batch(self):
        """Recordings missing from snapshots dict keep existing cache entries."""
        from app.qt.views.recordings_view import QtRecordingsView

        rec_updated = MagicMock()
        rec_updated.rec_id = "updated"
        rec_updated.loop_time_seconds = 60

        rec_missing = MagicMock()
        rec_missing.rec_id = "missing"
        rec_missing.loop_time_seconds = 300

        snap = MagicMock()
        snap.likelihood = 0.9
        snap.is_stale = False

        model = MagicMock()
        model._badge_cache = {"missing": ("S", "#FF0000", 0.1, True)}
        model.recordings.return_value = [rec_updated, rec_missing]

        view = MagicMock(spec=QtRecordingsView)
        view.list_model = model
        view._view_mode = "list"
        view.list_view = MagicMock()
        view._cards = {}

        QtRecordingsView._on_precog_snapshot_batch(
            view, "precog_snapshot_batch", {"updated": snap}
        )

        # Updated recording gets new cache entry
        updated_cached = model._badge_cache.get("updated")
        self.assertIsNotNone(updated_cached)
        self.assertEqual(updated_cached[0], "F")

        # Missing recording keeps old entry
        missing_cached = model._badge_cache.get("missing")
        self.assertIsNotNone(missing_cached)
        self.assertEqual(missing_cached, ("S", "#FF0000", 0.1, True))


if __name__ == "__main__":
    unittest.main()
