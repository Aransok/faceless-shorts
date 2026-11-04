"""Pure-logic tests for the mix pipeline (no network, no render)."""
import unittest

from pipeline.metadata import DESCRIPTION_MAX_CHARS, _append_credits
from pipeline.mix_commons import license_ok
from pipeline.mix_plan import PALETTES, clean_text, script_text, style_for, validate_spec
import tempfile
import wave
from pathlib import Path

import numpy as np

from pipeline.mix_render import build_html, score, timings


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

    def test_say_kept_plain(self):
        raw = _raw()
        raw["scenes"][0]["say"] = "Octopuses have <b>three</b> hearts."
        self.assertEqual(validate_spec(raw)["scenes"][0]["say"], "Octopuses have three hearts.")

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


class ScoreVoiceTest(unittest.TestCase):
    def test_voice_is_mixed_in_and_music_ducked(self):
        spec = validate_spec(_raw())
        spec["style"] = style_for("vid-1")
        starts = timings(spec["scenes"])
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            v = tmp / "v.wav"
            with wave.open(str(v), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
                w.writeframes((np.sin(np.arange(4800) * .3) * 20000).astype(np.int16).tobytes())
            score(spec, starts, tmp / "plain.wav")
            score(spec, starts, tmp / "voiced.wav", [v] * len(starts))

            def read(p):
                with wave.open(str(p)) as w:
                    return np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)[:, 0] / 32768
            plain, voiced = read(tmp / "plain.wav"), read(tmp / "voiced.wav")
        quiet = slice(int(48000 * 1.0), int(48000 * 3.5))  # after the 0.1 s line, before the next cut
        self.assertLess(np.abs(voiced[quiet]).max(), np.abs(plain[quiet]).max() * 0.5)
        line = slice(int(48000 * .16), int(48000 * .24))
        self.assertGreater(np.abs(voiced[line]).max(), .4)


class ScoreHasNoEffectsTest(unittest.TestCase):
    """Owner, 2026-11-04: "I don't like when images change the sound effect, I want
    it removed". The 11-03 commit removed only the low booms and the cut whoosh was
    still there, so this pins the whole rule: the score is the music bed and nothing
    else. If any effect is tied to a cut or a scene type, two films of the same
    length with different cuts and scene types stop producing the same audio."""

    @staticmethod
    def _read(path: Path) -> np.ndarray:
        with wave.open(str(path)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)[:, 0] / 32768

    def _score(self, raw: dict, seed: int | None = None) -> np.ndarray:
        spec = validate_spec(raw)
        spec["style"] = style_for("vid-1")
        if seed is not None:
            spec["style"]["seed"] = seed
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "s.wav"
            score(spec, timings(spec["scenes"]), out)
            return self._read(out)

    def test_same_length_different_cuts_and_scene_types_give_identical_audio(self):
        a = self._score(_raw())  # card 4, counter 4, grid 5, card 4, end 3 = 20 s
        other = _raw(scenes=[
            {"type": "card", "dur": 5, "h": "One", "media": {"query": "octopus", "kind": "video"}},
            {"type": "card", "dur": 4, "h": "Two", "media": {"query": "octopus", "kind": "image"}},
            {"type": "card", "dur": 3.5, "h": "Three", "media": {"query": "octopus", "kind": "video"}},
            {"type": "card", "dur": 4.5, "h": "Four", "media": {"query": "octopus", "kind": "video"}},
            {"type": "end", "dur": 3},
        ])  # 20 s, cuts at 5, 9, 12.5, 17 (card scenes are 3.5-5 s, see mix_plan.DUR_RANGE)
        b = self._score(other)
        self.assertEqual(len(a), len(b))
        self.assertTrue(np.array_equal(a, b), "the score changed with the cuts or scene types: an effect is tied to them")

    def test_nothing_in_the_score_is_random(self):
        self.assertTrue(np.array_equal(self._score(_raw(), seed=1), self._score(_raw(), seed=999)))

    def test_the_music_runs_through_the_end_scene_instead_of_dropping_out(self):
        x = self._score(_raw())
        end = x[int(48000 * 17.5):int(48000 * 19.0)]  # the end scene starts at 17 s
        self.assertGreater(20 * np.log10(np.sqrt(np.mean(end ** 2)) + 1e-9), -35)

    def test_no_burst_above_the_bed_anywhere(self):
        x = self._score(_raw())
        win = 48000 // 10
        levels = np.array([np.sqrt(np.mean(x[i:i + win] ** 2)) for i in range(0, len(x) - win, win)])
        body = levels[3:-8]  # skip the fade-in and the fade-out
        self.assertLess(body.max(), np.median(body) * 3, "something louder than the music bed is in the score")

