import inspect
import unittest
from unittest.mock import MagicMock

from app.qt.views.home_view import QtHomeView


class HomeViewRefreshSchedulingTests(unittest.TestCase):
    def test_init_uses_owned_single_shot_refresh_timer(self):
        source = inspect.getsource(QtHomeView.__init__)
        self.assertIn("self._stats_refresh_debounce_timer = QTimer(self)", source)
        self.assertIn("self._stats_refresh_debounce_timer.setSingleShot(True)", source)
        self.assertIn("self._stats_refresh_debounce_timer.setInterval(100)", source)
        self.assertNotIn("QTimer.singleShot(100, self._refresh_stats)", source)

    def test_recording_events_only_schedule_when_no_refresh_is_pending(self):
        view = MagicMock()
        view._stats_refresh_debounce_timer.isActive.side_effect = [False, True, True]

        QtHomeView._on_recording_event(view, "update", {})
        QtHomeView._on_recording_event(view, "add", {})
        QtHomeView._on_recording_event(view, "delete", {})

        view._stats_refresh_debounce_timer.start.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
