from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...models.recording.recording_model import Recording
from ...utils.utils import is_time_interval_exceeded
from .history_manager import HistoryManager
from .recording_state_logic import RecordingStateLogic


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


@dataclass(frozen=True)
class PrecogSnapshot:
    """Unified snapshot of a recording's predictive state at a point in time."""

    likelihood: float
    confidence: str
    forecast_details: dict[str, Any]
    reason_key: str
    adjusted_interval: int
    queue_key: str
    should_check: bool
    time_state: dict[str, Any]
    is_stale: bool
    priority_score: float
    consistency_score: float


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
        range_str = f"{first_h:02d}:00-{end_h:02d}:00"

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
    def snapshot(recording: Recording, now: datetime | None = None) -> PrecogSnapshot:
        """Return a unified snapshot of predictive state for *recording* at *now*.

        Core values (forecast, adjusted_interval) are computed once and shared
        across derived fields — avoids the 4× get_forecast_details and 2×
        get_adjusted_interval that calling predict() + decide_queue() would
        produce independently.
        """
        now = now or datetime.now()
        forecast = HistoryManager.get_forecast_details(recording, now=now)
        base_interval = getattr(recording, "loop_time_seconds", None) or Precog.DEFAULT_BASE_INTERVAL

        adjusted_interval = HistoryManager.get_adjusted_interval(recording, base_interval)
        adjusted_interval = Precog._apply_favorite_cap(adjusted_interval, recording)

        return PrecogSnapshot(
            likelihood=forecast["score"],
            confidence=forecast["confidence"],
            forecast_details=forecast,
            reason_key=forecast.get("reason_key", ""),
            adjusted_interval=adjusted_interval,
            queue_key=Precog.interval_to_queue_key(adjusted_interval),
            should_check=is_time_interval_exceeded(
                getattr(recording, "detection_time", None),
                adjusted_interval,
                now,
            ),
            time_state=Precog.time_state(recording, now=now),
            is_stale=RecordingStateLogic.is_stale(recording, now=now),
            priority_score=getattr(recording, "priority_score", 0.0),
            consistency_score=getattr(recording, "consistency_score", 0.0),
        )

    @staticmethod
    def interval_to_queue_key(interval_seconds: int) -> str:
        """Canonical queue-key rule: map an interval in seconds to F (fast), M (medium), S (slow)."""
        if interval_seconds <= 60:
            return "F"
        if interval_seconds <= 180:
            return "M"
        return "S"

    @staticmethod
    def _apply_favorite_cap(adjusted_interval: int, recording: Recording) -> int:
        """Cap adjusted interval at 180s for favorite recordings."""
        if getattr(recording, "is_favorite", False) and adjusted_interval > 180:
            return 180
        return adjusted_interval

    @staticmethod
    def stable_queue_key(recording: Recording) -> str:
        """Stable queue key for UI badge — base (configured) interval only, no jitter.

        The old badge path used *loop_time_seconds* or 60 directly without
        adjustment/jitter.  This restores that semantics so the badge never
        flickers due to operational jitter.
        """
        base = getattr(recording, "loop_time_seconds", None)
        if base is None:
            base = 60  # legacy UI badge default
        return Precog.interval_to_queue_key(base)

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
        adjusted_interval = Precog._apply_favorite_cap(adjusted_interval, recording)

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
