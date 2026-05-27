import unittest
from unittest.mock import MagicMock, patch

from app.qt.components.recording_card import QtRecordingCard


class FillBadgesPrecogTests(unittest.TestCase):
    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.RecordingStateLogic")
    @patch("app.core.recording.precog.Precog.predict")
    def test_uses_precog_predict_for_likelihood(self, mock_predict, mock_logic, mock_badge_cls):
        """_fill_badges must read likelihood via Precog.predict, not HistoryManager."""
        mock_predict.return_value = MagicMock(likelihood=0.85)
        mock_logic.is_stale.return_value = False

        rec = MagicMock()
        rec.loop_time_seconds = 60

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        # Ensure cache miss so badges are rebuilt
        type(card)._badge_state_test = MagicMock(return_value=None)

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Precog must be consulted
        mock_predict.assert_called_once_with(rec)

        # With likelihood 0.85, a "High" badge should be added
        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("High", badge_texts)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.RecordingStateLogic")
    @patch("app.core.recording.precog.Precog.predict")
    def test_no_likelihood_badge_when_precog_returns_zero(self, mock_predict, mock_logic, mock_badge_cls):
        """When Precog returns 0 likelihood, no likelihood badge should appear."""
        mock_predict.return_value = MagicMock(likelihood=0.0)
        mock_logic.is_stale.return_value = False

        rec = MagicMock()
        rec.loop_time_seconds = 60

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        type(card)._badge_state_test = MagicMock(return_value=None)

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Queue badge is always present
        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertEqual(badge_texts, ["F"])  # Only queue badge


if __name__ == "__main__":
    unittest.main()
