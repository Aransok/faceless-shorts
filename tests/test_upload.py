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

from pipeline.upload import _CTA_COMMENTS, CTA_COMMENT_PROBABILITY, _generate_cta_comment, post_cta_comment, upload

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


if __name__ == "__main__":
    unittest.main()
