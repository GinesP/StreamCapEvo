"""Runtime warning capture for long-running app sessions.

Installs a ``warnings.showwarning`` hook that mirrors Python warnings (e.g.
``RuntimeWarning: coroutine ... was never awaited``) into the loguru app log
(``logs/streamget.log``) so they remain observable during overnight runs when
no console is attached.

Observation only: default warning filters are untouched and the previous
``showwarning`` handler is still called, preserving stderr behavior.
"""

import warnings
from collections import OrderedDict

from app.utils.logger import logger

_original_showwarning = None
_seen: OrderedDict[tuple, int] = OrderedDict()
_max_entries = 512


def _warning_key(message, category, filename, lineno) -> tuple:
    return (category.__name__, str(message), filename, lineno)


def _showwarning_handler(message, category, filename, lineno, file=None, line=None):
    key = _warning_key(message, category, filename, lineno)
    if key in _seen:
        _seen[key] += 1
        _seen.move_to_end(key)
    else:
        _seen[key] = 1
        logger.warning(f"Python warning: {category.__name__}: {message} (source: {filename}:{lineno})")
        if len(_seen) > _max_entries:
            evicted_key, evicted_count = _seen.popitem(last=False)
            if evicted_count > 1:
                logger.debug(
                    f"Warning {evicted_key[0]} at {evicted_key[2]}:{evicted_key[3]} "
                    f"repeated {evicted_count}x before being dropped (capped at {_max_entries} unique)"
                )
    if _original_showwarning is not None:
        _original_showwarning(message, category, filename, lineno, file=file, line=line)


def install_warning_capture(max_entries: int = 512) -> None:
    """Route Python warnings into the loguru app log.

    Idempotent. Call once at application startup, before starting the event
    loop, so runtime warnings (including asyncio coroutine warnings) are
    captured. Default warning filters and stderr output are preserved.
    """
    global _original_showwarning, _seen, _max_entries
    if _original_showwarning is None:
        _original_showwarning = warnings.showwarning
    _max_entries = max_entries
    _seen = OrderedDict()
    warnings.showwarning = _showwarning_handler


def uninstall_warning_capture() -> None:
    """Restore the previously installed ``warnings.showwarning`` hook."""
    global _original_showwarning, _seen
    if _original_showwarning is not None:
        warnings.showwarning = _original_showwarning
    _original_showwarning = None
    _seen = OrderedDict()
