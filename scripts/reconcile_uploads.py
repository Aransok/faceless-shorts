"""Find (and optionally re-register) videos that are live on the channel
but missing from the pipeline's own records.

Real incident 2026-09-22: a scheduled run uploaded 3 videos, then its
state.db/videos.json commit failed on a binary merge conflict -- the
videos stayed live, but the pipeline lost every record of them (no
analytics sync, no topic dedup). This lists the channel's real uploads
and diffs them against data/videos.json.

Usage:
    python scripts/reconcile_uploads.py                 # list only
    python scripts/reconcile_uploads.py --apply ID1,ID2 # re-register those
    python scripts/reconcile_uploads.py --apply ID1:food,ID2

--apply takes explicit IDs on purpose: the channel may also have videos
uploaded by hand that the pipeline never made. The template is inferred
from the video's YouTube category unless given as ID:template.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from googleapiclient.discovery import build

from pipeline.state import create_video, update_video
from pipeline.upload import VIDEOS_LOG_PATH, _load_credentials

# Reverse of pipeline/upload.py's CATEGORY_ID, for the templates that
# map unambiguously (24 is shared by facts and weird -- defaults to facts;
# pass ID:weird to override).
CATEGORY_TEMPLATE = {"28": "programming", "24": "facts", "26": "food", "22": "sauce_recipe"}


def template_for_category(category_id: str) -> str:
    return CATEGORY_TEMPLATE.get(category_id, "facts")


def find_untracked(channel_videos: list[dict], tracked_ids: set[str], since: datetime) -> list[dict]:
    """Channel videos uploaded on/after `since` whose ID isn't tracked."""
    return [
        v for v in channel_videos
        if v["id"] not in tracked_ids and datetime.fromisoformat(v["uploaded_at"].replace("Z", "+00:00")) >= since
    ]


def parse_apply_arg(arg: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for part in filter(None, (p.strip() for p in arg.split(","))):
        vid, _, template = part.partition(":")
        out[vid] = template or None
    return out


def _fetch_channel_videos(youtube) -> list[dict]:
    uploads = youtube.channels().list(part="contentDetails", mine=True).execute()
    playlist = uploads["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, page = [], None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=playlist, maxResults=50, pageToken=page
        ).execute()
        ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        page = resp.get("nextPageToken")
        if not page:
            break
    videos = []
    for i in range(0, len(ids), 50):
        resp = youtube.videos().list(part="snippet,status", id=",".join(ids[i : i + 50])).execute()
        for item in resp.get("items", []):
            videos.append({
                "id": item["id"],
                "title": item["snippet"]["title"],
                "description": item["snippet"].get("description", ""),
                "category_id": item["snippet"].get("categoryId", ""),
                "uploaded_at": item["snippet"]["publishedAt"],
                "publish_at": item["status"].get("publishAt"),
                "privacy": item["status"].get("privacyStatus"),
            })
    return videos


def _register(video: dict, template: str) -> dict:
    video_id = create_video(template, topic=video["title"])
    update_video(
        video_id, status="uploaded", title=video["title"], description=video["description"],
        youtube_video_id=video["id"],
    )
    return {
        "video_id": video_id,
        "youtube_video_id": video["id"],
        "uploaded_at": video["uploaded_at"].replace("Z", "+00:00"),
        "template": template,
        "approach": None,
        "scheduled_publish_at": video["publish_at"].replace("Z", "+00:00") if video["publish_at"] else None,
        "recovered": True,
    }


def main() -> None:
    log = json.loads(VIDEOS_LOG_PATH.read_text(encoding="utf-8")) if VIDEOS_LOG_PATH.exists() else []
    tracked = {r["youtube_video_id"] for r in log}
    since = min(datetime.fromisoformat(r["uploaded_at"]) for r in log) if log else datetime.min
    youtube = build("youtube", "v3", credentials=_load_credentials())
    channel = _fetch_channel_videos(youtube)
    untracked = find_untracked(channel, tracked, since)

    print(f"{len(channel)} videos on channel, {len(tracked)} tracked, {len(untracked)} untracked since {since.date()}:")
    for v in untracked:
        print(f"  {v['id']}  cat={v['category_id']} ({template_for_category(v['category_id'])})  "
              f"{v['privacy']}  uploaded {v['uploaded_at']}  {v['title']}")

    if "--apply" not in sys.argv:
        return
    wanted = parse_apply_arg(sys.argv[sys.argv.index("--apply") + 1])
    by_id = {v["id"]: v for v in untracked}
    for vid, template in wanted.items():
        if vid not in by_id:
            print(f"skip {vid}: not in the untracked list")
            continue
        record = _register(by_id[vid], template or template_for_category(by_id[vid]["category_id"]))
        log.append(record)
        print(f"registered {vid} as {record['template']} ({record['video_id']})")
    VIDEOS_LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
