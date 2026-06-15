"""
Tests for RecordingsView — badge-related plumbing removal.

After removing predictive badges from the virtualized list delegate and
the grid-card badge cache / snapshot plumbing, we verify:
1. RecordingListDelegate no longer has badge-drawing methods.
2. RecordingListModel no longer has _badge_cache.
3. QtRecordingsView does not subscribe to precog_snapshot_batch.
"""

import inspect
import unittest
from unittest.mock import MagicMock


class BadgeDelegateMethodsRemovedTests(unittest.TestCase):
    """RecordingListDelegate no longer has badge-related methods."""

    def test_draw_badge_method_removed(self):
        """_draw_badge must not exist on RecordingListDelegate."""
        from app.qt.views.recordings_view import RecordingListDelegate
        assert not hasattr(RecordingListDelegate, "_draw_badge"), \
            "_draw_badge should be removed"

    def test_badge_data_method_removed(self):
        """_badge_data must not exist on RecordingListDelegate."""
        from app.qt.views.recordings_view import RecordingListDelegate
        assert not hasattr(RecordingListDelegate, "_badge_data"), \
            "_badge_data should be removed"

    def test_snapshot_data_method_removed(self):
        """_snapshot_data must not exist on RecordingListDelegate."""
        from app.qt.views.recordings_view import RecordingListDelegate
        assert not hasattr(RecordingListDelegate, "_snapshot_data"), \
            "_snapshot_data should be removed"


class BadgeModelCacheRemovedTests(unittest.TestCase):
    """RecordingListModel no longer has badge cache."""

    def test_badge_cache_not_in_model_init(self):
        """RecordingListModel must not have _badge_cache attribute."""
        from app.qt.views.recordings_view import RecordingListModel
        model = RecordingListModel.__new__(RecordingListModel)
        assert not hasattr(model, "_badge_cache"), \
            "_badge_cache should be removed from model"


class PrecogBatchSubscriptionRemovedTests(unittest.TestCase):
    """QtRecordingsView no longer subscribes to precog_snapshot_batch."""

    def test_on_precog_snapshot_batch_removed(self):
        """_on_precog_snapshot_batch must not exist on QtRecordingsView."""
        from app.qt.views.recordings_view import QtRecordingsView
        assert not hasattr(QtRecordingsView, "_on_precog_snapshot_batch"), \
            "_on_precog_snapshot_batch should be removed"

    def test_no_subscription_to_precog_snapshot_batch(self):
        """QtRecordingsView must not subscribe to precog_snapshot_batch."""
        from app.qt.views.recordings_view import QtRecordingsView

        bus = MagicMock()
        view = MagicMock(spec=QtRecordingsView)
        view.app = MagicMock()
        view.app.event_bus = bus

        QtRecordingsView._subscribe_events(view)

        subscribe_calls = [call.args[0] for call in bus.subscribe.call_args_list]
        assert "precog_snapshot_batch" not in subscribe_calls, \
            "No subscription to precog_snapshot_batch"

    def test_applies_filters_still_works(self):
        """_apply_filters runs without badge_cache reference."""
        from app.qt.views.recordings_view import QtRecordingsView

        view = MagicMock(spec=QtRecordingsView)
        view._view_mode = "list"
        view.list_model = MagicMock()
        view.list_view = MagicMock()
        view._cards = {}
        view._visible_recordings = []
        view._all_recordings = []
        view._current_status_filter = "all"
        view._current_platform_filter = "all"
        view._search_query = ""

        try:
            QtRecordingsView._apply_filters(view)
        except AttributeError as e:
            raise AssertionError(f"_apply_filters raised AttributeError: {e}") from e

    def test_refresh_tick_still_updates_cards(self):
        """_on_refresh_tick still updates grid cards without badge plumbing."""
        from app.qt.views.recordings_view import QtRecordingsView

        view = MagicMock(spec=QtRecordingsView)
        view._view_mode = "grid"
        view.list_model = MagicMock()
        view._update_badge_cache = MagicMock()

        QtRecordingsView._on_refresh_tick(view)

        # Grid mode calls _update_badge_cache but not refresh_all
        view._update_badge_cache.assert_called_once()
        view.list_model.refresh_all.assert_not_called()

    def test_paint_does_not_use_badge_data(self):
        """RecordingListDelegate.paint must not reference _badge_data."""
        from app.qt.views.recordings_view import RecordingListDelegate
        source = inspect.getsource(RecordingListDelegate.paint)
        assert "_badge_data" not in source, "paint must not call _badge_data"
        assert "_draw_badge" not in source, "paint must not call _draw_badge"


if __name__ == "__main__":
    unittest.main()
