"""Pure-logic tests for pipeline/upload.py's CTA-comment cheap-backend
wiring (_generate_cta_comment, post_cta_comment's fallback) -- no real
LLM/YouTube calls, no DB writes, per CLAUDE.md's testing rules.
call_bulk_llm is mocked; the YouTube client is a plain Mock passed in as
an argument, never constructed internally by these functions."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import tempfile
from datetime import datetime, timedelta, timezone

from pipeline import upload as upload_module
from pipeline.upload import (
    _CTA_COMMENTS,
    CTA_COMMENT_PROBABILITY,
    _generate_cta_comment,
    _in_publish_window,
    _next_publish_time,
    _snap_into_publish_window,
    post_cta_comment,
    upload,
)

_VIDEO = {"topic": "a topic", "hook": "a hook", "script_text": "a script"}

_UPLOAD_VIDEO = {
    "id": "vid-1",
    "status": "approved",
    "final_path": "/fake/path.mp4",
    "template": "facts",
    "title": "a title",
    "description": "a description",
    "tags": "tag1, tag2",
    "topic": "a topic",
    "hook": "a hook",
    "script_text": "a script",
    "approach": "storytelling_hook",
}


class GenerateCtaCommentTest(unittest.TestCase):
    @mock.patch("pipeline.upload.call_bulk_llm")
    def test_parses_comment_field_from_bulk_backend(self, mock_bulk):
        mock_bulk.return_value = "COMMENT: Which one surprised you most?"
        comment = _generate_cta_comment(_VIDEO)
        self.assertEqual(comment, "Which one surprised you most?")
        mock_bulk.assert_called_once()

    @mock.patch("pipeline.upload.call_bulk_llm")
    def test_missing_comment_field_raises(self, mock_bulk):
        mock_bulk.return_value = "no comment field here"
        with self.assertRaises(ValueError):
            _generate_cta_comment(_VIDEO)

    @mock.patch("pipeline.upload.call_bulk_llm")
    def test_empty_comment_raises(self, mock_bulk):
        mock_bulk.return_value = "COMMENT:    "
        with self.assertRaises(ValueError):
            _generate_cta_comment(_VIDEO)


class PostCtaCommentTest(unittest.TestCase):
    @mock.patch("pipeline.upload.call_bulk_llm")
    def test_posts_the_generated_comment(self, mock_bulk):
        mock_bulk.return_value = "COMMENT: Real, specific comment."
        youtube = mock.Mock()
        post_cta_comment(_VIDEO, "yt123", youtube)
        body = youtube.commentThreads().insert.call_args
        # commentThreads() itself is called twice (once above, once
        # inside post_cta_comment) since youtube is a bare Mock -- assert
        # against the actual insert() call the function made.
        insert_calls = youtube.commentThreads.return_value.insert.call_args_list
        posted_text = insert_calls[-1].kwargs["body"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
        self.assertEqual(posted_text, "Real, specific comment.")

    @mock.patch("pipeline.upload.call_bulk_llm")
    def test_falls_back_to_canned_pool_on_any_failure(self, mock_bulk):
        mock_bulk.side_effect = RuntimeError("GROQ_API_KEY not set")
        youtube = mock.Mock()
        post_cta_comment(_VIDEO, "yt123", youtube)
        insert_calls = youtube.commentThreads.return_value.insert.call_args_list
        posted_text = insert_calls[-1].kwargs["body"]["snippet"]["topLevelComment"]["snippet"]["textOriginal"]
        self.assertIn(posted_text, _CTA_COMMENTS)


class UploadCtaCommentProbabilityTest(unittest.TestCase):
    """Real feedback (2026-09-13): a CTA comment on literally every
    upload read as spammy. upload() now rolls once per video and either
    attempts a comment or marks the video done (cta_comment_posted=1)
    without ever calling the comment machinery -- no real YouTube/LLM
    calls, everything upload() touches is mocked."""

    def setUp(self):
        patchers = {
            "get_video": mock.patch("pipeline.upload.get_video", return_value=dict(_UPLOAD_VIDEO)),
            "path_exists": mock.patch("pipeline.upload.Path.exists", return_value=True),
            "load_credentials": mock.patch("pipeline.upload._load_credentials"),
            "build": mock.patch("pipeline.upload.build"),
            "media_upload": mock.patch("pipeline.upload.MediaFileUpload"),
            "update_video": mock.patch("pipeline.upload.update_video"),
            "log_uploaded": mock.patch("pipeline.upload._log_uploaded_video"),
            "upload_thumbnail": mock.patch("pipeline.upload.upload_thumbnail"),
            "post_cta_comment": mock.patch("pipeline.upload.post_cta_comment"),
        }
        self.mocks = {name: p.start() for name, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)

        youtube_client = mock.Mock()
        self.mocks["build"].return_value = youtube_client
        self.mocks["build"].return_value.videos.return_value.insert.return_value.execute.return_value = {
            "id": "yt-123"
        }

        env_patcher = mock.patch.dict("os.environ", {"UPLOAD_VISIBILITY": "public"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    def test_losing_the_roll_skips_comment_and_marks_done_immediately(self):
        with mock.patch("pipeline.upload.random.random", return_value=CTA_COMMENT_PROBABILITY):
            # random() >= CTA_COMMENT_PROBABILITY -- losing roll
            upload("vid-1")
        self.mocks["post_cta_comment"].assert_not_called()
        cta_calls = [c for c in self.mocks["update_video"].call_args_list if c.kwargs.get("cta_comment_posted") == 1]
        self.assertEqual(len(cta_calls), 1)

    def test_winning_the_roll_attempts_the_comment(self):
        with mock.patch("pipeline.upload.random.random", return_value=0.0):
            # random() < CTA_COMMENT_PROBABILITY (any positive probability) -- winning roll
            upload("vid-1")
        self.mocks["post_cta_comment"].assert_called_once()


def _utc(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, day, hour, minute, tzinfo=timezone.utc)


class PublishWindowTest(unittest.TestCase):
    """Real channel data (2026-09-24): Shorts going public 00:00-04:00 UTC
    had ~5x the median views of ones going public 04:00-12:00 UTC --
    every publish time now lands inside 20:00-04:00 UTC."""

    def test_window_spans_midnight(self):
        self.assertTrue(_in_publish_window(_utc(24, 20, 0)))
        self.assertTrue(_in_publish_window(_utc(24, 23, 59)))
        self.assertTrue(_in_publish_window(_utc(25, 0, 30)))
        self.assertTrue(_in_publish_window(_utc(25, 3, 59)))

    def test_dead_hours_are_outside_the_window(self):
        for hour in (4, 6, 9, 12, 15, 19):
            self.assertFalse(_in_publish_window(_utc(24, hour, 0)), f"{hour}:00 UTC should be outside")

    def test_in_window_time_is_left_alone(self):
        t = _utc(24, 22, 15)
        self.assertEqual(_snap_into_publish_window(t), t)

    def test_early_morning_time_moves_to_that_evening_not_the_next(self):
        snapped = _snap_into_publish_window(_utc(24, 6, 0))
        self.assertEqual(snapped.date(), _utc(24, 20).date())
        self.assertTrue(_utc(24, 20, 0) <= snapped <= _utc(24, 20, 30))

    def test_late_afternoon_time_moves_to_the_same_evening(self):
        snapped = _snap_into_publish_window(_utc(24, 19, 30))
        self.assertTrue(_utc(24, 20, 0) <= snapped <= _utc(24, 20, 30))

    def _with_log(self, records: list[dict]):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(records, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink, missing_ok=True)
        patcher = mock.patch.object(upload_module, "VIDEOS_LOG_PATH", Path(tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_full_six_video_batch_never_lands_in_dead_hours(self):
        # The exact real failure: a batch starting ~18:00 UTC used to push
        # its 4th/5th videos to ~05:00-09:00 UTC.
        self._with_log([])
        now = _utc(24, 18, 0)
        scheduled = []
        for _ in range(6):
            t = _next_publish_time(now=now)
            scheduled.append(t)
            self._with_log([{"scheduled_publish_at": s.isoformat()} for s in scheduled])
        for t in scheduled:
            self.assertTrue(_in_publish_window(t), f"{t.isoformat()} landed outside the window")
        self.assertEqual(scheduled, sorted(scheduled), "publish times must stay in order")

    def test_a_six_video_batch_starting_at_the_opening_fits_one_evening(self):
        self._with_log([])
        scheduled = []
        for _ in range(6):
            scheduled.append(_next_publish_time(now=_utc(24, 18, 45)))
            self._with_log([{"scheduled_publish_at": s.isoformat()} for s in scheduled])
        self.assertLess(scheduled[-1] - scheduled[0], timedelta(hours=upload_module.PUBLISH_WINDOW_HOURS))

    def test_spacing_still_respects_the_minimum_gap(self):
        self._with_log([{"scheduled_publish_at": _utc(24, 21, 0).isoformat()}])
        t = _next_publish_time(now=_utc(24, 18, 0))
        self.assertGreaterEqual(t - _utc(24, 21, 0), timedelta(hours=upload_module.PUBLISH_GAP_MIN_HOURS))


if __name__ == "__main__":
    unittest.main()
