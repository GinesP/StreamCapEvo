import argparse
import json
import os
import sys
from pathlib import Path


def resolve_repo_root():
    return Path(__file__).resolve().parent.parent


REPO_ROOT = resolve_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.config.config_manager import ConfigManager
from app.core.recording.predictor_metrics import PredictorMetricsStore


def main(argv=None):
    parser = argparse.ArgumentParser(description="Predictor metrics summary report")
    parser.add_argument("--lookback-hours", type=int, default=72)
    parser.add_argument("--user-data-dir", default=os.environ.get("STREAMCAPEVO_USER_DATA_DIR") or os.environ.get("STREAMCAP_USER_DATA_DIR"))
    parser.add_argument(
        "--metrics-file", default=None, help="Override path to predictor_metrics.db or legacy predictor_metrics.jsonl"
    )
    parser.add_argument("--human", action="store_true", help="Print human-readable table instead of JSON")
    args = parser.parse_args(argv)

    if args.metrics_file:
        metrics_path = Path(args.metrics_file)
    else:
        config_manager = ConfigManager(str(REPO_ROOT), user_data_path=args.user_data_dir)
        metrics_path = Path(config_manager.config_path) / "predictor_metrics.db"
    store = PredictorMetricsStore(metrics_path)
    summary = store.summarize(lookback_hours=args.lookback_hours)

    if args.human:
        _print_human(summary, metrics_path)
    else:
        print(f"metrics_file={metrics_path}")
        print("notes=offline_checks_* are monitoring heuristics, not confirmed false positives/misses")
        print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))


def _print_human(summary, metrics_path):
    s = summary
    div = "-" * 42
    print(f"metrics_file={metrics_path}")
    print(f"lookback_hours=72 (default)\n")
    print(f"  Total checks:        {s.total_checks:>8,}")
    print(f"  Live detections:     {s.live_detections:>8}")
    if s.total_checks:
        print(f"  Live rate:           {s.live_detections / s.total_checks * 100:>7.3f}%")
    print(f"  Non-live results:    {s.non_live_results:>8,}")
    print(f"  {div}")
    print(f"  Queue breakdown (F/M/S):")
    print(f"    Fast    (<=60s):   {s.dispatch_fast:>6} dispatched, {s.lives_fast:>5} lives")
    print(f"    Medium (<=180s):   {s.dispatch_medium:>6} dispatched, {s.lives_medium:>5} lives")
    print(f"    Slow    (>180s):   {s.dispatch_slow:>6} dispatched, {s.lives_slow:>5} lives")
    if s.lives_medium > 0:
        print(
            f"    Medium lives/pct:  {s.lives_medium / s.live_detections * 100:.1f}% of all lives"
            if s.live_detections
            else ""
        )
    print(f"  {div}")
    print(f"  Offline (no follow): {s.offline_checks_without_near_live_followup:>8,}")
    print(f"  Offline (+ follow):  {s.offline_checks_with_near_live_followup:>8,}")
    print(f"  Live via follow-up:  {s.live_detections_after_offline_check:>8}")
    if s.live_detections:
        print(f"  % Live via follow-up:{s.live_detections_after_offline_check / s.live_detections * 100:>7.1f}%")
    print(f"  {div}")
    print(f"  Detection latency percentiles (s):")
    print(f"    avg:  {s.avg_detection_latency_seconds:>8.1f}" if s.avg_detection_latency_seconds else "    avg:  -")
    print(f"    p50:  {s.latency_p50:>8.1f}" if s.latency_p50 else "    p50:  -")
    print(f"    p95:  {s.latency_p95:>8.1f}" if s.latency_p95 else "    p95:  -")
    print(f"    p99:  {s.latency_p99:>8.1f}" if s.latency_p99 else "    p99:  -")
    print(f"  Dispatch->result percentiles (s):")
    print(f"    p50:  {s.dispatch_p50:>8.1f}" if s.dispatch_p50 else "    p50:  - (no dispatch_wait data in window)")
    print(f"    p95:  {s.dispatch_p95:>8.1f}" if s.dispatch_p95 else "    p95:  -")
    if s.avg_likelihood_at_dispatch is not None:
        print(f"  Avg likelihood (live detections): {s.avg_likelihood_at_dispatch:.4f}")
        if s.avg_likelihood_fast is not None:
            print(
                f"    Fast:   {s.avg_likelihood_fast:.4f}  (p50={s.lh_fast_p50:.4f}, {s.lives_fast} lives)"
                if s.lh_fast_p50
                else f"    Fast:   {s.avg_likelihood_fast:.4f}  ({s.lives_fast} lives)"
            )
        if s.avg_likelihood_medium is not None:
            print(
                f"    Medium: {s.avg_likelihood_medium:.4f}  (p50={s.lh_medium_p50:.4f}, {s.lives_medium} lives)"
                if s.lh_medium_p50
                else f"    Medium: {s.avg_likelihood_medium:.4f}  ({s.lives_medium} lives)"
            )
        if s.avg_likelihood_slow is not None:
            line = (
                f"    Slow:   {s.avg_likelihood_slow:.4f}  (p50={s.lh_slow_p50:.4f}"
                if s.lh_slow_p50
                else f"    Slow:   {s.avg_likelihood_slow:.4f}  ("
            )
            if s.lh_slow_min is not None and s.lh_slow_max is not None:
                line += f", min={s.lh_slow_min:.4f}, max={s.lh_slow_max:.4f}"
            line += f", {s.lives_slow} lives)"
            print(line)
    print(f"  {div}")
    print(
        f"  avg_lead_min_vs_interval: {s.avg_lead_minutes_vs_interval:.2f}"
        if s.avg_lead_minutes_vs_interval
        else "  avg_lead_min_vs_interval: -"
    )
    print(f"  !! lead_min is an ARTIFACT of fixed loop_time, not real detection lead.")


if __name__ == "__main__":
    main()
