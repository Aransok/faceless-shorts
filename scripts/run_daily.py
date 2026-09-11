"""Cron entrypoint for the daily pipeline run. See SPEC.md / ROADMAP.md
Phase 9. The actual orchestration logic lives in pipeline/orchestrator.py
— this is just the thin CLI wrapper GitHub Actions (or a local cron) calls.

Usage:
    python scripts/run_daily.py --count 5
    python scripts/run_daily.py --templates sauce_recipe,sauce_recipe

Per-template topic hints (see plan.py's _topic_hint_block()) come from
the TOPIC_HINTS_JSON env var, not a CLI flag — a JSON object can contain
characters (quotes, newlines) that don't round-trip safely through a
shell-quoted CLI arg the way the workflow's other inputs do, and this
project already reads config through env vars for exactly that reason
(LLM_BACKEND, TTS_BACKEND, etc.).
"""

from __future__ import annotations

import json
import os
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

    topic_hints = None
    raw_hints = os.environ.get("TOPIC_HINTS_JSON", "").strip()
    if raw_hints:
        topic_hints = json.loads(raw_hints)

    results = run_daily(count, templates=templates, topic_hints=topic_hints)
    print()
    print("=== run_daily summary ===")
    for r in results:
        suffix = f"  ({r['error']})" if r["error"] else ""
        print(f"{r['video_id']}  [{r['template']}]  {r['status']}{suffix}")


if __name__ == "__main__":
    main()
