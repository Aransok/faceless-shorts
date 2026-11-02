"""Pure-logic tests for the mix pipeline (no network, no render)."""
import unittest

from pipeline.metadata import DESCRIPTION_MAX_CHARS, _append_credits
from pipeline.mix_commons import license_ok
from pipeline.mix_plan import PALETTES, clean_text, script_text, style_for, validate_spec
from pipeline.mix_render import build_html, timings


def _raw(**over) -> dict:
    raw = {
        "topic": "Octopus hearts", "hook": "Three hearts", "kicker": "did you know",
        "scenes": [
            {"type": "card", "dur": 4, "h": "An octopus has <b>three</b> hearts",
             "media": {"query": "octopus", "kind": "video"}},
            {"type": "counter", "dur": 4, "h": "Hearts", "to": 3, "unit": "hearts", "icon": "heart"},
            {"type": "grid", "dur": 5, "h": "Arms", "count": 8, "shape": "octopus"},
            {"type": "card", "dur": 4, "h": "Blue blood", "body": "Copper, not iron",
             "media": {"query": "octopus blood", "kind": "image"}},
            {"type": "end", "dur": 3},
        ],
    }
    raw.update(over)
    return raw


class LicenseTest(unittest.TestCase):
    def test_free_licenses_pass(self):
        for lic in ("CC BY-SA 4.0", "CC BY 2.0", "Public domain", "CC0"):
            self.assertTrue(license_ok(lic), lic)

    def test_nc_nd_fail(self):
        for lic in ("CC BY-NC 4.0", "CC BY-ND 3.0", "CC BY-NC-SA 2.0", "All rights reserved"):
            self.assertFalse(license_ok(lic), lic)


class ValidateSpecTest(unittest.TestCase):
    def test_valid_spec(self):
        spec = validate_spec(_raw())
        self.assertEqual([s["type"] for s in spec["scenes"]], ["card", "counter", "grid", "card", "end"])
        self.assertEqual(spec["kicker"], "DID YOU KNOW")
        self.assertEqual(spec["scenes"][2]["labels"], [""] * 8)

    def test_first_scene_must_be_card(self):
        raw = _raw()
        raw["scenes"].insert(0, raw["scenes"].pop(1))
        with self.assertRaises(ValueError):
            validate_spec(raw)

    def test_end_must_be_last(self):
        raw = _raw()
        raw["scenes"].insert(2, raw["scenes"].pop())
        with self.assertRaises(ValueError):
            validate_spec(raw)

    def test_missing_end_is_appended(self):
        raw = _raw()
        raw["scenes"].pop()
        self.assertEqual(validate_spec(raw)["scenes"][-1]["type"], "end")

    def test_total_out_of_range(self):
        raw = _raw()
        del raw["scenes"][2]  # card, counter, card, end
        for s in raw["scenes"]:
            s["dur"] = 0.1  # clamps to minimums: 3.5+4+3.5+2.5 = 13.5 < 18
        with self.assertRaises(ValueError):
            validate_spec(raw)

    def test_script_text_is_plain(self):
        text = script_text(validate_spec(_raw()))
        self.assertIn("An octopus has three hearts.", text)
        self.assertNotIn("<", text)


class CleanTextTest(unittest.TestCase):
    def test_strips_unknown_tags_keeps_b_and_ascii(self):
        self.assertEqual(clean_text('<script>x</script><b>hi</b> — café'), "x<b>hi</b> ,  caf")


class StyleTest(unittest.TestCase):
    def test_deterministic_and_from_palettes(self):
        a, b = style_for("vid-1"), style_for("vid-1")
        self.assertEqual(a, b)
        self.assertIn((a["bg"], a["ink"], a["mute"], a["acc"], a["acc2"]), PALETTES)

    def test_varies_across_ids(self):
        self.assertGreater(len({style_for(f"v{i}")["bg"] for i in range(40)}), 1)


class RenderLogicTest(unittest.TestCase):
    def test_timings_are_cumulative(self):
        self.assertEqual(timings([{"dur": 4}, {"dur": 3.5}, {"dur": 2}]), [0, 4, 7.5])

    def test_html_has_seek_and_palette(self):
        spec = validate_spec(_raw())
        spec["style"] = style_for("vid-1")
        media = {0: {"file": "assets/m0.webm", "kind": "video", "credit": "x", "title": "t"},
                 3: {"file": "assets/m3.jpg", "kind": "image", "credit": "y", "title": "u"}}
        html = build_html(spec, timings(spec["scenes"]), media)
        self.assertIn("window.__seek", html)
        self.assertIn(spec["style"]["bg"], html)
        self.assertIn(spec["style"]["acc"], html)


class CreditsTest(unittest.TestCase):
    def test_credits_appended(self):
        out = _append_credits("desc", ["A (B, CC BY)", "C (D, CC0)"])
        self.assertTrue(out.endswith("A (B, CC BY)\nC (D, CC0)"))

    def test_credits_respect_budget(self):
        desc = "x" * (DESCRIPTION_MAX_CHARS - 60)
        out = _append_credits(desc, ["a" * 20, "b" * 20, "c" * 20])
        self.assertLessEqual(len(out), DESCRIPTION_MAX_CHARS)
        self.assertTrue(out.startswith(desc))

    def test_no_room_leaves_description_alone(self):
        desc = "x" * DESCRIPTION_MAX_CHARS
        self.assertEqual(_append_credits(desc, ["a"]), desc)


if __name__ == "__main__":
    unittest.main()
