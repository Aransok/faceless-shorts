"""Stage 2 (assembly): mux voice + visuals + a music bed into one raw
video, with the subscribe/share CTA overlay. See SPEC.md.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.brand import INDIGO as BRAND_INDIGO, TEAL as BRAND_TEAL, paste_gradient_rounded_rect
from pipeline.rotation import pick_rotating
from pipeline.state import get_video, list_by_status, update_video
from pipeline.voice import audio_duration_seconds

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"
MUSIC_DIR = PROJECT_ROOT / "assets" / "music"
FONT_BOLD_PATH = PROJECT_ROOT / "assets" / "fonts" / "JetBrainsMono-Bold.ttf"

MUSIC_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg")
# Every template gets a music bed now -- was ("facts", "quiz_longform")
# only, deliberately excluding "programming" (real reasoning at the time:
# code-render Shorts already have their own visual energy). Extended to
# all four templates for consistency/authenticity (silence under TTS
# reads as uncanny); "sauce_recipe" specifically was a real oversight,
# not a deliberate exclusion -- it launched without ever being added here.
MUSIC_TEMPLATES = ("facts", "quiz_longform", "programming", "sauce_recipe")
# How far below the narration's own measured loudness the music should
# sit — measured per-track/per-video rather than a fixed gain constant,
# since a fixed multiplier on top of tracks with different native loudness
# lands at wildly different perceived levels (a quiet track + a blind
# 0.12x multiplier was landing ~29dB under narration — near-inaudible).
MUSIC_GAP_DB = 15.0
MUSIC_GAIN_MIN, MUSIC_GAIN_MAX = 0.02, 1.5

CTA_FADE_IN = 0.5
CTA_FADE_OUT = 0.5

# 4 real variants (position, timing, phrasing) instead of one fixed badge
# on every video. y_fraction/start_fraction are both measured against the
# same safe band captions.py/visuals_code.py already established (clear
# of the top branding strip and the caption zone) -- see brand.py.
# save_for_later_early fires near the start (0.15) rather than mid/late
# like the other three -- "save this" only makes sense as a nudge before
# the viewer might swipe away, not after they've already watched most of it.
CTA_VARIANTS = [
    {
        "name": "corner_badge_late",
        "text": "SUBSCRIBE FOR MORE",
        "y_fraction": 0.12,
        "start_fraction": 0.80,
        "hold": 2.5,
    },
    {
        "name": "center_punch_mid",
        "text": "MORE LIKE THIS?",
        "y_fraction": 0.30,
        "start_fraction": 0.47,
        "hold": 1.5,
    },
    {
        "name": "late_banner_cadence",
        "text": "SUBSCRIBE — MORE TOMORROW",
        "y_fraction": 0.50,
        "start_fraction": 0.85,
        "hold": 2.0,
    },
    {
        "name": "save_for_later_early",
        "text": "SAVE THIS FOR LATER",
        "y_fraction": 0.12,
        "start_fraction": 0.15,
        "hold": 2.0,
    },
]
_CTA_VARIANTS_BY_NAME = {v["name"]: v for v in CTA_VARIANTS}
# 3 variants, exclude the last 1 -- same reasoning as the theme pool's
# window: a 15-video window sized for the 18-item hook pool would make
# this a permanent no-op on a pool this small. Leaves 2 real candidates.
CTA_ROTATION_WINDOW = 1


def pick_cta_variant() -> dict:
    name = pick_rotating("cta_variant", [v["name"] for v in CTA_VARIANTS], CTA_ROTATION_WINDOW)
    return _CTA_VARIANTS_BY_NAME[name]


CTA_BG_OPACITY = 225  # was a flat near-black CTA_BG=(19,20,18,225); now the brand gradient at the same opacity
CTA_ICON_BG = (255, 255, 255, 255)
CTA_ICON_FG = BRAND_INDIGO + (255,)
CTA_TEXT_COLOR = (242, 242, 234, 255)


def _probe_dimensions(path: Path) -> tuple[int, int]:
    """Reads the video's real width/height rather than assuming a fixed
    resolution — the Shorts templates render 1080x1920, the quiz
    longform track renders 1920x1080, and CTA badge positioning needs to
    work for either."""
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        raise RuntimeError("ffprobe not found on PATH")
    result = subprocess.run(
        [
            ffprobe_path, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed (exit {result.returncode}): {result.stderr}")
    width_str, height_str = result.stdout.strip().split("x")
    return int(width_str), int(height_str)


# Same reasoning as the theme/CTA pools: a real gap found while building
# those two (not something explicitly requested for music, but the same
# bug) -- this used to be a flat random.choice with no recent-history
# check at all, meaning two consecutive videos could land the identical
# track purely by chance once more than one track exists. 1 is safe
# regardless of how many tracks actually exist (with just 1 track, the
# exclusion always falls back to the full pool -- no crash, no
# behavior change from before); with 3-4, it leaves real candidates.
MUSIC_ROTATION_WINDOW = 1


def _pick_music_track() -> Path:
    tracks = [p for p in MUSIC_DIR.iterdir() if p.suffix.lower() in MUSIC_EXTENSIONS]
    if not tracks:
        raise RuntimeError(
            f"no music files in {MUSIC_DIR} — add 1+ royalty-free tracks "
            "(YouTube Audio Library / Pixabay Music) before running assemble.py"
        )
    by_name = {p.name: p for p in tracks}
    picked_name = pick_rotating("music_track", list(by_name), MUSIC_ROTATION_WINDOW)
    return by_name[picked_name]


def _measure_mean_volume_db(path: Path) -> float:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    result = subprocess.run(
        [ffmpeg_path, "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "mean_volume:" in line:
            return float(line.split("mean_volume:")[1].strip().split(" ")[0])
    raise RuntimeError(f"could not measure mean_volume for {path}:\n{result.stderr[-500:]}")


def _music_gain(music_track: Path, voice_path: Path) -> float:
    """Linear gain that puts the music track's mean loudness MUSIC_GAP_DB
    below the actual voice track's measured mean loudness — adaptive to
    both, so it stays correct whichever track gets dropped into
    assets/music/ and however loud a given narration happens to be.
    """
    voice_db = _measure_mean_volume_db(voice_path)
    music_db = _measure_mean_volume_db(music_track)
    target_db = voice_db - MUSIC_GAP_DB
    gain_db = target_db - music_db
    gain = 10 ** (gain_db / 20)
    return max(MUSIC_GAIN_MIN, min(MUSIC_GAIN_MAX, gain))


def render_cta_overlay(out_path: Path, text: str) -> tuple[int, int]:
    """Renders the reusable CTA badge (icon + text) as a transparent PNG.
    Returns its (width, height) for positioning.
    """
    font = ImageFont.truetype(str(FONT_BOLD_PATH), 40)
    padding_x, padding_y = 28, 20
    icon_size = 52
    gap = 18

    dummy = Image.new("RGBA", (10, 10))
    draw = ImageDraw.Draw(dummy)
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]

    badge_w = padding_x * 2 + icon_size + gap + text_w
    badge_h = max(icon_size, text_h) + padding_y * 2

    img = Image.new("RGBA", (badge_w, badge_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    paste_gradient_rounded_rect(
        img, (0, 0, badge_w, badge_h), badge_h // 2, BRAND_TEAL, BRAND_INDIGO, opacity=CTA_BG_OPACITY
    )

    icon_x0 = padding_x
    icon_y0 = (badge_h - icon_size) // 2
    draw.ellipse([icon_x0, icon_y0, icon_x0 + icon_size, icon_y0 + icon_size], fill=CTA_ICON_BG)
    cx, cy = icon_x0 + icon_size / 2, icon_y0 + icon_size / 2
    triangle = [
        (cx - icon_size * 0.14, cy - icon_size * 0.22),
        (cx - icon_size * 0.14, cy + icon_size * 0.22),
        (cx + icon_size * 0.22, cy),
    ]
    draw.polygon(triangle, fill=CTA_ICON_FG)

    text_x = icon_x0 + icon_size + gap
    text_y = (badge_h - text_h) // 2 - text_bbox[1]
    draw.text((text_x, text_y), text, font=font, fill=CTA_TEXT_COLOR)

    img.save(out_path)
    return badge_w, badge_h


def assemble(video_id: str, music_track: Path | None = None) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if not video["audio_path"]:
        raise ValueError(f"video {video_id} has no audio_path — run voice() first")
    if not video["video_path"]:
        raise ValueError(
            f"video {video_id} has no video_path — run visuals_code()/visuals_facts() first"
        )

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")

    duration = audio_duration_seconds(Path(video["audio_path"]))
    width, height = _probe_dimensions(Path(video["video_path"]))
    use_music = video["template"] in MUSIC_TEMPLATES
    if use_music:
        music_track = music_track or _pick_music_track()
        music_gain = _music_gain(music_track, Path(video["audio_path"]))

    cta_variant = pick_cta_variant()

    with tempfile.TemporaryDirectory(prefix="assemble_") as tmp:
        tmp_dir = Path(tmp)
        cta_path = tmp_dir / "cta.png"
        cta_w, cta_h = render_cta_overlay(cta_path, cta_variant["text"])

        cta_x = (width - cta_w) // 2
        cta_y = int(height * cta_variant["y_fraction"])

        fade_in_start = duration * cta_variant["start_fraction"]
        fade_out_start = fade_in_start + CTA_FADE_IN + cta_variant["hold"]
        # clamp defensively so an unusually short video can't push the CTA past the end
        fade_out_start = min(fade_out_start, max(0.0, duration - CTA_FADE_OUT))

        cmd = [ffmpeg_path, "-y", "-i", str(video["video_path"]), "-i", str(video["audio_path"])]
        if use_music:
            cmd += ["-stream_loop", "-1", "-i", str(music_track)]
        cta_input_index = 3 if use_music else 2
        cmd += ["-loop", "1", "-i", str(cta_path)]

        cta_filter = (
            f"[{cta_input_index}:v]format=rgba,"
            f"fade=t=in:st={fade_in_start:.3f}:d={CTA_FADE_IN}:alpha=1,"
            f"fade=t=out:st={fade_out_start:.3f}:d={CTA_FADE_OUT}:alpha=1[cta];"
            f"[0:v][cta]overlay={cta_x}:{cta_y}:format=auto[vout]"
        )
        if use_music:
            # normalize=0 is load-bearing: amix's default normalize=1
            # scales output based on how many inputs are momentarily
            # "active", which — with a spoken-word track full of natural
            # pauses — made the music nearly vanish underneath every
            # single narration gap instead of playing through as a
            # continuous bed. Confirmed via silencedetect: with the
            # default, the mixed output's silence gaps matched the voice
            # track's own pauses almost exactly; disabling normalize fixed
            # it, verified the same way.
            filter_complex = (
                f"{cta_filter};"
                f"[2:a]volume={music_gain:.4f}[music];"
                f"[1:a][music]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
            )
            audio_map = "[aout]"
        else:
            filter_complex = cta_filter
            audio_map = "1:a"

        output_path = OUTPUT_DIR / f"{video_id}_assembled.mp4"
        # Write to a scratch path first, then move into place — video_path
        # can already point at a previous assemble() run's own output (this
        # video was assembled before, e.g. to try a different track), and
        # ffmpeg refuses to open a file as both input and output.
        scratch_path = tmp_dir / "assembled_out.mp4"
        cmd += [
            "-filter_complex", filter_complex,
            "-map", "[vout]", "-map", audio_map,
            "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(scratch_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(scratch_path), str(output_path))

    update_video(video_id, status="assembled", video_path=str(output_path), cta_overlay_variant=cta_variant["name"])
    return str(output_path)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        candidates = list_by_status("visuals_ready")
        if not candidates:
            raise SystemExit(
                "no visuals_ready videos in state.db — run visuals_code.py/visuals_facts.py first"
            )
        video_id_arg = candidates[0]["id"]

    path = assemble(video_id_arg)
    print(f"video_id: {video_id_arg}")
    print(f"output:   {path}")
