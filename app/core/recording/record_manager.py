import asyncio
import random
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta

from ...models.recording.recording_model import Recording
from ...models.recording.recording_status_model import RecordingStatus
from ...utils import utils
from ...utils.delay import DelayedTaskExecutor
from ...utils.diagnostics import TEMP_DIAG_TAG  # TEMP-DIAG
from ...utils.i18n import tr
from ...utils.logger import logger
from ..platforms.platform_handlers import get_platform_info
from .predictor_metrics import PredictorMetricsStore
from .stream_manager import LiveStreamRecorder


def _dispatch_seconds(info: dict | None) -> float | None:
    """Seconds between dispatch and now. Returns None if not tracked."""
    if not info:
        return None
    started = info.get("at")
    if started is None:
        return None
    return round((datetime.now() - started).total_seconds(), 3)


class GlobalRecordingState:
    recordings = []
    lock = threading.Lock()


class RecordingManager:
    def __init__(self, app):
        self.app = app
        self.settings = app.settings
        self.periodic_task_started = False
        self.loop_time_seconds = None
        self._needs_platform_migration_persist = False
        self.app.language_manager.add_observer(self)
        self.load_recordings()
        self._ = {}
        self.load()
        self.initialize_dynamic_state()
        max_concurrent = int(self.settings.user_config.get("platform_max_concurrent_requests", 3))
        self.platform_semaphores = defaultdict(lambda: asyncio.Semaphore(max_concurrent))
        self.active_recorders = {}
        self.persist_delay_handler = DelayedTaskExecutor(self.app, self, delay=2)
        self.predictor_metrics = PredictorMetricsStore(
            f"{self.app.config_manager.config_path}/predictor_metrics.db"
        )
        self._predictor_last_offline_result_at: dict[str, datetime] = {}
        self._predictor_dispatched_at: dict[str, dict] = {}

        if self._needs_platform_migration_persist:
            self.app.event_bus.run_task(self.persist_recordings)
        
        # 1. Multi-Priority Task Queues (Intelligence)
        self._queue_fast = asyncio.Queue()
        self._queue_medium = asyncio.Queue()
        self._queue_slow = asyncio.Queue()

        # Adaptive worker pools: all min=1 max=2, only ONE queue at 2 workers
        self._pool_config = {
            "fast":   {"queue": self._queue_fast,   "min": 1, "max": 2, "scale_up_at": 5},
            "medium": {"queue": self._queue_medium, "min": 1, "max": 2, "scale_up_at": 8},
            "slow":   {"queue": self._queue_slow,   "min": 1, "max": 2, "scale_up_at": 5},
        }
        self._pool_workers: dict[str, list[asyncio.Task]] = {name: [] for name in self._pool_config}
        self._pool_empty_since: dict[str, float | None] = {name: None for name in self._pool_config}
        self._boosted_queue: str | None = None  # which queue currently has the extra worker

        for name, cfg in self._pool_config.items():
            for _ in range(cfg["min"]):
                task = asyncio.create_task(self._process_priority_queue(name, cfg["queue"]))
                self._pool_workers[name].append(task)

        self._adaptive_monitor = asyncio.create_task(self._monitor_queues())

    def _record_predictor_metric(self, event_type: str, payload: dict):
        try:
            self.predictor_metrics.record_event(event_type, payload)
        except Exception as e:
            logger.debug(f"Predictor metrics skipped: {e}")

    async def _process_priority_queue(self, name: str, queue: asyncio.Queue):
        """Dedicated worker for a specific priority queue."""
        logger.debug(f"Intelligence Worker-{name} started.")
        while True:
            try:
                recording = await queue.get()
            except asyncio.CancelledError:
                logger.debug(f"Intelligence Worker-{name} cancelled while idle.")
                break
            try:
                if recording.monitor_status and not recording.is_recording:
                    await self.check_if_live(recording)
            except asyncio.CancelledError:
                logger.debug(f"Intelligence Worker-{name} cancelled mid-check.")
                break
            except Exception as e:
                logger.error(f"Error in {name} queue worker: {e}")
            finally:
                queue.task_done()

    def _spawn_worker(self, name: str) -> None:
        cfg = self._pool_config[name]
        task = asyncio.create_task(self._process_priority_queue(name, cfg["queue"]))
        self._pool_workers[name].append(task)
        logger.debug(
            f"Adaptive: spawned {name} worker "
            f"(total={len(self._pool_workers[name])}, depth={cfg['queue'].qsize()})"
        )

    async def _remove_worker(self, name: str) -> None:
        workers = self._pool_workers[name]
        if not workers:
            return
        task = workers.pop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        logger.debug(
            f"Adaptive: removed {name} worker (total={len(workers)})"
        )

    async def _monitor_queues(self) -> None:
        """Periodically check queue depths and adjust worker count.

        Rule: at most ONE queue can have 2 workers at a time.
        The most congested queue gets the boost; others stay at 1.
        """
        MONITOR_INTERVAL = 15  # seconds
        SCALE_DOWN_IDLE = 60   # seconds of continuous emptiness
        while True:
            await asyncio.sleep(MONITOR_INTERVAL)
            now = time.monotonic()

            # ---- Scale down idle workers first (frees up the boost) ----
            for name in list(self._pool_config):
                cfg = self._pool_config[name]
                depth = cfg["queue"].qsize()
                current = len(self._pool_workers[name])

                if depth == 0:
                    if self._pool_empty_since[name] is None:
                        self._pool_empty_since[name] = now
                    elif now - self._pool_empty_since[name] >= SCALE_DOWN_IDLE:
                        if current > cfg["min"]:
                            await self._remove_worker(name)
                            if self._boosted_queue == name:
                                self._boosted_queue = None
                            self._pool_empty_since[name] = now
                else:
                    self._pool_empty_since[name] = None

            # ---- Decide which queue needs the boost most ----
            candidates = []
            for name, cfg in self._pool_config.items():
                depth = cfg["queue"].qsize()
                current = len(self._pool_workers[name])
                if depth > cfg["scale_up_at"] and current < cfg["max"]:
                    # Weight: how far above threshold, normalized
                    excess = depth - cfg["scale_up_at"]
                    candidates.append((excess, name))

            if not candidates:
                continue

            # Most congested queue wins
            candidates.sort(reverse=True)
            _, best = candidates[0]

            if self._boosted_queue is None:
                # No queue boosted yet — give it to the winner
                self._spawn_worker(best)
                self._boosted_queue = best
            elif self._boosted_queue != best:
                # Boost is on a different queue; move it if winner is
                # significantly more congested (avoid flapping)
                cfg_current = self._pool_config[self._boosted_queue]
                depth_current = cfg_current["queue"].qsize()
                cfg_best = self._pool_config[best]
                depth_best = cfg_best["queue"].qsize()

                # Only move if winner has >= 2x the depth of current holder
                if depth_best >= depth_current * 2 or depth_current <= cfg_current["scale_up_at"]:
                    await self._remove_worker(self._boosted_queue)
                    self._spawn_worker(best)
                    self._boosted_queue = best
            # else: boost already on the winning queue, nothing to do

    @property
    def recordings(self):
        return GlobalRecordingState.recordings

    @recordings.setter
    def recordings(self, value):
        raise AttributeError("Please use add_recording/update_recording methods to modify data")

    def load(self):
        language = self.app.language_manager.language
        for key in ("recording_manager", "video_quality"):
            self._.update(language.get(key, {}))

    def load_recordings(self):
        """Load recordings from a JSON file into objects."""
        recordings_data = self.app.config_manager.load_recordings_config()
        if not GlobalRecordingState.recordings:
            raw = [Recording.from_dict(rec) for rec in recordings_data]

            # Deduplicate by URL — keep the recording with higher live_found_count
            seen: dict[str, Recording] = {}
            duplicates = 0
            for rec in raw:
                key = (rec.url or "").strip().lower()
                if not key:
                    seen.setdefault(rec.rec_id, rec)
                    continue
                existing = seen.get(key)
                if existing is None:
                    seen[key] = rec
                else:
                    duplicates += 1
                    # Keep the one with more live data
                    if (rec.live_found_count or 0) > (existing.live_found_count or 0):
                        seen[key] = rec
            if duplicates:
                logger.warning(f"Deduplicated {duplicates} recording(s) by URL during loading.")
            GlobalRecordingState.recordings = list(seen.values())

            migrated = False
            for recording in GlobalRecordingState.recordings:
                canonical_platform, canonical_key = get_platform_info(getattr(recording, "url", "") or "")
                if canonical_key and recording.platform_key != canonical_key:
                    recording.platform_key = canonical_key
                    migrated = True
                if canonical_platform and recording.platform != canonical_platform:
                    recording.platform = canonical_platform
                    migrated = True
                if recording.normalize_long_live_sessions_temporarily():
                    migrated = True

            if migrated:
                self._needs_platform_migration_persist = True

        logger.info(f"Live Recordings: Loaded {len(self.recordings)} items")

    def initialize_dynamic_state(self):
        """Initialize dynamic state for all recordings."""
        loop_time_seconds = self.settings.user_config.get("loop_time_seconds")
        self.loop_time_seconds = int(loop_time_seconds or 300)
        for recording in self.recordings:
            recording.loop_time_seconds = self.loop_time_seconds
            recording.update_title(self._[recording.quality])
            recording.is_checking = False

    async def add_recording(self, recording):
        with GlobalRecordingState.lock:
            GlobalRecordingState.recordings.append(recording)
            await self.persist_recordings()

    async def remove_recording(self, recording: Recording):
        with GlobalRecordingState.lock:
            GlobalRecordingState.recordings.remove(recording)
            await self.persist_recordings()

    async def clear_all_recordings(self):
        with GlobalRecordingState.lock:
            GlobalRecordingState.recordings.clear()
            await self.persist_recordings()

    async def persist_recordings(self):
        """Persist recordings to a JSON file with a small delay to batch updates."""
        await self.persist_delay_handler.start_task_timer(self._actual_persist_recordings)

    async def _actual_persist_recordings(self):
        """The actual disk write operation."""
        data_to_save = [rec.to_dict() for rec in self.recordings]
        await self.app.config_manager.save_recordings_config(data_to_save)

    async def update_recording_card(self, recording: Recording, updated_info: dict):
        """Update an existing recording object and persist changes to a JSON file."""
        if recording:
            recording.update(updated_info)
            await self.persist_recordings()

    @staticmethod
    async def _update_recording(
            recording: Recording, monitor_status: bool, display_title: str, status_info: str, selected: bool
    ):
        attrs_update = {
            "monitor_status": monitor_status,
            "display_title": display_title,
            "status_info": status_info,
            "selected": selected,
        }
        for attr, value in attrs_update.items():
            setattr(recording, attr, value)

    async def start_monitor_recording(self, recording: Recording, auto_save: bool = True):
        """
        Start monitoring a single recording if it is not already being monitored.
        """
        if not recording.monitor_status:
            recording.is_checking = True
            recording.is_live = False
            recording.showed_checking_status = False
            await self._update_recording(
                recording=recording,
                monitor_status=True,
                display_title=recording.title,
                status_info=RecordingStatus.STATUS_CHECKING,
                selected=False,
            )

            self.app.event_bus.publish("update", recording)
            self.app.event_bus.run_task(self.check_if_live, recording)

            await self.persist_recordings()

    async def stop_monitor_recording(self, recording: Recording, auto_save: bool = True):
        """
        Stop monitoring a single recording if it is currently being monitored.
        """
        if recording.monitor_status:
            # If it's recording, stop it first
            self.stop_recording(recording, manually_stopped=True)
            self._predictor_dispatched_at.pop(recording.rec_id, None)
            self._predictor_last_offline_result_at.pop(recording.rec_id, None)
            recording._last_snapshot = None

            # Now update to stopped monitoring state
            monitor_stopped_label = self._.get('monitor_stopped', 'Stopped monitoring')
            await self._update_recording(
                recording=recording,
                monitor_status=False,
                display_title=f"[{monitor_stopped_label}] {recording.title}",
                status_info=RecordingStatus.STOPPED_MONITORING,
                selected=False,
            )
            self.app.event_bus.publish("update", recording)
            await self.persist_recordings()

    async def start_monitor_recordings(self, selected_recordings: list[Recording | None] | None = None):
        """
        Start monitoring multiple recordings based on user selection or all recordings if none are selected.
        """
        if not selected_recordings:
            selected_recordings = await self.get_selected_recordings()
        pre_start_monitor_recordings = selected_recordings or self.recordings
        if hasattr(self.app, 'record_card_manager') and self.app.record_card_manager:
            cards_obj = self.app.record_card_manager.cards_obj
            for recording in pre_start_monitor_recordings:
                # If card manager exists, check visibility
                if recording.rec_id in cards_obj and cards_obj[recording.rec_id]["card"].visible:
                    self.app.event_bus.run_task(self.start_monitor_recording, recording, auto_save=False)
        else:
            # In Qt version, we just start all selected/filtered recordings for now
            # TODO: Improve filtering for Qt version batch actions
            for recording in pre_start_monitor_recordings:
                self.app.event_bus.run_task(self.start_monitor_recording, recording, auto_save=False)
        
        self.app.event_bus.run_task(self.persist_recordings)
        logger.info(f"Batch Start Monitor Recordings: {[i.rec_id for i in pre_start_monitor_recordings]}")

    async def stop_monitor_recordings(self, selected_recordings: list[Recording | None] | None = None):
        """
        Stop monitoring multiple recordings based on user selection or all recordings if none are selected.
        """
        if not selected_recordings:
            selected_recordings = await self.get_selected_recordings()
        pre_stop_monitor_recordings = selected_recordings or self.recordings
        if hasattr(self.app, 'record_card_manager') and self.app.record_card_manager:
            cards_obj = self.app.record_card_manager.cards_obj
            for recording in pre_stop_monitor_recordings:
                if recording.rec_id in cards_obj and cards_obj[recording.rec_id]["card"].visible:
                    self.app.event_bus.run_task(self.stop_monitor_recording, recording, auto_save=False)
        else:
            for recording in pre_stop_monitor_recordings:
                self.app.event_bus.run_task(self.stop_monitor_recording, recording, auto_save=False)
        
        self.app.event_bus.run_task(self.persist_recordings)
        logger.info(f"Batch Stop Monitor Recordings: {[i.rec_id for i in pre_stop_monitor_recordings]}")

    async def get_selected_recordings(self):
        return [recording for recording in self.recordings if recording.selected]

    async def remove_recordings(self, recordings: list[Recording]):
        """Remove a recording from the list and update the JSON file."""
        for recording in recordings:
            if recording in self.recordings:
                await self.remove_recording(recording)
                logger.info(f"Delete Items: {recording.rec_id}-{recording.streamer_name}")

    def find_recording_by_id(self, rec_id: str):
        """Find a recording by its ID (hash of dict representation)."""
        for rec in self.recordings:
            if rec.rec_id == rec_id:
                return rec
        return None

    async def check_all_live_status(self):
        """Check the live status of all recordings and update their display titles."""
        # Prioritize recordings based on their EMA priority score
        def get_priority_score(rec):
            return getattr(rec, 'priority_score', 0.0)

        recordings_to_check = sorted(
            self.recordings,
            key=lambda r: (get_priority_score(r), random.random()),
            reverse=True
        )
        
        dispatched_fast = 0
        dispatched_medium = 0
        dispatched_slow = 0
        busy_fast = 0
        busy_medium = 0
        busy_slow = 0
        skipping_count = 0
        
        _precog_snapshots = {}
        for recording in recordings_to_check:
            if not recording.monitor_status:
                continue

            if recording.is_recording:
                recording._last_snapshot = None
                # Still live, so update historical patterns!
                alpha_active = float(self.settings.user_config.get("ema_alpha_active", 0.1))
                alpha_offline = float(self.settings.user_config.get("ema_alpha_offline", 0.01))
                recording.increment_live_counts(is_live=True, alpha_active=alpha_active, alpha_offline=alpha_offline)
                self.app.event_bus.publish("update", recording)
                continue

            # 1. Apply Smart Predictive Polling (Intelligence)
            from .precog import Precog
            base_interval = int(self.settings.user_config.get("loop_time_seconds", 300))
            recording.loop_time_seconds = base_interval
            snap = Precog.snapshot(recording, now=None, include_debug=True)  # TEMP-DIAG
            recording._last_snapshot = snap
            _precog_snapshots[recording.rec_id] = snap
            likelihood = snap.likelihood

            if snap.should_check:
                prio_key = snap.queue_key

                # 4. Prevent redundant queuing if already checking or in queue
                if recording.is_checking:
                    if prio_key == "F":
                        busy_fast += 1
                    elif prio_key == "M":
                        busy_medium += 1
                    else:
                        busy_slow += 1
                    continue

                recording.is_checking = True
                self._predictor_dispatched_at[recording.rec_id] = {
                    "at": datetime.now(),
                    "likelihood": round(float(likelihood), 4),
                }
                self._record_predictor_metric(
                    "check_dispatched",
                    {
                        "rec_id": recording.rec_id,
                        "priority": prio_key,
                        "likelihood": round(float(likelihood), 4),
                        "loop_time_seconds": snap.adjusted_interval,
                        "is_favorite": bool(getattr(recording, "is_favorite", False)),
                    },
                )
                
                # 5. Dispatch to priority-specific queue
                if prio_key == "F":
                    self._queue_fast.put_nowait(recording)
                    dispatched_fast += 1
                elif prio_key == "M":
                    self._queue_medium.put_nowait(recording)
                    dispatched_medium += 1
                else:
                    self._queue_slow.put_nowait(recording)
                    dispatched_slow += 1
                
                # TEMP-DIAG: queue assignment trace with window state and score breakdown
                _details = getattr(snap, 'forecast_details', None) or {}
                _debug = _details.get("_score_debug", {}) if isinstance(_details, dict) else {}
                _stages = _debug.get("stages", _debug if isinstance(_debug, list) else [])
                _stages_str = ""
                if isinstance(_stages, list) and _stages:
                    _stages_str = ", stages: [" + " → ".join(
                        f"{lbl}={s:.3f}" for lbl, s in _stages
                    ) + "]"
                _cap_str = ""
                if isinstance(_debug, dict):
                    if _debug.get("cap_applied"):
                        _cap_str = f", capped_from={_debug.get('pre_cap_interval', '?')}s"
                _interval = getattr(snap, 'adjusted_interval', None)
                _interval_str = f", interval={_interval}s" if isinstance(_interval, (int, float)) else ""
                _ws = getattr(snap, 'window_state', '?')
                _wc = getattr(snap, 'window_confidence', '?')
                logger.debug(
                    f"Intelligence: Dispatched {recording.streamer_name} "
                    f"to {prio_key} queue"
                    f" (likelihood={likelihood:.3f}"
                    f", priority={getattr(snap, 'priority_score', 0.0):.2f}"
                    f", consistency={getattr(snap, 'consistency_score', 0.0):.2f}"
                    f", reason={getattr(snap, 'reason_key', '')}"
                    f"{_interval_str}"
                    f", window=({_ws},{_wc})"
                    f", fav={bool(getattr(recording, 'is_favorite', False))}"
                    f"{_cap_str}{_stages_str}){TEMP_DIAG_TAG}"
                )
            else:
                skipping_count += 1

        # Summary Log
        total_active = dispatched_fast + dispatched_medium + dispatched_slow + busy_fast + busy_medium + busy_slow
        if total_active > 0:
            logger.opt(colors=True).info(
                f"<yellow>Intelligence Cycle Summary: "
                f"Disp({dispatched_fast}F+{dispatched_medium}M+{dispatched_slow}S) | "
                f"Busy({busy_fast}F+{busy_medium}M+{busy_slow}S) | "
                f"{skipping_count} waiting</yellow>"
            )

        # TEMP-DIAG: per-cycle predictor churn (snapshot counts, horizons, debug stages)
        if _precog_snapshots:
            _ws_counts: dict[str, int] = {}
            _has_debug = 0
            _horizons_total = 0
            for _snap in _precog_snapshots.values():
                _ws = getattr(_snap, 'window_state', '?')
                _ws_counts[_ws] = _ws_counts.get(_ws, 0) + 1
                _fd = getattr(_snap, 'forecast_details', {}) or {}
                if isinstance(_fd, dict) and _fd.get('_score_debug'):
                    _has_debug += 1
                if isinstance(_fd, dict):
                    _fd_h = _fd.get("horizons", {})
                    if isinstance(_fd_h, dict):
                        _horizons_total += len(_fd_h)
            _n = len(_precog_snapshots)
            logger.debug(
                f"Intelligence Cycle TEMP-DIAG: "
                f"snapshots={_n}, horizons={_horizons_total}, debug_snapshots={_has_debug}, "
                f"window_states={_ws_counts}{TEMP_DIAG_TAG}"
            )

        # Publish structured data so the dashboard can update in real-time
        self.app.event_bus.publish("intelligence_cycle", {
            "disp_fast":   dispatched_fast,
            "disp_medium": dispatched_medium,
            "disp_slow":   dispatched_slow,
            "busy_fast":   busy_fast,
            "busy_medium": busy_medium,
            "busy_slow":   busy_slow,
            "waiting":     skipping_count,
            "total_disp":  dispatched_fast + dispatched_medium + dispatched_slow,
            "total_busy":  busy_fast + busy_medium + busy_slow,
        })

        # Publish snapshot data so UI consumers can update without recomputing Precog
        if _precog_snapshots:
            self.app.event_bus.publish("precog_snapshot_batch", _precog_snapshots)

        # Persist all recording updates once after all checks are queued
        await self.persist_recordings()

    _periodic_task_running = False

    @classmethod
    def is_periodic_task_running(cls):
        return cls._periodic_task_running

    @classmethod
    def set_periodic_task_running(cls, value=True):
        cls._periodic_task_running = value

    async def setup_periodic_live_check(self, interval: int = 180):
        """Set up a periodic task to check live status."""

        async def periodic_check():
            logger.info("Starting periodic live check background task")
            while True:
                immediate_check_on_startup = self.app.settings.user_config.get("check_live_on_browser_refresh", True)
                if immediate_check_on_startup:
                    # Run first check immediately (it is already staggered inside check_all_live_status)
                    if self.app.recording_enabled:
                        await self.check_all_live_status()
                    await asyncio.sleep(interval)
                else:
                    await asyncio.sleep(interval)
                
                await self.check_free_space()
                if self.app.recording_enabled:
                    await self.check_all_live_status()

        if not RecordingManager.is_periodic_task_running():
            RecordingManager.set_periodic_task_running(True)
            self.periodic_task_started = True
            logger.info(f"Initializing periodic live check task with interval: {interval}s")
            asyncio.create_task(periodic_check())
        else:
            logger.info("Periodic live check task already running globally, skipping initialization")

    async def check_if_live_with_retry(self, recording: Recording, retries: int = 2, delay: int = 20):
        """
        Check if the live stream is available with retries.
        Useful when a stream ends abruptly and might restart shortly.
        """
        for i in range(retries):
            if recording.is_recording or not recording.monitor_status:
                break
            
            logger.log("RETRY", f"Performing extra live check ({i + 1}/{retries}) for: {recording.url}")
            await self.check_if_live(recording)
            
            # If after check_if_live the recording started (is_recording will be True), we stop retrying
            if recording.is_recording:
                logger.log("RETRY", f"Stream resumed and recording started for: {recording.url}")
                break
            
            if i < retries - 1:
                await asyncio.sleep(delay)

    async def check_if_live(self, recording: Recording):
        """Check if the live stream is available, fetch stream data and update is_live status."""
        try:
            recording.manually_stopped = False
            if recording.is_recording:
                logger.debug(f"Skip check_if_live because recording is busy: {recording.url}")
                return

            if recording.rec_id in self.active_recorders:
                recorder = self.active_recorders[recording.rec_id]
                if not recorder.should_stop:
                    logger.debug(f"Skip check_if_live because recorder is active: {recording.url}")
                    return
                else:
                    logger.debug(
                        f"Proceeding with check_if_live because existing recorder is stopping: {recording.url}"
                    )

            if not recording.monitor_status:
                recording.display_title = f"[{self._['monitor_stopped']}] {recording.title}"
                recording.status_info = RecordingStatus.STOPPED_MONITORING
                self.app.event_bus.publish("update", recording)
                return

            recording.detection_time = datetime.now().time()
            recording.is_checking = True
            
            # Always update UI to show "Checking" status at the start of detection
            recording.status_info = RecordingStatus.STATUS_CHECKING
            self.app.event_bus.publish("update", recording)

            if recording.scheduled_recording:
                scheduled_time_range_list = await self.get_scheduled_time_range(
                    recording.scheduled_start_time, recording.monitor_hours)
                recording.scheduled_time_range = scheduled_time_range_list
                in_scheduled = False
                for scheduled_time_range in scheduled_time_range_list:
                    in_scheduled = utils.is_current_time_within_range(scheduled_time_range)
                    if in_scheduled:
                        break

                if not in_scheduled:
                    recording.status_info = RecordingStatus.NOT_IN_SCHEDULED_CHECK
                    recording.is_live = False
                    logger.info(
                        f"Skip Detection: {recording.url} not in scheduled check range {scheduled_time_range_list}"
                    )
                    self.app.event_bus.publish("update", recording)
                    return

            recording.status_info = RecordingStatus.STATUS_CHECKING
            platform, platform_key = get_platform_info(recording.url)

            if platform and platform_key and (recording.platform != platform or recording.platform_key != platform_key):
                recording.platform = platform
                recording.platform_key = platform_key
                await self.persist_recordings()

            recording_platform = platform_key or platform

            output_dir = self.settings.get_video_save_path()
            await self.check_free_space(output_dir)
            if not self.app.recording_enabled:
                recording.status_info = RecordingStatus.NOT_RECORDING_SPACE
                return
            
            recording_info = {
                "platform": recording_platform,
                "platform_key": platform_key,
                "live_url": recording.url,
                "output_dir": output_dir,
                "segment_record": recording.segment_record,
                "segment_time": recording.segment_time,
                "save_format": recording.record_format,
                "quality": recording.quality,
            }

            semaphore = self.platform_semaphores[platform_key]
            recorder = LiveStreamRecorder(self.app, recording, recording_info)
            
            # Stagger requests slightly *before* acquiring the semaphore to avoid blocking workers
            await asyncio.sleep(random.uniform(0.5, 3.0))
            
            async with semaphore:
                stream_info = await recorder.fetch_stream()
                logger.info(f"Stream Data: {stream_info.anchor_name if stream_info else 'None'}")
            
            if not stream_info or not stream_info.anchor_name:
                logger.error(f"Fetch stream data failed: {recording.url}")
                recording.status_info = RecordingStatus.LIVE_STATUS_CHECK_ERROR
                if recording.monitor_status:
                    self.app.event_bus.publish("update", recording)
                    self.app.event_bus.publish("update", recording)
                return
                
            if self.settings.user_config.get("remove_emojis"):
                live_room_text = self._.get("live_room", "Live Room")
                stream_info.anchor_name = utils.clean_name(stream_info.anchor_name, live_room_text)

            if stream_info.is_live:
                detected_at = datetime.now()
                last_offline_result_at = self._predictor_last_offline_result_at.get(recording.rec_id)
                detection_latency_seconds = None
                if last_offline_result_at:
                    detection_latency_seconds = max((detected_at - last_offline_result_at).total_seconds(), 0.0)
                split_due_to_gap = recording.split_stale_live_session_if_needed(detected_at=detected_at)
                was_live = recording.is_live
                if split_due_to_gap:
                    was_live = False
                # Update last active time
                recording.last_active_at = detected_at.strftime("%Y-%m-%d %H:%M:%S")

                # Update counts using the new responsive method
                alpha_active = float(self.settings.user_config.get("ema_alpha_active", 0.1))
                alpha_offline = float(self.settings.user_config.get("ema_alpha_offline", 0.01))
                recording.increment_live_counts(is_live=True, alpha_active=alpha_active, alpha_offline=alpha_offline)
                
                recording.live_title = stream_info.title
                if stream_info.extra:
                    recording.avatar_url = stream_info.extra.get('avatar')
                    recording.cover_url = stream_info.extra.get('cover')

                if recording.streamer_name.strip() == self._["live_room"]:
                    recording.streamer_name = stream_info.anchor_name
                recording.title = f"{recording.streamer_name} - {self._[recording.quality]}"
                recording.display_title = f"[{self._['is_live']}] {recording.live_title or recording.title}"

                if not recording.is_live:
                    recording.is_live = stream_info.is_live
                    recording.notified_live_start = False
                    recording.notified_live_end = False

                if not was_live:
                    recording.start_live_session(
                        detected_at=detected_at,
                        scheduled_start_time=recording.scheduled_start_time if recording.scheduled_recording else None
                    )

                if not recording.only_notify_no_record:
                    recording.status_info = RecordingStatus.PREPARING_RECORDING
                    recording.loop_time_seconds = self.loop_time_seconds
                    self.start_update(recording)
                    # Explicitly start recording loop instead of relying on a potentially unsubscribed event
                    self.app.event_bus.run_task(recorder.start_recording, stream_info)
                else:
                    if recording.notified_live_start:
                        notify_loop_time = self.settings.user_config.get("notify_loop_time")
                        recording.loop_time_seconds = int(notify_loop_time or 600)
                    else:
                        recording.loop_time_seconds = self.loop_time_seconds

                    recording.cumulative_duration = timedelta()
                    recording.last_duration = timedelta()
                    recording.status_info = RecordingStatus.LIVE_BROADCASTING

                info = self._predictor_dispatched_at.pop(recording.rec_id, None)
                self._record_predictor_metric(
                    "check_result",
                    {
                        "rec_id": recording.rec_id,
                        "is_live": True,
                        "was_live": bool(was_live),
                        "loop_time_seconds": recording.loop_time_seconds,
                        "detection_latency_seconds": detection_latency_seconds,
                        "dispatch_wait_seconds": _dispatch_seconds(info),
                        "likelihood_at_dispatch": info.get("likelihood") if info else None,
                    },
                )
                self._predictor_last_offline_result_at.pop(recording.rec_id, None)

            else:
                # Update counts for non-live case
                alpha_active = float(self.settings.user_config.get("ema_alpha_active", 0.1))
                alpha_offline = float(self.settings.user_config.get("ema_alpha_offline", 0.01))
                recording.increment_live_counts(is_live=False, alpha_active=alpha_active, alpha_offline=alpha_offline)

                recording.is_recording = False
                if recording.is_live or recording.current_live_session_start:
                    recording.end_live_session()
                    recording.is_live = False
                    pass # removed message push

                recording.status_info = RecordingStatus.MONITORING
                title = f"{stream_info.anchor_name or recording.streamer_name} - {self._[recording.quality]}"
                if recording.streamer_name == self._["live_room"] or \
                        f"[{self._['is_live']}]" in recording.display_title:
                    recording.update(
                        {
                            "streamer_name": stream_info.anchor_name,
                            "title": title,
                            "display_title": title,
                        }
                    )

                info = self._predictor_dispatched_at.pop(recording.rec_id, None)
                self._record_predictor_metric(
                    "check_result",
                    {
                        "rec_id": recording.rec_id,
                        "is_live": False,
                        "was_live": False,
                        "loop_time_seconds": recording.loop_time_seconds,
                        "dispatch_wait_seconds": _dispatch_seconds(info),
                        "likelihood_at_dispatch": info.get("likelihood") if info else None,
                    },
                )
                self._predictor_last_offline_result_at[recording.rec_id] = datetime.now()

        finally:
            recording.is_checking = False
            recording._last_snapshot = None
            self.app.event_bus.publish("update", recording)
        return

    @staticmethod
    def start_update(recording: Recording):
        """Start the recording process."""
        if recording.is_live and not recording.is_recording:
            # Reset cumulative and last durations for a fresh start
            recording.update(
                {
                    "cumulative_duration": timedelta(),
                    "last_duration": timedelta(),
                    "start_time": datetime.now(),
                    "is_recording": True,
                }
            )
            logger.info(tr("console.started_recording", "Started recording for {}").format(recording.title))

    def stop_recording(self, recording: Recording, manually_stopped: bool = True):
        """Stop the recording process."""
        recording.end_live_session()
        recording.is_live = False
        if recording.is_recording:

            recording.stopping_in_progress = True

            logger.info(f"Trying to stop recorder for {recording.rec_id}, title: {recording.title}")
            logger.debug(f"Active recorders: {list(self.active_recorders.keys())}")

            recording.detection_time = None
            if recording.rec_id in self.active_recorders:
                recorder = self.active_recorders[recording.rec_id]
                logger.debug(f"Found recorder instance - id: {id(recorder)}")
                recorder.request_stop()
                logger.info(f"Requested stop for recorder: {recording.rec_id}")
            else:
                logger.warning(f"No active recorder found for {recording.rec_id}, cannot request stop")
                recording.force_stop = True
                logger.info(f"Set force_stop=True for recording: {recording.rec_id}")

            if recording.start_time is not None:
                elapsed = datetime.now() - recording.start_time
                # Add the elapsed time to the cumulative duration.
                recording.cumulative_duration += elapsed
                # Update the last recorded duration.
                recording.last_duration = recording.cumulative_duration
            recording.start_time = None
            recording.is_recording = False
            recording.manually_stopped = manually_stopped
            recording.status_info = RecordingStatus.NOT_RECORDING
            logger.info(f"Stopped recording for {recording.title}")

            self.app.event_bus.run_task(self.persist_recordings)

    def get_duration(self, recording: Recording):
        """Get the duration of the current recording session in a formatted string."""
        if recording.is_recording and recording.start_time is not None:
            elapsed = datetime.now() - recording.start_time
            # If recording, add the current session time.
            total_duration = recording.cumulative_duration + elapsed
            return self._["recorded"] + " " + str(total_duration).split(".")[0]
        else:
            # If stopped, show the last recorded total duration.
            total_duration = recording.last_duration
            return str(total_duration).split(".")[0]

    async def delete_recording_cards(self, recordings: list[Recording]):
        self.app.event_bus.publish("update", recordings)
        self.app.event_bus.publish("delete", recordings)
        await self.remove_recordings(recordings)

        # update the filter area of the recording list page (Flet specific)
        if self.app.page and hasattr(self.app, 'current_page') and hasattr(self.app.current_page, 'view_container'):
            current_page = self.app.current_page
            if hasattr(current_page, 'create_filter_area') and len(current_page.view_container.controls) > 1:
                current_page.view_container.controls[1] = current_page.create_filter_area()
                current_page.view_container.update()

    async def check_free_space(self, output_dir: str | None = None):
        disk_space_limit = float(self.settings.user_config.get("recording_space_threshold") or 0)
        output_dir = output_dir or self.settings.get_video_save_path()
        if utils.check_disk_capacity(output_dir) < disk_space_limit:
            self.app.recording_enabled = False
            logger.error(
                f"Disk space remaining is below {disk_space_limit} GB. Recording function disabled"
            )
            if hasattr(self.app, 'snack_bar') and self.app.snack_bar:
                self.app.event_bus.run_task(
                    self.app.snack_bar.show_snack_bar,
                    self._["not_disk_space_tip"],
                    duration=86400,
                    show_close_icon=True
                )
            else:
                # In Qt or if page is missing, just log it; Qt version of snackbar is not yet implemented
                logger.warning(self._["not_disk_space_tip"])

        else:
            self.app.recording_enabled = True

    @staticmethod
    async def get_scheduled_time_range(scheduled_start_time, monitor_hours) -> list | None:
        scheduled_time_range_list = []
        if not scheduled_start_time:
            return scheduled_time_range_list
            
        for index, start_time in enumerate(str(scheduled_start_time).split(',')):
            try:
                hours_list = str(monitor_hours or "").split(',')
                hours = hours_list[index] if index < len(hours_list) else "5"
                if start_time and hours:
                    end_time = utils.add_hours_to_time(start_time, float(hours or 5))
                    scheduled_time_range = f"{start_time}~{end_time}"
                    scheduled_time_range_list.append(scheduled_time_range)
            except Exception:
                pass
        return scheduled_time_range_list

    @staticmethod
    async def _reset_stopping_flag(recording: Recording):
        recording.stopping_in_progress = False
        logger.debug(f"Reset stopping_in_progress flag for recording: {recording.rec_id}")
