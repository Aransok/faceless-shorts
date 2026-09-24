"""Pure-logic tests for scripts/reconcile_uploads.py -- no YouTube calls."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import reconcile_uploads as ru


def _v(vid: str, uploaded: str) -> dict:
    return {"id": vid, "uploaded_at": uploaded, "category_id": "24"}


class FindUntrackedTest(unittest.TestCase):
    def test_only_untracked_videos_since_the_pipeline_started(self):
        since = datetime(2026, 9, 5, tzinfo=timezone.utc)
        channel = [
            _v("tracked", "2026-09-10T00:00:00Z"),
            _v("lost", "2026-09-22T18:30:00Z"),
            _v("manual-before-pipeline", "2026-08-01T00:00:00Z"),
        ]
        found = ru.find_untracked(channel, {"tracked"}, since)
        self.assertEqual([v["id"] for v in found], ["lost"])


class HelpersTest(unittest.TestCase):
    def test_category_maps_back_to_template(self):
        self.assertEqual(ru.template_for_category("28"), "programming")
        self.assertEqual(ru.template_for_category("22"), "sauce_recipe")
        self.assertEqual(ru.template_for_category("26"), "food")
        self.assertEqual(ru.template_for_category("99"), "facts")

    def test_apply_arg_supports_template_overrides(self):
        self.assertEqual(ru.parse_apply_arg("a1, b2:weird,"), {"a1": None, "b2": "weird"})


if __name__ == "__main__":
    unittest.main()
