"""Pure-logic tests for pipeline/plan.py's authenticity-review wiring
(pipeline/review_script.py integration) -- no real LLM calls, no DB
writes, per CLAUDE.md's testing rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.plan import _build_rewrite_prompt, _extract_narration


class ExtractNarrationTest(unittest.TestCase):
    def test_programming_joins_hook_and_step_scripts_only(self):
        parsed = {
            "hook": "This default argument bug is sneaky.",
            "steps": [
                {"script_text": "Define a function with a list default.", "code_snippet": "def f(x=[]):"},
                {"script_text": "Every call shares the same list.", "code_snippet": "def f(x=[]): ..."},
            ],
        }
        narration = _extract_narration("programming", parsed)
        self.assertIn("This default argument bug is sneaky.", narration)
        self.assertIn("Define a function with a list default.", narration)
        self.assertIn("Every call shares the same list.", narration)
        self.assertNotIn("def f", narration)  # code must not leak into the reviewed text

    def test_facts_joins_hook_and_fact_scripts_only(self):
        parsed = {
            "hook": "Bananas are berries, strawberries aren't.",
            "facts": [
                {"script_text": "Octopuses have three hearts.", "keywords": "octopus swimming"},
                {"script_text": "Honey never spoils.", "keywords": "honey jar"},
            ],
        }
        narration = _extract_narration("facts", parsed)
        self.assertIn("Bananas are berries, strawberries aren't.", narration)
        self.assertIn("Octopuses have three hearts.", narration)
        self.assertIn("Honey never spoils.", narration)
        self.assertNotIn("octopus swimming", narration)  # keywords must not leak in


class BuildRewritePromptTest(unittest.TestCase):
    def test_includes_original_prompt_previous_draft_and_feedback(self):
        prompt = _build_rewrite_prompt(
            "original prompt instructions",
            "TOPIC: x\nHOOK: y",
            "REWRITE_REQUIRED\n1. generic filler",
        )
        self.assertIn("original prompt instructions", prompt)
        self.assertIn("TOPIC: x\nHOOK: y", prompt)
        self.assertIn("REWRITE_REQUIRED", prompt)
        self.assertIn("generic filler", prompt)


class GenerateReviewedTest(unittest.TestCase):
    def test_approves_first_draft_without_rewriting(self):
        import pipeline.plan as plan_module

        llm_calls = []
        review_calls = []
        raw_response = "TOPIC: t\nHOOK: h\nFACT_1_SCRIPT: a\nFACT_1_KEYWORDS: k\nFACT_2_SCRIPT: b\nFACT_2_KEYWORDS: k\nFACT_3_SCRIPT: c\nFACT_3_KEYWORDS: k"

        def fake_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return raw_response

        def fake_review(narration: str, fn) -> dict:
            review_calls.append(narration)
            return {"approved": True, "feedback": "APPROVED"}

        original_llm = plan_module.call_llm
        original_review = plan_module.review_script
        plan_module.call_llm = fake_llm
        plan_module.review_script = fake_review
        try:
            parsed = plan_module._generate_reviewed("facts", "prompt")
        finally:
            plan_module.call_llm = original_llm
            plan_module.review_script = original_review

        self.assertEqual(parsed["topic"], "t")
        self.assertEqual(len(llm_calls), 1)  # no rewrite needed
        self.assertEqual(len(review_calls), 1)

    def test_rewrites_until_approved_then_raises_after_max_attempts(self):
        import pipeline.plan as plan_module

        raw_response = "TOPIC: t\nHOOK: h\nFACT_1_SCRIPT: a\nFACT_1_KEYWORDS: k\nFACT_2_SCRIPT: b\nFACT_2_KEYWORDS: k\nFACT_3_SCRIPT: c\nFACT_3_KEYWORDS: k"

        def fake_llm(prompt: str) -> str:
            return raw_response

        original_llm = plan_module.call_llm
        original_review = plan_module.review_script
        plan_module.call_llm = fake_llm
        # Every review comes back rejected -- should raise once attempts exceed REVIEW_MAX_REWRITES.
        plan_module.review_script = lambda narration, fn: {"approved": False, "feedback": "REWRITE_REQUIRED\nstill generic"}
        try:
            with self.assertRaises(RuntimeError):
                plan_module._generate_reviewed("facts", "prompt")
        finally:
            plan_module.call_llm = original_llm
            plan_module.review_script = original_review


if __name__ == "__main__":
    unittest.main()
