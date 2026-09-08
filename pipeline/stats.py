"""Phase 10 #4: pulls real view/like/comment stats for recently-uploaded
videos, joined against data/videos.json's approach/template log — the
payoff of the approach-rotation A/B testing system built in Phase 6.
Stays on the free Data API quota (videos.list with part=statistics), no
YouTube Analytics OAuth scope. See ROADMAP.md Phase 10.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build

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


def weekly_report_data(days: int = 7) -> list[dict]:
    """One row per recently-uploaded video with real stats joined in."""
    records = recent_uploads(days)
    stats = fetch_statistics([r["youtube_video_id"] for r in records])
    rows = []
    for r in records:
        s = stats.get(r["youtube_video_id"], {"views": 0, "likes": 0, "comments": 0})
        rows.append({**r, **s})
    return rows
