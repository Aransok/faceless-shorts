"""The "Case File" look for facts / sauce_recipe Shorts (see STYLE.md).

Owner-approved 2026-10-31 from the style lab (scripts/style_lab, style
D). STYLE.md is the spec; every number here comes from it. Switched on
with VISUAL_STYLE=casefile.

How it plugs into the pipeline:
- plan.py appends prompt_block() and runs extract_fields() on the model
  output: per-beat TAG / TAG_LABEL go into each beat's keywords JSON,
  CASE_HEADER / CASE_DATE / STAMP into videos.style_json.
- visuals_facts.py cuts footage faster (SEGMENT_SECONDS), shows real
  Commons photos as evidence Polaroids (render_card_clip) and records
  the segment plan in style_json.
- assemble.py mixes voice + music only (no CTA overlay, no SFX) and
  records any music credit in style_json.
- captions.py calls render_final(): one Pillow pass that draws the
  footage effects, the case-file layer, the captions and the subscribe
  strip in the right stacking order, then copies the audio unchanged.
  Any failure there falls back to the normal ASS captions.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from pipeline.state import get_video, get_video_steps, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
MUSIC_DIR = PROJECT_ROOT / "assets" / "music" / "casefile"
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"

RENDERER_NAME = "casefile"
TEMPLATES = ("facts", "sauce_recipe")
W, H, FPS = 1080, 1920, 30

# visuals_facts.py pacing in this style (STYLE.md section 4)
SEGMENT_SECONDS = 2.5
CARD_SECONDS = 2.0
MAX_CARDS_PER_VIDEO = 3

# colors
RED = (255, 59, 48)
YELLOW = (255, 225, 77)
WHITE = (255, 255, 255)
PAPER = (236, 230, 214)
STAMP_RED = (214, 38, 38)
TAG_COLORS = (RED, YELLOW, WHITE)

# layout (y in px on the 1920-tall frame)
HEADER_Y = 132
TAG_Y = 400
TAG_LABEL_Y = 575
CARD_Y = 1005
STAMP_POS = (W / 2 + 110, 1095)
CAPTION_Y = 1460
CAPTION_MAX_W = 900
CTA_Y = 900

# timing
TAG_POP_SECONDS = 0.18
TYPE_SECONDS_PER_CHAR = 0.022
CAPTION_POP_SECONDS = 0.15
CAPTION_HOLD_SECONDS = 0.25
LOOP_SEAM_SECONDS = 0.45
SNAP_SECONDS = 0.2
SNAP_ZOOM = 1.14
PUNCH_ZOOM = 1.18
PUNCH_MIN_SECONDS = 2.4
FLASH_SECONDS = 0.12
SHAKE_SECONDS = 0.35
CTA_START_FRACTION = 0.55
CTA_HOLD_SECONDS = 2.2
CTA_FADE_SECONDS = 0.25
LOUDNESS_LUFS = -14

# field limits (STYLE.md section 3)
LIMITS = {"CASE_HEADER": 32, "CASE_DATE": 12, "STAMP": 14, "TAG": 7, "TAG_LABEL": 26}

KICKER = {"facts": "CASE FILE", "sauce_recipe": "RECIPE FILE"}
CTA_TEXT = {"facts": "SUBSCRIBE FOR MORE CASES", "sauce_recipe": "SUBSCRIBE FOR MORE SAUCES"}

# Music: CC BY tracks need a credit line in the description (metadata.py
# appends style_json["music_credit"]).
MUSIC_TRACKS = {
    "facts": [
        {
            "file": "darkest_child.mp3",
            "credit": 'Music: "Darkest Child" by Kevin MacLeod (incompetech.com), licensed under CC BY 4.0',
        },
    ],
}


def applies(template: str, env: dict[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return (e.get("VISUAL_STYLE") or "").strip().lower() == RENDERER_NAME and template in TEMPLATES


# ----------------------------------------------------------------- prompt
_EXAMPLES = {
    "facts": (
        'CASE_HEADER: LAKE NYOS, CAMEROON\nCASE_DATE: 21.08.1986\nSTAMP: NOT DROWNED\n'
        'TAG_1: 1,746\nTAG_LABEL_1: DEAD IN ONE NIGHT\nTAG_2: CO2\nTAG_LABEL_2: DISSOLVED IN DEEP WATER\n'
        'TAG_3: 24/7\nTAG_LABEL_3: VENTED SINCE 2001'
    ),
    "sauce_recipe": (
        'CASE_HEADER: LEBANESE TOUM\nCASE_DATE: none\nSTAMP: NO EGG\n'
        'TAG_1: 4X\nTAG_LABEL_1: ITS VOLUME IN OIL\nTAG_2: 2 CUPS\nTAG_LABEL_2: OIL, ONE THREAD AT A TIME\n'
        'TAG_3: SLOW\nTAG_LABEL_3: THE ONLY HARD PART'
    ),
}


def prompt_block(template: str) -> str:
    return f"""

--- ON-SCREEN CASE-FILE TEXT (required) ---
After everything above, add these lines at the very end of your output,
one per line, in this order. They are drawn as big on-screen text over
the video. Every tag and label must restate something the script
already says; never add a new claim. Use plain capital letters.
CASE_HEADER: <the subject's name or place, 2-5 words, max {LIMITS['CASE_HEADER']} characters>
CASE_DATE: <the real date or year it happened, max {LIMITS['CASE_DATE']} characters, or none>
STAMP: <a 1-2 word verdict stamped over the first picture, max {LIMITS['STAMP']} characters, or none>
TAG_1: <the single most striking number or word in beat 1, max {LIMITS['TAG']} characters>
TAG_LABEL_1: <what TAG_1 means, 2-5 words, max {LIMITS['TAG_LABEL']} characters>
TAG_2: <same for beat 2>
TAG_LABEL_2: <same for beat 2>
TAG_3: <same for beat 3>
TAG_LABEL_3: <same for beat 3>
Example:
{_EXAMPLES.get(template, _EXAMPLES['facts'])}
"""


_FIELD_LINE = re.compile(r"^\s*(CASE_HEADER|CASE_DATE|STAMP|TAG_LABEL_[123]|TAG_[123]):[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def clean_field(value: str | None, max_chars: int) -> str | None:
    """Upper-cased, quote/markdown-stripped value, or None when it's empty,
    'none', or too long for its slot. Never raises."""
    if value is None:
        return None
    text = " ".join(value.strip().strip("\"'*`").split()).upper()
    text = text.replace("₂", "2")
    if not text or text in {"NONE", "N/A", "-"} or len(text) > max_chars:
        return None
    return text


def extract_fields(raw: str) -> tuple[str, dict]:
    """Splits the case-file lines off the model output. Returns (output
    without them, {"header", "date", "stamp", "tags": [(tag, label) x3]}).
    Missing or invalid lines come back as None; never raises."""
    found: dict[str, str] = {}
    for m in _FIELD_LINE.finditer(raw):
        found.setdefault(m.group(1), m.group(2))
    stripped = _FIELD_LINE.sub("", raw)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    fields = {
        "header": clean_field(found.get("CASE_HEADER"), LIMITS["CASE_HEADER"]),
        "date": clean_field(found.get("CASE_DATE"), LIMITS["CASE_DATE"]),
        "stamp": clean_field(found.get("STAMP"), LIMITS["STAMP"]),
        "tags": [
            (clean_field(found.get(f"TAG_{i}"), LIMITS["TAG"]), clean_field(found.get(f"TAG_LABEL_{i}"), LIMITS["TAG_LABEL"]))
            for i in (1, 2, 3)
        ],
    }
    return stripped, fields


# ----------------------------------------------------------------- style_json
def load_style(video: dict) -> dict:
    try:
        data = json.loads(video.get("style_json") or "{}")
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def merge_style(video_id: str, **values) -> dict:
    video = get_video(video_id)
    data = load_style(video or {})
    data.update(values)
    update_video(video_id, style_json=json.dumps(data))
    return data


def beat_tag(beat: dict) -> tuple[str | None, str | None]:
    try:
        kw = json.loads(beat.get("keywords") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None, None
    if not isinstance(kw, dict):
        return None, None
    return kw.get("tag"), kw.get("tag_label")


# ----------------------------------------------------------------- music
def pick_music(template: str, video_id: str, video_seconds: float, duration_of=None) -> dict | None:
    """The style's music bed for this template (None = use the default
    pool) and a per-video start offset, so consecutive Shorts don't share
    the same opening bars. Deterministic per video id. `duration_of(path)`
    returns a track's length (defaults to ffprobe)."""
    tracks = MUSIC_TRACKS.get(template)
    if not tracks:
        return None
    digest = int(hashlib.sha256(video_id.encode()).hexdigest(), 16)
    track = tracks[digest % len(tracks)]
    track_seconds = (duration_of or _probe_duration)(MUSIC_DIR / track["file"])
    span = max(0.0, track_seconds - video_seconds - 4.0)
    offset = round((digest // 7 % 1000) / 1000 * span, 2)
    return {"path": MUSIC_DIR / track["file"], "offset": offset, "credit": track["credit"]}


# ----------------------------------------------------------------- easing
def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return max(a, min(b, x))


def lin(t: float, a: float, b: float) -> float:
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def ease_out(x: float) -> float:
    return 1 - (1 - clamp(x)) ** 3


def ease_out_back(x: float, s: float = 1.7) -> float:
    x = clamp(x) - 1
    return x * x * ((s + 1) * x + s) + 1


# ----------------------------------------------------------------- timing plans
def caption_chunks(words: list[dict], solo: set[str], max_words: int = 2, max_chars: int = 13) -> list[list[dict]]:
    """1-2 word caption cards; a new card at every sentence end; numbers
    and the beat tag words (`solo`, normalized) always get their own."""
    out: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        key = normalize(w["word"])
        is_solo = key in solo or any(ch.isdigit() for ch in w["word"])
        prev_solo = bool(cur) and (normalize(cur[-1]["word"]) in solo or any(ch.isdigit() for ch in cur[-1]["word"]))
        too_long = bool(cur) and (len(cur) >= max_words or len(" ".join(c["word"] for c in [*cur, w])) > max_chars)
        sentence_end = bool(cur) and cur[-1]["word"].rstrip("\"')").endswith((".", "!", "?"))
        if cur and (is_solo or prev_solo or too_long or sentence_end):
            out.append(cur)
            cur = []
        cur.append(w)
    if cur:
        out.append(cur)
    return out


def chunk_at(chunks: list[list[dict]], t: float, hold: float = CAPTION_HOLD_SECONDS) -> int:
    for i, c in enumerate(chunks):
        nxt = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else 1e9
        if c[0]["start"] - 0.02 <= t < min(nxt, c[-1]["end"] + hold):
            return i
    return -1


def normalize(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def plan_effects(segments: list[dict], beat_starts: list[float]) -> dict:
    """Frame-level effect plan from visuals_facts' segment list
    ([{"start": frame, "frames": n, "kind": "video"|"card"}]):
    snap-zoom starts, mid-clip punch-ins and flash frames (STYLE.md 4)."""
    snaps, punches = [], []
    for seg in segments:
        if seg["kind"] != "video":
            continue
        if seg["start"] > 0:
            snaps.append(seg["start"])
        if seg["frames"] > PUNCH_MIN_SECONDS * FPS:
            punches.append((seg["start"] + seg["frames"] // 2, seg["start"] + seg["frames"]))
    flashes = [round(t * FPS) for t in beat_starts[1:]]
    return {"snaps": snaps, "punches": punches, "flashes": flashes}


# ----------------------------------------------------------------- drawing
@cache
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / name), size)


def text_img(fnt: ImageFont.FreeTypeFont, text: str, fill, stroke: int = 0, stroke_fill=(0, 0, 0, 255),
             shadow: tuple[int, int, int, int] | None = None, tracking: int = 0) -> Image.Image:
    """Tight RGBA image of `text`. shadow = (dx, dy, blur, alpha)."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [probe.textlength(ch, font=fnt) + tracking for ch in text] if tracking else []
    total = int(sum(widths) - tracking) if tracking else int(probe.textlength(text, font=fnt))
    asc, desc = fnt.getmetrics()
    pad = stroke + (shadow[2] * 3 + max(abs(shadow[0]), abs(shadow[1])) if shadow else 0) + 4
    w, h = total + pad * 2, asc + desc + pad * 2

    def draw(d: ImageDraw.ImageDraw, ox: int, oy: int, f, sw: int, sf) -> None:
        if tracking:
            x = ox
            for ch, cw in zip(text, widths):
                d.text((x, oy), ch, font=fnt, fill=f, stroke_width=sw, stroke_fill=sf)
                x += cw
        else:
            d.text((ox, oy), text, font=fnt, fill=f, stroke_width=sw, stroke_fill=sf)

    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw(ImageDraw.Draw(sh), pad + shadow[0], pad + shadow[1], (0, 0, 0, shadow[3]), stroke, (0, 0, 0, shadow[3]))
        layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(shadow[2])))
    draw(ImageDraw.Draw(layer), pad, pad, fill, stroke, stroke_fill)
    return layer


def rich_text(fnt: ImageFont.FreeTypeFont, items: list[dict], stroke: int, shadow: tuple[int, int, int, int],
              max_w: int, line_gap: int) -> Image.Image:
    """One canvas per caption card: natural word spacing, per-word fill,
    balanced 2-line wrap when wider than max_w."""
    sp = fnt.getlength(" ")
    widths = [fnt.getlength(it["text"]) for it in items]
    lines = [list(range(len(items)))]
    if sum(widths) + sp * (len(items) - 1) > max_w and len(items) > 1:
        k = min(range(1, len(items)), key=lambda j: abs(sum(widths[:j]) - sum(widths[j:])))
        lines = [list(range(k)), list(range(k, len(items)))]
    asc, desc = fnt.getmetrics()
    lh = asc + desc
    pad = stroke + shadow[2] * 3 + abs(shadow[1]) + 4
    lws = [sum(widths[i] for i in line) + sp * (len(line) - 1) for line in lines]
    cw, ch = int(max(lws)) + 2 * pad, lh * len(lines) + line_gap * (len(lines) - 1) + 2 * pad
    pos = {}
    for li, line in enumerate(lines):
        x = pad + (max(lws) - lws[li]) / 2
        for i in line:
            pos[i] = (x, pad + li * (lh + line_gap))
            x += widths[i] + sp
    sh = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
    d = ImageDraw.Draw(sh)
    for i, it in enumerate(items):
        x, y = pos[i]
        d.text((x + shadow[0], y + shadow[1]), it["text"], font=fnt, fill=(0, 0, 0, shadow[3]),
               stroke_width=stroke, stroke_fill=(0, 0, 0, shadow[3]))
    out = Image.alpha_composite(Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), sh.filter(ImageFilter.GaussianBlur(shadow[2])))
    d = ImageDraw.Draw(out)
    for i, it in enumerate(items):
        d.text(pos[i], it["text"], font=fnt, fill=it["fill"], stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    return out


def paste(base: Image.Image, im: Image.Image, cx: float, cy: float, alpha: float = 1.0, scale: float = 1.0) -> None:
    """Alpha-composite `im` centered at (cx, cy), clipped to the frame."""
    if alpha <= 0.003 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.004:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.BILINEAR)
    if alpha < 0.997:
        im = im.copy()
        im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
    x, y = round(cx - im.width / 2), round(cy - im.height / 2)
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(im.width, base.width - x), min(im.height, base.height - y)
    if sx1 > sx0 and sy1 > sy0:
        base.alpha_composite(im, dest=(x + sx0, y + sy0), source=(sx0, sy0, sx1, sy1))


@cache
def vgradient(h: int, top_alpha: int, bottom_alpha: int) -> Image.Image:
    a = np.linspace(top_alpha, bottom_alpha, h).astype(np.uint8)[:, None].repeat(W, 1)
    g = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    g.putalpha(Image.fromarray(a))
    return g


@cache
def vignette(strength: int) -> Image.Image:
    y, x = np.mgrid[0:H // 4, 0:W // 4]
    d = np.sqrt(((x - W / 8) / (W / 8)) ** 2 + ((y - H / 8) / (H / 8)) ** 2)
    a = (np.clip((d - 0.55) / 0.75, 0, 1) ** 1.6 * strength).astype(np.uint8)
    v = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    v.putalpha(Image.fromarray(a).resize((W, H), Image.BICUBIC))
    return v


def big_tag(text: str, color: tuple[int, int, int]) -> Image.Image:
    f = font("Anton-Regular.ttf", 250)
    fill = color + (255,)
    shadow = (0, 8, 14, 190)
    if text == "CO2":  # chemistry subscript, the most common case
        co = text_img(f, "CO", fill, stroke=6, shadow=shadow)
        f2 = font("Anton-Regular.ttf", 130)
        two = text_img(f2, "2", fill, stroke=5, shadow=shadow)
        pad_co, pad_two = 6 + 14 * 3 + 8 + 4, 5 + 14 * 3 + 8 + 4
        x2 = co.width - pad_co - pad_two + 8
        y2 = pad_co + f.getmetrics()[0] - (pad_two + f2.getmetrics()[0]) + 38
        out = Image.new("RGBA", (x2 + two.width, max(co.height, y2 + two.height)), (0, 0, 0, 0))
        out.alpha_composite(co, dest=(0, 0))
        out.alpha_composite(two, dest=(x2, y2))
        return out
    return text_img(f, text, fill, stroke=6, shadow=shadow)


def stamp_img(text: str) -> Image.Image:
    t = text_img(font("Anton-Regular.ttf", 118), text, STAMP_RED + (255,))
    pad = 28
    im = Image.new("RGBA", (t.width + pad * 2, t.height + pad), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((6, 6, im.width - 7, im.height - 7), 18, outline=STAMP_RED + (255,), width=10)
    im.alpha_composite(t, dest=(pad, pad // 2))
    keep = (np.random.default_rng(1).random((im.height, im.width)) > 0.2).astype(np.uint8) * 255
    holes = Image.fromarray(keep).filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: 255 if v > 150 else int(v * 0.5))
    im.putalpha(Image.fromarray(np.minimum(np.array(im.getchannel("A")), np.array(holes))))
    return im.rotate(13, resample=Image.BICUBIC, expand=True)


def cta_img(text: str) -> Image.Image:
    t = text_img(font("SpecialElite-Regular.ttf", 34), text, (40, 36, 30, 255))
    strip = Image.new("RGBA", (t.width + 30, t.height + 6), PAPER + (245,))
    strip.alpha_composite(t, dest=(15, 3))
    return strip.rotate(-2, resample=Image.BICUBIC, expand=True)


# ----------------------------------------------------------------- evidence cards
PHOTO_W, PHOTO_H = 700, 540
CARD_BORDER, CARD_BOTTOM = 26, 92


def _cover(im: Image.Image, tw: int, th: int, zoom: float = 1.0) -> Image.Image:
    a = tw / th
    cw = min(im.width, im.height * a) / zoom
    ch = cw / a
    x0, y0 = (im.width - cw) / 2, (im.height - ch) / 2
    return im.resize((tw, th), Image.BICUBIC, box=(max(0.0, x0), max(0.0, y0), min(float(im.width), x0 + cw), min(float(im.height), y0 + ch)))


def card_label(subject: str | None) -> str:
    text = f"EXHIBIT  ·  {(subject or 'EVIDENCE').upper()}"
    return text if len(text) <= 38 else text[:37].rstrip() + "."


def render_card_clip(image_path: Path, frames: int, label: str, out_path: Path, rotation: float = -2.0) -> None:
    """A real photo as an evidence Polaroid over a blurred, darkened copy of
    itself (STYLE.md 4). Slams in over 0.2 s, slow push-in inside. Same
    codec/size/fps as visuals_facts' other segments so they concat by copy."""
    src = Image.open(image_path).convert("RGB")
    up = src.resize((max(src.width, PHOTO_W * 2), round(src.height * max(src.width, PHOTO_W * 2) / src.width)), Image.LANCZOS)
    backdrop = _cover(src, 270, 480).filter(ImageFilter.GaussianBlur(14))
    backdrop = ImageEnhance.Brightness(backdrop).enhance(0.36).resize((W, H), Image.BICUBIC).convert("RGBA")
    backdrop.alpha_composite(vignette(170))
    lab = text_img(font("SpecialElite-Regular.ttf", 30), label, (40, 36, 30, 255))
    tape = Image.new("RGBA", (230, 60), (226, 214, 170, 150)).rotate(-4, expand=True, resample=Image.BICUBIC)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    proc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", str(out_path)],
        stdin=subprocess.PIPE,
    )
    try:
        for i in range(frames):
            t = i / FPS
            photo = _cover(up, PHOTO_W, PHOTO_H, zoom=1.0 + 0.08 * i / max(1, frames - 1)).convert("RGBA")
            card = Image.new("RGBA", (PHOTO_W + CARD_BORDER * 2, PHOTO_H + CARD_BORDER + CARD_BOTTOM), PAPER + (255,))
            card.alpha_composite(photo, dest=(CARD_BORDER, CARD_BORDER))
            card.alpha_composite(lab, dest=(CARD_BORDER, PHOTO_H + CARD_BORDER + (CARD_BOTTOM - lab.height) // 2 + 2))
            full = Image.new("RGBA", (card.width, card.height + 40), (0, 0, 0, 0))
            full.alpha_composite(card, dest=(0, 30))
            full.alpha_composite(tape, dest=(card.width // 2 - tape.width // 2, 0))
            enter = lin(t, 0, 0.2)
            full = full.rotate(rotation + (1 - ease_out(enter)) * 6, resample=Image.BICUBIC, expand=True)
            shadow = Image.new("RGBA", full.size, (0, 0, 0, 0))
            shadow.putalpha(full.getchannel("A").point(lambda v: int(v * 0.6)))
            shadow = shadow.filter(ImageFilter.GaussianBlur(16))
            sc = 1.28 - 0.28 * ease_out_back(enter, 1.3)
            fr = backdrop.copy()
            paste(fr, shadow, W / 2 + 10, CARD_Y + 22, scale=sc)
            paste(fr, full, W / 2, CARD_Y, scale=sc)
            proc.stdin.write(fr.convert("RGB").tobytes())
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed rendering evidence card {out_path}")


# ----------------------------------------------------------------- final pass
def _probe_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


class _Layer:
    """Everything drawn over the footage for one video."""

    def __init__(self, video: dict, beats: list[dict], words: list[dict], duration: float):
        self.template = video["template"]
        style = load_style(video)
        self.duration = duration
        self.beat_starts: list[float] = []
        acc = 0.0
        for b in beats:
            self.beat_starts.append(acc)
            acc += b["duration"] or 0.0
        self.tags = [beat_tag(b) for b in beats]
        tag_words = {normalize(part) for tag, _ in self.tags if tag for part in tag.split()}
        self.words = words
        self.chunks = caption_chunks(words, tag_words)
        self.solo = tag_words
        self.cap_cache: dict = {}
        hf = font("SpecialElite-Regular.ttf", 36)
        header = f"{KICKER.get(self.template, 'CASE FILE')}  ·  {style.get('header') or ''}".rstrip(" ·")
        self.header = text_img(hf, header, PAPER + (255,), shadow=(0, 2, 6, 200))
        self.header_r = text_img(hf, style["date"], PAPER + (210,), shadow=(0, 2, 6, 200)) if style.get("date") else None
        small = font("Montserrat-ExtraBold.ttf", 44)
        self.tag_imgs = []
        for i, (tag, label) in enumerate(self.tags):
            big = big_tag(tag, TAG_COLORS[i % 3]) if tag else None
            lab = text_img(small, label, (255, 255, 255, 240), tracking=3, shadow=(0, 3, 8, 220)) if label else None
            self.tag_imgs.append((big, lab, len(label or "")))
        self.stamp = stamp_img(style["stamp"]) if style.get("stamp") else None
        beat1_words = [w for w in words if len(self.beat_starts) < 2 or w["start"] < self.beat_starts[1]]
        self.t_stamp = beat1_words[-1]["start"] if beat1_words else None
        self.t_beat2 = self.beat_starts[1] if len(self.beat_starts) > 1 else duration
        self.cta = cta_img(CTA_TEXT.get(self.template, CTA_TEXT["facts"]))
        self.t_cta = duration * CTA_START_FRACTION
        self.t_seam = duration - LOOP_SEAM_SECONDS

    def tag_index(self, t: float) -> int:
        if t >= self.t_seam:
            return 0
        return max(i for i, s in enumerate(self.beat_starts) if s <= t + 1e-6) if self.beat_starts else 0

    def shake(self, t: float) -> tuple[float, float]:
        for ts, amp in ((0.0, 24), (self.t_stamp, 30)):
            if ts is not None and ts <= t < ts + SHAKE_SECONDS:
                d = 1 - lin(t, ts, ts + SHAKE_SECONDS)
                return (math.sin(t * 91) * amp * d, math.cos(t * 77) * amp * d)
        return (0.0, 0.0)

    def caption(self, idx: int, t: float) -> Image.Image:
        chunk = self.chunks[idx]
        active = max([k for k, x in enumerate(chunk) if x["start"] <= t + 0.03] or [0])
        key = (idx, active)
        if key not in self.cap_cache:
            emph = len(chunk) == 1 and (normalize(chunk[0]["word"]) in self.solo or any(c.isdigit() for c in chunk[0]["word"]))
            f = font("Montserrat-Black.ttf", 140 if emph else 112)
            items = [{"text": x["word"].upper(), "fill": YELLOW + (255,) if (k == active or emph) else WHITE + (255,)}
                     for k, x in enumerate(chunk)]
            self.cap_cache[key] = rich_text(f, items, stroke=12, shadow=(0, 9, 10, 190), max_w=CAPTION_MAX_W, line_gap=-22)
        return self.cap_cache[key]

    def draw(self, fr: Image.Image, t: float) -> None:
        jit = self.shake(t)
        if self.stamp is not None and self.t_stamp is not None and self.t_stamp <= t < self.t_beat2:
            sc = 1 + 0.8 * (1 - ease_out(lin(t, self.t_stamp, self.t_stamp + 0.12)))
            paste(fr, self.stamp, STAMP_POS[0] + jit[0], STAMP_POS[1] + jit[1], alpha=lin(t, self.t_stamp, self.t_stamp + 0.04), scale=sc)
        if self.t_cta <= t < self.t_cta + CTA_HOLD_SECONDS:
            a = min(lin(t, self.t_cta, self.t_cta + CTA_FADE_SECONDS), 1 - lin(t, self.t_cta + CTA_HOLD_SECONDS - CTA_FADE_SECONDS, self.t_cta + CTA_HOLD_SECONDS))
            paste(fr, self.cta, W / 2, CTA_Y, alpha=a)
        fr.alpha_composite(vgradient(780, 235, 0), dest=(0, 0))
        paste(fr, self.header, 70 + self.header.width / 2, HEADER_Y)
        if self.header_r is not None:
            rx = W - 70 - self.header_r.width / 2
            paste(fr, self.header_r, rx, HEADER_Y)
            dot = 0.5 + 0.5 * math.sin(t * 6)
            x0 = W - 70 - self.header_r.width - 40
            ImageDraw.Draw(fr).ellipse((x0, HEADER_Y - 10, x0 + 20, HEADER_Y + 10), fill=RED + (int(120 + 135 * dot),))
        ti = self.tag_index(t)
        big, lab, n_chars = self.tag_imgs[ti] if ti < len(self.tag_imgs) else (None, None, 0)
        t0 = self.t_seam if (t >= self.t_seam) else self.beat_starts[ti] if self.beat_starts else 0.0
        # Frame 0 and the loop seam are drawn static and identical, so the
        # last frame flows straight into the first.
        static = ti == 0
        if big is not None:
            a = 1.0 if static else ease_out(lin(t, t0, t0 + 0.15))
            sc = 1.0 if static else 1 + 0.3 * (1 - ease_out_back(lin(t, t0, t0 + TAG_POP_SECONDS)))
            paste(fr, big, W / 2, TAG_Y, alpha=a, scale=sc)
        if lab is not None:
            reveal = 1.0 if static else lin(t, t0, t0 + TYPE_SECONDS_PER_CHAR * max(1, n_chars))
            cw = int(lab.width * reveal)
            if cw > 0:
                paste(fr, lab.crop((0, 0, cw, lab.height)), W / 2 - lab.width / 2 + cw / 2, TAG_LABEL_Y)
        ci = chunk_at(self.chunks, t)
        if ci >= 0 and t < self.t_seam:
            start = self.chunks[ci][0]["start"]
            sc = 0.72 + 0.28 * ease_out_back(lin(t, start - 0.02, start + CAPTION_POP_SECONDS), 2.0)
            paste(fr, self.caption(ci, t), W / 2, CAPTION_Y, scale=sc)


def _footage_frame(raw: Image.Image, i: int, effects: dict, jit: tuple[float, float]) -> Image.Image:
    """Snap zoom after cuts, punch-in framing cuts and shake, as a crop of
    the decoded footage frame."""
    zoom, fx = 1.0, 0.5
    for start in effects["snaps"]:
        if start <= i < start + SNAP_SECONDS * FPS:
            zoom = 1 + (SNAP_ZOOM - 1) * (1 - ease_out((i - start) / (SNAP_SECONDS * FPS)))
    for k, (start, end) in enumerate(effects["punches"]):
        if start <= i < end:
            zoom = max(zoom, PUNCH_ZOOM)
            fx = 0.44 if k % 2 == 0 else 0.56
    if zoom == 1.0 and jit == (0.0, 0.0):
        return raw
    if zoom == 1.0:
        zoom = 1.04  # room to shake without exposing an edge
    cw, ch = W / zoom, H / zoom
    cx = clamp(fx * W + jit[0] / zoom, cw / 2, W - cw / 2)
    cy = clamp(H / 2 + jit[1] / zoom, ch / 2, H - ch / 2)
    return raw.resize((W, H), Image.BILINEAR, box=(cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2))


def render_final(video_id: str, words: list[dict]) -> str:
    """The style's last pass (called by captions.py instead of the ASS
    burn-in): footage effects + case-file layer + captions + subscribe
    strip over the assembled video. Audio is copied as-is."""
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    src = Path(video["video_path"])
    beats = [dict(b) for b in get_video_steps(video_id)]
    duration = _probe_duration(src)
    style = load_style(video)
    layer = _Layer(video, beats, words, duration)
    effects = plan_effects(style.get("segments") or [], layer.beat_starts)
    flash_frames = set()
    for f0 in effects["flashes"]:
        flash_frames.update(range(f0, f0 + round(FLASH_SECONDS * FPS)))

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("ffmpeg not found on PATH")
    out_path = OUTPUT_DIR / f"{video_id}_final.mp4"
    tmp_path = OUTPUT_DIR / f"{video_id}_final.tmp.mp4"
    dec = subprocess.Popen(
        [ffmpeg, "-v", "error", "-i", str(src), "-vf", f"scale={W}:{H},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    enc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
         "-i", str(src), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(tmp_path)],
        stdin=subprocess.PIPE,
    )
    frame_bytes = W * H * 3
    i = 0
    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            t = i / FPS
            raw = Image.frombuffer("RGB", (W, H), buf, "raw", "RGB", 0, 1)
            fr = _footage_frame(raw, i, effects, layer.shake(t)).convert("RGBA")
            fr.alpha_composite(vgradient(760, 0, 200), dest=(0, H - 760))
            fr.alpha_composite(vignette(120))
            if i in flash_frames:
                f0 = max(f for f in effects["flashes"] if f <= i)
                a = int(200 * (1 - (i - f0) / (FLASH_SECONDS * FPS)))
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, a)))
            layer.draw(fr, t)
            enc.stdin.write(fr.convert("RGB").tobytes())
            i += 1
    finally:
        enc.stdin.close()
        dec.stdout.close()
    if dec.wait() != 0 or enc.wait() != 0 or i == 0:
        raise RuntimeError(f"casefile final pass failed for {video_id} after {i} frames")
    shutil.move(str(tmp_path), str(out_path))
    update_video(video_id, status="captioned", final_path=str(out_path), cta_overlay_variant="casefile_paper_strip")
    print(f"[casefile] {video_id}: {i} frames, {duration:.2f}s -> {out_path}")
    return str(out_path)


if __name__ == "__main__":
    from pipeline.captions import captions

    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m pipeline.casefile <video_id>  (renders the final pass for an assembled video)")
    print(captions(sys.argv[1]))
