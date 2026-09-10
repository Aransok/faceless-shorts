"""Pure-logic tests for pipeline/family_game/rapid_fire.py. Fully
algorithmic (curated pool of real true/false facts, no LLM call) --
runs for real against generate_round() with no mocking. Also the first
real exercise of validate_round()'s multi-cycle-safe reveal check (this
game type has several reveal segments per round, not one)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.family_game.rapid_fire import QUESTIONS_PER_ROUND, STATEMENT_POOL, generate_round


class GenerateRoundTest(unittest.TestCase):
    def test_produces_a_valid_round_every_time(self):
        # This is the real end-to-end proof that base.py's multi-cycle
        # validate_round fix actually works on real generated content,
        # not just the synthetic fixture in test_family_game_base.py.
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(round_["game_type"], "rapid_fire")

    def test_picks_the_configured_number_of_questions(self):
        for _ in range(20):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(len(round_["presentation_data"]["statements"]), QUESTIONS_PER_ROUND)
            # intro + 3 segments (prompt/think/reveal) per question
            self.assertEqual(len(segments), 1 + 3 * QUESTIONS_PER_ROUND)

    def test_no_duplicate_statements_within_one_round(self):
        for _ in range(20):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            statements = round_["presentation_data"]["statements"]
            self.assertEqual(len(statements), len(set(statements)))

    def test_each_question_cycle_is_prompt_think_reveal(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        cycles = segments[1:]  # after intro
        for i in range(0, len(cycles), 3):
            prompt, think, reveal = cycles[i], cycles[i + 1], cycles[i + 2]
            self.assertEqual((prompt["kind"], prompt["beat"]), (HOST_TIME, "prompt"))
            self.assertEqual((think["kind"], think["beat"]), (PLAYER_TIME, "think"))
            self.assertEqual((reveal["kind"], reveal["beat"]), (HOST_TIME, "reveal"))

    def test_reveal_answer_matches_the_pool_entry(self):
        statement_to_answer = {s["statement"]: s["answer"] for s in STATEMENT_POOL}
        _, segments = generate_round(avoid_topics=[], round_index=0)
        cycles = segments[1:]
        for i in range(0, len(cycles), 3):
            prompt, reveal = cycles[i], cycles[i + 2]
            statement = prompt["script_text"].replace("True or false: ", "")
            expected_answer = statement_to_answer[statement]
            self.assertIn(expected_answer.capitalize(), reveal["script_text"])

    def test_player_segments_narrate_nothing(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        for s in segments:
            if s["kind"] == PLAYER_TIME:
                self.assertEqual(s["script_text"], "")


if __name__ == "__main__":
    unittest.main()
