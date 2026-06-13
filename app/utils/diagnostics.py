"""Lightweight runtime diagnostics for memory growth investigation.

Provides helpers to snapshot observable state of key application components
so the user can correlate suspect accumulation with log timestamps.

=== Where diagnostics appear in logs ===

Every 5 minutes (configurable via STREAMCAP_DIAGNOSTICS_INTERVAL env var,
in seconds), a combined report is logged at INFO level under the
``app.qt.main_window`` logger.

Example log lines::

    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN - === DIAGNOSTICS ===
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   language_manager: {'observer_count': 3}
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   event_bus: {'topics': {'language_changed': 5, 'app_closing': 1}, 'total_subscribers': 6, 'topic_count': 2}
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   predictor_store: {'db_path': '...', 'db_exists': True}

Additionally, when the Stats view loads predictor data:

    2026-06-13 12:05:00.000 | INFO     | app.core.recording.predictor_metrics:_load_records_after:NNN - [DIAG] PredictorMetricsStore._load_records_after: 142 rows, 28400 est. payload bytes
    2026-06-13 12:05:00.123 | INFO     | app.core.recording.predictor_metrics:summarize:NNN - [DIAG] PredictorMetricsStore.summarize loaded 142 records in 0.123s

=== What to watch ===

- ``language_manager.observer_count``: should stay small and stable.
  Each LiveStreamRecorder adds itself as an observer. If this count grows
  without bound, observer cleanup is missing (suspect #1).

- ``event_bus.topics`` and ``event_bus.total_subscribers``: should be
  bounded and stable. Pages that are re-created (e.g. on language change)
  subscribe again without unsubscribing the old instance (suspect #2).

- ``asyncio.total_tasks``: should be bounded. A steady upward trend
  suggests orphaned coroutines (suspect #4 — check cycle accumulation).

- ``gc.gen0`` / ``gen1`` / ``gen2``: generation counts since last collection.
  Spikes, especially sustained high gen2 counts, indicate objects surviving
  into old generation — a leakage signal (suspect #5 — predictor retention).

- predictor_metrics timing/bytes: a sudden spike in rows or payload bytes
  when opening the Stats view would confirm the RAM-spike hypothesis
  (suspect #3).
"""

from __future__ import annotations

import asyncio
import gc
from typing import TYPE_CHECKING

# TEMP-DIAG: marker constant for temporary diagnostic instrumentation.
# Search for TEMP_DIAG_TAG across the codebase to find all locations
# that should be cleaned up after the predictive queue investigation.
# Remove when the "too many streams reaching medium queue" issue is resolved.
TEMP_DIAG_TAG = "  # TEMP-DIAG"

if TYPE_CHECKING:
    from app.core.config.language_manager import LanguageManager
    from app.core.recording.predictor_metrics import PredictorMetricsStore
    from app.event_bus import EventBus


def collect_report(
    event_bus: EventBus,
    language_manager: LanguageManager,
    predictor_store: PredictorMetricsStore | None = None,
) -> dict:
    """Return a combined diagnostics snapshot.

    This is meant to be called at a regular interval (e.g. every 5 minutes)
    so the user can spot growth in observer/subscriber counts over time.
    """
    return {
        "language_manager": _language_manager_report(language_manager),
        "event_bus": _event_bus_report(event_bus),
        "predictor_store": _predictor_store_report(predictor_store) if predictor_store else None,
        "asyncio": _asyncio_report(),
        "gc": _gc_report(),
    }


def _language_manager_report(lm: LanguageManager) -> dict:
    return {"observer_count": lm.observer_count}


def _event_bus_report(eb: EventBus) -> dict:
    return eb.diagnostic_report()


def _predictor_store_report(store: PredictorMetricsStore) -> dict:
    return {
        "db_path": str(store.db_path),
        "db_exists": store.db_path.exists(),
    }


def _asyncio_report() -> dict:
    """Return lightweight asyncio task metrics.

    Returns total number of tasks known to the running event loop.
    Safe to call from any context — returns empty dict if no loop.
    """
    try:
        tasks = asyncio.all_tasks()
        pending = sum(1 for t in tasks if not t.done())
        return {
            "total_tasks": len(tasks),
            "pending_tasks": pending,
        }
    except RuntimeError:
        return {}


def _gc_report() -> dict:
    """Return lightweight GC pressure metrics.

    Uses gc.get_count() which returns (gen0, gen1, gen2) counts of
    objects in each generation since the last collection.  This is
    O(1) and safe for production — no full object scan.

    A sustained rise in gen2 indicates objects surviving into old
    generation without being collected.
    """
    g0, g1, g2 = gc.get_count()
    return {
        "gen0": g0,
        "gen1": g1,
        "gen2": g2,
    }
