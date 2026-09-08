"""Pure-logic tests for pipeline/review_script.py's response parsing --
no real LLM calls, per CLAUDE.md's testing rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.review_script import _parse_review_response, review_script


class ParseReviewResponseTest(unittest.TestCase):
    def test_approved(self):
        result = _parse_review_response("APPROVED")
        self.assertTrue(result["approved"])

    def test_rewrite_required(self):
        text = (
            "REWRITE_REQUIRED\n"
            "1. \"Pretty cool, right?\" -- generic filler, category: hype."
        )
        result = _parse_review_response(text)
        self.assertFalse(result["approved"])
        self.assertIn("Pretty cool", result["feedback"])

    def test_missing_verdict_raises(self):
        with self.assertRaises(ValueError):
            _parse_review_response("This script looks fine to me.")

    def test_last_verdict_wins_when_model_reasons_out_loud(self):
        # Same failure mode already caught for real in games/base.py's
        # verify_claim(): a model sometimes emits a draft verdict, then
        # reverses it in its own follow-up reasoning despite being told
        # to respond in exactly one format.
        text = (
            "REWRITE_REQUIRED\n"
            "Actually, rereading this, every line holds up.\n"
            "APPROVED"
        )
        result = _parse_review_response(text)
        self.assertTrue(result["approved"])


class ReviewScriptTest(unittest.TestCase):
    def test_reads_prompt_template_and_calls_llm(self):
        captured = {}

        def fake_llm(prompt: str) -> str:
            captured["prompt"] = prompt
            return "APPROVED"

        result = review_script("Some narration text.", fake_llm)
        self.assertTrue(result["approved"])
        self.assertIn("Some narration text.", captured["prompt"])
        self.assertIn("APPROVED", captured["prompt"])  # instructions mention the verdict format


if __name__ == "__main__":
    unittest.main()
