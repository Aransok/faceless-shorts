"""Uploads hand-made promo videos (not pipeline output) listed in a
manifest, e.g. the Project Ember game teaser (2026-10-09, owner: "add the
teaser for our game as a short ... highlight it in the channel and as a
normal video too").

Each manifest entry is uploaded public once (entries already in
data/videos.json are skipped, so re-running is safe) and logged there
with template "promo", which makes the daily upload cap count it -- the
owner chose to fit promo uploads inside the day's normal 6. An entry with
"channel_trailer": true also becomes the channel trailer shown to
non-subscribers.

Usage (CI only -- needs the YT_* secrets):
    python scripts/upload_promo.py assets/promo/project-ember/manifest.json
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from pipeline.upload import VIDEOS_LOG_PATH, _load_credentials


def pending_entries(manifest: list[dict], log: list[dict]) -> list[dict]:
    done = {r["video_id"] for r in log}
    return [e for e in manifest if e["key"] not in done]


def build_body(entry: dict) -> dict:
    return {
        "snippet": {
            "title": entry["title"],
            "description": entry["description"],
            "tags": entry.get("tags", []),
            "categoryId": entry.get("category_id", "20"),
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False},
    }


def with_trailer(branding: dict, youtube_video_id: str) -> dict:
    """brandingSettings with only the trailer changed. channels.update
    clears any brandingSettings field left out of the request, so the
    channel's current values (description, keywords, ...) must be sent
    back unchanged."""
    updated = json.loads(json.dumps(branding))
    updated.setdefault("channel", {})["unsubscribedTrailer"] = youtube_video_id
    return updated


def set_channel_trailer(youtube, youtube_video_id: str) -> None:
    channel = youtube.channels().list(part="brandingSettings", mine=True).execute()["items"][0]
    branding = channel.get("brandingSettings", {})
    if branding.get("channel", {}).get("unsubscribedTrailer") == youtube_video_id:
        print(f"{youtube_video_id} is already the channel trailer")
        return
    youtube.channels().update(
        part="brandingSettings",
        body={"id": channel["id"], "brandingSettings": with_trailer(branding, youtube_video_id)},
    ).execute()
    print(f"channel trailer set to https://youtu.be/{youtube_video_id}")


def main(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    log = json.loads(VIDEOS_LOG_PATH.read_text(encoding="utf-8")) if VIDEOS_LOG_PATH.exists() else []
    todo = pending_entries(manifest, log)
    if not todo:
        print("every manifest entry is already uploaded")
        return
    youtube = build("youtube", "v3", credentials=_load_credentials())
    for entry in todo:
        media = MediaFileUpload(str(manifest_path.parent / entry["file"]), mimetype="video/mp4", resumable=True)
        response = None
        request = youtube.videos().insert(part="snippet,status", body=build_body(entry), media_body=media)
        while response is None:
            _, response = request.next_chunk()
        youtube_video_id = response["id"]
        print(f"uploaded {entry['key']}: https://youtu.be/{youtube_video_id}")
        log.append({
            "video_id": entry["key"],
            "youtube_video_id": youtube_video_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "template": "promo",
            "approach": None,
        })
        # Written after every upload, so a later failure can't lose the
        # record of one that already went live.
        VIDEOS_LOG_PATH.write_text(json.dumps(log, indent=2), encoding="utf-8")
        if entry.get("channel_trailer"):
            set_channel_trailer(youtube, youtube_video_id)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/upload_promo.py <manifest.json>")
    main(Path(sys.argv[1]))
