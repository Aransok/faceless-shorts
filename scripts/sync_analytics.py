"""Cron entrypoint for pulling real view/like/comment counts into
state.db for videos in a 48h-14d age window. Data collection only --
see pipeline/stats.py's sync_analytics() and ROADMAP.md.

Usage:
    python scripts/sync_analytics.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.stats import sync_analytics


def main() -> None:
    updated = sync_analytics()
    print(f"synced real stats for {updated} video(s)")


if __name__ == "__main__":
    main()
