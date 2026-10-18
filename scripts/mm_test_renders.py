"""Render one motionmaxxing test film per niche from the latest state.db rows.

  python scripts/mm_test_renders.py stills   # stills only (fast)
  python scripts/mm_test_renders.py full     # full gated renders
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import mm_render, mm_specs  # noqa: E402

NICHES = {"chef": "sauce_recipe", "facts": "facts", "code": "programming"}


def rows(template: str) -> tuple[dict, list[dict]]:
    c = sqlite3.connect(ROOT / "state.db")
    c.row_factory = sqlite3.Row
    v = c.execute("select * from videos where template=? order by rowid desc limit 1", (template,)).fetchone()
    steps = [dict(s) for s in c.execute("select * from video_steps where video_id=? order by step_index", (v["id"],))]
    return dict(v), steps


def spec_for(kind: str, video: dict, steps: list[dict]) -> dict:
    for s in steps:
        s["duration"] = s["duration"] or 12.0
        s["script_text"] = s["script_text"] or ""
    if kind == "chef":
        return mm_specs.chef_spec(steps)
    if kind == "facts":
        return mm_specs.facts_spec(steps)
    return mm_specs.code_spec(steps, video.get("language"))


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "stills"
    only = sys.argv[2:] or list(NICHES)
    out = mm_render.WORK_DIR / "trial"
    for kind in only:
        video, steps = rows(NICHES[kind])
        spec = {"fps": 30, **spec_for(kind, video, steps)}
        (out / kind).mkdir(parents=True, exist_ok=True)
        (out / kind / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
        film = mm_render.build_film_dir(kind, spec, out / kind / "film")
        d = spec["duration"]
        if mode == "stills":
            mm_render.lint(film, d)
            ts = [round(d * f, 1) for f in (0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95)]
            print(kind, d, mm_render.render_stills(film, ts, out / kind / "stills"))
        else:
            print(kind, mm_render.render_film(kind, spec, out / kind / f"{kind}.mp4", f"trial/{kind}/film"))
