"""Pure-logic tests for pipeline/render_veylorn.py's per-beat duration
math -- no real ffmpeg/TTS/network calls, per CLAUDE.md's testing rules.
"""

from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
