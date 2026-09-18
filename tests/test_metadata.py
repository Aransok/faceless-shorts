"""Pure-logic tests for pipeline/metadata.py's cheap-backend retry/
fallback wiring (_generate_metadata_fields) -- no real LLM calls, no DB
writes, per CLAUDE.md's testing rules. call_bulk_llm/call_llm are both
mocked at the module level."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.metadata import (
    DESCRIPTION_MAX_CHARS,
    METADATA_FAMILY_GAME_PROMPT_PATH,
    METADATA_PROMPT_PATH,
    METADATA_QUIZ_PROMPT_PATH,
    _append_full_story,
    _generate_metadata_fields,
    generate_metadata,
)

_VALID_RESPONSE = "TITLE: A Real Title\nDESCRIPTION: A real description.\nTAGS: tag1, tag2"
_MALFORMED_RESPONSE = "not even close to the expected format"

_BASE_VIDEO = {
    "id": "vid-1", "template": "family_game_night", "topic": "a topic", "hook": "a hook",
    "script_text": "a script", "approach": None,
}


class GenerateMetadataFieldsTest(unittest.TestCase):
    @mock.patch("pipeline.metadata.call_llm")
    @mock.patch("pipeline.metadata.call_bulk_llm")
    def test_uses_bulk_backend_on_first_try_when_valid(self, mock_bulk, mock_claude):
        mock_bulk.return_value = _VALID_RESPONSE
        fields = _generate_metadata_fields("prompt")
        self.assertEqual(fields["TITLE"], "A Real Title")
        mock_bulk.assert_called_once()
        mock_claude.assert_not_called()

    @mock.patch("pipeline.metadata.call_llm")
    @mock.patch("pipeline.metadata.call_bulk_llm")
    def test_retries_bulk_backend_once_before_escalating(self, mock_bulk, mock_claude):
        mock_bulk.side_effect = [_MALFORMED_RESPONSE, _VALID_RESPONSE]
        fields = _generate_metadata_fields("prompt")
        self.assertEqual(fields["TITLE"], "A Real Title")
        self.assertEqual(mock_bulk.call_count, 2)
        mock_claude.assert_not_called()

    @mock.patch("pipeline.metadata.call_llm")
    @mock.patch("pipeline.metadata.call_bulk_llm")
    def test_falls_back_to_claude_after_two_bad_bulk_responses(self, mock_bulk, mock_claude):
        mock_bulk.side_effect = [_MALFORMED_RESPONSE, _MALFORMED_RESPONSE]
        mock_claude.return_value = _VALID_RESPONSE
        fields = _generate_metadata_fields("prompt")
        self.assertEqual(fields["TITLE"], "A Real Title")
        self.assertEqual(mock_bulk.call_count, 2)
        mock_claude.assert_called_once()

    @mock.patch("pipeline.metadata.call_llm")
    @mock.patch("pipeline.metadata.call_bulk_llm")
    def test_bulk_backend_raising_counts_as_a_bad_response_too(self, mock_bulk, mock_claude):
        # e.g. GROQ_API_KEY not configured yet -- RuntimeError, not a
        # malformed-text ValueError, but still just "try again / escalate."
        mock_bulk.side_effect = RuntimeError("GROQ_API_KEY not set")
        mock_claude.return_value = _VALID_RESPONSE
        fields = _generate_metadata_fields("prompt")
        self.assertEqual(fields["TITLE"], "A Real Title")
        mock_claude.assert_called_once()

    @mock.patch("pipeline.metadata.call_llm")
    @mock.patch("pipeline.metadata.call_bulk_llm")
    def test_claude_fallback_failure_propagates(self, mock_bulk, mock_claude):
        mock_bulk.side_effect = [_MALFORMED_RESPONSE, _MALFORMED_RESPONSE]
        mock_claude.return_value = _MALFORMED_RESPONSE
        with self.assertRaises(ValueError):
            _generate_metadata_fields("prompt")


class GenerateMetadataPromptSelectionTest(unittest.TestCase):
    """generate_metadata() picks the right prompt FILE per template --
    real files read from disk (same as production), only the LLM call/
    DB writes are mocked."""

    def setUp(self):
        patchers = {
            "get_video": mock.patch("pipeline.metadata.get_video", return_value=dict(_BASE_VIDEO)),
            "get_video_steps": mock.patch("pipeline.metadata.get_video_steps", return_value=[]),
            "update_video": mock.patch("pipeline.metadata.update_video"),
            "fields": mock.patch(
                "pipeline.metadata._generate_metadata_fields",
                return_value={"TITLE": "A Real Title", "DESCRIPTION": "A real description.", "TAGS": "tag1, tag2"},
            ),
        }
        self.mocks = {name: p.start() for name, p in patchers.items()}
        for p in patchers.values():
            self.addCleanup(p.stop)

    def test_family_game_night_uses_its_own_prompt_file(self):
        generate_metadata("vid-1")
        prompt_used = self.mocks["fields"].call_args.args[0]
        expected_snippet = METADATA_FAMILY_GAME_PROMPT_PATH.read_text(encoding="utf-8").split("\n")[0]
        self.assertIn(expected_snippet, prompt_used)
        # And NOT the generic Shorts prompt's own distinguishing line.
        generic_only_line = "you are writing the youtube shorts title"
        self.assertNotIn(generic_only_line, prompt_used.lower())

    def test_quiz_longform_still_uses_the_quiz_prompt(self):
        self.mocks["get_video"].return_value = {**_BASE_VIDEO, "template": "quiz_longform"}
        generate_metadata("vid-1")
        prompt_used = self.mocks["fields"].call_args.args[0]
        expected_snippet = METADATA_QUIZ_PROMPT_PATH.read_text(encoding="utf-8").split("\n")[0]
        self.assertIn(expected_snippet, prompt_used)

    def test_facts_still_uses_the_generic_shorts_prompt(self):
        self.mocks["get_video"].return_value = {**_BASE_VIDEO, "template": "facts"}
        generate_metadata("vid-1")
        prompt_used = self.mocks["fields"].call_args.args[0]
        expected_snippet = METADATA_PROMPT_PATH.read_text(encoding="utf-8").split("\n")[0]
        self.assertIn(expected_snippet, prompt_used)


class AppendFullStoryTest(unittest.TestCase):
    """veylorn_story owner ask (2026-09-18): full narration text in the
    description, without ever crowding out the LLM-written CTA."""

    def test_appends_the_full_story_under_a_header(self):
        result = _append_full_story("A short description.", "Once upon a time in Veylorn.")
        self.assertIn("A short description.", result)
        self.assertIn("Full story:", result)
        self.assertIn("Once upon a time in Veylorn.", result)
        self.assertTrue(result.index("A short description.") < result.index("Full story:"))

    def test_empty_script_text_leaves_description_unchanged(self):
        self.assertEqual(_append_full_story("A short description.", ""), "A short description.")

    def test_long_story_is_truncated_to_fit_the_real_youtube_limit(self):
        description = "x" * 100
        story = "word " * 2000  # far longer than any real budget
        result = _append_full_story(description, story)
        self.assertLessEqual(len(result), DESCRIPTION_MAX_CHARS)
        self.assertTrue(result.endswith("…"))
        self.assertIn(description, result, "the description itself must never be the part that gets cut")

    def test_description_already_at_the_limit_gets_no_story_appended(self):
        description = "x" * DESCRIPTION_MAX_CHARS
        result = _append_full_story(description, "some story text")
        self.assertEqual(result, description)


if __name__ == "__main__":
    unittest.main()
