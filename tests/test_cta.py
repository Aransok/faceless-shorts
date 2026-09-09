"""Pure-logic tests for pipeline/cta.py's weighted rotation and
guidance-block formatting -- no real LLM calls, per CLAUDE.md's testing
rules."""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.cta import CTA_TYPES, cta_guidance_block, pick_cta_angle


class PickCtaAngleTest(unittest.TestCase):
    def test_milestone_always_wins(self):
        for _ in range(20):
            angle = pick_cta_angle(milestone_line="just crossed 100 subscribers")
            self.assertEqual(angle["name"], "milestone")

    def test_never_repeats_immediately_previous_type(self):
        for _ in range(50):
            angle = pick_cta_angle(last_cta_type="comment_question")
            self.assertNotEqual(angle["name"], "comment_question")

    def test_picks_from_known_types_without_exclusion(self):
        for _ in range(20):
            angle = pick_cta_angle()
            self.assertIn(angle["name"], CTA_TYPES)

    def test_weighted_distribution_roughly_matches_target(self):
        # Not a statistical proof, just a sanity check that comment
        # (weight 40) shows up far more than share/none (weight 10 each)
        # over a decent sample, with no consecutive-exclusion in play.
        counts = Counter(pick_cta_angle()["name"] for _ in range(2000))
        self.assertGreater(counts["comment_question"], counts["share"])
        self.assertGreater(counts["comment_question"], counts["none"])
        self.assertGreater(counts["subscribe_series"], counts["share"])


class CtaGuidanceBlockTest(unittest.TestCase):
    def test_none_type_explicitly_says_no_cta(self):
        block = cta_guidance_block({"name": "none", **CTA_TYPES["none"]}, "facts")
        self.assertIn("No spoken CTA", block)
        self.assertNotIn("subscribe", block.lower().split("no spoken cta")[0])

    def test_includes_template_hint_when_available(self):
        angle = {"name": "comment_question", **CTA_TYPES["comment_question"]}
        block = cta_guidance_block(angle, "programming")
        self.assertIn("spotted the bug", block)

    def test_no_hint_for_unmapped_template_does_not_crash(self):
        angle = {"name": "comment_question", **CTA_TYPES["comment_question"]}
        block = cta_guidance_block(angle, "quiz_longform")
        self.assertIn("SPOKEN CTA", block)

    def test_milestone_line_included_when_given(self):
        angle = pick_cta_angle(milestone_line="just crossed 100 subscribers")
        block = cta_guidance_block(angle, "facts", milestone_line="just crossed 100 subscribers")
        self.assertIn("just crossed 100 subscribers", block)

    def test_never_stacks_multiple_asks_instruction_present(self):
        angle = {"name": "save", **CTA_TYPES["save"]}
        block = cta_guidance_block(angle, "sauce_recipe")
        self.assertIn("ONE ask", block)


if __name__ == "__main__":
    unittest.main()
