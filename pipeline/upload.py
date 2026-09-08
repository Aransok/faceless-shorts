"""Stage 3 (Phase 8): YouTube upload. See SPEC.md.

Credentials come from credentials/youtube_token.json (local dev, produced
by scripts/get_youtube_token.py) or, if that file isn't present, from
YT_CLIENT_ID/YT_CLIENT_SECRET/YT_REFRESH_TOKEN env vars (CI, where a
committed JSON file isn't an option — see SPEC.md's CI section).
"""

from __future__ import annotations

import json
import os
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from pipeline.plan import call_llm
from pipeline.state import get_video, list_by_status, list_uploaded_without_cta_comment, update_video
from pipeline.thumbnails import upload_thumbnail

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOKEN_PATH = PROJECT_ROOT / "credentials" / "youtube_token.json"
DATA_DIR = PROJECT_ROOT / "data"
VIDEOS_LOG_PATH = DATA_DIR / "videos.json"
CTA_COMMENT_PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "cta_comment_template.txt"

load_dotenv(PROJECT_ROOT / ".env")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# YouTube's fixed category IDs. Not configurable — a sane per-template
# default is enough, this isn't a knob anything else needs yet.
CATEGORY_ID = {
    "programming": "28",  # Science & Technology
    "facts": "24",  # Entertainment
    "quiz_longform": "27",  # Education
}

VALID_VISIBILITY = ("private", "unlisted", "public", "scheduled")

# UPLOAD_VISIBILITY=scheduled: upload private with a future publishAt —
# YouTube auto-flips it public at that time, no process needs to stay
# running. Each video schedules 2-4 random hours after the latest
# already-scheduled (not yet public) one, so a batch spreads out over the
# day instead of all going public back-to-back.
PUBLISH_GAP_MIN_HOURS = 2.0
PUBLISH_GAP_MAX_HOURS = 4.0


def _load_credentials() -> Credentials:
    if TOKEN_PATH.exists():
        data = json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
        return Credentials(
            None,
            refresh_token=data["refresh_token"],
            token_uri=data["token_uri"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            scopes=data["scopes"],
        )

    client_id = os.environ.get("YT_CLIENT_ID")
    client_secret = os.environ.get("YT_CLIENT_SECRET")
    refresh_token = os.environ.get("YT_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        raise RuntimeError(
            f"no YouTube credentials found — expected {TOKEN_PATH} (local dev, run "
            "scripts/get_youtube_token.py) or YT_CLIENT_ID/YT_CLIENT_SECRET/"
            "YT_REFRESH_TOKEN env vars (CI)"
        )
    return Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )


def _build_snippet(video: dict) -> dict:
    tags = [t.strip() for t in (video["tags"] or "").split(",") if t.strip()]
    return {
        "title": video["title"],
        "description": video["description"],
        "tags": tags,
        "categoryId": CATEGORY_ID.get(video["template"], "22"),
    }


def _next_publish_time() -> datetime:
    """Random 2-4 hours after the latest already-scheduled-but-not-yet-
    public video in the log, or 2-4 hours from now if there's no pending
    one — keeps a whole batch spread out rather than clustered, and
    keeps spacing correct across separate daily runs too."""
    now = datetime.now(timezone.utc)
    records = json.loads(VIDEOS_LOG_PATH.read_text(encoding="utf-8")) if VIDEOS_LOG_PATH.exists() else []
    future_times = [
        t
        for r in records
        if r.get("scheduled_publish_at")
        and (t := datetime.fromisoformat(r["scheduled_publish_at"])) > now
    ]
    base = max(future_times) if future_times else now
    gap_hours = random.uniform(PUBLISH_GAP_MIN_HOURS, PUBLISH_GAP_MAX_HOURS)
    return base + timedelta(hours=gap_hours)


def _build_upload_body(video: dict, visibility: str, scheduled_publish_at: datetime | None) -> dict:
    status = {"selfDeclaredMadeForKids": False}
    if visibility == "scheduled":
        status["privacyStatus"] = "private"
        status["publishAt"] = scheduled_publish_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        status["privacyStatus"] = visibility

    return {"snippet": _build_snippet(video), "status": status}


def update_remote_metadata(video_id: str) -> None:
    """Pushes this video's current title/description/tags to the already-
    uploaded YouTube video, without re-uploading the file — for fixing
    metadata after upload (e.g. the #Shorts hashtag requirement discovered
    once a video was already live).
    """
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if not video["youtube_video_id"]:
        raise ValueError(f"{video_id} has no youtube_video_id — it hasn't been uploaded yet")

    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    body = {"id": video["youtube_video_id"], "snippet": _build_snippet(video)}
    youtube.videos().update(part="snippet", body=body).execute()


def _log_uploaded_video(video: dict, youtube_video_id: str, scheduled_publish_at: datetime | None) -> None:
    """Appends one record to data/videos.json — video ID, upload
    timestamp, template, and approach tag — feeding the weekly stats job
    (ROADMAP.md Phase 10 #4) once enough videos/time have accumulated.
    scheduled_publish_at (when UPLOAD_VISIBILITY=scheduled) is what
    _next_publish_time() reads back to keep a batch's publish times
    spread out.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    records = json.loads(VIDEOS_LOG_PATH.read_text(encoding="utf-8")) if VIDEOS_LOG_PATH.exists() else []
    records.append(
        {
            "video_id": video["id"],
            "youtube_video_id": youtube_video_id,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "template": video["template"],
            "approach": video["approach"],
            "scheduled_publish_at": scheduled_publish_at.isoformat() if scheduled_publish_at else None,
        }
    )
    VIDEOS_LOG_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def upload(video_id: str) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if video["status"] != "approved":
        raise ValueError(f"{video_id} is status {video['status']!r}, not approved — refusing to upload")
    final_path = video["final_path"]
    if not final_path or not Path(final_path).exists():
        raise ValueError(f"no final video file on disk for {video_id} (final_path={final_path!r})")

    visibility = os.environ.get("UPLOAD_VISIBILITY", "private")
    if visibility not in VALID_VISIBILITY:
        raise ValueError(f"invalid UPLOAD_VISIBILITY {visibility!r}, expected one of {VALID_VISIBILITY}")
    scheduled_publish_at = _next_publish_time() if visibility == "scheduled" else None

    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    body = _build_upload_body(video, visibility, scheduled_publish_at)

    media = MediaFileUpload(final_path, mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = request.execute()
    youtube_video_id = response["id"]

    update_video(video_id, status="uploaded", youtube_video_id=youtube_video_id)
    _log_uploaded_video(video, youtube_video_id, scheduled_publish_at)

    try:
        upload_thumbnail(video_id, youtube)
    except Exception as exc:
        # The main video is already live at this point — a thumbnail
        # failure (quota, transient error) shouldn't undo that or fail
        # the whole upload() call.
        print(f"warning: thumbnail upload failed for {video_id}: {exc}")

    # Only attempt this immediately when the video is ALREADY public
    # (visibility == "public", not "scheduled"/"private") -- confirmed for
    # real that commentThreads.insert always fails on a still-private
    # video (identical call succeeds instantly once a video is actually
    # public), so trying it right after a scheduled upload was a
    # guaranteed, wasted failure every single time. The scheduled/private
    # case is caught later by post_pending_cta_comments().
    if visibility == "public":
        try:
            post_cta_comment(video, youtube_video_id, youtube)
            update_video(video_id, cta_comment_posted=1)
        except Exception as exc:
            print(f"warning: CTA comment post failed for {video_id}: {exc}")

    return youtube_video_id


# The Data API's commentThreads resource only supports list/insert — there
# is no pin endpoint at all (confirmed against the current API reference,
# not assumed). Posting the comment is real and automatable; pinning it
# still needs one manual click per video in YouTube Studio.
#
# Fallback pool only — used if the real topic-aware LLM comment (below)
# fails for any reason, so a transient LLM error never blocks the comment
# entirely, just makes this one instance generic instead of specific.
_CTA_COMMENTS = [
    "More of these coming — subscribed yet?",
    "Which one got you? Let me know below.",
    "If this caught you off guard, there's more where it came from.",
    "Subscribe if you want more of these.",
    "Drop a comment if you actually knew this one.",
]

_COMMENT_FIELD_PATTERN = re.compile(r"COMMENT:\s*(.*)", re.DOTALL)


def _generate_cta_comment(video: dict) -> str:
    """A real comment referencing this specific video's actual content —
    not a generic line picked from a fixed pool — same authenticity
    reasoning as everywhere else in this pipeline (see persona.md):
    generic, reused-across-every-video comments read as template output,
    a specific one reads as a creator who watched their own upload.
    """
    prompt_body = CTA_COMMENT_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = (
        prompt_body.replace("{topic}", video["topic"] or "")
        .replace("{hook}", video["hook"] or "")
        .replace("{script_text}", video["script_text"] or "")
    )
    raw = call_llm(prompt)
    match = _COMMENT_FIELD_PATTERN.search(raw.strip())
    if not match:
        raise ValueError(f"LLM output missing COMMENT field:\n{raw}")
    comment = match.group(1).strip()
    if not comment:
        raise ValueError("LLM produced an empty comment")
    return comment


def post_cta_comment(video: dict, youtube_video_id: str, youtube) -> None:
    try:
        comment = _generate_cta_comment(video)
    except Exception as exc:
        print(f"warning: topic-aware CTA comment generation failed ({exc}) — using fallback pool")
        comment = random.choice(_CTA_COMMENTS)

    body = {
        "snippet": {
            "videoId": youtube_video_id,
            "topLevelComment": {"snippet": {"textOriginal": comment}},
        }
    }
    youtube.commentThreads().insert(part="snippet", body=body).execute()


def post_pending_cta_comments() -> None:
    """Catch-up pass: for every uploaded video whose CTA comment hasn't
    posted yet, re-checks its REAL current privacyStatus (not our own
    stored schedule -- that's an estimate, this is the source of truth)
    and posts once it's actually public. Meant to run on its own schedule
    (see .github/workflows/post-pending-comments.yml), separate from the
    upload run itself, since a scheduled video can take hours to go
    public after upload() already returned.
    """
    pending = list_uploaded_without_cta_comment()
    if not pending:
        print("no pending CTA comments")
        return

    creds = _load_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    by_yt_id = {v["youtube_video_id"]: v for v in pending}
    yt_ids = list(by_yt_id)
    live_status: dict[str, str] = {}
    for i in range(0, len(yt_ids), 50):
        batch = yt_ids[i : i + 50]
        resp = youtube.videos().list(part="status", id=",".join(batch)).execute()
        for item in resp.get("items", []):
            live_status[item["id"]] = item["status"]["privacyStatus"]

    for yt_id, video in by_yt_id.items():
        status = live_status.get(yt_id)
        if status != "public":
            print(f"still {status!r}, not yet public: {video['id']} ({yt_id})")
            continue
        try:
            post_cta_comment(video, yt_id, youtube)
            update_video(video["id"], cta_comment_posted=1)
            print(f"posted CTA comment: {video['id']} ({yt_id})")
        except Exception as exc:
            print(f"warning: CTA comment post failed for {video['id']} ({yt_id}): {exc}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        approved = list_by_status("approved")
        if not approved:
            raise SystemExit("no approved videos in state.db — run scripts/review.py approve <id> first")
        video_id_arg = approved[0]["id"]

    yt_id = upload(video_id_arg)
    print(f"video_id:         {video_id_arg}")
    print(f"youtube_video_id: {yt_id}")
    print(f"url:              https://youtube.com/watch?v={yt_id}")
