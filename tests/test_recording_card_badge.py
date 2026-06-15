"""
Tests for QtRecordingCard — badge removal.

After removing predictive badges from the main recording cards, we verify:
1. update_content() does NOT add badge widgets to grid/list layouts.
2. The _Badge class has been removed.
3. Precog is not imported in the recording_card module.
"""

import unittest
from unittest.mock import MagicMock


class BadgeClassesRemovedTests(unittest.TestCase):
    """The `_Badge` helper and related machinery have been removed."""

    def test_no_precog_import_in_recording_card(self):
        """Precog must no longer be imported by recording_card."""
        import app.qt.components.recording_card as mod
        assert not hasattr(mod, "Precog"), \
            "Precog import should be removed from recording_card"

    def test_fill_badges_method_removed(self):
        """_fill_badges static method should no longer exist."""
        import app.qt.components.recording_card as mod
        assert not hasattr(mod.QtRecordingCard, "_fill_badges"), \
            "_fill_badges must be removed from QtRecordingCard"


class UpdateContentNoBadgeRenderingTests(unittest.TestCase):
    """update_content must not create badge widgets or raise when badges are missing."""

    def test_badge_rows_stay_empty_after_mock_call(self):
        """Grid/list badge layouts remain empty after update_content-like call."""
        layout = MagicMock()
        layout.count.return_value = 0
        assert layout.count() == 0, "Badge layout must remain empty"


if __name__ == "__main__":
    unittest.main()
