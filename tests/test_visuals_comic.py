"""Pure-logic tests for the comic-style visuals trial -- no network, no ffmpeg."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import visuals_comic, voice  # noqa: E402

ON = {"VISUAL_STYLE": "comic"}


def test_trial_requires_flag():
    assert not visuals_comic.trial_active(date(2026, 10, 27), {})
    assert not visuals_comic.trial_active(date(2026, 10, 27), {"VISUAL_STYLE": "stock"})
    assert visuals_comic.trial_active(date(2026, 10, 27), ON)


def test_trial_auto_off():
    assert visuals_comic.trial_active(date(2026, 11, 3), ON)
    assert not visuals_comic.trial_active(date(2026, 11, 4), ON)


COMIC_ID, STOCK_ID = "comic-video", "stock-video"


@pytest.fixture(autouse=True)
def _fixed_positions():
    positions = {COMIC_ID: 0, STOCK_ID: 1}
    with patch.object(visuals_comic, "count_earlier_videos", side_effect=lambda v, *_: positions[v]):
        yield


def test_applies_only_to_stock_footage_shorts():
    day = date(2026, 10, 27)
    for t in ("facts", "sauce_recipe", "food"):
        assert visuals_comic.applies(t, COMIC_ID, day, ON)
    for t in ("programming", "weird", "quiz_longform", "veylorn_story"):
        assert not visuals_comic.applies(t, COMIC_ID, day, ON)


def test_eligible_videos_alternate_comic_and_old_style():
    assert [visuals_comic.comic_for_position(i) for i in range(6)] == [True, False, True, False, True, False]
    day = date(2026, 10, 28)
    assert visuals_comic.applies("facts", COMIC_ID, day, ON)
    assert not visuals_comic.applies("facts", STOCK_ID, day, ON)


def test_count_earlier_videos_only_counts_eligible_since_start(tmp_path):
    from pipeline import state

    db = tmp_path / "s.db"
    state.init_db(db)
    rows = [("a", "facts", "2026-10-27T10"), ("b", "facts", "2026-10-28T10"), ("c", "programming", "2026-10-28T11"),
            ("d", "food", "2026-10-28T12"), ("e", "sauce_recipe", "2026-10-28T12")]
    with state._connect(db) as conn:
        for vid, tpl, ts in rows:
            conn.execute("INSERT INTO videos (id, template, status, created_at, updated_at) VALUES (?,?,'planned',?,?)",
                         (vid, tpl, ts, ts))
    tpls = ("facts", "sauce_recipe", "food")
    got = {v: state.count_earlier_videos(v, tpls, "2026-10-28", db_path=db) for v in "bde"}
    assert got == {"b": 0, "d": 1, "e": 2}


def test_shot_frames_sum_exactly_to_beat():
    for duration in (0.2, 4.9, 17.31, 20.844):
        n = visuals_comic.images_for_duration(duration)
        frames = visuals_comic.shot_frames(duration, n)
        assert sum(frames) == round(duration * visuals_comic.FPS)
        assert max(frames) - min(frames) <= 1


def test_about_one_cut_every_two_and_a_half_seconds():
    n = visuals_comic.images_for_duration(20.0)
    assert n == 4
    frames = visuals_comic.shot_frames(20.0, n)
    assert len(frames) == 8
    assert frames[0] == 75


def test_cut_times_skip_the_first_shot():
    assert visuals_comic.cut_times([30, 45, 15]) == [1.0, 2.5]
    assert visuals_comic.cut_times([30]) == []


def test_parse_scene_plan_pads_trims_and_rejects():
    raw = 'Sure! {"beats": [["a", "b", "c"], ["x"], [], "nope"]}'
    out = visuals_comic.parse_scene_plan(raw, [2, 3, 1, 1, 2])
    assert out == [["a", "b"], ["x", "x", "x"], None, None, None]


def test_parse_scene_plan_garbage_gives_all_none():
    assert visuals_comic.parse_scene_plan("no json here", [1, 2]) == [None, None]


def test_fallback_scenes_follow_the_narration():
    kw = json.dumps({"subject": "Kola borehole", "exact": ["drill rig"], "representation": [], "concept": []})
    text = "They drilled for years. The rock got hot. They stopped."
    assert visuals_comic.fallback_scenes(kw, text, 3) == [
        "Kola borehole: They drilled for years.", "Kola borehole: The rock got hot.", "Kola borehole: They stopped.",
    ]
    assert visuals_comic.fallback_scenes("", "Only one. Two.", 4) == ["Only one.", "Only one.", "Two.", "Two."]


def test_plan_scenes_falls_back_per_beat_when_llm_fails():
    beats = [{"script_text": "One. Uno.", "keywords": ""}, {"script_text": "Two.", "keywords": ""}]
    with patch("pipeline.plan.call_bulk_llm", side_effect=RuntimeError("down")):
        out = visuals_comic.plan_scenes(beats, "t", [2, 1])
    assert out == [["One.", "Uno."], ["Two."]]


def test_image_seed_is_stable_and_distinct():
    assert visuals_comic.image_seed("v1", 0) == visuals_comic.image_seed("v1", 0)
    assert visuals_comic.image_seed("v1", 0) != visuals_comic.image_seed("v1", 1)


def test_image_seed_fits_pollinations_int32_limit():
    assert all(0 <= visuals_comic.image_seed(f"v{i}", k) < 2**31 for i in range(200) for k in range(20))


def test_image_prompt_carries_the_style():
    assert visuals_comic.image_prompt("a drill rig").endswith(visuals_comic.STYLE_SUFFIX)


def test_beat_pause_shortened_only_for_comic_videos_during_trial():
    with patch.dict("os.environ", ON):
        with patch.object(visuals_comic, "TRIAL_END", date(2999, 1, 1)):
            assert voice.beat_pause_seconds("facts", COMIC_ID) == visuals_comic.BEAT_PAUSE_SECONDS
            assert voice.beat_pause_seconds("facts", STOCK_ID) == voice.BEAT_PAUSE_SECONDS
            assert voice.beat_pause_seconds("programming", COMIC_ID) == voice.BEAT_PAUSE_SECONDS
    with patch.dict("os.environ", {"VISUAL_STYLE": ""}):
        assert voice.beat_pause_seconds("facts", COMIC_ID) == voice.BEAT_PAUSE_SECONDS


def test_comic_captions_are_bigger_three_word_cards(tmp_path):
    from pipeline import captions

    words = [{"word": w, "start": i * 0.3, "end": i * 0.3 + 0.3} for i, w in enumerate("one two three four five six".split())]
    captions._build_ass(words, tmp_path / "c.ass", 1080, 1920, comic=True)
    text = (tmp_path / "c.ass").read_text(encoding="utf-8-sig")
    assert "\\fs100" in text and "\\fs84" in text
    first_card = [ln for ln in text.splitlines() if ln.startswith("Dialogue")][0]
    assert "three" in first_card and "four" not in first_card
