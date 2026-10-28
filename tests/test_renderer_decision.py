from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import renderer_decision, visuals_comic


class TestPick(unittest.TestCase):
    def test_too_little_data_keeps_original(self):
        self.assertEqual(renderer_decision.pick([500] * 3, [100] * 10)[0], "original")

    def test_clear_comic_win(self):
        self.assertEqual(renderer_decision.pick([300] * 6, [200] * 6)[0], "comic")

    def test_small_comic_edge_is_not_enough(self):
        self.assertEqual(renderer_decision.pick([205] * 6, [200] * 6)[0], "original")


class TestApplies(unittest.TestCase):
    ENV = {"VISUAL_STYLE": "comic"}

    def test_comic_verdict_covers_every_video_after_trial(self):
        with mock.patch.object(renderer_decision, "load", return_value="comic"):
            self.assertTrue(visuals_comic.applies("facts", "x", date(2027, 1, 1), self.ENV))
            self.assertFalse(visuals_comic.applies("facts", "x", date(2027, 1, 1), {}))
            self.assertFalse(visuals_comic.applies("programming", "x", date(2027, 1, 1), self.ENV))

    def test_original_verdict_ends_comic(self):
        with mock.patch.object(renderer_decision, "load", return_value="original"):
            self.assertFalse(visuals_comic.applies("facts", "x", date(2026, 11, 10), self.ENV))
