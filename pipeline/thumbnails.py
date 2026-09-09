"""Phase 10 #2: custom thumbnails via a still frame extracted from each
video's own rendered final file, rather than a separate graphic-
generation system — the fastest path to working thumbnails, reusing what
Phase 4/5 already rendered. v2 (a branded title-card graphic) is a later
improvement once this simple version is proven. See ROADMAP.md Phase 10.

Requires the channel to be phone-verified (thumbnails.set fails with a
403 otherwise) — see ROADMAP.md for that prerequisite.
"""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import time
from pathlib import Path

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from PIL import Image, ImageDraw, ImageFont

from pipeline.brand import INDIGO as BRAND_INDIGO, TEAL as BRAND_TEAL, make_gradient_image, paste_gradient_rounded_rect
from pipeline.state import get_video, get_video_steps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"
THUMBNAIL_LOG_PATH = PROJECT_ROOT / "data" / "thumbnails.json"
FONT_BOLD_PATH = PROJECT_ROOT / "assets" / "fonts" / "Poppins-ExtraBold.ttf"

# Quiz longform: the thumbnail is the main click-through driver (unlike a
# Short), so it's a designed graphic, not a frame extraction — real 16:9
# since the quiz video itself already is, no letterbox scaling needed.
# Poppins ExtraBold (not JetBrains Mono) — a thumbnail is viewed tiny in
# search/browse, and a bold sans-serif reads clearer at that size than a
# monospace face designed for code.
QUIZ_THUMB_WIDTH, QUIZ_THUMB_HEIGHT = 1280, 720
QUIZ_HOOK_TEXT = "CAN YOU PASS THIS QUIZ?"
QUIZ_FONT_SIZE = 92
QUIZ_SUBTITLE_FONT_SIZE = 48
QUIZ_DARK_BG = (14, 14, 13)
QUIZ_WHITE = (255, 255, 255)

# YouTube's stated thumbnail minimum is expressed as a 16:9 1280x720
# frame, but Shorts thumbnails are actually displayed vertically — we
# scale the real 9:16 frame up so both dimensions clear that floor
# (1280 wide, well over 720 tall) rather than force-cropping into a
# landscape frame that doesn't match how the video is actually watched.
MIN_WIDTH = 1280
MAX_BYTES = 2 * 1024 * 1024


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _video_duration(path: Path) -> float:
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        raise RuntimeError("ffprobe not found on PATH")
    result = _run(
        [
            ffprobe_path, "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        ]
    )
    return float(result.stdout.strip())


def _candidate_timestamps(video: dict) -> list[float]:
    """Two candidate timestamps in priority order — a primary
    strong-visual-moment pick, and a fallback if the primary lands on
    something illegible (blank panel, mid fade-transition)."""
    steps = get_video_steps(video["id"])
    durations = [s["duration"] or 0.0 for s in steps]

    if video["template"] == "programming":
        # Prefer the last step with real output_text — per the prompt
        # template, that's the corrected code + right result, the
        # strongest "real code + output on screen" moment. Fall back to
        # the last step overall if none have output_text.
        output_indices = [i for i, s in enumerate(steps) if s["output_text"]]
        target_index = output_indices[-1] if output_indices else len(steps) - 1
        cumulative = sum(durations[:target_index])
        target_duration = durations[target_index] if durations else 0.0
        # 85% into the step's hold period (well past typing, before any
        # outgoing fade — the last step never fades out); 50% as fallback.
        return [cumulative + 0.85 * target_duration, cumulative + 0.5 * target_duration]

    # facts: near the hook (early in beat 1's narration), not the outro.
    total = sum(durations)
    return [min(3.5, total * 0.5), min(1.8, total * 0.25)]


def _extract_frame(video_path: Path, timestamp: float, out_path: Path) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    result = _run(
        [
            ffmpeg_path, "-y", "-ss", f"{timestamp:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-vf", f"scale={MIN_WIDTH}:-2", "-q:v", "2", str(out_path),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed (exit {result.returncode}): {result.stderr}")


def _is_frame_valid(video_path: Path, timestamp: float) -> bool:
    """A cheap sanity check, not full legibility detection: reject a
    timestamp landing inside visuals_code.py's fade-to-blank transition
    (or any near-black moment) by checking a small window around it."""
    ffmpeg_path = shutil.which("ffmpeg")
    start = max(0.0, timestamp - 0.15)
    result = _run(
        [
            ffmpeg_path, "-ss", f"{start:.3f}", "-i", str(video_path), "-t", "0.3",
            "-vf", "blackdetect=d=0.05:pic_th=0.98", "-an", "-f", "null", "-",
        ]
    )
    return "black_start" not in result.stderr


def _log_thumbnail_pick(video_id: str, chosen: float, candidates: list[float], out_path: Path) -> None:
    THUMBNAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(THUMBNAIL_LOG_PATH.read_text(encoding="utf-8")) if THUMBNAIL_LOG_PATH.exists() else []
    records.append(
        {
            "video_id": video_id,
            "chosen_timestamp": round(chosen, 2),
            "candidate_timestamps": [round(t, 2) for t in candidates],
            "thumbnail_path": str(out_path),
        }
    )
    THUMBNAIL_LOG_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def generate_thumbnail(video_id: str) -> Path:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    final_path = video["final_path"]
    if not final_path or not Path(final_path).exists():
        raise ValueError(f"no final video file on disk for {video_id}")

    duration = _video_duration(Path(final_path))
    candidates = [min(t, max(0.0, duration - 0.2)) for t in _candidate_timestamps(video)]

    chosen = next((t for t in candidates if _is_frame_valid(Path(final_path), t)), candidates[-1])

    out_path = OUTPUT_DIR / f"{video_id}_thumbnail.jpg"
    _extract_frame(Path(final_path), chosen, out_path)

    size = out_path.stat().st_size
    if size > MAX_BYTES:
        raise RuntimeError(f"thumbnail for {video_id} is {size} bytes, over the 2MB limit")

    _log_thumbnail_pick(video_id, chosen, candidates, out_path)
    return out_path


def _wrap_thumb_text(draw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or draw.textlength(trial, font=font) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _quiz_headline_text(video: dict, question_count: int) -> str:
    """A real, per-video challenge-framed headline built from the
    video's actual hook — not a generic label like "Python Quiz #N"."""
    hook = (video["hook"] or "").rstrip(".!? ")
    if not hook:
        return f"{question_count} PYTHON QUESTIONS"
    if len(hook) > 65:
        hook = hook[:65].rsplit(" ", 1)[0]
    return hook.upper()


def _draw_outlined_centered(draw, lines, font, cx, top_y, line_height, outline=3):
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        x, y = cx - w / 2, top_y + i * line_height
        for ox, oy in ((-outline, 0), (outline, 0), (0, -outline), (0, outline)):
            draw.text((x + ox, y + oy), line, font=font, fill=QUIZ_DARK_BG)
        draw.text((x, y), line, font=font, fill=QUIZ_WHITE)


def _render_thumb_challenge_hook(headline: str, question_count: int) -> Image.Image:
    """Concept 1: full gradient background, the real per-video hook as a
    bold challenge-framed headline, question count as a subtitle."""
    img = Image.new("RGB", (QUIZ_THUMB_WIDTH, QUIZ_THUMB_HEIGHT))
    paste_gradient_rounded_rect(img, (0, 0, QUIZ_THUMB_WIDTH, QUIZ_THUMB_HEIGHT), 0, BRAND_TEAL, BRAND_INDIGO)
    draw = ImageDraw.Draw(img)

    hook_font = ImageFont.truetype(str(FONT_BOLD_PATH), QUIZ_FONT_SIZE)
    sub_font = ImageFont.truetype(str(FONT_BOLD_PATH), QUIZ_SUBTITLE_FONT_SIZE)
    max_width = QUIZ_THUMB_WIDTH - 160
    lines = _wrap_thumb_text(draw, headline, hook_font, max_width)

    ascent, descent = hook_font.getmetrics()
    line_height = int((ascent + descent) * 1.15)
    total_h = len(lines) * line_height
    subtitle_text = f"{question_count} QUESTIONS — HOW MANY DO YOU KNOW?"
    sub_ascent, sub_descent = sub_font.getmetrics()
    gap = 30
    top_y = (QUIZ_THUMB_HEIGHT - (total_h + gap + sub_ascent + sub_descent)) // 2

    _draw_outlined_centered(draw, lines, hook_font, QUIZ_THUMB_WIDTH // 2, top_y, line_height)
    sub_w = draw.textlength(subtitle_text, font=sub_font)
    draw.text(((QUIZ_THUMB_WIDTH - sub_w) / 2, top_y + total_h + gap), subtitle_text, font=sub_font, fill=QUIZ_WHITE)
    return img


_STAT_MARGIN_V = 40
_MIN_STAT_NUMBER_SIZE = 180
_MIN_STAT_HEADLINE_SIZE = 40


def _render_thumb_stat_challenge(headline: str, question_count: int) -> Image.Image:
    """Concept 2: dark background, the question count as a huge gradient
    number (the "big visual hook" of a number, not just text), headline
    stacked below it."""
    img = Image.new("RGB", (QUIZ_THUMB_WIDTH, QUIZ_THUMB_HEIGHT), QUIZ_DARK_BG)
    draw = ImageDraw.Draw(img)

    max_width = QUIZ_THUMB_WIDTH - 120
    available_h = QUIZ_THUMB_HEIGHT - 2 * _STAT_MARGIN_V

    # Shrink number + headline together until the stacked block actually
    # fits the canvas height — a fixed 320pt number plus a 3-line-wrapped
    # headline can exceed 720px and get clipped at the bottom edge (a real,
    # observed overflow, not hypothetical), same class of bug as the quiz
    # longform panel overflow fixed earlier in visuals_quiz.py.
    number_size, headline_size = 320, 66
    while True:
        number_font = ImageFont.truetype(str(FONT_BOLD_PATH), number_size)
        number_text = str(question_count)
        n_ascent, n_descent = number_font.getmetrics()

        headline_font = ImageFont.truetype(str(FONT_BOLD_PATH), headline_size)
        lines = _wrap_thumb_text(draw, headline, headline_font, max_width)
        h_ascent, h_descent = headline_font.getmetrics()
        line_height = int((h_ascent + h_descent) * 1.15)

        block_h = (n_ascent + n_descent) + 40 + len(lines) * line_height
        if block_h <= available_h or (number_size <= _MIN_STAT_NUMBER_SIZE and headline_size <= _MIN_STAT_HEADLINE_SIZE):
            break
        number_size = max(_MIN_STAT_NUMBER_SIZE, number_size - 20)
        headline_size = max(_MIN_STAT_HEADLINE_SIZE, headline_size - 4)

    num_w = draw.textlength(number_text, font=number_font)
    top_y = max(_STAT_MARGIN_V, (QUIZ_THUMB_HEIGHT - block_h) // 2)

    # Number rendered as a gradient-filled cutout via the mask trick used
    # for panel borders elsewhere — paste the gradient through the glyph
    # shape instead of a flat fill.
    mask = Image.new("L", (int(num_w) + 20, n_ascent + n_descent), 0)
    ImageDraw.Draw(mask).text((10, 0), number_text, font=number_font, fill=255)
    grad_img = make_gradient_image(mask.width, mask.height, BRAND_TEAL, BRAND_INDIGO)
    img.paste(grad_img, (int((QUIZ_THUMB_WIDTH - mask.width) / 2), top_y), mask)

    _draw_outlined_centered(
        draw, lines, headline_font, QUIZ_THUMB_WIDTH // 2, top_y + (n_ascent + n_descent) + 40, line_height, outline=2
    )
    return img


def _render_thumb_question_panel(video: dict, question_count: int) -> Image.Image:
    """Concept 3: the actual first question's real text in a small
    chrome-styled panel (matching the video's own brand chrome), a big
    "?" as a background design element, and a short challenge headline."""
    img = Image.new("RGB", (QUIZ_THUMB_WIDTH, QUIZ_THUMB_HEIGHT), QUIZ_DARK_BG)
    draw = ImageDraw.Draw(img)

    # Big "?" as a subtle background design element, drawn first so the
    # panel/text layer on top stays fully legible.
    q_font = ImageFont.truetype(str(FONT_BOLD_PATH), 420)
    draw.text((QUIZ_THUMB_WIDTH - 260, QUIZ_THUMB_HEIGHT // 2), "?", font=q_font, anchor="mm", fill=(34, 36, 46))

    steps = get_video_steps(video["id"])
    first_question = next((s["script_text"] for s in steps if s["card_type"] == "question"), "")
    panel_font = ImageFont.truetype(str(FONT_BOLD_PATH), 40)
    panel_x0, panel_y0, panel_w = 70, 240, 760
    panel_lines = _wrap_thumb_text(draw, first_question, panel_font, panel_w - 60)[:4]
    p_ascent, p_descent = panel_font.getmetrics()
    p_line_height = int((p_ascent + p_descent) * 1.3)
    panel_h = len(panel_lines) * p_line_height + 60
    paste_gradient_rounded_rect(
        img, (panel_x0 - 4, panel_y0 - 4, panel_x0 + panel_w + 4, panel_y0 + panel_h + 4), 20, BRAND_TEAL, BRAND_INDIGO,
    )
    draw.rounded_rectangle([panel_x0, panel_y0, panel_x0 + panel_w, panel_y0 + panel_h], radius=16, fill=(24, 25, 22))
    for i, line in enumerate(panel_lines):
        draw.text((panel_x0 + 30, panel_y0 + 30 + i * p_line_height), line, font=panel_font, fill=QUIZ_WHITE)

    headline_font = ImageFont.truetype(str(FONT_BOLD_PATH), 56)
    headline = f"{question_count} QUESTIONS. CAN YOU GET THEM ALL?"
    _draw_outlined_centered(
        draw, _wrap_thumb_text(draw, headline, headline_font, QUIZ_THUMB_WIDTH - 100),
        headline_font, QUIZ_THUMB_WIDTH // 2, panel_y0 + panel_h + 50, 66, outline=2,
    )
    return img


_QUIZ_THUMBNAIL_VARIANTS = ("challenge_hook", "stat_challenge", "question_panel")


def _recent_thumbnail_variants(limit: int = 3) -> list[str]:
    if not THUMBNAIL_LOG_PATH.exists():
        return []
    records = json.loads(THUMBNAIL_LOG_PATH.read_text(encoding="utf-8"))
    return [r["variant"] for r in records if "variant" in r][-limit:]


def _score_variant(name: str, img: Image.Image, headline_fit: bool, recent: list[str]) -> float:
    """Deterministic, code-based scoring — not the LLM's own unchecked
    choice. Real, measurable criteria: reward headline text that fit
    without needing truncation, and reward variety by penalizing a
    variant used in the last few thumbnails."""
    score = 0.0
    score += 2.0 if headline_fit else 0.0
    score -= recent.count(name) * 1.5
    return score


def generate_quiz_thumbnail(video_id: str) -> Path:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")

    steps = get_video_steps(video_id)
    question_count = sum(1 for s in steps if s["card_type"] == "question")
    headline = _quiz_headline_text(video, question_count)
    recent = _recent_thumbnail_variants()

    dummy_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    hook_font_check = ImageFont.truetype(str(FONT_BOLD_PATH), QUIZ_FONT_SIZE)
    headline_fits = len(_wrap_thumb_text(dummy_draw, headline, hook_font_check, QUIZ_THUMB_WIDTH - 160)) <= 2

    candidates = {
        "challenge_hook": _render_thumb_challenge_hook(headline, question_count),
        "stat_challenge": _render_thumb_stat_challenge(headline, question_count),
        "question_panel": _render_thumb_question_panel(video, question_count),
    }
    scored = [(name, _score_variant(name, img, headline_fits, recent)) for name, img in candidates.items()]
    best_score = max(s for _, s in scored)
    best_names = [name for name, s in scored if s == best_score]
    chosen_name = random.choice(best_names)  # tie-break among equally-scored candidates, not a fixed order
    chosen_img = candidates[chosen_name]

    out_path = OUTPUT_DIR / f"{video_id}_quiz_thumbnail.jpg"
    chosen_img.save(out_path, quality=92)

    THUMBNAIL_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    records = json.loads(THUMBNAIL_LOG_PATH.read_text(encoding="utf-8")) if THUMBNAIL_LOG_PATH.exists() else []
    records.append({"video_id": video_id, "variant": chosen_name, "thumbnail_path": str(out_path)})
    THUMBNAIL_LOG_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")

    return out_path


# Real, observed failure (2026-09-09 daily run): thumbnails().set()
# called immediately after videos().insert() returns a 404 "video not
# found" -- YouTube's backend hasn't finished indexing the just-created
# video yet. Same "immediately after upload" propagation-delay class of
# bug as Phase 15's CTA-comment-on-a-still-private-video fix, just a
# different endpoint. Retrying specifically on 404 (not any other error
# -- a real quota/permission failure should still fail fast, not be
# masked by retries) recovers it once the video is indexed.
THUMBNAIL_SET_RETRY_DELAYS = (2, 4, 8)


def upload_thumbnail(video_id: str, youtube) -> Path:
    """Call after the main upload succeeds. `youtube` is an
    already-built googleapiclient discovery resource, reused from
    upload.py rather than reconstructed here, to avoid a second OAuth
    round-trip. Costs 50 quota units, separate from the upload bucket."""
    video = get_video(video_id)
    if not video["youtube_video_id"]:
        raise ValueError(f"{video_id} has no youtube_video_id yet — upload the video first")

    if video["template"] == "quiz_longform":
        thumb_path = generate_quiz_thumbnail(video_id)
    else:
        thumb_path = generate_thumbnail(video_id)

    last_exc: HttpError | None = None
    for delay in (0,) + THUMBNAIL_SET_RETRY_DELAYS:
        if delay:
            time.sleep(delay)
        media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg")
        try:
            youtube.thumbnails().set(videoId=video["youtube_video_id"], media_body=media).execute()
            return thumb_path
        except HttpError as exc:
            if exc.resp.status != 404:
                raise
            last_exc = exc
    raise last_exc
