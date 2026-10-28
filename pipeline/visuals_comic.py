"""Stage 2 (visuals, comic-style trial): each beat -> a run of AI-drawn
comic panels (Pollinations, free, no key), cut every ~2.5s with a
punch-in zoom and a whoosh on every cut.

One-week trial started 2026-10-26. The owner picked this look ("style B")
from rendered samples after calling the stock-footage videos cheap,
slow and boring, and after the doodle trial lost (see HANDOFF.md).
Same shape as the motionmaxxing trial: the VISUAL_STYLE=comic flag turns it
on, and it switches itself off on TRIAL_END so a forgotten flag can't
keep it running. Unlike that trial, any failure here falls back to the
stock-footage renderer. That trial had no fallback and lost every
programming video for a week.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from pipeline.pollinations import download_image
from pipeline.state import count_earlier_videos, get_video, get_video_steps, list_by_status, update_video
from pipeline.visuals_facts import FPS, HEIGHT, OUTPUT_DIR, WIDTH, _concat_segments, _parse_beat_visual_plan

TRIAL_END = date(2026, 11, 4)  # flag auto-offs on this day (last trial day is 11-03)
TEMPLATES = ("facts", "sauce_recipe", "food")
ALTERNATION_START = "2026-10-28"  # first eligible video from here on goes comic
RENDERER_NAME = "comic"

STYLE_SUFFIX = (
    "graphic novel illustration, bold black ink outlines, flat vivid colors, "
    "dramatic comic book composition, vertical"
)
IMAGE_SECONDS = 5.0  # one new picture per ~5s of narration...
CUTS_PER_IMAGE = 2  # ...shown in two framings, so a cut lands every ~2.5s
# The stock renderer leaves 3.5s of silence between beats (voice.py's
# BEAT_PAUSE_SECONDS). With a cut every 2.5s, that pause just reads as dead air.
BEAT_PAUSE_SECONDS = 0.6
PUNCH_FRAMES = 9  # 0.3s punch-in at the start of every shot
WHOOSH_LEAD_SECONDS = 0.15  # whoosh starts just before the cut so it lands on it

SCENE_PROMPT = """You plan the pictures for a faceless YouTube Short drawn in a comic-book style.
Video title: {title}
For EACH numbered beat below, write exactly the number of picture descriptions asked for, in the
order they will be shown while that beat is narrated. Each description is one concrete visual
scene of 8 to 20 words: who or what is in it, what is happening, the setting. Show what the
narration is literally talking about at that point. No text, letters, numbers, signs, charts or
diagrams in the picture (the image model draws them as gibberish). No real people's names.
Reply with ONLY JSON: {{"beats": [["scene", ...], ...]}} with one inner list per beat, in order.

Beats:
{beats}"""


def trial_active(today: date | None = None, env: dict[str, str] | None = None) -> bool:
    """True only when VISUAL_STYLE=comic and the trial window has not ended."""
    e = os.environ if env is None else env
    if (e.get("VISUAL_STYLE") or "").strip().lower() != RENDERER_NAME:
        return False
    return (today or date.today()) < TRIAL_END


def comic_for_position(position: int) -> bool:
    return position % 2 == 0


def in_comic_half(video_id: str) -> bool:
    """The owner wants old-style videos to keep coming during the trial,
    so eligible videos strictly alternate: comic, old, comic, old...
    (counted from ALTERNATION_START). A hash of the id was tried first, and
    the first real run sent only 1 of 5 eligible videos to comic. The
    position comes from earlier rows only, so voice() (which sets the beat
    gap) and the visuals stage agree, even across a resumed run. The old
    half is the control group for the weekly report."""
    return comic_for_position(count_earlier_videos(video_id, TEMPLATES, ALTERNATION_START))


def applies(template: str, video_id: str, today: date | None = None, env: dict[str, str] | None = None) -> bool:
    return template in TEMPLATES and in_comic_half(video_id) and trial_active(today, env)


def images_for_duration(duration: float) -> int:
    return max(1, round(duration / IMAGE_SECONDS))


def shot_frames(duration: float, images: int) -> list[int]:
    """Frame counts for the beat's images * CUTS_PER_IMAGE shots, summing
    exactly to the beat's own frame count (remainder to the earliest)."""
    total = round(duration * FPS)
    shots = max(1, min(images * CUTS_PER_IMAGE, total))
    base, remainder = divmod(total, shots)
    return [base + (1 if i < remainder else 0) for i in range(shots)]


def cut_times(frame_counts: list[int]) -> list[float]:
    """Seconds at which each shot after the first starts."""
    times, t = [], 0
    for f in frame_counts[:-1]:
        t += f
        times.append(t / FPS)
    return times


def fallback_scenes(raw_keywords: str, script_text: str, count: int) -> list[str]:
    """Scenes for a beat the LLM gave nothing usable for: the beat's own
    sentences, in narration order, tagged with its planned subject. The
    abstract search keywords ("serotonin light exposure") drew random
    moody characters when tried for real (2026-10-26); the sentences at
    least keep the picture on what is being said."""
    subject = _parse_beat_visual_plan(raw_keywords or "").get("subject")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", script_text) if s.strip()] or [script_text]
    picked = [sentences[min(len(sentences) - 1, i * len(sentences) // count)] for i in range(count)]
    return [f"{subject}: {s}" if subject else s for s in picked]


def parse_scene_plan(raw: str, counts: list[int]) -> list[list[str] | None]:
    """Validated scene lists aligned to beats; None for a beat the model got
    wrong (missing, wrong type, empty). Lists are trimmed or padded by
    repetition to exactly the asked-for count."""
    try:
        data, _ = json.JSONDecoder().raw_decode(raw[raw.index("{"):])
        beats = data["beats"]
    except (ValueError, KeyError, TypeError):
        return [None] * len(counts)
    out: list[list[str] | None] = []
    for i, count in enumerate(counts):
        scenes = beats[i] if i < len(beats) and isinstance(beats[i], list) else []
        scenes = [s.strip() for s in scenes if isinstance(s, str) and s.strip()]
        out.append([scenes[k % len(scenes)] for k in range(count)] if scenes else None)
    return out


def plan_scenes(beats: list[dict], title: str, counts: list[int]) -> list[list[str]]:
    from pipeline.plan import call_bulk_llm

    listing = "\n".join(
        f"{i + 1}. ({n} pictures) {b['script_text']}" for i, (b, n) in enumerate(zip(beats, counts))
    )
    try:
        planned = parse_scene_plan(call_bulk_llm(SCENE_PROMPT.format(title=title, beats=listing)), counts)
    except Exception as exc:  # fail soft: keyword scenes below
        print(f"[visuals_comic] scene planning failed: {exc}")
        planned = [None] * len(counts)
    return [
        p if p is not None else fallback_scenes(b["keywords"], b["script_text"], n)
        for p, b, n in zip(planned, beats, counts)
    ]


def image_prompt(scene: str) -> str:
    return f"{scene}, {STYLE_SUFFIX}"


def image_seed(video_id: str, index: int) -> int:
    """Stable per video+image, so a resumed run regenerates the same picture.
    Kept under 2**31: Pollinations answers 400 to a larger seed (seen for
    real, 2026-10-26)."""
    return int(hashlib.sha256(f"{video_id}:{index}".encode()).hexdigest()[:8], 16) % 2**31


def zoom_expr(variant: int) -> str:
    """Punch-in from 1.18 to 1.04 over PUNCH_FRAMES, then a slow push.
    Variant 1 (an image's second framing) starts tighter so the cut
    between two framings of the same picture visibly changes."""
    start = 1.18 if variant == 0 else 1.32
    settle = 1.04 if variant == 0 else 1.18
    step = (start - settle) / PUNCH_FRAMES
    return f"if(lt(on,{PUNCH_FRAMES}),{start}-{step:.5f}*on,{settle}+0.0009*(on-{PUNCH_FRAMES}))"


def _ffmpeg() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    return path


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-1500:]}")


def _render_shot(image_path: Path, frames: int, variant: int, out_path: Path) -> None:
    # 2x pre-upscale keeps zoompan smooth (same reason as visuals_facts'
    # image segments); variant 1 also pans the opposite way.
    x = "iw/2-(iw/zoom/2)" if variant == 0 else "(iw-iw/zoom)*0.35"
    vf = (
        f"scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,crop={WIDTH * 2}:{HEIGHT * 2},"
        f"zoompan=z='{zoom_expr(variant)}':x='{x}':y='ih/2-(ih/zoom/2)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS},"
        "eq=contrast=1.06:saturation=1.12,vignette=PI/5"
    )
    _run([_ffmpeg(), "-y", "-i", str(image_path), "-vf", vf, "-frames:v", str(frames),
          "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", str(out_path)])


def _whoosh(out_path: Path) -> None:
    _run([_ffmpeg(), "-y", "-f", "lavfi", "-i", "anoisesrc=d=0.35:c=pink:a=0.5", "-af",
          "highpass=f=400,lowpass=f=5000,afade=t=in:d=0.12,afade=t=out:st=0.15:d=0.2,volume=1.6",
          "-ar", "44100", "-ac", "2", str(out_path)])


def _mux_whooshes(video_path: Path, times: list[float], tmp_dir: Path, out_path: Path) -> None:
    """Adds an audio track of whooshes on every cut; assemble.py mixes any
    audio already on the visuals file in under the narration."""
    whoosh = tmp_dir / "whoosh.wav"
    _whoosh(whoosh)
    cmd = [_ffmpeg(), "-y", "-i", str(video_path)]
    chains, labels = [], []
    for i, t in enumerate(times):
        cmd += ["-i", str(whoosh)]
        ms = int(max(0.0, t - WHOOSH_LEAD_SECONDS) * 1000)
        chains.append(f"[{i + 1}:a]adelay={ms}|{ms}[w{i}]")
        labels.append(f"[w{i}]")
    if not labels:
        shutil.copy(video_path, out_path)
        return
    graph = ";".join(chains) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:normalize=0,apad[a]"
    _run(cmd + ["-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-shortest",
                "-c:v", "copy", "-c:a", "aac", str(out_path)])


def visuals_comic(video_id: str) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if video["template"] not in TEMPLATES:
        raise ValueError(f"visuals_comic only applies to {TEMPLATES}, got {video['template']!r}")
    beats = [dict(b) for b in get_video_steps(video_id)]
    if not beats or any(not b["duration"] for b in beats):
        raise ValueError(f"video {video_id} has beats without durations — run voice() first")

    counts = [images_for_duration(b["duration"]) for b in beats]
    scenes = plan_scenes(beats, video["title"] or video["topic"] or "", counts)

    with tempfile.TemporaryDirectory(prefix="visuals_comic_") as tmp:
        tmp_dir = Path(tmp)
        shots: list[Path] = []
        all_frames: list[int] = []
        image_index = 0
        for bi, (beat, beat_scenes) in enumerate(zip(beats, scenes)):
            images: list[Path] = []
            for scene in beat_scenes:
                path = tmp_dir / f"img{image_index:03d}.jpg"
                try:
                    download_image(image_prompt(scene), path, width=WIDTH, height=HEIGHT,
                                   seed=image_seed(video_id, image_index))
                    images.append(path)
                except Exception as exc:
                    # one missing picture shouldn't cost the video: reuse
                    # this beat's last good one (in its other framing)
                    print(f"[visuals_comic] beat {beat['step_index']} image failed: {exc}")
                    if not images:
                        raise
                    images.append(images[-1])
                image_index += 1
            frames = shot_frames(beat["duration"], len(images))
            for si, f in enumerate(frames):
                shot = tmp_dir / f"beat{bi}_shot{si:02d}.mp4"
                _render_shot(images[(si // CUTS_PER_IMAGE) % len(images)], f, si % CUTS_PER_IMAGE, shot)
                shots.append(shot)
            all_frames += frames

        silent = tmp_dir / "silent.mp4"
        _concat_segments(shots, silent)
        output_path = OUTPUT_DIR / f"{video_id}_comic.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        _mux_whooshes(silent, cut_times(all_frames), tmp_dir, output_path)

    update_video(video_id, status="visuals_ready", video_path=str(output_path), renderer=RENDERER_NAME)
    return str(output_path)


def try_comic(video_id: str) -> str | None:
    """Renders comic visuals while the trial is on for this video.
    Returns None (after logging why) when it doesn't apply or fails, so the
    caller falls back to the stock-footage renderer."""
    video = get_video(video_id)
    if video is None or not applies(video["template"], video_id):
        return None
    try:
        return visuals_comic(video_id)
    except Exception as exc:
        print(f"[visuals_comic] FAILED for {video_id}, falling back to stock footage: {exc}", file=sys.stderr)
        return None


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        candidates = [v for v in list_by_status("voiced") if v["template"] in TEMPLATES]
        if not candidates:
            raise SystemExit("no voiced facts/sauce_recipe/food videos in state.db — run voice.py first")
        video_id_arg = candidates[0]["id"]
    print(visuals_comic(video_id_arg))
