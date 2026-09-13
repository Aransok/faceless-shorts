"""Render stage for family_game_night (2026-09-13): the one stage that
produces BOTH audio and video for this template in a single pass,
unlike every other template's separate voice()/visuals_*() split.
pipeline/family_game/render.py's render_episode() already has to
interleave real narration audio with real PLAYER_TIME silence in
lockstep with the matching visual frame -- splitting that into two
independently-timed stages would mean re-deriving the same segment
timeline twice, in two places. Instead this stage does the whole render
in one call, then splits the single muxed output back into a silent
video-only file and an audio-only file so the REST of the pipeline
(assemble.py's music bed + CTA overlay, captions.py, upload.py) can
stay completely unmodified -- they already expect exactly that shape
from every other template.

video_id's status jumps straight from "scripted" to "visuals_ready"
(pipeline/orchestrator.py special-cases this one transition for this
template) -- there's no separate "voiced" status for family_game_night,
since the generic voice() stage doesn't know about PLAYER_TIME segments
at all, and family_game/render.py's own synth path already handles the
real narration.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pipeline.family_game.render import render_episode
from pipeline.state import get_video, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"


def _run_ffmpeg(args: list[str]) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    result = subprocess.run([ffmpeg_path, "-y", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")


def render_family_game_night(video_id: str) -> None:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if not video["family_game_segments_json"]:
        raise ValueError(f"video {video_id} has no family_game_segments_json -- run plan_family_game_night() first")

    segments = json.loads(video["family_game_segments_json"])
    combined_path = OUTPUT_DIR / f"{video_id}_family_game_combined.mp4"
    render_episode(segments, combined_path)

    video_only_path = OUTPUT_DIR / f"{video_id}_video.mp4"
    audio_only_path = OUTPUT_DIR / f"{video_id}_audio.wav"
    # assemble.py expects separate silent-video and audio-only inputs --
    # the same shape every other template's voice()/visuals_*() pair
    # already produces. Splitting the single muxed render back apart is
    # a plain stream copy for video (no re-encode), letting assemble.py
    # stay untouched for this template instead of teaching it a second
    # "already-muxed input" code path.
    _run_ffmpeg(["-i", str(combined_path), "-an", "-c:v", "copy", str(video_only_path)])
    _run_ffmpeg(["-i", str(combined_path), "-vn", str(audio_only_path)])

    update_video(video_id, status="visuals_ready", video_path=str(video_only_path), audio_path=str(audio_only_path))


if __name__ == "__main__":
    from pipeline.plan_family_game import plan_family_game_night

    new_id = plan_family_game_night()
    render_family_game_night(new_id)
    video = get_video(new_id)
    print(f"video_id: {new_id}")
    print(f"video_path: {video['video_path']}")
    print(f"audio_path: {video['audio_path']}")
