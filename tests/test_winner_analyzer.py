"""Pure-logic tests for pipeline/winner_analyzer.py -- no real network/DB
calls per CLAUDE.md's testing rules. all_uploads() (data/videos.json) and
get_video() (state.db) are both mocked; only the classification/pattern/
RPM-estimate math itself is under test."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import winner_analyzer as wa

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)


def _log_row(video_id: str, template: str, hours_ago: float, approach: str = "storytelling_hook") -> dict:
    uploaded = NOW - timedelta(hours=hours_ago)
    return {
        "video_id": video_id,
        "youtube_video_id": f"yt-{video_id}",
        "uploaded_at": uploaded.isoformat(),
        "template": template,
        "approach": approach,
    }


def _video_row(views: int | None, likes: int = 0, comments: int = 0, item_count=None, visual_density=None) -> dict:
    return {
        "views": views,
        "likes": likes,
        "comment_count": comments,
        "genome_item_count": item_count,
        "genome_visual_density": visual_density,
        "topic": "a topic",
        "hook": "a hook",
    }


class FreshnessTest(unittest.TestCase):
    def test_video_younger_than_freeze_window_is_excluded(self):
        rows = [_log_row("v1", "facts", hours_ago=24)]
        with mock.patch.object(wa, "all_uploads", return_value=rows), \
             mock.patch.object(wa, "get_video", return_value=_video_row(1000)):
            self.assertEqual(wa.eligible_rows(now=NOW), [])

    def test_video_older_than_freeze_window_is_included(self):
        rows = [_log_row("v1", "facts", hours_ago=200)]
        with mock.patch.object(wa, "all_uploads", return_value=rows), \
             mock.patch.object(wa, "get_video", return_value=_video_row(1000)):
            result = wa.eligible_rows(now=NOW)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["views"], 1000)

    def test_video_with_no_synced_stats_is_excluded(self):
        rows = [_log_row("v1", "facts", hours_ago=200)]
        with mock.patch.object(wa, "all_uploads", return_value=rows), \
             mock.patch.object(wa, "get_video", return_value=_video_row(None)):
            self.assertEqual(wa.eligible_rows(now=NOW), [])

    def test_missing_state_db_row_is_excluded_not_crashed_on(self):
        rows = [_log_row("v1", "facts", hours_ago=200)]
        with mock.patch.object(wa, "all_uploads", return_value=rows), \
             mock.patch.object(wa, "get_video", return_value=None):
            self.assertEqual(wa.eligible_rows(now=NOW), [])


class ClassifyTest(unittest.TestCase):
    def test_zero_baseline_is_normal(self):
        self.assertEqual(wa.classify(500, 0), "NORMAL")

    def test_below_promising_multiplier_is_normal(self):
        self.assertEqual(wa.classify(100, 100), "NORMAL")

    def test_at_promising_multiplier(self):
        self.assertEqual(wa.classify(130, 100), "PROMISING")

    def test_at_winner_multiplier(self):
        self.assertEqual(wa.classify(200, 100), "WINNER")

    def test_at_breakout_multiplier(self):
        self.assertEqual(wa.classify(500, 100), "BREAKOUT")

    def test_just_under_a_threshold_stays_in_the_lower_band(self):
        self.assertEqual(wa.classify(199, 100), "PROMISING")


class BaselineTest(unittest.TestCase):
    def test_uses_per_template_average_when_sample_is_large_enough(self):
        rows = [
            {"template": "facts", "views": 100},
            {"template": "facts", "views": 200},
            {"template": "facts", "views": 300},
            {"template": "programming", "views": 900},
        ]
        self.assertEqual(wa._baseline_views(rows, "facts"), 200.0)

    def test_falls_back_to_whole_pool_when_template_sample_too_small(self):
        rows = [
            {"template": "facts", "views": 100},
            {"template": "programming", "views": 900},
        ]
        # Only 1 "facts" row -- below MIN_TEMPLATE_SAMPLE -- falls back to
        # the whole pool's average (100 + 900) / 2 = 500, not just 100.
        self.assertEqual(wa._baseline_views(rows, "facts"), 500.0)


class EngagementRateTest(unittest.TestCase):
    def test_computes_likes_plus_comments_over_views(self):
        row = {"views": 1000, "likes": 40, "comment_count": 10}
        self.assertAlmostEqual(wa.engagement_rate(row), 0.05)

    def test_zero_views_is_zero_not_a_crash(self):
        row = {"views": 0, "likes": 5, "comment_count": 1}
        self.assertEqual(wa.engagement_rate(row), 0.0)


class DescribeCommonPatternTest(unittest.TestCase):
    def test_fewer_than_two_winners_says_not_enough_data(self):
        self.assertIn("Not enough winners", wa.describe_common_pattern([], []))
        self.assertIn("Not enough winners", wa.describe_common_pattern([{"template": "facts", "approach": "x"}], []))

    def test_no_shared_combo_among_winners(self):
        winners = [
            {"template": "facts", "approach": "a"},
            {"template": "programming", "approach": "b"},
        ]
        self.assertIn("don't share a common", wa.describe_common_pattern(winners, []))

    def test_real_shared_pattern_is_reported_with_numbers(self):
        winners = [
            {"template": "facts", "approach": "storytelling_hook"},
            {"template": "facts", "approach": "storytelling_hook"},
            {"template": "programming", "approach": "listicle"},
        ]
        pool = [{"template": "facts", "approach": "storytelling_hook"}] * 2 + [{"template": "programming", "approach": "listicle"}] * 8
        result = wa.describe_common_pattern(winners, pool)
        self.assertIn("2/3 winners", result)
        self.assertIn("facts", result)
        self.assertIn("storytelling_hook", result)


class EstimatedValueTest(unittest.TestCase):
    def test_higher_rpm_template_can_beat_higher_view_template(self):
        # Real point from the owner-shared research: fewer views doesn't
        # mean less value once RPM differs enough between genres.
        rows = [
            {"template": "facts", "views": 1000},
            {"template": "programming", "views": 300},
        ]
        values = wa.estimated_value_per_video(rows)
        self.assertGreater(values["programming"], values["facts"])

    def test_unknown_template_defaults_to_zero_rpm(self):
        rows = [{"template": "some_new_template", "views": 1000}]
        values = wa.estimated_value_per_video(rows)
        self.assertEqual(values["some_new_template"], 0.0)


if __name__ == "__main__":
    unittest.main()
