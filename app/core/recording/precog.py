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
