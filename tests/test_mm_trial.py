"""Pure-logic tests for the motionmaxxing trial: flag/auto-off, spec building, renderer comparison, voice override."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from pipeline import mm_render, mm_specs, voice  # noqa: E402


def test_trial_requires_flag():
    assert not mm_render.trial_active(date(2026, 10, 20), {})
    assert not mm_render.trial_active(date(2026, 10, 20), {"RENDERER": "original"})
    assert mm_render.trial_active(date(2026, 10, 20), {"RENDERER": "motionmaxxing"})


def test_trial_auto_off():
    env = {"RENDERER": "motionmaxxing"}
    assert mm_render.trial_active(date(2026, 10, 25), env)
    assert not mm_render.trial_active(date(2026, 10, 26), env)


def test_kind_for_leaves_weird_alone():
    assert mm_render.kind_for("weird") is None
    assert mm_render.kind_for("sauce_recipe") == "chef"
    assert mm_render.kind_for("food") == "chef"
    assert mm_render.kind_for("facts") == "facts"
    assert mm_render.kind_for("programming") == "code"


def test_chef_events_follow_text_order():
    ev = mm_specs.chef_events("Pour olive oil into a hot pan, then add garlic.", None, 8.0)
    assert [e["ingredient"] for e in ev] == ["olive oil", "garlic"]
    assert ev[0]["t"] < ev[1]["t"]


def test_chef_spec_duration_and_plate():
    steps = [{"script_text": "Pour cream into a hot pan, add thyme.", "duration": 12.0}]
    spec = mm_specs.chef_spec(steps)
    assert spec["duration"] == 12.0
    assert spec["steps"][-1]["action"] == "plate"
    assert all(s["t1"] > s["t0"] for s in spec["steps"])


def test_facts_spec_duration():
    spec = mm_specs.facts_spec([{"script_text": "Octopuses have 3 hearts. Two pump blood to the gills.", "duration": 10}])
    assert spec["duration"] == 10.0
    assert spec["beats"]


def test_clip_words_has_no_dangling_word():
    out = mm_specs._clip_words("the quick fox jumped over the lazy dog but the", 7)
    assert not out.split()[-1] in {"but", "the", "a"}


def test_chef_voice_override():
    assert voice.voice_for_template("sauce_recipe") == voice.CHEF_TTS_VOICE
    assert voice.voice_for_template("food") == voice.CHEF_TTS_VOICE
    assert voice.voice_for_template("facts") == voice.EDGE_TTS_VOICE


def test_renderer_comparison_groups_weeks():
    import weekly_report as w

    now = datetime.now(timezone.utc)
    rows = [
        {"uploaded_at": (now - timedelta(days=2)).isoformat(), "renderer": "motionmaxxing", "views": 100, "likes": 5,
         "avg_view_duration_seconds": 20, "avg_view_percentage": 40},
        {"uploaded_at": (now - timedelta(days=9)).isoformat(), "views": 50, "likes": 2,
         "avg_view_duration_seconds": None, "avg_view_percentage": None},
    ]
    text = "\n".join(w.renderer_comparison(rows))
    assert "| motionmaxxing | this week | 1 | 100 |" in text
    assert "| original | previous week | 1 | 50 |" in text
