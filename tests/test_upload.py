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

from pipeline.upload import _CTA_COMMENTS, _generate_cta_comment, post_cta_comment

_VIDEO = {"topic": "a topic", "hook": "a hook", "script_text": "a script"}


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


if __name__ == "__main__":
    unittest.main()
