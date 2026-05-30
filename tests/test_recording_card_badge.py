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
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        type(card)._badge_state_test = MagicMock(return_value=None)

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Precog.snapshot must be consulted
        mock_snapshot.assert_called_once_with(rec)

        # With likelihood 0.85, a "High" badge should be added
        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("High", badge_texts)

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
        type(card)._badge_state_test = MagicMock(return_value=None)

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Queue badge is always present
        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertEqual(badge_texts, ["F"])  # Only queue badge


    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_fallback_badge_when_snapshot_fails(self, mock_snapshot, mock_badge_cls):
        """When Precog.snapshot raises, _fill_badges still renders a fallback queue badge."""
        mock_snapshot.side_effect = RuntimeError("snapshot failed")

        rec = MagicMock()
        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        type(card)._badge_state_test = MagicMock(return_value=None)

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        self.assertGreaterEqual(len(calls), 1)
        self.assertIn("?", [args[0] for args in calls if args])


if __name__ == "__main__":
    unittest.main()
