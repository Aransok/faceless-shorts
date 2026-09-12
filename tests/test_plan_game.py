"""Pure-logic tests for pipeline/plan_game.py's LONGFORM_ROUND_POOL --
no real LLM calls, no DB writes, per CLAUDE.md's testing rules.

Covers the real cost-control property this pool exists for (owner
wanted "at least 10 mins" without a large Claude cost jump): LLM-
touching round types (higher_or_lower, prediction) are capped
regardless of how many total rounds the episode has, with the extra
length coming from the fully algorithmic round types instead."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.games.base import VERIFIED_CONTENT_ROUND_TYPES, select_rounds
from pipeline.plan_game import DEFAULT_ROUND_COUNT, LONGFORM_ROUND_POOL


class LongformRoundPoolTest(unittest.TestCase):
    def test_default_round_count_matches_pool_size(self):
        self.assertEqual(DEFAULT_ROUND_COUNT, len(LONGFORM_ROUND_POOL))

    def test_llm_touching_rounds_stay_a_small_minority(self):
        llm_touching = sum(1 for t in LONGFORM_ROUND_POOL if t in VERIFIED_CONTENT_ROUND_TYPES)
        # Real, load-bearing property: this is what keeps a 30-round
        # episode from costing 6x a 5-round one just because it's
        # longer -- most of the added length must come from the free
        # algorithmic round types, not the ones that call Claude.
        self.assertLessEqual(llm_touching, len(LONGFORM_ROUND_POOL) // 4)

    def test_pool_is_long_enough_for_a_real_ten_plus_minute_episode(self):
        # Not a duration guarantee by itself (that's voice.py's
        # GAME_NIGHT_MIN_BEAT_SECONDS floors + real narration length),
        # but 30 rounds at the old ~2min-for-5-rounds rate is already
        # well past the 10-minute floor even before the floor increase.
        self.assertGreaterEqual(len(LONGFORM_ROUND_POOL), 24)

    def test_select_rounds_on_the_real_production_pool_never_repeats_adjacently(self):
        for _ in range(20):
            rounds = select_rounds(DEFAULT_ROUND_COUNT, pool=LONGFORM_ROUND_POOL)
            self.assertEqual(len(rounds), DEFAULT_ROUND_COUNT)
            self.assertTrue(all(rounds[i] != rounds[i + 1] for i in range(len(rounds) - 1)), rounds)


if __name__ == "__main__":
    unittest.main()
