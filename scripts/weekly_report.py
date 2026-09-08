"""Generates the weekly approach-ranking report from real pulled stats.
See ROADMAP.md Phase 10 #4.

Usage:
    python scripts/weekly_report.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.stats import weekly_report_data

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def build_report(days: int = 7) -> str:
    # This report is specifically the Shorts approach A/B comparison —
    # the quiz longform track is a separate, lower-frequency content
    # track that never gets an approach tag and shouldn't be mixed in.
    rows = [r for r in weekly_report_data(days) if r["template"] != "quiz_longform"]

    by_approach: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        by_approach[r["approach"] or "(none)"].append(r["views"])

    lines = [f"# Weekly report — {date.today().isoformat()}", ""]
    lines.append(f"{len(rows)} video(s) uploaded in the last {days} days.")
    lines.append("")
    lines.append("## Approach ranking (by average views)")
    lines.append("")
    lines.append("| approach | videos | avg views | total views |")
    lines.append("|---|---|---|---|")
    ranked = sorted(by_approach.items(), key=lambda kv: -(sum(kv[1]) / len(kv[1])) if kv[1] else 0)
    for approach, views in ranked:
        avg = sum(views) / len(views) if views else 0
        lines.append(f"| {approach} | {len(views)} | {avg:.0f} | {sum(views)} |")
    lines.append("")
    lines.append("## Per-video detail")
    lines.append("")
    lines.append("| youtube_video_id | template | approach | views | likes | comments | uploaded_at |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: -r["views"]):
        lines.append(
            f"| {r['youtube_video_id']} | {r['template']} | {r['approach'] or '(none)'} | "
            f"{r['views']} | {r['likes']} | {r['comments']} | {r['uploaded_at']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    report = build_report()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    year, week, _ = date.today().isocalendar()
    out_path = REPORTS_DIR / f"week-{year}-{week:02d}.md"
    out_path.write_text(report, encoding="utf-8")
    print(f"wrote {out_path}")
    print()
    print(report)


if __name__ == "__main__":
    main()
