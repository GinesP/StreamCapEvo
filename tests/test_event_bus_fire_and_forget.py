# ruff: noqa: PT009  # unittest-style assertions are intentional here
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.recording.record_manager import RecordingManager
from app.event_bus import EventBus


class EventBusFireAndForgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_task_executes_happy_path(self):
        bus = EventBus()
        bus.set_loop(asyncio.get_running_loop())
        seen = []

        async def sample(value):
            seen.append(value)

        bus.run_task(sample, "ok")
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        self.assertEqual(seen, ["ok"])

    async def test_run_task_logs_exception_without_raising(self):
        bus = EventBus()
        bus.set_loop(asyncio.get_running_loop())

        async def boom():
            raise RuntimeError("kaboom")

        with self.assertLogs("app.event_bus", level="ERROR") as logs:
            bus.run_task(boom)
            await asyncio.sleep(0)
            await asyncio.sleep(0)

        self.assertIn("EventBus: async task failed for task", "\n".join(logs.output))
        self.assertIn("kaboom", "\n".join(logs.output))

    async def test_cancelled_task_is_not_logged_as_failure(self):
        bus = EventBus()
        bus.set_loop(asyncio.get_running_loop())
        started = asyncio.Event()

        async def cancellable():
            started.set()
            raise asyncio.CancelledError()

        with self.assertNoLogs("app.event_bus", level="ERROR"):
            bus.run_task(cancellable)
            await started.wait()
            await asyncio.sleep(0)


class RecordingManagerPeriodicTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        RecordingManager.set_periodic_task_running(False)

    async def test_periodic_task_logs_exception_without_raising(self):
        manager = RecordingManager.__new__(RecordingManager)
        manager.app = SimpleNamespace(
            settings=SimpleNamespace(
                user_config={"check_live_on_browser_refresh": True}
            ),
            recording_enabled=True,
        )
        manager.periodic_task_started = False
        manager.check_all_live_status = AsyncMock(side_effect=RuntimeError("periodic boom"))
        manager.check_free_space = AsyncMock()

        captured = []

        def capture_task(coro):
            captured.append(coro)
            return SimpleNamespace()

        with patch("app.core.recording.record_manager.asyncio.create_task", side_effect=capture_task):
            await manager.setup_periodic_live_check(interval=1)

        self.assertEqual(len(captured), 1)

        with patch("app.core.recording.record_manager.logger.error") as mock_error:
            await captured[0]

        mock_error.assert_called_once()
        message = mock_error.call_args[0][0]
        self.assertIn("Periodic live check task failed", message)
        self.assertIn("periodic boom", message)


if __name__ == "__main__":
    unittest.main()
