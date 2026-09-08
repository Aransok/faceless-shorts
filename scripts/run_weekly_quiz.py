"""Cron entrypoint for the weekly quiz longform video. Separate track
from the daily Shorts pipeline (scripts/run_daily.py) — see ROADMAP.md's
quiz track section.

Usage:
    python scripts/run_weekly_quiz.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import run_weekly_quiz


def main() -> None:
    result = run_weekly_quiz()
    print()
    print("=== run_weekly_quiz summary ===")
    suffix = f"  ({result['error']})" if result["error"] else ""
    print(f"{result['video_id']}  [{result['template']}]  {result['status']}{suffix}")


if __name__ == "__main__":
    main()
