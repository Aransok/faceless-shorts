"""Pure-logic tests for pipeline/research.py -- no real network calls,
per CLAUDE.md's testing rules. The Wikipedia fetchers are mocked; the
rotation log is redirected to a temp file."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import research, rotation
from pipeline.plan import _research_seed_block

_DYK_HTML = """
<div class="mw-parser-output">
<h2>18 September 2026</h2>
<ul>
<li>... that the <b><a href="/wiki/Foo_bridge">Foo bridge</a></b> (pictured) was built entirely
    from recycled ship hulls in just nine days?</li>
<li>... that <b><a href="/wiki/John_Smith">John Smith</a></b> played for three clubs?</li>
<li>... that a <b><a href="/wiki/Bar_moth">moth</a></b> can hear bat calls pitched higher than any other animal can?</li>
<li><a href="/wiki/Main_Page">Back to the main page</a></li>
</ul>
</div>
"""


class ParseDykHooksTest(unittest.TestCase):
    def test_extracts_clean_fact_sentences(self):
        hooks = research.parse_dyk_hooks(_DYK_HTML)
        self.assertIn(
            "the Foo bridge was built entirely from recycled ship hulls in just nine days", hooks
        )
        self.assertIn("a moth can hear bat calls pitched higher than any other animal can", hooks)

    def test_drops_the_pictured_note_lead_in_and_question_mark(self):
        for hook in research.parse_dyk_hooks(_DYK_HTML):
            self.assertNotIn("pictured", hook)
            self.assertFalse(hook.startswith("..."))
            self.assertFalse(hook.endswith("?"))

    def test_skips_too_short_hooks_and_non_hook_list_items(self):
        hooks = research.parse_dyk_hooks(_DYK_HTML)
        self.assertFalse(any("John Smith" in h for h in hooks), "34-char hook is below the minimum")
        self.assertFalse(any("main page" in h.lower() for h in hooks))

    def test_accepts_unicode_and_spaced_ellipsis(self):
        html = (
            "<ul><li>\u2026 that the oldest known recipe for beer is written as a hymn to a goddess?</li>"
            "<li>. . . that a lighthouse in Wales was lit by candles until the nineteen-twenties?</li></ul>"
        )
        hooks = research.parse_dyk_hooks(html)
        self.assertEqual(len(hooks), 2)
        self.assertTrue(hooks[0].startswith("the oldest known recipe"))

    def test_empty_html_gives_no_hooks(self):
        self.assertEqual(research.parse_dyk_hooks(""), [])


class CleanSauceTitlesTest(unittest.TestCase):
    def test_strips_disambiguation_and_list_pages(self):
        names = research.clean_category_titles(["Mole (sauce)", "List of sauces", "Chimichurri", "Gravy"])
        self.assertEqual(names, ["Mole", "Chimichurri", "Gravy"])

    def test_dedupes_after_cleaning(self):
        self.assertEqual(research.clean_category_titles(["Mole (sauce)", "Mole (Mexican sauce)"]), ["Mole"])


class SuggestResearchSeedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({}, tmp)
        tmp.close()
        self.log_path = Path(tmp.name)
        self.addCleanup(self.log_path.unlink, missing_ok=True)
        for patcher in (
            mock.patch.object(rotation, "ROTATION_LOG_PATH", self.log_path),
            mock.patch.dict(os.environ, {"ENABLE_RESEARCH_TOPICS": "1"}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_programming_gets_no_seed(self):
        self.assertIsNone(research.suggest_research_seed("programming"))

    @mock.patch.object(research, "fetch_dyk_hooks")
    def test_facts_seed_lists_candidates_and_marks_them_used(self, mock_fetch):
        mock_fetch.return_value = [f"fact number {i} is surprising enough to matter" for i in range(10)]
        seed = research.suggest_research_seed("facts")
        self.assertIsNotNone(seed)
        self.assertIn("Did you know", seed)
        used = rotation.used_values("research_used_facts")
        self.assertEqual(len(used), research.CANDIDATES_PER_SEED)
        for picked in used:
            self.assertIn(picked, seed)

    @mock.patch.object(research, "fetch_dyk_hooks")
    def test_already_offered_candidates_are_never_offered_again(self, mock_fetch):
        pool = [f"fact number {i} is surprising enough to matter" for i in range(8)]
        mock_fetch.return_value = pool
        research.suggest_research_seed("facts")
        first = set(rotation.used_values("research_used_facts"))
        research.suggest_research_seed("facts")
        second = set(rotation.used_values("research_used_facts")) - first
        self.assertFalse(first & second)
        self.assertEqual(first | second, set(pool))

    @mock.patch.object(research, "fetch_dyk_hooks")
    def test_exhausted_pool_returns_none(self, mock_fetch):
        mock_fetch.return_value = ["only one fact that is long enough to be a real hook"]
        research.suggest_research_seed("facts")
        self.assertIsNone(research.suggest_research_seed("facts"))

    @mock.patch.object(research, "all_script_text", return_value="we made chimichurri and a basic gravy")
    @mock.patch.object(research, "fetch_category_names")
    def test_sauces_already_covered_on_the_channel_are_excluded(self, mock_fetch, _covered):
        mock_fetch.return_value = ["Chimichurri", "Gravy", "Mole", "Romesco"]
        seed = research.suggest_research_seed("sauce_recipe")
        mock_fetch.assert_called_once_with("Category:Sauces")
        self.assertIn("Mole", seed)
        self.assertIn("Romesco", seed)
        self.assertNotIn("Chimichurri", seed)
        self.assertNotIn("Gravy", seed)

    @mock.patch.object(research, "all_script_text", return_value="we covered brining last week")
    @mock.patch.object(research, "fetch_category_names")
    def test_food_seeds_come_from_cooking_techniques_minus_covered(self, mock_fetch, _covered):
        mock_fetch.return_value = ["Brining", "Velveting", "Nixtamalization"]
        seed = research.suggest_research_seed("food")
        mock_fetch.assert_called_once_with("Category:Cooking techniques")
        self.assertIn("Velveting", seed)
        self.assertNotIn("Brining", seed)
        self.assertEqual(sorted(rotation.used_values("research_used_food")), ["Nixtamalization", "Velveting"])

    def test_weird_gets_no_seed(self):
        self.assertIsNone(research.suggest_research_seed("weird"))

    @mock.patch.object(research, "fetch_dyk_hooks", side_effect=RuntimeError("connect rejected"))
    def test_network_failure_falls_back_to_none(self, _fetch):
        self.assertIsNone(research.suggest_research_seed("facts"))
        self.assertEqual(rotation.used_values("research_used_facts"), [])

    @mock.patch.object(research, "fetch_dyk_hooks")
    def test_can_be_disabled_via_env(self, mock_fetch):
        with mock.patch.dict(os.environ, {"ENABLE_RESEARCH_TOPICS": "0"}):
            self.assertIsNone(research.suggest_research_seed("facts"))
        mock_fetch.assert_not_called()


class ResearchSeedBlockTest(unittest.TestCase):
    def test_includes_the_seed_and_lets_the_model_skip_weak_candidates(self):
        block = _research_seed_block("- candidate one\n- candidate two")
        self.assertIn("candidate one", block)
        self.assertIn("ignore this list entirely", block)


if __name__ == "__main__":
    unittest.main()
