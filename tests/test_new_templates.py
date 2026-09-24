"""The weird/food templates (2026-09-24) must be fully wired: prompt file
present, every placeholder plan() fills actually filled, persona mapped,
and the output format parseable by the shared FACT_N parser. Pure file/
string checks -- no LLM calls."""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.persona import load_persona
from pipeline.plan import TEMPLATES, _parse_response

_PLACEHOLDER = re.compile(r"\{(avoid_[a-z]+)\}")
_FILLED_BY_PLAN = {"avoid_topics", "avoid_facts", "avoid_sauces", "avoid_items"}

_SAMPLE = "\n".join(
    ["TOPIC: a topic", "HOOK: a hook"]
    + [
        line
        for i in (1, 2, 3)
        for line in (
            f"FACT_{i}_SCRIPT: beat {i} narration",
            f"FACT_{i}_SUBJECT: subject {i}",
            f"FACT_{i}_EXACT_QUERIES: q{i}a, q{i}b",
            f"FACT_{i}_REPRESENTATION_QUERIES: r{i}a",
            f"FACT_{i}_CONCEPT_QUERIES: none",
        )
    ]
)


class NewTemplatesWiringTest(unittest.TestCase):
    def test_both_templates_are_registered_with_existing_prompt_files(self):
        for template in ("weird", "food"):
            self.assertIn(template, TEMPLATES)
            self.assertTrue(TEMPLATES[template].exists(), f"{TEMPLATES[template]} missing")

    def test_every_placeholder_is_one_plan_fills(self):
        for template in ("weird", "food"):
            found = set(_PLACEHOLDER.findall(TEMPLATES[template].read_text(encoding="utf-8")))
            self.assertIn("avoid_topics", found)
            self.assertTrue(found <= _FILLED_BY_PLAN, f"{template} has unfilled placeholders: {found - _FILLED_BY_PLAN}")

    def test_persona_loads_for_both(self):
        for template in ("weird", "food"):
            self.assertIn("Editorial identity", load_persona(template))

    def test_output_format_parses_with_the_shared_parser(self):
        for template in ("weird", "food"):
            parsed = _parse_response(template, _SAMPLE)
            self.assertEqual(len(parsed["facts"]), 3)
            self.assertEqual(parsed["topic"], "a topic")


if __name__ == "__main__":
    unittest.main()
