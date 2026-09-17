"""Pure-logic tests for pipeline/pollinations.py's URL building -- no
real network calls, per CLAUDE.md's testing rules.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from pipeline import pollinations


class TestBuildImageUrl(unittest.TestCase):
    def test_prompt_is_url_encoded(self):
        url = pollinations.build_image_url("a dragon & a knight", width=100, height=50)
        self.assertNotIn("&", url.split("?")[0], "prompt segment must not leak an unencoded '&'")
        self.assertIn("dragon", url)

    def test_width_and_height_are_included(self):
        url = pollinations.build_image_url("a castle", width=1920, height=1080)
        self.assertIn("width=1920", url)
        self.assertIn("height=1080", url)

    def test_seed_included_when_given(self):
        url = pollinations.build_image_url("a forest", width=100, height=100, seed=42)
        self.assertIn("seed=42", url)

    def test_seed_omitted_when_not_given(self):
        url = pollinations.build_image_url("a forest", width=100, height=100)
        self.assertNotIn("seed=", url)

    def test_starts_with_base_url(self):
        url = pollinations.build_image_url("test", width=10, height=10)
        self.assertTrue(url.startswith(pollinations.POLLINATIONS_BASE_URL))


class TestDownloadImage(unittest.TestCase):
    def test_writes_response_content_to_out_path(self):
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.content = b"fake-image-bytes"
        with patch.object(pollinations.requests, "get", return_value=mock_response) as mock_get:
            with patch.object(Path, "write_bytes") as mock_write:
                pollinations.download_image("a hero", Path("/tmp/fake.jpg"), width=10, height=10)
        mock_get.assert_called_once()
        mock_write.assert_called_once_with(b"fake-image-bytes")


if __name__ == "__main__":
    unittest.main()
