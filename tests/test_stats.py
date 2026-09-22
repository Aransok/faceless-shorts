"""Pure-logic tests for pipeline/stats.py's retention collection
(2026-09-21 owner ask: real audience-retention numbers, not just view
counts) -- no real network/API calls, per CLAUDE.md's testing rules.
_load_credentials, build (googleapiclient), _load_video_log, and
update_video are all mocked at the module level."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.stats import fetch_retention, fetch_retention_curve, sync_analytics, weekly_report_data

_LOG_ROW = {
    "video_id": "vid-1",
    "youtube_video_id": "yt-1",
    "template": "facts",
    "approach": "listicle",
    "uploaded_at": "2020-01-01T00:00:00+00:00",
}


class FetchRetentionTest(unittest.TestCase):
    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_parses_rows_into_a_dict_keyed_by_video_id(self, mock_creds, mock_build):
        mock_query = mock.Mock()
        mock_query.execute.return_value = {"rows": [["yt-1", 62.5, 37.0], ["yt-2", 88.0, 52.0]]}
        mock_build.return_value.reports.return_value.query.return_value = mock_query

        result = fetch_retention(["yt-1", "yt-2"])

        self.assertEqual(
            result,
            {
                "yt-1": {"avg_view_percentage": 62.5, "avg_view_duration_seconds": 37.0},
                "yt-2": {"avg_view_percentage": 88.0, "avg_view_duration_seconds": 52.0},
            },
        )

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_empty_input_short_circuits_without_calling_the_api(self, mock_creds, mock_build):
        self.assertEqual(fetch_retention([]), {})
        mock_build.assert_not_called()

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_video_with_no_rows_is_simply_absent_from_the_result(self, mock_creds, mock_build):
        mock_query = mock.Mock()
        mock_query.execute.return_value = {"rows": []}
        mock_build.return_value.reports.return_value.query.return_value = mock_query

        self.assertEqual(fetch_retention(["yt-brand-new"]), {})

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_missing_scope_error_propagates_to_the_caller(self, mock_creds, mock_build):
        # A token not yet re-authorized with yt-analytics.readonly raises
        # here -- fetch_retention() itself stays un-defensive (matches
        # fetch_statistics()'s own style); it's sync_analytics()/
        # weekly_report_data() that catch this, not this function.
        mock_build.return_value.reports.return_value.query.return_value.execute.side_effect = (
            RuntimeError("403 insufficient scope")
        )
        with self.assertRaises(RuntimeError):
            fetch_retention(["yt-1"])


class FetchRetentionCurveTest(unittest.TestCase):
    """Owner ask (2026-09-22): "the watchtime itself we get 42[%], only
    the others just swipe [away]" -- the single average number
    fetch_retention() returns can't show WHERE viewers leave; this
    per-moment curve can."""

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_parses_rows_into_elapsed_fraction_watch_ratio_pairs(self, mock_creds, mock_build):
        mock_query = mock.Mock()
        mock_query.execute.return_value = {
            "rows": [[0.0, 1.0], [0.1, 0.62], [0.5, 0.31], [1.0, 0.18]]
        }
        mock_build.return_value.reports.return_value.query.return_value = mock_query

        result = fetch_retention_curve("yt-1")

        self.assertEqual(
            result,
            [
                {"elapsed_fraction": 0.0, "audience_watch_ratio": 1.0},
                {"elapsed_fraction": 0.1, "audience_watch_ratio": 0.62},
                {"elapsed_fraction": 0.5, "audience_watch_ratio": 0.31},
                {"elapsed_fraction": 1.0, "audience_watch_ratio": 0.18},
            ],
        )

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_uses_a_single_video_filter_not_the_multi_id_batching(self, mock_creds, mock_build):
        mock_query = mock.Mock()
        mock_query.execute.return_value = {"rows": []}
        mock_build.return_value.reports.return_value.query.return_value = mock_query

        fetch_retention_curve("yt-solo")

        call_kwargs = mock_build.return_value.reports.return_value.query.call_args.kwargs
        self.assertEqual(call_kwargs["filters"], "video==yt-solo")
        self.assertEqual(call_kwargs["dimensions"], "elapsedVideoTimeRatio")

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_no_data_returns_an_empty_list(self, mock_creds, mock_build):
        mock_query = mock.Mock()
        mock_query.execute.return_value = {"rows": []}
        mock_build.return_value.reports.return_value.query.return_value = mock_query

        self.assertEqual(fetch_retention_curve("yt-brand-new"), [])

    @mock.patch("pipeline.stats.build")
    @mock.patch("pipeline.stats._load_credentials")
    def test_error_propagates_uncaught(self, mock_creds, mock_build):
        mock_build.return_value.reports.return_value.query.return_value.execute.side_effect = (
            RuntimeError("403 insufficient scope")
        )
        with self.assertRaises(RuntimeError):
            fetch_retention_curve("yt-1")


class SyncAnalyticsRetentionTest(unittest.TestCase):
    @mock.patch("pipeline.stats.update_video")
    @mock.patch("pipeline.stats.fetch_retention")
    @mock.patch("pipeline.stats.fetch_statistics")
    @mock.patch("pipeline.stats._load_video_log")
    def test_persists_retention_alongside_view_counts_when_available(
        self, mock_log, mock_fetch_stats, mock_fetch_retention, mock_update
    ):
        mock_log.return_value = [{**_LOG_ROW, "uploaded_at": _eligible_for_sync_iso()}]
        mock_fetch_stats.return_value = {"yt-1": {"views": 100, "likes": 5, "comments": 1}}
        mock_fetch_retention.return_value = {
            "yt-1": {"avg_view_percentage": 45.0, "avg_view_duration_seconds": 22.5}
        }

        updated = sync_analytics()

        self.assertEqual(updated, 1)
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(kwargs["avg_view_percentage"], 45.0)
        self.assertEqual(kwargs["avg_view_duration_seconds"], 22.5)

    @mock.patch("pipeline.stats.update_video")
    @mock.patch("pipeline.stats.fetch_retention")
    @mock.patch("pipeline.stats.fetch_statistics")
    @mock.patch("pipeline.stats._load_video_log")
    def test_retention_failure_still_persists_view_counts(
        self, mock_log, mock_fetch_stats, mock_fetch_retention, mock_update
    ):
        # The real-world case right before re-authorization: the scope
        # isn't granted yet, so retention 403s -- must not take down the
        # view/like/comment sync that already works today.
        mock_log.return_value = [{**_LOG_ROW, "uploaded_at": _eligible_for_sync_iso()}]
        mock_fetch_stats.return_value = {"yt-1": {"views": 100, "likes": 5, "comments": 1}}
        mock_fetch_retention.side_effect = RuntimeError("403 insufficient scope")

        updated = sync_analytics()

        self.assertEqual(updated, 1)
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(kwargs["views"], 100)
        self.assertIsNone(kwargs["avg_view_percentage"])
        self.assertIsNone(kwargs["avg_view_duration_seconds"])


class WeeklyReportDataRetentionTest(unittest.TestCase):
    @mock.patch("pipeline.stats.fetch_retention")
    @mock.patch("pipeline.stats.fetch_statistics")
    @mock.patch("pipeline.stats._load_video_log")
    def test_rows_carry_none_retention_when_the_fetch_fails(
        self, mock_log, mock_fetch_stats, mock_fetch_retention
    ):
        mock_log.return_value = [{**_LOG_ROW, "uploaded_at": _recent_iso()}]
        mock_fetch_stats.return_value = {"yt-1": {"views": 100, "likes": 5, "comments": 1}}
        mock_fetch_retention.side_effect = RuntimeError("403 insufficient scope")

        rows = weekly_report_data()

        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["avg_view_percentage"])
        self.assertIsNone(rows[0]["avg_view_duration_seconds"])

    @mock.patch("pipeline.stats.fetch_retention")
    @mock.patch("pipeline.stats.fetch_statistics")
    @mock.patch("pipeline.stats._load_video_log")
    def test_rows_carry_real_retention_when_available(
        self, mock_log, mock_fetch_stats, mock_fetch_retention
    ):
        mock_log.return_value = [{**_LOG_ROW, "uploaded_at": _recent_iso()}]
        mock_fetch_stats.return_value = {"yt-1": {"views": 100, "likes": 5, "comments": 1}}
        mock_fetch_retention.return_value = {
            "yt-1": {"avg_view_percentage": 42.0, "avg_view_duration_seconds": 18.0}
        }

        rows = weekly_report_data()

        self.assertEqual(rows[0]["avg_view_percentage"], 42.0)
        self.assertEqual(rows[0]["avg_view_duration_seconds"], 18.0)


def _recent_iso() -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()


def _eligible_for_sync_iso() -> str:
    """Inside sync_analytics()'s default 48h-14d age window."""
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()


if __name__ == "__main__":
    unittest.main()
