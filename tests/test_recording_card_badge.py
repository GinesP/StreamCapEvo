import unittest
from unittest.mock import MagicMock, patch

from app.qt.components.recording_card import QtRecordingCard


class FillBadgesPrecogTests(unittest.TestCase):
    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_uses_precog_snapshot_for_likelihood(self, mock_snapshot, mock_badge_cls):
        """_fill_badges must read likelihood via Precog.snapshot, not HistoryManager."""
        mock_snapshot.return_value = MagicMock(
            queue_key="F",
            likelihood=0.85,
            is_stale=False,
        )

        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = None
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Precog.snapshot must be consulted
        mock_snapshot.assert_called_once_with(rec)

        # With likelihood 0.85, a "High" badge should be added
        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("High", badge_texts)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_queue_key_uses_stable_interval_not_snap(self, mock_snapshot, mock_badge_cls):
        """Queue key badge must use stable (base) interval, not snap.queue_key (jittered)."""
        # snap says "S" but base interval 120 → "M"
        mock_snapshot.return_value = MagicMock(
            queue_key="S",
            likelihood=0.0,
            is_stale=False,
        )

        rec = MagicMock()
        rec.loop_time_seconds = 120
        rec._last_snapshot = None
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("M", badge_texts)  # stable_queue_key(120) → M
        self.assertNotIn("S", badge_texts)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_queue_key_defaults_to_60_when_loop_time_none(self, mock_snapshot, mock_badge_cls):
        """When loop_time_seconds is None, queue badge must use 60 (legacy default)."""
        mock_snapshot.return_value = MagicMock(
            queue_key="S",  # jittered/adjusted would be S
            likelihood=0.0,
            is_stale=False,
        )

        rec = MagicMock()
        rec.loop_time_seconds = None
        rec._last_snapshot = None
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("F", badge_texts)  # 60 → F
        self.assertNotIn("S", badge_texts)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_no_likelihood_badge_when_snapshot_returns_zero(self, mock_snapshot, mock_badge_cls):
        """When Precog.snapshot returns 0 likelihood, no likelihood badge should appear."""
        mock_snapshot.return_value = MagicMock(
            queue_key="F",
            likelihood=0.0,
            is_stale=False,
        )

        rec = MagicMock()
        rec._last_snapshot = None
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Queue badge is always present
        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertEqual(len(badge_texts), 1)  # Only queue badge

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_fallback_badge_when_snapshot_fails(self, mock_snapshot, mock_badge_cls):
        """When Precog.snapshot raises, _fill_badges still renders a fallback queue badge."""
        mock_snapshot.side_effect = RuntimeError("snapshot failed")

        rec = MagicMock()
        rec._last_snapshot = None
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertEqual(len(badge_texts), 1)
        self.assertEqual(badge_texts[0], "?")



class FillBadgesLastSnapshotTests(unittest.TestCase):
    """_fill_badges reads from recording._last_snapshot when available."""

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_uses_last_snapshot_when_available(self, mock_snapshot, mock_badge_cls):
        """_fill_badges must prefer _last_snapshot over Precog.snapshot()."""
        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = MagicMock(likelihood=0.65, is_stale=False)

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_falls_back_to_snapshot_when_no_last_snapshot(self, mock_snapshot, mock_badge_cls):
        """_fill_badges calls Precog.snapshot() when _last_snapshot is not set."""
        mock_snapshot.return_value = MagicMock(likelihood=0.85, is_stale=False)

        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = None

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        mock_snapshot.assert_called_once_with(rec)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_last_snapshot_stale_flag_propagated(self, mock_snapshot, mock_badge_cls):
        """_fill_badges propagates is_stale from _last_snapshot."""
        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = MagicMock(likelihood=0.0, is_stale=True)

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("30D", badge_texts)
        mock_snapshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()
