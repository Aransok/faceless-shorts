"""Pure-logic tests for pipeline/family_game/memory_challenge.py. Fully
algorithmic (no LLM call), same as spot_the_difference -- runs for real
against generate_round() with no mocking."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.family_game.memory_challenge import ICON_POOL, generate_round


class GenerateRoundTest(unittest.TestCase):
    def test_produces_a_valid_round_every_time(self):
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(round_["game_type"], "memory_challenge")
            self.assertIn(round_["answer"], ("yes", "no"))
            self.assertEqual(len(segments), 7)

    def test_answer_is_correct_relative_to_the_real_generated_sequence(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            sequence = round_["presentation_data"]["sequence"]
            target = round_["reveal_data"]["target"]
            really_present = target in sequence
            claimed_answer = round_["answer"]
            self.assertEqual(claimed_answer, "yes" if really_present else "no")

    def test_sequence_length_is_one_of_the_allowed_choices(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            self.assertIn(len(round_["presentation_data"]["sequence"]), (4, 5, 6, 7))

    def test_sequence_has_no_duplicate_icons(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            sequence = round_["presentation_data"]["sequence"]
            self.assertEqual(len(sequence), len(set(sequence)))
            self.assertTrue(set(sequence).issubset(set(ICON_POOL)))

    def test_segment_sequence_shape(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        kinds = [(s["kind"], s["beat"]) for s in segments]
        self.assertEqual(
            kinds,
            [
                (HOST_TIME, "intro"),
                (HOST_TIME, "prompt"),
                (PLAYER_TIME, "think"),
                (HOST_TIME, "transition"),
                (PLAYER_TIME, "think"),
                (PLAYER_TIME, "countdown"),
                (HOST_TIME, "reveal"),
            ],
        )

    def test_question_segment_never_carries_the_correct_answer(self):
        # The whole point of a real recall test: once the sequence is
        # hidden and only the question remains, that segment's data must
        # not smuggle in the answer -- checked structurally, not just by
        # trusting the renderer won't draw it.
        import json

        _, segments = generate_round(avoid_topics=[], round_index=0)
        question_segment = segments[3]
        question_data = json.loads(question_segment["round_data_json"])
        self.assertNotIn("correct_answer", question_data)
        self.assertNotIn("sequence", question_data)

    def test_neither_player_segment_narrates_anything(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        player_segments = [s for s in segments if s["kind"] == PLAYER_TIME]
        for s in player_segments:
            self.assertEqual(s["script_text"], "")


if __name__ == "__main__":
    unittest.main()
