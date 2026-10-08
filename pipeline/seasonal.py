"""Seasonal topic steering (2026-10-08, owner: "Halloween is on its way ...
make the facts around it ... after that comes Christmas etc").

A fixed calendar of holidays, each with a lead-in window. While one is
active, run_daily() plans a subset of the day's videos around it (see
SeasonalEvent.templates) -- the rest of the day stays on normal topics so
the channel doesn't turn into a single-theme feed for three weeks.

Calendar-based on purpose rather than scraping live "trending" data:
every free trends source is unofficial/unstable, and the big seasonal
search spikes are predictable years ahead anyway.

The last seasonal batch is the day BEFORE the holiday: uploads publish
in a 20:00-04:00 UTC window after each daily run (pipeline/upload.py),
so that batch is live through the holiday itself, while a batch made on
the day would mostly publish after the interest has already dropped.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable


def _fixed(month: int, day: int) -> Callable[[int], date]:
    return lambda year: date(year, month, day)


def _us_thanksgiving(year: int) -> date:
    first = date(year, 11, 1)
    first_thursday = first + timedelta(days=(3 - first.weekday()) % 7)
    return first_thursday + timedelta(weeks=3)


@dataclass(frozen=True)
class SeasonalEvent:
    key: str
    name: str
    date_for_year: Callable[[int], date]
    lead_days: int
    templates: frozenset[str]
    angles: dict[str, str]
    hashtags: tuple[str, ...]

    def window(self, year: int) -> tuple[date, date]:
        day = self.date_for_year(year)
        return day - timedelta(days=self.lead_days), day - timedelta(days=1)


EVENTS: tuple[SeasonalEvent, ...] = (
    SeasonalEvent(
        key="halloween",
        name="Halloween",
        date_for_year=_fixed(10, 31),
        lead_days=24,
        # No sauce_recipe: there's no honest Halloween angle on sauces
        # that isn't a costume on an ordinary recipe.
        templates=frozenset({"facts", "food"}),
        angles={
            "facts": (
                "real history, science, or folklore behind Halloween things "
                "people take for granted -- where a tradition actually came "
                "from, the real animal/plant/chemistry behind a 'spooky' "
                "symbol, real events or places tied to the season"
            ),
            "food": (
                "the real cooking science behind Halloween-season food -- "
                "pumpkins and squash, candy and caramel, apples, roasted "
                "seeds -- explained so a viewer can actually use it"
            ),
        },
        hashtags=("#Halloween",),
    ),
    SeasonalEvent(
        key="thanksgiving",
        name="Thanksgiving",
        date_for_year=_us_thanksgiving,
        lead_days=14,
        templates=frozenset({"food", "sauce_recipe"}),
        angles={
            "food": (
                "real techniques for the Thanksgiving table -- turkey, "
                "stuffing, potatoes, pies -- and the real reason each one "
                "works or goes wrong"
            ),
            "sauce_recipe": (
                "gravies, cranberry sauces, and other real sauces that "
                "belong on a Thanksgiving table"
            ),
        },
        hashtags=("#Thanksgiving",),
    ),
    SeasonalEvent(
        key="christmas",
        name="Christmas",
        date_for_year=_fixed(12, 25),
        lead_days=24,
        templates=frozenset({"facts", "food", "sauce_recipe"}),
        angles={
            "facts": (
                "the real history, science, or regional traditions behind "
                "Christmas things people take for granted"
            ),
            "food": (
                "the real cooking science behind Christmas-season food -- "
                "roasts, cookies, spices, holiday baking"
            ),
            "sauce_recipe": (
                "real sauces from Christmas tables around the world"
            ),
        },
        hashtags=("#Christmas",),
    ),
    SeasonalEvent(
        key="new_year",
        name="New Year's",
        date_for_year=_fixed(1, 1),
        lead_days=5,
        templates=frozenset({"facts"}),
        angles={
            "facts": (
                "the real history and science behind New Year's traditions "
                "and the calendar itself"
            ),
        },
        hashtags=("#NewYear",),
    ),
    SeasonalEvent(
        key="valentines",
        name="Valentine's Day",
        date_for_year=_fixed(2, 14),
        lead_days=10,
        templates=frozenset({"facts", "food"}),
        angles={
            "facts": (
                "the real history and science behind Valentine's Day "
                "traditions -- not relationship advice"
            ),
            "food": (
                "the real science behind chocolate and other Valentine's "
                "food, explained so a viewer can actually use it"
            ),
        },
        hashtags=("#ValentinesDay",),
    ),
)

_BY_KEY = {e.key: e for e in EVENTS}


def get_event(key: str) -> SeasonalEvent:
    return _BY_KEY[key]


def active_event(today: date | None = None) -> SeasonalEvent | None:
    """The event whose window contains `today` (UTC), or None. If windows
    ever overlap, the nearest holiday wins."""
    if os.environ.get("ENABLE_SEASONAL_TOPICS", "1") == "0":
        return None
    today = today or datetime.now(timezone.utc).date()
    candidates = []
    # Next year too, so late-December dates find January holidays.
    for event in EVENTS:
        for year in (today.year, today.year + 1):
            start, end = event.window(year)
            if start <= today <= end:
                candidates.append((event.date_for_year(year), event))
    if not candidates:
        return None
    return min(candidates, key=lambda c: c[0])[1]


def seasonal_block(event: SeasonalEvent, template: str) -> str:
    """Appended to plan()'s prompt. A theme and direction, never a
    required subject or text to copy -- the same lesson as plan.py's
    topic-hint/research blocks."""
    return (
        f"\n\nSEASONAL THEME FOR THIS VIDEO: {event.name}. Build this video "
        f"around {event.name}: {event.angles[template]}.\n"
        "Pick the angle most seasonal content DOESN'T already cover -- skip "
        "the handful of facts every list repeats. Every claim must be real "
        "and something you can stand behind; the season is the theme, not "
        "an excuse for made-up or exaggerated claims. Don't say 'tonight', "
        "'tomorrow', or 'this week' -- the video stays up through and after "
        "the holiday.\n"
    )


def metadata_block(event: SeasonalEvent) -> str:
    """Appended to the metadata prompt so the title/tags actually signal
    the season to search and the Shorts feed."""
    tags = ", ".join(event.hashtags)
    return (
        f"\n\nThis video is part of the channel's {event.name} content. Make "
        f"the title clearly read as {event.name}-related, put {tags} among "
        f"the description hashtags, and include '{event.name.lower()}' in "
        "the tags.\n"
    )


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    event = active_event(day)
    print(f"active event for {day or 'today (UTC)'}: {event.name if event else None}")
    if event:
        for template in sorted(event.templates):
            print(f"--- {template} ---{seasonal_block(event, template)}")
        print(f"--- metadata ---{metadata_block(event)}")
