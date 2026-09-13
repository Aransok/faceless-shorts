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

from pipeline.thumbnails import (
    QUIZ_ACCENT,
    QUIZ_DARK_BG,
    THUMBNAIL_SET_RETRY_DELAYS,
    _render_thumb_challenge_hook,
    _render_thumb_question_panel,
    _render_thumb_stat_challenge,
    upload_thumbnail,
)

_OLD_GRADIENT_COLORS = ((20, 184, 166), (99, 102, 241))  # pipeline.brand.TEAL, INDIGO


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


class SingleAccentColorTest(unittest.TestCase):
    """Real (unmocked) Pillow rendering, checking actual pixel content --
    2026-09-13's redesign replaced every two-color TEAL/INDIGO gradient
    accent in these 3 renderers with one solid accent color (owner-shared
    creator research: a busy multi-color thumbnail gives the eye nowhere
    obvious to land). Assert on the real rendered pixels, not just that
    the code no longer calls the gradient helper."""

    def _colors_present(self, img):
        return set(img.getdata())

    def test_challenge_hook_has_no_gradient_colors(self):
        img = _render_thumb_challenge_hook("A TEST HEADLINE", 10)
        colors = self._colors_present(img)
        for gradient_color in _OLD_GRADIENT_COLORS:
            self.assertNotIn(gradient_color, colors)
        self.assertIn(QUIZ_ACCENT, colors)
        self.assertIn(QUIZ_DARK_BG, colors)

    def test_stat_challenge_has_no_gradient_colors(self):
        img = _render_thumb_stat_challenge("A TEST HEADLINE", 10)
        colors = self._colors_present(img)
        for gradient_color in _OLD_GRADIENT_COLORS:
            self.assertNotIn(gradient_color, colors)
        self.assertIn(QUIZ_ACCENT, colors)

    def test_question_panel_has_no_gradient_colors(self):
        fake_video = {"id": "vid-1", "hook": "A TEST HEADLINE"}
        fake_steps = [{"card_type": "question", "script_text": "A real test question?"}]
        with patch("pipeline.thumbnails.get_video_steps", return_value=fake_steps):
            img = _render_thumb_question_panel(fake_video, 10)
        colors = self._colors_present(img)
        for gradient_color in _OLD_GRADIENT_COLORS:
            self.assertNotIn(gradient_color, colors)
        self.assertIn(QUIZ_ACCENT, colors)


if __name__ == "__main__":
    unittest.main()
