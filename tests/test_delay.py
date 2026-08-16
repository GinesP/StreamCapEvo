# ruff: noqa: PT009  # unittest-style assertions are intentional here
import asyncio
import unittest
from typing import cast
from unittest.mock import patch

from app.utils.delay import DelayedTaskExecutor


class DelayedTaskExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_task_executes_after_delay(self):
        seen = []
        executor = DelayedTaskExecutor(app=None, settings=None, delay=0)

        def task(value):
            seen.append(value)

        await executor.start_task_timer(task, "ok")
        save_timer = cast(asyncio.Task, executor.save_timer)
        await save_timer

        self.assertEqual(seen, ["ok"])

    async def test_async_task_failure_is_logged(self):
        executor = DelayedTaskExecutor(app=None, settings=None, delay=0)

        async def failing_task():
            raise RuntimeError("boom")

        with patch("app.utils.delay.logger.error") as mock_error:
            await executor.start_task_timer(failing_task)
            save_timer = cast(asyncio.Task, executor.save_timer)
            await save_timer

        mock_error.assert_called_once()
        message = mock_error.call_args[0][0]
        self.assertIn("Error executing delayed task failing_task", message)
        self.assertIn("boom", message)

    async def test_previous_timer_is_cancelled_before_replacement(self):
        executor = DelayedTaskExecutor(app=None, settings=None, delay=0)
        first_started = asyncio.Event()
        block = asyncio.Event()

        async def first_task():
            first_started.set()
            await block.wait()

        async def second_task():
            return None

        await executor.start_task_timer(first_task)
        first_timer = cast(asyncio.Task, executor.save_timer)
        self.assertIsNotNone(first_timer)
        await first_started.wait()

        await executor.start_task_timer(second_task)

        self.assertTrue(first_timer.cancelled())
        self.assertIsNot(first_timer, executor.save_timer)

        save_timer = cast(asyncio.Task, executor.save_timer)
        await save_timer


if __name__ == "__main__":
    unittest.main()
