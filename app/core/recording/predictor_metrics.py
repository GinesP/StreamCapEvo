import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


def _utcnow() -> datetime:
    return datetime.utcnow()


def _pct(values: list[float], p: int) -> float | None:
    """Percentile of sorted values using linear interpolation."""
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = k - f
    if f + 1 < len(s):
        return round(s[f] + c * (s[f + 1] - s[f]), 3)
    return round(s[f], 3)


@dataclass(frozen=True)
class MetricsSummary:
    total_checks: int
    live_detections: int
    non_live_results: int
    offline_checks_without_near_live_followup: int
    offline_checks_with_near_live_followup: int
    live_detections_after_offline_check: int
    avg_detection_latency_seconds: float | None
    avg_lead_minutes_vs_interval: float | None
    latency_p50: float | None = None
    latency_p95: float | None = None
    latency_p99: float | None = None
    dispatch_p50: float | None = None
    dispatch_p95: float | None = None
    dispatch_fast: int = 0
    dispatch_medium: int = 0
    dispatch_slow: int = 0
    lives_fast: int = 0
    lives_medium: int = 0
    lives_slow: int = 0
    avg_likelihood_at_dispatch: float | None = None
    avg_likelihood_fast: float | None = None
    avg_likelihood_medium: float | None = None
    avg_likelihood_slow: float | None = None
    lh_fast_p50: float | None = None
    lh_medium_p50: float | None = None
    lh_slow_p50: float | None = None
    lh_slow_min: float | None = None
    lh_slow_max: float | None = None
    _lead_is_interval_artifact: bool = True

    def to_dict(self) -> dict:
        return {
            "total_checks": self.total_checks,
            "live_detections": self.live_detections,
            "non_live_results": self.non_live_results,
            "offline_checks_without_near_live_followup": self.offline_checks_without_near_live_followup,
            "offline_checks_with_near_live_followup": self.offline_checks_with_near_live_followup,
            "live_detections_after_offline_check": self.live_detections_after_offline_check,
            "avg_detection_latency_seconds": self.avg_detection_latency_seconds,
            "avg_lead_minutes_vs_interval": self.avg_lead_minutes_vs_interval,
            "latency_p50": self.latency_p50,
            "latency_p95": self.latency_p95,
            "latency_p99": self.latency_p99,
            "dispatch_p50": self.dispatch_p50,
            "dispatch_p95": self.dispatch_p95,
            "dispatch_fast": self.dispatch_fast,
            "dispatch_medium": self.dispatch_medium,
            "dispatch_slow": self.dispatch_slow,
            "lives_fast": self.lives_fast,
            "lives_medium": self.lives_medium,
            "lives_slow": self.lives_slow,
            "avg_likelihood_at_dispatch": self.avg_likelihood_at_dispatch,
            "avg_likelihood_fast": self.avg_likelihood_fast,
            "avg_likelihood_medium": self.avg_likelihood_medium,
            "avg_likelihood_slow": self.avg_likelihood_slow,
            "lh_fast_p50": self.lh_fast_p50,
            "lh_medium_p50": self.lh_medium_p50,
            "lh_slow_p50": self.lh_slow_p50,
            "lh_slow_min": self.lh_slow_min,
            "lh_slow_max": self.lh_slow_max,
            "note_lead_is_interval_artifact": self._lead_is_interval_artifact,
        }


# Default retention window for tuning metrics (not indefinite history).
DEFAULT_RETENTION_HOURS = 72

# Minimum minutes between purges to avoid SQLite cost on every write.
DEFAULT_PURGE_THROTTLE_MINUTES = 10


class PredictorMetricsStore:
    """SQLite-backed store for recent predictor tuning metrics.

    Records are kept only within a configurable rolling window (default 72h).
    Older rows are purged automatically with a throttle to avoid per-write cost.
    This is intended for operational tuning, not long-term historical analysis.
    """

    def __init__(
        self,
        file_path: str | Path,
        retention_hours: int = DEFAULT_RETENTION_HOURS,
        purge_throttle_minutes: int = DEFAULT_PURGE_THROTTLE_MINUTES,
    ):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._active_connections_lock = threading.Lock()
        self._active_connections: set[sqlite3.Connection] = set()
        self._interrupt_event = threading.Event()
        self.db_path = self._resolve_db_path(self.file_path)
        self.legacy_jsonl_path = (
            self.file_path if self.file_path.suffix.lower() == ".jsonl" else self.file_path.with_suffix(".jsonl")
        )
        self._retention_hours = max(1, int(retention_hours))
        self._purge_throttle = timedelta(minutes=max(1, int(purge_throttle_minutes)))
        self._last_purge_time: datetime | None = None
        self._init_db()
        self._migrate_legacy_jsonl_if_needed()

    @staticmethod
    def _resolve_db_path(file_path: Path) -> Path:
        if file_path.suffix.lower() == ".db":
            return file_path
        return file_path.with_suffix(".db")

    @staticmethod
    def _configure_db(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")

    @contextmanager
    def _connect(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
            self._configure_db(conn)
            with self._active_connections_lock:
                self._active_connections.add(conn)
            try:
                yield conn
            finally:
                with self._active_connections_lock:
                    self._active_connections.discard(conn)

    def interrupt_pending_operations(self) -> None:
        self._interrupt_event.set()
        with self._active_connections_lock:
            active_connections = list(self._active_connections)
        for conn in active_connections:
            try:
                conn.interrupt()
            except sqlite3.Error:
                continue

    def _raise_if_interrupted(self) -> None:
        if self._interrupt_event.is_set():
            raise sqlite3.OperationalError("interrupted")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS predictor_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    rec_id TEXT,
                    is_live INTEGER,
                    priority TEXT,
                    likelihood REAL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_predictor_metrics_timestamp ON predictor_metrics(timestamp)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictor_metrics_event_timestamp ON predictor_metrics(event, timestamp)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_predictor_metrics_rec_timestamp ON predictor_metrics(rec_id, timestamp)"
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS predictor_metrics_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
                """
            )
            conn.commit()

    def _migrate_legacy_jsonl_if_needed(self) -> None:
        if not self.legacy_jsonl_path.exists():
            return
        source_key = f"legacy_jsonl_migrated::{self.legacy_jsonl_path.resolve()}"
        with self._connect() as conn:
            already_migrated = conn.execute(
                "SELECT value FROM predictor_metrics_meta WHERE key = ?",
                (source_key,),
            ).fetchone()
            if already_migrated:
                return

            row_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]
            if row_count:
                return

            imported_rows = 0
            batch = []
            with self.legacy_jsonl_path.open("r", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        item = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    payload = item.get("payload") or {}
                    batch.append(
                        (
                            item.get("timestamp") or _utcnow().isoformat(),
                            item.get("event") or "unknown",
                            payload.get("rec_id") or None,
                            self._to_db_bool(payload.get("is_live")),
                            payload.get("priority"),
                            self._extract_likelihood(payload),
                            json.dumps(payload, ensure_ascii=False),
                        )
                    )
                    if len(batch) >= 1000:
                        conn.executemany(
                            "INSERT INTO predictor_metrics (timestamp, event, rec_id, is_live, priority, likelihood, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            batch,
                        )
                        imported_rows += len(batch)
                        batch.clear()

            if batch:
                conn.executemany(
                    "INSERT INTO predictor_metrics (timestamp, event, rec_id, is_live, priority, likelihood, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                imported_rows += len(batch)
            conn.execute(
                "INSERT OR REPLACE INTO predictor_metrics_meta (key, value) VALUES (?, ?)",
                (source_key, str(imported_rows)),
            )
            conn.commit()

    @staticmethod
    def _to_db_bool(value) -> int | None:
        if value is None:
            return None
        return 1 if bool(value) else 0

    @staticmethod
    def _extract_likelihood(payload: dict) -> float | None:
        for key in ("likelihood", "likelihood_at_dispatch"):
            value = payload.get(key)
            if isinstance(value, (int, float)):
                return float(value)
        return None

    def _maybe_purge(self, conn: sqlite3.Connection) -> None:
        """Purge old records if throttle interval has passed."""
        now = _utcnow()
        if self._last_purge_time is not None and (now - self._last_purge_time) < self._purge_throttle:
            return
        cutoff = now - timedelta(hours=self._retention_hours)
        conn.execute(
            "DELETE FROM predictor_metrics WHERE timestamp < ?",
            (cutoff.isoformat(),),
        )
        conn.commit()
        self._last_purge_time = now

    def record_event(self, event_type: str, payload: dict) -> None:
        timestamp = _utcnow().isoformat()
        with self._lock:
            with self._connect() as conn:
                self._maybe_purge(conn)
                conn.execute(
                    "INSERT INTO predictor_metrics (timestamp, event, rec_id, is_live, priority, likelihood, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        timestamp,
                        event_type,
                        payload.get("rec_id") or None,
                        self._to_db_bool(payload.get("is_live")),
                        payload.get("priority"),
                        self._extract_likelihood(payload),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
                conn.commit()

    def summarize(self, lookback_hours: int = 72, near_live_minutes: int = 15) -> MetricsSummary:
        self._interrupt_event.clear()
        horizon_start = _utcnow() - timedelta(hours=max(1, int(lookback_hours)))
        records = self._load_records_after(horizon_start)
        results = [item for item in records if item.get("event") == "check_result"]
        dispatched = [item for item in records if item.get("event") == "check_dispatched"]

        total_checks = len(results)
        live_detections = sum(1 for item in results if bool(item.get("payload", {}).get("is_live")))
        non_live_results = total_checks - live_detections

        by_rec: dict[str, list[dict]] = {}
        for item in results:
            self._raise_if_interrupted()
            rec_id = str(item.get("payload", {}).get("rec_id") or "")
            if not rec_id:
                continue
            by_rec.setdefault(rec_id, []).append(item)

        offline_checks_without_near_live_followup = 0
        offline_checks_with_near_live_followup = 0
        live_detections_after_offline_check = 0
        detection_latencies = []
        lead_minutes = []
        near_live_delta = timedelta(minutes=max(1, int(near_live_minutes)))

        for events in by_rec.values():
            self._raise_if_interrupted()
            ordered = sorted(events, key=lambda item: item.get("timestamp", ""))
            for idx, current in enumerate(ordered):
                self._raise_if_interrupted()
                payload = current.get("payload", {})
                ts = self._parse_ts(current.get("timestamp"))
                if ts is None:
                    continue

                if payload.get("is_live"):
                    if idx > 0:
                        prev = ordered[idx - 1]
                        prev_payload = prev.get("payload", {})
                        prev_ts = self._parse_ts(prev.get("timestamp"))
                        if prev_ts and not prev_payload.get("is_live"):
                            latency = (ts - prev_ts).total_seconds()
                            if latency >= 0:
                                detection_latencies.append(latency)
                                live_detections_after_offline_check += 1
                    check_interval = payload.get("loop_time_seconds")
                    detection_latency_seconds = payload.get("detection_latency_seconds")
                    if isinstance(check_interval, (int, float)) and isinstance(detection_latency_seconds, (int, float)):
                        lead = (float(check_interval) - float(detection_latency_seconds)) / 60.0
                        lead_minutes.append(lead)
                    continue

                has_near_live = False
                for future in ordered[idx + 1 :]:
                    future_payload = future.get("payload", {})
                    if not future_payload.get("is_live"):
                        continue
                    future_ts = self._parse_ts(future.get("timestamp"))
                    if future_ts is None:
                        continue
                    if future_ts - ts <= near_live_delta:
                        has_near_live = True
                    break
                if has_near_live:
                    offline_checks_with_near_live_followup += 1
                else:
                    offline_checks_without_near_live_followup += 1

        dispatch_times: list[float] = []
        for item in results:
            self._raise_if_interrupted()
            dw = item.get("payload", {}).get("dispatch_wait_seconds")
            if isinstance(dw, (int, float)):
                dispatch_times.append(float(dw))

        # ---- Priority attribution: match each result to its dispatch ----
        disp_by_rec: dict[str, list[dict]] = {}
        for item in dispatched:
            self._raise_if_interrupted()
            rec_id = str(item.get("payload", {}).get("rec_id") or "")
            if not rec_id:
                continue
            disp_by_rec.setdefault(rec_id, []).append(item)

        # Sort all dispatch lists by timestamp once
        for rec_id in disp_by_rec:
            self._raise_if_interrupted()
            disp_by_rec[rec_id].sort(key=lambda x: x.get("timestamp", ""))

        d_fast = d_medium = d_slow = 0
        l_fast = l_medium = l_slow = 0
        likelihoods: list[float] = []
        lh_fast: list[float] = []
        lh_medium: list[float] = []
        lh_slow: list[float] = []

        for rec_id, result_list in by_rec.items():
            self._raise_if_interrupted()
            disp_list = disp_by_rec.get(rec_id, [])
            for result in result_list:
                self._raise_if_interrupted()
                r_ts = self._parse_ts(result.get("timestamp"))
                if r_ts is None:
                    continue
                best_prio = None
                best_lh = None
                for d in disp_list:
                    d_ts = self._parse_ts(d.get("timestamp"))
                    if d_ts and d_ts <= r_ts:
                        prio = d.get("payload", {}).get("priority")
                        if prio in ("F", "M", "S"):
                            best_prio = prio
                        lh = d.get("payload", {}).get("likelihood")
                        if isinstance(lh, (int, float)):
                            best_lh = float(lh)
                    else:
                        break

                if best_prio == "F":
                    d_fast += 1
                    if result.get("payload", {}).get("is_live"):
                        l_fast += 1
                        if best_lh is not None:
                            lh_fast.append(best_lh)
                elif best_prio == "M":
                    d_medium += 1
                    if result.get("payload", {}).get("is_live"):
                        l_medium += 1
                        if best_lh is not None:
                            lh_medium.append(best_lh)
                elif best_prio == "S":
                    d_slow += 1
                    if result.get("payload", {}).get("is_live"):
                        l_slow += 1
                        if best_lh is not None:
                            lh_slow.append(best_lh)

                if best_lh is not None and result.get("payload", {}).get("is_live"):
                    likelihoods.append(best_lh)

        return MetricsSummary(
            total_checks=total_checks,
            live_detections=live_detections,
            non_live_results=non_live_results,
            offline_checks_without_near_live_followup=offline_checks_without_near_live_followup,
            offline_checks_with_near_live_followup=offline_checks_with_near_live_followup,
            live_detections_after_offline_check=live_detections_after_offline_check,
            avg_detection_latency_seconds=(
                (sum(detection_latencies) / len(detection_latencies)) if detection_latencies else None
            ),
            avg_lead_minutes_vs_interval=((sum(lead_minutes) / len(lead_minutes)) if lead_minutes else None),
            latency_p50=_pct(detection_latencies, 50),
            latency_p95=_pct(detection_latencies, 95),
            latency_p99=_pct(detection_latencies, 99),
            dispatch_p50=_pct(dispatch_times, 50),
            dispatch_p95=_pct(dispatch_times, 95),
            dispatch_fast=d_fast,
            dispatch_medium=d_medium,
            dispatch_slow=d_slow,
            lives_fast=l_fast,
            lives_medium=l_medium,
            lives_slow=l_slow,
            avg_likelihood_at_dispatch=((sum(likelihoods) / len(likelihoods)) if likelihoods else None),
            avg_likelihood_fast=((sum(lh_fast) / len(lh_fast)) if lh_fast else None),
            avg_likelihood_medium=((sum(lh_medium) / len(lh_medium)) if lh_medium else None),
            avg_likelihood_slow=((sum(lh_slow) / len(lh_slow)) if lh_slow else None),
            lh_fast_p50=_pct(lh_fast, 50),
            lh_medium_p50=_pct(lh_medium, 50),
            lh_slow_p50=_pct(lh_slow, 50),
            lh_slow_min=(round(min(lh_slow), 4) if lh_slow else None),
            lh_slow_max=(round(max(lh_slow), 4) if lh_slow else None),
        )

    def _load_records_after(self, horizon_start: datetime) -> list[dict]:
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT timestamp, event, payload_json FROM predictor_metrics WHERE timestamp >= ? ORDER BY timestamp ASC",
                (horizon_start.isoformat(),),
            ).fetchall()

        self._raise_if_interrupted()
        records = []
        for timestamp, event, payload_json in rows:
            self._raise_if_interrupted()
            try:
                payload = json.loads(payload_json)
            except json.JSONDecodeError:
                continue
            records.append(
                {
                    "timestamp": timestamp,
                    "event": event,
                    "payload": payload,
                }
            )
        return records

    @staticmethod
    def _parse_ts(value) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None
