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


if __name__ == "__main__":
    unittest.main()
