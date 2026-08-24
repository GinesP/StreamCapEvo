"""
Focalised tests for the shared queue-badge helper.

Guards the F/M/S rule used by both the recordings list delegate and the
recording card against divergence from the canonical Precog.interval_to_queue_key.
"""

import unittest

from app.core.recording.precog import Precog
from app.qt.utils.queue_badge import (
    QUEUE_BADGE_COLORS,
    QUEUE_BADGE_FALLBACK_COLOR,
    interval_to_queue_key,
    queue_badge_color,
)


class IntervalToQueueKeyTests(unittest.TestCase):
    def test_none_falls_back_to_medium(self):
        self.assertEqual(interval_to_queue_key(None), "M")

    def test_boundaries(self):
        self.assertEqual(interval_to_queue_key(60), "F")
        self.assertEqual(interval_to_queue_key(180), "M")
        self.assertEqual(interval_to_queue_key(181), "S")

    def test_matches_precog_canonical_rule(self):
        for interval in (0, 30, 60, 90, 180, 181, 300, 600, 1000):
            self.assertEqual(
                interval_to_queue_key(interval),
                Precog.interval_to_queue_key(interval),
                f"diverges from Precog at interval={interval}",
            )


class QueueBadgeColorTests(unittest.TestCase):
    def test_known_keys_have_colors(self):
        for key in ("F", "M", "S"):
            self.assertIn(key, QUEUE_BADGE_COLORS)

    def test_unknown_key_uses_fallback(self):
        self.assertEqual(queue_badge_color("X"), QUEUE_BADGE_FALLBACK_COLOR)

    def test_known_key_color(self):
        self.assertEqual(queue_badge_color("M"), QUEUE_BADGE_COLORS["M"])


if __name__ == "__main__":
    unittest.main()
