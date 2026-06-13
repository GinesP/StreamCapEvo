import unittest
from unittest.mock import MagicMock, patch

from app.qt.components.recording_card import QtRecordingCard


class FillBadgesNoSnapshotTests(unittest.TestCase):
    """_fill_badges must NEVER call Precog.snapshot; uses stable fallback."""

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_never_calls_precog_snapshot_when_no_last_snapshot(self, mock_snapshot, mock_badge_cls):
        """_fill_badges must NOT call Precog.snapshot when _last_snapshot is None."""
        rec = MagicMock()
        rec._last_snapshot = None
        rec.loop_time_seconds = 60

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_never_calls_precog_snapshot_when_last_snapshot_present(self, mock_snapshot, mock_badge_cls):
        """_fill_badges must NOT call Precog.snapshot when _last_snapshot is available."""
        rec = MagicMock()
        rec._last_snapshot = MagicMock(likelihood=0.65, is_stale=False, queue_key="F")
        rec.loop_time_seconds = 60

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_stable_fallback_uses_stable_queue_key(self, mock_snapshot, mock_badge_cls):
        """When _last_snapshot is None, queue badge uses stable_queue_key."""
        rec = MagicMock()
        rec._last_snapshot = None
        rec.loop_time_seconds = 120  # → "M" via stable_queue_key

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("M", badge_texts)
        self.assertNotIn("F", badge_texts)
        self.assertNotIn("S", badge_texts)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_stable_fallback_default_60(self, mock_snapshot, mock_badge_cls):
        """When loop_time_seconds is None, stable_queue_key defaults to 60 → 'F'."""
        rec = MagicMock()
        rec._last_snapshot = None
        rec.loop_time_seconds = None

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("F", badge_texts)

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.core.recording.precog.Precog.snapshot")
    def test_no_likelihood_badge_in_fallback(self, mock_snapshot, mock_badge_cls):
        """When _last_snapshot is None, only queue badge is shown (no likelihood badge)."""
        rec = MagicMock()
        rec._last_snapshot = None
        rec.loop_time_seconds = 300  # → "S" via stable_queue_key

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        # Only queue badge, no likelihood badge
        self.assertEqual(len(badge_texts), 1)
        self.assertIn("S", badge_texts)



class FillBadgesLastSnapshotTests(unittest.TestCase):
    """_fill_badges reads from recording._last_snapshot when available."""

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_uses_last_snapshot_when_available(self, mock_snapshot, mock_badge_cls):
        """_fill_badges must prefer _last_snapshot over Precog.snapshot()."""
        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = MagicMock(likelihood=0.65, is_stale=False, queue_key="F")

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_uses_stable_fallback_when_no_last_snapshot(self, mock_snapshot, mock_badge_cls):
        """_fill_badges uses stable fallback (not Precog.snapshot) when _last_snapshot is not set."""
        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = None

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_last_snapshot_stale_flag_propagated(self, mock_snapshot, mock_badge_cls):
        """_fill_badges propagates is_stale from _last_snapshot."""
        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = MagicMock(likelihood=0.0, is_stale=True, queue_key="F")

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("30D", badge_texts)
        mock_snapshot.assert_not_called()


class FillBadgesFallbackStaleTests(unittest.TestCase):
    """_fill_badges fallback derives is_stale from RecordingStateLogic.is_stale(rec)."""

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    @patch("app.core.recording.recording_state_logic.RecordingStateLogic.is_stale")
    def test_fallback_stale_shows_30d_badge_when_stale(self, mock_is_stale, mock_snapshot, mock_badge_cls):
        """When _last_snapshot is None and rec is stale, fallback shows 30D badge."""
        mock_is_stale.return_value = True

        rec = MagicMock()
        rec._last_snapshot = None
        rec.loop_time_seconds = 180

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertIn("30D", badge_texts)
        mock_is_stale.assert_called_once_with(rec)
        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    @patch("app.core.recording.recording_state_logic.RecordingStateLogic.is_stale")
    def test_fallback_no_30d_badge_when_not_stale(self, mock_is_stale, mock_snapshot, mock_badge_cls):
        """When _last_snapshot is None and rec is not stale, 30D badge is absent."""
        mock_is_stale.return_value = False

        rec = MagicMock()
        rec._last_snapshot = None
        rec.loop_time_seconds = 60

        layout = MagicMock()
        layout.count.return_value = 0

        card = MagicMock()
        card._badge_state_test = None

        QtRecordingCard._fill_badges(rec, layout, card, "test")

        calls = [call.args for call in mock_badge_cls.call_args_list]
        badge_texts = [args[0] for args in calls if args]
        self.assertNotIn("30D", badge_texts)
        mock_is_stale.assert_called_once_with(rec)
        mock_snapshot.assert_not_called()

    @patch("app.qt.components.recording_card._Badge")
    @patch("app.qt.components.recording_card.Precog.snapshot")
    def test_stale_from_snapshot_still_works(self, mock_snapshot, mock_badge_cls):
        """When _last_snapshot is present, is_stale from snapshot is used (not state logic)."""
        rec = MagicMock()
        rec.loop_time_seconds = 60
        rec._last_snapshot = MagicMock(likelihood=0.0, is_stale=True, queue_key="F")

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
