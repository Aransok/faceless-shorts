"""Stage 2 for the mix templates: videos.mix_spec -> final mp4 with voice + score.

Ported from the openmontage trial (projects/shorts/build.py) that the owner
approved on 2026-11-02. Real footage/photos come from Wikimedia Commons
(pipeline/mix_commons.py), the score is synthesized with numpy, and the page
is rendered by the same vendored render.mjs the motionmaxxing renderer uses,
so CI needs nothing new. Each scene gets one edge-tts line (owner ask
2026-11-03: a voice, and no low "boom" hits); a scene stretches to fit
its line. Status goes scripted -> captioned (no separate caption pass:
all text is on screen).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import requests

from pipeline import mix_commons
from pipeline.mm_render import VENDOR, render_video

ROOT = Path(__file__).resolve().parent.parent
WORK_DIR = ROOT / "assets" / "mix_work"
OUTPUT_DIR = ROOT / "assets" / "output"
FONT = ROOT / "mm" / "fonts" / "montserrat-latin-wght-normal.woff2"
GSAP = VENDOR / "runtime" / "vendor" / "gsap.min.js"
CARD_W, CARD_H = 920, 720
MAX_SOURCE_SECONDS = 300  # longer Commons videos are big downloads for a 5 s cut

ICONS = {  # all draw with currentColor so GSAP can tween `color`
    "spoon": ('0 0 300 140', '<ellipse cx="70" cy="70" rx="62" ry="44"/><ellipse cx="66" cy="64" rx="40" ry="24" fill="#fff" opacity=".18"/>'
              '<path d="M128 66 C170 62 240 58 292 60 L292 76 C240 78 170 80 128 76 Z"/>'),
    "timer": ('0 0 300 300', '<rect x="125" y="10" width="50" height="30" rx="8"/><circle cx="150" cy="170" r="120" fill="none" stroke="currentColor" stroke-width="26"/>'
              '<path d="M150 170 L150 85" stroke="currentColor" stroke-width="22" stroke-linecap="round"/><circle cx="150" cy="170" r="16"/>'),
    "heart": ('0 0 300 280', '<path d="M150 265 C60 195 15 145 15 95 C15 52 48 22 88 22 C116 22 138 38 150 62 C162 38 184 22 212 22 C252 22 285 52 285 95 C285 145 240 195 150 265 Z"/>'),
    "brain": ('0 0 300 260', '<path d="M150 30 C120 0 60 10 50 55 C10 65 5 120 30 140 C10 175 40 225 85 215 C100 250 145 250 150 225 C155 250 200 250 215 215 C260 225 290 175 270 140 C295 120 290 65 250 55 C240 10 180 0 150 30 Z"/>'
              '<path d="M150 35 V225 M95 80 C120 95 110 125 80 130 M205 80 C180 95 190 125 220 130 M90 175 C115 165 130 185 120 205 M210 175 C185 165 170 185 180 205" fill="none" stroke="#fff" stroke-opacity=".35" stroke-width="10" stroke-linecap="round"/>'),
    "onion": ('0 0 300 320', '<path d="M150 40 C150 40 170 70 175 85 C260 110 290 190 250 250 C215 300 85 300 50 250 C10 190 40 110 125 85 C130 70 150 40 150 40 Z"/>'
              '<path d="M150 95 C110 140 105 230 150 285 M150 95 C190 140 195 230 150 285 M150 95 V285" fill="none" stroke="#fff" stroke-opacity=".3" stroke-width="8"/>'
              '<path d="M140 45 C130 20 120 10 105 5 M158 45 C165 22 178 10 195 6" stroke="currentColor" stroke-width="10" stroke-linecap="round" fill="none"/>'),
    "octopus": ('0 0 300 300', '<ellipse cx="150" cy="105" rx="85" ry="90"/><circle cx="118" cy="115" r="14" fill="#fff"/><circle cx="182" cy="115" r="14" fill="#fff"/>'
                '<path d="M80 170 C50 220 20 230 15 270 M120 185 C110 240 90 260 95 295 M180 185 C190 240 210 260 205 295 M220 170 C250 220 280 230 285 270" fill="none" stroke="currentColor" stroke-width="26" stroke-linecap="round"/>'),
    "drop": ('0 0 200 280', '<path d="M100 10 C100 10 185 120 185 185 C185 235 147 270 100 270 C53 270 15 235 15 185 C15 120 100 10 100 10 Z"/>'),
    "star": ('0 0 300 290', '<path d="M150 10 L188 105 L290 110 L210 175 L238 275 L150 218 L62 275 L90 175 L10 110 L112 105 Z"/>'),
    "bolt": ('0 0 200 300', '<path d="M120 10 L20 170 L95 170 L75 290 L180 120 L105 120 Z"/>'),
    "eye": ('0 0 300 200', '<path d="M10 100 C60 20 240 20 290 100 C240 180 60 180 10 100 Z"/><circle cx="150" cy="100" r="48" fill="#fff"/><circle cx="150" cy="100" r="24"/>'),
    "globe": ('0 0 300 300', '<circle cx="150" cy="150" r="135"/><path d="M15 150 H285 M150 15 V285 M150 15 C80 70 80 230 150 285 M150 15 C220 70 220 230 150 285 M40 85 H260 M40 215 H260" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="8"/>'),
    "flame": ('0 0 240 300', '<path d="M120 10 C140 80 210 110 210 190 C210 250 170 290 120 290 C70 290 30 250 30 190 C30 140 60 110 80 80 C85 120 100 140 115 145 C105 100 105 50 120 10 Z"/>'),
    "leaf": ('0 0 300 300', '<path d="M40 260 C30 120 120 30 280 20 C270 180 180 270 40 260 Z"/><path d="M50 250 C120 180 180 120 250 50" fill="none" stroke="#fff" stroke-opacity=".4" stroke-width="10" stroke-linecap="round"/>'),
}

CSS = """
@font-face { font-family: "Montserrat"; font-weight: 100 900; src: url("montserrat.woff2") format("woff2"); }
:root { --bg: BG; --ink: INK; --acc: ACC; --acc2: AC2; --mute: MUTE; }
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1080px; height: 1920px; overflow: hidden; background: var(--bg); }
#root { position: relative; width: 100%; height: 100%; font-family: "Montserrat", sans-serif; color: var(--ink); background: var(--bg); }
.t { position: absolute; left: 80px; right: 80px; }
#k { top: 200px; font-size: 30px; font-weight: 700; letter-spacing: .25em; color: var(--acc); }
.h { top: 250px; font-size: 92px; font-weight: 800; line-height: 1.02; letter-spacing: -0.02em; }
.h b, .body b { color: var(--acc); }
#card { position: absolute; left: 80px; top: 560px; width: 920px; height: 720px; border-radius: 28px; overflow: hidden; background: #111; box-shadow: 0 30px 60px rgba(0,0,0,.28); opacity: 0; }
#card video, #card img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.chip { position: absolute; left: 28px; bottom: 28px; padding: 14px 22px; border-radius: 14px; background: rgba(20,18,16,.82); color: #fff; font-size: 30px; font-weight: 700; }
.chip i { font-style: normal; font-weight: 500; color: var(--acc2); }
.body { top: 1340px; font-size: 54px; font-weight: 700; line-height: 1.15; }
.src { top: 1720px; font-size: 26px; color: var(--mute); }
.stats { position: absolute; left: 80px; right: 80px; top: 1340px; display: flex; gap: 40px; }
.stats div { flex: 1; border-top: 6px solid var(--ink); padding-top: 18px; }
.stats b { display: block; font-size: 110px; font-weight: 800; line-height: 1; color: var(--acc); }
.stats span { font-size: 36px; font-weight: 600; color: var(--mute); }
.icon { position: absolute; left: 80px; top: 780px; width: 320px; height: 320px; color: var(--ink); }
.eq { position: absolute; left: 430px; top: 760px; font-size: 160px; font-weight: 300; color: var(--mute); }
.big { position: absolute; left: 570px; top: 760px; font-size: 230px; font-weight: 800; line-height: 1; color: var(--acc); font-variant-numeric: tabular-nums; }
.unit { position: absolute; left: 580px; top: 1000px; font-size: 48px; font-weight: 700; color: var(--mute); }
.tri { position: absolute; left: 80px; top: 600px; width: 920px; display: grid; grid-template-columns: repeat(12, 1fr); gap: 10px; }
.tri i { display: block; height: 0; padding-bottom: 86%; background: var(--ink); clip-path: polygon(50% 0, 100% 100%, 0 100%); }
.few { position: absolute; left: 80px; right: 80px; top: 640px; display: flex; flex-wrap: wrap; justify-content: center; gap: 40px; }
.few div { width: 260px; text-align: center; color: var(--ink); }
.few svg { width: 260px; height: 260px; }
.few span { display: block; margin-top: 18px; font-size: 40px; font-weight: 700; color: var(--mute); }
.endicon { position: absolute; left: 380px; top: 720px; width: 320px; height: 320px; color: var(--acc); }
"""


class MixRenderError(RuntimeError):
    pass


def svg(name: str, cls: str, extra: str = "") -> str:
    vb, body = ICONS[name]
    return f'<svg class="{cls}" {extra} viewBox="{vb}" fill="currentColor" preserveAspectRatio="xMidYMid meet">{body}</svg>'


def timings(scenes: list[dict]) -> list[float]:
    starts, t = [], 0.0
    for s in scenes:
        starts.append(round(t, 3))
        t += s["dur"]
    return starts


def _prep_video(item: dict, scene: dict, dest: Path) -> None:
    raw = dest.with_suffix(".src")
    mix_commons.download(mix_commons.video_url(item), raw)
    dur = float(item.get("duration") or 0)
    start = max(0.0, min(scene["media"].get("start", 0), dur - scene["dur"] - 1))
    vf = f"scale={CARD_W}:{CARD_H}:force_original_aspect_ratio=increase:flags=lanczos,crop={CARD_W}:{CARD_H},eq=contrast=1.05:saturation=1.1,fps=30"
    # VP9 webm: the render Chromium in CI has no H.264 decoder
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start), "-i", str(raw), "-t", str(scene["dur"] + .5),
                    "-vf", vf, "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0", "-deadline", "realtime", "-cpu-used", "8",
                    "-an", str(dest)], timeout=300)
    raw.unlink(missing_ok=True)
    if not dest.exists() or dest.stat().st_size < 10_000:
        dest.unlink(missing_ok=True)
        raise MixRenderError(f"clip prep failed for {item['title']}")


def resolve_media(scene: dict, i: int, assets: Path, used: set[str]) -> dict:
    """Find, download and cut one card's media. Video falls back to a photo of the same query."""
    m = scene["media"]
    if m["kind"] == "video":
        tries = 0
        for it in mix_commons.search(m["query"], "video"):
            dur = float(it.get("duration") or 0)
            if it["title"] in used or not scene["dur"] + 1 <= dur <= MAX_SOURCE_SECONDS or tries >= 3:
                continue
            tries += 1
            dest = assets / f"m{i}.webm"
            try:
                _prep_video(it, scene, dest)
            except (MixRenderError, requests.RequestException, subprocess.TimeoutExpired) as exc:
                print(f"[mix] skip {it['title']}: {exc}")
                continue
            used.add(it["title"])
            return {"file": dest.name, "kind": "video", "credit": "Footage: " + mix_commons.credit(it), "title": it["title"]}
    for it in mix_commons.search(m["query"], "bitmap"):
        if it["title"] in used or it["w"] < 800:
            continue
        dest = assets / f"m{i}{'.png' if it['thumb'].lower().endswith('.png') else '.jpg'}"
        try:
            mix_commons.download(it["thumb"], dest)
        except requests.RequestException as exc:
            print(f"[mix] skip {it['title']}: {exc}")
            continue
        used.add(it["title"])
        return {"file": dest.name, "kind": "image", "credit": "Photo: " + mix_commons.credit(it), "title": it["title"]}
    raise MixRenderError(f"no usable Commons media for {m['query']!r}")


def build_html(spec: dict, starts: list[float], media: dict[int, dict]) -> str:
    scenes, total = spec["scenes"], round(sum(s["dur"] for s in spec["scenes"]), 3)
    end_at = next((a for a, s in zip(starts, scenes) if s["type"] == "end"), total)
    H, card, js = [], [], []
    H.append(f'<div id="k" class="t clip" data-start="0" data-duration="{end_at}" data-track-index="1">{spec["kicker"]}</div>')

    def clip(el_id: str, cls: str, st: float, du: float, tr: int, inner: str) -> str:
        return f'<div id="{el_id}" class="{cls} clip" data-start="{round(st, 3)}" data-duration="{round(du, 3)}" data-track-index="{tr}">{inner}</div>'

    prev_card = False
    for i, (a, s) in enumerate(zip(starts, scenes)):
        d, typ = s["dur"], s["type"]
        H.append(clip(f"h{i}", "t h", a, d, 1, s["h"]))
        js.append(f'tl.fromTo("#h{i}", {{opacity:{1 if a == 0 else 0}, y:{0 if a == 0 else 40}}}, {{opacity:1, y:0, duration:.45, ease:E}}, {a + .02});')
        if a + d < total:
            js.append(f'tl.fromTo("#h{i}", {{opacity:1}}, {{opacity:0, duration:.2, immediateRender:false}}, {a + d - .22});')
        if a == 0:
            js.append('tl.fromTo("#h0", {scale:1.04}, {scale:1, duration:.6, ease:E, transformOrigin:"0 0"}, 0);')

        is_card = typ == "card"
        if is_card and not prev_card:
            js.append(f'tl.fromTo("#card", {{opacity:0, y:{60 if a == 0 else 0}, scale:{.96 if a == 0 else .9}}}, {{opacity:1, y:0, scale:1, duration:.5, ease:E, immediateRender:false}}, {a + (.15 if a == 0 else 0)});')
        if prev_card and not is_card:
            js.append(f'tl.fromTo("#card", {{opacity:1, scale:1}}, {{opacity:0, scale:.9, duration:.3, ease:"power2.in", immediateRender:false}}, {a - .3});')
        if is_card and prev_card:
            js.append(f'tl.fromTo("#m{i}", {{clipPath:"inset(100% 0 0 0)"}}, {{clipPath:"inset(0% 0 0 0)", duration:.5, ease:"expo.out"}}, {a});')
        prev_card = is_card

        if is_card:
            m = media[i]
            if m["kind"] == "video":
                card.append(f'<video id="m{i}" class="clip" src="assets/{m["file"]}" muted playsinline preload="auto" data-start="{a}" data-duration="{d}" data-track-index="0"></video>')
            else:
                card.append(f'<img id="m{i}" class="clip" src="assets/{m["file"]}" data-start="{a}" data-duration="{d}" data-track-index="0" />')
            js.append(f'tl.fromTo("#m{i}", {{scale:1.12}}, {{scale:1, duration:{d}, ease:"none", immediateRender:false}}, {a});')
            if s.get("chip"):
                card.append(clip(f"c{i}", "chip", a + .5, d - .5, 2, s["chip"]))
                js.append(f'tl.fromTo("#c{i}", {{opacity:0, x:-30}}, {{opacity:1, x:0, duration:.35, ease:E}}, {a + .5});')
            H.append(clip(f"src{i}", "t src", a + .2, d - .2, 5, m["credit"]))
            js.append(f'tl.fromTo("#src{i}", {{opacity:0}}, {{opacity:1, duration:.3}}, {a + .2});')
            if s.get("stats"):
                cells = "".join(f"<div><b>{v}</b><span>{lab}</span></div>" for v, lab in s["stats"])
                H.append(clip(f"st{i}", "stats", a + .7, d - .7, 3, cells))
                js.append(f'tl.fromTo("#st{i} > div", {{opacity:0, y:40}}, {{opacity:1, y:0, duration:.45, ease:"back.out(1.8)", stagger:.35}}, {a + .7});')
        elif typ == "counter":
            H.append(svg(s["icon"], "icon clip", f'id="ic{i}" data-start="{a}" data-duration="{d}" data-track-index="4"'))
            H.append(clip(f"eq{i}", "eq", a + .4, d - .4, 4, "="))
            H.append(clip(f"big{i}", "big", a + .6, d - .6, 4, "0"))
            H.append(clip(f"un{i}", "unit", a + .6, d - .6, 4, s["unit"]))
            js += [f'tl.fromTo("#ic{i}", {{opacity:0, x:-60, rotation:-12}}, {{opacity:1, x:0, rotation:0, duration:.6, ease:E}}, {a});',
                   f'tl.fromTo("#eq{i}", {{opacity:0}}, {{opacity:1, duration:.3}}, {a + .4});',
                   f'tl.fromTo(["#big{i}","#un{i}"], {{opacity:0, y:20}}, {{opacity:1, y:0, duration:.4, ease:E}}, {a + .6});',
                   f'(() => {{ const n = {{v:0}}, el = document.getElementById("big{i}"); tl.fromTo(n, {{v:0}}, {{v:{s["to"]}, duration:1.4, ease:"power2.out", onUpdate:() => {{ el.textContent = n.v.toFixed({s.get("decimals", 0)}); }}}}, {a + .6}); }})();',
                   f'tl.fromTo("#big{i}", {{scale:1}}, {{keyframes:[{{scale:1.12, duration:.08}}, {{scale:1, duration:.3, ease:"power2.out"}}], transformOrigin:"0 50%", immediateRender:false}}, {a + 2.0});']
        elif typ == "grid":
            n, flip = s["count"], s.get("flip")
            if n <= 12:
                labels = s.get("labels", [""] * n)
                cells = "".join(f'<div>{svg(s.get("shape", "heart"), "")}<span>{labels[j]}</span></div>' for j in range(n))
                H.append(clip(f"g{i}", "few", a, d, 4, cells))
                js.append(f'tl.fromTo("#g{i} > div", {{opacity:0, scale:.4}}, {{opacity:1, scale:1, duration:.45, ease:"back.out(2)", stagger:.25}}, {a + .1});')
                sel = [f"#g{i} > div:nth-child({j + 1})" for j in (flip if flip else range(n))]
                js.append(f'tl.fromTo({json.dumps(sel)}, {{color:INK}}, {{color:ACC, duration:.4, stagger:.15, immediateRender:false}}, {a + 1.4});')
            else:
                cols = 12 if n <= 72 else 20 if n <= 200 else 40
                H.append(f'<div id="g{i}" class="tri clip" style="grid-template-columns:repeat({cols},1fr)" data-count="{n}" data-start="{a}" data-duration="{d}" data-track-index="4"></div>')
                js.append(f'tl.fromTo("#g{i} i", {{scale:0, opacity:0}}, {{scale:1, opacity:1, duration:.25, ease:"back.out(2)", stagger:{{each:{1.2 / n:.5f}}}}}, {a + .1});')
                tgt = f'"#g{i} i"' if not flip else json.dumps([f"#g{i} i:nth-child({j + 1})" for j in flip])
                js.append(f'tl.fromTo({tgt}, {{backgroundColor:INK}}, {{backgroundColor:ACC, duration:.4, stagger:{{each:{.6 / n:.5f}}}, immediateRender:false}}, {a + 1.4});')
        elif typ == "end":
            H.append(clip(f"h{i}x", "t h", a, d, 1, ""))  # keeps ids unique if a later edit adds text
            H.append(svg(s.get("icon", "heart"), "endicon clip", f'id="ei{i}" data-start="{a}" data-duration="{d}" data-track-index="4"'))
            js.append(f'tl.fromTo("#ei{i}", {{opacity:0, scale:.6, rotation:-20}}, {{opacity:1, scale:1, rotation:0, duration:.5, ease:"back.out(2)"}}, {a + .1});')

        if s.get("body"):
            bt = {"card": .8, "counter": 2.1, "grid": 1.4}.get(typ, .3)
            H.append(clip(f"b{i}", "t body", a + bt, d - bt, 3, s["body"]))
            js.append(f'tl.fromTo("#b{i}", {{opacity:0, y:30}}, {{opacity:1, y:0, duration:.4, ease:E}}, {a + bt});')

    st = spec["style"]
    css = (CSS.replace("BG", st["bg"]).replace("INK", st["ink"]).replace("MUTE", st["mute"])
           .replace("AC2", st["acc2"]).replace("ACC", st["acc"]))
    nl = "\n      "
    return f"""<!doctype html>
<html lang="en" data-resolution="portrait">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1080, height=1920" />
    <script src="gsap.min.js"></script>
    <style>{css}</style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="1080" data-height="1920">
      {nl.join(H)}
      <div id="card">
      {nl.join(card)}
      </div>
    </div>
    <script>
      document.querySelectorAll(".tri").forEach(g => {{ for (let j = 0; j < +g.dataset.count; j++) g.appendChild(document.createElement("i")); }});
      const tl = gsap.timeline({{ paused: true }});
      const E = "power3.out", INK = {json.dumps(st["ink"])}, ACC = {json.dumps(st["acc"])};
      {nl.join(js)}
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = tl;
      window.__duration = {total};
      // render.mjs calls __seek; clip windows are applied here (HyperFrames does this itself)
      const clips = [...document.querySelectorAll(".clip")];
      window.__seek = (t) => {{
        tl.seek(t, false);
        for (const c of clips) {{ const a = +c.dataset.start, d = +c.dataset.duration; c.style.visibility = t >= a && t < a + d ? "visible" : "hidden"; }}
      }};
      window.__seek(0);
    </script>
  </body>
</html>
"""


END_SAY = "Follow for more."
VOICE_LEAD, VOICE_TAIL = 0.15, 0.45  # seconds of air before/after each scene's line
MUSIC_UNDER_VOICE = 0.3


def narrate(spec: dict, template: str, work: Path) -> list[Path]:
    """One TTS line per scene -> 48 kHz mono wavs; stretches scene durs to fit. Mutates spec."""
    from pipeline import voice
    from pipeline.mix_plan import script_text

    voice._voice_override = voice.voice_for_template(template)
    wavs = []
    try:
        for i, s in enumerate(spec["scenes"]):
            line = s.get("say") or (END_SAY if s["type"] == "end" else script_text({"scenes": [s]}))
            mp3, wav = work / f"say{i}.mp3", work / f"say{i}.wav"
            voice.synthesize(line, mp3, "edge_tts")
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-ac", "1", "-ar", "48000", str(wav)],
                               capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise MixRenderError("voice decode failed: " + r.stderr[-400:])
            with wave.open(str(wav)) as w:
                need = w.getnframes() / w.getframerate() + VOICE_LEAD + VOICE_TAIL
            s["dur"] = round(max(s["dur"], need), 2)
            wavs.append(wav)
    finally:
        voice._voice_override = None
    return wavs


def score(spec: dict, starts: list[float], out_path: Path, voices: list[Path] | None = None) -> None:
    """Marimba bed + soft whooshes on cuts + counter ticks + end chime, ducked under the voice lines."""
    SR = 48000
    scenes, st = spec["scenes"], spec["style"]
    total = sum(s["dur"] for s in scenes)
    end_at = next((a for a, s in zip(starts, scenes) if s["type"] == "end"), total)
    rng = np.random.default_rng(st["seed"])
    out = np.zeros(int(SR * total))

    def add(sig: np.ndarray, at: float, gain: float = 1.0) -> None:
        i = int(at * SR)
        n = min(len(sig), len(out) - i)
        if n > 0 and i >= 0:
            out[i:i + n] += gain * sig[:n]

    def tone(f: float, d: float, decay: float, harm: tuple = (1, .35, .12)) -> np.ndarray:
        t = np.arange(int(d * SR)) / SR
        return sum(a * np.sin(2 * np.pi * f * (k + 1) * t) for k, a in enumerate(harm)) * np.exp(-t * decay) * np.minimum(1, t / .004)

    def swell(d: float) -> np.ndarray:
        n = np.convolve(rng.standard_normal(int(d * SR)), np.ones(40) / 40, "same")
        return n * (np.arange(len(n)) / len(n)) ** 2.5 * 3

    beat = 60 / st["bpm"] / 2
    chords = st["chords"]
    for s in range(int(end_at / beat)):
        ch = chords[(s // 8) % len(chords)]
        add(tone(ch[[0, 2, 1, 3, 2, 1, 3, 2][s % 8]], .5, 9), s * beat, .16 if s % 2 else .22)
    for c in starts[1:]:
        add(swell(.45), c - .45, .25)
    for a, s in zip(starts, scenes):
        if s["type"] == "counter":
            t = 0.0
            while t < 1.4:
                add(tone(2400, .03, 120, (1,)), a + .6 + t, .25)
                t += .035 + .09 * (t / 1.4) ** 2
        if s["type"] == "grid":
            tt = np.arange(int(1.2 * SR)) / SR
            add(np.sin(2 * np.pi * (600 + 900 * tt / 1.2) * tt) * (tt / 1.2) * .5, a + .2, .18)
        if s["type"] == "card" and s.get("stats"):
            for j in range(len(s["stats"])):
                add(tone(1046.5 * (1.25 ** j), .25, 14), a + .7 + .35 * j, .14)
    for j, f in enumerate((523.3, 659.3, 784.0, 1046.5)):
        add(tone(f, 1.5, 3), end_at + .1 + j * .07, .2)
    fade = np.minimum(1, np.arange(len(out)) / (SR * .3)) * np.minimum(1, (len(out) - np.arange(len(out))) / (SR * .8))
    out = np.tanh(out * fade * 1.2) * .85
    if voices:
        music, out = out * MUSIC_UNDER_VOICE, np.zeros_like(out)
        for a, wav in zip(starts, voices):
            with wave.open(str(wav)) as w:
                add(np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768, a + VOICE_LEAD, .95)
        out = np.clip(out + music, -1, 1)
    pcm = (np.repeat(out[:, None], 2, 1) * 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def build_dir(spec: dict, work: Path, template: str | None = None) -> tuple[list[float], dict[int, dict]]:
    """Write index.html + assets + score.wav into work. Returns (starts, media).
    With a template, scenes are voiced first (and may get longer)."""
    if work.exists():
        shutil.rmtree(work)
    assets = work / "assets"
    assets.mkdir(parents=True)
    shutil.copy(GSAP, work / "gsap.min.js")
    shutil.copy(FONT, work / "montserrat.woff2")
    voices = narrate(spec, template, work) if template else None
    starts = timings(spec["scenes"])
    used: set[str] = set()
    media = {i: resolve_media(s, i, assets, used) for i, s in enumerate(spec["scenes"]) if s["type"] == "card"}
    (work / "index.html").write_text(build_html(spec, starts, media), encoding="utf-8")
    score(spec, starts, work / "score.wav", voices)
    return starts, media


def mix_render(video_id: str) -> Path:
    """scripted -> captioned. Raises on failure; the orchestrator marks the video failed."""
    from pipeline.state import get_video, update_video

    video = get_video(video_id)
    spec = json.loads(video["mix_spec"])
    work = WORK_DIR / video_id
    _, media = build_dir(spec, work, video["template"])
    total = round(sum(s["dur"] for s in spec["scenes"]), 3)
    silent = work / "silent.mp4"
    render_video(work, silent, total)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    final = OUTPUT_DIR / f"{video_id}_final.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(silent), "-i", str(work / "score.wav"),
                        "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)],
                       capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise MixRenderError("mux failed: " + r.stderr[-600:])
    # look_gate is tuned for promo films (short end hold, constant motion) and fails held mix cards
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
                           capture_output=True, text=True, timeout=60)
    got = float(probe.stdout.strip() or 0)
    if abs(got - total) > 1.0:
        raise MixRenderError(f"render length {got:.2f}s, expected {total:.2f}s")
    spec["credits"] = [f"{m['title'].removeprefix('File:')} ({m['credit'].split(': ', 1)[1]})" for _, m in sorted(media.items())]
    update_video(video_id, status="captioned", video_path=str(silent), final_path=str(final),
                 renderer="mix", mix_spec=json.dumps(spec))
    return final


if __name__ == "__main__":
    print(mix_render(sys.argv[1]))
