import asyncio
import os
import threading

from ...utils.logger import logger


import queue

class BackgroundService:

    _instance = None
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = BackgroundService()
        return cls._instance
    
    def __init__(self):
        self.tasks = queue.Queue()
        self.is_running = False
        self.worker_thread = None
        self._stop_event = threading.Event()
    
    def add_task(self, task_func, *args, **kwargs):
        self.tasks.put((task_func, args, kwargs))
        logger.info(f"Added background task: {task_func.__name__}")
        
        if not self.is_running:
            self.start()
    
    def start(self):
        if self.is_running:
            return
            
        self.is_running = True
        self._stop_event.clear()
        self.worker_thread = threading.Thread(target=self._process_tasks, daemon=True)
        self.worker_thread.start()
        logger.info("Background service started")
    
    def stop(self):
        self._stop_event.set()
        self.is_running = False

    def active_task_count(self) -> int:
        """Number of background tasks queued or currently being executed."""
        return self.tasks.unfinished_tasks

    def is_worker_alive(self) -> bool:
        return self.worker_thread is not None and self.worker_thread.is_alive()

    def join(self, timeout: float | None = None) -> bool:
        """Wait for the worker thread to finish; return True if it exited."""
        if not self.is_worker_alive():
            return True
        self.worker_thread.join(timeout)
        return not self.is_worker_alive()

    def _process_tasks(self):
        # Keep processing until a stop was requested AND the queue is drained,
        # so work enqueued during shutdown still completes before exiting.
        while not self._stop_event.is_set() or not self.tasks.empty():
            try:
                # Wait for a task with a timeout to allow checking stop_event
                task_func, args, kwargs = self.tasks.get(timeout=1.0)
                try:
                    logger.info(f"Executing background task: {task_func.__name__}")
                    task_func(*args, **kwargs)
                    logger.info(f"Background task completed: {task_func.__name__}")
                except Exception as e:
                    logger.error(f"Background task execution failed: {e}")
                finally:
                    self.tasks.task_done()
            except queue.Empty:
                continue
        
        logger.info("Background service worker stopped")
        self.is_running = False


class AsyncProcessManager:
    def __init__(self):
        self.ffmpeg_processes = []

    def add_process(self, process):
        self.ffmpeg_processes.append(process)

    def remove_process(self, process):
        if process in self.ffmpeg_processes:
            self.ffmpeg_processes.remove(process)

    async def cleanup(self):
        for process in self.ffmpeg_processes[:]:
            try:
                if process.returncode is None:
                    logger.debug(f"Terminating process {process.pid}")
                    if os.name == "nt":
                        if process.stdin:
                            process.stdin.write(b"q")
                            await process.stdin.drain()
                    else:
                        process.terminate()

                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        logger.warning(f"Process {process.pid} did not terminate, killing it")
                        process.kill()
                        await process.wait()

                self.remove_process(process)
            except Exception as e:
                logger.error(f"Error cleaning up process: {e}")
                self.remove_process(process)

        logger.debug("All processes cleaned up")
