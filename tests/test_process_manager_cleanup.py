import unittest
from unittest.mock import mock_open
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.recording.stream_manager import LiveStreamRecorder
from app.core.runtime.process_manager import AsyncProcessManager
from app.models.recording.recording_status_model import RecordingStatus


class AsyncProcessManagerTests(unittest.TestCase):
    def test_remove_process_drops_finished_wrapper(self):
        manager = AsyncProcessManager()
        process = MagicMock()

        manager.add_process(process)
        manager.remove_process(process)

        self.assertEqual(manager.ffmpeg_processes, [])


class LiveStreamRecorderProcessCleanupTests(unittest.IsolatedAsyncioTestCase):
    def _build_app(self):
        app = MagicMock()
        app.settings = SimpleNamespace(
            user_config={
                "convert_to_mp4": False,
                "execute_custom_script": False,
                "default_platform_with_proxy": "",
                "enable_proxy": False,
            },
            accounts_config={},
            cookies_config={},
        )
        app.language_manager = SimpleNamespace(language={"recording_manager": {}, "stream_manager": {}})
        app.subprocess_start_up_info = None
        app.recording_enabled = True
        app.event_bus = SimpleNamespace(publish=MagicMock(), run_task=MagicMock())
        app.add_ffmpeg_process = MagicMock()
        app.remove_ffmpeg_process = MagicMock()
        return app

    def _build_recording(self):
        recording = MagicMock()
        recording.rec_id = "rec-1"
        recording.force_stop = False
        recording.is_recording = True
        recording.monitor_status = False
        recording.title = "Title"
        recording.display_title = "Display"
        recording.streamer_name = "Streamer"
        recording.recording_dir = None
        return recording

    def _build_recording_info(self):
        return {
            "platform_key": "demo",
            "platform": "demo",
            "live_url": "https://example.com/live",
            "output_dir": ".",
            "quality": "OD",
            "save_format": "ts",
        }

    @patch("app.core.recording.stream_manager.asyncio.create_subprocess_exec")
    async def test_start_ffmpeg_removes_finished_process(self, mock_create_subprocess_exec):
        process = MagicMock()
        process.returncode = 0
        process.communicate = AsyncMock(return_value=(b"", b""))
        mock_create_subprocess_exec.return_value = process

        app = self._build_app()
        recording = self._build_recording()
        recorder = LiveStreamRecorder(app, recording, self._build_recording_info())
        recorder.remove_active_recorder = AsyncMock()
        recorder.recheck_live_status = AsyncMock()

        result = await recorder.start_ffmpeg(
            record_name="demo",
            live_url="https://example.com/live",
            record_url="https://example.com/stream.m3u8",
            ffmpeg_command=["ffmpeg", "-i", "in", "out.ts"],
            save_type="ts",
        )

        self.assertTrue(result)
        app.add_ffmpeg_process.assert_called_once_with(process)
        app.remove_ffmpeg_process.assert_called_once_with(process)
        self.assertEqual(recording.status_info, RecordingStatus.STOPPED_MONITORING)

    @patch("app.core.recording.stream_manager.open", new_callable=mock_open)
    @patch("app.core.recording.stream_manager.os.path.getsize", return_value=1)
    @patch("app.core.recording.stream_manager.os.path.exists", return_value=True)
    @patch("app.core.recording.stream_manager.asyncio.create_subprocess_exec")
    async def test_transcode_removes_finished_process(
        self,
        mock_create_subprocess_exec,
        _mock_exists,
        _mock_getsize,
        _mock_open,
    ):
        process = MagicMock()
        process.returncode = 0
        process.communicate = AsyncMock(return_value=(b"", b""))
        mock_create_subprocess_exec.return_value = process

        app = self._build_app()
        recording = self._build_recording()
        recorder = LiveStreamRecorder(app, recording, self._build_recording_info())
        recorder._delete_with_retry = AsyncMock(return_value=True)

        await recorder._do_converts_mp4("video.ts", is_original_delete=True)

        app.add_ffmpeg_process.assert_called_once_with(process)
        app.remove_ffmpeg_process.assert_called_once_with(process)
