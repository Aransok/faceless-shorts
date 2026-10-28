"""Automatic end of the comic trial (2026-10-28, owner: "whatever you
decide", he does not want to make the call himself).

After the comic trial (2026-10-28 .. 2026-11-03) has had time to collect
views, decide() compares the two halves of the alternation on the same
templates and the same dates, and writes the verdict to
data/renderer_decision.json. visuals_comic.applies() reads it:
  - "comic": every eligible video goes comic, no end date.
  - "original": comic stays off after TRIAL_END (stock footage look).
No owner input, no paid service. Hyperframes is not part of this: its
trial stays paused for good (owner liked the UI but said it lacked
visuals, and the doodle renderer already lost on the same kind of test).
"""
from __future__ import annotations

import json
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

from pipeline.state import DB_PATH

DECISION_PATH = Path(__file__).resolve().parent.parent / "data" / "renderer_decision.json"
TEMPLATES = ("facts", "sauce_recipe", "weird", "food")
WINDOW_START = "2026-10-28"
WINDOW_END = "2026-11-04"  # exclusive
MIN_PER_SIDE = 5
# Comic costs extra render time and depends on a free image API, so it has
# to win clearly, not by noise: at least 10 percent higher median views.
COMIC_MARGIN = 1.10


def load() -> str | None:
    """'comic', 'original', or None if no decision has been made yet."""
    try:
        return json.loads(DECISION_PATH.read_text(encoding="utf-8")).get("winner")
    except (OSError, ValueError, AttributeError):
        return None


def pick(comic_views: list[int], original_views: list[int]) -> tuple[str, str]:
    """(winner, reason). Pure, so it is easy to test."""
    if len(comic_views) < MIN_PER_SIDE or len(original_views) < MIN_PER_SIDE:
        return "original", (
            f"not enough data (comic {len(comic_views)}, original {len(original_views)}, "
            f"need {MIN_PER_SIDE} each); keeping the cheaper, proven look"
        )
    c, o = statistics.median(comic_views), statistics.median(original_views)
    if c >= o * COMIC_MARGIN:
        return "comic", f"comic median {c:.0f} views vs original {o:.0f}"
    return "original", f"comic median {c:.0f} views vs original {o:.0f} (needed +10%)"


def _views(db_path: Path) -> tuple[list[int], list[int]]:
    marks = ",".join("?" * len(TEMPLATES))
    q = (
        f"SELECT renderer, views FROM videos WHERE template IN ({marks}) "
        "AND youtube_video_id IS NOT NULL AND views IS NOT NULL "
        "AND created_at >= ? AND created_at < ?"
    )
    comic, original = [], []
    with sqlite3.connect(db_path) as conn:
        for renderer, views in conn.execute(q, (*TEMPLATES, WINDOW_START, WINDOW_END)):
            (comic if renderer == "comic" else original).append(int(views))
    return comic, original


def decide(db_path: Path = DB_PATH, force: bool = False) -> str:
    existing = load()
    if existing and not force:
        print(f"already decided: {existing}")
        return existing
    comic, original = _views(db_path)
    winner, reason = pick(comic, original)
    DECISION_PATH.parent.mkdir(parents=True, exist_ok=True)
    DECISION_PATH.write_text(
        json.dumps(
            {
                "winner": winner,
                "reason": reason,
                "comic_videos": len(comic),
                "original_videos": len(original),
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"renderer decision: {winner} ({reason})")
    return winner


if __name__ == "__main__":
    decide()
