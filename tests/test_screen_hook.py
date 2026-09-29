"""Pure-logic tests for the on-screen hook (plan.py extraction +
assemble.py overlay rendering). No LLM or ffmpeg calls."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class HookOverlayKillSwitchTest(unittest.TestCase):
    """2026-09-29 owner ask ("we can't get past 100 views"): the first
    real hook batch underperformed the batch before it, so the overlay
    is off by default, controlled by ENABLE_SCREEN_HOOK_OVERLAY. These
    check assemble() itself only renders the overlay when explicitly
    turned back on -- no real ffmpeg/ffprobe/font work, everything that
    touches disk or a subprocess is mocked."""

    def _video(self):
        # template not in MUSIC_TEMPLATES -- skips assemble()'s music-bed
        # branch (its own ffmpeg volumedetect call), which is irrelevant
        # to what this test checks and would need its own separate mock.
        return {
            "id": "v1",
            "template": "veylorn_story",
            "audio_path": "/tmp/audio.wav",
            "video_path": "/tmp/video.mp4",
            "screen_hook": "THIS BELL HASN'T STOPPED SINCE 1840",
        }

    def _run_assemble(self):
        with mock.patch.object(assemble, "get_video", return_value=self._video()), mock.patch.object(
            assemble, "update_video"
        ), mock.patch.object(assemble, "shutil") as mock_shutil, mock.patch.object(
            assemble, "subprocess"
        ) as mock_subprocess, mock.patch.object(
            assemble, "audio_duration_seconds", return_value=45.0
        ), mock.patch.object(
            assemble, "_probe_dimensions", return_value=(1080, 1920)
        ), mock.patch.object(
            assemble, "pick_cta_variant", return_value=assemble.CTA_VARIANTS[0]
        ), mock.patch.object(
            assemble, "render_cta_overlay", return_value=(100, 50)
        ), mock.patch.object(
            assemble, "render_hook_overlay", return_value=(200, 80)
        ) as mock_render_hook, mock.patch.object(
            assemble, "OUTPUT_DIR", Path(tempfile.gettempdir())
        ):
            mock_shutil.which.return_value = "/usr/bin/ffmpeg"
            mock_subprocess.run.return_value = mock.Mock(returncode=0, stderr="")
            assemble.assemble("v1")
        return mock_render_hook

    def test_overlay_off_by_default(self):
        # ENABLE_SCREEN_HOOK_OVERLAY is read from the environment once at
        # import time (a plain module-level constant, not re-read per
        # call) -- default-off here means whatever it was actually set
        # to when pipeline.assemble was imported for this test run.
        self.assertFalse(assemble.ENABLE_SCREEN_HOOK_OVERLAY)
        mock_render_hook = self._run_assemble()
        mock_render_hook.assert_not_called()

    def test_overlay_renders_when_explicitly_enabled(self):
        with mock.patch.object(assemble, "ENABLE_SCREEN_HOOK_OVERLAY", True):
            mock_render_hook = self._run_assemble()
        mock_render_hook.assert_called_once()


if __name__ == "__main__":
    unittest.main()
