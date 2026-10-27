"""Hyperframes hybrid renderer: one-week trial (2026-10-27 to 2026-11-02).

The stock-footage visuals stay exactly as visuals_facts() builds them (same
Pexels/Wikimedia clips, same per-beat timing). Hyperframes (heygen-com/
hyperframes, Apache 2.0) only adds a design layer on top of that footage:
ByteBits wordmark, a segmented progress bar (one segment per beat) and, per
beat, a big outlined number with the beat's subject as a short label. The
owner liked this UI in the 2026-10-18 sample but missed real visuals; this
keeps both.

Deliberately NOT added, to keep the trial a one-variable test against the
old renderer:
- no hook title card (the on-screen hook overlay was turned off on
  2026-09-29, see ROADMAP.md, and stays off)
- no end card (assemble.py still adds the CTA badge)
- nothing in the caption zone (captions.py still burns subtitles there)

Unlike the motionmaxxing trial, a failed render here falls back to the
plain footage video (renderer stays 'original'), so a renderer bug never
costs an upload. renderer='hyperframes' is recorded only on success, which
is what scripts/weekly_report.py's renderer comparison groups by.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "assets" / "fonts"
GSAP_FILE = ROOT / "vendor" / "gsap" / "gsap-3.14.2.min.js"
WORK_DIR = ROOT / "assets" / "hf_work"
HYPERFRAMES_VERSION = "0.8.170"
TRIAL_END = date(2026, 11, 3)  # auto-off on this day; last trial day is 2026-11-02
TEMPLATES = ("facts", "sauce_recipe", "weird", "food")
RENDER_TIMEOUT_SECONDS = 1800

WIDTH, HEIGHT = 1080, 1920
TEAL, INDIGO = "#14B8A6", "#6366F1"
MAX_LABEL_CHARS = 30


class HFRenderError(RuntimeError):
    pass


def trial_active(today: date | None = None, env: dict[str, str] | None = None) -> bool:
    """True only when VISUAL_RENDERER=hyperframes and the trial window is open."""
    e = os.environ if env is None else env
    if (e.get("VISUAL_RENDERER") or "").strip().lower() != "hyperframes":
        return False
    return (today or date.today()) < TRIAL_END


def beat_label(keywords: str | None, script_text: str | None) -> str:
    """Short on-screen label: the beat's planned visual subject (already a
    2-5 word noun phrase from plan.py), else the first words of the line.
    Cut on a word boundary, never mid-word."""
    label = ""
    try:
        label = (json.loads(keywords or "{}").get("subject") or "").strip()
    except (ValueError, AttributeError):
        label = ""
    if not label:
        label = " ".join((script_text or "").split()[:4])
    label = re.sub(r"\s+", " ", label).strip(" ,.;:-")
    if len(label) > MAX_LABEL_CHARS:
        cut = label[: MAX_LABEL_CHARS + 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        label = cut or label[:MAX_LABEL_CHARS]
    return label


def beat_timeline(durations: list[float]) -> list[tuple[float, float]]:
    """(start, duration) per beat, back to back from 0."""
    out, t = [], 0.0
    for d in durations:
        out.append((round(t, 3), round(float(d), 3)))
        t += float(d)
    return out


def _accent(label: str) -> int:
    words = label.split()
    if not words:
        return -1
    return max(range(len(words)), key=lambda i: (len(re.sub(r"\W", "", words[i])), -i))


def _label_html(label: str) -> str:
    acc = _accent(label)
    return " ".join(
        f'<span class="w{" accent" if i == acc else ""}">{html.escape(w)}</span>' for i, w in enumerate(label.split())
    )


def build_html(labels: list[str], durations: list[float], footage_name: str) -> str:
    beats = beat_timeline(durations)
    total = round(sum(float(d) for d in durations), 3)
    n = len(beats)
    segs = "".join(f'<div class="seg"><div class="fill" id="fill{i}"></div></div>' for i in range(n))
    sections, js = [], []
    for i, (label, (start, dur)) in enumerate(zip(labels, beats)):
        sections.append(
            f'<section id="b{i}" class="clip beat" data-start="{start}" data-duration="{dur}" data-track-index="2">'
            f'<div class="num">{i + 1:02d}</div><h2 class="label">{_label_html(label)}</h2></section>'
        )
        out_at = round(start + dur - 0.35, 3)
        js.append(
            f'tl.from("#b{i} .num", {{ x: -60, opacity: 0, duration: 0.45, ease: "power3.out" }}, {start + 0.05});'
            f'tl.from("#b{i} .w", {{ y: 50, opacity: 0, duration: 0.45, stagger: 0.06, ease: "power3.out" }}, {start + 0.15});'
            f'tl.fromTo("#fill{i}", {{ scaleX: 0 }}, {{ scaleX: 1, duration: {dur}, ease: "none" }}, {start});'
            f'tl.to("#b{i}", {{ opacity: 0, y: -30, duration: 0.3, ease: "power2.in" }}, {out_at});'
        )
    return f"""<!doctype html>
<html lang="en" data-resolution="portrait">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={WIDTH}, height={HEIGHT}" />
<script src="gsap.min.js"></script>
<style>
@font-face {{ font-family: Poppins; src: url("Poppins-ExtraBold.ttf"); font-weight: 800; }}
@font-face {{ font-family: Mono; src: url("JetBrainsMono-Bold.ttf"); font-weight: 700; }}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {WIDTH}px; height: {HEIGHT}px; overflow: hidden; background: #000; }}
#root {{ position: relative; width: 100%; height: 100%; font-family: Poppins, sans-serif; color: #fff; }}
#footage {{ position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }}
#scrim {{ position: absolute; left: 0; right: 0; top: 0; height: 760px;
  background: linear-gradient(180deg, rgba(4,6,12,0.82) 0%, rgba(4,6,12,0.55) 55%, rgba(4,6,12,0) 100%); }}
.brand {{ position: absolute; top: 118px; width: 100%; text-align: center; font-family: Mono; font-size: 32px;
  letter-spacing: 0.35em; opacity: 0.85; }}
.bar {{ position: absolute; top: 182px; left: 90px; right: 90px; display: flex; gap: 14px; }}
.seg {{ flex: 1; height: 8px; border-radius: 4px; background: rgba(255,255,255,0.22); overflow: hidden; }}
.fill {{ width: 100%; height: 100%; transform-origin: left; transform: scaleX(0); background: linear-gradient(90deg, {TEAL}, {INDIGO}); }}
.beat {{ position: absolute; left: 90px; right: 90px; top: 250px; }}
.num {{ font-family: Mono; font-size: 120px; line-height: 1; margin-bottom: 18px;
  background: linear-gradient(90deg, {TEAL}, {INDIGO}); -webkit-background-clip: text; background-clip: text; color: transparent; }}
.label {{ font-size: 78px; line-height: 1.06; letter-spacing: -0.02em; text-shadow: 0 4px 24px rgba(0,0,0,0.55); }}
.w {{ display: inline-block; }}
.accent {{ background: linear-gradient(90deg, {TEAL}, {INDIGO}); -webkit-background-clip: text; background-clip: text; color: transparent; text-shadow: none; }}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{total}" data-width="{WIDTH}" data-height="{HEIGHT}">
<video id="footage" class="clip" data-start="0" data-duration="{total}" data-track-index="0" src="{footage_name}" muted playsinline></video>
<div id="ui" class="clip" data-start="0" data-duration="{total}" data-track-index="1">
<div id="scrim"></div><div class="brand">BYTEBITS</div><div class="bar">{segs}</div>
</div>
{"".join(sections)}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{"".join(js)}
window.__timelines["main"] = tl;
tl.seek(0);
</script>
</body>
</html>
"""


def write_project(project_dir: Path, footage: Path, labels: list[str], durations: list[float]) -> Path:
    """Self-contained composition folder: no CDN or network at render time."""
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True)
    for font in ("Poppins-ExtraBold.ttf", "JetBrainsMono-Bold.ttf"):
        shutil.copy(FONTS_DIR / font, project_dir / font)
    shutil.copy(GSAP_FILE, project_dir / "gsap.min.js")
    shutil.copy(footage, project_dir / "footage.mp4")
    (project_dir / "index.html").write_text(build_html(labels, durations, "footage.mp4"), encoding="utf-8")
    (project_dir / "meta.json").write_text(json.dumps({"id": "bytebits-hybrid", "name": "bytebits-hybrid"}), encoding="utf-8")
    return project_dir


def render(project_dir: Path, out_mp4: Path, workers: str = "auto") -> Path:
    """npx hyperframes render (pinned). HYPERFRAMES_BROWSER_PATH is passed
    through when set; otherwise the CLI uses its own headless shell."""
    env = {**os.environ, "HYPERFRAMES_SKIP_SKILLS": "1", "DO_NOT_TRACK": "1"}
    cmd = [
        "npx", "--yes", f"hyperframes@{HYPERFRAMES_VERSION}", "render",
        "--output", str(out_mp4.resolve()), "--workers", workers, "--quiet",
    ]
    proc = subprocess.run(cmd, cwd=project_dir, env=env, capture_output=True, text=True, timeout=RENDER_TIMEOUT_SECONDS)
    if proc.returncode != 0 or not out_mp4.exists() or out_mp4.stat().st_size == 0:
        tail = (proc.stdout + proc.stderr)[-1500:]
        raise HFRenderError(f"hyperframes render failed (exit {proc.returncode}):\n{tail}")
    return out_mp4


def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def try_hyperframes(video_id: str) -> bool:
    """Called right after visuals_facts() succeeded. Replaces video_path
    with the hybrid render and records renderer='hyperframes', or leaves
    the footage-only video in place (the old renderer's output) and returns
    False. Never raises: a trial renderer must not fail a video."""
    from pipeline.state import get_video, get_video_steps, update_video

    try:
        video = get_video(video_id)
        if not video or video["template"] not in TEMPLATES or not trial_active():
            return False
        footage = Path(video["video_path"] or "")
        if not footage.exists():
            raise HFRenderError(f"footage video missing: {footage}")
        steps = [dict(s) for s in get_video_steps(video_id)]
        durations = [float(s["duration"]) for s in steps]
        labels = [beat_label(s.get("keywords"), s.get("script_text")) for s in steps]
        project = write_project(WORK_DIR / video_id, footage, labels, durations)
        out = footage.with_name(f"{video_id}_hf.mp4")
        render(project, out)
        # Guard against a silent short render: assemble() muxes narration
        # onto this, so the picture must cover the whole voiceover.
        got, want = _probe_duration(out), sum(durations)
        if got < want - 0.5:
            raise HFRenderError(f"render is {got:.1f}s, narration needs {want:.1f}s")
        update_video(video_id, video_path=str(out), renderer="hyperframes")
        shutil.rmtree(project, ignore_errors=True)
        print(f"[hyperframes] {video_id}: hybrid render ok ({got:.1f}s)")
        return True
    except Exception as exc:
        print(f"[hyperframes] {video_id}: falling back to footage-only video ({type(exc).__name__}: {exc})", file=sys.stderr)
        return False


if __name__ == "__main__":
    # Standalone check: python -m pipeline.hf_render <footage.mp4> <out.mp4>
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    demo_labels = ["Will-o'-the-wisps", "Ball lightning", "Lenticular clouds"]
    demo_durations = [17.0, 17.0, 17.0]
    proj = write_project(WORK_DIR / "selftest", src, demo_labels, demo_durations)
    print(render(proj, dst))
