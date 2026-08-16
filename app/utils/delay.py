import asyncio
import inspect

from .logger import logger


class DelayedTaskExecutor:
    def __init__(self, app, settings, delay=3):
        self.app = app
        self.settings = settings
        self.save_timer = None
        self.delay = delay

    async def start_task_timer(self, task, *args):
        """Start a timer to save the configuration after a short delay."""
        if self.save_timer:
            self.save_timer.cancel()
            try:
                await self.save_timer
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f"Error cancelling previous save timer: {e}")

        async def _timer_task():
            await asyncio.sleep(self.delay)
            try:
                if inspect.iscoroutinefunction(task):
                    await task(*args)
                else:
                    task(*args)
            except Exception as e:
                logger.error(f"Error executing delayed task {task.__name__}: {e}")

        self.save_timer = asyncio.create_task(_timer_task())
