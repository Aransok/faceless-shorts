"""Shared ByteBits brand visual identity — colors + gradient helpers used
by both the programming-visuals editor chrome (visuals_code.py) and the
subscribe CTA badge (assemble.py), so the two don't drift out of sync by
each hand-rolling their own copy of the same brand colors.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

TEAL = (20, 184, 166)
INDIGO = (99, 102, 241)

# Shared vertical safe-zone geometry for portrait (Shorts) frames, so the
# code panel (visuals_code.py) and the caption burn-in (captions.py) agree
# on where the caption zone actually is instead of each guessing
# independently. Real bug this fixes: the code panel was vertically
# centered with unbounded height (no cap on code line count), while
# captions.py picked a fixed caption position with zero knowledge of the
# panel's actual size -- for anything past a handful of code lines the
# panel's bottom edge ran straight into the caption zone.
CAPTION_MARGIN_V_RATIO_PORTRAIT = 0.38  # ASS MarginV -- distance from the frame's bottom edge to the caption's baseline
CAPTION_TEXT_HEIGHT_RATIO = 110 / 1080  # rough vertical footprint of one caption line (active-word size + breathing room)
TOP_SAFE_ZONE_RATIO = 0.12  # keep panel content clear of the top title/branding zone too

# A per-pixel-column Python loop (the original approach here) is fine
# called once, but visuals_code.py and visuals_quiz.py call this on
# EVERY rendered video frame — thousands of times for a multi-minute
# video — so the loop must stay a small constant, not scale with the
# target width/height. Build a small strip once, let PIL's C-level
# resize scale it, regardless of how large the requested box is.
_GRADIENT_STRIP_SIZE = 256


def make_gradient_image(width: int, height: int, color_start=TEAL, color_end=INDIGO) -> Image.Image:
    width, height = max(1, width), max(1, height)
    strip = Image.new("RGB", (_GRADIENT_STRIP_SIZE, 1))
    draw = ImageDraw.Draw(strip)
    for x in range(_GRADIENT_STRIP_SIZE):
        t = x / (_GRADIENT_STRIP_SIZE - 1)
        color = tuple(int(color_start[i] + (color_end[i] - color_start[i]) * t) for i in range(3))
        draw.point((x, 0), fill=color)
    return strip.resize((width, height))


def paste_gradient_rounded_rect(
    frame: Image.Image, box, radius: int, color_start=TEAL, color_end=INDIGO, opacity: int = 255
) -> None:
    """Composites a gradient-filled rounded rect onto frame at box. Works
    for both an opaque RGB frame (blends against whatever's already
    there — visuals_code.py's editor chrome) and an RGBA frame with real
    transparency (assemble.py's CTA badge PNG) — alpha_composite for the
    latter so the transparent background outside the shape stays
    transparent rather than picking up an opaque black fringe.
    """
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=opacity)

    if frame.mode == "RGBA":
        gradient = make_gradient_image(w, h, color_start, color_end).convert("RGBA")
        gradient.putalpha(mask)
        frame.alpha_composite(gradient, (x0, y0))
    else:
        gradient = make_gradient_image(w, h, color_start, color_end)
        frame.paste(gradient, (x0, y0), mask)
