"""Tests for the Visual Director upgrade to the facts/sauce_recipe
visual pipeline (see visuals_facts.py, plan.py's tiered visual-plan
parsing). stdlib unittest only -- no new dependency, no test framework
existed in this repo before this file, so this is the smallest addition
that fits. Mocks _search_pexels_videos everywhere -- never hits the real
Pexels API.
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from pipeline import visuals_facts as vf


def _fake_video(video_id: int, slug_words: str) -> dict:
    return {
        "id": video_id,
        "url": f"https://www.pexels.com/video/{slug_words.replace(' ', '-')}-{video_id}/",
        "video_files": [{"file_type": "video/mp4", "width": 1080, "height": 1920, "link": "x"}],
    }


class TestVisualPlanParsing(unittest.TestCase):
    def test_new_json_format_parsed_directly(self):
        raw = json.dumps({"subject": "Oxford Electric Bell", "exact": ["a"], "representation": ["b"], "concept": []})
        plan = vf._parse_beat_visual_plan(raw)
        self.assertEqual(plan["subject"], "Oxford Electric Bell")
        self.assertEqual(plan["exact"], ["a"])

    def test_legacy_comma_format_falls_back_into_exact_tier(self):
        plan = vf._parse_beat_visual_plan("octopus swimming, ocean reef")
        self.assertIsNone(plan["subject"])
        self.assertEqual(plan["exact"], ["octopus swimming", "ocean reef"])
        self.assertEqual(plan["representation"], [])
        self.assertEqual(plan["concept"], [])


class TestQuerySpecificity(unittest.TestCase):
    def test_specific_subject_queries_are_not_collapsed_to_broad_category(self):
        """The whole point of the upgrade: a specific subject's exact
        queries must stay specific, not get flattened into something as
        broad as "science laboratory"."""
        raw = json.dumps({
            "subject": "Oxford Electric Bell",
            "exact": ["Oxford electric bell", "historic electric bell apparatus"],
            "representation": ["antique brass bell mechanism"],
            "concept": [],
        })
        plan = vf._parse_beat_visual_plan(raw)
        broad_terms = {"science", "laboratory", "technology", "history"}
        for query in plan["exact"]:
            self.assertFalse(
                set(query.lower().split()) & broad_terms,
                f"exact query {query!r} collapsed into a broad generic term",
            )


class TestCandidateScoring(unittest.TestCase):
    def test_exact_tier_outranks_generic_fallback_with_similar_overlap(self):
        video = _fake_video(1, "oxford electric bell apparatus")
        exact_score, exact_type = vf._score_candidate(video, "Oxford electric bell", "exact_subject", "Oxford Electric Bell")
        generic_score, generic_type = vf._score_candidate(video, "Oxford electric bell", "generic_fallback", "Oxford Electric Bell")
        self.assertEqual(exact_type, "exact_subject")
        self.assertEqual(generic_type, "generic_fallback")
        self.assertGreater(exact_score, generic_score)

    def test_misleading_zero_overlap_candidate_cannot_stay_exact_subject(self):
        """A candidate returned FOR an exact-subject query but whose own
        description shares no real words with the query/subject can't be
        trusted as actually showing the subject -- must be demoted, not
        silently labeled exact_subject just because of which tier
        searched for it."""
        video = _fake_video(2, "random unrelated stock footage clip")
        score, match_type = vf._score_candidate(video, "Oxford electric bell", "exact_subject", "Oxford Electric Bell")
        self.assertNotEqual(match_type, "exact_subject")
        self.assertEqual(match_type, "accurate_representation")

    def test_real_overlap_keeps_exact_subject_classification(self):
        video = _fake_video(3, "oxford electric bell close up")
        score, match_type = vf._score_candidate(video, "Oxford electric bell", "exact_subject", "Oxford Electric Bell")
        self.assertEqual(match_type, "exact_subject")
        self.assertGreaterEqual(score, vf.MIN_ACCEPTABLE_SCORE)

    def test_generic_scene_words_in_query_cannot_manufacture_false_overlap(self):
        """Real bug, caught on a live test run: query "Slinky toy walking
        down stairs" shares generic scene words ("down", "stairs") with
        a completely unrelated "person walking down stairs" clip that
        has nothing to do with a Slinky. Checking overlap against the
        whole query let that false match through as exact_subject --
        must check against the SUBJECT specifically."""
        video = _fake_video(4, "a woman going down on stairs")
        score, match_type = vf._score_candidate(
            video, "Slinky toy walking down stairs", "exact_subject", "Slinky spring toy"
        )
        self.assertNotEqual(match_type, "exact_subject")


class TestTierProgressionAndRanking(unittest.TestCase):
    def test_stops_early_once_enough_good_candidates_found_in_exact_tier(self):
        """Should not need to search accurate_representation/concept
        tiers at all if the exact tier already found enough strong
        matches -- verified by asserting the mocked search function was
        never called with a representation/concept query."""
        plan = {
            "subject": "Oxford Electric Bell",
            "exact": ["Oxford electric bell"],
            "representation": ["should not be searched"],
            "concept": ["should not be searched either"],
        }
        results_by_query = {
            "Oxford electric bell": [
                _fake_video(10, "oxford electric bell apparatus"),
                _fake_video(11, "oxford electric bell close up"),
            ],
        }

        def fake_search(query, api_key, per_page=5):
            self.assertIn(query, results_by_query, f"unexpected extra query {query!r} -- tier progression didn't stop early")
            return results_by_query[query]

        with patch.object(vf, "_search_pexels_videos", side_effect=fake_search):
            pool, log = vf._build_clip_pool(plan, api_key="fake", min_count=2)

        self.assertEqual(len(pool), 2)
        self.assertTrue(all(entry["match_type"] == "exact_subject" for entry in log))

    def test_falls_through_tiers_when_exact_search_yields_nothing_good(self):
        plan = {
            "subject": "Oxford Electric Bell",
            "exact": ["Oxford electric bell"],
            "representation": ["antique brass bell mechanism"],
            "concept": [],
        }
        results_by_query = {
            "Oxford electric bell": [_fake_video(20, "totally unrelated content")],
            "antique brass bell mechanism": [_fake_video(21, "antique brass bell mechanism demo")],
        }

        def fake_search(query, api_key, per_page=5):
            return results_by_query.get(query, [])

        with patch.object(vf, "_search_pexels_videos", side_effect=fake_search):
            pool, log = vf._build_clip_pool(plan, api_key="fake", min_count=1)

        self.assertEqual(log[0]["match_type"], "accurate_representation")

    def test_selects_highest_scoring_candidates_not_first_found(self):
        plan = {"subject": "Oxford Electric Bell", "exact": ["Oxford electric bell"], "representation": [], "concept": []}
        results_by_query = {
            "Oxford electric bell": [
                _fake_video(30, "unrelated stock clip"),  # first result, but weak match
                _fake_video(31, "oxford electric bell close up"),  # second result, but strong match
            ],
        }

        def fake_search(query, api_key, per_page=5):
            return results_by_query[query]

        with patch.object(vf, "_search_pexels_videos", side_effect=fake_search):
            pool, log = vf._build_clip_pool(plan, api_key="fake", min_count=1)

        self.assertEqual(pool[0]["id"], 31, "picked the first result instead of the higher-scoring one")


if __name__ == "__main__":
    unittest.main()
