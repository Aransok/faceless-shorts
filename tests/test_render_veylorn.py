"""Pure-logic tests for pipeline/render_veylorn.py's per-beat duration
math and on-screen choice-prompt overlay -- no real ffmpeg/TTS/network
calls, per CLAUDE.md's testing rules. The overlay test does use real
Pillow image ops (in-memory only) since that's the thing under test,
not an external call.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from pipeline import render_veylorn as rv


class TestBeatTiming(unittest.TestCase):
    def test_short_narration_gets_padded_to_the_fixed_budget(self):
        pad_seconds, final_duration = rv._beat_timing(6.0, idx=0)
        self.assertAlmostEqual(pad_seconds, rv.BEAT_SECONDS - 6.0)
        self.assertEqual(final_duration, rv.BEAT_SECONDS)

    def test_narration_exactly_at_budget_needs_no_padding(self):
        pad_seconds, final_duration = rv._beat_timing(rv.BEAT_SECONDS, idx=0)
        self.assertEqual(pad_seconds, 0.0)
        self.assertEqual(final_duration, rv.BEAT_SECONDS)

    def test_overrunning_narration_keeps_its_real_length_unpadded(self):
        pad_seconds, final_duration = rv._beat_timing(rv.BEAT_SECONDS + 3.0, idx=5)
        self.assertEqual(pad_seconds, 0.0)
        self.assertEqual(final_duration, rv.BEAT_SECONDS + 3.0)

    def test_ten_beats_at_the_fixed_budget_sum_to_the_total_duration(self):
        total = sum(rv._beat_timing(rv.BEAT_SECONDS, idx=i)[1] for i in range(rv.BEAT_COUNT))
        self.assertAlmostEqual(total, rv.TOTAL_DURATION_SECONDS)


class TestZoompanRate(unittest.TestCase):
    def test_reaches_max_zoom_exactly_at_the_last_frame(self):
        frame_count = 1800  # 60s at 30fps
        rate = rv._zoompan_rate(frame_count)
        zoom_at_last_frame = 1.0 + rate * frame_count
        self.assertAlmostEqual(zoom_at_last_frame, rv.MAX_ZOOM, places=6)

    def test_shorter_segment_gets_a_faster_rate(self):
        """A real bug this guards against: a rate tuned for one beat
        length freezes early on a much longer segment (see MAX_ZOOM's
        docstring) -- the rate must scale inversely with frame_count,
        not stay constant."""
        short_rate = rv._zoompan_rate(300)
        long_rate = rv._zoompan_rate(1800)
        self.assertGreater(short_rate, long_rate)

    def test_zero_frames_does_not_divide_by_zero(self):
        rv._zoompan_rate(0)  # must not raise


class TestDrawChoiceOverlay(unittest.TestCase):
    """Real owner feedback (2026-09-18): pressing 7/8/9 didn't feel like
    a real choice without visible on-screen text -- this is what makes
    the choice actually visible."""

    def _blank_image(self, color=(50, 60, 70)) -> Path:
        tmp_dir = Path(tempfile.mkdtemp())
        path = tmp_dir / "test.jpg"
        Image.new("RGB", (rv.WIDTH, rv.HEIGHT), color).save(path)
        return path

    def test_overlay_darkens_the_bottom_region_only(self):
        path = self._blank_image(color=(200, 200, 200))
        rv._draw_choice_overlay(path, "PRESS 3: Confront them\nPRESS 4: Talk it out")
        image = Image.open(path)
        top_pixel = image.getpixel((rv.WIDTH // 2, 50))
        # Sample near the left edge of the box's vertical middle (not
        # dead center, which risks landing on a glyph stroke instead of
        # the box background at some font/text combination).
        box_area_pixel = image.getpixel((40, rv.HEIGHT - 150))
        self.assertEqual(top_pixel, (200, 200, 200), "region outside the prompt box must be untouched")
        self.assertLess(sum(box_area_pixel), sum(top_pixel), "the prompt box must visibly darken its region")

    def test_output_stays_a_valid_same_size_image(self):
        path = self._blank_image()
        rv._draw_choice_overlay(path, "PRESS 7: ...\nPRESS 8: ...\nPRESS 9: ...")
        image = Image.open(path)
        self.assertEqual(image.size, (rv.WIDTH, rv.HEIGHT))

    def test_handles_a_single_line_prompt(self):
        path = self._blank_image()
        rv._draw_choice_overlay(path, "PRESS 5 to continue")  # no real beat uses this, but must not crash
        Image.open(path).verify()


if __name__ == "__main__":
    unittest.main()
