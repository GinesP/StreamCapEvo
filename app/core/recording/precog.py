from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.recording.history_manager import HistoryManager
from app.models.recording.recording_model import Recording


@dataclass(frozen=True)
class PrecogPrediction:
    """Snapshot unificado del estado predictivo de un streamer."""

    likelihood: float
    confidence: str
    priority_score: float
    consistency_score: float
    adjusted_interval: int
    forecast_details: dict[str, Any]


@dataclass(frozen=True)
class PrecogDecision:
    """Decisión operativa mínima para un ciclo de polling."""

    should_check: bool
    queue_key: str
    adjusted_interval: int
    likelihood: float
    reason: str


class Precog:
    """Fachada simple sobre la lógica predictiva actual.

    Precog no reemplaza el algoritmo interno; solo lo reúne en un punto único
    para lectura. Las mutaciones de datos históricos siguen gestionándose desde
    ``Recording`` / ``HistoryManager``.
    """

    DEFAULT_BASE_INTERVAL = 300

    @staticmethod
    def predict(recording: Recording, now: datetime | None = None) -> PrecogPrediction:
        """Devuelve un snapshot predictivo unificado para *recording* en el instante *now*.

        El snapshot incluye ``likelihood``, ``confidence``, ``priority_score``,
        ``consistency_score``, ``adjusted_interval`` y ``forecast_details``,
        calculados delegando en la lógica existente de ``HistoryManager``.
        """
        now = now or datetime.now()
        forecast = HistoryManager.get_forecast_details(recording, now=now)

        # Usa el intervalo base del recording si está disponible; si no, el default del sistema.
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
    def _should_check(detection_time, interval_seconds: int, now: datetime) -> bool:
        """Replica la lógica de ``utils.is_time_interval_exceeded`` usando un *now* explícito."""
        now_time = now.time()
        if not detection_time or detection_time > now_time:
            return True
        last_dt = datetime.combine(datetime.today(), detection_time)
        now_dt = datetime.combine(datetime.today(), now_time)
        return (now_dt - last_dt).total_seconds() > interval_seconds

    @staticmethod
    def decide_queue(recording: Recording, base_interval: int = DEFAULT_BASE_INTERVAL, now: datetime | None = None) -> PrecogDecision:
        """Devuelve la decisión operativa mínima para *recording* en el instante *now*.

        Encapsula el cálculo de ``likelihood``, ``adjusted_interval``,
        ``queue_key`` (F/M/S) y ``should_check``, preservando los thresholds
        y comportamientos actuales de ``record_manager.py``.
        """
        now = now or datetime.now()
        forecast = HistoryManager.get_forecast_details(recording, now=now)
        likelihood = forecast["score"]
        adjusted_interval = HistoryManager.get_adjusted_interval(recording, base_interval)

        # Favorites never go to slow queue (>180s)
        if getattr(recording, "is_favorite", False) and adjusted_interval > 180:
            adjusted_interval = 180

        # Queue categorization (1:1 con record_manager.py)
        if adjusted_interval <= 60:
            queue_key = "F"
        elif adjusted_interval <= 180:
            queue_key = "M"
        else:
            queue_key = "S"

        should_check = Precog._should_check(
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
