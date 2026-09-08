"""Phase 7: human review queue CLI. See SPEC.md / ROADMAP.md.

Usage:
    python scripts/review.py list
    python scripts/review.py open <video_id>
    python scripts/review.py approve <video_id>
    python scripts/review.py reject <video_id>
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.state import get_video, list_by_status, update_video


def cmd_list() -> None:
    videos = list_by_status("awaiting_review")
    if not videos:
        print("nothing awaiting review")
        return
    for v in videos:
        print(f"{v['id']}  [{v['template']}]  {v['title'] or v['hook'] or '(no title)'}")


def cmd_open(video_id: str) -> None:
    video = _require_video(video_id)
    path = video["final_path"]
    if not path or not Path(path).exists():
        raise SystemExit(f"no final video file on disk for {video_id} (final_path={path!r})")
    if os.name == "nt":
        os.startfile(path)
    else:
        raise SystemExit(f"don't know how to open a file on this OS — path is {path}")
    print(f"opened {path}")


def cmd_approve(video_id: str) -> None:
    video = _require_video(video_id)
    _check_awaiting_review(video)
    update_video(video_id, status="approved")
    print(f"{video_id} -> approved")


def cmd_reject(video_id: str) -> None:
    video = _require_video(video_id)
    _check_awaiting_review(video)
    update_video(video_id, status="rejected")
    print(f"{video_id} -> rejected")


def _require_video(video_id: str) -> dict:
    video = get_video(video_id)
    if video is None:
        raise SystemExit(f"no video with id {video_id}")
    return video


def _check_awaiting_review(video: dict) -> None:
    if video["status"] != "awaiting_review":
        raise SystemExit(
            f"{video['id']} is status {video['status']!r}, not awaiting_review — refusing to touch it"
        )


def main() -> None:
    args = sys.argv[1:]
    if not args:
        raise SystemExit(__doc__)

    command, rest = args[0], args[1:]
    if command == "list":
        cmd_list()
    elif command == "open":
        cmd_open(_require_id(rest))
    elif command == "approve":
        cmd_approve(_require_id(rest))
    elif command == "reject":
        cmd_reject(_require_id(rest))
    else:
        raise SystemExit(f"unknown command {command!r}\n\n{__doc__}")


def _require_id(rest: list[str]) -> str:
    if not rest:
        raise SystemExit("missing <video_id> argument")
    return rest[0]


if __name__ == "__main__":
    main()
