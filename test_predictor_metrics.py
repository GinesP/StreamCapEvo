import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from app.core.recording.predictor_metrics import MetricsSummary, PredictorMetricsStore
from scripts import predictor_metrics_report


class PredictorMetricsStoreTests(unittest.TestCase):
    def test_record_event_persists_sqlite_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")

            store.record_event("check_dispatched", {"rec_id": "r-1", "loop_time_seconds": 60})
            store.record_event("check_result", {"rec_id": "r-1", "is_live": False})

            store.close()
            conn = sqlite3.connect(store.db_path)
            rows = conn.execute("SELECT event, rec_id FROM predictor_metrics ORDER BY id ASC").fetchall()
            conn.close()

            self.assertEqual(rows, [("check_dispatched", "r-1"), ("check_result", "r-1")])

    def test_migrates_legacy_jsonl_without_deleting_source_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "predictor_metrics.jsonl"
            legacy_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-05-03T09:00:00",
                                "event": "check_dispatched",
                                "payload": {"rec_id": "rec-1", "priority": "F", "likelihood": 0.9},
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-03T09:03:00",
                                "event": "check_result",
                                "payload": {"rec_id": "rec-1", "is_live": True, "dispatch_wait_seconds": 12},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            store = PredictorMetricsStore(legacy_path)
            summary = store.summarize(lookback_hours=99999)

            self.assertTrue(legacy_path.exists())
            self.assertEqual(summary.total_checks, 1)
            self.assertEqual(summary.live_detections, 1)

            conn = sqlite3.connect(store.db_path)
            row_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]
            conn.close()
            self.assertEqual(row_count, 2)

    def test_migration_is_idempotent_across_store_reinitialization(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "predictor_metrics.jsonl"
            legacy_path.write_text(
                json.dumps(
                    {
                        "timestamp": "2026-05-03T09:00:00",
                        "event": "check_result",
                        "payload": {"rec_id": "rec-1", "is_live": False},
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            first_store = PredictorMetricsStore(legacy_path)
            conn = sqlite3.connect(first_store.db_path)
            first_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]
            conn.close()

            second_store = PredictorMetricsStore(legacy_path)
            conn = sqlite3.connect(second_store.db_path)
            second_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]
            conn.close()

            self.assertEqual(first_count, 1)
            self.assertEqual(second_count, 1)

    def test_summary_uses_honest_naming_and_expected_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "predictor_metrics.jsonl"
            legacy_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-05-03T09:00:00",
                                "event": "check_result",
                                "payload": {"rec_id": "rec-1", "is_live": False, "loop_time_seconds": 300},
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-03T09:03:00",
                                "event": "check_result",
                                "payload": {
                                    "rec_id": "rec-1",
                                    "is_live": True,
                                    "loop_time_seconds": 300,
                                    "detection_latency_seconds": 180,
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-05-03T09:30:00",
                                "event": "check_result",
                                "payload": {"rec_id": "rec-2", "is_live": False, "loop_time_seconds": 180},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            store = PredictorMetricsStore(legacy_path)
            summary = store.summarize(lookback_hours=99999, near_live_minutes=15)

            self.assertEqual(summary.total_checks, 3)
            self.assertEqual(summary.live_detections, 1)
            self.assertEqual(summary.non_live_results, 2)
            self.assertEqual(summary.offline_checks_with_near_live_followup, 1)
            self.assertEqual(summary.offline_checks_without_near_live_followup, 1)
            self.assertEqual(summary.live_detections_after_offline_check, 1)
            self.assertEqual(summary.avg_detection_latency_seconds, 180.0)
            self.assertEqual(summary.avg_lead_minutes_vs_interval, 2.0)
            self.assertEqual(
                summary.to_dict()["offline_checks_without_near_live_followup"],
                1,
            )

    def test_interrupt_pending_operations_is_safe_when_idle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")
            store.interrupt_pending_operations()
            store.record_event("check_result", {"rec_id": "rec-1", "is_live": False})
            summary = store.summarize(lookback_hours=72)

            store.close()
            conn = sqlite3.connect(store.db_path)
            row_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]
            conn.close()
            self.assertEqual(row_count, 1)
            self.assertEqual(summary.total_checks, 1)

    def test_summarize_aborts_when_interrupted_during_postprocessing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")
            rows = [
                (
                    f"2026-05-03T09:{idx // 60:02d}:{idx % 60:02d}",
                    "check_result",
                    f"rec-{idx}",
                    0,
                    None,
                    None,
                    json.dumps({"rec_id": f"rec-{idx}", "is_live": False}),
                )
                for idx in range(2000)
            ]
            with store._connect() as conn:
                conn.executemany(
                    "INSERT INTO predictor_metrics (timestamp, event, rec_id, is_live, priority, likelihood, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                conn.commit()

            original_parse_ts = store._parse_ts
            call_count = {"value": 0}

            def slow_parse(value):
                call_count["value"] += 1
                if call_count["value"] == 50:
                    store.interrupt_pending_operations()
                return original_parse_ts(value)

            store._parse_ts = slow_parse
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    store.summarize(lookback_hours=99999)
            finally:
                store._parse_ts = original_parse_ts

    def test_metrics_summary_to_dict_has_expected_keys(self):
        summary = MetricsSummary(
            total_checks=1,
            live_detections=1,
            non_live_results=0,
            offline_checks_without_near_live_followup=0,
            offline_checks_with_near_live_followup=0,
            live_detections_after_offline_check=0,
            avg_detection_latency_seconds=None,
            avg_lead_minutes_vs_interval=None,
        )

        self.assertEqual(
            summary.to_dict(),
            {
                "total_checks": 1,
                "live_detections": 1,
                "non_live_results": 0,
                "offline_checks_without_near_live_followup": 0,
                "offline_checks_with_near_live_followup": 0,
                "live_detections_after_offline_check": 0,
                "avg_detection_latency_seconds": None,
                "avg_lead_minutes_vs_interval": None,
                "latency_p50": None,
                "latency_p95": None,
                "latency_p99": None,
                "dispatch_p50": None,
                "dispatch_p95": None,
                "dispatch_fast": 0,
                "dispatch_medium": 0,
                "dispatch_slow": 0,
                "lives_fast": 0,
                "lives_medium": 0,
                "lives_slow": 0,
                "avg_likelihood_at_dispatch": None,
                "avg_likelihood_fast": None,
                "avg_likelihood_medium": None,
                "avg_likelihood_slow": None,
                "lh_fast_p50": None,
                "lh_medium_p50": None,
                "lh_slow_p50": None,
                "lh_slow_min": None,
                "lh_slow_max": None,
                "note_lead_is_interval_artifact": True,
            },
        )

    def _insert_records(self, store: PredictorMetricsStore, records: list[tuple[str, str, dict]]) -> None:
        """Insert records with explicit timestamps directly into the DB."""
        with store._connect() as conn:
            for ts, event, payload in records:
                conn.execute(
                    "INSERT INTO predictor_metrics (timestamp, event, rec_id, is_live, priority, likelihood, payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        ts,
                        event,
                        payload.get("rec_id") or None,
                        1 if payload.get("is_live") else 0,
                        payload.get("priority"),
                        payload.get("likelihood"),
                        json.dumps(payload, ensure_ascii=False),
                    ),
                )
            conn.commit()

    def test_purge_removes_old_records_and_keeps_recent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(
                Path(temp_dir) / "predictor_metrics.db",
                retention_hours=72,
                purge_throttle_minutes=0,  # disable throttle for deterministic test
            )
            now = datetime.utcnow()
            old_ts = (now - timedelta(hours=73)).isoformat()
            recent_ts = (now - timedelta(hours=1)).isoformat()

            self._insert_records(
                store,
                [
                    (old_ts, "check_result", {"rec_id": "old-rec", "is_live": False}),
                    (recent_ts, "check_result", {"rec_id": "recent-rec", "is_live": True}),
                ],
            )

            # Trigger purge via record_event
            store.record_event("check_dispatched", {"rec_id": "trigger", "loop_time_seconds": 60})
            store.close()

            with store._connect() as conn:
                rows = conn.execute("SELECT rec_id FROM predictor_metrics ORDER BY timestamp ASC").fetchall()

            rec_ids = [r[0] for r in rows]
            self.assertNotIn("old-rec", rec_ids)
            self.assertIn("recent-rec", rec_ids)
            self.assertIn("trigger", rec_ids)

    def test_purge_throttling_limits_frequency(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(
                Path(temp_dir) / "predictor_metrics.db",
                retention_hours=72,
                purge_throttle_minutes=60,  # long throttle
            )
            now = datetime.utcnow()
            old_ts = (now - timedelta(hours=73)).isoformat()

            self._insert_records(
                store,
                [
                    (old_ts, "check_result", {"rec_id": "old-rec", "is_live": False}),
                ],
            )

            # First write triggers purge
            store.record_event("check_dispatched", {"rec_id": "t1", "loop_time_seconds": 60})

            # Manually backdate _last_purge_time so the second write would also purge
            # (simulating no throttle)
            store._last_purge_time = now - timedelta(minutes=61)

            # Second write should purge again because throttle elapsed
            store.record_event("check_dispatched", {"rec_id": "t2", "loop_time_seconds": 60})
            store.close()

            with store._connect() as conn:
                row_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]

            # old-rec purged, t1 and t2 remain
            self.assertEqual(row_count, 2)

    def test_purge_does_not_run_when_throttle_active(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(
                Path(temp_dir) / "predictor_metrics.db",
                retention_hours=72,
                purge_throttle_minutes=60,
            )
            now = datetime.utcnow()
            old_ts = (now - timedelta(hours=73)).isoformat()

            self._insert_records(
                store,
                [
                    (old_ts, "check_result", {"rec_id": "old-rec", "is_live": False}),
                ],
            )

            # First write purges
            store.record_event("check_dispatched", {"rec_id": "t1", "loop_time_seconds": 60})

            # Second write with throttle still active should NOT purge again
            store.record_event("check_dispatched", {"rec_id": "t2", "loop_time_seconds": 60})
            store.close()

            with store._connect() as conn:
                row_count = conn.execute("SELECT COUNT(*) FROM predictor_metrics").fetchone()[0]

            # old-rec purged once, t1 and t2 remain
            self.assertEqual(row_count, 2)

    def test_writes_still_work_after_close(self):
        """close() discards the persistent connection; next write re-creates it."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")
            store.record_event("check_dispatched", {"rec_id": "r-1"})
            store.close()
            # Next write should create a fresh connection without error
            store.record_event("check_dispatched", {"rec_id": "r-2"})
            store.close()
            conn = sqlite3.connect(store.db_path)
            rows = conn.execute("SELECT rec_id FROM predictor_metrics ORDER BY id ASC").fetchall()
            conn.close()
            self.assertEqual([r[0] for r in rows], ["r-1", "r-2"])

    def test_close_is_idempotent(self):
        """Calling close() multiple times is safe."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")
            store.close()
            store.close()  # second call should not raise
            store.record_event("check_dispatched", {"rec_id": "r-1"})
            store.close()

    def test_interrupt_then_write_creates_fresh_connection(self):
        """After interrupt_pending_operations, the persistent connection is
        discarded and a new write succeeds on the next record_event."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")
            store.record_event("check_dispatched", {"rec_id": "r-1"})
            store.interrupt_pending_operations()
            # The write connection was discarded; next call creates a fresh one
            store.record_event("check_dispatched", {"rec_id": "r-2"})
            store.close()
            conn = sqlite3.connect(store.db_path)
            rows = conn.execute("SELECT rec_id FROM predictor_metrics ORDER BY id ASC").fetchall()
            conn.close()
            self.assertEqual([r[0] for r in rows], ["r-1", "r-2"])

    def test_reuses_write_connection_within_record_event(self):
        """Multiple record_event calls reuse the same connection (internal check)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(Path(temp_dir) / "predictor_metrics.db")
            # First call creates the connection
            store.record_event("check_dispatched", {"rec_id": "r-1"})
            conn1 = store._write_conn
            self.assertIsNotNone(conn1)
            # Second call reuses it
            store.record_event("check_dispatched", {"rec_id": "r-2"})
            self.assertIs(store._write_conn, conn1)
            store.close()

    def test_summarize_still_works_after_purge(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PredictorMetricsStore(
                Path(temp_dir) / "predictor_metrics.db",
                retention_hours=72,
                purge_throttle_minutes=0,
            )
            now = datetime.utcnow()
            old_ts = (now - timedelta(hours=73)).isoformat()
            recent_ts = (now - timedelta(hours=1)).isoformat()

            self._insert_records(
                store,
                [
                    (old_ts, "check_result", {"rec_id": "old", "is_live": False, "loop_time_seconds": 300}),
                    (recent_ts, "check_result", {"rec_id": "recent", "is_live": True, "loop_time_seconds": 300, "detection_latency_seconds": 180}),
                ],
            )

            store.record_event("check_dispatched", {"rec_id": "trigger", "loop_time_seconds": 60})
            store.close()

            summary = store.summarize(lookback_hours=72)
            self.assertEqual(summary.total_checks, 1)
            self.assertEqual(summary.live_detections, 1)
            self.assertEqual(summary.non_live_results, 0)


class PredictorMetricsReportTests(unittest.TestCase):
    def test_report_prints_metrics_file_note_and_summary_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            metrics_store = PredictorMetricsStore(Path(temp_dir) / "config" / "predictor_metrics.db")
            metrics_store.record_event("check_dispatched", {"rec_id": "r-1", "loop_time_seconds": 60})
            metrics_store.record_event("check_result", {"rec_id": "r-1", "is_live": False})
            metrics_store.close()

            output = io.StringIO()
            with redirect_stdout(output):
                predictor_metrics_report.main(
                    [
                        "--user-data-dir",
                        temp_dir,
                        "--lookback-hours",
                        "24",
                    ]
                )

            rendered = output.getvalue()
            self.assertIn("metrics_file=", rendered)
            self.assertIn(
                "notes=offline_checks_* are monitoring heuristics, not confirmed false positives/misses",
                rendered,
            )
            self.assertIn("total_checks", rendered)
            self.assertIn("offline_checks_without_near_live_followup", rendered)

    def test_resolve_repo_root_points_to_project_root(self):
        root = predictor_metrics_report.resolve_repo_root()
        self.assertTrue((root / "app").exists())


if __name__ == "__main__":
    unittest.main()
