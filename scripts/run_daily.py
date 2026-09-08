"""Cron entrypoint for the daily pipeline run. See SPEC.md / ROADMAP.md
Phase 9. The actual orchestration logic lives in pipeline/orchestrator.py
— this is just the thin CLI wrapper GitHub Actions (or a local cron) calls.

Usage:
    python scripts/run_daily.py --count 5
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

    results = run_daily(count)
    print()
    print("=== run_daily summary ===")
    for r in results:
        suffix = f"  ({r['error']})" if r["error"] else ""
        print(f"{r['video_id']}  [{r['template']}]  {r['status']}{suffix}")


if __name__ == "__main__":
    main()
