"""Pure-logic tests for pipeline/games/base.py's select_rounds() -- no
real LLM calls, no DB writes, per CLAUDE.md's testing rules.

Covers the real bug fixed 2026-09-12: the count<=len(pool) branch used
to be a bare shuffle with no adjacency check, silently relying on every
caller passing an all-distinct pool. A weighted pool with duplicates
(plan_game.py's LONGFORM_ROUND_POOL, built to hit a 10+ minute episode
without a large Claude cost jump) broke that silent assumption."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.games.base import ROUND_TYPES, select_rounds


def _no_adjacent_repeats(rounds: list[str]) -> bool:
    return all(rounds[i] != rounds[i + 1] for i in range(len(rounds) - 1))


class SelectRoundsTest(unittest.TestCase):
    def test_distinct_pool_count_equal_to_pool_size_is_a_full_permutation(self):
        # Original guarantee: every type appears exactly once.
        rounds = select_rounds(len(ROUND_TYPES))
        self.assertEqual(sorted(rounds), sorted(ROUND_TYPES))
        self.assertTrue(_no_adjacent_repeats(rounds))

    def test_count_greater_than_pool_never_repeats_adjacently(self):
        for _ in range(20):
            rounds = select_rounds(15)
            self.assertTrue(_no_adjacent_repeats(rounds), rounds)

    def test_weighted_pool_with_duplicates_never_repeats_adjacently(self):
        # The real regression: a pool where one type appears 8 times
        # among 30 entries used to have real odds of landing two
        # copies back to back under a bare shuffle.
        weighted_pool = ("memory",) * 8 + ("what_changed",) * 8 + ("risk_or_safe",) * 8 + ("prediction",) * 3 + ("higher_or_lower",) * 3
        for _ in range(50):
            rounds = select_rounds(len(weighted_pool), pool=weighted_pool)
            self.assertTrue(_no_adjacent_repeats(rounds), rounds)
            self.assertEqual(sorted(rounds), sorted(weighted_pool))

    def test_weighted_pool_count_less_than_pool_size_still_safe(self):
        weighted_pool = ("memory",) * 5 + ("what_changed",) * 5 + ("prediction",) * 2
        for _ in range(50):
            rounds = select_rounds(10, pool=weighted_pool)
            self.assertTrue(_no_adjacent_repeats(rounds), rounds)
            self.assertEqual(len(rounds), 10)

    def test_impossible_pool_raises_instead_of_hanging_or_lying(self):
        # One type is more than half the pool -- no adjacency-safe
        # ordering exists at all.
        impossible_pool = ("memory",) * 6 + ("prediction",) * 1
        with self.assertRaises(RuntimeError):
            select_rounds(len(impossible_pool), pool=impossible_pool)


if __name__ == "__main__":
    unittest.main()
