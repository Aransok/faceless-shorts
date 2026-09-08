"""Milestone stat mentions (Phase 6 extension). Checks real, pulled
subscriber/view counts against a fixed list of meaningful milestones and
returns a pending announcement for plan.py to fold into a script — never
invents or rounds a number; if no real stat has been recorded yet, there
is nothing to announce. See SPEC.md/ROADMAP.md: the weekly stats job that
actually writes real numbers via set_channel_stat() only exists once
Phase 8 is live and real videos/subscribers exist — this module is the
data model and injection logic, ready for that job to feed.

Milestones are explicit, meaningful numbers (50 subs, 100 subs, 100k
views, ...), not a mechanical every-N step — these should be rare events
worth a mention, not something that fires on a large fraction of videos.
get_pending_announcement() also only ever returns ONE metric's milestone
per call, so a single video never stacks more than one milestone mention.
"""

from __future__ import annotations

from pipeline.state import (
    get_channel_stat,
    get_last_announced_milestone,
    set_last_announced_milestone,
)

# Explicit, meaningful milestones per metric, ascending. Once the channel
# outgrows the largest listed value, milestones continue at the same
# spacing as the last two entries (e.g. every 100k after 500k subs).
_MILESTONES = {
    "subscribers": [50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000],
    "views": [1000, 10000, 50000, 100000, 250000, 500000, 1000000],
}

_METRIC_LABELS = {
    "subscribers": "subscribers",
    "views": "total views",
}


def _highest_threshold(metric: str, value: int) -> int:
    milestones = _MILESTONES[metric]
    reached = [m for m in milestones if m <= value]
    if not reached:
        return 0
    highest = reached[-1]
    if highest < milestones[-1]:
        return highest
    # Past the largest explicit milestone: keep going at the same spacing
    # as the last step in the list.
    step = milestones[-1] - milestones[-2]
    return (value // step) * step


def check_for_new_milestone(metric: str) -> int | None:
    """Highest threshold crossed since the last announcement, or None if
    there's no real stat recorded yet or nothing new to announce."""
    if metric not in _MILESTONES:
        raise ValueError(f"unknown metric {metric!r}, expected one of {sorted(_MILESTONES)}")

    current = get_channel_stat(metric)
    if current is None:
        return None

    threshold = _highest_threshold(metric, current)
    if threshold == 0:
        return None

    last_announced = get_last_announced_milestone(metric) or 0
    return threshold if threshold > last_announced else None


def mark_milestone_announced(metric: str, value: int) -> None:
    set_last_announced_milestone(metric, value)


def format_milestone_line(metric: str, value: int) -> str:
    return f"just crossed {value:,} {_METRIC_LABELS[metric]}"


def get_pending_announcement() -> tuple[str, int] | None:
    """(metric, threshold) for the first metric with a real pending
    milestone, checked in a fixed order, or None if nothing is pending.
    Only ever one metric per call — a video never stacks two milestone
    mentions."""
    for metric in ("subscribers", "views"):
        threshold = check_for_new_milestone(metric)
        if threshold is not None:
            return metric, threshold
    return None
