"""Observation-only status-check trace tests.

The status-check instrumentation wraps each cached platform handler's
``get_stream_info`` to emit STATUS-level log lines (identity, reuse, timing,
success classification, in-flight counts, coarse tracemalloc delta).

These tests prove the wrapper never changes results, exceptions, or
lifecycle semantics.
"""

import asyncio
import os
import tracemalloc
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from app.core.platforms.platform_handlers import StreamData
from app.core.platforms.platform_handlers.base import (
    PlatformHandler,
    _instrument_status_check,
    _status_check_context,
    _status_inflight,
    reset_status_check_context,
    set_status_check_context,
)


class _ProbeHandler(PlatformHandler):
    platform = "probe"

    def __init__(self):
        super().__init__(platform="probe")
        self.live_stream = None

    async def get_stream_info(self, live_url):
        if self.live_stream is None:
            self.live_stream = object()
        return StreamData(platform="probe", anchor_name="Anchor", is_live=True, record_url=live_url)


class _SlowProbeHandler(PlatformHandler):
    platform = "probe-slow"

    def __init__(self):
        super().__init__(platform="probe-slow")
        self.live_stream = None

    async def get_stream_info(self, live_url):
        self.live_stream = object()
        await asyncio.sleep(0.05)
        return StreamData(platform="probe-slow", anchor_name="Anchor", is_live=True, record_url=live_url)


class _FailingProbeHandler(PlatformHandler):
    """Mimics trace_error_decorator, which swallows exceptions into [].

    Real handlers never raise; failures surface as falsy results, so the
    wrapper must classify ok=False by inspecting the result.
    """

    platform = "probe-fail"

    def __init__(self):
        super().__init__(platform="probe-fail")
        self.live_stream = None

    async def get_stream_info(self, live_url) -> Any:
        return []


class _RaisingProbeHandler(PlatformHandler):
    """A handler that does raise: the wrapper must re-raise unchanged."""

    platform = "probe-raise"

    def __init__(self):
        super().__init__(platform="probe-raise")
        self.live_stream = None

    async def get_stream_info(self, live_url):
        raise RuntimeError("boom")


class StatusCheckTraceTests(unittest.TestCase):
    def setUp(self):
        self.logger = MagicMock()
        self._logger_patch = patch(
            "app.core.platforms.platform_handlers.base.logger", new=self.logger
        )
        self._logger_patch.start()
        self.addCleanup(self._logger_patch.stop)
        _status_inflight.clear()
        self.addCleanup(_status_inflight.clear)

    @staticmethod
    def _instrumented(handler):
        _instrument_status_check(handler)
        return handler

    def _messages(self, tag):
        return [
            call.args[1]
            for call in self.logger.log.call_args_list
            if call.args[0] == "STATUS" and call.args[1].startswith(f"CHECK {tag}")
        ]

    def test_logs_begin_and_end_with_identity(self):
        handler = self._instrumented(_ProbeHandler())
        handler.live_stream = object()  # cached streamget client from a prior check
        result = asyncio.run(handler.get_stream_info("https://probe.example/live"))

        begin = self._messages("begin")
        end = self._messages("end")
        self.assertEqual(len(begin), 1)
        self.assertEqual(len(end), 1)
        self.assertIn("platform=probe", begin[0])
        self.assertIn("handler=_ProbeHandler", begin[0])
        self.assertIn("handler_id=0x", begin[0])
        self.assertIn("url=https://probe.example/live", begin[0])
        self.assertIn("reused=True", begin[0])
        self.assertIn("live_stream_id=0x", begin[0])
        self.assertIn("active_checks=0", begin[0])
        self.assertIn("platform_inflight=1", begin[0])
        self.assertIn("ok=True", end[0])
        self.assertIn("is_live=True", end[0])
        self.assertIn("duration_ms=", end[0])
        # Result passthrough is unchanged
        self.assertIsNotNone(result.anchor_name)

    def test_new_live_stream_reports_not_reused(self):
        handler = self._instrumented(_ProbeHandler())
        asyncio.run(handler.get_stream_info("https://probe.example/live"))

        begin = self._messages("begin")[0]
        self.assertIn("reused=False", begin)
        self.assertIn("live_stream_id=-", begin)

    def test_failed_result_classified_ok_false(self):
        handler = self._instrumented(_FailingProbeHandler())
        result = asyncio.run(handler.get_stream_info("https://probe.example/live"))

        end = self._messages("end")[0]
        self.assertEqual(result, [])
        self.assertIn("ok=False", end)
        self.assertIn("is_live=None", end)

    def test_exception_propagates_and_is_logged(self):
        handler = self._instrumented(_RaisingProbeHandler())
        with self.assertRaises(RuntimeError):
            asyncio.run(handler.get_stream_info("https://probe.example/live"))

        error = self._messages("error")[0]
        self.assertIn("exc=RuntimeError", error)
        self.assertIn("duration_ms=", error)

    def test_inflight_tracking_drains_to_zero(self):
        first = self._instrumented(_SlowProbeHandler())
        second = self._instrumented(_SlowProbeHandler())

        async def run_both():
            await asyncio.gather(
                first.get_stream_info("https://probe.example/a"),
                second.get_stream_info("https://probe.example/b"),
            )

        asyncio.run(run_both())

        inflight_values = [
            int(call.args[1].split("platform_inflight=")[1].split()[0])
            for call in self.logger.log.call_args_list
            if call.args[0] == "STATUS" and "platform_inflight=" in call.args[1]
        ]
        self.assertIn(2, inflight_values)
        self.assertEqual(_status_inflight.get("probe-slow", 0), 0)

    def test_inflight_warns_above_threshold(self):
        started = asyncio.Event()

        class _BurstHandler(PlatformHandler):
            platform = "probe-burst"

            def __init__(self):
                super().__init__(platform="probe-burst")
                self.live_stream = None

            async def get_stream_info(self, live_url):
                await started.wait()
                return StreamData(
                    platform="probe-burst", anchor_name="A", is_live=True, record_url=live_url
                )

        handlers = [self._instrumented(_BurstHandler()) for _ in range(9)]

        async def run_burst():
            tasks = [asyncio.create_task(h.get_stream_info("u")) for h in handlers]
            await asyncio.sleep(0.05)  # let all 9 enter the trace wrapper
            started.set()
            await asyncio.gather(*tasks)

        asyncio.run(run_burst())

        warnings = [str(call.args[0]) for call in self.logger.warning.call_args_list]
        self.assertTrue(any("in-flight warning" in w for w in warnings))
        self.assertEqual(_status_inflight.get("probe-burst", 0), 0)

    def test_tracemalloc_delta_when_active(self):
        if not tracemalloc.is_tracing():
            tracemalloc.start()
            self.addCleanup(tracemalloc.stop)
        handler = self._instrumented(_ProbeHandler())
        asyncio.run(handler.get_stream_info("https://probe.example/live"))

        begin = self._messages("begin")[0]
        end = self._messages("end")[0]
        self.assertIn("tracemalloc=on", begin)
        self.assertRegex(end, r"alloc_delta_bytes=-?\d+")

    def test_tracemalloc_off_marks_off(self):
        handler = self._instrumented(_ProbeHandler())
        with patch(
            "app.core.platforms.platform_handlers.base.tracemalloc.is_tracing",
            return_value=False,
        ):
            asyncio.run(handler.get_stream_info("https://probe.example/live"))

        begin = self._messages("begin")[0]
        end = self._messages("end")[0]
        self.assertIn("tracemalloc=off", begin)
        self.assertIn("alloc_delta_bytes=-", end)

    def test_rec_id_flows_into_trace_lines(self):
        handler = self._instrumented(_ProbeHandler())
        token = set_status_check_context("rec-xyz")
        try:
            asyncio.run(handler.get_stream_info("https://probe.example/live"))
        finally:
            reset_status_check_context(token)

        self.assertIn("rec_id=rec-xyz", self._messages("begin")[0])
        self.assertIn("rec_id=rec-xyz", self._messages("end")[0])

    def test_fetch_stream_passes_rec_id_through(self):
        from app.core.recording.stream_manager import LiveStreamRecorder

        app = MagicMock()
        app.language_manager.language = {}
        app.settings = MagicMock(spec=["user_config", "accounts_config", "cookies_config"])
        app.settings.user_config = {}
        app.settings.accounts_config = {}
        app.settings.cookies_config = {}
        app.subprocess_start_up_info = None

        recording = MagicMock()
        recording.is_checking = True
        recording.rec_id = "rec-777"
        recording_info = {
            "platform": "probe",
            "platform_key": "probe",
            "live_url": "https://probe.example/live",
            "output_dir": os.getcwd(),
            "quality": "HD",
        }

        recorder = LiveStreamRecorder(app, recording, recording_info)
        handler = self._instrumented(_ProbeHandler())
        with patch(
            "app.core.recording.stream_manager.platform_handlers.get_platform_handler",
            return_value=handler,
        ):
            asyncio.run(recorder.fetch_stream())

        self.assertIn("rec_id=rec-777", self._messages("begin")[0])
        self.assertIn("rec_id=rec-777", self._messages("end")[0])
        self.assertFalse(recording.is_checking)


_REGISTRY_PATTERN = r"trace-probe\.example"
_REGISTRY_PROXY = "trace-probe-test-proxy"


class _RegistryProbeHandler(PlatformHandler):
    platform = "registry-probe"

    def __init__(self, proxy=None, cookies=None, record_quality=None, platform=None):
        super().__init__(proxy, cookies, record_quality, platform)
        self.live_stream = None

    async def get_stream_info(self, live_url):
        return StreamData(
            platform="registry-probe", anchor_name="R", is_live=False, record_url=live_url
        )


_RegistryProbeHandler.register(_REGISTRY_PATTERN)


class RegistryInstrumentationTests(unittest.TestCase):
    def test_cached_handlers_are_instrumented_once(self):
        key = PlatformHandler._get_instance_key(_REGISTRY_PROXY, None, None, None, None, None, None)

        def cleanup():
            with PlatformHandler._lock:
                PlatformHandler._instances.pop(key, None)
                PlatformHandler._registry.pop(_REGISTRY_PATTERN, None)

        self.addCleanup(cleanup)

        first = PlatformHandler.get_handler_instance(
            "https://trace-probe.example/live", proxy=_REGISTRY_PROXY
        )
        second = PlatformHandler.get_handler_instance(
            "https://trace-probe.example/live", proxy=_REGISTRY_PROXY
        )

        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertIsNotNone(getattr(first.get_stream_info, "_status_check_trace", None))
        self.assertEqual(first.get_stream_info._status_check_trace, True)


if __name__ == "__main__":
    unittest.main()
