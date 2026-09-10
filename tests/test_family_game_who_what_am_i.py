"""Pure-logic tests for pipeline/family_game/who_what_am_i.py. Fully
algorithmic (curated pool, no LLM call) -- runs for real against
generate_round() with no mocking."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.family_game.who_what_am_i import ROUND_POOL, generate_round


class GenerateRoundTest(unittest.TestCase):
    def test_produces_a_valid_round_every_time(self):
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(round_["game_type"], "who_what_am_i")
            self.assertEqual(len(segments), 9)

    def test_three_clue_prompts_then_countdown_then_reveal(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        kinds = [(s["kind"], s["beat"]) for s in segments]
        self.assertEqual(
            kinds,
            [
                (HOST_TIME, "intro"),
                (HOST_TIME, "prompt"),
                (PLAYER_TIME, "think"),
                (HOST_TIME, "prompt"),
                (PLAYER_TIME, "think"),
                (HOST_TIME, "prompt"),
                (PLAYER_TIME, "think"),
                (PLAYER_TIME, "countdown"),
                (HOST_TIME, "reveal"),
            ],
        )

    def test_clue_prompts_never_state_the_answer(self):
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            answer_lower = round_["answer"].lower()
            clue_prompts = [s for s in segments if s["beat"] == "prompt"]
            for s in clue_prompts:
                self.assertNotIn(answer_lower, s["script_text"].lower())

    def test_reveal_states_the_real_answer(self):
        round_, segments = generate_round(avoid_topics=[], round_index=0)
        reveal = segments[-1]
        self.assertIn(round_["answer"], reveal["script_text"])

    def test_final_clues_shown_matches_the_full_pool_entry(self):
        for _ in range(20):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            reveal = segments[-1]
            reveal_data = json.loads(reveal["round_data_json"])
            pool_entry = next(r for r in ROUND_POOL if r["answer"] == round_["answer"])
            self.assertEqual(tuple(reveal_data["clues_shown"]), pool_entry["clues"])

    def test_player_segments_narrate_nothing(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        for s in segments:
            if s["kind"] == PLAYER_TIME:
                self.assertEqual(s["script_text"], "")


if __name__ == "__main__":
    unittest.main()
