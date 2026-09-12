"""Visuals for the game-night longform track (Phase 16) -- horizontal
1920x1080, same panel/border chrome as visuals_quiz.py for brand
consistency (reused via render_text.py, not re-implemented). Every beat
(intro/rule/countdown/gameplay/suspense/reveal) renders from real,
already-decided data -- round_data_json -- nothing here re-derives a
game outcome, it only draws what pipeline/games/ and plan_game.py
already computed.

No lives/points HUD and no win/loss (green/red) coloring -- an earlier
version had both, simulating a "contestant" who won or lost each round.
Cut after watching a real rendered test episode: it read as a fake AI
playing the game by itself. Every reveal now uses one neutral highlight
color -- it's just marking "this is the real answer", not judging
anyone. See ROADMAP.md Phase 16.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from pipeline.brand import INDIGO as BRAND_INDIGO, TEAL as BRAND_TEAL, paste_gradient_rounded_rect
from pipeline.render_text import draw_centered_lines, encode_png, fit_multiline, fit_single_line, wrap_text
from pipeline.state import get_video, get_video_steps, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"
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
# Same reasoning as visuals_quiz.py: captions.py burns in a bottom strip
# for landscape frames, the panel must stay clear of it.
CAPTION_SAFE_HEIGHT = 220
SAFE_MARGIN_FRACTION = 0.05

PANEL_BOX = (PANEL_MARGIN_X, TOP_MARGIN, WIDTH - PANEL_MARGIN_X, HEIGHT - CAPTION_SAFE_HEIGHT)

ROUND_LABEL_FONT_SIZE = 28
TEXT_FONT_SIZE = 54
MIN_TEXT_FONT_SIZE = 28
VALUE_FONT_SIZE = 68
MIN_VALUE_FONT_SIZE = 32
NAME_FONT_SIZE = 40
MIN_NAME_FONT_SIZE = 24
CHIP_FONT_SIZE = 32

TEXT_COLOR = (242, 242, 234)
DIM_TEXT = (147, 148, 138)
CARD_BG = (39, 40, 34)
CARD_BG_DIM = (30, 31, 27)
# The one "this is the real answer" highlight -- a muted brand-teal tint,
# deliberately not red/green, since nothing here is being judged right
# or wrong.
REVEAL_BG = (24, 74, 68)
REVEAL_TEXT = (198, 245, 235)

ROUND_LABELS = {
    "higher_or_lower": "HIGHER OR LOWER",
    "memory": "MEMORY",
    "what_changed": "WHAT CHANGED",
    "risk_or_safe": "RISK OR SAFE",
    "prediction": "PREDICTION",
}


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _text_center_y(draw, text, font, cy):
    """Baseline y that visually centers `text` on cy, same formula used
    throughout visuals_quiz.py's row rendering."""
    ascent, descent = font.getmetrics()
    return cy - (ascent + descent) / 2 - descent / 2 + descent


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


def _draw_round_label(draw: ImageDraw.ImageDraw, round_type: str | None) -> None:
    """Top-right, inside the panel -- which round this is, so a viewer
    scrubbing the video can tell rounds apart at a glance."""
    if round_type is None:
        return
    _, y0, x1, _ = PANEL_BOX
    label = ROUND_LABELS.get(round_type, round_type.upper())
    font = _font(FONT_BOLD_PATH, ROUND_LABEL_FONT_SIZE)
    w = draw.textlength(label, font=font)
    draw.text((x1 - PANEL_PADDING - w, y0 + PANEL_PADDING - 4), label, font=font, fill=DIM_TEXT)


def _content_area() -> tuple[int, int, int, int]:
    """The panel area below the round-label row, where beat-specific
    content actually draws."""
    x0, y0, x1, y1 = PANEL_BOX
    content_top = y0 + PANEL_PADDING + 50
    return x0 + PANEL_PADDING, content_top, x1 - PANEL_PADDING, y1 - PANEL_PADDING


def _render_text_beat(script_text: str, round_type: str | None) -> Image.Image:
    """intro/rule/countdown/suspense/outro beats -- a centered text card,
    same shape as visuals_quiz.py's intro/outro card."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    _draw_round_label(draw, round_type)

    cx0, cy0, cx1, cy1 = _content_area()
    max_width = int((cx1 - cx0) * (1 - SAFE_MARGIN_FRACTION))
    font, lines = fit_multiline(draw, script_text, FONT_PATH, TEXT_FONT_SIZE, MIN_TEXT_FONT_SIZE, max_width)
    ascent, descent = font.getmetrics()
    line_height = int((ascent + descent) * 1.4)
    total_h = len(lines) * line_height
    top_y = (cy0 + cy1) // 2 - total_h // 2
    draw_centered_lines(draw, lines, font, TEXT_COLOR, WIDTH // 2, top_y, line_height)
    return frame


def _chip_row(
    draw: ImageDraw.ImageDraw, cy: int, entries: list[tuple[str, tuple[int, int, int], tuple[int, int, int]]],
    font: ImageFont.FreeTypeFont, gap: int = 24, pad_x: int = 28, pad_y: int = 18,
) -> None:
    """A horizontal row of rounded-rect text chips, centered on the panel.
    entries: list of (label, bg_color, text_color)."""
    ascent, descent = font.getmetrics()
    h = ascent + descent + 2 * pad_y
    widths = [draw.textlength(label, font=font) + 2 * pad_x for label, _, _ in entries]
    total_w = sum(widths) + gap * max(0, len(entries) - 1)
    x = WIDTH / 2 - total_w / 2
    for (label, bg, text_color), w in zip(entries, widths):
        box = [x, cy - h / 2, x + w, cy + h / 2]
        draw.rounded_rectangle(box, radius=14, fill=bg)
        tw = draw.textlength(label, font=font)
        text_y = _text_center_y(draw, label, font, cy)
        draw.text((x + w / 2 - tw / 2, text_y), label, font=font, fill=text_color)
        x += w + gap


def _render_memory_beat(round_data: dict, phase: str, round_type: str) -> Image.Image:
    """Real bug fixed here (2026-09-12, caught by the owner watching the
    actual rendered episode): the old two-phase (question/reveal) version
    shared by every other round type showed the FULL icon sequence during
    the "was X one of them?" question -- the answer was sitting right
    there on screen the entire time, so the round tested nothing. It also
    never showed the sequence at all during the "rule" beat (the "watch
    closely" moment), since that beat_type fell through to a plain-text
    card instead of reaching this renderer in the first place.

    Three real phases now: "study" (the actual memorize moment -- shows
    the real sequence, no question yet), "recall" (the actual question --
    sequence hidden, only the target chip shows, so answering it requires
    genuinely remembering), "reveal" (sequence back, target chip shows
    the real answer)."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    _draw_round_label(draw, round_type)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) // 2

    show_sequence = phase in ("study", "reveal")
    if show_sequence:
        seq_font = _font(FONT_PATH, CHIP_FONT_SIZE)
        sequence = round_data["sequence"]
        seq_entries = [(icon.upper(), CARD_BG, TEXT_COLOR) for icon in sequence]
        _chip_row(draw, cy_mid - 90, seq_entries, seq_font)

    if phase == "study":
        return frame

    target_font = _font(FONT_BOLD_PATH, VALUE_FONT_SIZE)
    target_label = round_data["target"].upper()
    if phase == "recall":
        target_entries = [(f"{target_label}  ?", CARD_BG, TEXT_COLOR)]
        cy_target = cy_mid  # center it -- the sequence row above is hidden
    else:
        answer = round_data["correct_answer"].upper()
        target_entries = [(f"{target_label}  -  {answer}", REVEAL_BG, REVEAL_TEXT)]
        cy_target = cy_mid + 60
    _chip_row(draw, cy_target, target_entries, target_font, pad_x=40, pad_y=26)
    return frame


def _render_what_changed_beat(round_data: dict, revealed: bool, round_type: str) -> Image.Image:
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    _draw_round_label(draw, round_type)
    cx0, cy0, cx1, cy1 = _content_area()

    subject_font = _font(FONT_BOLD_PATH, NAME_FONT_SIZE)
    subject = round_data["subject"].upper()
    sw = draw.textlength(subject, font=subject_font)
    draw.text((WIDTH / 2 - sw / 2, cy0), subject, font=subject_font, fill=DIM_TEXT)

    row_font = _font(FONT_PATH, CHIP_FONT_SIZE)
    changed = round_data["changed_attribute"]
    before, after = round_data["before"], round_data["after"]
    attr_names = list(before)
    row_top = cy0 + 90
    row_h = 64
    row_gap = 14
    col_w = (cx1 - cx0 - 60) / 2
    col_a_x = cx0
    col_b_x = cx0 + col_w + 60

    header_font = _font(FONT_BOLD_PATH, 30)
    draw.text((col_a_x, row_top - 50), "BEFORE", font=header_font, fill=DIM_TEXT)
    draw.text((col_b_x, row_top - 50), "AFTER", font=header_font, fill=DIM_TEXT)

    for i, attr in enumerate(attr_names):
        y = row_top + i * (row_h + row_gap)
        is_changed_row = revealed and attr == changed
        bg = REVEAL_BG if is_changed_row else CARD_BG_DIM
        text_color = REVEAL_TEXT if is_changed_row else TEXT_COLOR
        label = attr.replace("_", " ").upper()

        draw.rounded_rectangle([col_a_x, y, col_a_x + col_w, y + row_h], radius=12, fill=bg)
        draw.text((col_a_x + 20, y + (row_h - CHIP_FONT_SIZE) / 2 - 6), f"{label}: {before[attr]}", font=row_font, fill=text_color)

        after_visible = revealed or attr != changed
        after_value = after[attr] if after_visible else "?"
        draw.rounded_rectangle([col_b_x, y, col_b_x + col_w, y + row_h], radius=12, fill=bg)
        draw.text((col_b_x + 20, y + (row_h - CHIP_FONT_SIZE) / 2 - 6), f"{label}: {after_value}", font=row_font, fill=text_color)
    return frame


def _render_risk_or_safe_beat(round_data: dict, revealed: bool, round_type: str) -> Image.Image:
    """SAFE is a static reference card (its value is already known, never
    revealed). RISKY is the only card with a real outcome to reveal --
    highlighted neutrally once the real weighted draw is known, labeled
    with what actually happened (HIT/MISS), not a win/loss judgment of
    anyone."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    _draw_round_label(draw, round_type)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) // 2

    win_pct = round(round_data["risk_win_probability"] * 100)
    risk_hits = round_data["risk_hits"]

    card_font = _font(FONT_BOLD_PATH, NAME_FONT_SIZE)
    sub_font = _font(FONT_PATH, CHIP_FONT_SIZE)
    card_w, card_h = 480, 220
    gap = 60
    total_w = 2 * card_w + gap
    x_safe = WIDTH / 2 - total_w / 2
    x_risky = x_safe + card_w + gap
    y = cy_mid - card_h / 2

    def draw_card(x, title, subtitle, bg):
        draw.rounded_rectangle([x, y, x + card_w, y + card_h], radius=18, fill=bg)
        tw = draw.textlength(title, font=card_font)
        draw.text((x + card_w / 2 - tw / 2, y + 40), title, font=card_font, fill=TEXT_COLOR)
        sw = draw.textlength(subtitle, font=sub_font)
        draw.text((x + card_w / 2 - sw / 2, y + 120), subtitle, font=sub_font, fill=DIM_TEXT)

    draw_card(x_safe, "SAFE", f"+{round_data['safe_points']} guaranteed", CARD_BG)
    risky_subtitle = f"{win_pct}% for +{round_data['risk_win_points']}"
    if revealed:
        risky_subtitle = f"{risky_subtitle} -- {'HIT' if risk_hits else 'MISS'}"
    draw_card(x_risky, "RISKY", risky_subtitle, REVEAL_BG if revealed else CARD_BG)
    return frame


def _render_comparison_beat(
    round_data: dict, revealed: bool, round_type: str,
    a_name_field: str, b_name_field: str, a_value_field: str, b_value_field: str, unit_field: str, question_label: str,
) -> Image.Image:
    """Shared layout for higher_or_lower and prediction -- both are a
    "known value" vs. "guess this one" versus card, just with different
    field names in round_data."""
    frame = _render_base_panel()
    draw = ImageDraw.Draw(frame)
    _draw_round_label(draw, round_type)
    cx0, cy0, cx1, cy1 = _content_area()
    cy_mid = (cy0 + cy1) // 2
    unit = round_data[unit_field]

    label_font = _font(FONT_PATH, 30)

    card_w, card_h = 560, 260
    gap = 80
    total_w = 2 * card_w + gap
    x_a = WIDTH / 2 - total_w / 2
    x_b = x_a + card_w + gap
    y = cy_mid - card_h / 2
    inner_max_w = int((card_w - 48) * (1 - SAFE_MARGIN_FRACTION))

    def centered_fit(text, x, y_, base_size, min_size, color, bold=True):
        """Shrinks text to fit the card width before centering -- a real
        bug this fixes: a long real subject name (e.g. "Empire State
        Building height") rendered past the card edge when this just
        centered at a fixed size instead of fitting first."""
        font, fitted = fit_single_line(draw, text, FONT_BOLD_PATH if bold else FONT_PATH, base_size, min_size, inner_max_w)
        w = draw.textlength(fitted, font=font)
        draw.text((x - w / 2, y_), fitted, font=font, fill=color)

    draw.rounded_rectangle([x_a, y, x_a + card_w, y + card_h], radius=18, fill=CARD_BG)
    centered_fit(round_data[a_name_field], x_a + card_w / 2, y + 40, NAME_FONT_SIZE, MIN_NAME_FONT_SIZE, TEXT_COLOR)
    centered_fit(f"~{round_data[a_value_field]:g} {unit}", x_a + card_w / 2, y + 120, VALUE_FONT_SIZE, MIN_VALUE_FONT_SIZE, TEXT_COLOR)

    if not revealed:
        draw.rounded_rectangle([x_b, y, x_b + card_w, y + card_h], radius=18, fill=CARD_BG_DIM)
        centered_fit(round_data[b_name_field], x_b + card_w / 2, y + 40, NAME_FONT_SIZE, MIN_NAME_FONT_SIZE, TEXT_COLOR)
        centered_fit("?", x_b + card_w / 2, y + 120, VALUE_FONT_SIZE, MIN_VALUE_FONT_SIZE, TEXT_COLOR)
    else:
        draw.rounded_rectangle([x_b, y, x_b + card_w, y + card_h], radius=18, fill=REVEAL_BG)
        centered_fit(round_data[b_name_field], x_b + card_w / 2, y + 40, NAME_FONT_SIZE, MIN_NAME_FONT_SIZE, REVEAL_TEXT)
        val_text = f"~{round_data[b_value_field]:g} {unit}"
        centered_fit(val_text, x_b + card_w / 2, y + 120, VALUE_FONT_SIZE, MIN_VALUE_FONT_SIZE, REVEAL_TEXT)

    label = question_label if not revealed else round_data["correct_answer"].upper()
    lw = draw.textlength(label, font=label_font)
    draw.text((WIDTH / 2 - lw / 2, y - 50), label, font=label_font, fill=DIM_TEXT)
    return frame


def _render_higher_or_lower_beat(round_data, revealed, round_type):
    return _render_comparison_beat(
        round_data, revealed, round_type,
        a_name_field="item_a_name", b_name_field="item_b_name",
        a_value_field="item_a_value", b_value_field="item_b_value",
        unit_field="unit", question_label="HIGHER OR LOWER?",
    )


def _render_prediction_beat(round_data, revealed, round_type):
    data = dict(round_data)
    data["item_a_name"] = "THRESHOLD"
    data["item_a_value"] = data["threshold_value"]
    data["item_b_name"] = data["subject_name"]
    data["item_b_value"] = data["actual_value"]
    return _render_comparison_beat(
        data, revealed, round_type,
        a_name_field="item_a_name", b_name_field="item_b_name",
        a_value_field="item_a_value", b_value_field="item_b_value",
        unit_field="unit", question_label="ABOVE OR BELOW?",
    )


# memory is deliberately NOT in this dict -- unlike every other round
# type here (a plain 2-phase question/reveal), it needs a real 3rd phase
# (the actual memorize moment) with content that's hidden, not just
# relabeled, during the question -- see _render_memory_beat's docstring
# for the real bug this fixes. Handled as its own branch in
# _render_beat_frame() below instead of forcing it through the shared
# revealed:bool signature.
_GAMEPLAY_RENDERERS = {
    "what_changed": _render_what_changed_beat,
    "risk_or_safe": _render_risk_or_safe_beat,
    "higher_or_lower": _render_higher_or_lower_beat,
    "prediction": _render_prediction_beat,
}

_MEMORY_PHASE_BY_BEAT = {"rule": "study", "gameplay": "recall", "reveal": "reveal"}


def _render_beat_frame(step: dict) -> Image.Image:
    round_type = step["round_type"]
    beat_type = step["beat_type"]
    round_data = json.loads(step["round_data_json"]) if step["round_data_json"] else None

    if round_type == "memory" and round_data and beat_type in _MEMORY_PHASE_BY_BEAT:
        return _render_memory_beat(round_data, _MEMORY_PHASE_BY_BEAT[beat_type], round_type)

    if beat_type in ("gameplay", "reveal") and round_type in _GAMEPLAY_RENDERERS and round_data:
        revealed = beat_type == "reveal"
        return _GAMEPLAY_RENDERERS[round_type](round_data, revealed, round_type)

    return _render_text_beat(step["script_text"], round_type)


def render_game_video(steps: list[dict], output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visuals_game_") as tmp:
        tmp_dir = Path(tmp)
        frame_idx = 0
        for step in steps:
            duration = step["duration"] or 0.0
            frame = _render_beat_frame(step)
            frame_bytes = encode_png(frame)
            for _ in range(max(1, round(duration * FPS))):
                (tmp_dir / f"{frame_idx:05d}.png").write_bytes(frame_bytes)
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


def visuals_game(video_id: str) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if video["template"] != "game_night":
        raise ValueError(f"visuals_game only applies to game_night, got {video['template']!r}")

    steps = get_video_steps(video_id)
    if not steps:
        raise ValueError(f"video {video_id} has no video_steps -- run plan_game_night() first")
    missing_duration = [s["step_index"] for s in steps if not s["duration"]]
    if missing_duration:
        raise ValueError(f"video {video_id} steps {missing_duration} have no duration -- run voice() first")

    output_path = OUTPUT_DIR / f"{video_id}_game.mp4"
    render_game_video(steps, output_path)

    update_video(video_id, status="visuals_ready", video_path=str(output_path))
    return str(output_path)


if __name__ == "__main__":
    import sys

    from pipeline.state import list_by_status

    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        candidates = [v for v in list_by_status("voiced") if v["template"] == "game_night"]
        if not candidates:
            raise SystemExit("no voiced game_night videos in state.db -- run plan_game.py then voice.py first")
        video_id_arg = candidates[0]["id"]

    path = visuals_game(video_id_arg)
    print(f"video_id: {video_id_arg}")
    print(f"output:   {path}")
