"""Stage 2 (visuals, programming template): a video's step sequence ->
a live-coding-style vertical video clip (code types in, changes between
steps, shows real output). See SPEC.md.
"""

from __future__ import annotations

import difflib
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pygments import lex
from pygments.lexers import PythonLexer, get_lexer_by_name
from pygments.styles import get_style_by_name
from pygments.token import Token
from pygments.util import ClassNotFound

from pipeline.brand import (
    CAPTION_MARGIN_V_RATIO_PORTRAIT,
    CAPTION_TEXT_HEIGHT_RATIO,
    INDIGO as BRAND_INDIGO,
    TEAL as BRAND_TEAL,
    TOP_SAFE_ZONE_RATIO,
    paste_gradient_rounded_rect,
)
from pipeline.rotation import pick_rotating
from pipeline.state import count_uploaded, get_video, get_video_steps, list_by_status, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"
FONT_PATH = PROJECT_ROOT / "assets" / "fonts" / "JetBrainsMono-Regular.ttf"

WIDTH, HEIGHT = 1080, 1920
FPS = 30
TYPING_CHARS_PER_SEC = 15  # within the 12-18 chars/sec target range
MAX_TYPING_FRACTION = 0.7  # typing never eats more than 70% of a step's slice
MIN_TYPING_SECONDS = 0.3
MIN_HOLD_SECONDS = 0.5
FLASH_SECONDS = 0.35  # border flash cueing "the code just changed", steps 2+
FONT_SIZE = 34
MIN_FONT_SIZE = 20
MAX_FONT_SIZE = 64
OUTPUT_FONT_SIZE = 26

PANEL_MARGIN_X = 60
PANEL_PADDING = 48
PANEL_RADIUS = 28
TITLEBAR_HEIGHT = 56
# Flash ring / tab chrome stay FIXED across every theme, same reasoning
# as the brand gradient border: they're BiteBits' own chrome, not the
# editor's content area, so they shouldn't shift when the syntax theme
# does. Real monokai keyword-cyan value, kept as-is regardless of theme.
FLASH_COLOR = (102, 217, 239)
FLASH_OFFSET = 12  # bigger than BRAND_BORDER_WIDTH so the flash ring stays visible outside it


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _darken(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, int(c * factor)) for c in rgb)


def _blend(rgb1: tuple[int, int, int], rgb2: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(rgb1[i] + t * (rgb2[i] - rgb1[i])) for i in range(3))


def _build_theme(name: str, pygments_style: str, output_hex: str) -> dict:
    """Derives the panel's chrome colors from the real pygments style
    object instead of hand-tuning ~4 constants per theme -- verified
    against monokai's own existing hand-picked values before trusting
    this for the other 4 (frame/divider/label all landed within a few
    RGB units of the original hand-tuned constants). Only the "output
    text" green needs picking by hand per theme -- pygments styles don't
    tag any one token as canonically "the terminal-output color", so
    this pulls each theme's own real green from its palette (verified
    directly against pygments' token definitions, not guessed): monokai
    a6e22e, dracula 50fa7b, nord a3be8c, one-dark 98C379, solarized-dark
    859900.
    """
    style = get_style_by_name(pygments_style)
    bg = _hex_to_rgb(style.background_color)
    text = _hex_to_rgb(style.style_for_token(Token.Text)["color"] or "ffffff")
    return {
        "name": name,
        "pygments_style": pygments_style,
        "panel_bg": bg,
        "frame_bg": _darken(bg, 0.5),
        "divider_color": _blend(bg, text, 0.10),
        "output_label_color": _blend(bg, text, 0.55),
        "output_text_color": _hex_to_rgb(output_hex),
        "text_color": text,
    }


CODE_THEMES = [
    _build_theme("monokai", "monokai", "a6e22e"),
    _build_theme("dracula", "dracula", "50fa7b"),
    _build_theme("nord", "nord", "a3be8c"),
    _build_theme("one-dark", "one-dark", "98C379"),
    _build_theme("solarized-dark", "solarized-dark", "859900"),
]
_CODE_THEMES_BY_NAME = {t["name"]: t for t in CODE_THEMES}
# 5 themes, exclude the last 2 -- a 15-video window (right for the
# 18-item hook pool) would make this exclusion a permanent no-op on a
# pool this small. Leaves 3 real candidates every pick.
THEME_ROTATION_WINDOW = 2


def pick_code_theme() -> dict:
    name = pick_rotating("code_theme", [t["name"] for t in CODE_THEMES], THEME_ROTATION_WINDOW)
    return _CODE_THEMES_BY_NAME[name]

# Brand identity, replacing the generic dark-mode terminal skin every
# coding-tips channel uses — teal-to-indigo gradient border + brand mark +
# filename tab instead of "●●●" traffic lights. Colors come from
# pipeline/brand.py, shared with assemble.py's CTA badge.
BRAND_BORDER_WIDTH = 6
BRAND_MARK_SIZE = 32
TAB_BG = (54, 55, 48)
TAB_TEXT_COLOR = (214, 214, 204)
TAB_LABELS = {
    "python": "main.py",
    "javascript": "script.js",
    "typescript": "script.ts",
    "bash": "script.sh",
    "java": "Main.java",
    "c": "main.c",
    "cpp": "main.cpp",
    "go": "main.go",
    "rust": "main.rs",
    "sql": "query.sql",
}
DEFAULT_TAB_LABEL = "main.txt"

# Human-like typing variance: occasional brief pauses, occasional short
# bursts, rather than one constant reveal rate — total typing_frames stays
# exactly what step timing already computed, only the per-frame pacing
# within that budget varies.
TYPING_PAUSE_CHANCE = 0.12
TYPING_BURST_CHANCE = 0.10


def _pick_lexer(language: str | None):
    # pygments' generic guess_lexer() has near-zero confidence on short
    # (2-6 line) snippets with no distinctive markers — every real
    # code_snippet from plan.py scored 0.0 across candidate lexers, so
    # heuristic guessing isn't viable here. plan.py's LANGUAGE field (a
    # closed vocabulary the LLM fills in, since it already knows what it
    # wrote) is the reliable source instead. Fall back to Python only for
    # rows created before LANGUAGE existed in the schema.
    if language:
        try:
            return get_lexer_by_name(language)
        except ClassNotFound:
            pass
    return PythonLexer()


def _flatten_tokens(code: str, language: str | None, theme: dict) -> list[tuple[str, tuple[int, int, int]]]:
    lexer = _pick_lexer(language)
    style = get_style_by_name(theme["pygments_style"])
    default_color = theme["text_color"]

    chars: list[tuple[str, tuple[int, int, int]]] = []
    for token_type, value in lex(code, lexer):
        style_def = style.style_for_token(token_type)
        hex_color = style_def["color"]
        color = (
            tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
            if hex_color
            else default_color
        )
        for ch in value:
            chars.append((ch, color))
    while chars and chars[-1][0] in ("\n", " "):
        chars.pop()
    return chars


def _line_char_units(line: list[tuple[str, tuple[int, int, int]]]) -> int:
    """Effective width in monospace-character units — a tab (real code
    indentation, e.g. gofmt) occupies 4 columns, not 1."""
    return sum(4 if ch == "\t" else 1 for ch, _ in line)


def _layout_lines(chars: list[tuple[str, tuple[int, int, int]]]) -> list[list[tuple[str, tuple[int, int, int]]]]:
    lines: list[list[tuple[str, tuple[int, int, int]]]] = [[]]
    for ch, color in chars:
        if ch == "\n":
            lines.append([])
        else:
            lines[-1].append((ch, color))
    return lines


def _reveal_schedule(total_chars: int, typing_frames: int) -> list[int]:
    """Per-frame cumulative reveal count with natural variance (small
    random pauses, occasional short bursts) instead of a constant rate —
    still hits exactly total_chars by the final frame, so the outer
    typing_frames budget (tied to narration duration) is unaffected.
    """
    if typing_frames <= 0:
        return []
    if total_chars <= 0:
        return [0] * typing_frames

    weights = []
    for _ in range(typing_frames):
        r = random.random()
        if r < TYPING_PAUSE_CHANCE:
            weights.append(random.uniform(0.15, 0.4))
        elif r < TYPING_PAUSE_CHANCE + TYPING_BURST_CHANCE:
            weights.append(random.uniform(2.0, 3.5))
        else:
            weights.append(random.uniform(0.8, 1.2))

    cumulative = []
    running = 0.0
    for w in weights:
        running += w
        cumulative.append(running)
    total_weight = cumulative[-1]

    schedule = [min(total_chars, round(total_chars * cw / total_weight)) for cw in cumulative]
    schedule[-1] = total_chars
    for i in range(1, len(schedule)):
        if schedule[i] < schedule[i - 1]:
            schedule[i] = schedule[i - 1]
    return schedule


def _line_texts(lines: list[list[tuple[str, tuple[int, int, int]]]]) -> list[str]:
    return ["".join(ch for ch, _ in line) for line in lines]


def _static_line_indices(prev_lines, new_lines) -> set[int]:
    """Row indices into new_lines that are byte-identical to a line in
    the previous step and should render fully from frame 0, not animate.
    Real bug this fixes: every step transition used to clear and retype
    the WHOLE panel even when only one or two lines actually changed
    (confirmed on a real render: three steps sharing near-identical code
    each retyped "public class Main {" from scratch). Diffed on plain
    text per line (not the raw code_snippet string) so this can never
    disagree with what _layout_lines actually produced -- rendering and
    diffing read the exact same line list.
    """
    if prev_lines is None:
        return set()
    matcher = difflib.SequenceMatcher(None, _line_texts(prev_lines), _line_texts(new_lines), autojunk=False)
    static: set[int] = set()
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            static.update(range(j1, j2))
    return static


def _build_line_reveal_schedule(lines, static_indices: set[int], typing_frames: int) -> list[list[int]]:
    """Per-frame list of per-line reveal counts. Static (unchanged) lines
    are fully revealed on every frame of this step -- nothing to animate,
    they were already on screen. Only the changed/new lines actually type
    up, sharing _reveal_schedule's natural-pacing curve but scoped to
    just their own character budget -- less to type when less actually
    changed, not a fixed-size animation regardless of how small the edit
    was.
    """
    full_lengths = [len(line) for line in lines]
    changed_indices = [i for i in range(len(lines)) if i not in static_indices]
    changed_total = sum(full_lengths[i] for i in changed_indices)
    cumulative_schedule = _reveal_schedule(changed_total, typing_frames)

    frames: list[list[int]] = []
    for cumulative in cumulative_schedule:
        counts = [full_lengths[i] if i in static_indices else 0 for i in range(len(lines))]
        remaining = cumulative
        for i in changed_indices:
            take = min(full_lengths[i], remaining)
            counts[i] = take
            remaining -= take
            if remaining <= 0:
                break
        frames.append(counts)
    return frames


def _draw_code(draw, lines, line_reveal_counts, font, char_width, line_height, x0, y0, show_cursor):
    """line_reveal_counts: one entry per line, how many of that line's
    chars to draw -- a static (unchanged-from-previous-step) line passes
    its full length every frame; a line still typing passes a count that
    grows frame to frame. Replaces the old single flat reveal_count that
    consumed the whole panel's chars in one sequential cursor sweep,
    which is what forced every step transition to clear and retype the
    entire panel even when only one line actually changed.
    """
    def line_width(line, count):
        return char_width * _line_char_units(line[:count])

    cursor_pos = None
    for row, line in enumerate(lines):
        y = y0 + row * line_height
        x = x0
        count = line_reveal_counts[row]
        for ch, color in line[:count]:
            if ch == "\t":
                # tabs (real code indentation, e.g. gofmt) have no visible
                # glyph in a monospace font — advance the cursor, don't draw.
                x += char_width * 4
            else:
                draw.text((x, y), ch, font=font, fill=color)
                x += char_width
        if cursor_pos is None and count < len(line):
            cursor_pos = (x, y)

    if cursor_pos is None and lines:
        last_row = len(lines) - 1
        cursor_pos = (
            x0 + line_width(lines[last_row], line_reveal_counts[last_row]),
            y0 + last_row * line_height,
        )

    if show_cursor and cursor_pos is not None:
        cx, cy = cursor_pos
        draw.rectangle([cx, cy, cx + char_width * 0.6, cy + line_height * 0.85], fill=(248, 248, 242))


def _render_step_frame(
    lines,
    line_reveal_counts: list[int],
    output_text: str | None,
    font,
    output_font,
    char_width: float,
    line_height: int,
    output_line_height: int,
    show_cursor: bool,
    flash: bool,
    layout: dict,
) -> Image.Image:
    theme = layout["theme"]
    frame = Image.new("RGB", (WIDTH, HEIGHT), theme["frame_bg"])
    draw = ImageDraw.Draw(frame)

    panel_x, panel_y = layout["panel_x"], layout["panel_y"]
    panel_w, panel_h = layout["panel_w"], layout["panel_h"]
    code_area_h = layout["code_area_h"]
    has_output_area = layout["has_output_area"]

    if flash:
        draw.rounded_rectangle(
            [panel_x - FLASH_OFFSET, panel_y - FLASH_OFFSET, panel_x + panel_w + FLASH_OFFSET, panel_y + panel_h + FLASH_OFFSET],
            radius=PANEL_RADIUS + FLASH_OFFSET,
            fill=FLASH_COLOR,
        )
    paste_gradient_rounded_rect(
        frame,
        (
            panel_x - BRAND_BORDER_WIDTH, panel_y - BRAND_BORDER_WIDTH,
            panel_x + panel_w + BRAND_BORDER_WIDTH, panel_y + panel_h + BRAND_BORDER_WIDTH,
        ),
        PANEL_RADIUS + BRAND_BORDER_WIDTH,
        BRAND_TEAL, BRAND_INDIGO,
    )
    draw.rounded_rectangle(
        [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
        radius=PANEL_RADIUS,
        fill=theme["panel_bg"],
    )

    # Brand mark + filename tab, replacing generic "●●●" traffic lights —
    # reads as this channel's own chrome, not the same terminal skin every
    # coding-tips channel uses.
    mark_x0 = panel_x + PANEL_PADDING
    mark_y0 = panel_y + (TITLEBAR_HEIGHT - BRAND_MARK_SIZE) // 2
    paste_gradient_rounded_rect(
        frame,
        (mark_x0, mark_y0, mark_x0 + BRAND_MARK_SIZE, mark_y0 + BRAND_MARK_SIZE),
        8, BRAND_TEAL, BRAND_INDIGO,
    )
    mark_bbox = draw.textbbox((0, 0), "B", font=font)
    mark_w, mark_h = mark_bbox[2] - mark_bbox[0], mark_bbox[3] - mark_bbox[1]
    draw.text(
        (mark_x0 + (BRAND_MARK_SIZE - mark_w) / 2 - mark_bbox[0], mark_y0 + (BRAND_MARK_SIZE - mark_h) / 2 - mark_bbox[1]),
        "B", font=font, fill=(255, 255, 255),
    )

    tab_label = layout["tab_label"]
    tab_bbox = draw.textbbox((0, 0), tab_label, font=output_font)
    tab_text_w, tab_text_h = tab_bbox[2] - tab_bbox[0], tab_bbox[3] - tab_bbox[1]
    tab_pad_x, tab_h = 14, 30
    tab_x0 = mark_x0 + BRAND_MARK_SIZE + 14
    tab_y0 = panel_y + (TITLEBAR_HEIGHT - tab_h) // 2
    draw.rounded_rectangle(
        [tab_x0, tab_y0, tab_x0 + tab_text_w + 2 * tab_pad_x, tab_y0 + tab_h],
        radius=8, fill=TAB_BG,
    )
    draw.text(
        (tab_x0 + tab_pad_x - tab_bbox[0], tab_y0 + (tab_h - tab_text_h) / 2 - tab_bbox[1]),
        tab_label, font=output_font, fill=TAB_TEXT_COLOR,
    )

    # Series-branding episode badge, right-aligned in the title bar
    # (mirroring the brand mark + tab on the left) -- a real running
    # count of prior uploaded programming videos, not a placeholder.
    # Themed to match the current code theme rather than a fixed color,
    # same reasoning as everything else in the panel's chrome.
    episode_number = layout.get("episode_number")
    if episode_number is not None:
        ep_label = f"EP {episode_number}"
        ep_bbox = draw.textbbox((0, 0), ep_label, font=output_font)
        ep_text_w, ep_text_h = ep_bbox[2] - ep_bbox[0], ep_bbox[3] - ep_bbox[1]
        ep_pad_x, ep_h = 14, 30
        ep_x1 = panel_x + panel_w - PANEL_PADDING
        ep_x0 = ep_x1 - (ep_text_w + 2 * ep_pad_x)
        ep_y0 = panel_y + (TITLEBAR_HEIGHT - ep_h) // 2
        draw.rounded_rectangle(
            [ep_x0, ep_y0, ep_x1, ep_y0 + ep_h],
            radius=8, fill=theme["frame_bg"],
        )
        draw.text(
            (ep_x0 + ep_pad_x - ep_bbox[0], ep_y0 + (ep_h - ep_text_h) / 2 - ep_bbox[1]),
            ep_label, font=output_font, fill=theme["output_text_color"],
        )

    text_x0 = panel_x + PANEL_PADDING
    text_y0 = panel_y + TITLEBAR_HEIGHT + PANEL_PADDING // 2
    _draw_code(draw, lines, line_reveal_counts, font, char_width, line_height, text_x0, text_y0, show_cursor)

    if has_output_area:
        divider_y = panel_y + code_area_h
        draw.line(
            [panel_x + PANEL_PADDING // 2, divider_y, panel_x + panel_w - PANEL_PADDING // 2, divider_y],
            fill=theme["divider_color"],
            width=2,
        )
        label_y = divider_y + 14
        draw.text((text_x0, label_y), "OUTPUT", font=output_font, fill=theme["output_label_color"])
        if output_text:
            # Defensive, regardless of what's stored upstream: a literal
            # two-character "\n" is never real terminal output, it's a
            # line break that failed to become one. Never draw it as text.
            normalized = output_text.replace("\\n", "\n")
            out_y = label_y + output_line_height
            for line in normalized.splitlines():
                draw.text((text_x0, out_y), line, font=output_font, fill=theme["output_text_color"])
                out_y += output_line_height

    return frame


def render_multi_step(
    steps: list[dict], output_path: Path, language: str | None, episode_number: int | None = None
) -> tuple[Path, str]:
    """steps: ordered list of {"code_snippet", "output_text", "duration"}.
    Each step's duration comes from its already-synthesized narration audio
    (see voice.py's _voice_steps) — the visual switches to the next step
    exactly when that audio segment starts, so the concatenated result is
    frame-accurate against the concatenated narration, not approximate.
    episode_number: real running count of prior uploaded programming
    videos + 1 (see state.py's count_uploaded) -- renders as a small
    series-branding badge in the title bar. None skips the badge (e.g.
    a throwaway test render with no real video_id behind it).
    Returns (output_path, theme_name) -- the caller persists theme_name for
    per-video attribution (see state.py's code_theme column).
    """
    theme = pick_code_theme()
    step_lines = [_flatten_tokens(s["code_snippet"] or "", language, theme) for s in steps]
    step_lines = [_layout_lines(chars) for chars in step_lines]

    max_cols = max((_line_char_units(line) for lines in step_lines for line in lines), default=0)
    max_code_lines = max((len(lines) for lines in step_lines), default=1)
    max_output_lines = max(
        (len((s["output_text"] or "").replace("\\n", "\n").splitlines()) for s in steps),
        default=0,
    )
    has_output_area = max_output_lines > 0

    # The code panel has to stay clear of two fixed zones it doesn't
    # otherwise know about: a top title/branding strip, and the caption
    # burn-in zone (captions.py) near the bottom. Real bug this fixes: the
    # panel used to be vertically centered with unbounded height (no cap
    # on code line count) and ran straight into the caption zone for
    # anything past a handful of lines — a many-line snippet's panel
    # bottom edge could land 300-500px below where captions render,
    # captions and code drawing on top of each other. CAPTION_MARGIN_V_RATIO_PORTRAIT
    # + CAPTION_TEXT_HEIGHT_RATIO come from pipeline/brand.py, the same
    # source captions.py itself uses, so the two can't drift apart.
    top_safe_margin = round(HEIGHT * TOP_SAFE_ZONE_RATIO)
    caption_zone_top = HEIGHT - round(HEIGHT * CAPTION_MARGIN_V_RATIO_PORTRAIT) - round(min(WIDTH, HEIGHT) * CAPTION_TEXT_HEIGHT_RATIO)
    available_panel_h = caption_zone_top - top_safe_margin

    # Search from MAX_FONT_SIZE down to the first (largest) size that fits
    # BOTH the frame width (long lines) and this vertical budget (many
    # lines) — starting from a small fixed FONT_SIZE and only ever
    # shrinking meant short code (2-3 lines) rendered tiny with a mostly-
    # empty panel and huge dead space around it (real, reported: "the
    # code is too small and can't see shit"). Long content still shrinks
    # all the way to MIN_FONT_SIZE exactly as before.
    font_size = MAX_FONT_SIZE
    available_width = (WIDTH - 2 * PANEL_MARGIN_X) - 2 * PANEL_PADDING
    while True:
        font = ImageFont.truetype(str(FONT_PATH), font_size)
        char_width = font.getlength("M")
        ascent, descent = font.getmetrics()
        line_height = int((ascent + descent) * 1.35)
        output_font = ImageFont.truetype(str(FONT_PATH), int(OUTPUT_FONT_SIZE * font_size / FONT_SIZE))
        out_ascent, out_descent = output_font.getmetrics()
        output_line_height = int((out_ascent + out_descent) * 1.4)

        code_area_h = TITLEBAR_HEIGHT + max_code_lines * line_height + int(PANEL_PADDING * 1.5)
        output_area_h = 0
        if has_output_area:
            output_area_h = 14 + output_line_height * (max_output_lines + 1) + PANEL_PADDING // 2
        panel_h = code_area_h + output_area_h

        width_fits = max_cols == 0 or max_cols * char_width <= available_width
        height_fits = panel_h <= available_panel_h
        if (width_fits and height_fits) or font_size <= MIN_FONT_SIZE:
            break
        font_size = max(MIN_FONT_SIZE, font_size - 1)

    panel_w = min(WIDTH - 2 * PANEL_MARGIN_X, int(max_cols * char_width) + 2 * PANEL_PADDING)
    panel_x = (WIDTH - panel_w) // 2
    # Center within the available vertical band, not the whole frame — if
    # even MIN_FONT_SIZE still doesn't fit (a pathologically long
    # snippet), pin to the top of the band rather than let it drift back
    # down into the caption zone.
    panel_y = top_safe_margin + max(0, (available_panel_h - panel_h) // 2)

    layout = {
        "panel_x": panel_x,
        "panel_y": panel_y,
        "panel_w": panel_w,
        "panel_h": panel_h,
        "code_area_h": code_area_h,
        "has_output_area": has_output_area,
        "tab_label": TAB_LABELS.get(language, DEFAULT_TAB_LABEL),
        "theme": theme,
        "episode_number": episode_number,
    }

    # Diff each step's code against the PREVIOUS step's (real fix, not
    # cosmetic: confirmed on a real render that every transition cleared
    # and retyped the whole panel even for lines that never changed).
    # Step 0 has nothing to diff against -- everything in it is new.
    static_indices_per_step = [
        _static_line_indices(step_lines[i - 1] if i > 0 else None, step_lines[i])
        for i in range(len(step_lines))
    ]

    # Precompute per-step frame budgets (typing paced to content length,
    # not a flat window). Typing duration is based on CHANGED characters
    # only for steps after the first -- unchanged lines need no typing
    # time at all, so a small edit gets a short typing phase and a long
    # hold, not the other way around. Total frame count per step is still
    # fixed by the real narration duration either way, so the
    # concatenated video stays frame-accurate against the audio.
    step_plan = []
    for step, lines, static_indices in zip(steps, step_lines, static_indices_per_step):
        changed_chars = sum(len(line) for i, line in enumerate(lines) if i not in static_indices)
        duration = step["duration"]
        natural_typing = changed_chars / TYPING_CHARS_PER_SEC if changed_chars else MIN_TYPING_SECONDS
        typing_seconds = min(natural_typing, duration * MAX_TYPING_FRACTION)
        typing_seconds = max(MIN_TYPING_SECONDS, typing_seconds)
        hold_seconds = max(MIN_HOLD_SECONDS, duration - typing_seconds)
        typing_frames = max(1, round(typing_seconds * FPS))
        hold_frames = max(1, round(hold_seconds * FPS))
        step_plan.append({"typing_frames": typing_frames, "hold_frames": hold_frames})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="visuals_code_") as tmp:
        tmp_dir = Path(tmp)
        frame_idx = 0

        for step_i, (step, lines, plan, static_indices) in enumerate(
            zip(steps, step_lines, step_plan, static_indices_per_step)
        ):
            typing_frames = plan["typing_frames"]
            hold_frames = plan["hold_frames"]
            # Only cue a change with the border flash when something is
            # actually animating -- no flash (and no point-of-interest)
            # if this step's code is identical to the last one.
            flash_frames = round(FLASH_SECONDS * FPS) if step_i > 0 and len(static_indices) < len(lines) else 0
            normalized_output = (step["output_text"] or "").replace("\\n", "\n") or None
            full_reveal = [len(line) for line in lines]

            line_reveal_schedule = _build_line_reveal_schedule(lines, static_indices, typing_frames)
            for f in range(typing_frames):
                blink_on = (f // (FPS // 2)) % 2 == 0
                frame = _render_step_frame(
                    lines, line_reveal_schedule[f], None, font, output_font, char_width,
                    line_height, output_line_height, blink_on, f < flash_frames, layout,
                )
                frame.save(tmp_dir / f"{frame_idx:05d}.png")
                frame_idx += 1

            for h in range(hold_frames):
                blink_on = (h // (FPS // 2)) % 2 == 0
                frame = _render_step_frame(
                    lines, full_reveal, normalized_output, font, output_font, char_width,
                    line_height, output_line_height, blink_on, False, layout,
                )
                frame.save(tmp_dir / f"{frame_idx:05d}.png")
                frame_idx += 1

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError("ffmpeg not found on PATH")

        result = subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-framerate", str(FPS),
                "-i", str(tmp_dir / "%05d.png"),
                # See assemble.py/visuals_game.py's matching comment (real
                # 2026-09-12 quality complaint) -- no encode in this
                # pipeline set a quality target before, defaulting to
                # libx264's own CRF 23/preset medium. CRF 18 is close to
                # visually lossless; "slow" is the right trade for a batch
                # job with no real-time constraint.
                "-c:v", "libx264",
                "-preset", "slow",
                "-crf", "18",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")

    return output_path, theme["name"]


def visuals_code(video_id: str) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if video["template"] != "programming":
        raise ValueError(f"visuals_code only applies to the programming template, got {video['template']!r}")

    steps = get_video_steps(video_id)
    if not steps:
        raise ValueError(
            f"video {video_id} has no video_steps — regenerate it with the current plan.py "
            "(older rows predate the step-based format)"
        )
    missing_duration = [s["step_index"] for s in steps if not s["duration"]]
    if missing_duration:
        raise ValueError(
            f"video {video_id} steps {missing_duration} have no duration — run voice() first; "
            "each step's visual duration comes from its own synthesized audio"
        )

    # This video will BE the next episode once it's actually uploaded --
    # +1 on top of the real count of already-uploaded ones.
    episode_number = count_uploaded("programming") + 1

    output_path = OUTPUT_DIR / f"{video_id}_code.mp4"
    _, theme_name = render_multi_step(steps, output_path, language=video["language"], episode_number=episode_number)

    update_video(video_id, status="visuals_ready", video_path=str(output_path), code_theme=theme_name)
    return str(output_path)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        candidates = [v for v in list_by_status("voiced") if v["template"] == "programming"]
        if not candidates:
            raise SystemExit(
                "no voiced programming videos in state.db — run plan.py then voice.py first"
            )
        video_id_arg = candidates[0]["id"]

    path = visuals_code(video_id_arg)
    print(f"video_id: {video_id_arg}")
    print(f"output:   {path}")
