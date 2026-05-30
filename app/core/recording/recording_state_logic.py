from datetime import datetime, timedelta

from app.models.recording.recording_status_model import CardStateType, RecordingStatus

class RecordingStateLogic:
    ERROR_STATUSES = [RecordingStatus.RECORDING_ERROR, RecordingStatus.LIVE_STATUS_CHECK_ERROR]
    ACTIVE_RECORDING_STATUSES = [RecordingStatus.RECORDING, RecordingStatus.PREPARING_RECORDING]
    
    @staticmethod
    def get_card_state(recording) -> CardStateType:
        if recording.is_recording:
            return CardStateType.RECORDING
        elif recording.status_info in RecordingStateLogic.ERROR_STATUSES:
            return CardStateType.ERROR
        elif getattr(recording, "is_checking", False):
            return CardStateType.CHECKING
        elif recording.is_live and recording.monitor_status and not recording.is_recording:
            return CardStateType.LIVE
        elif (not recording.is_live and recording.monitor_status and
              recording.status_info != RecordingStatus.NOT_IN_SCHEDULED_CHECK):
            return CardStateType.OFFLINE
        elif (not recording.monitor_status or 
              recording.status_info == RecordingStatus.NOT_IN_SCHEDULED_CHECK):
            return CardStateType.STOPPED
        return CardStateType.UNKNOWN

    @classmethod
    def is_actively_recording(cls, recording) -> bool:
        return bool(
            getattr(recording, "is_recording", False)
            or getattr(recording, "status_info", None) in cls.ACTIVE_RECORDING_STATUSES
        )

    @classmethod
    def should_show_duration(cls, recording) -> bool:
        return cls.is_actively_recording(recording)

    @classmethod
    def should_show_live_title(cls, recording) -> bool:
        return cls.is_actively_recording(recording) and bool(getattr(recording, "live_title", None))

    @classmethod
    def has_active_session(cls, recording) -> bool:
        return cls.is_actively_recording(recording) or bool(getattr(recording, "monitor_status", False))

    @classmethod
    def should_show_stop_monitoring_action(cls, recording) -> bool:
        return bool(
            getattr(recording, "monitor_status", False)
            and cls.is_actively_recording(recording)
        )

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            raw = str(value).strip()
            if not raw:
                return None
            raw = raw.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(raw)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(raw, fmt)
                        break
                    except ValueError:
                        dt = None
                if dt is None:
                    return None

        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt

    @classmethod
    def is_stale(cls, recording, days: int = 30, now: datetime | None = None) -> bool:
        """True when a stream has not been seen live for >days.

        If `last_seen_live` is missing, falls back to `added_at`.
        Uses `now` as the time basis (defaults to `datetime.now()`).
        """
        reference = cls._parse_datetime(getattr(recording, "last_seen_live", None))
        if reference is None:
            reference = cls._parse_datetime(getattr(recording, "added_at", None))
        if reference is None:
            return False
        return ((now or datetime.now()) - reference) > timedelta(days=days)
