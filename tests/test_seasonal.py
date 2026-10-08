"""Pure date/prompt logic for pipeline/seasonal.py -- no network or LLM."""

from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import seasonal  # noqa: E402


def _key(day: date) -> str | None:
    event = seasonal.active_event(day)
    return event.key if event else None


class ActiveEventTest(unittest.TestCase):
    def test_halloween_starts_a_month_out_and_ends_the_day_before(self):
        self.assertIsNone(_key(date(2026, 9, 29)))
        self.assertEqual(_key(date(2026, 9, 30)), "halloween")
        self.assertEqual(_key(date(2026, 10, 30)), "halloween")
        # Halloween day itself: Thanksgiving's window is open, nearest wins.
        self.assertEqual(_key(date(2026, 10, 31)), "thanksgiving")

    def test_overlapping_windows_pick_the_nearest_holiday(self):
        self.assertEqual(_key(date(2026, 10, 28)), "halloween")
        self.assertEqual(_key(date(2026, 11, 25)), "thanksgiving")
        self.assertEqual(_key(date(2026, 11, 26)), "christmas")
        self.assertEqual(_key(date(2026, 12, 24)), "christmas")
        self.assertEqual(_key(date(2026, 12, 25)), "new_year")
        self.assertEqual(_key(date(2026, 12, 31)), "new_year")
        self.assertIsNone(_key(date(2027, 1, 1)))
        self.assertEqual(_key(date(2027, 1, 14)), "valentines")
        self.assertIsNone(_key(date(2027, 2, 14)))

    def test_thanksgiving_is_fourth_thursday(self):
        self.assertEqual(seasonal._us_thanksgiving(2026), date(2026, 11, 26))
        self.assertEqual(seasonal._us_thanksgiving(2027), date(2027, 11, 25))
        self.assertEqual(seasonal._us_thanksgiving(2024), date(2024, 11, 28))

    def test_peak_is_the_final_ten_days(self):
        halloween = seasonal.get_event("halloween")
        self.assertFalse(seasonal.in_peak(halloween, date(2026, 10, 20)))
        self.assertTrue(seasonal.in_peak(halloween, date(2026, 10, 21)))
        self.assertTrue(seasonal.in_peak(halloween, date(2026, 10, 30)))

    @mock.patch.dict("os.environ", {"ENABLE_SEASONAL_TOPICS": "0"})
    def test_kill_switch(self):
        self.assertIsNone(seasonal.active_event(date(2026, 10, 20)))


class BlocksTest(unittest.TestCase):
    def test_every_event_has_an_angle_for_each_of_its_templates(self):
        for event in seasonal.EVENTS:
            self.assertTrue(event.templates)
            self.assertEqual(set(event.angles), set(event.templates), event.key)
            for template in event.templates:
                self.assertIn(event.name, seasonal.seasonal_block(event, template))

    def test_metadata_block_names_the_hashtags(self):
        block = seasonal.metadata_block(seasonal.get_event("halloween"))
        self.assertIn("#Halloween", block)


if __name__ == "__main__":
    unittest.main()
