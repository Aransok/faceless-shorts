"""Visuals for the quiz longform track (horizontal 1920x1080, not a
Short) — question/countdown/reveal cards. Reuses the brand colors/fonts
from the Shorts pipeline (pipeline/brand.py, JetBrains Mono) so it's
recognizably the same channel. See ROADMAP.md's quiz track section.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.brand import INDIGO as BRAND_INDIGO, TEAL as BRAND_TEAL, paste_gradient_rounded_rect
from pipeline.render_text import draw_centered_lines, encode_png, fit_multiline, fit_single_line, wrap_text
from pipeline.state import get_video, get_video_steps, update_video
from pipeline.voice import voice

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "JetBrainsMono-Regular.ttf"
FONT_BOLD_PATH = PROJECT_ROOT / "assets" / "fonts" / "JetBrainsMono-Bold.ttf"

WIDTH, HEIGHT = 1920, 1080
FPS = 30
COUNTDOWN_SECONDS = 30.0  # silent think-time tail appended after each question's narration — also pushes total length toward the long-form threshold

PANEL_MARGIN_X = 260
PANEL_PADDING = 48
PANEL_RADIUS = 32
PANEL_BG = (24, 25, 22)
FRAME_BG = (14, 14, 13)
BORDER_WIDTH = 6
TOP_MARGIN = 70
# Hard safety margin text must never cross, on top of the panel's own
# padding — question/option text was observed rendering past the panel
# (and in the worst case past the frame edge) for long strings, since
# option text previously had no wrapping or shrinking at all. Named
# explicitly so it can't be quietly dropped later.
SAFE_MARGIN_FRACTION = 0.05
MIN_QUESTION_FONT_SIZE = 30
MIN_OPTION_FONT_SIZE = 24
# captions.py burns in word-level captions in a thin strip right at the
# bottom for a landscape frame (unlike the Shorts vertical layout, which
# has real empty space below its panel) — the panel must not extend into
# that zone, or captions collide with the option rows underneath them.
CAPTION_SAFE_HEIGHT = 220

QUESTION_FONT_SIZE = 50
OPTION_FONT_SIZE = 38
LABEL_FONT_SIZE = 34
INTRO_OUTRO_FONT_SIZE = 60
ROW_HEIGHT = 74
ROW_GAP = 16
OPTIONS_GAP = 40  # between the (wrapped) question text and the first option row

TEXT_COLOR = (242, 242, 234)
OPTION_BG = (39, 40, 34)
OPTION_LABEL_COLOR = (147, 148, 138)
CORRECT_BG = (34, 122, 90)  # dim green, reads clearly against the dark panel
CORRECT_TEXT = (232, 255, 244)
DIM_TEXT = (120, 121, 112)
COUNTDOWN_TRACK = (54, 55, 48)


def _compute_panel_geometry(steps: list[dict]) -> tuple[tuple[int, int, int, int], int, int]:
    """One panel size/position for the whole video (not resized per
    question — that would look jarring) — sized to the LONGEST wrapped
    question so every question fits, and positioned to stay clear of
    captions.py's bottom caption strip.

    REAL BUG this fixes: the previous version measured content_h at a
    fixed base font size, then clamped panel_h to the available space
    with min(content_h, available_h) if content_h was too big — but
    nothing then shrank the actual CONTENT to match, so a long question
    (5-6+ wrapped lines) pushed the option rows past the clamped panel's
    own bottom edge, visible in a real render (confirmed: option D fully
    outside the panel border). Fix: shrink the base question font size
    in a loop — same "shrink until it fits" principle as
    fit_multiline/fit_single_line, applied to the whole video's shared
    panel budget instead of one line's width — until content_h actually
    fits available_h, before the panel size is ever fixed.
    """
    dummy_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    content_w = (WIDTH - 2 * PANEL_MARGIN_X) - 2 * PANEL_PADDING
    safe_content_w = int(content_w * (1 - SAFE_MARGIN_FRACTION))
    question_texts = [s["script_text"] for s in steps if s["card_type"] == "question"]

    available_top = TOP_MARGIN
    available_bottom = HEIGHT - CAPTION_SAFE_HEIGHT
    available_h = available_bottom - available_top

    size = QUESTION_FONT_SIZE
    while True:
        q_font = ImageFont.truetype(str(FONT_PATH), size)
        max_q_lines = max(
            (len(wrap_text(dummy_draw, t, q_font, safe_content_w)) for t in question_texts), default=1,
        )
        ascent, descent = q_font.getmetrics()
        q_line_height = int((ascent + descent) * 1.3)
        content_h = max_q_lines * q_line_height + OPTIONS_GAP + 4 * (ROW_HEIGHT + ROW_GAP) + 2 * PANEL_PADDING
        if content_h <= available_h or size <= MIN_QUESTION_FONT_SIZE:
            break
        size -= 2

    x0 = PANEL_MARGIN_X
    x1 = WIDTH - PANEL_MARGIN_X
    # Even at the size floor, a pathologically long question could still
    # exceed available_h — panel_h stays clamped as a last-resort visual
    # bound (better a tight fit than drawing past the frame), but this
    # should be rare given the shrink loop above already ran to the floor.
    panel_h = min(content_h, available_h)
    y0 = available_top + max(0, available_h - panel_h) // 2
    y1 = y0 + panel_h
    return (x0, y0, x1, y1), q_line_height, size


def _render_base_panel(panel_box: tuple[int, int, int, int]) -> Image.Image:
    frame = Image.new("RGB", (WIDTH, HEIGHT), FRAME_BG)
    draw = ImageDraw.Draw(frame)
    x0, y0, x1, y1 = panel_box
    paste_gradient_rounded_rect(
        frame, (x0 - BORDER_WIDTH, y0 - BORDER_WIDTH, x1 + BORDER_WIDTH, y1 + BORDER_WIDTH),
        PANEL_RADIUS + BORDER_WIDTH, BRAND_TEAL, BRAND_INDIGO,
    )
    draw.rounded_rectangle([x0, y0, x1, y1], radius=PANEL_RADIUS, fill=PANEL_BG)
    return frame


def _render_text_card(text: str, panel_box: tuple[int, int, int, int], base_panel: Image.Image) -> Image.Image:
    """Intro/outro card: the narration line, centered in the panel."""
    frame = base_panel.copy()
    draw = ImageDraw.Draw(frame)
    x0, y0, x1, y1 = panel_box
    max_width = int(((x1 - x0) - 2 * PANEL_PADDING) * (1 - SAFE_MARGIN_FRACTION))
    font, lines = fit_multiline(draw, text, FONT_PATH, INTRO_OUTRO_FONT_SIZE, MIN_QUESTION_FONT_SIZE, max_width)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * 1.4)
    total_h = len(lines) * line_height
    top_y = (y0 + y1) // 2 - total_h // 2
    draw_centered_lines(draw, lines, font, TEXT_COLOR, WIDTH // 2, top_y, line_height)
    return frame


def _fit_question_layout(
    question: str, options: list[str], panel_box: tuple[int, int, int, int], q_line_height: int, base_font_size: int
) -> dict:
    """Fitting (shrink-to-width, option truncation) is the same for every
    frame of a given question — computed once per question/reveal pair,
    not per frame. With the countdown now running up to 30s (900 frames
    at 30fps), re-fitting on every countdown frame would reintroduce a
    real per-frame cost.

    base_font_size is _compute_panel_geometry's resolved size (already
    shrunk if needed so every question's line count fits the shared
    panel height) — starting from it here, rather than the fixed
    QUESTION_FONT_SIZE constant, keeps this shrink pass and the panel's
    own height budget consistent with each other.
    """
    draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    x0, y0, x1, y1 = panel_box
    content_w = (x1 - x0) - 2 * PANEL_PADDING
    safe_content_w = int(content_w * (1 - SAFE_MARGIN_FRACTION))

    # Word-wrapping (wrap_text) already keeps normal questions within
    # bounds; the shrink loop here is the real safety net — a single
    # long unbroken token (or an unusually long question) can't be
    # wrapped away, only shrunk.
    q_font_fit, q_lines = fit_multiline(draw, question, FONT_PATH, base_font_size, MIN_QUESTION_FONT_SIZE, safe_content_w)
    q_ascent, q_descent = q_font_fit.getmetrics()
    q_line_height_fit = int((q_ascent + q_descent) * 1.3)
    q_top = y0 + PANEL_PADDING

    # Options positioned against the SAME q_line_height the panel
    # geometry was computed with, so row positions stay stable even when
    # a question needed to shrink.
    options_top = q_top + len(q_lines) * q_line_height + OPTIONS_GAP
    row_x0 = x0 + PANEL_PADDING
    label_reserved_w = 60  # space text_x starts after (label + its own gap)
    option_max_w = int((content_w - label_reserved_w - 24) * (1 - SAFE_MARGIN_FRACTION))  # 24px right-side breathing room

    fitted_options = [
        fit_single_line(draw, opt, FONT_PATH, OPTION_FONT_SIZE, MIN_OPTION_FONT_SIZE, option_max_w)
        for opt in options
    ]

    return {
        "q_font": q_font_fit, "q_lines": q_lines, "q_line_height": q_line_height_fit, "q_top": q_top,
        "options_top": options_top, "row_x0": row_x0, "row_w": content_w,
        "label_reserved_w": label_reserved_w, "fitted_options": fitted_options,
    }


def _render_question_card(
    layout: dict,
    correct_index: int | None,
    reveal: bool,
    countdown_fraction: float | None,
    label_font: ImageFont.FreeTypeFont,
    panel_box: tuple[int, int, int, int],
    base_panel: Image.Image,
) -> Image.Image:
    frame = base_panel.copy()
    draw = ImageDraw.Draw(frame)
    x0, y0, x1, y1 = panel_box
    cx = WIDTH // 2

    draw_centered_lines(draw, layout["q_lines"], layout["q_font"], TEXT_COLOR, cx, layout["q_top"], layout["q_line_height"])

    row_x0, row_w = layout["row_x0"], layout["row_w"]
    for i, (opt_font_fit, fitted_text) in enumerate(layout["fitted_options"]):
        row_y0 = layout["options_top"] + i * (ROW_HEIGHT + ROW_GAP)
        row_y1 = row_y0 + ROW_HEIGHT
        is_correct = reveal and correct_index == i
        bg = CORRECT_BG if is_correct else OPTION_BG
        draw.rounded_rectangle([row_x0, row_y0, row_x0 + row_w, row_y1], radius=16, fill=bg)

        label_x = row_x0 + 28
        label_y = row_y0 + (ROW_HEIGHT - LABEL_FONT_SIZE) // 2 - 4
        label_color = CORRECT_TEXT if is_correct else OPTION_LABEL_COLOR
        draw.text((label_x, label_y), chr(65 + i), font=label_font, fill=label_color)

        text_color = CORRECT_TEXT if is_correct else (DIM_TEXT if reveal else TEXT_COLOR)
        text_x = label_x + layout["label_reserved_w"]
        o_ascent, o_descent = opt_font_fit.getmetrics()
        text_y = row_y0 + (ROW_HEIGHT - (o_ascent + o_descent)) // 2 - o_descent // 2
        draw.text((text_x, text_y), fitted_text, font=opt_font_fit, fill=text_color)

    # Countdown bar: only during a question card's silent think-time tail,
    # drawn within the panel's own bottom padding so it never touches the
    # last option row.
    if countdown_fraction is not None:
        bar_y0 = y1 - PANEL_PADDING + 10
        bar_y1 = bar_y0 + 8
        bar_x0 = x0 + PANEL_PADDING
        bar_x1 = x1 - PANEL_PADDING
        draw.rounded_rectangle([bar_x0, bar_y0, bar_x1, bar_y1], radius=4, fill=COUNTDOWN_TRACK)
        remaining_w = int((bar_x1 - bar_x0) * max(0.0, 1.0 - countdown_fraction))
        if remaining_w > 0:
            paste_gradient_rounded_rect(
                frame, (bar_x0, bar_y0, bar_x0 + remaining_w, bar_y1), 4, BRAND_TEAL, BRAND_INDIGO,
            )

    return frame


def render_quiz_video(steps: list[dict], output_path: Path) -> Path:
    label_font = ImageFont.truetype(str(FONT_BOLD_PATH), LABEL_FONT_SIZE)
    panel_box, q_line_height, base_font_size = _compute_panel_geometry(steps)
    # The border/panel fill never changes across the whole video — render
    # it once and .copy() it per frame instead of recomputing the
    # gradient border thousands of times (this was the real per-frame
    # cost: a multi-minute video means thousands of frames, and
    # make_gradient_image used to scale its own cost with pixel width).
    base_panel = _render_base_panel(panel_box)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visuals_quiz_") as tmp:
        tmp_dir = Path(tmp)
        frame_idx = 0

        current_layout: dict | None = None
        for step in steps:
            duration = step["duration"] or 0.0
            card_type = step["card_type"]

            if card_type in ("intro", "outro"):
                frame = _render_text_card(step["script_text"], panel_box, base_panel)
                # Identical content for the whole duration — render once,
                # write the same bytes to every needed frame index rather
                # than re-running Pillow draw calls per frame.
                frame_bytes = encode_png(frame)
                for _ in range(max(1, round(duration * FPS))):
                    (tmp_dir / f"{frame_idx:05d}.png").write_bytes(frame_bytes)
                    frame_idx += 1
                continue

            options = json.loads(step["options"]) if step["options"] else []
            correct_index = step["correct_index"]
            reveal = card_type == "reveal"
            # A reveal card shows the SAME question as its preceding
            # question card — script_text on a reveal step is the
            # explanation narration (captioned separately by
            # captions.py), not something to display as the heading.
            # Fitting (shrink-to-width, truncation) only needs to run once
            # per question — reused for its paired reveal step too, not
            # recomputed per frame.
            if card_type == "question":
                current_layout = _fit_question_layout(step["script_text"], options, panel_box, q_line_height, base_font_size)
            layout = current_layout

            narration_frames = max(1, round(duration * FPS))
            countdown_frames = round(COUNTDOWN_SECONDS * FPS) if card_type == "question" else 0

            # Narration phase: content is static (no countdown bar) for
            # its whole span — same one-render-many-writes optimization.
            frame = _render_question_card(layout, correct_index, reveal, None, label_font, panel_box, base_panel)
            frame_bytes = encode_png(frame)
            for f in range(narration_frames):
                (tmp_dir / f"{frame_idx:05d}.png").write_bytes(frame_bytes)
                frame_idx += 1

            # Countdown phase: the progress bar genuinely changes every
            # frame, so this part still renders each frame individually —
            # but the (now-cheap) draw calls only, no re-fitting text.
            for f in range(countdown_frames):
                progress = (f + 1) / countdown_frames
                frame = _render_question_card(layout, correct_index, reveal, progress, label_font, panel_box, base_panel)
                frame.save(tmp_dir / f"{frame_idx:05d}.png")
                frame_idx += 1

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg not found on PATH")

        result = subprocess.run(
            [
                ffmpeg_path, "-y", "-framerate", str(FPS), "-i", str(tmp_dir / "%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output_path),
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")

    return output_path


def _build_padded_audio(video_id: str, steps: list[dict]) -> Path:
    """Question steps get COUNTDOWN_SECONDS of silence appended to their
    own narration so the audio timeline matches the video's — the visual
    holds through the countdown, so the audio must too, or every
    subsequent step drifts out of sync. Uses the concat filter (not the
    demuxer used elsewhere) since it re-encodes internally regardless of
    input codec, avoiding the exact-codec-match requirement a stream-copy
    concat would need to mix in generated silence cleanly.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")

    inputs: list[str] = []
    filter_parts: list[str] = []
    for i, step in enumerate(steps):
        inputs += ["-i", step["audio_path"]]
        if step["card_type"] == "question":
            filter_parts.append(f"[{i}:a]apad=pad_dur={COUNTDOWN_SECONDS}[a{i}]")
        else:
            filter_parts.append(f"[{i}:a]anull[a{i}]")

    concat_inputs = "".join(f"[a{i}]" for i in range(len(steps)))
    filter_complex = ";".join(filter_parts) + f";{concat_inputs}concat=n={len(steps)}:v=0:a=1[aout]"

    out_path = OUTPUT_DIR / f"{video_id}_quiz_audio.mp3"
    result = subprocess.run(
        [ffmpeg_path, "-y", *inputs, "-filter_complex", filter_complex, "-map", "[aout]", str(out_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg audio padding failed (exit {result.returncode}): {result.stderr}")
    return out_path


def visuals_quiz(video_id: str) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if video["template"] != "quiz_longform":
        raise ValueError(f"visuals_quiz only applies to quiz_longform, got {video['template']!r}")

    steps = get_video_steps(video_id)
    if not steps:
        raise ValueError(f"video {video_id} has no video_steps — run plan_quiz() first")
    missing_duration = [s["step_index"] for s in steps if not s["duration"]]
    if missing_duration:
        raise ValueError(f"video {video_id} steps {missing_duration} have no duration — run voice() first")

    padded_audio_path = _build_padded_audio(video_id, steps)

    output_path = OUTPUT_DIR / f"{video_id}_quiz.mp4"
    render_quiz_video(steps, output_path)

    update_video(video_id, status="visuals_ready", video_path=str(output_path), audio_path=str(padded_audio_path))
    return str(output_path)


if __name__ == "__main__":
    import sys

    from pipeline.state import list_by_status

    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        candidates = [v for v in list_by_status("voiced") if v["template"] == "quiz_longform"]
        if not candidates:
            raise SystemExit("no voiced quiz videos in state.db — run plan_quiz.py then voice.py first")
        video_id_arg = candidates[0]["id"]

    path = visuals_quiz(video_id_arg)
    print(f"video_id: {video_id_arg}")
    print(f"output:   {path}")
