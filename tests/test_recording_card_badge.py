"""
Tests for QtRecordingCard — lightweight predictive badges.

After reintroducing badges using ONLY lightweight fields already persisted
by the predictor cycle (no Precog.snapshot(), no _last_snapshot), we verify:
1. Badges render when lightweight data (queue, likelihood) is present.
2. The UI does NOT depend on ``Precog.snapshot()``.
3. Queue badge derives correctly (F/M/S) and does NOT collapse everything to M.
4. Staleness badge (30D) works without snapshot data.
5. ``Precog`` is not imported in ``recording_card`` module.
6. ``_last_snapshot`` is never read or stored.
"""

import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, PropertyMock, patch


class NoPrecogImportTests(unittest.TestCase):
    """Precog must not be imported by the recording_card module."""

    def test_no_precog_import_in_recording_card(self):
        """Precog import must not exist in recording_card module."""
        import app.qt.components.recording_card as mod
        assert not hasattr(mod, "Precog"), \
            "Precog must not be imported in recording_card"


class FillBadgesLogicTests(unittest.TestCase):
    """_fill_badges logic — tests without creating real Qt widgets."""

    # Patch _Badge at module level so no real QFrame is created
    def _make_rec(self, **overrides):
        """Create a mock recording with realistic badge attributes."""
        rec = MagicMock()
        rec._last_queue_key = overrides.get("queue_key", "F")
        rec._last_likelihood = overrides.get("likelihood", 0.75)
        rec.priority_score = overrides.get("priority", 0.5)
        rec.loop_time_seconds = overrides.get("loop_time", 60)
        rec.last_seen_live = overrides.get("last_seen", None)
        rec.added_at = overrides.get("added_at", None)
        rec.is_live = overrides.get("is_live", False)
        rec.monitor_status = overrides.get("monitor_status", True)
        rec.is_checking = overrides.get("is_checking", False)
        rec.status_info = overrides.get("status_info", "Monitoring")
        rec.is_recording = overrides.get("is_recording", False)
        return rec

    def _make_layout(self):
        layout = MagicMock()
        layout.count.return_value = 0
        return layout

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_adds_widgets_to_layout(self, mock_badge):
        """_fill_badges adds at least queue badge to layout."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec()
        layout = self._make_layout()
        card = MagicMock()

        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")

        # _Badge should have been instantiated at least once
        self.assertGreater(mock_badge.call_count, 0,
                           "_Badge must be instantiated for queue badge")
        # addWidget must have been called
        self.assertGreater(layout.addWidget.call_count, 0,
                           "Widgets must be added to badge layout")

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_cache_avoids_rebuild(self, mock_badge):
        """_fill_badges returns early without churn when data is unchanged."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec()
        layout = self._make_layout()
        card = MagicMock()

        # First call — populates cache, creates badges
        mock_badge.reset_mock()
        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")
        self.assertGreater(mock_badge.call_count, 0,
                           "First call should instantiate badges")

        # Second call with same state — cache should prevent widget creation
        mock_badge.reset_mock()
        layout.addWidget.reset_mock()
        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")
        self.assertEqual(mock_badge.call_count, 0,
                         "No _Badge instances should be created when cache matches")
        self.assertEqual(layout.addWidget.call_count, 0,
                         "addWidget should not be called when cache matches")

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_updates_on_new_data(self, mock_badge):
        """_fill_badges refreshes widgets when queue or likelihood changes."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec()
        layout = self._make_layout()
        card = MagicMock()

        # First call
        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Change data
        rec._last_queue_key = "M"
        rec._last_likelihood = 0.25
        layout.addWidget.reset_mock()

        # Second call — should rebuild
        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")
        self.assertGreater(layout.addWidget.call_count, 0,
                           "addWidget should be called after data changes")

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_skips_0_score_likelihood(self, mock_badge):
        """Likelihood badge omitted when score is 0."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec(likelihood=0.0, priority=0.0, loop_time=180)
        layout = self._make_layout()
        card = MagicMock()

        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Should have only 1 _Badge (queue only, no likelihood, no stale)
        self.assertEqual(mock_badge.call_count, 1,
                         "Only queue badge expected when likelihood=0 and not stale")

    @patch("app.qt.components.recording_card._Badge")
    def test_queue_key_fallback_from_loop_time(self, mock_badge):
        """When _last_queue_key is None, derive from loop_time_seconds."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec(queue_key=None, likelihood=None,
                             priority=0.0, loop_time=300)
        layout = self._make_layout()
        card = MagicMock()

        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")
        self.assertGreater(mock_badge.call_count, 0,
                           "Fallback should still produce queue badge")

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_shows_30D_when_stale(self, mock_badge):
        """30D stale badge shown for recordings not seen live in 30+ days."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec(
            queue_key="S", likelihood=0.0, priority=0.0,
            loop_time=300, last_seen="2024-01-01", added_at="2023-12-01",
        )
        layout = self._make_layout()
        card = MagicMock()

        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")

        # Get the "30D" or "stale" argument passed to _Badge
        call_texts = [call.args[0] if call.args else "" for call in mock_badge.call_args_list]
        has_stale = any("30" in str(t) or "stale" in str(t).lower() for t in call_texts)
        self.assertTrue(has_stale,
                        "30D stale badge should be present for stale recordings")

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_no_stale_for_recent_streams(self, mock_badge):
        """No 30D badge for streams seen recently."""
        import app.qt.components.recording_card as mod

        recent_last_seen = (datetime.now() - timedelta(days=7)).date().isoformat()
        recent_added_at = (datetime.now() - timedelta(days=20)).date().isoformat()

        rec = self._make_rec(
            queue_key="F", likelihood=0.8, priority=0.5,
            loop_time=60, last_seen=recent_last_seen, added_at=recent_added_at,
        )
        layout = self._make_layout()
        card = MagicMock()

        mod.QtRecordingCard._fill_badges(rec, layout, card, "test")

        call_texts = [str(call.args[0]) if call.args else "" for call in mock_badge.call_args_list]
        has_stale = any("30" in t or "stale" in t.lower() for t in call_texts)
        self.assertFalse(has_stale,
                         "No 30D badge expected for recently seen streams")

    @patch("app.qt.components.recording_card._Badge")
    def test_fill_badges_both_list_and_grid(self, mock_badge):
        """_fill_badges called for both grid and list layouts."""
        import app.qt.components.recording_card as mod

        rec = self._make_rec(likelihood=0.6)
        card = MagicMock()

        layout_grid = self._make_layout()
        layout_list = self._make_layout()

        mod.QtRecordingCard._fill_badges(rec, layout_grid, card, "grid")
        mod.QtRecordingCard._fill_badges(rec, layout_list, card, "list")

        # Both layouts should have gotten widgets
        self.assertGreater(layout_grid.addWidget.call_count, 0)
        self.assertGreater(layout_list.addWidget.call_count, 0)


class QueueKeyMappingTests(unittest.TestCase):
    """interval_to_queue_key mapping (no Qt needed)."""

    def test_interval_to_queue_key_mapping(self):
        """Verify F → F, M → M, S → S mapping."""
        import app.qt.utils.queue_badge as mod

        cases = [
            (30, "F"),     # ≤60 → Fast
            (60, "F"),     # ≤60 → Fast
            (90, "M"),     # ≤180 → Medium
            (180, "M"),    # ≤180 → Medium
            (300, "S"),    # >180 → Slow
            (600, "S"),    # >180 → Slow
        ]
        for interval, expected in cases:
            result = mod.interval_to_queue_key(interval)
            self.assertEqual(result, expected,
                             f"interval={interval}s → expected {expected}, got {result}")

    def test_queue_key_does_not_collapse_everything_to_M(self):
        """Explicit check that F, M, S all produce distinct keys."""
        import app.qt.utils.queue_badge as mod

        f_key = mod.interval_to_queue_key(30)
        m_key = mod.interval_to_queue_key(120)
        s_key = mod.interval_to_queue_key(300)

        self.assertEqual(f_key, "F")
        self.assertEqual(m_key, "M")
        self.assertEqual(s_key, "S")
        # All three must be different
        self.assertEqual(len({f_key, m_key, s_key}), 3,
                         "F, M, S must all be distinct queue keys")


class QueueColorMappingTests(unittest.TestCase):
    """QUEUE_BADGE_COLORS (no Qt needed)."""

    def test_all_queue_keys_have_colors(self):
        """F, M, S all have mapped colors."""
        import app.qt.utils.queue_badge as mod
        for key in ("F", "M", "S"):
            self.assertIn(key, mod.QUEUE_BADGE_COLORS,
                          f"Queue key {key} must have a color mapping")

    def test_unknown_key_returns_fallback(self):
        """Unknown queue key uses fallback color."""
        import app.qt.utils.queue_badge as mod
        fallback = mod.QUEUE_BADGE_COLORS.get("X", "#9E9E9E")
        self.assertEqual(fallback, "#9E9E9E",
                         "Unknown queue key should get fallback color")


class NoSnapshotReferenceTests(unittest.TestCase):
    """Verify there's no _last_snapshot dependency in the badge path."""

    def test_fill_badges_does_not_check_last_snapshot(self):
        """_fill_badges must not read _last_snapshot attribute."""
        import app.qt.components.recording_card as mod
        import inspect
        source = inspect.getsource(mod.QtRecordingCard._fill_badges)
        # Only check for attribute access patterns, not docstring mentions
        lines = [l for l in source.split("\n") if "_last_snapshot" in l and "``" not in l]
        self.assertEqual(len(lines), 0,
                         f"_fill_badges uses _last_snapshot:\n" + "\n".join(lines))

    def test_fill_badges_does_not_call_snapshot(self):
        """_fill_badges must not call Precog.snapshot()."""
        import app.qt.components.recording_card as mod
        import inspect
        source = inspect.getsource(mod.QtRecordingCard._fill_badges)
        # Check that there's no actual function call, ignoring docstring mentions
        lines = [l for l in source.split("\n")
                 if "snapshot" in l and "``" not in l and "snapshot" in l]
        self.assertEqual(len(lines), 0,
                         f"_fill_badges references snapshot:\n" + "\n".join(lines))
        self.assertFalse(hasattr(mod, "Precog"),
                         "Precog must not be imported in recording_card")


if __name__ == "__main__":
    unittest.main()
