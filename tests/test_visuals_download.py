"""Clip download reliability (pipeline/visuals_facts.py, 2026-10-31).
Mocks requests.get and time.sleep: no network, no waiting."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests

from pipeline import visuals_facts as vf

CLIP = {"id": 7, "video_files": [{"link": "https://example.test/c.mp4", "width": 1080, "height": 1920, "file_type": "video/mp4"}]}


def _ok(content: bytes = b"video-bytes") -> MagicMock:
    resp = MagicMock()
    resp.content = content
    resp.raise_for_status.return_value = None
    return resp


def _http_error(status: int) -> requests.HTTPError:
    resp = MagicMock()
    resp.status_code = status
    return requests.HTTPError(f"{status} error", response=resp)


class DownloadClipRetryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out = self.tmp / "c.mp4"
        patcher = patch.object(vf, "_pick_video_file", return_value="https://example.test/c.mp4")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_retries_a_timeout_then_succeeds(self):
        with patch("requests.get", side_effect=[requests.Timeout("slow"), _ok()]) as get, patch("time.sleep") as sleep:
            vf._download_clip(CLIP, self.out)
        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once()
        self.assertEqual(self.out.read_bytes(), b"video-bytes")

    def test_retries_5xx_and_429(self):
        for status in (500, 503, 429):
            bad = MagicMock()
            bad.raise_for_status.side_effect = _http_error(status)
            with patch("requests.get", side_effect=[bad, _ok()]) as get, patch("time.sleep"):
                vf._download_clip(CLIP, self.out)
            self.assertEqual(get.call_count, 2, status)

    def test_a_dead_link_is_not_retried(self):
        bad = MagicMock()
        bad.raise_for_status.side_effect = _http_error(404)
        with patch("requests.get", return_value=bad) as get, patch("time.sleep") as sleep, self.assertRaises(requests.HTTPError):
            vf._download_clip(CLIP, self.out)
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    def test_gives_up_after_the_attempt_limit(self):
        with patch("requests.get", side_effect=requests.ConnectionError("down")) as get, patch("time.sleep"), self.assertRaises(requests.ConnectionError):
            vf._download_clip(CLIP, self.out)
        self.assertEqual(get.call_count, vf.CLIP_DOWNLOAD_ATTEMPTS)


class DownloadPoolTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.pool = [{"id": i} for i in (1, 2, 3)]

    def test_one_failed_clip_is_skipped_not_fatal(self):
        def fake(clip, path):
            if clip["id"] == 2:
                raise requests.ConnectionError("down")
            path.write_bytes(b"x")

        with patch.object(vf, "_download_clip", side_effect=fake):
            paths = vf._download_pool(self.pool, self.tmp, beat_index=1)
        self.assertEqual([p.name for p in paths], ["beat1_source_00.mp4", "beat1_source_02.mp4"])

    def test_every_clip_failing_raises_a_clear_error(self):
        with patch.object(vf, "_download_clip", side_effect=requests.ConnectionError("down")), self.assertRaisesRegex(
            RuntimeError, "beat 2: every stock clip download failed \\(3 tried\\)"
        ):
            vf._download_pool(self.pool, self.tmp, beat_index=2)

    def test_a_non_network_error_is_not_swallowed(self):
        with patch.object(vf, "_download_clip", side_effect=ValueError("bug")), self.assertRaises(ValueError):
            vf._download_pool(self.pool, self.tmp, beat_index=1)


if __name__ == "__main__":
    unittest.main()
