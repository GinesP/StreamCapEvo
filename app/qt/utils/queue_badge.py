"""
Shared, UI-safe queue-badge helpers.

Centralises the F/M/S queue-key rule used by the recordings list delegate and
the recording card. This module intentionally imports NO Precog logic so the UI
layer stays free of prediction/snapshot dependencies.

The key rule mirrors ``Precog.interval_to_queue_key``:
  <= 60s   -> "F" (fast)
  <= 180s  -> "M" (medium)
  > 180s   -> "S" (slow)
A ``None`` interval falls back to "M" (legacy UI badge default).
"""

from __future__ import annotations

from app.qt.themes.theme import QUEUE_COLORS

QUEUE_BADGE_COLORS: dict[str, str] = {
    "F": QUEUE_COLORS["fast"],
    "M": QUEUE_COLORS["medium"],
    "S": QUEUE_COLORS["slow"],
}

QUEUE_BADGE_FALLBACK_COLOR = "#9E9E9E"


def interval_to_queue_key(interval_seconds: int | None) -> str:
    """Map an interval in seconds to F/M/S (None falls back to M)."""
    if interval_seconds is None:
        return "M"
    if interval_seconds <= 60:
        return "F"
    if interval_seconds <= 180:
        return "M"
    return "S"


def queue_badge_color(key: str) -> str:
    """Return the badge colour for a queue key, falling back to neutral grey."""
    return QUEUE_BADGE_COLORS.get(key, QUEUE_BADGE_FALLBACK_COLOR)
