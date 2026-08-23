"""
Tests for RecordingsView — badge-related plumbing removal.

After removing predictive badges from the virtualized list delegate and
the grid-card badge cache / snapshot plumbing, we verify:
1. RecordingListDelegate no longer has badge-drawing methods.
2. RecordingListModel no longer has _badge_cache.
3. QtRecordingsView does not subscribe to precog_snapshot_batch.
"""

import inspect
import re
import unittest
from unittest.mock import MagicMock

from app.qt.themes.theme import QUEUE_COLORS
from app.qt.views.recordings_view import (
    RecordingListDelegate,
    _derive_likelihood_badge,
    _derive_queue_badge,
    _derive_stale_badge,
    _interval_to_queue_key,
)


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


class LazyQueueBadgeTests(unittest.TestCase):
    """List delegate queue badge (F/M/S) is lazy, read-only, snapshot-free."""

    def _make_rec(self, **overrides):
        rec = MagicMock()
        rec._last_queue_key = overrides.get("_last_queue_key")
        rec.loop_time_seconds = overrides.get("loop_time_seconds")
        rec.streamer_name = overrides.get("streamer_name", "Nova")
        return rec

    def test_uses_last_queue_key_when_present(self):
        """Prefer predictor-computed _last_queue_key over derivation."""
        rec = self._make_rec(_last_queue_key="S", loop_time_seconds=600)
        key, color = _derive_queue_badge(rec)
        assert key == "S"
        assert color != "#9E9E9E"

    def test_falls_back_to_loop_time_seconds(self):
        """When _last_queue_key is missing, derive from loop_time_seconds."""
        rec = self._make_rec(_last_queue_key=None, loop_time_seconds=60)
        assert _derive_queue_badge(rec)[0] == "F"

        rec = self._make_rec(_last_queue_key=None, loop_time_seconds=120)
        assert _derive_queue_badge(rec)[0] == "M"

        rec = self._make_rec(_last_queue_key=None, loop_time_seconds=900)
        assert _derive_queue_badge(rec)[0] == "S"

    def test_fallback_defaults_to_medium_when_unknown(self):
        """Missing loop_time_seconds yields the legacy medium badge."""
        rec = self._make_rec(_last_queue_key=None, loop_time_seconds=None)
        key, color = _derive_queue_badge(rec)
        assert key == "M"
        assert color == QUEUE_COLORS["medium"]

    def test_interval_to_queue_key_semantics(self):
        """Local derivation mirrors Precog.interval_to_queue_key semantics."""
        assert _interval_to_queue_key(None) == "M"
        assert _interval_to_queue_key(60) == "F"
        assert _interval_to_queue_key(180) == "M"
        assert _interval_to_queue_key(181) == "S"

    def test_paint_is_snapshot_free(self):
        """paint must never call Precog.snapshot() (lazy/read-only only)."""
        source = inspect.getsource(RecordingListDelegate.paint)
        assert "snapshot" not in source, "paint must not reference snapshot"
        assert "Precog" not in source, "paint must not reference Precog"

    def test_no_global_badge_cache_introduced(self):
        """List delegate must not introduce a new global badge cache."""
        assert not hasattr(RecordingListDelegate, "_badge_cache"), \
            "_badge_cache must not be introduced"


class LazyStaleBadgeTests(unittest.TestCase):
    """List delegate staleness badge (30D) is lazy, read-only, snapshot-free."""

    def _make_rec(self, **overrides):
        rec = MagicMock()
        rec.last_seen_live = overrides.get("last_seen_live")
        rec.added_at = overrides.get("added_at")
        rec.streamer_name = overrides.get("streamer_name", "Nova")
        return rec

    def test_stale_when_last_seen_older_than_30d(self):
        """A stream unseen for >30 days yields a 30D badge."""
        rec = self._make_rec(last_seen_live="2020-01-01T00:00:00")
        assert _derive_stale_badge(rec) is True

    def test_not_stale_when_recently_seen(self):
        """A stream seen recently does not yield a 30D badge."""
        from datetime import datetime

        recent = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        rec = self._make_rec(last_seen_live=recent)
        assert _derive_stale_badge(rec) is False

    def test_stale_falls_back_to_added_at(self):
        """Missing last_seen_live falls back to added_at for staleness."""
        rec = self._make_rec(last_seen_live=None, added_at="2020-01-01T00:00:00")
        assert _derive_stale_badge(rec) is True

    def test_not_stale_when_no_dates(self):
        """A stream with no available dates is never flagged stale."""
        rec = self._make_rec(last_seen_live=None, added_at=None)
        assert _derive_stale_badge(rec) is False

    def test_stale_badge_uses_existing_dates_only(self):
        """_derive_stale_badge must not add snapshot/cache plumbing."""
        source = inspect.getsource(_derive_stale_badge)
        # Strip the docstring so only real code is asserted against.
        body = re.sub(r'"""[^"]*"""', "", source, count=1)
        assert "snapshot" not in body, "stale badge must not reference snapshot"
        assert "Precog" not in body, "stale badge must not reference Precog"
        assert "_badge_cache" not in body, "stale badge must not use a cache"

    def test_paint_draws_stale_badge_without_cache(self):
        """paint references the lazy stale badge and stays snapshot-free."""
        source = inspect.getsource(RecordingListDelegate.paint)
        assert "_derive_stale_badge" in source, "paint must draw the 30D badge"
        assert "snapshot" not in source, "paint must not reference snapshot"
        assert "Precog" not in source, "paint must not reference Precog"


class LazyLikelihoodBadgeTests(unittest.TestCase):
    """List delegate likelihood badge (%) is lazy, read-only, snapshot-free."""

    def _make_rec(self, **overrides):
        rec = MagicMock()
        rec._last_likelihood = overrides.get("_last_likelihood")
        rec.priority_score = overrides.get("priority_score", 0.0)
        rec.streamer_name = overrides.get("streamer_name", "Nova")
        return rec

    def test_uses_last_likelihood_when_present(self):
        """Prefer predictor-computed _last_likelihood for the badge."""
        rec = self._make_rec(_last_likelihood=0.9)
        label, color = _derive_likelihood_badge(rec)
        assert label == "90%"
        assert color == "#4CAF50"

    def test_falls_back_to_priority_score(self):
        """When _last_likelihood is missing, fall back to priority_score."""
        rec = self._make_rec(_last_likelihood=None, priority_score=0.3)
        label, color = _derive_likelihood_badge(rec)
        assert label == "30%"
        assert color == "#FF9800"

    def test_omitted_when_score_is_zero(self):
        """A 0 score yields no badge (mirrors the grid card rule)."""
        rec = self._make_rec(_last_likelihood=0.0)
        assert _derive_likelihood_badge(rec) is None

        rec = self._make_rec(_last_likelihood=None, priority_score=0.0)
        assert _derive_likelihood_badge(rec) is None

    def test_color_thresholds(self):
        """Likelihood color follows the grid card thresholds."""
        assert _derive_likelihood_badge(self._make_rec(_last_likelihood=0.6))[1] == "#4CAF50"
        assert _derive_likelihood_badge(self._make_rec(_last_likelihood=0.3))[1] == "#FF9800"
        assert _derive_likelihood_badge(self._make_rec(_last_likelihood=0.1))[1] == "#F44336"

    def test_label_format_for_over_one_scores(self):
        """Scores expressed as >1 percentages keep their raw integer form."""
        label, _ = _derive_likelihood_badge(self._make_rec(_last_likelihood=85))
        assert label == "85%"

    def test_helper_is_snapshot_free_and_cache_free(self):
        """_derive_likelihood_badge must not add snapshot/cache plumbing."""
        source = inspect.getsource(_derive_likelihood_badge)
        body = re.sub(r'"""[^"]*"""', "", source, count=1)
        assert "snapshot" not in body, "likelihood badge must not reference snapshot"
        assert "Precog" not in body, "likelihood badge must not reference Precog"
        assert "_badge_cache" not in body, "likelihood badge must not use a cache"

    def test_paint_draws_likelihood_badge_without_cache(self):
        """paint references the lazy likelihood badge and stays snapshot-free."""
        source = inspect.getsource(RecordingListDelegate.paint)
        assert "_derive_likelihood_badge" in source, "paint must draw the likelihood badge"
        assert "snapshot" not in source, "paint must not reference snapshot"
        assert "Precog" not in source, "paint must not reference Precog"
        assert "_badge_cache" not in source, "paint must not introduce a cache"


if __name__ == "__main__":
    unittest.main()
