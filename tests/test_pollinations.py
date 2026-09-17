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


def _response(status_code: int, content: bytes = b"") -> Mock:
    resp = Mock()
    resp.status_code = status_code
    resp.content = content
    resp.raise_for_status = Mock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = pollinations.requests.HTTPError(f"{status_code} error")
    return resp


class TestDownloadImage(unittest.TestCase):
    def test_writes_response_content_to_out_path(self):
        mock_response = _response(200, b"fake-image-bytes")
        with patch.object(pollinations.requests, "get", return_value=mock_response) as mock_get:
            with patch.object(Path, "write_bytes") as mock_write:
                pollinations.download_image("a hero", Path("/tmp/fake.jpg"), width=10, height=10)
        mock_get.assert_called_once()
        mock_write.assert_called_once_with(b"fake-image-bytes")

    def test_a_4xx_error_fails_immediately_without_retrying(self):
        mock_response = _response(400)
        with patch.object(pollinations.requests, "get", return_value=mock_response) as mock_get:
            with patch.object(pollinations.time, "sleep") as mock_sleep:
                with self.assertRaises(pollinations.requests.HTTPError):
                    pollinations.download_image("bad prompt", Path("/tmp/fake.jpg"), width=10, height=10)
        mock_get.assert_called_once()
        mock_sleep.assert_not_called()

    def test_a_transient_5xx_error_is_retried_and_can_succeed(self):
        """Real observed failure (2026-09-17): a plain HTTP 500 from
        Pollinations killed an otherwise-successful 10-beat video after
        8 beats had already rendered -- must retry a real 5xx instead of
        failing the whole video over one transient error."""
        responses = [_response(500), _response(500), _response(200, b"finally-worked")]
        with patch.object(pollinations.requests, "get", side_effect=responses) as mock_get:
            with patch.object(pollinations.time, "sleep") as mock_sleep:
                with patch.object(Path, "write_bytes") as mock_write:
                    pollinations.download_image("a hero", Path("/tmp/fake.jpg"), width=10, height=10)
        self.assertEqual(mock_get.call_count, 3)
        mock_write.assert_called_once_with(b"finally-worked")
        self.assertEqual(mock_sleep.call_count, 2)

    def test_exhausting_all_retries_on_persistent_5xx_raises(self):
        responses = [_response(500)] * 4  # first attempt + all 3 retries
        with patch.object(pollinations.requests, "get", side_effect=responses):
            with patch.object(pollinations.time, "sleep"):
                with self.assertRaises(pollinations.requests.HTTPError):
                    pollinations.download_image("a hero", Path("/tmp/fake.jpg"), width=10, height=10)


if __name__ == "__main__":
    unittest.main()
