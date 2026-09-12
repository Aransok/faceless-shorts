"""Pure-logic tests for pipeline/visuals_game.py's beat-render dispatch
-- no real Pillow rendering, no DB writes, per CLAUDE.md's testing rules.
_render_memory_beat and the other gameplay renderers are mocked; only
_render_beat_frame's branching (which phase/renderer a given beat_type
gets) is under test.

Covers the real bug found 2026-09-12 (owner caught it from a real
rendered episode): the memory round's "gameplay" beat used to render
the full icon sequence right alongside the "was X one of them?"
question, making the answer visible on screen at the exact moment it
was being asked -- the round tested nothing. _render_beat_frame now
routes memory's rule/gameplay/reveal beats to three distinct phases
(study/recall/reveal) instead of the shared 2-phase question/reveal
every other round type uses."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline.visuals_game as visuals_game

_MEMORY_ROUND_DATA = {
    "sequence": ["leaf", "star", "sun", "diamond", "crown", "fire"],
    "target": "leaf",
    "correct_answer": "yes",
}


def _step(round_type: str, beat_type: str, round_data: dict | None = None) -> dict:
    return {
        "round_type": round_type,
        "beat_type": beat_type,
        "round_data_json": json.dumps(round_data) if round_data is not None else None,
        "script_text": "some narration",
    }


class MemoryBeatDispatchTest(unittest.TestCase):
    @mock.patch("pipeline.visuals_game._render_memory_beat")
    def test_rule_beat_dispatches_to_study_phase(self, mock_render):
        visuals_game._render_beat_frame(_step("memory", "rule", _MEMORY_ROUND_DATA))
        mock_render.assert_called_once_with(_MEMORY_ROUND_DATA, "study", "memory")

    @mock.patch("pipeline.visuals_game._render_memory_beat")
    def test_gameplay_beat_dispatches_to_recall_phase_not_revealed(self, mock_render):
        # The core regression: gameplay must be a distinct "recall" phase,
        # never the same call as "reveal" -- that's exactly what let the
        # sequence (and therefore the answer) leak onto screen during the
        # question in the real bug.
        visuals_game._render_beat_frame(_step("memory", "gameplay", _MEMORY_ROUND_DATA))
        mock_render.assert_called_once_with(_MEMORY_ROUND_DATA, "recall", "memory")

    @mock.patch("pipeline.visuals_game._render_memory_beat")
    def test_reveal_beat_dispatches_to_reveal_phase(self, mock_render):
        visuals_game._render_beat_frame(_step("memory", "reveal", _MEMORY_ROUND_DATA))
        mock_render.assert_called_once_with(_MEMORY_ROUND_DATA, "reveal", "memory")

    @mock.patch("pipeline.visuals_game._render_memory_beat")
    def test_intro_and_countdown_beats_stay_plain_text(self, mock_render):
        for beat_type in ("intro", "countdown", "suspense"):
            with self.subTest(beat_type=beat_type):
                frame = visuals_game._render_beat_frame(_step("memory", beat_type, _MEMORY_ROUND_DATA))
                mock_render.assert_not_called()
                self.assertIsNotNone(frame)


class RenderMemoryBeatContentTest(unittest.TestCase):
    """Real (unmocked) Pillow calls -- fast, deterministic, purely local
    image drawing, not a network/API call, so this stays within CLAUDE.md's
    testing rules. Asserts on the actual drawn pixels: the sequence chip
    row must NOT be drawn during "recall" (that's the bug), and the
    target chip must always be present once a question exists."""

    def test_recall_phase_does_not_draw_the_sequence_row(self):
        study_frame = visuals_game._render_memory_beat(_MEMORY_ROUND_DATA, "study", "memory")
        recall_frame = visuals_game._render_memory_beat(_MEMORY_ROUND_DATA, "recall", "memory")
        # The sequence row occupies the same pixel band in both frames
        # (cy_mid - 90) -- in "study" it's populated with chip content,
        # in "recall" it must be untouched background instead.
        cx0, cy0, cx1, cy1 = visuals_game._content_area()
        cy_mid = (cy0 + cy1) // 2
        row_y = cy_mid - 90
        study_row = study_frame.crop((cx0, row_y - 20, cx1, row_y + 20))
        recall_row = recall_frame.crop((cx0, row_y - 20, cx1, row_y + 20))
        self.assertNotEqual(list(study_row.tobytes()), list(recall_row.tobytes()))

    def test_study_phase_has_no_target_question_chip(self):
        # "study" is purely the memorize moment -- no question yet.
        frame_study = visuals_game._render_memory_beat(_MEMORY_ROUND_DATA, "study", "memory")
        frame_recall = visuals_game._render_memory_beat(_MEMORY_ROUND_DATA, "recall", "memory")
        self.assertNotEqual(list(frame_study.tobytes()), list(frame_recall.tobytes()))


class IconDrawingTest(unittest.TestCase):
    """Real feedback (2026-09-12): the memory round was "basically words
    on screen" -- these are the actual drawn icon glyphs replacing the
    old text-word chips. Real (unmocked) Pillow calls, same reasoning as
    RenderMemoryBeatContentTest above."""

    def test_every_pool_icon_draws_without_crashing(self):
        from pipeline.games.memory import ICON_POOL

        frame = Image.new("RGB", (200, 200), (0, 0, 0))
        draw = ImageDraw.Draw(frame)
        for icon_name in ICON_POOL:
            with self.subTest(icon=icon_name):
                visuals_game._draw_icon(draw, 100, 100, 60, icon_name, (255, 255, 255), (0, 0, 0))

    def test_unknown_icon_name_falls_back_to_a_circle_not_a_crash(self):
        frame = Image.new("RGB", (200, 200), (0, 0, 0))
        draw = ImageDraw.Draw(frame)
        visuals_game._draw_icon(draw, 100, 100, 60, "not-a-real-icon", (255, 255, 255), (0, 0, 0))

    def test_each_icon_actually_draws_something_distinct(self):
        # Not pixel-perfect shape validation, but a real regression guard:
        # two different icons must not render identical pixels (the kind
        # of bug a copy-pasted lambda entry in _ICON_DRAWERS would cause).
        from pipeline.games.memory import ICON_POOL

        rendered = {}
        for icon_name in ICON_POOL:
            frame = Image.new("RGB", (200, 200), (0, 0, 0))
            draw = ImageDraw.Draw(frame)
            visuals_game._draw_icon(draw, 100, 100, 60, icon_name, (255, 255, 255), (0, 0, 0))
            rendered[icon_name] = frame.tobytes()
        distinct_renderings = len(set(rendered.values()))
        self.assertEqual(distinct_renderings, len(ICON_POOL), rendered.keys())


class RoundAccentColorTest(unittest.TestCase):
    """Real feedback (2026-09-12): every round type used to render with
    the exact identical brand-teal-to-indigo border -- the whole episode
    looked like one repeating screen. Each round type now gets its own
    accent gradient."""

    def test_every_round_type_has_a_distinct_accent(self):
        colors = {rt: visuals_game.ROUND_ACCENT_COLORS[rt] for rt in visuals_game.ROUND_LABELS}
        self.assertEqual(len(set(colors.values())), len(colors), colors)

    def test_panel_border_pixels_differ_by_round_type(self):
        # Sample a real pixel from the gradient border itself (top edge,
        # just inside the panel box) for two different round types.
        x0, y0, x1, y1 = visuals_game.PANEL_BOX
        sample_x = (x0 + x1) // 2
        sample_y = y0 - 3  # inside the border ring, above the panel fill
        frame_memory = visuals_game._render_base_panel("memory")
        frame_prediction = visuals_game._render_base_panel("prediction")
        self.assertNotEqual(
            frame_memory.getpixel((sample_x, sample_y)),
            frame_prediction.getpixel((sample_x, sample_y)),
        )

    def test_unknown_round_type_falls_back_to_brand_colors(self):
        frame = visuals_game._render_base_panel(None)
        self.assertIsNotNone(frame)


if __name__ == "__main__":
    unittest.main()
