# ruff: noqa: PT009, PT019  # unittest-style assertions are intentional here
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.qt.main_window import MainWindow


class MainWindowShutdownTests(unittest.TestCase):
    @patch("app.qt.main_window.tr", side_effect=lambda key, default=None: default or key)
    @patch("app.qt.main_window.asyncio.ensure_future")
    @patch("app.qt.components.confirm_dialog.QtConfirmDialog.confirm", return_value=True)
    def test_close_event_does_not_disable_monitor_status(self, _confirm, mock_ensure_future, _tr):
        rec_a = types.SimpleNamespace(rec_id="a", monitor_status=True, is_recording=False)
        rec_b = types.SimpleNamespace(rec_id="b", monitor_status=True, is_recording=True)

        predictor_metrics = MagicMock()
        record_manager = types.SimpleNamespace(
            recordings=[rec_a, rec_b],
            predictor_metrics=predictor_metrics,
            stop_recording=MagicMock(),
        )
        event_bus = types.SimpleNamespace(publish=MagicMock())

        window = MainWindow.__new__(MainWindow)
        window.app = types.SimpleNamespace(
            recording_enabled=True,
            event_bus=event_bus,
            record_manager=record_manager,
        )
        window._is_shutting_down = False
        window.setEnabled = MagicMock()
        window.show_toast = MagicMock()
        window._perform_shutdown = MagicMock(return_value="shutdown-coro")

        event = MagicMock()

        MainWindow.closeEvent(window, event)

        self.assertTrue(rec_a.monitor_status)
        self.assertTrue(rec_b.monitor_status)
        predictor_metrics.interrupt_pending_operations.assert_called_once_with()
        record_manager.stop_recording.assert_any_call(rec_a, manually_stopped=True)
        record_manager.stop_recording.assert_any_call(rec_b, manually_stopped=True)
        event.ignore.assert_called_once_with()
        mock_ensure_future.assert_called_once_with("shutdown-coro")


class PerformShutdownTests(unittest.IsolatedAsyncioTestCase):
    def _build_window(self, pending_task_count):
        window = MainWindow.__new__(MainWindow)
        window.app = types.SimpleNamespace(
            event_bus=types.SimpleNamespace(pending_task_count=pending_task_count),
            process_manager=types.SimpleNamespace(ffmpeg_processes=[]),
            record_manager=types.SimpleNamespace(active_recorders={}),
        )
        return window

    async def _run_shutdown(self, window):
        with (
            patch("asyncio.sleep", new=AsyncMock()),
            patch("app.utils.logger.logger") as mock_logger,
            patch("PySide6.QtWidgets.QApplication") as mock_qapp,
        ):
            await window._perform_shutdown()
        return mock_logger, mock_qapp

    async def test_perform_shutdown_quits_when_idle(self):
        window = self._build_window(pending_task_count=lambda: 0)

        mock_logger, mock_qapp = await self._run_shutdown(window)

        mock_qapp.instance().quit.assert_called_once()
        self.assertIn(
            "All background tasks and recordings finished. Safe to exit.",
            "\n".join(str(call) for call in mock_logger.info.call_args_list),
        )

    async def test_perform_shutdown_waits_for_event_bus_pending_tasks(self):
        state = {"pending": 1}

        def pending_task_count():
            value = state["pending"]
            state["pending"] = 0
            return value

        window = self._build_window(pending_task_count)

        mock_logger, mock_qapp = await self._run_shutdown(window)

        mock_qapp.instance().quit.assert_called_once()
        self.assertIn(
            "PendingAsync: 1",
            "\n".join(str(call) for call in mock_logger.info.call_args_list),
        )


if __name__ == "__main__":
    unittest.main()
