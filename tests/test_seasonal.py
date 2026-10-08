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
    def test_halloween_window_ends_the_day_before(self):
        self.assertIsNone(_key(date(2026, 10, 6)))
        self.assertEqual(_key(date(2026, 10, 7)), "halloween")
        self.assertEqual(_key(date(2026, 10, 30)), "halloween")
        self.assertIsNone(_key(date(2026, 10, 31)))

    def test_thanksgiving_is_fourth_thursday(self):
        self.assertEqual(seasonal._us_thanksgiving(2026), date(2026, 11, 26))
        self.assertEqual(seasonal._us_thanksgiving(2027), date(2027, 11, 25))
        self.assertEqual(seasonal._us_thanksgiving(2024), date(2024, 11, 28))
        self.assertEqual(_key(date(2026, 11, 25)), "thanksgiving")
        self.assertIsNone(_key(date(2026, 11, 26)))

    def test_late_december_finds_next_years_new_year(self):
        self.assertEqual(_key(date(2026, 12, 24)), "christmas")
        self.assertIsNone(_key(date(2026, 12, 25)))
        self.assertEqual(_key(date(2026, 12, 30)), "new_year")

    def test_windows_never_overlap(self):
        day = date(2026, 1, 1)
        while day < date(2028, 1, 1):
            active = [
                e.key for e in seasonal.EVENTS
                for y in (day.year, day.year + 1)
                if e.window(y)[0] <= day <= e.window(y)[1]
            ]
            self.assertLessEqual(len(active), 1, f"{day}: {active}")
            day = date.fromordinal(day.toordinal() + 1)

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
