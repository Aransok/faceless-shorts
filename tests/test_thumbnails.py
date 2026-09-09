"""Pure-logic test for pipeline/thumbnails.py's real-bug fix: retrying
thumbnails().set() on a transient 404 (YouTube hasn't indexed the
just-uploaded video yet) -- no real network/API calls, per CLAUDE.md's
testing rules. Mocks every I/O boundary (state lookup, frame extraction,
the YouTube API client itself)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from googleapiclient.errors import HttpError

from pipeline.thumbnails import THUMBNAIL_SET_RETRY_DELAYS, upload_thumbnail


class _FakeResp:
    def __init__(self, status: int):
        self.status = status
        self.reason = "error"


def _http_error(status: int) -> HttpError:
    return HttpError(_FakeResp(status), b"error body")


class UploadThumbnailRetryTest(unittest.TestCase):
    def setUp(self):
        self.video = {"id": "vid1", "youtube_video_id": "yt123", "template": "facts"}
        self.get_video_patcher = patch("pipeline.thumbnails.get_video", return_value=self.video)
        self.generate_patcher = patch("pipeline.thumbnails.generate_thumbnail", return_value=Path("/tmp/thumb.jpg"))
        self.sleep_patcher = patch("pipeline.thumbnails.time.sleep")
        self.media_patcher = patch("pipeline.thumbnails.MediaFileUpload")
        self.get_video_patcher.start()
        self.generate_patcher.start()
        self.mock_sleep = self.sleep_patcher.start()
        self.media_patcher.start()
        self.addCleanup(self.get_video_patcher.stop)
        self.addCleanup(self.generate_patcher.stop)
        self.addCleanup(self.sleep_patcher.stop)
        self.addCleanup(self.media_patcher.stop)

    def _youtube_with_set_side_effect(self, side_effect):
        youtube = MagicMock()
        youtube.thumbnails.return_value.set.return_value.execute.side_effect = side_effect
        return youtube

    def test_succeeds_immediately_no_retry_needed(self):
        youtube = self._youtube_with_set_side_effect([{"ok": True}])
        result = upload_thumbnail("vid1", youtube)
        self.assertEqual(result, Path("/tmp/thumb.jpg"))
        self.mock_sleep.assert_not_called()

    def test_retries_on_404_then_succeeds(self):
        youtube = self._youtube_with_set_side_effect([_http_error(404), _http_error(404), {"ok": True}])
        result = upload_thumbnail("vid1", youtube)
        self.assertEqual(result, Path("/tmp/thumb.jpg"))
        self.assertEqual(self.mock_sleep.call_count, 2)

    def test_gives_up_after_exhausting_retries_on_persistent_404(self):
        side_effect = [_http_error(404)] * (len(THUMBNAIL_SET_RETRY_DELAYS) + 1)
        youtube = self._youtube_with_set_side_effect(side_effect)
        with self.assertRaises(HttpError) as ctx:
            upload_thumbnail("vid1", youtube)
        self.assertEqual(ctx.exception.resp.status, 404)

    def test_non_404_error_raises_immediately_without_retrying(self):
        youtube = self._youtube_with_set_side_effect([_http_error(403)])
        with self.assertRaises(HttpError) as ctx:
            upload_thumbnail("vid1", youtube)
        self.assertEqual(ctx.exception.resp.status, 403)
        self.mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
