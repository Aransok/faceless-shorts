"""Pure-logic tests for pipeline/family_game/base.py's HOST_TIME/
PLAYER_TIME state machine -- no real LLM calls, per CLAUDE.md's testing
rules. This is the foundation Phase 21's vertical slice (Higher or
Lower) is built on, so these tests exist to pin down the state-machine
rules themselves, independent of any one game type."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.family_game.base import (
    HOST_TIME,
    PLAYER_TIME,
    estimate_thinking_time,
    make_round,
    make_segment,
    validate_round,
)


class EstimateThinkingTimeTest(unittest.TestCase):
    def test_medium_difficulty_lands_at_category_midpoint(self):
        self.assertAlmostEqual(estimate_thinking_time("simple_question", difficulty="medium"), 6.5)

    def test_easy_lands_at_category_low_end(self):
        self.assertAlmostEqual(estimate_thinking_time("simple_question", difficulty="easy"), 5.0)

    def test_hard_lands_at_category_high_end(self):
        self.assertAlmostEqual(estimate_thinking_time("simple_question", difficulty="hard"), 8.0)

    def test_extra_items_add_real_time_not_free(self):
        base = estimate_thinking_time("connection", item_count=2)
        with_more_items = estimate_thinking_time("connection", item_count=6)
        self.assertGreater(with_more_items, base)

    def test_first_two_items_are_free(self):
        self.assertEqual(
            estimate_thinking_time("moderate_deduction", item_count=1),
            estimate_thinking_time("moderate_deduction", item_count=2),
        )

    def test_extra_items_cannot_blow_past_a_capped_ceiling(self):
        duration = estimate_thinking_time("rapid_fire", item_count=1000, difficulty="hard")
        lo, hi = 3.0, 6.0
        self.assertLessEqual(duration, hi + 0.6 * 3)

    def test_unknown_category_raises(self):
        with self.assertRaises(ValueError):
            estimate_thinking_time("not_a_real_category")

    def test_unknown_difficulty_raises(self):
        with self.assertRaises(ValueError):
            estimate_thinking_time("simple_question", difficulty="extreme")


class MakeSegmentTest(unittest.TestCase):
    def test_player_segment_requires_explicit_duration(self):
        with self.assertRaises(ValueError):
            make_segment("higher_or_lower", 0, PLAYER_TIME, "think", duration_seconds=None)

    def test_player_segment_rejects_zero_or_negative_duration(self):
        with self.assertRaises(ValueError):
            make_segment("higher_or_lower", 0, PLAYER_TIME, "think", duration_seconds=0)

    def test_host_segment_does_not_require_duration(self):
        seg = make_segment("higher_or_lower", 0, HOST_TIME, "intro", "Alright, first challenge.")
        self.assertIsNone(seg["duration_seconds"])

    def test_reveal_beat_is_not_allowed_during_player_time(self):
        with self.assertRaises(ValueError):
            make_segment("higher_or_lower", 0, PLAYER_TIME, "reveal", duration_seconds=5.0)

    def test_think_beat_is_not_allowed_during_host_time(self):
        with self.assertRaises(ValueError):
            make_segment("higher_or_lower", 0, HOST_TIME, "think")

    def test_unknown_kind_raises(self):
        with self.assertRaises(ValueError):
            make_segment("higher_or_lower", 0, "narrator", "intro")


class MakeRoundTest(unittest.TestCase):
    def test_rejects_non_positive_thinking_time(self):
        with self.assertRaises(ValueError):
            make_round(
                "higher_or_lower", "medium", "title", "instructions", {}, "higher", "explanation",
                thinking_time=0, reveal_data={},
            )

    def test_rejects_unknown_difficulty(self):
        with self.assertRaises(ValueError):
            make_round(
                "higher_or_lower", "brutal", "title", "instructions", {}, "higher", "explanation",
                thinking_time=6.0, reveal_data={},
            )


def _valid_round_and_segments():
    round_ = make_round(
        game_type="higher_or_lower",
        difficulty="medium",
        title="mountain heights",
        instructions="Is Denali higher or lower than Everest?",
        presentation_data={"item_a_name": "Everest", "item_a_value": 8849},
        answer="lower",
        explanation="Denali is roughly 6,190 meters, well below Everest.",
        thinking_time=6.5,
        reveal_data={"item_b_name": "Denali", "item_b_value": 6190, "correct_answer": "lower"},
    )
    segments = [
        make_segment("higher_or_lower", 0, HOST_TIME, "intro", "Mountain heights, first challenge."),
        make_segment("higher_or_lower", 0, HOST_TIME, "prompt", "Everest is roughly 8,849 meters. Is Denali higher or lower?"),
        make_segment("higher_or_lower", 0, PLAYER_TIME, "think", "", duration_seconds=6.5),
        make_segment("higher_or_lower", 0, PLAYER_TIME, "countdown", "", duration_seconds=3.0),
        make_segment("higher_or_lower", 0, HOST_TIME, "reveal", "Denali comes in at roughly 6,190 meters -- lower."),
    ]
    return round_, segments


class ValidateRoundTest(unittest.TestCase):
    def test_well_formed_round_passes(self):
        round_, segments = _valid_round_and_segments()
        ok, reason = validate_round(round_, segments)
        self.assertTrue(ok, reason)

    def test_missing_required_field_fails(self):
        round_, segments = _valid_round_and_segments()
        del round_["explanation"]
        ok, reason = validate_round(round_, segments)
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_no_player_segment_fails(self):
        round_, segments = _valid_round_and_segments()
        host_only = [s for s in segments if s["kind"] == HOST_TIME]
        ok, reason = validate_round(round_, host_only)
        self.assertFalse(ok)
        self.assertIn("PLAYER_TIME", reason)

    def test_player_segment_leaking_the_answer_fails(self):
        round_, segments = _valid_round_and_segments()
        # Simulate a bug that let the answer slip into the "think" beat's
        # narration -- the exact failure section 9 exists to prevent.
        segments[2] = {**segments[2], "script_text": "It's definitely lower, by the way."}
        ok, reason = validate_round(round_, segments)
        self.assertFalse(ok)
        self.assertIn("leaks", reason)

    def test_reveal_before_player_time_ends_fails(self):
        round_, segments = _valid_round_and_segments()
        reordered = [segments[0], segments[4], segments[1], segments[2], segments[3]]
        ok, reason = validate_round(round_, reordered)
        self.assertFalse(ok)
        self.assertIn("before player time", reason)

    def test_empty_segments_fails(self):
        round_, _ = _valid_round_and_segments()
        ok, reason = validate_round(round_, [])
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
