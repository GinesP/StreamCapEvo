"""Lightweight runtime diagnostics for memory growth investigation.

Provides helpers to snapshot observable state of key application components
so the user can correlate suspect accumulation with log timestamps.

=== Where diagnostics appear in logs ===

Every 5 minutes (configurable via STREAMCAP_DIAGNOSTICS_INTERVAL env var,
in seconds), a combined report is logged at INFO level under the
``app.qt.main_window`` logger.

Example log lines::

    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN - === DIAGNOSTICS ===
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   process_memory: {'available': True, 'rss_bytes': 164626432, 'rss_mb': 157.0}
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   language_manager: {'observer_count': 3}
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   event_bus: {'topics': {'language_changed': 5, 'app_closing': 1}, 'total_subscribers': 6, 'topic_count': 2}
    2026-06-13 12:00:00.000 | INFO     | app.qt.main_window:_log_diagnostics:NNN -   record_manager: {'recording_count': 42, 'active_recorders': 1, 'predictor_dispatched_recordings': 3, 'predictor_dispatched_stale': 0, 'predictor_last_offline_sticky_recordings': 40, 'predictor_last_offline_stale': 0, 'checking': 3, 'status_checking': 3}
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

- ``process_memory.rss_mb``: real resident memory of the Python process.
  Normal oscillation is expected; what matters is when the baseline stops
  returning and begins ratcheting upward cycle after cycle.

- ``record_manager.active_recorders`` / ``predictor_dispatched_recordings`` /
  ``checking``: these should roughly track active work. If RSS starts
  climbing while one of these stops draining, that is a concrete trigger
  candidate.

- ``predictor_last_offline_sticky_recordings``: sticky per recording after an
  offline result, so it is retention context rather than an active-work
  signal.

- ``*_stale`` counters: predictor map entries whose IDs are no longer in the
  current recordings list. These are useful for spotting retention after
  recordings are deleted.

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

import psutil

from app.models.recording.recording_status_model import RecordingStatus

# TEMP-DIAG: marker constant for temporary diagnostic instrumentation.
# Search for TEMP_DIAG_TAG across the codebase to find all locations
# that should be cleaned up after the predictive queue investigation.
# Remove when the "too many streams reaching medium queue" issue is resolved.
TEMP_DIAG_TAG = "  # TEMP-DIAG"

if TYPE_CHECKING:
    from app.core.config.language_manager import LanguageManager
    from app.core.recording.record_manager import RecordingManager
    from app.core.recording.predictor_metrics import PredictorMetricsStore
    from app.event_bus import EventBus


def collect_report(
    event_bus: EventBus,
    language_manager: LanguageManager,
    record_manager: RecordingManager | None = None,
    predictor_store: PredictorMetricsStore | None = None,
) -> dict:
    """Return a combined diagnostics snapshot.

    This is meant to be called at a regular interval (e.g. every 5 minutes)
    so the user can spot growth in observer/subscriber counts over time.
    """
    return {
        "process_memory": _process_memory_report(),
        "language_manager": _language_manager_report(language_manager),
        "event_bus": _event_bus_report(event_bus),
        "record_manager": _record_manager_report(record_manager) if record_manager else None,
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


def _process_memory_report() -> dict:
    """Return current process RSS using psutil.

    psutil is already a project dependency, and Process.memory_info().rss is
    a cheap OS-backed call that reflects real resident memory better than GC
    counters alone.
    """
    try:
        rss_bytes = psutil.Process().memory_info().rss
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    return {
        "available": True,
        "rss_bytes": rss_bytes,
        "rss_mb": round(rss_bytes / (1024 * 1024), 1),
    }


def _record_manager_report(manager: "RecordingManager") -> dict:
    """Return lightweight counters that may expose sustained accumulation."""
    recordings = getattr(manager, "recordings", []) or []
    recording_ids = {
        rec_id
        for recording in recordings
        if (rec_id := getattr(recording, "rec_id", None))
    }
    checking_count = 0
    status_checking_count = 0
    for recording in recordings:
        if getattr(recording, "is_checking", False):
            checking_count += 1
        if getattr(recording, "status_info", None) == RecordingStatus.STATUS_CHECKING:
            status_checking_count += 1

    predictor_dispatched_ids = set(getattr(manager, "_predictor_dispatched_at", {}))
    predictor_last_offline_ids = set(getattr(manager, "_predictor_last_offline_result_at", {}))

    return {
        "recording_count": len(recordings),
        "active_recorders": len(getattr(manager, "active_recorders", {})),
        "predictor_dispatched_recordings": len(predictor_dispatched_ids & recording_ids),
        "predictor_dispatched_stale": len(predictor_dispatched_ids - recording_ids),
        "predictor_last_offline_sticky_recordings": len(predictor_last_offline_ids & recording_ids),
        "predictor_last_offline_stale": len(predictor_last_offline_ids - recording_ids),
        "checking": checking_count,
        "status_checking": status_checking_count,
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
