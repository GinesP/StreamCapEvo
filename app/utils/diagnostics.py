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
import time
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

try:
    import tracemalloc
except Exception:  # pragma: no cover - platform/runtime dependent
    tracemalloc = None

from app.models.recording.recording_status_model import RecordingStatus

# TEMP-DIAG: marker constant for temporary diagnostic instrumentation.
# Search for TEMP_DIAG_TAG across the codebase to find all locations
# that should be cleaned up after the predictive queue investigation.
# Remove when the "too many streams reaching medium queue" issue is resolved.
TEMP_DIAG_TAG = "  # TEMP-DIAG"
_TRACEMALLOC_FRAME_DEPTH = 5
_TRACEMALLOC_TOP_N = 5

if TYPE_CHECKING:
    from app.core.config.language_manager import LanguageManager
    from app.core.recording.record_manager import RecordingManager
    from app.core.recording.predictor_metrics import PredictorMetricsStore
    from app.core.runtime.process_manager import AsyncProcessManager
    from app.event_bus import EventBus


def collect_report(
    event_bus: EventBus,
    language_manager: LanguageManager,
    record_manager: RecordingManager | None = None,
    predictor_store: PredictorMetricsStore | None = None,
    process_manager: AsyncProcessManager | None = None,
) -> dict:
    """Return a combined diagnostics snapshot.

    This is meant to be called at a regular interval (e.g. every 5 minutes)
    so the user can spot growth in observer/subscriber counts over time.
    """
    return {
        "process_memory": _process_memory_report(process_manager=process_manager),
        "python_allocations": _tracemalloc_report(),
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


def _process_memory_report(process_manager: "AsyncProcessManager | None" = None) -> dict:
    """Return current process RSS using psutil.

    psutil is already a project dependency, and Process.memory_info().rss is
    a cheap OS-backed call that reflects real resident memory better than GC
    counters alone.
    """
    try:
        rss_bytes = psutil.Process().memory_info().rss
    except Exception as exc:
        return {"available": False, "error": str(exc)}

    child_processes = _child_processes_report(process_manager)
    child_rss_bytes = child_processes.get("rss_bytes", 0)

    return {
        "available": True,
        "rss_bytes": rss_bytes,
        "rss_mb": round(rss_bytes / (1024 * 1024), 1),
        "child_processes": child_processes,
        "combined_rss_bytes": rss_bytes + child_rss_bytes,
        "combined_rss_mb": round((rss_bytes + child_rss_bytes) / (1024 * 1024), 1),
    }


def _child_processes_report(process_manager: "AsyncProcessManager | None") -> dict:
    if process_manager is None:
        return {"known_count": 0, "active_count": 0, "rss_bytes": 0, "rss_mb": 0.0, "by_name": {}, "active": []}

    by_name: dict[str, dict] = {}
    active = []
    active_count = 0
    total_rss_bytes = 0

    for process in list(getattr(process_manager, "ffmpeg_processes", [])):
        pid = getattr(process, "pid", None)
        returncode = getattr(process, "returncode", None)
        if pid is None or returncode is not None:
            continue

        active_count += 1
        try:
            proc = psutil.Process(pid)
            proc_name = proc.name()
            rss_bytes = proc.memory_info().rss
        except Exception as exc:
            active.append({"pid": pid, "name": "unknown", "available": False, "error": str(exc)})
            continue

        total_rss_bytes += rss_bytes
        active.append(
            {
                "pid": pid,
                "name": proc_name,
                "rss_mb": round(rss_bytes / (1024 * 1024), 1),
            }
        )
        bucket = by_name.setdefault(proc_name, {"count": 0, "rss_bytes": 0})
        bucket["count"] += 1
        bucket["rss_bytes"] += rss_bytes

    summarized_by_name = {
        name: {
            "count": info["count"],
            "rss_bytes": info["rss_bytes"],
            "rss_mb": round(info["rss_bytes"] / (1024 * 1024), 1),
        }
        for name, info in sorted(by_name.items())
    }
    active.sort(key=lambda item: item.get("rss_mb", -1), reverse=True)

    return {
        "known_count": len(getattr(process_manager, "ffmpeg_processes", [])),
        "active_count": active_count,
        "rss_bytes": total_rss_bytes,
        "rss_mb": round(total_rss_bytes / (1024 * 1024), 1),
        "by_name": summarized_by_name,
        "active": active,
    }


def _tracemalloc_report(top_n: int = _TRACEMALLOC_TOP_N) -> dict:
    """Return a bounded tracemalloc summary grouped by allocating file."""
    if tracemalloc is None:
        return {"available": False, "enabled": False, "reason": "unavailable"}

    started_now = False
    try:
        if not tracemalloc.is_tracing():
            tracemalloc.start(_TRACEMALLOC_FRAME_DEPTH)
            started_now = True

        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics("filename")
    except Exception as exc:
        return {"available": False, "enabled": False, "error": str(exc)}

    top_stats = stats[:top_n]
    top_total = sum(stat.size for stat in top_stats)
    total_traced = sum(stat.size for stat in stats)

    return {
        "available": True,
        "enabled": True,
        "started_now": started_now,
        "traceback_limit": tracemalloc.get_traceback_limit(),
        "top": [
            {
                "file": _format_tracemalloc_filename(stat.traceback[0].filename),
                "size_bytes": stat.size,
                "size_mb": round(stat.size / (1024 * 1024), 3),
                "count": stat.count,
            }
            for stat in top_stats
        ],
        "top_total_bytes": top_total,
        "top_total_mb": round(top_total / (1024 * 1024), 3),
        "other_bytes": max(total_traced - top_total, 0),
        "other_mb": round(max(total_traced - top_total, 0) / (1024 * 1024), 3),
        "total_traced_bytes": total_traced,
        "total_traced_mb": round(total_traced / (1024 * 1024), 3),
    }


def _format_tracemalloc_filename(filename: str) -> str:
    parts = Path(filename).parts
    for anchor in ("app", "tests"):
        if anchor in parts:
            return Path(*parts[parts.index(anchor) :]).as_posix()
    if len(parts) <= 3:
        return Path(filename).as_posix()
    return Path(*parts[-3:]).as_posix()


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
    active_recorder_details = _active_recorder_details(getattr(manager, "active_recorders", {}))

    return {
        "recording_count": len(recordings),
        "active_recorders": len(getattr(manager, "active_recorders", {})),
        "active_recorder_details": active_recorder_details,
        "predictor_dispatched_recordings": len(predictor_dispatched_ids & recording_ids),
        "predictor_dispatched_stale": len(predictor_dispatched_ids - recording_ids),
        "predictor_last_offline_sticky_recordings": len(predictor_last_offline_ids & recording_ids),
        "predictor_last_offline_stale": len(predictor_last_offline_ids - recording_ids),
        "checking": checking_count,
        "status_checking": status_checking_count,
    }


def _active_recorder_details(active_recorders: dict) -> list[dict]:
    details = []
    now = time.time()
    for rec_id, recorder in active_recorders.items():
        recording = getattr(recorder, "recording", None)
        started_at = getattr(recorder, "recording_start_time", 0) or 0
        details.append(
            {
                "rec_id": rec_id,
                "streamer": getattr(recording, "streamer_name", None),
                "status": getattr(recording, "status_info", None),
                "output": "direct" if getattr(recorder, "direct_downloader", None) else "ffmpeg",
                "duration_s": round(now - started_at, 1) if started_at > 0 else None,
            }
        )
    return sorted(details, key=lambda item: item["rec_id"])


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
