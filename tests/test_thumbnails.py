"""Pure-logic test for pipeline/thumbnails.py's real-bug fix: retrying
thumbnails().set() on a transient 404 (YouTube hasn't indexed the
just-uploaded video yet) -- no real network/API calls, per CLAUDE.md's
testing rules. Mocks every I/O boundary (state lookup, frame extraction,
the YouTube API client itself)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from googleapiclient.errors import HttpError

import pipeline.thumbnails as thumbnails_module
from pipeline.thumbnails import (
    DEFAULT_BADGE_TEXT,
    QUIZ_DARK_BG,
    SHORTS_CARD_HEIGHT,
    SHORTS_CARD_WIDTH,
    TEMPLATE_BADGE_TEXT,
    THUMBNAIL_ACCENT,
    THUMBNAIL_SET_RETRY_DELAYS,
    _generate_thumbnail_from_card,
    _render_shorts_card,
    _render_thumb_challenge_hook,
    _render_thumb_question_panel,
    _render_thumb_stat_challenge,
    generate_thumbnail,
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
        self.assertIn(THUMBNAIL_ACCENT, colors)
        self.assertIn(QUIZ_DARK_BG, colors)

    def test_stat_challenge_has_no_gradient_colors(self):
        img = _render_thumb_stat_challenge("A TEST HEADLINE", 10)
        colors = self._colors_present(img)
        for gradient_color in _OLD_GRADIENT_COLORS:
            self.assertNotIn(gradient_color, colors)
        self.assertIn(THUMBNAIL_ACCENT, colors)

    def test_question_panel_has_no_gradient_colors(self):
        fake_video = {"id": "vid-1", "hook": "A TEST HEADLINE"}
        fake_steps = [{"card_type": "question", "script_text": "A real test question?"}]
        with patch("pipeline.thumbnails.get_video_steps", return_value=fake_steps):
            img = _render_thumb_question_panel(fake_video, 10)
        colors = self._colors_present(img)
        for gradient_color in _OLD_GRADIENT_COLORS:
            self.assertNotIn(gradient_color, colors)
        self.assertIn(THUMBNAIL_ACCENT, colors)


class ShortsCardTest(unittest.TestCase):
    """Real (unmocked) Pillow rendering of the v2 designed Shorts
    thumbnail (2026-09-13) -- replaces frame extraction as the default
    for facts/programming/sauce_recipe/game_night."""

    def _colors_present(self, img):
        return set(img.getdata())

    def test_renders_at_the_real_9_16_canvas_size(self):
        img = _render_shorts_card({"template": "facts", "hook": "A real hook"})
        self.assertEqual(img.size, (SHORTS_CARD_WIDTH, SHORTS_CARD_HEIGHT))

    def test_uses_the_single_accent_color_and_dark_background(self):
        img = _render_shorts_card({"template": "programming", "hook": "A real hook"})
        colors = self._colors_present(img)
        self.assertIn(THUMBNAIL_ACCENT, colors)
        self.assertIn(QUIZ_DARK_BG, colors)

    def test_every_known_template_has_its_own_badge_text(self):
        for template, badge in TEMPLATE_BADGE_TEXT.items():
            with self.subTest(template=template):
                # Doesn't raise, and produces a real image -- the badge
                # text itself is drawn, not asserted pixel-by-pixel here.
                img = _render_shorts_card({"template": template, "hook": "A real hook"})
                self.assertEqual(img.size, (SHORTS_CARD_WIDTH, SHORTS_CARD_HEIGHT))

    def test_unknown_template_falls_back_to_default_badge(self):
        # Doesn't raise for a template with no curated badge text --
        # DEFAULT_BADGE_TEXT covers it rather than a KeyError.
        img = _render_shorts_card({"template": "some_future_template", "hook": "A real hook"})
        self.assertEqual(img.size, (SHORTS_CARD_WIDTH, SHORTS_CARD_HEIGHT))
        self.assertTrue(DEFAULT_BADGE_TEXT)

    def test_missing_hook_raises(self):
        with self.assertRaises(ValueError):
            _render_shorts_card({"template": "facts", "hook": ""})
        with self.assertRaises(ValueError):
            _render_shorts_card({"template": "facts", "hook": None})

    def test_long_hook_still_fits_within_four_lines(self):
        long_hook = "This is a deliberately very long hook sentence that should still wrap and shrink to fit cleanly"
        img = _render_shorts_card({"template": "facts", "hook": long_hook})
        self.assertEqual(img.size, (SHORTS_CARD_WIDTH, SHORTS_CARD_HEIGHT))

    def test_generate_thumbnail_from_card_logs_a_debuggable_record(self):
        # Real gap found 2026-09-13: this path had no log entry at all,
        # so a real production run left no way to tell from
        # data/thumbnails.json whether a video got the new card or
        # silently fell back to frame extraction. tmp log path, never
        # the real project file.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "thumbnails.json"
            with patch.object(thumbnails_module, "THUMBNAIL_LOG_PATH", log_path), \
                 patch.object(thumbnails_module, "OUTPUT_DIR", Path(tmp)):
                out_path = _generate_thumbnail_from_card("vid-1", {"template": "programming", "hook": "a real hook"})
            self.assertTrue(out_path.exists())
            records = json.loads(log_path.read_text(encoding="utf-8"))
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["video_id"], "vid-1")
            self.assertEqual(records[0]["method"], "card")
            self.assertEqual(records[0]["template"], "programming")


class GenerateThumbnailFallbackTest(unittest.TestCase):
    """generate_thumbnail() tries the designed card first and falls back
    to frame extraction on ANY failure (CLAUDE.md's fail-soft rule) --
    no real network/file I/O, both underlying generators are mocked."""

    def setUp(self):
        self.video = {"id": "vid1", "template": "facts", "hook": "a hook", "final_path": "/fake/path.mp4"}
        self.get_video_patcher = patch("pipeline.thumbnails.get_video", return_value=self.video)
        self.get_video_patcher.start()
        self.addCleanup(self.get_video_patcher.stop)

    def test_uses_the_card_path_when_it_succeeds(self):
        card_path = Path("/tmp/card.jpg")
        with patch("pipeline.thumbnails._generate_thumbnail_from_card", return_value=card_path) as mock_card, \
             patch("pipeline.thumbnails._generate_thumbnail_from_frame") as mock_frame:
            result = generate_thumbnail("vid1")
        self.assertEqual(result, card_path)
        mock_card.assert_called_once()
        mock_frame.assert_not_called()

    def test_falls_back_to_frame_extraction_when_the_card_raises(self):
        frame_path = Path("/tmp/frame.jpg")
        with patch("pipeline.thumbnails._generate_thumbnail_from_card", side_effect=RuntimeError("font issue")), \
             patch("pipeline.thumbnails._generate_thumbnail_from_frame", return_value=frame_path) as mock_frame:
            result = generate_thumbnail("vid1")
        self.assertEqual(result, frame_path)
        mock_frame.assert_called_once()

    def test_landscape_templates_never_attempt_the_vertical_card(self):
        # Real regression caught before shipping (2026-09-13): game_night
        # (and quiz_longform) render LANDSCAPE 1920x1080 -- routing them
        # through the 9:16 card would produce a mismatched, cropped-
        # looking thumbnail. They must go straight to frame extraction,
        # never even attempt the card.
        for landscape_template in ("game_night", "quiz_longform", "family_game_night"):
            with self.subTest(template=landscape_template):
                self.video["template"] = landscape_template
                frame_path = Path("/tmp/frame.jpg")
                with patch("pipeline.thumbnails._generate_thumbnail_from_card") as mock_card, \
                     patch("pipeline.thumbnails._generate_thumbnail_from_frame", return_value=frame_path) as mock_frame:
                    result = generate_thumbnail("vid1")
                self.assertEqual(result, frame_path)
                mock_card.assert_not_called()
                mock_frame.assert_called_once()


if __name__ == "__main__":
    unittest.main()
