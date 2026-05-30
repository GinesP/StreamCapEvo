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
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertEqual(len(badge_texts), 1)
        self.assertEqual(badge_texts[0], "?")


if __name__ == "__main__":
    unittest.main()
