"""TikTok status-check stream isolation tests.

TikTokHandler used to cache a streamget.TikTokLiveStream instance on
``self.live_stream`` and reuse it across concurrent status checks, which
correlated with httpx/_models.py allocation growth in the periodic
diagnostics. The mitigation creates a fresh stream object per check for
TikTok only; every other platform keeps the cached-instance pattern.

These tests prove the fresh-per-check behavior, the no-shared-state
property under concurrency, and that result/enrichment semantics are
preserved.
"""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from streamget import StreamData

from app.core.platforms.platform_handlers.handlers import DouyinHandler, TikTokHandler

_WEB_PAYLOAD = {
    "LiveRoom": {
        "liveRoomUserInfo": {
            "user": {"avatarThumb": {"url_list": ["https://av.example/1.jpg"]}},
        },
        "liveRoom": {"cover": {"url_list": ["https://cv.example/2.jpg"]}},
    },
}

_DEFAULT_RESULT = StreamData(
    platform="TikTok", anchor_name="Anchor-user", is_live=True, record_url="https://play.example/x.m3u8"
)


class _StreamStub:
    """Minimal async stand-in for streamget live-stream fetchers."""

    def __init__(self, proxy_addr=None, cookies=None, payload=None, result=None):
        self.proxy_addr = proxy_addr
        self.cookies = cookies
        self.fetch_web_stream_data = AsyncMock(return_value=payload if payload is not None else _WEB_PAYLOAD)
        self.fetch_app_stream_data = AsyncMock(return_value=payload if payload is not None else _WEB_PAYLOAD)
        self.fetch_stream_url = AsyncMock(return_value=result if result is not None else _DEFAULT_RESULT)


class TikTokHandlerIsolationTests(unittest.TestCase):
    def setUp(self):
        self.created = []

        def factory(*args, **kwargs):
            stub = _StreamStub(*args, **kwargs)
            self.created.append(stub)
            return stub

        self.stream_patch = patch(
            "app.core.platforms.platform_handlers.handlers.streamget.TikTokLiveStream",
            side_effect=factory,
        )
        self.stream_class = self.stream_patch.start()
        self.addCleanup(self.stream_patch.stop)

    def test_creates_fresh_stream_per_check_and_never_caches(self):
        handler = TikTokHandler(proxy="http://proxy:8080", cookies="tk-cookie")
        asyncio.run(handler.get_stream_info("https://www.tiktok.com/@anchor/live"))
        asyncio.run(handler.get_stream_info("https://www.tiktok.com/@anchor/live"))

        self.assertEqual(self.stream_class.call_count, 2)
        self.assertIsNone(handler.live_stream)
        self.assertEqual(len(self.created), 2)
        # Handler config still flows into every fresh stream object.
        self.assertEqual(self.created[0].proxy_addr, "http://proxy:8080")
        self.assertEqual(self.created[0].cookies, "tk-cookie")
        self.assertEqual(self.created[1].proxy_addr, "http://proxy:8080")

    def test_concurrent_checks_do_not_share_stream_object(self):
        handler = TikTokHandler()

        async def run_both():
            await asyncio.gather(
                handler.get_stream_info("https://www.tiktok.com/@a/live"),
                handler.get_stream_info("https://www.tiktok.com/@b/live"),
            )

        asyncio.run(run_both())

        self.assertEqual(self.stream_class.call_count, 2)
        self.assertIsNot(self.created[0], self.created[1])
        # Each check drives its own stream object end-to-end.
        self.created[0].fetch_web_stream_data.assert_awaited_once()
        self.created[1].fetch_web_stream_data.assert_awaited_once()
        self.created[0].fetch_stream_url.assert_awaited_once()
        self.created[1].fetch_stream_url.assert_awaited_once()

    def test_result_passthrough_preserved(self):
        handler = TikTokHandler(record_quality="HD")
        result = asyncio.run(handler.get_stream_info("https://www.tiktok.com/@anchor/live"))

        self.assertIs(result, self.created[0].fetch_stream_url.return_value)
        self.created[0].fetch_stream_url.assert_awaited_once_with(_WEB_PAYLOAD, "HD")

    def test_avatar_cover_enrichment_preserved(self):
        handler = TikTokHandler()
        result = asyncio.run(handler.get_stream_info("https://www.tiktok.com/@anchor/live"))

        self.assertEqual(result.extra, {"avatar": "https://av.example/1.jpg", "cover": "https://cv.example/2.jpg"})

    def test_error_path_returns_empty_list(self):
        # trace_error_decorator swallows handler exceptions into [] (same as
        # every platform): a fresh-per-check stream must not alter that.
        handler = TikTokHandler()
        self.created.clear()

        def factory(*args, **kwargs):
            stub = _StreamStub(*args, **kwargs)
            stub.fetch_web_stream_data.side_effect = RuntimeError("network down")
            return stub

        with patch(
            "app.core.platforms.platform_handlers.handlers.streamget.TikTokLiveStream",
            side_effect=factory,
        ):
            result = asyncio.run(handler.get_stream_info("https://www.tiktok.com/@anchor/live"))

        self.assertEqual(result, [])


class OtherPlatformsKeepCachingTests(unittest.TestCase):
    """Guard: the isolation change must be TikTok-only."""

    def test_douyin_handler_still_caches_live_stream(self):
        created = []

        def factory(*args, **kwargs):
            stub = _StreamStub(*args, **kwargs)
            created.append(stub)
            return stub

        with patch(
            "app.core.platforms.platform_handlers.handlers.streamget.DouyinLiveStream",
            side_effect=factory,
        ):
            handler = DouyinHandler()
            asyncio.run(handler.get_stream_info("https://v.douyin.com/abc/"))
            asyncio.run(handler.get_stream_info("https://v.douyin.com/abc/"))

        # Cached pattern: one stream object reused across checks.
        self.assertEqual(len(created), 1)
        self.assertIs(handler.live_stream, created[0])
        self.assertEqual(created[0].fetch_app_stream_data.await_count, 2)


if __name__ == "__main__":
    unittest.main()
