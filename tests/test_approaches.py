"""Pure-logic tests for pipeline/approaches.py's choose_next_approach()
feedback loop and pipeline/winner_analyzer.py's approach_performance() --
no real network/DB calls per CLAUDE.md's testing rules. classified_rows()
is mocked at its source module (pipeline.winner_analyzer), since
choose_next_approach() imports it locally inside the function; real
data/phrase_usage.json rotation state is backed up/restored, same
discipline this project already applies elsewhere (e.g.
test_family_game_episode.py)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.approaches import MIN_APPROACH_SAMPLE, choose_next_approach
from pipeline.rotation import ROTATION_LOG_PATH
from pipeline.winner_analyzer import approach_performance


def _row(approach: str, views: int, baseline: float) -> dict:
    return {"approach": approach, "views": views, "baseline_views": baseline}


class ApproachPerformanceTest(unittest.TestCase):
    def test_averages_the_ratio_per_approach(self):
        rows = [_row("storytelling_hook", 200, 100), _row("storytelling_hook", 150, 100), _row("fast_cuts", 50, 100)]
        result = approach_performance(rows)
        self.assertEqual(result["storytelling_hook"]["count"], 2)
        self.assertAlmostEqual(result["storytelling_hook"]["avg_ratio"], 1.75)
        self.assertEqual(result["fast_cuts"]["count"], 1)
        self.assertAlmostEqual(result["fast_cuts"]["avg_ratio"], 0.5)

    def test_skips_rows_with_no_approach_or_no_baseline(self):
        rows = [
            {"approach": None, "views": 500, "baseline_views": 100},
            {"approach": "storytelling_hook", "views": 500, "baseline_views": 0},
            {"views": 500, "baseline_views": 100},
        ]
        self.assertEqual(approach_performance(rows), {})


class ChooseNextApproachTest(unittest.TestCase):
    def setUp(self):
        self._original_rotation_log = ROTATION_LOG_PATH.read_text(encoding="utf-8") if ROTATION_LOG_PATH.exists() else None
        self.addCleanup(self._restore_rotation_log)

    def _restore_rotation_log(self):
        if self._original_rotation_log is None:
            ROTATION_LOG_PATH.unlink(missing_ok=True)
        else:
            ROTATION_LOG_PATH.write_text(self._original_rotation_log, encoding="utf-8")

    def test_picks_the_real_winner_once_two_approaches_have_enough_samples(self):
        rows = (
            [_row("storytelling_hook", 300, 100) for _ in range(MIN_APPROACH_SAMPLE)]
            + [_row("fast_cuts", 100, 100) for _ in range(MIN_APPROACH_SAMPLE)]
        )
        with mock.patch("pipeline.winner_analyzer.classified_rows", return_value=rows):
            result = choose_next_approach()
        self.assertEqual(result, "storytelling_hook")

    def test_falls_back_to_rotation_when_only_one_approach_has_real_data(self):
        # Real production state (2026-09-14): current_approach had been
        # fixed to storytelling_hook since launch, so no OTHER approach
        # had ever been tried -- there's no comparison to make yet.
        rows = [_row("storytelling_hook", 300, 100) for _ in range(20)]
        with mock.patch("pipeline.winner_analyzer.classified_rows", return_value=rows):
            result = choose_next_approach()
        # Doesn't crash, returns a real approach from the pool -- the
        # rotation's own randomness is covered by pipeline/rotation.py's
        # own tests, not re-tested here.
        self.assertIn(result, ("storytelling_hook", "fast_cuts", "deadpan_facts"))

    def test_falls_back_to_rotation_when_samples_are_too_small(self):
        rows = (
            [_row("storytelling_hook", 300, 100) for _ in range(2)]
            + [_row("fast_cuts", 100, 100) for _ in range(2)]
        )
        with mock.patch("pipeline.winner_analyzer.classified_rows", return_value=rows):
            result = choose_next_approach()
        self.assertIn(result, ("storytelling_hook", "fast_cuts", "deadpan_facts"))

    def test_ignores_an_eligible_approach_outside_the_real_pool(self):
        # A stray/renamed approach value in old data shouldn't ever win a
        # real config.yaml value that config/approaches.yaml can't serve.
        rows = (
            [_row("some_retired_approach", 900, 100) for _ in range(MIN_APPROACH_SAMPLE)]
            + [_row("storytelling_hook", 100, 100) for _ in range(MIN_APPROACH_SAMPLE)]
            + [_row("fast_cuts", 50, 100) for _ in range(MIN_APPROACH_SAMPLE)]
        )
        with mock.patch("pipeline.winner_analyzer.classified_rows", return_value=rows):
            result = choose_next_approach()
        self.assertEqual(result, "storytelling_hook")


if __name__ == "__main__":
    unittest.main()
