"""Winner analyzer (owner-shared creator-research ask, 2026-09-13):
classifies recently-uploaded videos' real performance and surfaces which
structural characteristics (template, approach, genome tags) show up
disproportionately among the winners -- not just "which video got the
most views," per the owner's own explicit ask.

Built entirely on data already collected: views/likes/comment_count via
pipeline/stats.py's Data-API sync, genome_item_count/genome_visual_density
via metadata.py's per-video "genome" tagging. Deliberately does NOT use
subscribers-gained or real RPM/revenue -- those need the YouTube
Analytics API's MONETARY scope (yt-analytics-monetary.readonly), which
stays unauthorized (see CLAUDE.md's OAuth-scope rule) since it's a much
bigger ask (real earnings data) than what real audience retention needed.

Real average-percentage-viewed / average-view-duration (2026-09-21 owner
ask) IS now collectable -- see pipeline/stats.py's fetch_retention() and
state.db's avg_view_percentage/avg_view_duration_seconds columns -- but
this module's classification below still doesn't read them: same
"collect first, before there's enough volume to score against"
posture already applied to views/likes/comment_count when they first
landed here (see ROADMAP.md). genome_hook_style/genome_concept_type are
read from state.db but not surfaced separately here -- they currently
just mirror approach/template (see metadata.py), so they'd add
duplicate columns, not new information.
"""

from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.state import get_video
from pipeline.stats import all_uploads

# YouTube's own algorithm-testing window is generally understood to take
# several days before it settles on a stable audience for a video -- the
# owner-shared research called this "3 to 5 days" and warned that judging
# (or worse, reacting to) a video before then just resets the testing
# cycle. Videos younger than this are excluded from classification
# entirely -- not scored as NORMAL, not folded into the baseline either
# -- rather than judged on a still-in-flux view count.
FRESH_WINDOW_HOURS = 120.0

# Multiplier bands against a per-template trailing baseline. Views-only
# (see module docstring) -- this is a relative "did more people watch
# this than usual" signal, not an absolute revenue judgment.
BREAKOUT_MULTIPLIER = 5.0
WINNER_MULTIPLIER = 2.0
PROMISING_MULTIPLIER = 1.3

# Below this many eligible same-template videos, a per-template baseline
# is too noisy to trust (one lucky/unlucky video could swing it wildly)
# -- fall back to the whole eligible pool's average instead. Same
# "fall back to the full pool when the narrow one is too small" idiom
# this project already uses elsewhere (e.g. spot_the_difference.py's
# avoid_topics fallback, who_what_am_i.py's ROUND_POOL fallback).
MIN_TEMPLATE_SAMPLE = 3

CLASSIFICATIONS = ("NORMAL", "PROMISING", "WINNER", "BREAKOUT")

# Approximate RPM ranges from the owner-shared creator research (stated
# INDUSTRY genre averages, not this channel's own measured earnings --
# real per-video revenue needs the YouTube Analytics API's monetary
# scope, which the owner explicitly chose not to authorize yet, see
# module docstring). Midpoints of the stated ranges: general/trivia/food
# content ~$1.50-$3.00 RPM, technical/developer content ~$15.00-$35.00+
# (advertisers buying enterprise SaaS/dev-tool/recruitment ads pay far
# more than general-interest ads do). quiz_longform is Python-focused,
# same tech audience as programming, so it gets the same high estimate;
# game_night (family entertainment) is general-interest like facts/
# sauce_recipe. Treat this as a relative comparison to weigh alongside
# real view data, never as an actual dollar figure for this channel.
TEMPLATE_RPM_ESTIMATE = {
    "programming": 22.0,
    "quiz_longform": 20.0,
    "facts": 2.25,
    "sauce_recipe": 2.25,
    "game_night": 2.25,
}


def avg_views_by_template(rows: list[dict]) -> dict[str, float]:
    by_template: dict[str, list[int]] = {}
    for r in rows:
        by_template.setdefault(r["template"], []).append(r["views"])
    return {t: sum(v) / len(v) for t, v in by_template.items() if v}


def estimated_value_per_video(rows: list[dict]) -> dict[str, float]:
    """avg views/1000 * RPM estimate, per template -- makes the owner-
    shared research's core point concrete on this channel's own real
    view data: two templates can be worth very different amounts per
    video, and the one with FEWER views can still be worth MORE. An
    estimate (see TEMPLATE_RPM_ESTIMATE), not a real earnings number --
    useful for weighing the rotation mix, not for reporting revenue."""
    avg_views = avg_views_by_template(rows)
    return {
        template: round(views / 1000 * TEMPLATE_RPM_ESTIMATE.get(template, 0.0), 2)
        for template, views in avg_views.items()
    }


def _is_fresh(uploaded_at: str, now: datetime) -> bool:
    uploaded = datetime.fromisoformat(uploaded_at)
    return (now - uploaded) < timedelta(hours=FRESH_WINDOW_HOURS)


def eligible_rows(now: datetime | None = None) -> list[dict]:
    """Every logged upload old enough to judge (past FRESH_WINDOW_HOURS)
    with real synced stats (views is not None) -- joins data/videos.json's
    upload log against state.db's per-video row for genome tags/stats.
    A video whose state.db row is missing or was never stats-synced is
    silently skipped, not counted as zero-performance."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for log_row in all_uploads():
        if _is_fresh(log_row["uploaded_at"], now):
            continue
        video = get_video(log_row["video_id"])
        if video is None or video.get("views") is None:
            continue
        rows.append({**log_row, **video})
    return rows


def _baseline_views(rows: list[dict], template: str) -> float:
    same_template = [r["views"] for r in rows if r["template"] == template]
    pool = same_template if len(same_template) >= MIN_TEMPLATE_SAMPLE else [r["views"] for r in rows]
    return sum(pool) / len(pool) if pool else 0.0


def classify(views: int, baseline: float) -> str:
    if baseline <= 0:
        return "NORMAL"
    multiplier = views / baseline
    if multiplier >= BREAKOUT_MULTIPLIER:
        return "BREAKOUT"
    if multiplier >= WINNER_MULTIPLIER:
        return "WINNER"
    if multiplier >= PROMISING_MULTIPLIER:
        return "PROMISING"
    return "NORMAL"


def engagement_rate(row: dict) -> float:
    """(likes + comments) / views -- the only engagement signal available
    without the Analytics API. Not blended into the view-based
    classification above (that would invent a weighting formula this
    project has no real basis for); reported alongside it instead, as a
    real second data point a reader can weigh for themselves."""
    views = row.get("views") or 0
    if views <= 0:
        return 0.0
    return ((row.get("likes") or 0) + (row.get("comment_count") or 0)) / views


def classified_rows(now: datetime | None = None) -> list[dict]:
    """Every eligible row plus its classification/baseline/engagement
    rate -- the report's real building block."""
    rows = eligible_rows(now)
    out = []
    for row in rows:
        baseline = _baseline_views(rows, row["template"])
        out.append({
            **row,
            "baseline_views": round(baseline, 1),
            "classification": classify(row["views"], baseline),
            "engagement_rate": round(engagement_rate(row), 4),
        })
    return out


def approach_performance(rows: list[dict]) -> dict[str, dict]:
    """{approach: {"count": n, "avg_ratio": x}} across every eligible row
    with a real approach set (facts/programming/sauce_recipe -- the only
    templates pipeline/approaches.py's rotation actually applies to;
    quiz_longform/game_night/family_game_night never set one). Each
    row's own views/baseline_views ratio (classify()'s own multiplier,
    already computed) is averaged per approach -- a real, comparable
    "did this approach outperform ITS OWN template's typical video"
    signal, not raw views (which would just measure template popularity,
    not the approach's own effect)."""
    ratios_by_approach: dict[str, list[float]] = {}
    for r in rows:
        approach = r.get("approach")
        baseline = r.get("baseline_views") or 0
        if not approach or baseline <= 0:
            continue
        ratios_by_approach.setdefault(approach, []).append(r["views"] / baseline)
    return {a: {"count": len(ratios), "avg_ratio": sum(ratios) / len(ratios)} for a, ratios in ratios_by_approach.items()}


def winner_characteristics(rows: list[dict]) -> list[dict]:
    """WINNER/BREAKOUT rows only, with the real structural fields the
    owner's research asked to see per winner -- template, approach, and
    the two genome fields that carry information beyond template/approach
    already (item_count, visual_density)."""
    winners = [r for r in rows if r["classification"] in ("WINNER", "BREAKOUT")]
    return [
        {
            "youtube_video_id": r["youtube_video_id"],
            "classification": r["classification"],
            "template": r["template"],
            "approach": r.get("approach"),
            "topic": r.get("topic"),
            "hook": r.get("hook"),
            "item_count": r.get("genome_item_count"),
            "visual_density": r.get("genome_visual_density"),
            "views": r["views"],
            "views_vs_baseline": round(r["views"] / r["baseline_views"], 1) if r["baseline_views"] else None,
            "engagement_rate": r["engagement_rate"],
        }
        for r in sorted(winners, key=lambda r: -r["views"])
    ]


def describe_common_pattern(winners: list[dict], rows: list[dict]) -> str:
    """A real, data-backed observation about what winners have in common
    -- qualified by real sample size, never phrased as confident
    causation. Small automated channels don't have the volume for a real
    statistical claim yet; this says so explicitly rather than manufacture
    false confidence from 2-3 data points."""
    if len(winners) < 2:
        return "Not enough winners yet to see a repeated pattern (need at least 2)."

    combo_counts = Counter((w["template"], w["approach"]) for w in winners)
    (top_template, top_approach), count = combo_counts.most_common(1)[0]
    if count < 2:
        return "Winners so far don't share a common template/approach combination yet."

    share_in_winners = count / len(winners)
    pool_with_combo = sum(1 for r in rows if r["template"] == top_template and r.get("approach") == top_approach)
    share_in_pool = pool_with_combo / len(rows) if rows else 0.0
    lean = (
        "more often than its overall share of uploads"
        if share_in_winners > share_in_pool
        else "roughly in line with how often it's uploaded overall (not a strong signal yet)"
    )
    return (
        f"{count}/{len(winners)} winners are template={top_template!r} approach={top_approach!r}, "
        f"{lean} ({share_in_pool:.0%} of {len(rows)} eligible uploads)."
    )


if __name__ == "__main__":
    all_rows = classified_rows()
    print(f"{len(all_rows)} eligible video(s) (past the {FRESH_WINDOW_HOURS:.0f}h freeze window, stats synced)")
    for classification in CLASSIFICATIONS:
        count = sum(1 for r in all_rows if r["classification"] == classification)
        print(f"  {classification}: {count}")
    winners = winner_characteristics(all_rows)
    print()
    print("Winners/breakouts:")
    for w in winners:
        print(f"  [{w['classification']}] {w['youtube_video_id']} template={w['template']} approach={w['approach']} "
              f"views={w['views']} ({w['views_vs_baseline']}x baseline) engagement={w['engagement_rate']:.1%} "
              f"item_count={w['item_count']} visual_density={w['visual_density']}")
    print()
    print(describe_common_pattern(winners, all_rows))
    print()
    print("Estimated value per video by template (RPM estimate, not measured earnings):")
    avg_views = avg_views_by_template(all_rows)
    for template, value in sorted(estimated_value_per_video(all_rows).items(), key=lambda kv: -kv[1]):
        print(f"  {template}: ${value:.2f}/video (avg {avg_views[template]:.0f} views x ${TEMPLATE_RPM_ESTIMATE.get(template, 0):.2f} RPM)")
