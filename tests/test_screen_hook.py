"""Pure-logic tests for the on-screen hook (plan.py extraction +
assemble.py overlay rendering). No LLM or ffmpeg calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import assemble
from pipeline.plan import _extract_screen_hook, _parse_response

_FACTS_RAW = "\n".join(
    ["TOPIC: a topic", "HOOK: a hook"]
    + [
        f"FACT_{i}_{field}: value {i}"
        for i in (1, 2, 3)
        for field in ("SCRIPT", "SUBJECT", "EXACT_QUERIES", "REPRESENTATION_QUERIES", "CONCEPT_QUERIES")
    ]
)


class ExtractScreenHookTest(unittest.TestCase):
    def test_splits_off_the_line_and_uppercases_it(self):
        raw, hook = _extract_screen_hook(_FACTS_RAW + '\nSCREEN_HOOK: "This bell hasn\'t stopped since 1840"')
        self.assertEqual(hook, "THIS BELL HASN'T STOPPED SINCE 1840")
        self.assertNotIn("SCREEN_HOOK", raw)

    def test_missing_or_too_long_hook_gives_none_without_failing(self):
        self.assertEqual(_extract_screen_hook(_FACTS_RAW), (_FACTS_RAW, None))
        _, hook = _extract_screen_hook(_FACTS_RAW + "\nSCREEN_HOOK: one two three four five six seven eight")
        self.assertIsNone(hook)

    def test_hook_line_never_leaks_into_the_last_parsed_field(self):
        parsed = _parse_response("facts", _FACTS_RAW + "\nSCREEN_HOOK: THE PINK RING ISN'T BLOOD")
        self.assertEqual(parsed["screen_hook"], "THE PINK RING ISN'T BLOOD")
        concept = parsed["facts"][2]["keywords"]
        self.assertNotIn("SCREEN_HOOK", concept)


class RenderHookOverlayTest(unittest.TestCase):
    def test_long_hook_wraps_and_fits_the_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hook.png"
            w, h = assemble.render_hook_overlay(out, "PYTHON QUIETLY CACHES EVERY INTEGER BELOW 257", 1080)
            self.assertLessEqual(w, int(1080 * assemble.HOOK_MAX_WIDTH_FRACTION))
            self.assertEqual(Image.open(out).size, (w, h))
            # Must stay above the caption zone (~62% down a 1920px frame).
            self.assertLess(int(1920 * assemble.HOOK_Y_FRACTION) + h, int(1920 * 0.6))


if __name__ == "__main__":
    unittest.main()
