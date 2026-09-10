"""Pure-logic tests for pipeline/family_game/guess_the_connection.py.
Fully algorithmic (curated pool, no LLM call) -- runs for real against
generate_round() with no mocking."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.family_game.guess_the_connection import ROUND_POOL, generate_round


class GenerateRoundTest(unittest.TestCase):
    def test_produces_a_valid_round_every_time(self):
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(round_["game_type"], "guess_the_connection")
            self.assertEqual(len(segments), 5)

    def test_four_clues_shown_every_time(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(len(round_["presentation_data"]["clues"]), 4)

    def test_prompt_segment_never_states_the_connection_early(self):
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            prompt_segment = segments[1]
            self.assertNotIn(round_["answer"].lower(), prompt_segment["script_text"].lower())

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

    def test_avoid_topics_excludes_already_used_connections(self):
        all_connections = {r["connection"] for r in ROUND_POOL}
        target = "Flightless birds"
        avoid = list(all_connections - {target})
        for _ in range(20):
            round_, _ = generate_round(avoid_topics=avoid, round_index=0)
            self.assertEqual(round_["title"], target)


if __name__ == "__main__":
    unittest.main()
