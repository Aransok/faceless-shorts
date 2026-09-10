"""Pure-logic tests for pipeline/family_game/spot_the_difference.py.
Fully algorithmic (no LLM call at all, per FAMILY_GAME_NIGHT_SPEC.md
section 30 Phase 4's "do not rely on LLM memory") so these run for real
against generate_round() directly -- no mocking needed, unlike
higher_or_lower's tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.family_game.spot_the_difference import SCENE_TEMPLATES, generate_round


class GenerateRoundTest(unittest.TestCase):
    def test_produces_a_valid_round_every_time(self):
        # validate_round() already runs inside generate_round() and
        # raises on failure -- 50 real trials is a cheap, real check
        # that the random choices involved never produce an invalid
        # round, not just that one lucky draw happened to pass.
        for _ in range(50):
            round_, segments = generate_round(avoid_topics=[], round_index=0)
            self.assertEqual(round_["game_type"], "spot_the_difference")
            self.assertIn(round_["answer"], round_["presentation_data"]["before"])
            self.assertEqual(len(segments), 7)

    def test_changed_attribute_actually_differs_between_before_and_after(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            changed = round_["answer"]
            before_val = round_["presentation_data"]["before"][changed]
            after_val = round_["reveal_data"]["after"][changed]
            self.assertNotEqual(before_val, after_val)

    def test_only_the_answer_attribute_differs(self):
        for _ in range(50):
            round_, _ = generate_round(avoid_topics=[], round_index=0)
            before, after, changed = round_["presentation_data"]["before"], round_["reveal_data"]["after"], round_["answer"]
            differing = [attr for attr in before if before[attr] != after[attr]]
            self.assertEqual(differing, [changed])

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

    def test_study_segment_shows_before_scene_only(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        study_segment = segments[2]
        self.assertIn('"phase": "before"', study_segment["round_data_json"])

    def test_compare_segment_shows_after_scene_only(self):
        _, segments = generate_round(avoid_topics=[], round_index=0)
        compare_segment = segments[4]
        self.assertIn('"phase": "after"', compare_segment["round_data_json"])

    def test_neither_player_segment_narrates_anything(self):
        # Section 9: the narrator stays quiet during player time -- this
        # game type has no narration-based leak risk at all since both
        # think segments are silent by construction, but assert it
        # explicitly so a future edit can't accidentally add a spoiler
        # line here without a test catching it.
        _, segments = generate_round(avoid_topics=[], round_index=0)
        player_segments = [s for s in segments if s["kind"] == PLAYER_TIME]
        for s in player_segments:
            self.assertEqual(s["script_text"], "")

    def test_avoid_topics_excludes_already_used_subjects(self):
        all_subjects = {t["subject"] for t in SCENE_TEMPLATES}
        avoid = list(all_subjects - {"a fruit stand"})
        for _ in range(20):
            round_, _ = generate_round(avoid_topics=avoid, round_index=0)
            self.assertEqual(round_["title"], "a fruit stand")

    def test_avoid_topics_covering_everything_falls_back_to_full_pool(self):
        all_subjects = [t["subject"] for t in SCENE_TEMPLATES]
        # Should not raise even when every template is "avoided" --
        # falls back to the full pool rather than crashing with no
        # candidates.
        round_, _ = generate_round(avoid_topics=all_subjects, round_index=0)
        self.assertIn(round_["title"], all_subjects)


if __name__ == "__main__":
    unittest.main()
