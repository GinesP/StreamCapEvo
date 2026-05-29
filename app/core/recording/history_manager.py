import random
from datetime import datetime, timedelta

from ...models.recording.recording_model import Recording


class HistoryManager:
    @staticmethod
    def _session_stats(recording: Recording, now: datetime) -> dict:
        sessions = []
        for session in getattr(recording, "live_sessions", []) or []:
            try:
                start = datetime.fromisoformat(session.get("start_time"))
            except (TypeError, ValueError):
                continue
            age_days = max(0, (now - start).days)
            if age_days > 90:
                continue

            weight = 1.0 / (1.0 + (age_days / 21.0))
            sessions.append((session, start, weight))

        if not sessions:
            return {
                "score": 0.0,
                "confidence_boost": 0.0,
                "next_slot_text": "",
                "window_text": "",
                "reason_key": "",
                "avg_delay_minutes": None,
            }

        today = now.weekday()
        current_minutes = now.hour * 60 + now.minute
        weighted_hits = 0.0
        weighted_total = 0.0
        nearest_minute = None          # for score computation (circular distance)
        nearest_distance = None
        nearest_display_minute = None  # for UI display (prefers future)
        nearest_display_distance = None
        durations = []
        delays = []

        for session, start, weight in sessions:
            start_minutes = start.hour * 60 + start.minute
            distance = abs(start_minutes - current_minutes)
            distance = min(distance, 1440 - distance)
            day_match = start.weekday() == today
            day_weight = weight * (1.25 if day_match else 0.35)
            proximity = max(0.0, 1.0 - (distance / 240.0))

            weighted_hits += day_weight * proximity
            weighted_total += day_weight

            if day_match and (nearest_distance is None or distance < nearest_distance):
                nearest_distance = distance
                nearest_minute = start_minutes

            if day_match:
                minutes_ahead = (start_minutes - current_minutes + 1440) % 1440
                if minutes_ahead >= 1440 - 15:
                    display_dist = 0          # "just passed" — still the active window
                elif minutes_ahead > 0:
                    display_dist = minutes_ahead
                else:
                    display_dist = 1440
                if nearest_display_distance is None or display_dist < nearest_display_distance:
                    nearest_display_distance = display_dist
                    nearest_display_minute = start_minutes

            duration = session.get("duration_minutes")
            if isinstance(duration, (int, float)) and duration > 0:
                durations.append(duration)

            delay = session.get("scheduled_delay_minutes")
            if isinstance(delay, (int, float)):
                delays.append(delay)

        session_score = weighted_hits / weighted_total if weighted_total else 0.0
        avg_duration = int(sum(durations) / len(durations)) if durations else 60
        avg_delay = int(sum(delays) / len(delays)) if delays else None

        display_minute = nearest_display_minute if nearest_display_minute is not None else nearest_minute

        window_text = ""
        next_slot_text = ""
        if display_minute is not None:
            start_h, start_m = divmod(display_minute, 60)
            end_minutes = (display_minute + avg_duration) % 1440
            end_h, end_m = divmod(end_minutes, 60)
            next_slot_text = f"{start_h:02d}:{start_m:02d}"
            window_text = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"

        confidence_boost = min(0.18, len(sessions) * 0.015)
        reason_key = "live_forecast_dialog.reason_session_pattern" if session_score >= 0.35 else ""

        return {
            "score": session_score,
            "confidence_boost": confidence_boost,
            "next_slot_text": next_slot_text,
            "window_text": window_text,
            "reason_key": reason_key,
            "avg_delay_minutes": avg_delay,
        }

    @staticmethod
    def _parse_scheduled_windows(recording: Recording, now: datetime) -> list[tuple[datetime, datetime]]:
        if not getattr(recording, "scheduled_recording", False):
            return []

        start_times = str(getattr(recording, "scheduled_start_time", "") or "").split(",")
        hours_list = str(getattr(recording, "monitor_hours", "") or "").split(",")
        windows: list[tuple[datetime, datetime]] = []

        for index, start_time in enumerate(start_times):
            start_time = start_time.strip()
            if not start_time:
                continue
            try:
                parsed = datetime.strptime(start_time, "%H:%M:%S")
            except ValueError:
                continue

            try:
                duration_hours = float((hours_list[index] if index < len(hours_list) else hours_list[0]).strip() or 2)
            except (ValueError, IndexError):
                duration_hours = 2

            start_dt = now.replace(
                hour=parsed.hour,
                minute=parsed.minute,
                second=parsed.second,
                microsecond=0,
            )
            end_dt = start_dt + timedelta(hours=max(1.0, duration_hours))
            windows.append((start_dt, end_dt))

        return windows

    @staticmethod
    def cluster_hours(hours: list[int], max_gap: int = 4) -> list[list[int]]:
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
    def _cluster_info(active_hours: list[int], display_hour: int) -> tuple[list[list[int]], list[int], int, int, int]:
        clusters = HistoryManager.cluster_hours(active_hours)
        target = next((c for c in clusters if display_hour in c), clusters[0])
        return clusters, target, target[0], target[-1], (target[-1] + 1) % 24

    @staticmethod
    def get_forecast_details(
        recording: Recording,
        now: datetime | None = None,
        include_horizons: bool = True,
    ) -> dict:
        now = now or datetime.now()
        if recording.is_live:
            return {
                "score": 1.0,
                "confidence": "high",
                "reason_key": "live_forecast_dialog.reason_live_now",
                "next_slot_text": "",
                "window_text": "",
                "avg_delay_minutes": None,
                "horizons": {15: 1.0, 30: 1.0, 60: 1.0} if include_horizons else {},
            }

        day_str = str(now.weekday())
        intervals = recording.historical_intervals or {}
        active_hours = sorted(set(intervals.get(day_str, [])))
        current_minutes = now.hour * 60 + now.minute

        score = 0.15
        confidence = "low"
        reason_key = "live_forecast_dialog.reason_low_signal"
        next_slot_text = ""
        window_text = ""

        if active_hours:
            nearest_hour = min(active_hours, key=lambda hour: abs((hour * 60) - current_minutes))
            minute_distance = abs((nearest_hour * 60) - current_minutes)
            proximity = max(0.0, 1.0 - (minute_distance / 180.0))
            score = max(score, 0.25 + (proximity * 0.55))

            future_hours = [h for h in active_hours if h * 60 >= current_minutes]
            if future_hours:
                display_hour = min(future_hours)
            elif active_hours:
                display_hour = min(active_hours)  # wrap to tomorrow
            else:
                display_hour = nearest_hour

            _, _, first_h, last_h, end_h = HistoryManager._cluster_info(active_hours, display_hour)
            window_text = f"{first_h:02d}:00-{end_h:02d}:00"
            next_slot_text = f"{display_hour:02d}:00"

            if now.hour in active_hours:
                score = max(score, 0.92)
                confidence = "high"
                reason_key = "live_forecast_dialog.reason_historical_window"
            elif minute_distance <= 60:
                confidence = "medium"
                reason_key = "live_forecast_dialog.reason_starting_soon"
            else:
                reason_key = "live_forecast_dialog.reason_historical_pattern"

        session_stats = HistoryManager._session_stats(recording, now)
        if session_stats["score"] > 0:
            session_component = 0.20 + (session_stats["score"] * 0.65)
            if session_component > score:
                score = session_component
                if session_stats["reason_key"]:
                    reason_key = session_stats["reason_key"]
            if session_stats["window_text"] and session_stats["next_slot_text"]:
                window_text = session_stats["window_text"]
                next_slot_text = session_stats["next_slot_text"]
            score += session_stats["confidence_boost"]

        score += min(0.12, max(0.0, getattr(recording, "consistency_score", 0.0)) * 0.12)
        score += min(0.12, max(0.0, getattr(recording, "priority_score", 0.0)) * 0.12)

        for start_dt, end_dt in HistoryManager._parse_scheduled_windows(recording, now):
            if start_dt <= now <= end_dt:
                score = max(score, 0.95)
                confidence = "high"
                reason_key = "live_forecast_dialog.reason_scheduled_window"
                next_slot_text = start_dt.strftime("%H:%M")
                window_text = f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
                break

            minutes_until = int((start_dt - now).total_seconds() // 60)
            if 0 < minutes_until <= 90:
                score = max(score, 0.70 + ((90 - minutes_until) / 90.0) * 0.15)
                confidence = "high" if minutes_until <= 30 else "medium"
                reason_key = "live_forecast_dialog.reason_scheduled_soon"
                next_slot_text = start_dt.strftime("%H:%M")
                window_text = f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
                break

        last_seen_live = getattr(recording, "last_seen_live", None)
        if last_seen_live:
            try:
                inactive_days = (now - datetime.fromisoformat(last_seen_live)).days
            except ValueError:
                inactive_days = 0
            if inactive_days > 14:
                score *= 0.82
            if inactive_days > 45:
                score *= 0.70

        score = max(0.05, min(1.0, score))
        if score >= 0.75:
            confidence = "high"
        elif score >= 0.45 and confidence != "high":
            confidence = "medium"

        result = {
            "score": score,
            "confidence": confidence,
            "reason_key": reason_key,
            "next_slot_text": next_slot_text,
            "window_text": window_text,
            "avg_delay_minutes": session_stats.get("avg_delay_minutes"),
            "horizons": {},
        }

        if include_horizons:
            result["horizons"] = {
                minutes: HistoryManager.get_forecast_details(
                    recording,
                    now + timedelta(minutes=minutes),
                    include_horizons=False,
                )["score"]
                for minutes in (15, 30, 60)
            }

        return result

    @staticmethod
    def get_likelihood_score(recording: Recording) -> float:
        """
        Calculates a score between 0.0 and 1.0 representing how likely 
        the streamer is to be live right now based on historical data.
        """
        return HistoryManager.get_forecast_details(recording)["score"]

    @staticmethod
    def get_adjusted_interval(recording: Recording, base_interval: int) -> int:
        """
        Returns an adjusted check interval based on the likelihood score and priority score.
        Applies a 15% jitter to prevent thundering herd / predictable bot patterns.

        Likelihood always wins over deep sleep — if the predictor says the stream
        is likely live (>= 0.5), we check faster regardless of historical deadness.
        """
        likelihood = HistoryManager.get_likelihood_score(recording)

        if likelihood >= 0.9:
            target_interval = 60

        elif likelihood >= 0.5:
            target_interval = base_interval // 2

        elif getattr(recording, 'priority_score', 0.0) < 0.01 and getattr(recording, 'live_check_count', 0) > 30:
            target_interval = base_interval * 3

        elif likelihood <= 0.15:
            target_interval = int(base_interval * 1.5)

        else:
            target_interval = base_interval

        jitter_min = int(target_interval * 0.85)
        jitter_max = int(target_interval * 1.15)

        jitter_min = max(45, jitter_min)
        jitter_max = max(jitter_min + 5, jitter_max)

        return random.randint(jitter_min, jitter_max)
