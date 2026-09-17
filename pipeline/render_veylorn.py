"""Render stage for veylorn_story (2026-09-18, standalone test format --
see HANDOFF.md): the real YouTube "keyboard-seek" mechanic (desktop
player: number keys 0-9 seek to that decile of total duration) only
works if the final video is a FIXED total duration with content that
actually changes at each exact 10% boundary. So unlike every other
template (which sizes its video to whatever the real narration takes),
this one fixes BEAT_SECONDS per beat up front and pads/measures audio
to fit it, then builds each beat's visual to match that same fixed
length -- the inverse of the usual "duration follows the audio" rule.

Does both narration synthesis AND visual rendering in this one stage
(same shape as render_family_game.py, for the same reason: the two are
locked together in time here, not independently timed), producing a
single combined output that's split into a silent video-only file and
an audio-only file so assemble.py/captions.py/upload.py stay unmodified.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from pipeline.pollinations import download_image
from pipeline.state import get_video, get_video_steps, update_video
from pipeline.voice import _pad_with_silence, audio_duration_seconds, synthesize

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"

WIDTH, HEIGHT = 1920, 1080
FPS = 30
TEMPLATE = "veylorn_story"

# 10 beats, one per decile of the final video -- see module docstring.
# 100s total is deliberately short for a first test (this format's real
# length can grow once the mechanic itself is validated against a real
# rendered video, not guessed at up front).
TOTAL_DURATION_SECONDS = 100.0
BEAT_COUNT = 10
BEAT_SECONDS = TOTAL_DURATION_SECONDS / BEAT_COUNT


def _beat_timing(real_duration: float, idx: int) -> tuple[float, float]:
    """(pad_seconds, final_duration) for one beat's real synthesized
    narration length -- pad_seconds > 0 means silence to append to hit
    the fixed BEAT_SECONDS budget exactly; pad_seconds == 0 (returned
    when the real narration already meets or exceeds the budget) means
    no padding, and final_duration is whatever the real overrun length
    actually is (see render_veylorn_story()'s own comment on why an
    overrun is allowed to happen rather than truncating speech).
    """
    pad_seconds = BEAT_SECONDS - real_duration
    if pad_seconds > 0:
        return pad_seconds, BEAT_SECONDS
    if pad_seconds < 0:
        print(f"[render_veylorn] beat {idx}: narration ({real_duration:.1f}s) exceeded the {BEAT_SECONDS:.0f}s budget -- decile alignment will drift from here")
    return 0.0, real_duration


def _run_ffmpeg(args: list[str]) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    result = subprocess.run([ffmpeg_path, "-y", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")


def _build_beat_segment(image_path: Path, audio_path: Path, frame_count: int, output_path: Path) -> None:
    """One beat's muxed video+audio, visual duration locked to
    `frame_count` (the beat's real, already-padded audio length in
    frames) via zoompan's own frame-exact `d=` -- same Ken-Burns
    approach as pipeline/visuals_facts.py's real-image beats, just muxed
    with real audio here instead of built silent.
    """
    vf = (
        f"scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH * 2}:{HEIGHT * 2},"
        f"zoompan=z='min(zoom+0.0008,1.1)':d={frame_count}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )
    _run_ffmpeg([
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-shortest",
        str(output_path),
    ])


def _concat_segments(segment_paths: list[Path], output_path: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in segment_paths:
            escaped = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        filelist_path = f.name
    try:
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", filelist_path, "-c", "copy", str(output_path)])
    finally:
        Path(filelist_path).unlink()


def render_veylorn_story(video_id: str) -> None:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    beats = get_video_steps(video_id)
    if len(beats) != BEAT_COUNT:
        raise ValueError(f"video {video_id} has {len(beats)} beats, expected exactly {BEAT_COUNT} -- run plan_veylorn_story() first")

    tts_backend = __import__("os").environ.get("TTS_BACKEND", "edge_tts")

    with tempfile.TemporaryDirectory(prefix="render_veylorn_") as tmp:
        tmp_dir = Path(tmp)
        segment_paths: list[Path] = []

        for beat in beats:
            idx = beat["round_index"]
            raw_audio_path = tmp_dir / f"beat{idx}_raw.mp3"
            synthesize(beat["script_text"], raw_audio_path, backend=tts_backend)
            real_duration = audio_duration_seconds(raw_audio_path)

            # Narration overrunning its 10s budget despite the prompt's
            # word-count limit is rare, but must not silently break
            # decile alignment for THIS beat -- letting it run its real
            # (longer) length instead of cutting speech off mid-word
            # means every later beat's decile boundary shifts by the
            # overrun on a real run. Acceptable for a standalone test,
            # worth tightening if this format moves past testing.
            pad_seconds, final_duration = _beat_timing(real_duration, idx)
            if pad_seconds > 0:
                _pad_with_silence(raw_audio_path, pad_seconds)

            image_path = tmp_dir / f"beat{idx}.jpg"
            download_image(beat["keywords"], image_path, width=WIDTH, height=HEIGHT, seed=idx)

            frame_count = round(final_duration * FPS)
            segment_path = tmp_dir / f"beat{idx}_segment.mp4"
            _build_beat_segment(image_path, raw_audio_path, frame_count, segment_path)
            segment_paths.append(segment_path)

        combined_path = OUTPUT_DIR / f"{video_id}_veylorn_combined.mp4"
        _concat_segments(segment_paths, combined_path)

        video_only_path = OUTPUT_DIR / f"{video_id}_video.mp4"
        audio_only_path = OUTPUT_DIR / f"{video_id}_audio.wav"
        _run_ffmpeg(["-i", str(combined_path), "-an", "-c:v", "copy", str(video_only_path)])
        _run_ffmpeg(["-i", str(combined_path), "-vn", str(audio_only_path)])

    update_video(video_id, status="visuals_ready", video_path=str(video_only_path), audio_path=str(audio_only_path))


if __name__ == "__main__":
    from pipeline.plan_veylorn import plan_veylorn_story

    new_id = plan_veylorn_story()
    render_veylorn_story(new_id)
    video = get_video(new_id)
    print(f"video_id:   {new_id}")
    print(f"video_path: {video['video_path']}")
    print(f"audio_path: {video['audio_path']}")
