"""Cron entrypoint for the daily pipeline run. See SPEC.md / ROADMAP.md
Phase 9. The actual orchestration logic lives in pipeline/orchestrator.py
— this is just the thin CLI wrapper GitHub Actions (or a local cron) calls.

Usage:
    python scripts/run_daily.py --count 5
    python scripts/run_daily.py --templates sauce_recipe,sauce_recipe
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.orchestrator import run_daily


def main() -> None:
    args = sys.argv[1:]
    count = 1
    if "--count" in args:
        count = int(args[args.index("--count") + 1])

    templates = None
    if "--templates" in args:
        raw = args[args.index("--templates") + 1]
        parsed = [t.strip() for t in raw.split(",") if t.strip()]
        templates = parsed or None  # an empty/blank value falls back to --count

    results = run_daily(count, templates=templates)
    print()
    print("=== run_daily summary ===")
    for r in results:
        suffix = f"  ({r['error']})" if r["error"] else ""
        print(f"{r['video_id']}  [{r['template']}]  {r['status']}{suffix}")


if __name__ == "__main__":
    main()
