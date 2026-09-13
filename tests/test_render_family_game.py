"""Pure-logic tests for pipeline/render_family_game.py -- no real
ffmpeg/DB calls per CLAUDE.md's testing rules. render_episode() and
ffmpeg subprocess calls are mocked; only the video-row loading/splitting/
status-update logic itself is under test."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline.render_family_game as rfg

_SEGMENTS_JSON = '[{"kind": "host", "script_text": "hi"}]'


class RenderFamilyGameNightTest(unittest.TestCase):
    def setUp(self):
        self.video = {"id": "vid-1", "family_game_segments_json": _SEGMENTS_JSON}
        self.get_video_patcher = mock.patch.object(rfg, "get_video", return_value=self.video)
        self.update_video_patcher = mock.patch.object(rfg, "update_video")
        self.render_episode_patcher = mock.patch.object(rfg, "render_episode")
        self.run_ffmpeg_patcher = mock.patch.object(rfg, "_run_ffmpeg")
        self.mock_get_video = self.get_video_patcher.start()
        self.mock_update_video = self.update_video_patcher.start()
        self.mock_render_episode = self.render_episode_patcher.start()
        self.mock_run_ffmpeg = self.run_ffmpeg_patcher.start()
        self.addCleanup(self.get_video_patcher.stop)
        self.addCleanup(self.update_video_patcher.stop)
        self.addCleanup(self.render_episode_patcher.stop)
        self.addCleanup(self.run_ffmpeg_patcher.stop)

    def test_raises_on_missing_video(self):
        self.mock_get_video.return_value = None
        with self.assertRaises(ValueError):
            rfg.render_family_game_night("vid-1")

    def test_raises_when_no_segments_stored(self):
        self.video["family_game_segments_json"] = None
        with self.assertRaises(ValueError):
            rfg.render_family_game_night("vid-1")
        self.mock_render_episode.assert_not_called()

    def test_calls_render_episode_with_the_parsed_segments(self):
        rfg.render_family_game_night("vid-1")
        args, _ = self.mock_render_episode.call_args
        self.assertEqual(args[0], [{"kind": "host", "script_text": "hi"}])

    def test_splits_combined_output_into_video_and_audio(self):
        rfg.render_family_game_night("vid-1")
        self.assertEqual(self.mock_run_ffmpeg.call_count, 2)
        video_call, audio_call = self.mock_run_ffmpeg.call_args_list
        self.assertIn("-an", video_call.args[0])
        self.assertIn("-vn", audio_call.args[0])

    def test_updates_status_to_visuals_ready_with_both_paths(self):
        rfg.render_family_game_night("vid-1")
        kwargs = self.mock_update_video.call_args.kwargs
        self.assertEqual(kwargs["status"], "visuals_ready")
        self.assertTrue(kwargs["video_path"].endswith("_video.mp4"))
        self.assertTrue(kwargs["audio_path"].endswith("_audio.wav"))


if __name__ == "__main__":
    unittest.main()
