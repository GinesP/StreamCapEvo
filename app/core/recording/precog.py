from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .history_manager import HistoryManager
from ...models.recording.recording_model import Recording
from ...utils.utils import is_time_interval_exceeded


@dataclass(frozen=True)
class PrecogPrediction:
    """Unified predictive snapshot for a streamer."""

    likelihood: float
    confidence: str
    priority_score: float
    consistency_score: float
    adjusted_interval: int
    forecast_details: dict[str, Any]


@dataclass(frozen=True)
class PrecogDecision:
    """Minimal operational decision for one polling cycle."""

    should_check: bool
    queue_key: str
    adjusted_interval: int
    likelihood: float
    reason: str


class Precog:
    """Simple facade over the current predictive logic."""

    DEFAULT_BASE_INTERVAL = 300

    @staticmethod
    def predict(recording: Recording, now: datetime | None = None) -> PrecogPrediction:
        """Return a unified predictive snapshot for *recording* at *now*."""
        now = now or datetime.now()
        forecast = HistoryManager.get_forecast_details(recording, now=now)

        base_interval = getattr(recording, "loop_time_seconds", None) or Precog.DEFAULT_BASE_INTERVAL
        adjusted_interval = HistoryManager.get_adjusted_interval(recording, base_interval)

        return PrecogPrediction(
            likelihood=forecast["score"],
            confidence=forecast["confidence"],
            priority_score=getattr(recording, "priority_score", 0.0),
            consistency_score=getattr(recording, "consistency_score", 0.0),
            adjusted_interval=adjusted_interval,
            forecast_details=forecast,
        )

    @staticmethod
    def time_state(recording: Recording, now: datetime | None = None) -> dict[str, Any]:
        """Return the time-state payload used by forecast UI consumers."""
        now = now or datetime.now()
        current_minutes = now.hour * 60 + now.minute
        day_str = str(now.weekday())
        intervals = recording.historical_intervals or {}
        active_hours = intervals.get(day_str, [])

        if not active_hours:
            return {"state": "none", "text": "", "text_key": "", "color": ""}

        future_hours = [h for h in active_hours if h * 60 >= current_minutes]
        display_hour = min(future_hours) if future_hours else min(active_hours)

        clusters, display_cluster, first_h, last_h, end_h = HistoryManager._cluster_info(active_hours, display_hour)
        current_cluster = next((c for c in clusters if now.hour in c), None)
        range_str = f"{first_h:02d}:00‑{end_h:02d}:00"

        is_live = recording.is_live

        if current_cluster is display_cluster and now.hour in display_cluster:
            if is_live:
                return {
                    "state": "live_range",
                    "text_key": "live_forecast_dialog.status_live",
                    "text": range_str,
                    "color": "#E53935",
                    "prefix": "",
                }
            minutes_into = (now.hour - first_h) * 60 + now.minute
            if minutes_into <= 15:
                return {
                    "state": "expected",
                    "text_key": "live_forecast_dialog.status_expected",
                    "text": "",
                    "color": "#FF9800",
                    "prefix": "",
                }
            return {
                "state": "delayed",
                "text_key": "live_forecast_dialog.status_delayed",
                "text": "",
                "color": "#FF5252",
                "prefix": "",
            }

        if display_hour == (now.hour + 1) % 24:
            minutes_left = 60 - now.minute
            return {
                "state": "countdown",
                "text_key": "live_forecast_dialog.status_countdown",
                "color": "#4CAF50",
                "prefix": "",
                "args": {"minutes": minutes_left},
            }

        return {"state": "upcoming", "text": f"{first_h:02d}:00", "text_key": "", "color": ""}

    @staticmethod
    def interval_to_queue_key(interval_seconds: int) -> str:
        """Canonical queue-key rule: map an interval in seconds to F (fast), M (medium), S (slow)."""
        if interval_seconds <= 60:
            return "F"
        if interval_seconds <= 180:
            return "M"
        return "S"

    @staticmethod
    def decide_queue(
        recording: Recording, base_interval: int = DEFAULT_BASE_INTERVAL,
        now: datetime | None = None,
    ) -> PrecogDecision:
        """Return the minimal queue decision for *recording* at *now*."""
        now = now or datetime.now()
        forecast = HistoryManager.get_forecast_details(recording, now=now)
        likelihood = forecast["score"]
        adjusted_interval = HistoryManager.get_adjusted_interval(recording, base_interval)

        # Favorites never go to slow queue (>180s)
        if getattr(recording, "is_favorite", False) and adjusted_interval > 180:
            adjusted_interval = 180

        queue_key = Precog.interval_to_queue_key(adjusted_interval)

        should_check = is_time_interval_exceeded(
            getattr(recording, "detection_time", None),
            adjusted_interval,
            now,
        )

        return PrecogDecision(
            should_check=should_check,
            queue_key=queue_key,
            adjusted_interval=adjusted_interval,
            likelihood=likelihood,
            reason=forecast.get("reason_key", ""),
        )
