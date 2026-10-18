"""Generates the weekly approach-ranking report from real pulled stats.
See ROADMAP.md Phase 10 #4.

Usage:
    python scripts/weekly_report.py
"""

from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.stats import weekly_report_data
from pipeline.winner_analyzer import (
    CLASSIFICATIONS,
    TEMPLATE_RPM_ESTIMATE,
    avg_views_by_template,
    classified_rows,
    describe_common_pattern,
    estimated_value_per_video,
    winner_characteristics,
)

REPORTS_DIR = Path(__file__).resolve().parent.parent / "reports"


def _build_winner_section() -> list[str]:
    """Owner-shared creator-research ask (2026-09-13): don't just show
    which video got the most views this week -- classify performance
    against a rolling baseline and surface what winners have in common.
    Uses classified_rows()'s own eligibility window (skips anything
    inside the 5-day "algorithm freeze"), not the weekly `days` window
    above -- a winner needs enough real, settled data to judge, which
    can span more than 7 days on a low-frequency channel."""
    rows = classified_rows()
    lines = ["## Performance classification (all eligible uploads, not just this week)", ""]
    if not rows:
        lines.append("No videos are past the 5-day freeze window with synced stats yet.")
        lines.append("")
        return lines
    lines.append(f"{len(rows)} eligible video(s) (uploaded 5+ days ago, stats synced).")
    lines.append("")
    lines.append("| classification | count |")
    lines.append("|---|---|")
    for classification in CLASSIFICATIONS:
        count = sum(1 for r in rows if r["classification"] == classification)
        lines.append(f"| {classification} | {count} |")
    lines.append("")

    winners = winner_characteristics(rows)
    lines.append("### Winners / breakouts")
    lines.append("")
    if not winners:
        lines.append("None yet.")
    else:
        lines.append("| video | class | template | approach | views | vs baseline | engagement | beats | avg s/beat |")
        lines.append("|---|---|---|---|---|---|---|---|---|")
        for w in winners:
            lines.append(
                f"| {w['youtube_video_id']} | {w['classification']} | {w['template']} | {w['approach'] or '(none)'} | "
                f"{w['views']} | {w['views_vs_baseline']}x | {w['engagement_rate']:.1%} | "
                f"{w['item_count'] if w['item_count'] is not None else '-'} | "
                f"{w['visual_density'] if w['visual_density'] is not None else '-'} |"
            )
    lines.append("")
    lines.append(f"**Pattern:** {describe_common_pattern(winners, rows)}")
    lines.append("")

    lines.append("### Estimated value per template (RPM estimate, NOT measured earnings)")
    lines.append("")
    lines.append(
        "Real per-video revenue needs the YouTube Analytics API's monetary "
        "scope (not authorized -- see pipeline/winner_analyzer.py). Below "
        "uses industry-genre RPM estimates against this channel's own real "
        "average views, to weigh alongside raw view counts -- not a real "
        "earnings figure."
    )
    lines.append("")
    avg_views = avg_views_by_template(rows)
    value_by_template = estimated_value_per_video(rows)
    lines.append("| template | avg views | RPM estimate | estimated value/video |")
    lines.append("|---|---|---|---|")
    for template, value in sorted(value_by_template.items(), key=lambda kv: -kv[1]):
        lines.append(
            f"| {template} | {avg_views[template]:.0f} | ${TEMPLATE_RPM_ESTIMATE.get(template, 0):.2f} | ${value:.2f} |"
        )
    lines.append("")
    return lines


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def renderer_comparison(rows: list[dict], now: datetime | None = None) -> list[str]:
    """Per-renderer averages (views, avg view duration, % viewed, likes) for
    the last 7 days vs the 7 days before that. `rows` must span 14 days."""
    now = now or datetime.now(timezone.utc)
    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        age = (now - datetime.fromisoformat(r["uploaded_at"])).total_seconds() / 86400
        if age > 14:
            continue
        buckets[(r.get("renderer") or "original", "this week" if age <= 7 else "previous week")].append(r)

    def fmt(v: float | None, spec: str) -> str:
        return "-" if v is None else format(v, spec)

    lines = ["## Renderer comparison (motionmaxxing trial)", "",
             "| renderer | week | videos | avg views | avg view duration | % viewed | avg likes |",
             "|---|---|---|---|---|---|---|"]
    for renderer in sorted({k[0] for k in buckets}):
        for week in ("this week", "previous week"):
            rs = buckets.get((renderer, week), [])
            lines.append(
                f"| {renderer} | {week} | {len(rs)} | {fmt(_mean([r['views'] for r in rs]), '.0f')} | "
                f"{fmt(_mean([r.get('avg_view_duration_seconds') for r in rs]), '.0f')}s | "
                f"{fmt(_mean([r.get('avg_view_percentage') for r in rs]), '.0f')}% | "
                f"{fmt(_mean([r['likes'] for r in rs]), '.1f')} |"
            )
    lines.append("")
    return lines


def build_report(days: int = 7) -> str:
    # This report is specifically the Shorts approach A/B comparison —
    # the quiz longform track is a separate, lower-frequency content
    # track that never gets an approach tag and shouldn't be mixed in.
    # Same for hand-made promo uploads (scripts/upload_promo.py).
    all_rows = [r for r in weekly_report_data(max(days, 14)) if r["template"] not in ("quiz_longform", "promo")]
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rows = [r for r in all_rows if datetime.fromisoformat(r["uploaded_at"]) >= cutoff]

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
    lines.extend(renderer_comparison(all_rows))
    lines.append("## Per-video detail")
    lines.append("")
    # avg_view_percentage/avg_view_duration_seconds are None until the
    # YouTube token has been re-authorized with yt-analytics.readonly
    # (see pipeline/stats.py's fetch_retention()) -- shown as "-" until
    # then rather than a misleading 0%.
    lines.append("| youtube_video_id | template | approach | views | likes | comments | watched % | avg watch | uploaded_at |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in sorted(rows, key=lambda r: -r["views"]):
        watched_pct = f"{r['avg_view_percentage']:.0f}%" if r.get("avg_view_percentage") is not None else "-"
        avg_watch = f"{r['avg_view_duration_seconds']:.0f}s" if r.get("avg_view_duration_seconds") is not None else "-"
        lines.append(
            f"| {r['youtube_video_id']} | {r['template']} | {r['approach'] or '(none)'} | "
            f"{r['views']} | {r['likes']} | {r['comments']} | {watched_pct} | {avg_watch} | {r['uploaded_at']} |"
        )
    lines.append("")
    lines.extend(_build_winner_section())
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
