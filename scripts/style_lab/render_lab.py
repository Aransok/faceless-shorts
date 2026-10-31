"""Style lab renderer: one script, three looks (A punchy, B premium,
C case-file documentary). Frames are composed with Pillow and piped to
ffmpeg; captions are drawn per frame from edge_tts word timings.

Usage:
    python scripts/style_lab/render_lab.py <lab_dir> <out_dir> [A B C]

<lab_dir> holds img/, fonts/, music/, voice/ (see voice_lab.py).
Test tool only: not part of the daily pipeline.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import time
import wave
from functools import cache
from pathlib import Path
from typing import ClassVar

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sfx

W, H, FPS = 1080, 1920, 30
SR = sfx.SR


# ---------------------------------------------------------------- easing
def clamp(x: float, a: float = 0.0, b: float = 1.0) -> float:
    return a if x < a else min(x, b)


def lin(t: float, a: float, b: float) -> float:
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def ease_out(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x: float) -> float:
    x = clamp(x)
    return x * x * (3 - 2 * x)


def ease_out_back(x: float, s: float = 1.7) -> float:
    x = clamp(x) - 1
    return x * x * ((s + 1) * x + s) + 1


# ---------------------------------------------------------------- words
class Words:
    def __init__(self, path: Path):
        self.w: list[dict] = json.loads(path.read_text())
        self.end = self.w[-1]["end"]

    def at(self, sentence: int, word: str, nth: int = 1) -> float:
        """Start time of the nth word in `sentence` whose text starts
        with `word` (case-insensitive)."""
        seen = 0
        for x in self.w:
            if x["sentence"] == sentence and x["word"].lower().startswith(word.lower()):
                seen += 1
                if seen == nth:
                    return x["start"]
        raise KeyError((sentence, word, nth))

    def sentence_start(self, s: int) -> float:
        return next(x["start"] for x in self.w if x["sentence"] == s)

    def sentence_end(self, s: int) -> float:
        return [x["end"] for x in self.w if x["sentence"] == s][-1]

    def chunks(self, max_words: int, max_chars: int, solo: set[str] = frozenset()) -> list[list[dict]]:
        out: list[list[dict]] = []
        cur: list[dict] = []
        for x in self.w:
            key = x["word"].lower()
            new_sentence = cur and cur[-1]["sentence"] != x["sentence"]
            too_long = cur and (len(cur) >= max_words or len(" ".join(c["word"] for c in cur + [x])) > max_chars)
            if cur and (new_sentence or too_long or key in solo or cur[-1]["word"].lower() in solo):
                out.append(cur)
                cur = []
            cur.append(x)
        if cur:
            out.append(cur)
        return out


def chunk_at(chunks: list[list[dict]], t: float, hold: float = 0.35) -> tuple[int, list[dict] | None]:
    for i, c in enumerate(chunks):
        start = c[0]["start"]
        nxt = chunks[i + 1][0]["start"] if i + 1 < len(chunks) else 1e9
        stop = min(nxt, c[-1]["end"] + hold)
        if start - 0.02 <= t < stop:
            return i, c
    return -1, None


# ---------------------------------------------------------------- assets
class Assets:
    def __init__(self, lab: Path):
        self.lab = lab
        self._img: dict = {}
        self._memo: dict = {}

    def _cached(self, key: tuple, make):
        if key not in self._memo:
            self._memo[key] = make()
        return self._memo[key]

    def font(self, name: str, size: int) -> ImageFont.FreeTypeFont:
        return self._cached(("font", name, size), lambda: ImageFont.truetype(str(self.lab / "fonts" / name), size))

    def raw(self, name: str) -> Image.Image:
        if name not in self._img:
            self._img[name] = Image.open(self.lab / "img" / f"{name}.jpg").convert("RGB")
        return self._img[name]

    def prepared(self, name: str, tw: int, th: int, look: str = "") -> Image.Image:
        """Source scaled (Lanczos + light sharpening) so a cover-crop at
        zoom 1.0 is at least 1.2x the target size, then color-graded."""
        return self._cached(("prep", name, tw, th, look), lambda: self._prepare(name, tw, th, look))

    def _prepare(self, name: str, tw: int, th: int, look: str) -> Image.Image:
        im = self.raw(name)
        scale = max(tw / im.width, th / im.height) * 1.2
        if scale > 1:
            im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
            im = im.filter(ImageFilter.UnsharpMask(radius=2.2, percent=70, threshold=2))
        return grade(im, look)

    def backdrop(self, name: str, look: str, brightness: float) -> Image.Image:
        return self._cached(("bg", name, look, brightness), lambda: self._backdrop(name, look, brightness))

    def _backdrop(self, name: str, look: str, brightness: float) -> Image.Image:
        im = self.raw(name)
        small = cover_box_resize(im, 270, 480)
        small = small.filter(ImageFilter.GaussianBlur(14))
        small = ImageEnhance.Brightness(grade(small, look)).enhance(brightness)
        return small.resize((W, H), Image.BICUBIC).convert("RGBA")


def grade(im: Image.Image, look: str) -> Image.Image:
    if not look:
        return im
    if look == "punch":
        im = ImageEnhance.Contrast(im).enhance(1.18)
        return ImageEnhance.Color(im).enhance(1.25)
    if look == "punchbright":
        im = ImageEnhance.Brightness(im).enhance(1.35)
        im = ImageEnhance.Contrast(im).enhance(1.2)
        return ImageEnhance.Color(im).enhance(1.3)
    if look == "night":
        im = ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(0.55)).enhance(0.7)
        blue = Image.new("RGB", im.size, (40, 70, 140))
        return Image.blend(im, blue, 0.28)
    if look == "red":
        im = ImageEnhance.Contrast(im).enhance(1.2)
        red = Image.new("RGB", im.size, (170, 20, 20))
        return Image.blend(im, red, 0.22)
    if look == "doc":
        im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(0.85)).enhance(1.08)
        warm = Image.new("RGB", im.size, (120, 90, 50))
        return Image.blend(im, warm, 0.08)
    if look == "soft":
        im = ImageEnhance.Color(im).enhance(0.9)
        return ImageEnhance.Contrast(im).enhance(1.04)
    raise ValueError(look)


def cover_box_resize(im: Image.Image, tw: int, th: int) -> Image.Image:
    a = tw / th
    if im.width / im.height > a:
        cw = im.height * a
        box = ((im.width - cw) / 2, 0, (im.width + cw) / 2, im.height)
    else:
        ch = im.width / a
        box = (0, (im.height - ch) / 2, im.width, (im.height + ch) / 2)
    return im.resize((tw, th), Image.BICUBIC, box=box)


def kenburns(src: Image.Image, tw: int, th: int, p: float, z0: float, z1: float,
             fx: float = 0.5, fy: float = 0.5, dx: float = 0.0, dy: float = 0.0,
             jitter: tuple[float, float] = (0.0, 0.0), extra_zoom: float = 1.0) -> tuple[Image.Image, tuple]:
    """Cover-crop of `src` at zoom z (z0->z1 over p), centered on focal
    (fx, fy) and panning by (dx, dy) crop-widths. Returns (frame, box)."""
    sw, sh = src.size
    a = tw / th
    cw0 = min(sw, sh * a)
    z = (z0 + (z1 - z0) * ease_in_out(p)) * extra_zoom
    cw = cw0 / z
    ch = cw / a
    cx = fx * sw + dx * p * cw + jitter[0] * cw / tw
    cy = fy * sh + dy * p * ch + jitter[1] * ch / th
    cx = min(max(cx, cw / 2), sw - cw / 2)
    cy = min(max(cy, ch / 2), sh - ch / 2)
    box = (max(0.0, cx - cw / 2), max(0.0, cy - ch / 2), min(float(sw), cx + cw / 2), min(float(sh), cy + ch / 2))
    return src.resize((tw, th), Image.BILINEAR, box=box), box


# ---------------------------------------------------------------- drawing
def text_img(font: ImageFont.FreeTypeFont, text: str, fill, stroke: int = 0, stroke_fill=(0, 0, 0, 255),
             shadow: tuple[int, int, int, int] | None = None, tracking: int = 0) -> Image.Image:
    """Tight RGBA image of `text`. shadow = (dx, dy, blur, alpha)."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    if tracking:
        widths = [probe.textlength(ch, font=font) + tracking for ch in text]
        total = int(sum(widths) - tracking)
    else:
        widths = []
        total = int(probe.textlength(text, font=font))
    asc, desc = font.getmetrics()
    pad = stroke + (shadow[2] * 3 + max(abs(shadow[0]), abs(shadow[1])) if shadow else 0) + 4
    w, h = total + pad * 2, asc + desc + pad * 2
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)

    def _draw(dr: ImageDraw.ImageDraw, ox: int, oy: int, f, sw: int, sf) -> None:
        if tracking:
            x = ox
            for ch, cw in zip(text, widths):
                dr.text((x, oy), ch, font=font, fill=f, stroke_width=sw, stroke_fill=sf)
                x += cw
        else:
            dr.text((ox, oy), text, font=font, fill=f, stroke_width=sw, stroke_fill=sf)

    if shadow:
        sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _draw(ImageDraw.Draw(sh), pad + shadow[0], pad + shadow[1], (0, 0, 0, shadow[3]), stroke, (0, 0, 0, shadow[3]))
        layer = Image.alpha_composite(layer, sh.filter(ImageFilter.GaussianBlur(shadow[2])))
        d = ImageDraw.Draw(layer)
    _draw(d, pad, pad, fill, stroke, stroke_fill)
    return layer


def paste(base: Image.Image, im: Image.Image, cx: float, cy: float, alpha: float = 1.0, scale: float = 1.0) -> None:
    """Alpha-composite `im` centered at (cx, cy), with opacity and scale."""
    if alpha <= 0.003 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.004:
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.BILINEAR)
    if alpha < 0.997:
        a = im.getchannel("A").point(lambda v: int(v * alpha))
        im = im.copy()
        im.putalpha(a)
    x, y = round(cx - im.width / 2), round(cy - im.height / 2)
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(im.width, base.width - x), min(im.height, base.height - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    base.alpha_composite(im, dest=(x + sx0, y + sy0), source=(sx0, sy0, sx1, sy1))


def hstack(parts: list[Image.Image], gap: int) -> Image.Image:
    w = sum(p.width for p in parts) + gap * (len(parts) - 1)
    h = max(p.height for p in parts)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = 0
    for p in parts:
        out.alpha_composite(p, dest=(x, (h - p.height) // 2))
        x += p.width + gap
    return out


def vstack(parts: list[Image.Image], gap: int) -> Image.Image:
    w = max(p.width for p in parts)
    h = sum(p.height for p in parts) + gap * (len(parts) - 1)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    y = 0
    for p in parts:
        out.alpha_composite(p, dest=((w - p.width) // 2, y))
        y += p.height + gap
    return out


def wrap_two(parts: list[Image.Image], gap: int, max_w: int, line_gap: int) -> Image.Image:
    line = hstack(parts, gap)
    if line.width <= max_w or len(parts) < 2:
        return line
    best = min(range(1, len(parts)), key=lambda k: abs(sum(p.width for p in parts[:k]) - sum(p.width for p in parts[k:])))
    return vstack([hstack(parts[:best], gap), hstack(parts[best:], gap)], line_gap)


@cache
def grain_frames(alpha: int, n: int = 6) -> list[Image.Image]:
    rng = np.random.default_rng(42)
    out = []
    for _ in range(n):
        g = rng.normal(128, 60, (H // 2, W // 2)).clip(0, 255).astype(np.uint8)
        L = Image.fromarray(g).resize((W, H), Image.NEAREST)
        rgba = Image.merge("RGBA", (L, L, L, Image.new("L", (W, H), alpha)))
        out.append(rgba)
    return out


@cache
def vignette(strength: int) -> Image.Image:
    y, x = np.mgrid[0:H // 4, 0:W // 4]
    d = np.sqrt(((x - W / 8) / (W / 8)) ** 2 + ((y - H / 8) / (H / 8)) ** 2)
    a = (np.clip((d - 0.55) / 0.75, 0, 1) ** 1.6 * strength).astype(np.uint8)
    A = Image.fromarray(a).resize((W, H), Image.BICUBIC)
    v = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    v.putalpha(A)
    return v


@cache
def vgradient(h: int, top_alpha: int, bottom_alpha: int, color=(0, 0, 0)) -> Image.Image:
    a = np.linspace(top_alpha, bottom_alpha, h).astype(np.uint8)[:, None].repeat(W, 1)
    g = Image.new("RGBA", (W, h), color + (0,))
    g.putalpha(Image.fromarray(a))
    return g


class Bubbles:
    """Soda-fizz particles rising through a region."""

    def __init__(self, n: int, seed: int, region: tuple[int, int, int, int], speed=(900, 2200), radius=(5, 30)):
        rng = np.random.default_rng(seed)
        x0, _y0, x1, _y1 = region
        self.region = region
        self.p = [
            {"x": rng.uniform(x0, x1), "delay": rng.uniform(0, 0.6), "v": rng.uniform(*speed),
                 "r": rng.uniform(*radius), "ph": rng.uniform(0, 6.28), "wob": rng.uniform(6, 22)}
            for _ in range(n)
        ]

    def draw(self, layer: Image.Image, age: float, alpha: float = 1.0) -> None:
        d = ImageDraw.Draw(layer)
        _x0, y0, _x1, y1 = self.region
        for b in self.p:
            a = age - b["delay"]
            if a < 0:
                continue
            y = y1 - a * b["v"]
            if y < y0 - 40:
                continue
            x = b["x"] + math.sin(a * 9 + b["ph"]) * b["wob"]
            r = b["r"] * (0.7 + 0.6 * min(1, a * 2))
            o = int(220 * alpha)
            d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, o), width=max(2, int(r / 6)), fill=(255, 255, 255, int(o * 0.18)))


@cache
def fog_texture(seed: int = 3) -> Image.Image:
    rng = np.random.default_rng(seed)
    rows, cols = 2 * H // 8, W // 8
    acc = np.zeros((rows, cols))
    for cells, amp in ((4, 1.0), (8, 0.5), (16, 0.25)):
        n = rng.random((cells * 2, cells))
        acc += amp * np.array(Image.fromarray((n * 255).astype(np.uint8)).resize((cols, rows), Image.BICUBIC)) / 255
    acc = (acc - acc.min()) / (acc.max() - acc.min())
    a = np.clip((acc - 0.2) / 0.55, 0, 1) * 215
    edge = np.clip((rows - np.arange(rows)) / (rows * 0.18), 0, 1)[:, None]
    a = (a * edge).astype(np.uint8)
    A = Image.fromarray(a).resize((W, 2 * H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(22))
    fog = Image.new("RGBA", (W, 2 * H), (214, 222, 208, 0))
    fog.putalpha(A)
    return fog


def rounded_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    return m


def rich_text(font: ImageFont.FreeTypeFont, items: list[dict], stroke: int = 0, stroke_fill=(0, 0, 0, 255),
              shadow: tuple[int, int, int, int] | None = None, max_w: int = 10**6, line_gap: int = 0,
              box_pad: tuple[int, int] = (14, 4), box_radius: int = 14) -> Image.Image:
    """One canvas for a whole caption: natural word spacing, per-word
    fill (RGBA), optional per-word highlight box, balanced 2-line wrap."""
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    sp = font.getlength(" ")
    widths = [font.getlength(it["text"]) + (2 * box_pad[0] if it.get("box") else 0) for it in items]
    total = sum(widths) + sp * (len(items) - 1)
    lines = [list(range(len(items)))]
    if total > max_w and len(items) > 1:
        k = min(range(1, len(items)), key=lambda j: abs(sum(widths[:j]) - sum(widths[j:])))
        lines = [list(range(k)), list(range(k, len(items)))]
    asc, desc = font.getmetrics()
    lh = asc + desc
    pad = stroke + box_pad[0] + (shadow[2] * 3 + abs(shadow[1]) if shadow else 0) + 4
    lws = [sum(widths[i] for i in L) + sp * (len(L) - 1) for L in lines]
    cw, chh = int(max(lws)) + 2 * pad, lh * len(lines) + line_gap * (len(lines) - 1) + 2 * pad
    pos = {}
    for li, L in enumerate(lines):
        x = pad + (max(lws) - lws[li]) / 2
        y = pad + li * (lh + line_gap)
        for i in L:
            pos[i] = (x, y)
            x += widths[i] + sp
    out = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
    if shadow:
        sh = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        d = ImageDraw.Draw(sh)
        for i, it in enumerate(items):
            if it.get("box"):
                continue
            x, y = pos[i]
            d.text((x + shadow[0], y + shadow[1]), it["text"], font=font, fill=(0, 0, 0, shadow[3]),
                   stroke_width=stroke, stroke_fill=(0, 0, 0, shadow[3]))
        out = Image.alpha_composite(out, sh.filter(ImageFilter.GaussianBlur(shadow[2])))
    d = ImageDraw.Draw(out)
    for i, it in enumerate(items):
        x, y = pos[i]
        if it.get("box"):
            x += box_pad[0]
            l, t, r, b = probe.textbbox((x, y), it["text"], font=font)
            d.rounded_rectangle((l - box_pad[0], t - box_pad[1] - 6, r + box_pad[0], b + box_pad[1] + 4), box_radius, fill=it["box"])
            d.text((x, y), it["text"], font=font, fill=it["fill"])
        else:
            d.text((x, y), it["text"], font=font, fill=it["fill"], stroke_width=stroke, stroke_fill=stroke_fill)
    return out


class LakeDiagram:
    """Animated cross-section of a crater lake on a volcano: two water
    layers (CO2-rich bottom), magma below, villages at the foot of the
    slopes. Modes: loaded, burst (gas erupts and rolls downhill),
    seeping (CO2 rising from magma)."""

    SW, SH = 1080, 1512
    PALETTES: ClassVar[dict[str, dict]] = {
        "punch": {"sky": ((8, 14, 32), (30, 44, 78)), "ground": ((52, 64, 44), (26, 18, 14)), "rim": (120, 170, 90),
                      "top": (46, 160, 214), "low": (10, 74, 98), "dot": (230, 255, 245), "magma": (255, 96, 31), "label": (255, 225, 77)},
        "soft": {"sky": ((16, 18, 22), (34, 38, 46)), "ground": ((48, 50, 52), (24, 24, 26)), "rim": (150, 150, 140),
                     "top": (96, 140, 160), "low": (32, 62, 74), "dot": (236, 228, 210), "magma": (205, 105, 62), "label": (236, 228, 210)},
        "doc": {"sky": ((22, 26, 34), (52, 58, 70)), "ground": ((70, 62, 48), (34, 28, 22)), "rim": (160, 150, 120),
                    "top": (70, 130, 160), "low": (24, 60, 72), "dot": (240, 236, 220), "magma": (230, 90, 40), "label": (255, 214, 10)},
    }

    def __init__(self, palette: str, label_font: ImageFont.FreeTypeFont | None, label: str = ""):
        self.P = self.PALETTES[palette]
        self.base = self._base(label_font, label)
        rng = np.random.default_rng(5)
        self.dots = []
        while len(self.dots) < 170:
            x, y = rng.uniform(300, 780), rng.uniform(668, 850)
            if ((x - 540) / 265) ** 2 + ((y - 560) / 300) ** 2 < 0.93 and 668 < y < 850:
                self.dots.append((x, y, rng.uniform(3, 7), rng.uniform(0, 6.28)))
        self.jets = [(rng.uniform(360, 720), rng.uniform(0, 0.6), rng.uniform(700, 1400), rng.uniform(5, 13)) for _ in range(70)]
        self.cloud_jit = [(rng.uniform(-28, 28), rng.uniform(-18, 18), rng.uniform(0.32, 0.55)) for _ in range(40)]
        self.label_img = None
        if label_font and label:
            self.label_img = text_img(label_font, label, self.P["label"] + (255,), stroke=5, stroke_fill=(0, 0, 0, 230), shadow=(0, 4, 8, 170))
        puff = Image.new("L", (360, 220), 0)
        ImageDraw.Draw(puff).ellipse((30, 30, 330, 190), fill=235)
        self.puff = puff.filter(ImageFilter.GaussianBlur(26))

    @staticmethod
    def _profile() -> list[tuple[int, int]]:
        return [(0, 1100), (80, 1000), (170, 800), (230, 600), (250, 525), (285, 560),
                (795, 560), (830, 525), (850, 600), (910, 800), (1000, 1000), (1080, 1100)]

    def _base(self, font, label: str) -> Image.Image:
        k = 2
        w, h = self.SW * k, self.SH * k
        P = self.P
        sky = np.linspace(0, 1, h)[:, None, None]
        c0, c1 = np.array(P["sky"][0]), np.array(P["sky"][1])
        arr = (c0 * (1 - sky) + c1 * sky).repeat(w, 1).astype(np.uint8)
        im = Image.fromarray(arr, "RGB").convert("RGBA")
        d = ImageDraw.Draw(im)
        prof = [(x * k, y * k) for x, y in self._profile()]
        g0, g1 = P["ground"]
        ground = Image.fromarray((np.array(g0) * (1 - np.linspace(0, 1, h)[:, None, None]) + np.array(g1) * np.linspace(0, 1, h)[:, None, None]).repeat(w, 1).astype(np.uint8), "RGB").convert("RGBA")
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).polygon(prof + [(w, h), (0, h)], fill=255)
        im.paste(ground, (0, 0), m)
        d.line(prof, fill=P["rim"] + (255,), width=6 * k, joint="curve")
        # lake bowl (lower half-ellipse), two layers
        bowl = Image.new("L", (w, h), 0)
        ImageDraw.Draw(bowl).ellipse(((540 - 268) * k, (560 - 300) * k, (540 + 268) * k, (560 + 300) * k), fill=255)
        ImageDraw.Draw(bowl).rectangle((0, 0, w, 560 * k), fill=0)
        top = Image.new("RGBA", (w, h), P["top"] + (255,))
        low = Image.new("RGBA", (w, h), P["low"] + (255,))
        lowmask = bowl.copy()
        ImageDraw.Draw(lowmask).rectangle((0, 0, w, 655 * k), fill=0)
        im.paste(top, (0, 0), bowl)
        im.paste(low, (0, 0), lowmask)
        for x in range(285 * k, 795 * k, 34 * k):
            d.line((x, 655 * k, x + 18 * k, 655 * k), fill=(255, 255, 255, 120), width=3 * k)
        # magma chamber + conduit
        d.ellipse((200 * k, 1290 * k, 880 * k, 1700 * k), fill=P["magma"] + (255,))
        d.ellipse((330 * k, 1360 * k, 750 * k, 1640 * k), fill=tuple(min(255, c + 60) for c in P["magma"]) + (255,))
        rng = np.random.default_rng(2)
        for x_end, spread in ((540, 26), (470, 18), (615, 18)):
            pts = [(540 * k, 1310 * k)]
            for j, yy in enumerate(range(1250, 850, -50)):
                f = (1250 - yy) / 400
                xx = 540 + (x_end - 540) * f + rng.uniform(-spread, spread)
                pts.append((xx * k, yy * k))
            d.line(pts, fill=P["magma"] + (210,), width=(9 if x_end == 540 else 5) * k, joint="curve")
        # villages at the foot of the slopes
        for hx, hy in [(930, 846), (975, 946), (1040, 1052), (150, 846), (105, 946)]:
            q = 1.5
            d.rectangle(((hx - 16 * q) * k, (hy - 22 * q) * k, (hx + 16 * q) * k, hy * k), fill=(232, 220, 196, 255))
            d.polygon([((hx - 22 * q) * k, (hy - 22 * q) * k), (hx * k, (hy - 42 * q) * k), ((hx + 22 * q) * k, (hy - 22 * q) * k)], fill=(150, 70, 50, 255))
            d.rectangle(((hx - 4 * q) * k, (hy - 12 * q) * k, (hx + 4 * q) * k, hy * k), fill=(255, 205, 110, 255))
        return im.resize((self.SW, self.SH), Image.LANCZOS)

    def render(self, mode: str, age: float) -> Image.Image:
        im = self.base.copy()
        layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        P = self.P
        for x, y, r, ph in self.dots:
            a = int(150 + 100 * math.sin(age * 5 + ph))
            yy = y - ((age * 18 + ph * 10) % 40) if mode == "loaded" else y
            d.ellipse((x - r, yy - r, x + r, yy + r), fill=P["dot"] + (a,))
        if mode == "seeping":
            for x0 in (485, 595):
                for j in range(6):
                    yy = 1290 - ((age * 260 + j * 70) % 400)
                    d.polygon([(x0 - 16, yy + 22), (x0, yy - 8), (x0 + 16, yy + 22)], fill=(255, 220, 120, 230))
            glow = int(40 + 35 * math.sin(age * 8))
            d.ellipse((330, 700, 750, 870), fill=(255, 60, 30, glow))
        if mode == "burst":
            for x, delay, v, r in self.jets:
                a = age - delay
                if a < 0:
                    continue
                y = 850 - a * v
                if y < 330:
                    continue
                d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255, 230), width=3, fill=(255, 255, 255, 60))
        im.alpha_composite(layer)
        if self.label_img is not None and mode != "burst":
            paste(im, self.label_img, 540, 760)
        if mode == "burst":
            path = [(540, 515), (720, 500), (845, 535), (880, 690), (918, 790), (962, 895), (1010, 990), (1070, 1070)]
            head = clamp((age - 0.3) / 2.0) * (len(path) - 1)
            for j, (jx, jy, sc) in enumerate(self.cloud_jit):
                f = head - j * 0.16
                if f < 0:
                    break
                i0 = min(int(f), len(path) - 2)
                u = f - i0
                x = path[i0][0] + (path[i0 + 1][0] - path[i0][0]) * u + jx
                y = path[i0][1] + (path[i0 + 1][1] - path[i0][1]) * u + jy
                a = 0.62 * (1 - 0.5 * j / len(self.cloud_jit))
                puff = Image.new("RGBA", self.puff.size, (214, 228, 206, 0))
                puff.putalpha(self.puff.point(lambda v, a=a: int(v * a)))
                paste(im, puff, x, y, scale=sc)
        return im.convert("RGB")


# ---------------------------------------------------------------- base style
class Style:
    key = "?"
    music = ("", 0.0, 14.0)  # file, offset seconds, dB below voice mean

    def __init__(self, A: Assets, words: Words):
        self.A = A
        self.wd = words
        self.T = words.end + 0.10
        self.events: list[tuple[float, np.ndarray, float]] = []
        self.setup()

    def setup(self) -> None: ...

    def frame(self, t: float, i: int) -> Image.Image: ...

    def shot_at(self, t: float) -> tuple[int, dict, float, float]:
        idx = 0
        for k, s in enumerate(self.shots):
            if t >= s["t"]:
                idx = k
        s = self.shots[idx]
        t1 = self.shots[idx + 1]["t"] if idx + 1 < len(self.shots) else self.T
        return idx, s, s["t"], t1


# ================================================================ A: PUNCH
class StyleA(Style):
    key = "A"
    music = ("Volatile_Reaction.mp3", 27.0, 13.0)
    YELLOW = (255, 225, 77, 255)

    def setup(self) -> None:
        w = self.wd
        S = w.at
        self.shots = [
            {"t": 0.0, "img": "lake1986", "z0": 1.0, "z1": 1.07, "fx": 0.55, "fy": 0.5, "look": "punch"},
            {"t": S(0, "single"), "img": "nyoslake", "z0": 1.2, "z1": 1.08, "fx": 0.6, "fy": 0.55, "look": "punchbright", "snap": True},
            {"t": S(0, "not"), "img": "cow", "z0": 1.0, "z1": 1.1, "fx": 0.5, "fy": 0.55, "look": "punch", "snap": True, "flash": True},
            {"t": S(1, "its"), "img": "@loaded", "z0": 1.0, "z1": 1.08, "fx": 0.5, "fy": 0.5, "look": "", "snap": True},
            {"t": S(1, "carbon"), "img": "@loaded", "z0": 1.55, "z1": 1.7, "fx": 0.5, "fy": 0.53, "look": "", "snap": True},
            {"t": S(2, "in"), "img": "timeline", "z0": 1.0, "z1": 1.12, "fx": 0.45, "fy": 0.55, "look": "punch", "snap": True, "flash": True},
            {"t": S(2, "shaken"), "img": "@burst", "z0": 1.0, "z1": 1.06, "fx": 0.5, "fy": 0.45, "look": "", "snap": True},
            {"t": S(2, "heavier"), "img": "@burst", "z0": 1.45, "z1": 1.55, "fx": 0.8, "fy": 0.55, "look": "", "snap": True, "age0": S(2, "shaken")},
            {"t": S(2, "rolled"), "img": "hills", "z0": 1.05, "z1": 1.2, "fx": 0.5, "fy": 0.4, "look": "punch", "snap": True, "fog": True},
            {"t": S(2, "sleeping"), "img": "timeline", "z0": 1.3, "z1": 1.45, "fx": 0.75, "fy": 0.55, "look": "night", "snap": True, "fog": True},
            {"t": S(3, "creepiest"), "img": "@seeping", "z0": 1.0, "z1": 1.08, "fx": 0.5, "fy": 0.6, "look": "", "snap": True, "flash": True},
            {"t": S(3, "still"), "img": "@seeping", "z0": 1.6, "z1": 1.75, "fx": 0.5, "fy": 0.68, "look": "", "snap": True, "pulse": True},
            {"t": S(4, "so"), "img": "lake2001", "z0": 1.05, "z1": 1.2, "fx": 0.3, "fy": 0.5, "look": "punch", "snap": True, "flash": True},
            {"t": S(4, "nonstop"), "img": "vent", "z0": 1.15, "z1": 1.35, "fx": 0.38, "fy": 0.42, "look": "punch", "snap": True},
            {"t": S(4, "every"), "img": "lake1992", "z0": 1.0, "z1": 1.12, "fx": 0.5, "fy": 0.55, "look": "punch", "snap": True},
            {"t": S(4, "why"), "img": "lake1986", "z0": 1.0, "z1": 1.0, "fx": 0.55, "fy": 0.5, "look": "punch", "loop": True},
        ]
        self.solo = {"1,746", "drowned", "dioxide", "in 1986", "soda", "still", "nonstop", "fountain", "why"}
        self.chunks = w.chunks(2, 13, self.solo)
        self.cap_cache: dict = {}
        f = self.A.font("Anton-400.ttf", 230)
        self.h1 = text_img(f, "1,746 DEAD", (255, 255, 255, 255), stroke=10, shadow=(0, 10, 12, 170))
        self.h2 = text_img(f, "0 DROWNED", self.YELLOW, stroke=10, shadow=(0, 10, 12, 170))
        self.t_drown = S(0, "not")
        self.t_s1 = w.sentence_start(1)
        self.t_why = S(4, "why")
        self.bubbles = Bubbles(80, 4, (0, 300, W, H + 200), speed=(1100, 2600), radius=(8, 42))
        self.diag = LakeDiagram("punch", self.A.font("Anton-400.ttf", 120), "CO2")
        # sound design
        self.events.append((0.0, sfx.boom(), 0.9))
        for s in self.shots[1:]:
            if s.get("loop"):
                continue
            self.events.append((s["t"] - 0.08, sfx.whoosh(0.32, seed=int(s["t"] * 10)), 0.32))
            if s.get("flash"):
                self.events.append((s["t"], sfx.boom(0.9), 0.35))
        self.events.append((self.t_drown, sfx.stamp(), 0.7))
        self.events.append((S(1, "volcanic"), sfx.riser(S(2, "in") - S(1, "volcanic")), 0.4))
        self.events.append((S(2, "shaken") - 0.05, sfx.whoosh(0.7, 21), 0.45))
        for c in self.chunks:
            if c[0]["word"].lower() in self.solo:
                self.events.append((c[0]["start"], sfx.pop(), 0.35))

    def caption(self, idx: int, chunk: list[dict], t: float) -> Image.Image:
        active = max([k for k, x in enumerate(chunk) if x["start"] <= t + 0.03] or [0])
        key = (idx, active)
        if key not in self.cap_cache:
            emph = len(chunk) == 1 and chunk[0]["word"].lower() in self.solo
            f = self.A.font("Montserrat-900.ttf", 150 if emph else 118)
            items = [{"text": x["word"].upper(), "fill": self.YELLOW if (k == active or emph) else (255, 255, 255, 255)}
                     for k, x in enumerate(chunk)]
            self.cap_cache[key] = rich_text(f, items, stroke=12, shadow=(0, 9, 10, 180), max_w=960, line_gap=-22)
        return self.cap_cache[key]

    def frame(self, t: float, i: int) -> Image.Image:
        _k, s, t0, t1 = self.shot_at(t)
        p = lin(t, t0, t1)
        extra = 1.0
        if s.get("snap"):
            extra = 1 + 0.14 * (1 - ease_out(lin(t, t0, t0 + 0.2)))
        jit = (0.0, 0.0)
        for ts, amp in ((0.0, 26), (self.t_drown, 30)):
            if ts <= t < ts + 0.35:
                d = 1 - lin(t, ts, ts + 0.35)
                jit = (math.sin(t * 91) * amp * d, math.cos(t * 77) * amp * d)
        if s["img"].startswith("@"):
            src = self.diag.render(s["img"][1:], t - s.get("age0", t0))
        else:
            src = self.A.prepared(s["img"], W, H, s["look"])
        bg, _ = kenburns(src, W, H, p, s["z0"], s["z1"], s["fx"], s["fy"], jitter=jit, extra_zoom=extra)
        fr = bg.convert("RGBA")
        fr.alpha_composite(vgradient(700, 170, 0), dest=(0, 0))
        fr.alpha_composite(vgradient(900, 0, 190), dest=(0, H - 900))
        if s.get("fog"):
            fog = fog_texture()
            y = int(-H + (t - t0) * 420)
            paste(fr, fog, W / 2, y + H, alpha=0.75)
        if s.get("bubbles"):
            layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            self.bubbles.draw(layer, t - t0)
            fr.alpha_composite(layer)
        if s.get("pulse"):
            pr = 0.5 + 0.5 * math.sin((t - t0) * 12)
            fr.alpha_composite(vignette(int(150 + 90 * pr)))
        fr.alpha_composite(vignette(120))
        # flash on hard cuts
        for sh in self.shots:
            if sh.get("flash") and sh["t"] <= t < sh["t"] + 0.12:
                a = int(200 * (1 - lin(t, sh["t"], sh["t"] + 0.12)))
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, a)))
        # hook headline (frame 0 is already fully readable: no fade-in)
        if t < self.t_s1 + 0.2:
            out = lin(t, self.t_s1 - 0.05, self.t_s1 + 0.2)
            paste(fr, self.h1, W / 2, 420 - 60 * ease_out(out), alpha=1 - out)
            if t >= self.t_drown:
                sc = 1.0 + 0.6 * (1 - ease_out_back(lin(t, self.t_drown, self.t_drown + 0.16), 2.2))
                paste(fr, self.h2, W / 2, 650 - 60 * ease_out(out), alpha=(1 - out) * lin(t, self.t_drown, self.t_drown + 0.05), scale=sc)
        if t >= self.t_why:
            paste(fr, self.h1, W / 2, 420, alpha=ease_out(lin(t, self.t_why, self.T - 0.05)))
        # captions
        ci, ch = chunk_at(self.chunks, t, hold=0.25)
        if ch and t < self.t_why:
            cap = self.caption(ci, ch, t)
            sc = 0.72 + 0.28 * ease_out_back(lin(t, ch[0]["start"] - 0.02, ch[0]["start"] + 0.13), 2.0)
            paste(fr, cap, W / 2, 1190, scale=sc)
        return fr.convert("RGB")


# ================================================================ B: PREMIUM
class StyleB(Style):
    key = "B"
    music = ("Echoes_of_Time.mp3", 15.0, 15.0)
    WARM = (226, 214, 190)
    CARD = (64, 204, 952, 1210)  # x, y, w, h

    def setup(self) -> None:
        w = self.wd
        S = w.at
        self.shots = [
            {"t": 0.0, "img": "lake1986", "z0": 1.0, "z1": 1.06, "fx": 0.6, "fy": 0.5, "credit": "USGS · Lake Nyos, August 1986"},
            {"t": S(1, "its"), "img": "nyoslake", "z0": 1.02, "z1": 1.1, "fx": 0.55, "fy": 0.55, "credit": "USGS · The lake after the eruption"},
            {"t": S(1, "volcanic"), "img": "@loaded", "z0": 1.0, "z1": 1.06, "fx": 0.5, "fy": 0.5, "credit": "Illustration · CO2 held in the deep layer"},
            {"t": S(2, "burst"), "img": "@burst", "z0": 1.0, "z1": 1.05, "fx": 0.5, "fy": 0.48, "credit": "Illustration · The 1986 eruption"},
            {"t": S(2, "rolled"), "img": "hills", "z0": 1.0, "z1": 1.1, "fx": 0.5, "fy": 0.45, "look": "night", "fog": True, "credit": "Northwest Cameroon highlands"},
            {"t": S(2, "sleeping"), "img": "timeline", "z0": 1.15, "z1": 1.25, "fx": 0.6, "fy": 0.55, "credit": "USGS · Shoreline villages, 1986"},
            {"t": S(3, "creepiest"), "img": "@seeping", "z0": 1.0, "z1": 1.06, "fx": 0.5, "fy": 0.6, "credit": "Illustration · CO2 still seeping in"},
            {"t": S(4, "so"), "img": "lake2001", "z0": 1.0, "z1": 1.08, "fx": 0.35, "fy": 0.5, "credit": "USGS · Degassing platform, 2001"},
            {"t": S(4, "nonstop"), "img": "vent", "z0": 1.1, "z1": 1.2, "fx": 0.38, "fy": 0.45, "credit": "USGS · The vent, running nonstop"},
            {"t": S(4, "every"), "img": "lake1992", "z0": 1.0, "z1": 1.06, "fx": 0.5, "fy": 0.55, "credit": "USGS · Fishermen on Lake Nyos, 1992"},
            {"t": S(4, "why"), "img": "lake1986", "z0": 1.0, "z1": 1.0, "fx": 0.6, "fy": 0.5, "credit": "USGS · Lake Nyos, August 1986", "loop": True},
        ]
        _x, _y, cw, chh = self.CARD
        self.mask = rounded_mask(cw, chh, 36)
        self.shadow = Image.new("RGBA", (cw + 160, chh + 160), (0, 0, 0, 0))
        ImageDraw.Draw(self.shadow).rounded_rectangle((80, 100, 80 + cw, 100 + chh), 36, fill=(0, 0, 0, 170))
        self.shadow = self.shadow.filter(ImageFilter.GaussianBlur(34))
        self.border = Image.new("RGBA", (cw, chh), (0, 0, 0, 0))
        ImageDraw.Draw(self.border).rounded_rectangle((0, 0, cw - 1, chh - 1), 36, outline=(255, 255, 255, 34), width=2)
        lab = self.A.font("Inter-600.ttf", 31)
        self.label_l = text_img(lab, "LAKE NYOS  ·  CAMEROON", self.WARM + (255,), tracking=5)
        self.label_r = text_img(lab, "AUG 21, 1986", (150, 145, 135, 255), tracking=5)
        serif = self.A.font("InstrumentSerif-400.ttf", 104)
        serif_i = self.A.font("InstrumentSerif-400i.ttf", 104)
        self.hl1 = text_img(serif, "The lake that killed", (255, 255, 255, 255), shadow=(0, 4, 14, 150))
        self.hl2 = text_img(serif, "1,746 people.", (255, 255, 255, 255), shadow=(0, 4, 14, 150))
        self.hl3 = text_img(serif_i, "None of them drowned.", self.WARM + (255,), shadow=(0, 4, 14, 150))
        self.credit_font = self.A.font("Inter-500.ttf", 24)
        self.chunks = w.chunks(5, 26)
        self.cap_font = self.A.font("Inter-600.ttf", 66)
        self.diag = LakeDiagram("soft", self.A.font("Inter-600.ttf", 40), "Dissolved CO2")
        self.t_s1 = w.sentence_start(1)
        self.t_drown = S(0, "not")
        self.t_why = S(4, "why")
        self.bg = Image.new("RGBA", (W, H), (12, 12, 14, 255))
        glow = vgradient(900, 0, 0, color=(40, 34, 26))
        self.bg.alpha_composite(glow)
        for s in self.shots:
            s.setdefault("look", "soft")
            s["credit_img"] = text_img(self.credit_font, s["credit"], (255, 255, 255, 200), shadow=(0, 2, 6, 160))
        for ts in (self.t_s1, w.sentence_start(3), self.t_why):
            self.events.append((ts - 0.5, sfx.swell(1.4), 0.22))

    def card_image(self, s: dict, t: float, t0: float, t1: float) -> Image.Image:
        _x, _y, cw, chh = self.CARD
        if s["img"].startswith("@"):
            src = self.diag.render(s["img"][1:], t - t0)
        else:
            src = self.A.prepared(s["img"], cw, chh, s["look"])
        p = lin(t, t0 - 0.6, t1 + 0.6)
        im, _ = kenburns(src, cw, chh, p, s["z0"], s["z1"], s["fx"], s["fy"])
        if s.get("fog"):
            im = im.convert("RGBA")
            paste(im, fog_texture(), cw / 2, -H + (t - t0) * 300 + H, alpha=0.6)
            im = im.convert("RGB")
        return im

    def frame(self, t: float, i: int) -> Image.Image:
        fr = self.bg.copy()
        x, y, cw, chh = self.CARD
        k, s, t0, t1 = self.shot_at(t)
        card = self.card_image(s, t, t0, t1)
        xf = 0.55
        if k > 0 and t < t0 + xf:
            prev = self.shots[k - 1]
            pim = self.card_image(prev, t, prev["t"], t0)
            card = Image.blend(pim, card, ease_in_out(lin(t, t0, t0 + xf)))
        card = card.convert("RGBA")
        g = Image.new("RGBA", (cw, 520), (0, 0, 0, 0))
        g.putalpha(Image.fromarray(np.linspace(0, 205, 520).astype(np.uint8)[:, None].repeat(cw, 1)))
        card.alpha_composite(g, dest=(0, chh - 520))
        card.alpha_composite(self.border)
        # photo credit chip, bottom-left inside the card
        cr = s["credit_img"]
        headline_on = t < self.t_s1 + 0.4 or t >= self.t_why
        if not headline_on:
            card.alpha_composite(cr, dest=(34, chh - cr.height - 26))
        fr.alpha_composite(self.shadow, dest=(x - 80, y - 80))
        fr.paste(card, (x, y), self.mask)
        paste(fr, self.label_l, x + self.label_l.width / 2 - 4, 150)
        paste(fr, self.label_r, x + cw - self.label_r.width / 2 + 4, 150)
        # serif headline over the card (hook) -- visible from frame 0
        if headline_on:
            if t >= self.t_why:
                a = ease_out(lin(t, self.t_why, self.T))
                a3 = 0.0
            else:
                a = 1 - ease_out(lin(t, self.t_s1 - 0.1, self.t_s1 + 0.4))
                a3 = a * ease_out(lin(t, self.t_drown, self.t_drown + 0.45))
            base_y = y + chh - 330
            paste(fr, self.hl1, W / 2, base_y, alpha=a)
            paste(fr, self.hl2, W / 2, base_y + 104, alpha=a)
            paste(fr, self.hl3, W / 2, base_y + 222 + 14 * (1 - a3), alpha=a3)
        # karaoke captions under the card (from sentence 2 on)
        _ci, ch = chunk_at(self.chunks, t, hold=0.5)
        if ch and self.t_s1 - 0.05 <= t < self.t_why:
            items = [{"text": xw["word"], "fill": (255, 255, 255, 255 if xw["start"] <= t + 0.02 else 92)} for xw in ch]
            cap = rich_text(self.cap_font, items, shadow=(0, 3, 10, 150), max_w=930, line_gap=-6)
            a = ease_out(lin(t, ch[0]["start"] - 0.05, ch[0]["start"] + 0.2))
            paste(fr, cap, W / 2, y + chh + 92 + 14 * (1 - a), alpha=a)
        fr.alpha_composite(grain_frames(10)[(i // 2) % 6])
        return fr.convert("RGB")


# ================================================================ C: CASE FILE
class StyleC(Style):
    key = "C"
    music = ("Darkest_Child.mp3", 6.0, 13.0)
    RED = (255, 59, 48)
    PAPER = (236, 230, 214)
    YELLOW = (255, 214, 10)
    PHOTO = (760, 590)

    def setup(self) -> None:
        w = self.wd
        S = w.at
        self.exhibits = [
            {"t": 0.0, "img": "lake1986", "fx": 0.6, "fy": 0.5, "z0": 1.0, "z1": 1.08, "label": "EXHIBIT A  ·  LAKE NYOS, AUG 1986", "rot": -2.5},
            {"t": S(1, "its"), "img": "@loaded", "fx": 0.5, "fy": 0.5, "z0": 1.0, "z1": 1.08, "label": "EXHIBIT B  ·  THE DEEP LAYER", "rot": 2.0},
            {"t": S(2, "in"), "img": "@burst", "fx": 0.5, "fy": 0.5, "z0": 1.0, "z1": 1.06, "label": "EXHIBIT C  ·  THE ERUPTION", "rot": -1.6},
            {"t": S(2, "the", 1), "img": "landsat", "fx": 0.5, "fy": 0.45, "z0": 1.0, "z1": 1.12, "label": "EXHIBIT D  ·  SATELLITE, LAKE NYOS", "rot": 1.5, "ring": (0.505, 0.43)},
            {"t": S(2, "sleeping"), "img": "timeline", "fx": 0.6, "fy": 0.55, "z0": 1.0, "z1": 1.1, "label": "NYOS · KAM · CHA · SUBUM", "rot": -1.8},
            {"t": S(3, "creepiest"), "img": "@seeping", "fx": 0.5, "fy": 0.62, "z0": 1.0, "z1": 1.08, "label": "EXHIBIT E  ·  STILL SEEPING IN", "rot": 2.2},
            {"t": S(4, "so"), "img": "vent", "fx": 0.4, "fy": 0.5, "z0": 1.0, "z1": 1.12, "label": "EXHIBIT F  ·  DEGASSING PIPE", "rot": -2.4},
            {"t": S(4, "every"), "img": "lake1992", "fx": 0.5, "fy": 0.55, "z0": 1.0, "z1": 1.08, "label": "LAKE NYOS, 1992", "rot": -1.2},
            {"t": S(4, "why"), "img": "lake1986", "fx": 0.6, "fy": 0.5, "z0": 1.0, "z1": 1.0, "label": "EXHIBIT A  ·  LAKE NYOS, AUG 1986", "rot": -2.5, "loop": True},
        ]
        self.shots = self.exhibits
        self.tags = [
            (0.0, "1,746", "DEAD IN ONE NIGHT", self.RED),
            (S(1, "its"), "CO2", "DISSOLVED IN THE DEEP WATER", self.YELLOW),
            (S(2, "in"), "1986", "THE LAKE ERUPTED", (255, 255, 255)),
            (S(2, "the", 1), "25 KM", "HOW FAR THE CLOUD ROLLED", self.YELLOW),
            (S(3, "creepiest"), "STILL", "SEEPING IN TODAY", self.RED),
            (S(4, "so"), "24/7", "VENTED SINCE 2001", (255, 255, 255)),
            (S(4, "why"), "1,746", "DEAD IN ONE NIGHT", self.RED),
        ]
        big = self.A.font("Anton-400.ttf", 250)
        small = self.A.font("Montserrat-800.ttf", 44)
        self.tag_imgs = [
            (t0, self._big(big, txt, col), text_img(small, sub, (255, 255, 255, 235), tracking=3, shadow=(0, 3, 8, 200)), sub)
            for t0, txt, sub, col in self.tags
        ]
        hf = self.A.font("SpecialElite-400.ttf", 36)
        self.header = text_img(hf, "CASE FILE  ·  LAKE NYOS, CAMEROON", self.PAPER + (255,))
        self.header_r = text_img(hf, "21.08.1986", self.PAPER + (200,))
        self.label_font = self.A.font("SpecialElite-400.ttf", 30)
        self.stamp = self._stamp("NOT DROWNED")
        self.chunks = w.chunks(3, 18)
        self.cap_font = self.A.font("Montserrat-800.ttf", 72)
        self.diag = LakeDiagram("doc", self.A.font("SpecialElite-400.ttf", 46), "DISSOLVED CO2")
        self.cap_cache: dict = {}
        self.t_drown = S(0, "drowned")
        self.t_s1 = w.sentence_start(1)
        self.t_why = S(4, "why")
        pw, ph = self.PHOTO
        self.bubbles = Bubbles(46, 7, (0, int(ph * 0.35), pw, ph + 60), speed=(260, 640), radius=(4, 16))
        # sound
        self.events.append((0.0, sfx.boom(), 0.8))
        self.events.append((self.t_drown, sfx.stamp(), 0.9))
        for e in self.exhibits[1:]:
            self.events.append((e["t"], sfx.shutter(int(e["t"] * 7)), 0.55))
        for t0, _, _, sub in self.tag_imgs[1:]:
            for j in range(0, min(len(sub), 18), 2):
                self.events.append((t0 + j * 0.022, sfx.type_key(j + int(t0 * 10)), 0.35))
        self.events.append((S(1, "volcanic"), sfx.riser(S(2, "in") - S(1, "volcanic")), 0.35))

    def _big(self, f, txt: str, col) -> Image.Image:
        if txt == "CO2":
            co = text_img(f, "CO", col + (255,), stroke=6, shadow=(0, 8, 14, 190))
            f2 = self.A.font("Anton-400.ttf", 130)
            two = text_img(f2, "2", col + (255,), stroke=5, shadow=(0, 8, 14, 190))
            pad_co, pad_two = 6 + 14 * 3 + 8 + 4, 5 + 14 * 3 + 8 + 4
            base_co = pad_co + f.getmetrics()[0]
            base_two = pad_two + f2.getmetrics()[0]
            x2 = co.width - pad_co - pad_two + 8
            y2 = base_co - base_two + 38
            out = Image.new("RGBA", (x2 + two.width, max(co.height, y2 + two.height)), (0, 0, 0, 0))
            out.alpha_composite(co, dest=(0, 0))
            out.alpha_composite(two, dest=(x2, y2))
            return out
        return text_img(f, txt, col + (255,), stroke=6, shadow=(0, 8, 14, 190))

    def _stamp(self, txt: str) -> Image.Image:
        f = self.A.font("Anton-400.ttf", 118)
        t = text_img(f, txt, (214, 38, 38, 255))
        pad = 28
        im = Image.new("RGBA", (t.width + pad * 2, t.height + pad), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((6, 6, im.width - 7, im.height - 7), 18, outline=(214, 38, 38, 255), width=10)
        im.alpha_composite(t, dest=(pad, pad // 2))
        rng = np.random.default_rng(1)
        holes = (rng.random((im.height, im.width)) > 0.2).astype(np.uint8)
        holes = Image.fromarray(holes * 255).filter(ImageFilter.GaussianBlur(1.2)).point(lambda v: 255 if v > 150 else int(v * 0.5))
        a = Image.fromarray(np.minimum(np.array(im.getchannel("A")), np.array(holes)))
        im.putalpha(a)
        return im.rotate(13, resample=Image.BICUBIC, expand=True)

    def polaroid(self, e: dict, t: float, t0: float, t1: float) -> Image.Image:
        pw, ph = self.PHOTO
        border, bottom = 26, 92
        if e["img"].startswith("@"):
            src = self.diag.render(e["img"][1:], t - t0)
        else:
            src = self.A.prepared(e["img"], pw, ph, e.get("look", "doc"))
        p = lin(t, t0, t1 + 0.3)
        photo, box = kenburns(src, pw, ph, p, e["z0"], e["z1"], e["fx"], e["fy"])
        photo = photo.convert("RGBA")
        if e.get("ring"):
            rx = (e["ring"][0] * src.width - box[0]) / (box[2] - box[0]) * pw
            ry = (e["ring"][1] * src.height - box[1]) / (box[3] - box[1]) * ph
            layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            for off in (0.0, 0.55):
                age = (t - t0 - off) % 1.1
                r = 18 + age / 1.1 * 420
                a = int(255 * (1 - age / 1.1))
                d.ellipse((rx - r, ry - r, rx + r, ry + r), outline=self.RED + (a,), width=7)
            d.ellipse((rx - 12, ry - 12, rx + 12, ry + 12), fill=self.RED + (255,))
            photo.alpha_composite(layer)
        if e.get("bubbles"):
            layer = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            self.bubbles.draw(layer, (t - t0) % 2.4)
            photo.alpha_composite(layer)
        card = Image.new("RGBA", (pw + border * 2, ph + border + bottom), self.PAPER + (255,))
        card.alpha_composite(photo, dest=(border, border))
        lab = text_img(self.label_font, e["label"], (40, 36, 30, 255))
        card.alpha_composite(lab, dest=(border, ph + border + (bottom - lab.height) // 2 + 2))
        tape = Image.new("RGBA", (230, 60), (226, 214, 170, 150))
        tape = tape.rotate(-4, expand=True, resample=Image.BICUBIC)
        out = Image.new("RGBA", (card.width, card.height + 40), (0, 0, 0, 0))
        out.alpha_composite(card, dest=(0, 30))
        out.alpha_composite(tape, dest=(card.width // 2 - tape.width // 2, 0))
        return out

    def place_polaroid(self, fr: Image.Image, e: dict, t: float, t0: float, t1: float, enter: float) -> None:
        im = self.polaroid(e, t, t0, t1)
        k = ease_out(enter)
        rot = e["rot"] + (1 - k) * 9
        im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
        shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
        shadow.putalpha(im.getchannel("A").point(lambda v: int(v * 0.55)))
        shadow = shadow.filter(ImageFilter.GaussianBlur(16))
        cx = W / 2 + (1 - k) * 760
        paste(fr, shadow, cx + 10, 985 + 22)
        paste(fr, im, cx, 985)

    def caption(self, idx: int, chunk: list[dict], t: float) -> Image.Image:
        active = max([k for k, x in enumerate(chunk) if x["start"] <= t + 0.03] or [0])
        key = (idx, active)
        if key not in self.cap_cache:
            items = [{"text": x["word"], "fill": (12, 12, 12, 255), "box": self.YELLOW + (255,)} if k == active
                     else {"text": x["word"], "fill": (255, 255, 255, 255)} for k, x in enumerate(chunk)]
            self.cap_cache[key] = rich_text(self.cap_font, items, stroke=8, shadow=(0, 6, 8, 170), max_w=980, line_gap=-4)
        return self.cap_cache[key]

    def frame(self, t: float, i: int) -> Image.Image:
        k, e, t0, t1 = self.shot_at(t)
        bg_name = "nyoslake" if e["img"].startswith("@") else e["img"]
        fr = self.A.backdrop(bg_name, e.get("look", "doc"), 0.32).copy()
        fr.alpha_composite(vignette(200))
        enter = 1.0 if k == 0 else lin(t, t0, t0 + 0.32)
        if k > 0 and enter < 1:
            prev = self.exhibits[k - 1]
            self.place_polaroid(fr, prev, t, prev["t"], t0, 1.0)
        self.place_polaroid(fr, e, t, t0, t1, enter)
        # stamp
        if self.t_drown <= t < self.t_s1 + 0.05:
            sc = 1 + 0.8 * (1 - ease_out(lin(t, self.t_drown, self.t_drown + 0.12)))
            paste(fr, self.stamp, W / 2 + 120, 1080, alpha=lin(t, self.t_drown, self.t_drown + 0.04), scale=sc)
        # header
        fr.alpha_composite(vgradient(240, 210, 0), dest=(0, 0))
        paste(fr, self.header, 70 + self.header.width / 2, 132)
        paste(fr, self.header_r, W - 70 - self.header_r.width / 2, 132)
        dot = 0.5 + 0.5 * math.sin(t * 6)
        ImageDraw.Draw(fr).ellipse((W - 70 - self.header_r.width - 40, 122, W - 70 - self.header_r.width - 20, 142), fill=self.RED + (int(120 + 135 * dot),))
        # evidence tag (big word + typed label)
        ti = max(j for j, x in enumerate(self.tag_imgs) if x[0] <= t)
        t0g, big, sub, subtxt = self.tag_imgs[ti]
        a_in = 1.0 if ti == 0 else ease_out(lin(t, t0g, t0g + 0.18))
        sc = 1 + 0.25 * (1 - ease_out_back(lin(t, t0g, t0g + 0.2))) if ti > 0 else 1.0
        paste(fr, big, W / 2, 400, alpha=a_in, scale=sc)
        reveal = 1.0 if ti == 0 else lin(t, t0g, t0g + 0.022 * len(subtxt))
        if reveal > 0:
            cw = int(sub.width * reveal)
            if cw > 0:
                part = sub.crop((0, 0, cw, sub.height))
                paste(fr, part, W / 2 - sub.width / 2 + cw / 2, 575)
        # captions
        ci, ch = chunk_at(self.chunks, t, hold=0.3)
        if ch and t < self.t_why:
            cap = self.caption(ci, ch, t)
            sc = 0.85 + 0.15 * ease_out_back(lin(t, ch[0]["start"] - 0.02, ch[0]["start"] + 0.12))
            paste(fr, cap, W / 2, 1460, scale=sc)
        fr.alpha_composite(grain_frames(14)[(i // 2) % 6])
        return fr.convert("RGB")


# ================================================================ D: A + C MIX
class StyleD(StyleC):
    """Owner's mix (2026-10-31): A's full-bleed fast cuts, pop captions,
    hits and voice + C's case-file layer (number tags, typed labels,
    evidence Polaroids for the low-res photos, stamp, satellite ring)."""

    key = "D"
    music = ("Darkest_Child.mp3", 6.0, 12.0)
    CAP_Y = 1460
    CARD_Y = 1005
    PHOTO = (700, 540)
    CAP_YELLOW = (255, 225, 77, 255)
    WHITE = (255, 255, 255)

    def setup(self) -> None:
        w = self.wd
        S = w.at
        self.shots = [
            {"t": 0.0, "img": "lake1986", "z0": 1.0, "z1": 1.07, "fx": 0.55, "fy": 0.5, "look": "punch"},
            {"t": S(0, "single"), "img": "nyoslake", "z0": 1.2, "z1": 1.08, "fx": 0.6, "fy": 0.55, "look": "punchbright", "snap": True},
            {"t": S(0, "not"), "img": "cow", "card": True, "label": "EXHIBIT A  ·  CATTLE, AUG 1986", "rot": -2.5,
                 "z0": 1.0, "z1": 1.08, "fx": 0.5, "fy": 0.55, "flash": True},
            {"t": S(1, "its"), "img": "@loaded", "z0": 1.0, "z1": 1.08, "fx": 0.5, "fy": 0.5, "snap": True},
            {"t": S(1, "carbon"), "img": "@loaded", "z0": 1.55, "z1": 1.7, "fx": 0.5, "fy": 0.53, "snap": True},
            {"t": S(2, "in"), "img": "timeline", "z0": 1.0, "z1": 1.12, "fx": 0.45, "fy": 0.55, "look": "punch", "snap": True, "flash": True},
            {"t": S(2, "shaken"), "img": "@burst", "z0": 1.0, "z1": 1.06, "fx": 0.5, "fy": 0.45, "snap": True},
            {"t": S(2, "heavier"), "img": "@burst", "z0": 1.45, "z1": 1.55, "fx": 0.8, "fy": 0.55, "snap": True, "age0": S(2, "shaken")},
            {"t": S(2, "rolled"), "img": "landsat", "card": True, "label": "EXHIBIT B  ·  SATELLITE, LAKE NYOS", "rot": 1.8,
                 "ring": (0.505, 0.43), "z0": 1.0, "z1": 1.12, "fx": 0.5, "fy": 0.45, "flash": True},
            {"t": S(2, "sleeping"), "img": "timeline", "card": True, "label": "NYOS  ·  KAM  ·  CHA  ·  SUBUM", "rot": -1.6, "z0": 1.0, "z1": 1.1, "fx": 0.6, "fy": 0.55},
            {"t": S(3, "creepiest"), "img": "@seeping", "z0": 1.0, "z1": 1.08, "fx": 0.5, "fy": 0.6, "snap": True, "flash": True},
            {"t": S(3, "still"), "img": "@seeping", "z0": 1.6, "z1": 1.75, "fx": 0.5, "fy": 0.68, "snap": True, "pulse": True},
            {"t": S(4, "so"), "img": "lake2001", "z0": 1.05, "z1": 1.2, "fx": 0.3, "fy": 0.5, "look": "punch", "snap": True, "flash": True},
            {"t": S(4, "nonstop"), "img": "vent", "z0": 1.15, "z1": 1.35, "fx": 0.38, "fy": 0.42, "look": "punch", "snap": True},
            {"t": S(4, "every"), "img": "lake1992", "z0": 1.0, "z1": 1.12, "fx": 0.5, "fy": 0.55, "look": "punch", "snap": True},
            {"t": S(4, "why"), "img": "lake1986", "z0": 1.0, "z1": 1.0, "fx": 0.55, "fy": 0.5, "look": "punch", "loop": True},
        ]
        self.exhibits = self.shots
        tags = [
            (0.0, "1,746", "DEAD IN ONE NIGHT", self.RED),
            (S(1, "its"), "CO2", "DISSOLVED IN THE DEEP WATER", self.CAP_YELLOW[:3]),
            (S(2, "in"), "1986", "THE LAKE ERUPTED", self.WHITE),
            (S(2, "rolled"), "25 KM", "HOW FAR THE CLOUD ROLLED", self.CAP_YELLOW[:3]),
            (S(3, "creepiest"), "STILL", "SEEPING IN TODAY", self.RED),
            (S(4, "so"), "24/7", "VENTED SINCE 2001", self.WHITE),
            (S(4, "why"), "1,746", "DEAD IN ONE NIGHT", self.RED),
        ]
        big = self.A.font("Anton-400.ttf", 250)
        small = self.A.font("Montserrat-800.ttf", 44)
        self.tag_imgs = [
            (t0, self._big(big, txt, col), text_img(small, sub, (255, 255, 255, 240), tracking=3, shadow=(0, 3, 8, 220)), sub)
            for t0, txt, sub, col in tags
        ]
        hf = self.A.font("SpecialElite-400.ttf", 36)
        self.header = text_img(hf, "CASE FILE  ·  LAKE NYOS, CAMEROON", self.PAPER + (255,), shadow=(0, 2, 6, 200))
        self.header_r = text_img(hf, "21.08.1986", self.PAPER + (210,), shadow=(0, 2, 6, 200))
        self.label_font = self.A.font("SpecialElite-400.ttf", 30)
        self.stamp = self._stamp("NOT DROWNED")
        self.diag = LakeDiagram("punch", None, "")
        self.solo = {"1,746", "drowned", "dioxide", "in 1986", "soda", "still", "nonstop", "fountain", "why"}
        self.chunks = w.chunks(2, 13, self.solo)
        self.cap_cache: dict = {}
        self.t_drown = S(0, "drowned")
        self.t_s1 = w.sentence_start(1)
        self.t_why = S(4, "why")
        # Sound. Owner (2026-10-31): no sound on cuts ("that bouncy noise ...
        # when switching between frames, it's annoying"). So no whoosh, no
        # flash boom, no shutter on a cut, and no pop on big words. What is
        # left is tied to a moment, not a cut: one low boom on frame 0, the
        # stamp thud, and soft typewriter ticks while a label types out. (The
        # riser went too: it peaked on the "In 1986" cut.)
        self.events.append((0.0, sfx.boom(), 0.85))
        self.events.append((self.t_drown, sfx.stamp(), 0.9))
        for t0, _, _, sub in self.tag_imgs[1:]:
            for j in range(0, min(len(sub), 18), 2):
                self.events.append((t0 + j * 0.022, sfx.type_key(j + int(t0 * 10)), 0.3))

    def caption(self, idx: int, chunk: list[dict], t: float) -> Image.Image:
        active = max([k for k, x in enumerate(chunk) if x["start"] <= t + 0.03] or [0])
        key = (idx, active)
        if key not in self.cap_cache:
            emph = len(chunk) == 1 and chunk[0]["word"].lower() in self.solo
            f = self.A.font("Montserrat-900.ttf", 140 if emph else 112)
            items = [{"text": x["word"].upper(), "fill": self.CAP_YELLOW if (k == active or emph) else (255, 255, 255, 255)}
                     for k, x in enumerate(chunk)]
            self.cap_cache[key] = rich_text(f, items, stroke=12, shadow=(0, 9, 10, 190), max_w=960, line_gap=-22)
        return self.cap_cache[key]

    def _shake(self, t: float) -> tuple[float, float]:
        for ts, amp in ((0.0, 24), (self.t_drown, 30)):
            if ts <= t < ts + 0.35:
                d = 1 - lin(t, ts, ts + 0.35)
                return (math.sin(t * 91) * amp * d, math.cos(t * 77) * amp * d)
        return (0.0, 0.0)

    def frame(self, t: float, i: int) -> Image.Image:
        _, s, t0, t1 = self.shot_at(t)
        p = lin(t, t0, t1)
        jit = self._shake(t)
        if s.get("card"):
            fr = self.A.backdrop(s["img"], "doc", 0.36).copy()
            fr.alpha_composite(vignette(170))
            enter = lin(t, t0, t0 + 0.2)
            im = self.polaroid(s, t, t0, t1)
            im = im.rotate(s["rot"] + (1 - ease_out(enter)) * 6, resample=Image.BICUBIC, expand=True)
            shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
            shadow.putalpha(im.getchannel("A").point(lambda v: int(v * 0.6)))
            shadow = shadow.filter(ImageFilter.GaussianBlur(16))
            sc = 1.28 - 0.28 * ease_out_back(enter, 1.3)
            paste(fr, shadow, W / 2 + 10 + jit[0], self.CARD_Y + 22 + jit[1], scale=sc)
            paste(fr, im, W / 2 + jit[0], self.CARD_Y + jit[1], scale=sc)
        else:
            extra = 1 + 0.14 * (1 - ease_out(lin(t, t0, t0 + 0.2))) if s.get("snap") else 1.0
            if s["img"].startswith("@"):
                src = self.diag.render(s["img"][1:], t - s.get("age0", t0))
            else:
                src = self.A.prepared(s["img"], W, H, s.get("look", ""))
            bg, _ = kenburns(src, W, H, p, s["z0"], s["z1"], s["fx"], s["fy"], jitter=jit, extra_zoom=extra)
            fr = bg.convert("RGBA")
            fr.alpha_composite(vgradient(760, 0, 200), dest=(0, H - 760))
            if s.get("fog"):
                paste(fr, fog_texture(), W / 2, int(-H + (t - t0) * 420) + H, alpha=0.5)
            if s.get("pulse"):
                fr.alpha_composite(vignette(int(150 + 90 * (0.5 + 0.5 * math.sin((t - t0) * 12)))))
            fr.alpha_composite(vignette(120))
        for sh in self.shots:
            if sh.get("flash") and sh["t"] <= t < sh["t"] + 0.12:
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(200 * (1 - lin(t, sh["t"], sh["t"] + 0.12))))))
        if self.t_drown <= t < self.t_s1 + 0.05:
            sc = 1 + 0.8 * (1 - ease_out(lin(t, self.t_drown, self.t_drown + 0.12)))
            paste(fr, self.stamp, W / 2 + 110 + jit[0], self.CARD_Y + 90 + jit[1], alpha=lin(t, self.t_drown, self.t_drown + 0.04), scale=sc)
        # case-file layer on top
        fr.alpha_composite(vgradient(780, 235, 0), dest=(0, 0))
        paste(fr, self.header, 70 + self.header.width / 2, 132)
        paste(fr, self.header_r, W - 70 - self.header_r.width / 2, 132)
        dot = 0.5 + 0.5 * math.sin(t * 6)
        ImageDraw.Draw(fr).ellipse((W - 70 - self.header_r.width - 40, 122, W - 70 - self.header_r.width - 20, 142), fill=self.RED + (int(120 + 135 * dot),))
        ti = max(j for j, x in enumerate(self.tag_imgs) if x[0] <= t)
        t0g, big, sub, subtxt = self.tag_imgs[ti]
        a_in = 1.0 if ti == 0 else ease_out(lin(t, t0g, t0g + 0.15))
        sc = 1.0 if ti == 0 else 1 + 0.3 * (1 - ease_out_back(lin(t, t0g, t0g + 0.18)))
        paste(fr, big, W / 2, 400, alpha=a_in, scale=sc)
        reveal = 1.0 if ti == 0 else lin(t, t0g, t0g + 0.022 * len(subtxt))
        cw = int(sub.width * reveal)
        if cw > 0:
            paste(fr, sub.crop((0, 0, cw, sub.height)), W / 2 - sub.width / 2 + cw / 2, 575)
        ci, ch = chunk_at(self.chunks, t, hold=0.25)
        if ch and t < self.t_why:
            cap = self.caption(ci, ch, t)
            sc = 0.72 + 0.28 * ease_out_back(lin(t, ch[0]["start"] - 0.02, ch[0]["start"] + 0.13), 2.0)
            paste(fr, cap, W / 2, self.CAP_Y, scale=sc)
        return fr.convert("RGB")


STYLES = {"A": StyleA, "B": StyleB, "C": StyleC, "D": StyleD}


# ---------------------------------------------------------------- audio + encode
def mean_db(path: Path, start: float = 0.0, dur: float | None = None) -> float:
    cmd = ["ffmpeg", "-hide_banner", "-ss", str(start), "-i", str(path)]
    if dur:
        cmd += ["-t", str(dur)]
    cmd += ["-af", "volumedetect", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True, check=False).stderr
    return float(err.split("mean_volume:")[1].split(" dB")[0])


def build_audio(style: Style, lab: Path, out_wav: Path) -> None:
    T = style.T
    track = np.zeros(int((T + 1.0) * SR), dtype=np.float32)
    for at, clip, gain in style.events:
        sfx.place(track, clip, max(0.0, at), gain)
    sfx_wav = out_wav.with_name(f"_sfx_{style.key}.wav")
    with wave.open(str(sfx_wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())
    voice = lab / "voice" / f"voice_{style.key}.wav"
    mfile, moff, gap = style.music
    music = lab / "music" / mfile
    gain_db = (mean_db(voice) - gap) - mean_db(music, moff, T + 1)
    fc = (
        f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=start={moff}:duration={T + 0.5},asetpts=PTS-STARTPTS,afade=t=in:d=0.04,volume={gain_db:.2f}dB[m];"
        f"[0:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=pad_dur=1,asplit=2[v][vs];"
        f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo[fx];"
        f"[m][vs]sidechaincompress=threshold=0.04:ratio=5:attack=12:release=280[md];"
        f"[v][md][fx]amix=inputs=3:normalize=0:duration=shortest,atrim=0:{T:.3f},"
        f"afade=t=out:st={T - 0.05:.3f}:d=0.05,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[a]"
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", str(voice), "-i", str(music), "-i", str(sfx_wav),
         "-filter_complex", fc, "-map", "[a]", "-ac", "2", str(out_wav)],
        check=True,
    )


def render(key: str, lab: Path, out_dir: Path, only_frames: list[float] | None = None) -> Path | None:
    A = Assets(lab)
    words = Words(lab / "voice" / f"words_{key}.json")
    st = STYLES[key](A, words)
    if only_frames is not None:
        for t in only_frames:
            st.frame(t, int(t * FPS)).save(out_dir / f"frame_{key}_{t:05.2f}.jpg", quality=88)
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    audio = out_dir / f"_audio_{key}.wav"
    build_audio(st, lab, audio)
    out = out_dir / f"test_{key}.mp4"
    n = round(st.T * FPS)
    ff = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
         "-i", "-", "-i", str(audio), "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high",
         "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(out)],
        stdin=subprocess.PIPE,
    )
    t_start = time.time()
    for i in range(n):
        ff.stdin.write(st.frame(i / FPS, i).tobytes())
    ff.stdin.close()
    if ff.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {key}")
    print(f"{key}: {n} frames, {st.T:.2f}s, rendered in {time.time() - t_start:.0f}s -> {out}")
    return out


if __name__ == "__main__":
    lab_dir, out_dir = Path(sys.argv[1]), Path(sys.argv[2])
    keys = [a for a in sys.argv[3:] if a in STYLES] or list(STYLES)
    frames = [float(a.split("=")[1]) for a in sys.argv[3:] if a.startswith("t=")]
    for k in keys:
        render(k, lab_dir, out_dir, frames or None)
