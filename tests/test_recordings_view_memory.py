"""
Focused tests for always-live Qt/native-memory mitigations.

1. RecordingListModel skips a full model reset when the visible list
   content/order did not actually change.
2. The 1-second refresh timer is paused while the recordings view is
   hidden and resumed when it is shown again.
3. Parented exec() dialogs carry WA_DeleteOnClose so their native windows
   are released on close instead of staying alive until app exit.
"""

import inspect
import types
import unittest
from unittest.mock import MagicMock

from app.qt.views.recordings_view import QtRecordingsView, RecordingListModel


def _recordings(count: int) -> list:
    return [types.SimpleNamespace(rec_id=str(i)) for i in range(count)]


class RecordingListModelResetGuardTests(unittest.TestCase):
    """set_recordings must not reset the model for identical content/order."""

    def _tracked_model(self):
        model = RecordingListModel()
        spy = MagicMock()
        model.modelAboutToBeReset.connect(spy)
        return model, spy

    def test_identical_content_skips_model_reset(self):
        recs = _recordings(3)
        model, spy = self._tracked_model()
        model.set_recordings(recs)
        assert spy.call_count == 1

        model.set_recordings(list(recs))

        assert spy.call_count == 1  # no extra reset

    def test_reordered_content_triggers_model_reset(self):
        recs = _recordings(3)
        model, spy = self._tracked_model()
        model.set_recordings(recs)

        model.set_recordings(list(reversed(recs)))

        assert spy.call_count == 2

    def test_changed_content_triggers_model_reset(self):
        recs = _recordings(3)
        model, spy = self._tracked_model()
        model.set_recordings(recs)

        model.set_recordings([types.SimpleNamespace(rec_id="new"), *recs[1:]])

        assert spy.call_count == 2

    def test_empty_to_empty_never_resets(self):
        model, spy = self._tracked_model()
        model.set_recordings([])
        spy.assert_not_called()

        model.set_recordings([])
        spy.assert_not_called()

    def test_empty_to_nonempty_triggers_reset(self):
        model, spy = self._tracked_model()
        model.set_recordings([])

        model.set_recordings(_recordings(2))

        assert spy.call_count == 1

    def test_model_still_holds_latest_recordings(self):
        recs = _recordings(3)
        model = RecordingListModel()
        model.set_recordings(recs)
        model.set_recordings([recs[0], recs[2]])
        assert [r.rec_id for r in model.recordings()] == ["0", "2"]


class RefreshTimerPauseTests(unittest.TestCase):
    """The 1s refresh timer runs only while the recordings view is visible."""

    def _make_view(self, active: bool = False):
        timer = MagicMock()
        timer.isActive.return_value = active
        view = MagicMock(spec=QtRecordingsView)
        view._refresh_timer = timer
        return view, timer

    def test_start_starts_inactive_timer(self):
        view, timer = self._make_view(active=False)

        QtRecordingsView._start_refresh_timer(view)

        timer.start.assert_called_once_with(1000)

    def test_start_keeps_active_timer_running(self):
        view, timer = self._make_view(active=True)

        QtRecordingsView._start_refresh_timer(view)

        timer.start.assert_not_called()

    def test_stop_stops_active_timer(self):
        view, timer = self._make_view(active=True)

        QtRecordingsView._stop_refresh_timer(view)

        timer.stop.assert_called_once_with()

    def test_stop_skips_already_stopped_timer(self):
        view, timer = self._make_view(active=False)

        QtRecordingsView._stop_refresh_timer(view)

        timer.stop.assert_not_called()

    def test_init_does_not_start_timer_unconditionally(self):
        init_source = inspect.getsource(QtRecordingsView.__init__)
        assert "self._refresh_timer = QTimer(self)" in init_source
        assert "_refresh_timer.start(1000)" not in init_source

    def test_show_and_hide_events_wire_timer_helpers(self):
        source = inspect.getsource(QtRecordingsView.showEvent)
        assert "_start_refresh_timer" in source
        source = inspect.getsource(QtRecordingsView.hideEvent)
        assert "_stop_refresh_timer" in source


class DialogDeleteOnCloseTests(unittest.TestCase):
    """Parented exec() dialogs must release native memory on close."""

    DIALOGS = [
        ("app.qt.components.add_stream_dialog", "QtAddStreamDialog"),
        ("app.qt.components.confirm_dialog", "QtConfirmDialog"),
        ("app.qt.components.recording_info_dialog", "QtRecordingInfoDialog"),
    ]

    def test_exec_dialogs_set_delete_on_close(self):
        for module_name, cls_name in self.DIALOGS:
            with self.subTest(dialog=cls_name):
                module = __import__(module_name, fromlist=[cls_name])
                init_source = inspect.getsource(getattr(module, cls_name).__init__)
                assert "WA_DeleteOnClose" in init_source

    def test_shared_video_player_keeps_delete_on_close_off(self):
        """QtVideoPlayer is a reused shared dialog — it must NOT self-delete."""
        from app.qt.components.video_player import QtVideoPlayer

        init_source = inspect.getsource(QtVideoPlayer.__init__)
        assert "WA_DeleteOnClose" not in init_source


if __name__ == "__main__":
    unittest.main()
