from pipeline import mm_specs


def test_icons_by_keyword_and_no_repeat():
    assert mm_specs.doodle_icons("Pumpkins and money", set()) == ["pumpkin", "money"]
    assert mm_specs.doodle_icons("Pumpkins again", {"pumpkin"}) == []


def test_word_has_no_digits():
    assert mm_specs.doodle_word("Most of 300 candy corn sales happen") == "candy corn"


def test_spec_covers_duration_and_varies():
    steps = [{"script_text": "Hi. Pumpkins were turnips. It costs money! Why is that? Because time.", "duration": 14.0}]
    spec = mm_specs.doodle_spec(steps, "Why garlic butter is the best sauce ever made")
    b = spec["beats"]
    assert b[0]["t0"] == 0 and abs(b[-1]["t1"] - 14.0) < 0.02
    assert all(x["t1"] - x["t0"] >= 1.5 for x in b)
    assert b[0]["mark_kind"] is None and len({x["layout"] for x in b}) > 1
    assert spec["title"].count("\n") == 1
    assert not any(any(c.isdigit() for c in x["label"]) for x in b)


def test_plan_drawings_filters_to_kit(monkeypatch):
    import json
    from pipeline import doodle_plan as dp
    reply = json.dumps([{"i": 1, "icons": ["pumpkin", "nope"], "pose": "wave", "caption": "Big 5 pumpkins"}, {"i": 2, "icons": ["nope"], "caption": "x"}])
    monkeypatch.setattr("pipeline.plan.call_llm", lambda p: "ok " + reply)
    out = dp.plan_drawings(["a", "b", "c"], "t")
    assert out[0] == {"icons": ["pumpkin"], "pose": "none", "caption": "Big pumpkins"}
    assert out[1] is None and out[2] is None


def test_kit_names_match_js():
    from pipeline import doodle_plan as dp
    assert "pumpkin" in dp.KIT and "stand" not in dp.KIT and len(dp.KIT) > 60
