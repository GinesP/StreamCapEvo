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
    def _cluster_hours(hours: list[int], max_gap: int = 4) -> list[list[int]]:
        """Agrupa horas donde el gap entre consecutivas <= max_gap (default: 4h).

        Replica fielmente ``HistoryManager._cluster_hours`` para eliminar
        la dependencia residual desde la UI.
        """
        if not hours:
            return []
        sorted_h = sorted(set(hours))
        clusters: list[list[int]] = [[sorted_h[0]]]
        for h in sorted_h[1:]:
            if h - clusters[-1][-1] > max_gap:
                clusters.append([])
            clusters[-1].append(h)
        return clusters

    @staticmethod
    def time_state(recording: Recording, now: datetime | None = None) -> dict[str, Any]:
        """Devuelve el estado temporal de UI para *recording* en el instante *now*.

        El dict tiene el mismo shape que el que antes producía
        ``_get_forecast_time_info`` en ``live_forecast_dialog.py``:

        - ``state``: one of ``none``, ``live_range``, ``expected``, ``delayed``,
          ``countdown``, ``upcoming``
        - ``text``: texto auxiliar (rango de horas o hora puntual)
        - ``text_key``: clave de traducción (si aplica)
        - ``color``: color hex del estado
        - ``prefix``: prefijo emoji (si aplica)
        - ``args``: dict de argumentos de formato (si aplica)
        """
        now = now or datetime.now()
        current_minutes = now.hour * 60 + now.minute
        day_str = str(now.weekday())
        intervals = recording.historical_intervals or {}
        active_hours = intervals.get(day_str, [])

        if not active_hours:
            return {"state": "none", "text": "", "color": ""}

        clusters = Precog._cluster_hours(active_hours)

        # Find the cluster containing the current hour
        current_cluster = next((c for c in clusters if now.hour in c), None)

        # Find the next future hour to compute display_hour
        future_hours = [h for h in active_hours if h * 60 >= current_minutes]
        display_hour = min(future_hours) if future_hours else min(active_hours)

        is_live = recording.is_live

        # Only use the cluster that contains the display_hour for a consistent state
        display_cluster = next((c for c in clusters if display_hour in c), clusters[0])
        first_h = display_cluster[0]
        last_h = display_cluster[-1]
        end_h = (last_h + 1) % 24
        range_str = f"{first_h:02d}:00‑{end_h:02d}:00"

        # Currently in the display cluster's window
        if current_cluster is display_cluster and now.hour in display_cluster:
            if is_live:
                return {
                    "state": "live_range",
                    "text_key": "live_forecast_dialog.status_live",
                    "text": range_str,
                    "color": "#E53935",
                    "prefix": "🔴 ",
                }
            minutes_into = (now.hour - first_h) * 60 + now.minute
            if minutes_into <= 15:
                return {
                    "state": "expected",
                    "text_key": "live_forecast_dialog.status_expected",
                    "text": "",
                    "color": "#FF9800",
                    "prefix": "⏳ ",
                }
            return {
                "state": "delayed",
                "text_key": "live_forecast_dialog.status_delayed",
                "text": "",
                "color": "#FF5252",
                "prefix": "⚠ ",
            }

        # Countdown: display_hour is the next hour
        if display_hour == (now.hour + 1) % 24:
            minutes_left = 60 - now.minute
            return {
                "state": "countdown",
                "text_key": "live_forecast_dialog.status_countdown",
                "color": "#4CAF50",
                "prefix": "⏱ ",
                "args": {"minutes": minutes_left},
            }

        # Far from display window
        return {"state": "upcoming", "text": f"{first_h:02d}:00", "color": ""}

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
