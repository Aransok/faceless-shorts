"""Generic PIL text-fitting/wrapping primitives, shared by every renderer
that draws text onto a fixed-size panel (visuals_quiz.py, visuals_game.py)
-- extracted out of visuals_quiz.py rather than re-implemented a second
time, same "extract once it's reused, don't fork a copy" call already
made for pipeline/rotation.py (pick_rotating, originally single-use in
approaches.py). No template-specific knowledge lives here.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
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


def fit_multiline(
    draw: ImageDraw.ImageDraw, text: str, font_path: Path, base_size: int, min_size: int, max_width: int
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """Shrinks font size in a loop, re-wrapping at each size, until every
    wrapped line fits within max_width -- word-wrapping alone isn't a
    safety net against a single long unbroken word/token, only shrinking
    (or shrinking down to min_size and re-wrapping) actually guarantees
    that.
    """
    size = base_size
    font = ImageFont.truetype(str(font_path), size)
    lines = wrap_text(draw, text, font, max_width)
    while size > min_size and max((draw.textlength(line, font=font) for line in lines), default=0) > max_width:
        size -= 2
        font = ImageFont.truetype(str(font_path), size)
        lines = wrap_text(draw, text, font, max_width)
    return font, lines


def fit_single_line(
    draw: ImageDraw.ImageDraw, text: str, font_path: Path, base_size: int, min_size: int, max_width: int
) -> tuple[ImageFont.FreeTypeFont, str]:
    """Shrinks font size until the (unwrapped) text fits on one line; if
    it still doesn't fit at min_size, truncates with an ellipsis as a
    last resort so it can never render past max_width.
    """
    size = base_size
    font = ImageFont.truetype(str(font_path), size)
    while size > min_size and draw.textlength(text, font=font) > max_width:
        size -= 2
        font = ImageFont.truetype(str(font_path), size)

    if draw.textlength(text, font=font) <= max_width:
        return font, text

    truncated = text
    while truncated and draw.textlength(truncated + "…", font=font) > max_width:
        truncated = truncated[:-1]
    return font, (truncated + "…") if truncated else "…"


def encode_png(frame: Image.Image) -> bytes:
    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    return buf.getvalue()


def draw_centered_lines(draw, lines, font, color, cx, top_y, line_height):
    for i, line in enumerate(lines):
        w = draw.textlength(line, font=font)
        draw.text((cx - w / 2, top_y + i * line_height), line, font=font, fill=color)
