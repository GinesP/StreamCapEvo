import abc
import contextvars
import functools
import inspect
import re
import threading
import time
import tracemalloc
from collections.abc import Awaitable, Callable
from typing import Any, Optional, TypeVar

from streamget import StreamData

from ....utils.logger import logger

T = TypeVar("T", bound="PlatformHandler")
InstanceKey = tuple[str | None, tuple[tuple[str, str], ...] | None, str, str | None, str | None, str | None, str | None]

# Observation-only status-check tracing.
# These helpers emit STATUS-level log lines around every streamget handoff so
# httpx/_models.py allocation spikes in the periodic diagnostics can be
# correlated with concrete status checks. They never change request semantics.
_STATUS_LEVEL = "STATUS"
_STATUS_CHECK_INFLIGHT_WARN = 8

#: Correlation identity set by the status-check caller (e.g. recording rec_id).
_status_check_context: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "status_check_context", default=None
)

#: Bounded per-platform counter of in-flight status checks.
_status_inflight: dict[str, int] = {}
_status_inflight_lock = threading.Lock()


def set_status_check_context(rec_id: Optional[str]) -> contextvars.Token:
    """Associate the current async context with a status-check identity."""
    return _status_check_context.set(rec_id)


def reset_status_check_context(token: contextvars.Token) -> None:
    """Undo set_status_check_context for the current async context."""
    _status_check_context.reset(token)


def _log_status(message: str) -> None:
    """Best-effort STATUS log; tracing must never break the fetch path."""
    try:
        logger.log(_STATUS_LEVEL, message)
    except Exception:
        pass


def _log_status_warning(message: str) -> None:
    """Best-effort STATUS warning; tracing must never break the fetch path."""
    try:
        logger.warning(message)
    except Exception:
        pass


def _status_inflight_enter(platform: str) -> int:
    with _status_inflight_lock:
        count = _status_inflight.get(platform, 0) + 1
        _status_inflight[platform] = count
    if count > _STATUS_CHECK_INFLIGHT_WARN:
        _log_status_warning(
            f"STATUS in-flight warning: platform={platform} "
            f"concurrent_status_checks={count} (>{_STATUS_CHECK_INFLIGHT_WARN})"
        )
    return count


def _status_inflight_exit(platform: str) -> int:
    with _status_inflight_lock:
        count = _status_inflight.get(platform, 1) - 1
        if count <= 0:
            _status_inflight.pop(platform, None)
            count = 0
        else:
            _status_inflight[platform] = count
    return count


def _status_check_trace(
    instance: "PlatformHandler", func: Callable[[str], Awaitable[Any]]
) -> Callable[[str], Awaitable[Any]]:
    """Wrap a handler's get_stream_info with observation-only STATUS tracing."""
    platform = getattr(instance, "platform", type(instance).__name__)

    @functools.wraps(func)
    async def traced(live_url: str) -> Any:
        rec_id = _status_check_context.get()
        handler_id = hex(id(instance))
        live_stream = getattr(instance, "live_stream", None)
        reused = live_stream is not None
        live_stream_id = hex(id(live_stream)) if live_stream is not None else "-"
        active_checks = getattr(instance, "_active_status_checks", 0)
        platform_inflight = _status_inflight_enter(platform)

        tracing = tracemalloc.is_tracing()
        mem_before = tracemalloc.get_traced_memory()[0] if tracing else None
        started = time.perf_counter()

        _log_status(
            f"CHECK begin rec_id={rec_id} platform={platform} "
            f"handler={type(instance).__name__} handler_id={handler_id} url={live_url} "
            f"live_stream_id={live_stream_id} reused={reused} "
            f"active_checks={active_checks} platform_inflight={platform_inflight} "
            f"tracemalloc={'on' if tracing else 'off'}"
        )

        error: BaseException | None = None
        try:
            result = await func(live_url)
        except BaseException as exc:
            error = exc
            result = None
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            mem_after = tracemalloc.get_traced_memory()[0] if tracing else 0
            delta = (mem_after - mem_before) if mem_before is not None else None
            _log_status(
                f"CHECK error rec_id={rec_id} platform={platform} handler_id={handler_id} "
                f"exc={type(exc).__name__}: {str(exc)[:200]!r} duration_ms={elapsed_ms:.1f} "
                f"alloc_delta_bytes={delta if delta is not None else '-'} "
                f"platform_inflight={platform_inflight}"
            )
        else:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            mem_after = tracemalloc.get_traced_memory()[0] if tracing else 0
            delta = (mem_after - mem_before) if mem_before is not None else None
            ok = bool(getattr(result, "anchor_name", None))
            is_live = getattr(result, "is_live", None) if ok else None
            _log_status(
                f"CHECK end rec_id={rec_id} platform={platform} handler_id={handler_id} "
                f"ok={ok} is_live={is_live} duration_ms={elapsed_ms:.1f} "
                f"alloc_delta_bytes={delta if delta is not None else '-'} "
                f"platform_inflight={platform_inflight}"
            )
        finally:
            _status_inflight_exit(platform)

        if error is not None:
            raise error
        return result

    traced._status_check_trace = True  # marker: re-instrumentation is a no-op
    return traced


def _instrument_status_check(instance: "PlatformHandler") -> None:
    """Apply observation-only tracing to a cached handler instance."""
    if getattr(instance.get_stream_info, "_status_check_trace", False):
        return
    original = instance.get_stream_info
    instance.get_stream_info = _status_check_trace(instance, original)


class PlatformHandler(abc.ABC):
    _registry: dict[str, type["PlatformHandler"]] = {}
    _instances: dict[InstanceKey, "PlatformHandler"] = {}
    _lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        proxy: str | None = None,
        cookies: str | None = None,
        record_quality: str | None = None,
        platform: str | None = None,
        username: str | None = None,
        password: str | None = None,
        account_type: str | None = None,
    ) -> None:
        self.proxy = proxy
        self.cookies = cookies
        self.record_quality = record_quality
        self.platform = platform
        self.username = username
        self.password = password
        self.account_type = account_type
        self._active_status_checks = 0

    @abc.abstractmethod
    async def get_stream_info(self, live_url: str) -> StreamData:
        """
        Abstract method to get stream information based on the live URL.
        """
        pass

    def release_status_check_state(self) -> None:
        """Drop transient stream state retained across periodic checks."""
        if getattr(self, "_active_status_checks", 0) > 0:
            return
        if hasattr(self, "live_stream"):
            self.live_stream = None

    def begin_status_check(self) -> None:
        self._active_status_checks = getattr(self, "_active_status_checks", 0) + 1

    def end_status_check(self) -> None:
        self._active_status_checks = max(getattr(self, "_active_status_checks", 0) - 1, 0)
        self.release_status_check_state()

    @classmethod
    def register(cls: type[T], *patterns: str) -> type[T]:
        """
        Register a platform handler class with one or more URL patterns.
        """
        with cls._lock:
            for pattern in patterns:
                cls._registry[pattern] = cls
        return cls

    @classmethod
    def get_registered_patterns(cls) -> dict[str, type["PlatformHandler"]]:
        """
        Return a copy of the registered URL patterns and their corresponding handler classes.
        """
        with cls._lock:
            return cls._registry.copy()

    @classmethod
    def _get_instance_key(
        cls, proxy: str | None, cookies: str | None, record_quality: str, platform: str | None,
        username: str | None = None, password: str | None = None, account_type: str | None = None
    ) -> InstanceKey:
        """
        Generate a unique key for each instance based on the provided parameters.
        """
        return proxy, cookies, record_quality, platform, username, password, account_type

    @classmethod
    def _get_handler_class(cls, live_url: str) -> type["PlatformHandler"] | None:
        """
        Find the appropriate handler class based on the live URL.
        """
        registered_patterns = cls.get_registered_patterns()
        for pattern, handler_class in registered_patterns.items():
            if re.search(pattern, live_url):
                return handler_class
        return None

    @classmethod
    def get_handler_instance(
        cls,
        live_url: str,
        proxy: str | None = None,
        cookies: str | None = None,
        record_quality: str | None = None,
        platform: str | None = None,
        username: str | None = None,
        password: str | None = None,
        account_type: str | None = None,
    ) -> Optional["PlatformHandler"]:
        """
        Get or create an instance of a platform handler based on the live URL and other parameters.
        """
        handler_class = cls._get_handler_class(live_url)
        if not handler_class:
            return None

        instance_key = cls._get_instance_key(proxy, cookies, record_quality, platform, username, password, account_type)
        if instance_key not in cls._instances:
            init_signature = inspect.signature(handler_class.__init__)
            handler_kwargs: dict[str, Any] = {
                "proxy": proxy,
                "cookies": cookies,
                "record_quality": record_quality,
                "platform": platform,
                "username": username,
                "password": password,
                "account_type": account_type,
            }
            filtered_kwargs = {k: v for k, v in handler_kwargs.items() if k in init_signature.parameters}
            with cls._lock:
                if instance_key not in cls._instances:
                    instance = handler_class(**filtered_kwargs)
                    _instrument_status_check(instance)
                    cls._instances[instance_key] = instance

        return cls._instances[instance_key]
