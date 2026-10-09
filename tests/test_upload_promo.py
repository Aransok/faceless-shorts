"""Pure logic for scripts/upload_promo.py -- no real YouTube calls."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import upload_promo  # noqa: E402

MANIFEST = ROOT / "assets" / "promo" / "project-ember" / "manifest.json"


class UploadPromoTest(unittest.TestCase):
    def test_already_uploaded_entries_are_skipped(self):
        manifest = [{"key": "a"}, {"key": "b"}]
        log = [{"video_id": "a", "youtube_video_id": "x"}]
        self.assertEqual(upload_promo.pending_entries(manifest, log), [{"key": "b"}])

    def test_body_is_public_and_not_made_for_kids(self):
        body = upload_promo.build_body({"title": "T", "description": "D", "tags": ["t"], "category_id": "20"})
        self.assertEqual(body["status"], {"privacyStatus": "public", "selfDeclaredMadeForKids": False})
        self.assertEqual(body["snippet"]["categoryId"], "20")

    def test_trailer_update_keeps_every_other_channel_setting(self):
        # channels.update clears whatever brandingSettings fields are omitted.
        branding = {"channel": {"description": "facts daily", "keywords": "facts food"}, "watch": {"x": 1}}
        updated = upload_promo.with_trailer(branding, "vid123")
        self.assertEqual(updated["channel"]["description"], "facts daily")
        self.assertEqual(updated["channel"]["keywords"], "facts food")
        self.assertEqual(updated["watch"], {"x": 1})
        self.assertEqual(updated["channel"]["unsubscribedTrailer"], "vid123")
        self.assertNotIn("unsubscribedTrailer", branding["channel"])

    def test_set_channel_trailer_sends_the_full_branding(self):
        youtube = mock.MagicMock()
        youtube.channels().list().execute.return_value = {
            "items": [{"id": "UC1", "brandingSettings": {"channel": {"description": "d"}}}]
        }
        upload_promo.set_channel_trailer(youtube, "vid123")
        body = youtube.channels().update.call_args.kwargs["body"]
        self.assertEqual(body["id"], "UC1")
        self.assertEqual(body["brandingSettings"]["channel"], {"description": "d", "unsubscribedTrailer": "vid123"})


class ProjectEmberManifestTest(unittest.TestCase):
    def test_entries_are_valid_for_youtube(self):
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(len({e["key"] for e in manifest}), len(manifest))
        self.assertEqual(sum(1 for e in manifest if e.get("channel_trailer")), 1)
        for entry in manifest:
            self.assertTrue((MANIFEST.parent / entry["file"]).exists(), entry["file"])
            self.assertLessEqual(len(entry["title"]), 100)
            self.assertLessEqual(len(entry["description"]), 5000)
            self.assertNotIn("<", entry["title"] + entry["description"])


if __name__ == "__main__":
    unittest.main()
