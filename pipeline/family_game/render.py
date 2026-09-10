"""Render path for Family Game Night segments -- FAMILY_GAME_NIGHT_SPEC.md
section 30 Phase 3's own vertical-slice list, the part
pipeline/family_game/base.py + higher_or_lower.py didn't yet cover:
Narration -> Player time -> Countdown -> Reveal -> Render.

Visual chrome (panel/border/gradient) is drawn locally rather than
imported from visuals_game.py's private helpers -- this project's own
convention (visuals_game.py itself doesn't import visuals_quiz.py's
private helpers either; each visuals_*.py file owns its own panel
constants and shares only the genuinely public pieces of
pipeline.brand/pipeline.render_text). The comparison-card layout is a
deliberate close cousin of visuals_game.py's _render_comparison_beat --
same idea (a known value vs. a "?" card, revealed on demand) -- redrawn
here because this format's PLAYER_TIME state (an unrevealed card held
for an explicit, narration-independent duration) has no equivalent
concept in that module to extend.

The one genuinely new piece: PLAYER_TIME duration comes from each
segment's own duration_seconds (pipeline/family_game/base.py), not from
narration length -- a HOST_TIME segment's clip duration is its real
synthesized audio length; a PLAYER_TIME segment's clip duration is
`silence padded to exactly duration_seconds`, built directly rather than
via voice.py's apad-a-narration-clip helpers (there is no narration to
pad -- the whole point is that none is required).
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.brand import INDIGO as BRAND_INDIGO, TEAL as BRAND_TEAL, paste_gradient_rounded_rect
from pipeline.family_game.base import HOST_TIME, PLAYER_TIME
from pipeline.render_text import draw_centered_lines, encode_png, fit_multiline, fit_single_line
from pipeline.voice import audio_duration_seconds, synthesize

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "JetBrainsMono-Regular.ttf"
FONT_BOLD_PATH = PROJECT_ROOT / "assets" / "fonts" / "JetBrainsMono-Bold.ttf"

WIDTH, HEIGHT = 1920, 1080
FPS = 30

PANEL_MARGIN_X = 260
PANEL_PADDING = 48
PANEL_RADIUS = 32
PANEL_BG = (24, 25, 22)
FRAME_BG = (14, 14, 13)
BORDER_WIDTH = 6
TOP_MARGIN = 70
CAPTION_SAFE_HEIGHT = 220
SAFE_MARGIN_FRACTION = 0.05
PANEL_BOX = (PANEL_MARGIN_X, TOP_MARGIN, WIDTH - PANEL_MARGIN_X, HEIGHT - CAPTION_SAFE_HEIGHT)

TEXT_FONT_SIZE = 54
MIN_TEXT_FONT_SIZE = 28
VALUE_FONT_SIZE = 68
MIN_VALUE_FONT_SIZE = 32
NAME_FONT_SIZE = 40
MIN_NAME_FONT_SIZE = 24
LABEL_FONT_SIZE = 30
COUNTDOWN_FONT_SIZE = 220
CHIP_FONT_SIZE = 32

TEXT_COLOR = (242, 242, 234)
DIM_TEXT = (147, 148, 138)
CARD_BG = (39, 40, 34)
CARD_BG_DIM = (30, 31, 27)
# Player time gets its own accent (distinct from the reveal accent below)
# so a viewer can tell "still guessable" from "answer is shown" at a
# glance, independent of reading the label text -- section 9's own
# requirement made visual, not just textual.
PLAYER_ACCENT = (74, 58, 24)
PLAYER_ACCENT_TEXT = (245, 214, 160)
REVEAL_BG = (24, 74, 68)
REVEAL_TEXT = (198, 245, 235)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _render_base_panel() -> Image.Image:
    frame = Image.new("RGB", (WIDTH, HEIGHT), FRAME_BG)
    draw = ImageDraw.Draw(frame)
    x0, y0, x1, y1 = PANEL_BOX
    paste_gradient_rounded_rect(
        frame, (x0 - BORDER_WIDTH, y0 - BORDER_WIDTH, x1 + BORDER_WIDTH, y1 + BORDER_WIDTH),
        PANEL_RADIUS + BORDER_WIDTH, BRAND_TEAL, BRAND_INDIGO,
    )
    draw.rounded_rectangle([x0, y0, x1, y1], radius=PANEL_RADIUS, fill=PANEL_BG)
    return frame


def _content_area() -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = PANEL_BOX
    return x0 + PANEL_PADDING, y0 + PANEL_PADDING, x1 - PANEL_PADDING, y1 - PANEL_PADDING


def _render_text_card(text: str) -> Image.Image:
    """HOST_TIME intro/rule/explanation/transition beats -- a centered
    text card. Not used for 'reveal' or 'prompt', which get the
    comparison card below."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()
    max_width = int((cx1 - cx0) * (1 - SAFE_MARGIN_FRACTION))
    font, lines = fit_multiline(draw, text, FONT_PATH, TEXT_FONT_SIZE, MIN_TEXT_FONT_SIZE, max_width)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * 1.4)
    total_h = len(lines) * line_height
    top_y = (cy0 + cy1) // 2 - total_h // 2
    draw_centered_lines(draw, lines, font, TEXT_COLOR, WIDTH // 2, top_y, line_height)
    return frame


def _render_comparison_card(round_data: dict, state: str) -> Image.Image:
    """The higher_or_lower versus card, one function covering all three
    states this format needs it in:
    - "prompt" (host time): item A known, item B hidden as "?", label asks
      the question.
    - "player" (player time): same unrevealed layout, but the label reads
      as an active prompt to the viewer instead of a question -- this is
      the card a viewer is looking at while actually thinking.
    - "reveal" (host time): item B's real value shown, label states the
      answer.
    """
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) // 2
    unit = round_data["unit"]

    label_font = _font(FONT_PATH, LABEL_FONT_SIZE)
    card_w, card_h = 560, 260
    gap = 80
    total_w = 2 * card_w + gap
    x_a = WIDTH / 2 - total_w / 2
    x_b = x_a + card_w + gap
    y = cy_mid - card_h / 2
    inner_max_w = int((card_w - 48) * (1 - SAFE_MARGIN_FRACTION))

    def centered_fit(text, cx, y_, base_size, min_size, color, bold=True):
        font, fitted = fit_single_line(draw, text, FONT_BOLD_PATH if bold else FONT_PATH, base_size, min_size, inner_max_w)
        w = draw.textlength(fitted, font=font)
        draw.text((cx - w / 2, y_), fitted, font=font, fill=color)

    draw.rounded_rectangle([x_a, y, x_a + card_w, y + card_h], radius=18, fill=CARD_BG)
    centered_fit(round_data["item_a_name"], x_a + card_w / 2, y + 40, NAME_FONT_SIZE, MIN_NAME_FONT_SIZE, TEXT_COLOR)
    centered_fit(f"~{round_data['item_a_value']:g} {unit}", x_a + card_w / 2, y + 120, VALUE_FONT_SIZE, MIN_VALUE_FONT_SIZE, TEXT_COLOR)

    if state == "reveal":
        draw.rounded_rectangle([x_b, y, x_b + card_w, y + card_h], radius=18, fill=REVEAL_BG)
        centered_fit(round_data["item_b_name"], x_b + card_w / 2, y + 40, NAME_FONT_SIZE, MIN_NAME_FONT_SIZE, REVEAL_TEXT)
        centered_fit(f"~{round_data['item_b_value']:g} {unit}", x_b + card_w / 2, y + 120, VALUE_FONT_SIZE, MIN_VALUE_FONT_SIZE, REVEAL_TEXT)
        label = round_data["correct_answer"].upper()
        label_color = DIM_TEXT
    else:
        card_bg = PLAYER_ACCENT if state == "player" else CARD_BG_DIM
        draw.rounded_rectangle([x_b, y, x_b + card_w, y + card_h], radius=18, fill=card_bg)
        centered_fit(round_data["item_b_name"], x_b + card_w / 2, y + 40, NAME_FONT_SIZE, MIN_NAME_FONT_SIZE, TEXT_COLOR)
        centered_fit("?", x_b + card_w / 2, y + 120, VALUE_FONT_SIZE, MIN_VALUE_FONT_SIZE, TEXT_COLOR)
        if state == "player":
            label, label_color = "YOUR TURN -- WHAT'S YOUR ANSWER?", PLAYER_ACCENT_TEXT
        else:
            label, label_color = "HIGHER OR LOWER?", DIM_TEXT

    lw = draw.textlength(label, font=label_font)
    draw.text((WIDTH / 2 - lw / 2, y - 50), label, font=label_font, fill=label_color)
    return frame


def _render_countdown_number(n: int) -> Image.Image:
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) // 2
    font = _font(FONT_BOLD_PATH, COUNTDOWN_FONT_SIZE)
    text = str(n)
    w = draw.textlength(text, font=font)
    ascent, descent = font.getmetrics()
    draw.text((WIDTH / 2 - w / 2, cy_mid - (ascent + descent) / 2), text, font=font, fill=PLAYER_ACCENT_TEXT)
    return frame


ROW_FONT_SIZE = 34
ATTR_LABEL_FONT_SIZE = 30


def _text_center_y(font: ImageFont.FreeTypeFont, cy: float) -> float:
    ascent, descent = font.getmetrics()
    return cy - (ascent + descent) / 2 - descent / 2 + descent


def _chip_row(
    draw: ImageDraw.ImageDraw, cy: float, entries: list[tuple[str, tuple[int, int, int], tuple[int, int, int]]],
    font: ImageFont.FreeTypeFont, gap: int = 24, pad_x: int = 28, pad_y: int = 18,
) -> None:
    """A horizontal row of rounded-rect text chips, centered on the
    panel. entries: list of (label, bg_color, text_color)."""
    ascent, descent = font.getmetrics()
    h = ascent + descent + 2 * pad_y
    widths = [draw.textlength(label, font=font) + 2 * pad_x for label, _, _ in entries]
    total_w = sum(widths) + gap * max(0, len(entries) - 1)
    x = WIDTH / 2 - total_w / 2
    for (label, bg, text_color), w in zip(entries, widths):
        box = [x, cy - h / 2, x + w, cy + h / 2]
        draw.rounded_rectangle(box, radius=14, fill=bg)
        tw = draw.textlength(label, font=font)
        draw.text((x + w / 2 - tw / 2, _text_center_y(font, cy)), label, font=font, fill=text_color)
        x += w + gap


def _render_memory_card(round_data: dict) -> Image.Image:
    """Memory Challenge's three real states, one function since they
    share the same chip-row visual language:
    - "sequence": the full sequence, nothing hidden -- this is shown
      while the viewer has real time to memorize it.
    - "question": the sequence is gone, only the target icon's name
      remains -- forces a genuine recall decision instead of letting the
      viewer just re-read the sequence to check.
    - "reveal": the sequence again, with the target's own chip (if
      present) highlighted, plus the real yes/no answer.
    """
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) / 2
    phase = round_data["phase"]
    chip_font = _font(FONT_PATH, CHIP_FONT_SIZE)

    if phase == "sequence":
        title = "MEMORIZE THIS SEQUENCE"
        entries = [(icon.upper(), CARD_BG, TEXT_COLOR) for icon in round_data["sequence"]]
        _chip_row(draw, cy_mid, entries, chip_font)
    elif phase == "question":
        title = "WAS THIS IN THE SEQUENCE?"
        target_font = _font(FONT_BOLD_PATH, VALUE_FONT_SIZE)
        entries = [(round_data["target"].upper(), PLAYER_ACCENT, PLAYER_ACCENT_TEXT)]
        _chip_row(draw, cy_mid, entries, target_font, pad_x=40, pad_y=26)
    else:  # reveal
        title = "THE SEQUENCE"
        target = round_data["target"]
        entries = [
            (icon.upper(), REVEAL_BG if icon == target else CARD_BG, REVEAL_TEXT if icon == target else TEXT_COLOR)
            for icon in round_data["sequence"]
        ]
        _chip_row(draw, cy_mid - 70, entries, chip_font)
        answer_font = _font(FONT_BOLD_PATH, VALUE_FONT_SIZE)
        answer_label = f"{target.upper()} -- {round_data['correct_answer'].upper()}"
        _chip_row(draw, cy_mid + 90, [(answer_label, REVEAL_BG, REVEAL_TEXT)], answer_font, pad_x=40, pad_y=26)

    label_font = _font(FONT_PATH, LABEL_FONT_SIZE)
    tw = draw.textlength(title, font=label_font)
    draw.text((WIDTH / 2 - tw / 2, cy0), title, font=label_font, fill=DIM_TEXT)
    return frame


def _render_item_grid_card(items: tuple, title: str, highlight: str | None) -> Image.Image:
    """odd_one_out / guess_the_connection share this shape: a row of
    item chips, plain until revealed, at which point `highlight` (the
    odd one out, or None for guess_the_connection -- that game's answer
    is the connection itself, not one of the shown items) gets the
    reveal accent."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) / 2
    chip_font = _font(FONT_PATH, CHIP_FONT_SIZE)

    entries = [
        (item.upper(), REVEAL_BG if item == highlight else CARD_BG, REVEAL_TEXT if item == highlight else TEXT_COLOR)
        for item in items
    ]
    _chip_row(draw, cy_mid, entries, chip_font, pad_x=36, pad_y=22)

    label_font = _font(FONT_PATH, LABEL_FONT_SIZE)
    tw = draw.textlength(title, font=label_font)
    draw.text((WIDTH / 2 - tw / 2, cy0), title, font=label_font, fill=DIM_TEXT)
    return frame


def _render_single_scene_card(subject: str, scene: dict, phase_label: str) -> Image.Image:
    """spot_the_difference's "study this" / "here's the new version"
    beats -- ONE scene's full attribute list, nothing hidden (there's
    nothing to hide yet; the challenge is remembering this against the
    scene shown next, not reading anything off this card)."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()

    subject_font = _font(FONT_BOLD_PATH, NAME_FONT_SIZE)
    title = subject.upper() if not phase_label else f"{subject.upper()} -- {phase_label.upper()}"
    tw = draw.textlength(title, font=subject_font)
    draw.text((WIDTH / 2 - tw / 2, cy0), title, font=subject_font, fill=TEXT_COLOR)

    row_font = _font(FONT_PATH, ROW_FONT_SIZE)
    attrs = list(scene)
    row_top = cy0 + 110
    row_h = 64
    row_gap = 16
    row_w = 640
    row_x = WIDTH / 2 - row_w / 2

    for i, attr in enumerate(attrs):
        y = row_top + i * (row_h + row_gap)
        draw.rounded_rectangle([row_x, y, row_x + row_w, y + row_h], radius=12, fill=CARD_BG)
        label = f"{attr}: {scene[attr]}"
        draw.text((row_x + 24, y + (row_h - ROW_FONT_SIZE) / 2 - 4), label, font=row_font, fill=TEXT_COLOR)
    return frame


def _render_what_changed_card(round_data: dict, revealed: bool) -> Image.Image:
    """The reveal beat's before/after comparison -- both scenes side by
    side, the changed row highlighted only once revealed. Not used
    before the reveal (the two study/compare beats each show one full
    scene alone via _render_single_scene_card, per section 30 Game Type
    D's actual flow -- study scene 1, then compare scene 2 against
    memory, not a side-by-side table the whole way through)."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    cx0, cy0, cx1, cy1 = _content_area()

    subject_font = _font(FONT_BOLD_PATH, NAME_FONT_SIZE)
    subject = round_data["subject"].upper()
    sw = draw.textlength(subject, font=subject_font)
    draw.text((WIDTH / 2 - sw / 2, cy0), subject, font=subject_font, fill=DIM_TEXT)

    before, after = round_data["before"], round_data["after"]
    changed = round_data.get("changed_attribute")
    attrs = list(before)
    row_font = _font(FONT_PATH, ROW_FONT_SIZE)
    header_font = _font(FONT_BOLD_PATH, ATTR_LABEL_FONT_SIZE)
    row_top = cy0 + 100
    row_h = 64
    row_gap = 16
    col_w = (cx1 - cx0 - 60) / 2
    col_a_x, col_b_x = cx0, cx0 + col_w + 60

    draw.text((col_a_x, row_top - 46), "BEFORE", font=header_font, fill=DIM_TEXT)
    draw.text((col_b_x, row_top - 46), "AFTER", font=header_font, fill=DIM_TEXT)

    for i, attr in enumerate(attrs):
        y = row_top + i * (row_h + row_gap)
        is_changed = revealed and attr == changed
        bg = REVEAL_BG if is_changed else CARD_BG_DIM
        text_color = REVEAL_TEXT if is_changed else TEXT_COLOR
        draw.rounded_rectangle([col_a_x, y, col_a_x + col_w, y + row_h], radius=12, fill=bg)
        draw.text((col_a_x + 20, y + (row_h - ROW_FONT_SIZE) / 2 - 4), f"{attr}: {before[attr]}", font=row_font, fill=text_color)
        draw.rounded_rectangle([col_b_x, y, col_b_x + col_w, y + row_h], radius=12, fill=bg)
        draw.text((col_b_x + 20, y + (row_h - ROW_FONT_SIZE) / 2 - 4), f"{attr}: {after[attr]}", font=row_font, fill=text_color)
    return frame


def _render_higher_or_lower_frame(segment: dict, round_data: dict) -> Image.Image:
    state = "player" if segment["beat"] == "think" else segment["beat"]
    return _render_comparison_card(round_data, state)


def _render_spot_the_difference_frame(segment: dict, round_data: dict) -> Image.Image:
    if segment["beat"] == "reveal":
        return _render_what_changed_card(round_data, revealed=True)
    if "scene" in round_data:
        return _render_single_scene_card(round_data["subject"], round_data["scene"], round_data.get("phase", ""))
    return _render_text_card(segment["script_text"] or " ")


def _render_memory_challenge_frame(segment: dict, round_data: dict) -> Image.Image:
    return _render_memory_card(round_data)


def _render_odd_one_out_frame(segment: dict, round_data: dict) -> Image.Image:
    highlight = round_data.get("odd_one") if segment["beat"] == "reveal" else None
    return _render_item_grid_card(round_data["items"], "WHICH ONE DOESN'T BELONG?", highlight)


def _render_guess_the_connection_frame(segment: dict, round_data: dict) -> Image.Image:
    title = round_data["connection"].upper() if segment["beat"] == "reveal" else "WHAT'S THE CONNECTION?"
    return _render_item_grid_card(round_data["clues"], title, highlight=None)


# One dispatch entry per game-type module's own round_data shape -- new
# game types register here rather than growing a single function's
# if/elif chain, since each game type's round_data means something
# different (a pair of values, a before/after scene, an icon sequence).
# who_what_am_i and rapid_fire aren't registered here -- both attach no
# round_data at all (their beats are plain narration: a clue, a true/
# false statement), so they fall through to the plain text card below
# with no special-casing needed.
_GAME_TYPE_RENDERERS = {
    "higher_or_lower": _render_higher_or_lower_frame,
    "spot_the_difference": _render_spot_the_difference_frame,
    "memory_challenge": _render_memory_challenge_frame,
    "odd_one_out": _render_odd_one_out_frame,
    "guess_the_connection": _render_guess_the_connection_frame,
}


def _render_segment_frame(segment: dict, round_data: dict | None) -> Image.Image:
    """The one non-countdown visual for a segment -- used for every
    HOST_TIME beat and every non-countdown PLAYER_TIME beat alike, since
    a game type's own renderer already knows how to draw its "unrevealed"
    vs. "revealed" states from `segment["beat"]`/`round_data` alone."""
    renderer = _GAME_TYPE_RENDERERS.get(segment["game_type"])
    if renderer and round_data:
        return renderer(segment, round_data)
    return _render_text_card(segment["script_text"] or " ")


def _run_ffmpeg(args: list[str]) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    result = subprocess.run([ffmpeg_path, "-y", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")


def _image_clip(image: Image.Image, duration: float, out_path: Path, tmp_dir: Path, tag: str) -> Path:
    png_path = tmp_dir / f"{tag}.png"
    png_path.write_bytes(encode_png(image))
    _run_ffmpeg([
        "-loop", "1", "-i", str(png_path), "-t", f"{duration:.3f}",
        "-r", str(FPS), "-pix_fmt", "yuv420p", str(out_path),
    ])
    return out_path


def _silence_audio(duration: float, out_path: Path) -> Path:
    _run_ffmpeg([
        "-f", "lavfi", "-i", f"anullsrc=r=24000:cl=mono", "-t", f"{duration:.3f}",
        str(out_path),
    ])
    return out_path


def _concat(paths: list[Path], out_path: Path) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in paths:
            escaped = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        list_path = f.name
    try:
        _run_ffmpeg(["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", str(out_path)])
    finally:
        Path(list_path).unlink(missing_ok=True)


def render_episode(segments: list[dict], output_path: Path, voice_backend: str = "edge_tts") -> Path:
    """segments: the make_segment() dicts from a game-type module's
    generate_round() (or several rounds' worth, concatenated). Produces a
    single real, watchable MP4 -- one video clip + one audio clip per
    segment, each held for that segment's REAL duration (synthesized
    narration length for HOST_TIME, the segment's own duration_seconds
    for PLAYER_TIME), muxed together in order. This is the actual proof
    this project has used for every prior new format (Phase 11 quiz,
    Phase 16 game_night): watch the output, don't just trust the timeline
    math.
    """
    import json as json_module

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="family_game_render_") as tmp:
        tmp_dir = Path(tmp)
        video_clips: list[Path] = []
        audio_clips: list[Path] = []

        for i, segment in enumerate(segments):
            round_data = json_module.loads(segment["round_data_json"]) if segment["round_data_json"] else None

            if segment["kind"] == HOST_TIME:
                audio_path = tmp_dir / f"seg{i:03d}_audio.mp3"
                synthesize(segment["script_text"], audio_path, voice_backend)
                duration = audio_duration_seconds(audio_path)
                audio_clips.append(audio_path)

                frame = _render_segment_frame(segment, round_data)
                video_clips.append(_image_clip(frame, duration, tmp_dir / f"seg{i:03d}_video.mp4", tmp_dir, f"seg{i:03d}"))
                continue

            # PLAYER_TIME: real silence for exactly duration_seconds, never
            # derived from (nonexistent) narration -- the segment's own
            # explicit contract from pipeline/family_game/base.py.
            duration = segment["duration_seconds"]
            audio_path = _silence_audio(duration, tmp_dir / f"seg{i:03d}_audio.wav")
            audio_clips.append(audio_path)

            if segment["beat"] == "countdown":
                whole_seconds = max(1, math.floor(duration))
                sub_clips = []
                remaining = duration
                for n in range(whole_seconds, 0, -1):
                    # Every second but the last holds for exactly 1s; the
                    # last one absorbs whatever's left (duration isn't
                    # always a whole number) so the sub-clips sum to
                    # exactly `duration`, never overshoot it.
                    sub_duration = 1.0 if n > 1 else remaining
                    frame = _render_countdown_number(n)
                    sub_clips.append(_image_clip(frame, sub_duration, tmp_dir / f"seg{i:03d}_count{n}.mp4", tmp_dir, f"seg{i:03d}_count{n}"))
                    remaining -= sub_duration
                video_path = tmp_dir / f"seg{i:03d}_video.mp4"
                _concat(sub_clips, video_path)
                video_clips.append(video_path)
            else:
                frame = _render_segment_frame(segment, round_data)
                video_clips.append(_image_clip(frame, duration, tmp_dir / f"seg{i:03d}_video.mp4", tmp_dir, f"seg{i:03d}"))

        video_only = tmp_dir / "video_only.mp4"
        _concat(video_clips, video_only)
        audio_only = tmp_dir / "audio_only.wav"
        _concat_audio_mixed(audio_clips, audio_only, tmp_dir)

        _run_ffmpeg([
            "-i", str(video_only), "-i", str(audio_only),
            "-c:v", "copy", "-c:a", "aac", "-shortest", str(output_path),
        ])
    return output_path


def _concat_audio_mixed(paths: list[Path], out_path: Path, tmp_dir: Path) -> None:
    """Audio clips here are a mix of codecs (mp3 from edge_tts, wav from
    anullsrc) -- ffmpeg's concat DEMUXER requires matching codecs/stream
    params (voice.py's own _concat_audio relies on that, safe there
    because every clip comes from the same TTS backend). Re-encoding each
    clip to a common format first, then concatenating via the concat
    FILTER (not the demuxer) is the correct tool for a mixed-codec list.
    """
    normalized = []
    for i, p in enumerate(paths):
        norm_path = tmp_dir / f"norm_{i:03d}.wav"
        _run_ffmpeg(["-i", str(p), "-ar", "24000", "-ac", "1", str(norm_path)])
        normalized.append(norm_path)

    inputs: list[str] = []
    for p in normalized:
        inputs += ["-i", str(p)]
    filter_inputs = "".join(f"[{i}:a]" for i in range(len(normalized)))
    filter_complex = f"{filter_inputs}concat=n={len(normalized)}:v=0:a=1[a]"
    _run_ffmpeg([*inputs, "-filter_complex", filter_complex, "-map", "[a]", str(out_path)])


if __name__ == "__main__":
    from pipeline.family_game.higher_or_lower import generate_round

    round_, segments = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {round_['title']} -- answer: {round_['answer']}")
    out = render_episode(segments, PROJECT_ROOT / "assets" / "output" / "family_game_test.mp4")
    print(f"output: {out}")
