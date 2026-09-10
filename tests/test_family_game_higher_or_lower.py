"""Pure-logic tests for pipeline/family_game/higher_or_lower.py -- no
real LLM calls, per CLAUDE.md's testing rules. call_llm/verify_claim are
monkeypatched on the module itself, same pattern tests/test_plan.py
already uses for pipeline/plan.py."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline.family_game.higher_or_lower as hol_module
from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.games.base import RoundVerificationFailed

_VALID_RESPONSE = (
    "CATEGORY: mountain heights\n"
    "ITEM_A_NAME: Mount Everest\n"
    "ITEM_A_VALUE: 8849\n"
    "ITEM_B_NAME: Denali\n"
    "ITEM_B_VALUE: 6190\n"
    "UNIT: meters\n"
    "INTRO_SCRIPT: Alright, mountain heights -- first challenge.\n"
    "PROMPT_SCRIPT: Everest comes in at roughly 8,849 meters. Higher or lower for Denali?\n"
    "REVEAL_SCRIPT: Denali lands at roughly 6,190 meters -- lower, and it's not close.\n"
)


class ParseResponseTest(unittest.TestCase):
    def test_parses_all_fields(self):
        parsed = hol_module._parse_response(_VALID_RESPONSE)
        self.assertEqual(parsed["ITEM_A_NAME"], "Mount Everest")
        self.assertEqual(parsed["item_a_value"], 8849.0)
        self.assertEqual(parsed["item_b_value"], 6190.0)

    def test_missing_field_raises(self):
        broken = _VALID_RESPONSE.replace("REVEAL_SCRIPT: Denali lands at roughly 6,190 meters -- lower, and it's not close.\n", "")
        with self.assertRaises(ValueError):
            hol_module._parse_response(broken)

    def test_non_numeric_value_raises(self):
        broken = _VALID_RESPONSE.replace("ITEM_B_VALUE: 6190", "ITEM_B_VALUE: about six thousand")
        with self.assertRaises(ValueError):
            hol_module._parse_response(broken)


class GenerateRoundTest(unittest.TestCase):
    def setUp(self):
        self._original_call_llm = hol_module.call_llm
        self._original_verify_claim = hol_module.verify_claim
        self.addCleanup(self._restore)

    def _restore(self):
        hol_module.call_llm = self._original_call_llm
        hol_module.verify_claim = self._original_verify_claim

    def test_confirmed_on_first_attempt_produces_a_valid_round(self):
        hol_module.call_llm = lambda prompt: _VALID_RESPONSE
        hol_module.verify_claim = lambda claim: {"verdict": "CONFIRMED", "corrected": None, "raw": "VERDICT: CONFIRMED"}

        round_, segments = hol_module.generate_round(avoid_topics=[], round_index=0)

        self.assertEqual(round_["game_type"], "higher_or_lower")
        self.assertEqual(round_["answer"], "lower")  # 6190 < 8849
        self.assertGreater(round_["thinking_time"], 0)

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
        # The prompt segment (spoken right before player time) must never
        # contain item B's real value -- that's the whole point of the gap.
        self.assertNotIn("6190", segments[1]["script_text"])
        self.assertNotIn("6,190", segments[1]["script_text"])

    def test_higher_answer_when_item_b_is_larger(self):
        response = _VALID_RESPONSE.replace("ITEM_B_VALUE: 6190", "ITEM_B_VALUE: 9000")
        hol_module.call_llm = lambda prompt: response
        hol_module.verify_claim = lambda claim: {"verdict": "CONFIRMED", "corrected": None, "raw": "VERDICT: CONFIRMED"}

        round_, _ = hol_module.generate_round(avoid_topics=[], round_index=0)
        self.assertEqual(round_["answer"], "higher")

    def test_rejected_every_attempt_raises_round_verification_failed(self):
        hol_module.call_llm = lambda prompt: _VALID_RESPONSE
        hol_module.verify_claim = lambda claim: {"verdict": "REJECTED", "corrected": None, "raw": "VERDICT: REJECTED"}

        with self.assertRaises(RoundVerificationFailed):
            hol_module.generate_round(avoid_topics=[], round_index=0)

    def test_rejected_then_confirmed_succeeds_on_retry(self):
        calls = {"n": 0}

        def fake_verify(claim):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"verdict": "REJECTED", "corrected": None, "raw": "VERDICT: REJECTED"}
            return {"verdict": "CONFIRMED", "corrected": None, "raw": "VERDICT: CONFIRMED"}

        hol_module.call_llm = lambda prompt: _VALID_RESPONSE
        hol_module.verify_claim = fake_verify

        round_, _ = hol_module.generate_round(avoid_topics=[], round_index=0)
        self.assertEqual(round_["answer"], "lower")
        self.assertEqual(calls["n"], 2)

    def test_avoid_topics_are_interpolated_into_the_prompt(self):
        seen_prompts = []

        def fake_call_llm(prompt):
            seen_prompts.append(prompt)
            return _VALID_RESPONSE

        hol_module.call_llm = fake_call_llm
        hol_module.verify_claim = lambda claim: {"verdict": "CONFIRMED", "corrected": None, "raw": "VERDICT: CONFIRMED"}

        hol_module.generate_round(avoid_topics=["mountain heights", "ocean depths"], round_index=0)
        self.assertIn("mountain heights, ocean depths", seen_prompts[0])


if __name__ == "__main__":
    unittest.main()
