"""Pure-logic tests for pipeline/family_game/odd_one_out.py. Fully
algorithmic (curated pool, no LLM call) -- runs for real against
generate_round() with no mocking."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.family_game.odd_one_out import ROUND_POOL, generate_round


class GenerateRoundTest(unittest.TestCase):
    def test_produces_a_valid_round_every_time(self):
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(round_["game_type"], "odd_one_out")
            self.assertEqual(len(segments), 5)

    def test_answer_is_one_of_the_shown_items(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            self.assertIn(round_["answer"], round_["presentation_data"]["items"])

    def test_segment_sequence_shape(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        kinds = [(s["kind"], s["beat"]) for s in segments]
        self.assertEqual(
            kinds,
            [
                (HOST_TIME, "intro"),
                (HOST_TIME, "prompt"),
                (PLAYER_TIME, "think"),
                (PLAYER_TIME, "countdown"),
                (HOST_TIME, "reveal"),
            ],
        )

    def test_player_segment_narrates_nothing(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        for s in segments:
            if s["kind"] == PLAYER_TIME:
                self.assertEqual(s["script_text"], "")

    def test_avoid_topics_excludes_already_used_categories(self):
        all_categories = {r["category_label"] for r in ROUND_POOL}
        avoid = list(all_categories - {"animals"})
        for _ in range(20):
            round_, _ = generate_round(avoid_topics=avoid, round_index=0)
            self.assertEqual(round_["title"], "animals")

    def test_avoid_topics_covering_everything_falls_back_to_full_pool(self):
        all_categories = [r["category_label"] for r in ROUND_POOL]
        round_, _ = generate_round(avoid_topics=all_categories, round_index=0)
        self.assertIn(round_["title"], all_categories)


if __name__ == "__main__":
    unittest.main()
