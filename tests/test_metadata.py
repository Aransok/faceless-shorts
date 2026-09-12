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

from pipeline.metadata import _generate_metadata_fields

_VALID_RESPONSE = "TITLE: A Real Title\nDESCRIPTION: A real description.\nTAGS: tag1, tag2"
_MALFORMED_RESPONSE = "not even close to the expected format"


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


if __name__ == "__main__":
    unittest.main()
