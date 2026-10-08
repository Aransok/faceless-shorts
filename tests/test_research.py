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


class FetchDykHooksTest(unittest.TestCase):
    def test_follows_redirects_and_falls_back_to_the_main_page_set(self):
        stub = "<ul><li>Wikipedia:Did you know archive</li></ul>"
        calls = []

        def fake_get(params):
            calls.append(params)
            html = stub if params["page"] == research.DYK_PAGE else _DYK_HTML
            return {"parse": {"text": html}}

        with mock.patch.object(research, "_wikipedia_get", side_effect=fake_get):
            hooks = research.fetch_dyk_hooks()
        self.assertTrue(all(c["redirects"] == 1 for c in calls))
        self.assertEqual([c["page"] for c in calls], [research.DYK_PAGE, research.DYK_FALLBACK_PAGE])
        self.assertIn("a moth can hear bat calls pitched higher than any other animal can", hooks)


class CleanSauceTitlesTest(unittest.TestCase):
    def test_strips_disambiguation_and_list_pages(self):
        names = research.clean_category_titles(["Mole (sauce)", "List of sauces", "Chimichurri", "Gravy"])
        self.assertEqual(names, ["Mole", "Chimichurri", "Gravy"])

    def test_dedupes_after_cleaning(self):
        self.assertEqual(research.clean_category_titles(["Mole (sauce)", "Mole (Mexican sauce)"]), ["Mole"])


class RisingTitlesTest(unittest.TestCase):
    def test_keeps_only_new_real_articles(self):
        recent = ["Main_Page", "Special:Search", "YouTube", "Oxford_Electric_Bell",
                  "Deaths_in_2026", "List_of_horror_films", "2026", "-", "Mary_Shelley"]
        baseline = ["YouTube", "Main_Page"]
        self.assertEqual(research.rising_titles(recent, baseline), ["Oxford Electric Bell", "Mary Shelley"])

    def test_respects_rank_cutoff(self):
        recent = [f"Article_{i}" for i in range(10)]
        self.assertEqual(research.rising_titles(recent, [], top_n=2), ["Article 0", "Article 1"])


class IsNewsyTest(unittest.TestCase):
    # Titles from the first real run (2026-10-08) with their style of
    # Wikipedia short description.
    def test_drops_people_and_news_events(self):
        for title, desc in [
            ("Eva Marie Saint", "American actress (born 1924)"),
            ("John Steinbeck", "American writer (1902–1968)"),
            ("Jim Bakker", "American televangelist"),
            ("2009 Fort Hood shooting", "Mass shooting in Texas, United States"),
            ("2026 Quebec general election", "Provincial election in Canada"),
            ("2024 Cornell University rape allegations", ""),
            ("Mercury", "Topics referred to by the same term"),
        ]:
            self.assertTrue(research.is_newsy(title, desc), title)

    def test_keeps_durable_subjects(self):
        for title, desc in [
            ("Pneumonic plague", "Lung infection caused by Yersinia pestis"),
            ("Carrie (miniseries)", "2002 American television film"),
            ("Pentobarbital", "Barbiturate medication"),
            ("Large language model", "Type of machine learning model"),
            ("Cathy Ames", "Fictional character in East of Eden"),
        ]:
            self.assertFalse(research.is_newsy(title, desc), title)


class FetchTrendingUncachedTest(unittest.TestCase):
    def test_drops_newsy_and_undescribed_risers(self):
        from datetime import date
        recent = ["Pneumonic_plague", "Mystery_page", "2026_Olney_house_investigation", "YouTube"]
        descriptions = {
            "Pneumonic plague": "Lung infection",
            "Mystery page": "",
            "2026 Olney house investigation": "Police investigation in Maryland",
        }
        with mock.patch.object(research, "fetch_top_articles", side_effect=[recent, ["YouTube"]]), \
             mock.patch.object(research, "fetch_descriptions", return_value=descriptions):
            got = research._fetch_trending_uncached(date(2026, 10, 8))
        self.assertEqual(got, [("Pneumonic plague", "Lung infection")])


class FetchDescriptionsTest(unittest.TestCase):
    def test_maps_normalized_and_redirected_titles_back(self):
        response = {"query": {
            "normalized": [{"from": "pneumonic plague", "to": "Pneumonic plague"}],
            "redirects": [{"from": "Carrie (2002 film)", "to": "Carrie (miniseries)"}],
            "pages": [
                {"title": "Pneumonic plague", "description": "Lung infection"},
                {"title": "Carrie (miniseries)", "description": "2002 American television film"},
                {"title": "Pentobarbital"},
            ],
        }}
        with mock.patch.object(research, "_wikipedia_get", return_value=response):
            got = research.fetch_descriptions(["pneumonic plague", "Carrie (2002 film)", "Pentobarbital"])
        self.assertEqual(got, {
            "pneumonic plague": "Lung infection",
            "Carrie (2002 film)": "2002 American television film",
            "Pentobarbital": "",
        })


class SuggestResearchSeedTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump({}, tmp)
        tmp.close()
        self.log_path = Path(tmp.name)
        self.addCleanup(self.log_path.unlink, missing_ok=True)
        for patcher in (
            mock.patch.object(rotation, "ROTATION_LOG_PATH", self.log_path),
            mock.patch.dict(os.environ, {"ENABLE_RESEARCH_TOPICS": "1", "ENABLE_TRENDING_TOPICS": "1"}),
            mock.patch.object(research, "all_script_text", return_value=""),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.trending_patcher = mock.patch.object(research, "fetch_trending_topics", return_value=[])
        self.mock_trending = self.trending_patcher.start()
        self.addCleanup(self.trending_patcher.stop)
        offered = mock.patch.object(research, "_offered_this_run", set())
        offered.start()
        self.addCleanup(offered.stop)

    def test_facts_prefer_trending_topics_in_rank_order(self):
        self.mock_trending.return_value = [(f"Rising topic {i}", "Some subject") for i in range(10)]
        seed = research.suggest_research_seed("facts")
        self.assertIn("suddenly started looking up", seed)
        for i in range(research.CANDIDATES_PER_SEED):
            self.assertIn(f"Rising topic {i}\n", seed + "\n")
        # The next facts video in the same run gets the next risers.
        second = research.suggest_research_seed("facts")
        self.assertIn("Rising topic 9", second)
        self.assertNotIn("Rising topic 0\n", second + "\n")

    def test_trending_offers_are_not_persisted_across_runs(self):
        # Real 2026-10-08: a run that failed at the LLM step burned the
        # whole trending list, leaving the re-run with nothing.
        self.mock_trending.return_value = [("Rising topic", "Some subject")]
        research.suggest_research_seed("facts")
        research._offered_this_run.clear()  # a new process / run
        self.assertIn("Rising topic", research.suggest_research_seed("facts"))

    @mock.patch.object(research, "fetch_dyk_hooks", return_value=[])
    def test_covered_check_ignores_the_parenthetical(self, _dyk):
        self.mock_trending.return_value = [("Carrie (miniseries)", "2002 television film"), ("Bioluminescence", "Light")]
        with mock.patch.object(research, "all_script_text", return_value="carrie was stephen king's first novel"):
            seed = research.suggest_research_seed("facts")
        self.assertNotIn("Carrie", seed)

    @mock.patch.object(research, "fetch_dyk_hooks")
    def test_trending_failure_falls_back_to_did_you_know(self, mock_dyk):
        self.mock_trending.side_effect = RuntimeError("connect rejected")
        mock_dyk.return_value = [f"fact number {i} is surprising enough to matter" for i in range(10)]
        self.assertIn("Did you know", research.suggest_research_seed("facts"))

    @mock.patch.object(research, "fetch_dyk_hooks")
    def test_trending_already_covered_on_channel_is_skipped(self, mock_dyk):
        mock_dyk.return_value = []
        self.mock_trending.return_value = [("Jack-o'-lantern", "Carved lantern"), ("Bioluminescence", "Light from organisms")]
        with mock.patch.object(research, "all_script_text", return_value="the jack-o'-lantern started as a turnip"):
            seed = research.suggest_research_seed("facts")
        self.assertIn("Bioluminescence", seed)
        self.assertNotIn("Jack-o'-lantern", seed)

    @mock.patch.object(research, "fetch_category_names", return_value=["Brining"])
    def test_food_gets_only_food_risers(self, _categories):
        self.mock_trending.return_value = [
            ("Squash (sport)", "Racket-and-ball sport"),
            ("Birria", "Mexican dish"),
            ("Pumpkin", "Cultivar of squash"),
        ]
        seed = research.suggest_research_seed("food")
        self.assertIn("Birria", seed)
        self.assertIn("Pumpkin", seed)
        self.assertNotIn("Squash (sport)", seed)

    @mock.patch.object(research, "fetch_category_names", return_value=["Mole"])
    def test_food_falls_back_to_categories_when_nothing_food_is_trending(self, _categories):
        self.mock_trending.return_value = [("Olympic Games", "International multi-sport event")]
        seed = research.suggest_research_seed("sauce_recipe")
        self.assertIn("Mole", seed)
        self.assertNotIn("Olympic", seed)

    def test_trending_list_is_fetched_once_per_day(self):
        self.trending_patcher.stop()
        with mock.patch.object(research, "_fetch_trending_uncached", return_value=[("A", "")]) as fetch, \
             mock.patch.dict(research._trending_cache, clear=True):
            from datetime import date
            research.fetch_trending_topics(date(2026, 10, 8))
            research.fetch_trending_topics(date(2026, 10, 8))
            self.assertEqual(fetch.call_count, 1)
        self.trending_patcher.start()

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
