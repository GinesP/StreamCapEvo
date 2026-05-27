import unittest
from unittest.mock import MagicMock, patch

from app.qt.views.recordings_view import RecordingListDelegate


class RecordingsViewPrecogTests(unittest.TestCase):
    @patch("app.core.recording.precog.Precog.predict")
    def test_likelihood_uses_precog_predict(self, mock_predict):
        """_likelihood must read likelihood via Precog.predict, not HistoryManager."""
        mock_predict.return_value = MagicMock(likelihood=0.85)

        rec = MagicMock()
        result = RecordingListDelegate._likelihood(rec)

        mock_predict.assert_called_once_with(rec)
        self.assertEqual(result, 0.85)

    @patch("app.core.recording.precog.Precog.predict")
    def test_likelihood_returns_zero_when_precog_raises(self, mock_predict):
        """When Precog.predict raises, _likelihood must gracefully return 0.0."""
        mock_predict.side_effect = Exception("boom")

        rec = MagicMock()
        result = RecordingListDelegate._likelihood(rec)

        self.assertEqual(result, 0.0)

    @patch("app.core.recording.precog.Precog.predict")
    def test_likelihood_returns_zero_when_precog_returns_zero(self, mock_predict):
        """When Precog returns 0 likelihood, _likelihood must return 0.0."""
        mock_predict.return_value = MagicMock(likelihood=0.0)

        rec = MagicMock()
        result = RecordingListDelegate._likelihood(rec)

        self.assertEqual(result, 0.0)


if __name__ == "__main__":
    unittest.main()
