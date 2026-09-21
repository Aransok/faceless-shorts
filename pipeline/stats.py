"""Phase 10 #4: pulls real view/like/comment stats for recently-uploaded
videos, joined against data/videos.json's approach/template log — the
payoff of the approach-rotation A/B testing system built in Phase 6.
Stays on the free Data API quota (videos.list with part=statistics) for
view/like/comment counts.

Real audience retention (2026-09-21 owner ask: "how much of the clip is
watched, how many swipe away") is a SEPARATE API -- YouTube Analytics,
not the Data API above -- see fetch_retention(). Needs the
yt-analytics.readonly scope (scripts/get_youtube_token.py), granted only
once the token has been regenerated with it; every caller here treats a
missing-scope failure as "no retention data yet," not a hard error, so
existing view/like/comment collection keeps working for anyone who
hasn't re-authorized yet. See ROADMAP.md Phase 10.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build

from pipeline.state import update_video
from pipeline.upload import _load_credentials

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VIDEOS_LOG_PATH = PROJECT_ROOT / "data" / "videos.json"


def _load_video_log() -> list[dict]:
    if not VIDEOS_LOG_PATH.exists():
        return []
    return json.loads(VIDEOS_LOG_PATH.read_text(encoding="utf-8"))


def recent_uploads(days: int = 7) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [r for r in _load_video_log() if datetime.fromisoformat(r["uploaded_at"]) >= cutoff]


def all_uploads() -> list[dict]:
    """Every logged upload, no day-window filter -- pipeline/winner_analyzer.py
    needs the full history (its own freshness/baseline logic decides what's
    eligible), not just a fixed recent window the way the weekly report does."""
    return _load_video_log()


def fetch_statistics(youtube_video_ids: list[str]) -> dict[str, dict]:
    """{youtube_video_id: {"views", "likes", "comments"}} — batches up to
    50 IDs per call, YouTube's real limit for videos.list."""
    if not youtube_video_ids:
        return {}
    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    stats: dict[str, dict] = {}
    for i in range(0, len(youtube_video_ids), 50):
        batch = youtube_video_ids[i : i + 50]
        resp = youtube.videos().list(part="statistics", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            s = item["statistics"]
            stats[item["id"]] = {
                "views": int(s.get("viewCount", 0)),
                "likes": int(s.get("likeCount", 0)),
                "comments": int(s.get("commentCount", 0)),
            }
    return stats


# YouTube Analytics' `filters=video==id1,id2,...` accepts multiple video
# IDs in one call, but the real cap isn't documented anywhere trustworthy
# -- reuses the Data API's own confirmed 50-per-call limit
# (fetch_statistics above) as a conservative batch size rather than
# guessing a larger one.
_RETENTION_BATCH_SIZE = 50

# A fixed, deliberately early date rather than each video's own upload
# date -- dimensions=video means only videos that actually have data in
# this window show up in the response at all, so one shared start date
# far before this channel's first upload is simpler and just as correct
# as tracking a real per-video start date would be.
_RETENTION_START_DATE = "2020-01-01"


def fetch_retention(youtube_video_ids: list[str]) -> dict[str, dict]:
    """{youtube_video_id: {"avg_view_percentage", "avg_view_duration_seconds"}}
    for however many of the given IDs the YouTube Analytics API actually
    has data for (a brand-new video with no views yet just won't appear
    in the response rows). Raises whatever the API raises -- notably a
    403 if the current token doesn't have yt-analytics.readonly yet (see
    scripts/get_youtube_token.py). Callers that want that to degrade
    gracefully instead of failing outright (sync_analytics(),
    weekly_report_data()) catch it themselves, same as fetch_statistics()
    staying a thin, un-defensive wrapper.
    """
    if not youtube_video_ids:
        return {}
    creds = _load_credentials()
    analytics = build("youtubeAnalytics", "v2", credentials=creds)
    today = datetime.now(timezone.utc).date().isoformat()
    retention: dict[str, dict] = {}
    for i in range(0, len(youtube_video_ids), _RETENTION_BATCH_SIZE):
        batch = youtube_video_ids[i : i + _RETENTION_BATCH_SIZE]
        resp = (
            analytics.reports()
            .query(
                ids="channel==MINE",
                startDate=_RETENTION_START_DATE,
                endDate=today,
                metrics="averageViewPercentage,averageViewDuration",
                dimensions="video",
                filters="video==" + ",".join(batch),
            )
            .execute()
        )
        for video_id, avg_percentage, avg_duration in resp.get("rows", []):
            retention[video_id] = {
                "avg_view_percentage": float(avg_percentage),
                "avg_view_duration_seconds": float(avg_duration),
            }
    return retention


def _fetch_retention_or_empty(youtube_video_ids: list[str]) -> dict[str, dict]:
    """Shared fail-soft wrapper (CLAUDE.md's "fail soft, not hard" rule):
    a token that hasn't been re-authorized with yt-analytics.readonly yet
    must not break the view/like/comment collection that already works
    without it."""
    try:
        return fetch_retention(youtube_video_ids)
    except Exception as exc:
        print(
            f"warning: retention fetch failed ({exc}) -- yt-analytics.readonly "
            "scope may not be authorized yet (see scripts/get_youtube_token.py); "
            "continuing with view/like/comment counts only"
        )
        return {}


def weekly_report_data(days: int = 7) -> list[dict]:
    """One row per recently-uploaded video with real stats (and, once the
    token is re-authorized for it, retention) joined in."""
    records = recent_uploads(days)
    video_ids = [r["youtube_video_id"] for r in records]
    stats = fetch_statistics(video_ids)
    retention = _fetch_retention_or_empty(video_ids)
    rows = []
    for r in records:
        s = stats.get(r["youtube_video_id"], {"views": 0, "likes": 0, "comments": 0})
        ret = retention.get(
            r["youtube_video_id"], {"avg_view_percentage": None, "avg_view_duration_seconds": None}
        )
        rows.append({**r, **s, **ret})
    return rows


def sync_analytics(min_age_hours: float = 48, max_age_days: float = 14) -> int:
    """Persists real view/like/comment counts (and, once the token is
    re-authorized with yt-analytics.readonly, real audience-retention
    numbers -- see fetch_retention()) into state.db for uploaded videos
    in a min_age_hours-max_age_days window -- old enough that initial-
    hour view counts have stabilized a bit, not so old the numbers are
    ancient by the time anything eventually reads them. Collection only:
    nothing scores, weights, or feeds these back into generation yet
    (out of scope until there's real volume -- see ROADMAP.md). Returns
    how many rows were actually updated.
    """
    now = datetime.now(timezone.utc)
    newest_eligible = now - timedelta(hours=min_age_hours)
    oldest_eligible = now - timedelta(days=max_age_days)
    candidates = [
        r
        for r in _load_video_log()
        if oldest_eligible <= datetime.fromisoformat(r["uploaded_at"]) <= newest_eligible
    ]
    if not candidates:
        return 0

    video_ids = [r["youtube_video_id"] for r in candidates]
    stats = fetch_statistics(video_ids)
    retention = _fetch_retention_or_empty(video_ids)
    synced_at = now.isoformat()
    updated = 0
    for r in candidates:
        s = stats.get(r["youtube_video_id"])
        if s is None:
            continue
        ret = retention.get(r["youtube_video_id"], {})
        update_video(
            r["video_id"],
            views=s["views"],
            likes=s["likes"],
            comment_count=s["comments"],
            avg_view_percentage=ret.get("avg_view_percentage"),
            avg_view_duration_seconds=ret.get("avg_view_duration_seconds"),
            stats_synced_at=synced_at,
        )
        updated += 1
    return updated
