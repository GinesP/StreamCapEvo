"""
EventBus: Framework-agnostic publish/subscribe system.

Replaces Flet's page.pubsub and page.run_task() with a decoupled
event system that works with any UI framework (Flet, Qt, etc.).
"""

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventBus:
    """
    A thread-safe, framework-agnostic event bus for pub/sub communication.

    Replaces:
        - page.pubsub.subscribe_topic(topic, callback)
        - page.pubsub.send_others_on_topic(topic, data)
        - page.run_task(coro, *args)
    """

    def __init__(self, page=None):
        self._subscribers: dict[str, list[Callable]] = defaultdict(list)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._page = page  # Flet page for bridging if needed during transition

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Set the asyncio event loop used for scheduling async callbacks."""
        self._loop = loop

    def set_page(self, page):
        """Set the Flet page instance for bridging to its pubsub system."""
        self._page = page

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    # ── Subscribe / Unsubscribe ──────────────────────────────────────

    def subscribe(self, topic: str, callback: Callable):
        """Subscribe a callback to a topic.

        Args:
            topic: The event topic name (e.g. 'update', 'delete', 'add').
            callback: A sync or async callable to invoke when the topic fires.
        """
        if callback not in self._subscribers[topic]:
            self._subscribers[topic].append(callback)
            logger.debug(f"EventBus: subscribed to '{topic}': {callback.__qualname__}")

    def unsubscribe(self, topic: str, callback: Callable):
        """Remove a callback from a topic."""
        try:
            self._subscribers[topic].remove(callback)
            logger.debug(f"EventBus: unsubscribed from '{topic}': {callback.__qualname__}")
        except ValueError:
            logger.warning(
                f"EventBus: tried to unsubscribe {callback.__qualname__} "
                f"from '{topic}' but it was not subscribed."
            )

    def unsubscribe_all(self, topic: str | None = None):
        """Remove all subscribers, optionally for a specific topic only."""
        if topic:
            self._subscribers[topic].clear()
        else:
            self._subscribers.clear()

    # ── Publish ──────────────────────────────────────────────────────

    def publish(self, topic: str, *args, **kwargs):
        """Publish an event to all subscribers of a topic.

        Replaces: page.pubsub.send_others_on_topic(topic, data)

        For async callbacks, the coroutine is scheduled on the event loop.
        For sync callbacks, they are called directly.

        Args:
            topic: The event topic name.
            *args: Positional arguments to pass to subscribers.
            **kwargs: Keyword arguments to pass to subscribers.
        """
        # Bridge to Flet's pubsub if the page is set (transition period)
        if self._page:
            try:
                # Use getattr just in case the bridge is being tested without full Page object
                pubsub = getattr(self._page, "pubsub", None)
                if pubsub:
                    # Bridge only the first data argument if present (Flet pubsub limit)
                    data = args[0] if args else None
                    pubsub.send_others_on_topic(topic, data)
            except Exception as e:
                logger.debug(f"EventBus: Failed to bridge to Flet pubsub: {e}")

        subscribers = self._subscribers.get(topic, [])
        if not subscribers:
            return

        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    self._schedule_async(callback, topic, *args, **kwargs)
                else:
                    callback(topic, *args, **kwargs)
            except Exception as e:
                logger.error(
                    f"EventBus: error in subscriber {callback.__qualname__} "
                    f"for topic '{topic}': {e}"
                )

    def _schedule_async(self, callback: Callable, topic: str, *args, **kwargs):
        """Schedule an async callback on the event loop."""
        loop = self._loop
        if loop is None:
            logger.warning(
                f"EventBus: no event loop set, cannot schedule async callback "
                f"{callback.__qualname__} for topic '{topic}'"
            )
            return

        if loop.is_running():
            loop.call_soon_threadsafe(
                asyncio.ensure_future, callback(topic, *args, **kwargs)
            )
        else:
            logger.warning(
                f"EventBus: event loop is not running, cannot schedule "
                f"{callback.__qualname__} for topic '{topic}'"
            )

    # ── run_task replacement ─────────────────────────────────────────

    def run_task(self, coro_func: Callable, *args, **kwargs):
        """Schedule an async coroutine for execution.

        Replaces: page.run_task(coro, *args)

        Args:
            coro_func: An async function (not a coroutine object).
            *args: Arguments to pass to the coroutine function.
            **kwargs: Keyword arguments to pass to the coroutine function.
        """
        loop = self._loop
        if loop is None:
            logger.warning(
                f"EventBus: no event loop set, cannot run task "
                f"{coro_func.__qualname__}"
            )
            return

        try:
            if loop.is_running():
                loop.call_soon_threadsafe(
                    asyncio.ensure_future, coro_func(*args, **kwargs)
                )
            else:
                logger.warning(
                    f"EventBus: event loop is not running, cannot run task "
                    f"{coro_func.__qualname__}"
                )
        except Exception as e:
            logger.error(f"EventBus: error scheduling task {coro_func.__qualname__}: {e}")

    # ── Debug helpers ────────────────────────────────────────────────

    def subscriber_count(self, topic: str) -> int:
        """Return the number of subscribers for a given topic."""
        return len(self._subscribers.get(topic, []))

    @property
    def topics(self) -> list[str]:
        """Return a list of all topics with active subscribers."""
        return [t for t, subs in self._subscribers.items() if subs]

    def diagnostic_report(self) -> dict:
        """Return a snapshot of current subscriber state for diagnostics.

        Returns:
            dict with keys: topics (per-topic counts), total_subscribers, topic_count.
        """
        topics: dict[str, int] = {}
        total = 0
        for topic, subs in self._subscribers.items():
            if subs:
                topics[topic] = len(subs)
                total += len(subs)
        return {
            "topics": topics,
            "total_subscribers": total,
            "topic_count": len(topics),
        }

    def __repr__(self) -> str:
        topic_info = ", ".join(f"{t}={len(s)}" for t, s in self._subscribers.items() if s)
        return f"<EventBus topics=[{topic_info}]>"
