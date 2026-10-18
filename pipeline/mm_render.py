"""Motionmaxxing renderer: build a film dir from a template + JSON spec, render
it headless, and run the quality gates (lint.mjs G5, look.py --expect).

Plain functions only. Raises MMRenderError on any failure so the caller can
fall back to the old renderer and log why.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MM_DIR = ROOT / "mm"
VENDOR = ROOT / "vendor" / "motionmaxxing"
WORK_DIR = ROOT / "assets" / "mm_work"
TEMPLATES = ("chef", "facts", "code")
TRIAL_END = date(2026, 10, 26)  # flag auto-offs on this day (last trial day is 10-25)


class MMRenderError(RuntimeError):
    pass


def trial_active(today: date | None = None, env: dict[str, str] | None = None) -> bool:
    """True only when RENDERER=motionmaxxing and the trial window has not ended."""
    e = os.environ if env is None else env
    if (e.get("RENDERER") or "").strip().lower() != "motionmaxxing":
        return False
    return (today or date.today()) < TRIAL_END


def build_film_dir(template: str, spec: dict, out_dir: Path) -> Path:
    """Copy runtime, fonts, libs and the template into out_dir and write spec.js."""
    if template not in TEMPLATES:
        raise MMRenderError(f"unknown mm template {template!r}")
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    shutil.copytree(VENDOR / "runtime", out_dir / "runtime")
    shutil.copytree(MM_DIR / "fonts", out_dir / "fonts")
    shutil.copytree(MM_DIR / "lib", out_dir / "lib")
    shutil.copy(MM_DIR / "templates" / f"{template}.html", out_dir / "index.html")
    (out_dir / "spec.js").write_text("window.SPEC=" + json.dumps(spec) + ";\n", encoding="utf-8")
    return out_dir


def _chrome_env() -> dict[str, str]:
    env = dict(os.environ)
    if not env.get("CHROME_PATH"):
        win = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
        if win.exists():
            env["CHROME_PATH"] = str(win)
    return env


def _run(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=_chrome_env(), cwd=str(ROOT))
    except subprocess.TimeoutExpired as exc:
        raise MMRenderError(f"timeout after {timeout}s: {' '.join(cmd[:3])}") from exc


def lint(film_dir: Path, duration: float) -> None:
    r = _run(["node", str(VENDOR / "scripts" / "lint.mjs"), str(film_dir / "index.html"),
              "--width", "1080", "--height", "1920", "--duration", str(duration)], 300)
    if r.returncode != 0:
        raise MMRenderError("lint gate G5 failed: " + (r.stdout + r.stderr)[-600:])


def render_stills(film_dir: Path, times: list[float], out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["node", str(VENDOR / "scripts" / "render.mjs"), str(film_dir / "index.html"),
              "--still", ",".join(str(t) for t in times), str(out)], 300)
    if r.returncode != 0:
        raise MMRenderError("still render failed: " + (r.stdout + r.stderr)[-600:])
    return out


def render_video(film_dir: Path, out_mp4: Path, duration: float, fps: int = 30) -> Path:
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    r = _run(["node", str(VENDOR / "scripts" / "render.mjs"), str(film_dir / "index.html"), str(out_mp4),
              "--fps", str(fps), "--width", "1080", "--height", "1920", "--crf", "20"], 1500)
    if r.returncode != 0 or not out_mp4.exists():
        raise MMRenderError("render failed: " + (r.stdout + r.stderr)[-600:])
    return out_mp4


def look_gate(mp4: Path, duration: float) -> None:
    r = _run([sys.executable, str(VENDOR / "scripts" / "look.py"), str(mp4), "--out", str(mp4.with_suffix("")) + "_look",
              "--expect", f"{duration:.2f}", "--expect-tol", "0.3", "--strict"], 600)
    if r.returncode != 0:
        raise MMRenderError("look.py gate failed: " + (r.stdout + r.stderr)[-600:])


def render_film(template: str, spec: dict, out_mp4: Path, work_name: str | None = None) -> Path:
    """Full path: build, lint, render, look gate. Returns out_mp4 or raises MMRenderError."""
    duration = float(spec["duration"])
    spec = {"fps": 30, **spec}
    film = build_film_dir(template, spec, WORK_DIR / (work_name or out_mp4.stem))
    lint(film, duration)
    render_video(film, out_mp4, duration, int(spec["fps"]))
    look_gate(out_mp4, duration)
    return out_mp4


TEMPLATE_KIND = {"sauce_recipe": "chef", "food": "chef", "facts": "facts", "programming": "code"}


def kind_for(template: str) -> str | None:
    """mm template for a pipeline template, or None when it stays on the old renderer (e.g. weird)."""
    return TEMPLATE_KIND.get(template)


def _step_words(step: dict) -> list[dict] | None:
    audio = step.get("audio_path")
    if not audio:
        return None
    p = Path(str(audio) + ".words.json")
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def try_motionmaxxing(video_id: str, out_dir: Path) -> Path | None:
    """Render a voiced video with motionmaxxing during the trial.

    Returns the mp4 path and records renderer='motionmaxxing', or returns None
    (after logging why) so the caller falls back to the old renderer.
    """
    from pipeline import mm_specs
    from pipeline.state import get_video, get_video_steps, update_video

    try:
        video = get_video(video_id)
        kind = kind_for(video["template"]) if video else None
        if kind is None or not trial_active():
            return None
        steps = [dict(s) for s in get_video_steps(video_id)]
        if not steps or any(not s.get("duration") for s in steps):
            raise MMRenderError("steps missing or without durations")
        for s in steps:
            s["script_text"] = s.get("script_text") or ""
            s["words"] = _step_words(s)
        if kind == "chef":
            spec = mm_specs.chef_spec(steps)
        elif kind == "facts":
            spec = mm_specs.facts_spec(steps)
        else:
            spec = mm_specs.code_spec(steps, video["language"])
        out = out_dir / f"{video_id}_mm.mp4"
        render_film(kind, spec, out, f"{video_id}_{kind}")
        update_video(video_id, status="visuals_ready", video_path=str(out), renderer="motionmaxxing")
        return out
    except Exception as exc:  # trial: no old-renderer fallback, the stage fails so stats stay clean
        print(f"[motionmaxxing] FAILED for {video_id}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    sample = {"duration": 14, "accent": "#e8542e", "steps": [
        {"action": "pour", "ingredient": "olive oil", "into": "pan", "color": "#c9a227", "label": "2 tbsp olive oil", "t0": 0.5, "t1": 5},
        {"action": "sprinkle", "ingredient": "garlic", "into": "pan", "color": "#f3e3b0", "label": "Add minced garlic", "t0": 5, "t1": 9},
        {"action": "plate", "label": "Serve it hot", "t0": 9, "t1": 12.5}]}
    print(render_film("chef", sample, WORK_DIR / "selftest_chef.mp4"))
