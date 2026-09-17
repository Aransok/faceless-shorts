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


if __name__ == "__main__":
    unittest.main()
