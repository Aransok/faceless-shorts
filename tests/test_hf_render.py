"""Pure-logic tests for pipeline/hf_render.py. No real render, no network."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import hf_render


class TrialWindowTest(unittest.TestCase):
    def test_on_only_with_flag_and_inside_window(self):
        on = {"VISUAL_RENDERER": "hyperframes"}
        self.assertTrue(hf_render.trial_active(date(2026, 10, 27), on))
        self.assertTrue(hf_render.trial_active(date(2026, 11, 2), on))
        self.assertFalse(hf_render.trial_active(date(2026, 11, 3), on))
        self.assertFalse(hf_render.trial_active(date(2026, 10, 27), {}))
        self.assertFalse(hf_render.trial_active(date(2026, 10, 27), {"VISUAL_RENDERER": "motionmaxxing"}))


class BeatLabelTest(unittest.TestCase):
    def test_uses_subject(self):
        kw = json.dumps({"subject": "Ball lightning", "exact": ["x"]})
        self.assertEqual(hf_render.beat_label(kw, "ignored"), "Ball lightning")

    def test_long_subject_cut_on_word_boundary(self):
        kw = json.dumps({"subject": "Pan reduction, cold cream finish with extra butter"})
        label = hf_render.beat_label(kw, "")
        self.assertLessEqual(len(label), hf_render.MAX_LABEL_CHARS)
        self.assertTrue("Pan reduction, cold cream finish with extra butter".startswith(label))
        self.assertFalse(label.endswith(","))

    def test_falls_back_to_script_words(self):
        self.assertEqual(hf_render.beat_label("not json", "Honey never spoils in sealed jars"), "Honey never spoils in")
        self.assertEqual(hf_render.beat_label(None, None), "")


class HtmlTest(unittest.TestCase):
    def test_timeline_and_markup(self):
        self.assertEqual(hf_render.beat_timeline([10, 5.5]), [(0.0, 10.0), (10.0, 5.5)])
        page = hf_render.build_html(["A <b>", "Second thing"], [10.0, 5.5], "footage.mp4")
        self.assertIn('data-duration="15.5"', page)
        self.assertIn('id="b1" class="clip beat" data-start="10.0" data-duration="5.5"', page)
        self.assertIn("&lt;b&gt;", page)  # labels are escaped
        self.assertIn('src="footage.mp4" muted', page)
        self.assertNotIn("Math.random", page)
        self.assertNotIn("https://", page.split("<body>")[1])  # no network at render time


class TryHyperframesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.footage = Path(self.tmp.name) / "v1_facts.mp4"
        self.footage.write_bytes(b"x")
        self.video = {"id": "v1", "template": "facts", "video_path": str(self.footage)}
        self.steps = [
            {"duration": 10.0, "keywords": json.dumps({"subject": "One"}), "script_text": "a"},
            {"duration": 8.0, "keywords": json.dumps({"subject": "Two"}), "script_text": "b"},
        ]
        env = mock.patch.dict("os.environ", {"VISUAL_RENDERER": "hyperframes"})
        env.start()
        self.addCleanup(env.stop)
        today = mock.patch.object(hf_render, "trial_active", return_value=True)
        today.start()
        self.addCleanup(today.stop)
        work = mock.patch.object(hf_render, "WORK_DIR", Path(self.tmp.name) / "work")
        work.start()
        self.addCleanup(work.stop)

    def _run(self, render_side_effect=None, probed=18.0):
        updates = []
        with mock.patch("pipeline.state.get_video", return_value=self.video), \
             mock.patch("pipeline.state.get_video_steps", return_value=self.steps), \
             mock.patch("pipeline.state.update_video", side_effect=lambda vid, **kw: updates.append(kw)), \
             mock.patch.object(hf_render, "write_project", return_value=Path(self.tmp.name)), \
             mock.patch.object(hf_render, "render", side_effect=render_side_effect), \
             mock.patch.object(hf_render, "_probe_duration", return_value=probed):
            ok = hf_render.try_hyperframes("v1")
        return ok, updates

    def test_success_swaps_video_and_records_renderer(self):
        ok, updates = self._run()
        self.assertTrue(ok)
        self.assertEqual(updates, [{"video_path": str(self.footage.with_name("v1_hf.mp4")), "renderer": "hyperframes"}])

    def test_render_failure_keeps_footage(self):
        ok, updates = self._run(render_side_effect=hf_render.HFRenderError("boom"))
        self.assertFalse(ok)
        self.assertEqual(updates, [])

    def test_short_render_rejected(self):
        ok, updates = self._run(probed=12.0)
        self.assertFalse(ok)
        self.assertEqual(updates, [])

    def test_other_templates_untouched(self):
        self.video["template"] = "programming"
        ok, updates = self._run()
        self.assertFalse(ok)
        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()
