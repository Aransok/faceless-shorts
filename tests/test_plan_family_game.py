"""Pure-logic tests for pipeline/plan_family_game.py -- no real LLM/DB
calls per CLAUDE.md's testing rules. compose_episode_with_quality_gate()
is mocked (its own real behavior is covered by
tests/test_family_game_quality_gate.py and tests/test_family_game_episode.py),
as are state.py's create_video/update_video."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline.plan_family_game as pfg

_FAKE_EPISODE = {
    "title": "Family Game Night: Test Theme",
    "theme": "Family Game Night: Test Theme",
    "intro": "Welcome back to Family Game Night. Tonight: test theme.",
    "games": [
        {
            "game_type": "spot_the_difference",
            "difficulty": "easy",
            "round": {"answer": "mug color"},
            "segments": [
                {"kind": "host", "beat": "intro", "game_type": "spot_the_difference", "round_index": 0,
                 "script_text": "Here's the scene.", "duration_seconds": None, "round_data_json": None},
                {"kind": "player", "beat": "think", "game_type": "spot_the_difference", "round_index": 0,
                 "script_text": "", "duration_seconds": 8.0, "round_data_json": None},
            ],
        },
    ],
    "outro": "That's the episode.",
    "quality_warnings": [],
}


class PlanFamilyGameNightTest(unittest.TestCase):
    @mock.patch("pipeline.plan_family_game.update_video")
    @mock.patch("pipeline.plan_family_game.create_video", return_value="vid-fg-1")
    @mock.patch("pipeline.plan_family_game.compose_episode_with_quality_gate", return_value=_FAKE_EPISODE)
    def test_creates_video_with_the_right_template(self, mock_compose, mock_create, mock_update):
        video_id = pfg.plan_family_game_night()
        self.assertEqual(video_id, "vid-fg-1")
        mock_create.assert_called_once_with(pfg.TEMPLATE, topic=_FAKE_EPISODE["theme"])

    @mock.patch("pipeline.plan_family_game.update_video")
    @mock.patch("pipeline.plan_family_game.create_video", return_value="vid-fg-1")
    @mock.patch("pipeline.plan_family_game.compose_episode_with_quality_gate", return_value=_FAKE_EPISODE)
    def test_stores_segments_as_json_and_sets_scripted_status(self, mock_compose, mock_create, mock_update):
        pfg.plan_family_game_night()
        kwargs = mock_update.call_args.kwargs
        self.assertEqual(kwargs["status"], "scripted")
        self.assertEqual(kwargs["hook"], _FAKE_EPISODE["intro"])
        stored_segments = json.loads(kwargs["family_game_segments_json"])
        # flatten_episode_to_segments() (the real function, not mocked)
        # wraps the fake episode's 2 round segments with its own
        # synthetic episode-level intro/outro segments -- 4 total.
        self.assertEqual(len(stored_segments), 4)
        self.assertEqual(stored_segments[0]["script_text"], _FAKE_EPISODE["intro"])
        self.assertEqual(stored_segments[1]["script_text"], "Here's the scene.")
        self.assertEqual(stored_segments[-1]["script_text"], _FAKE_EPISODE["outro"])

    @mock.patch("pipeline.plan_family_game.update_video")
    @mock.patch("pipeline.plan_family_game.create_video", return_value="vid-fg-1")
    @mock.patch("pipeline.plan_family_game.compose_episode_with_quality_gate", return_value=_FAKE_EPISODE)
    def test_script_text_joins_only_non_empty_host_lines(self, mock_compose, mock_create, mock_update):
        # The PLAYER_TIME segment's script_text is "" -- must be skipped,
        # not leave a stray double space in the joined script.
        pfg.plan_family_game_night()
        script_text = mock_update.call_args.kwargs["script_text"]
        self.assertNotIn("  ", script_text)
        self.assertEqual(
            script_text,
            f"{_FAKE_EPISODE['intro']} Here's the scene. {_FAKE_EPISODE['outro']}",
        )


if __name__ == "__main__":
    unittest.main()
