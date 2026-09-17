"""Pure-logic tests for pipeline/plan_veylorn.py's episode-JSON parsing
-- no real LLM calls, per CLAUDE.md's testing rules.
"""

from __future__ import annotations

import json
import unittest

from pipeline import plan_veylorn as pv


def _episode(beats: list[dict], title: str = "Test Episode") -> str:
    return json.dumps({"title": title, "beats": beats})


def _beat(round_index: int, beat_type: str = "main", narration: str = "Something happens.", image_prompt: str = "a scene") -> dict:
    return {"round_index": round_index, "beat_type": beat_type, "narration": narration, "image_prompt": image_prompt}


def _valid_beats() -> list[dict]:
    return [_beat(i, "main" if i < 7 else "bonus") for i in range(10)]


class TestParseEpisodeResponse(unittest.TestCase):
    def test_valid_episode_parses_cleanly(self):
        episode = pv._parse_episode_response(_episode(_valid_beats()))
        self.assertEqual(episode["title"], "Test Episode")
        self.assertEqual(len(episode["beats"]), 10)

    def test_extracts_json_from_surrounding_prose(self):
        """Real LLM responses sometimes wrap the JSON in commentary --
        must still find and parse it, same lesson as review_script.py's
        own last-match-wins verdict parsing."""
        raw = "Here is the episode:\n" + _episode(_valid_beats()) + "\nHope that works!"
        episode = pv._parse_episode_response(raw)
        self.assertEqual(len(episode["beats"]), 10)

    def test_wrong_beat_count_rejected(self):
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(_valid_beats()[:9]))

    def test_duplicate_round_index_rejected(self):
        beats = _valid_beats()
        beats[1]["round_index"] = 0  # duplicate of beat 0
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(beats))

    def test_missing_round_index_rejected(self):
        beats = _valid_beats()
        beats[9]["round_index"] = 10  # skips 9, out of the required 0-9 range
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(beats))

    def test_missing_narration_rejected(self):
        beats = _valid_beats()
        beats[3]["narration"] = ""
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(beats))

    def test_missing_image_prompt_rejected(self):
        beats = _valid_beats()
        del beats[5]["image_prompt"]
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(beats))

    def test_no_json_object_raises(self):
        with self.assertRaises(ValueError):
            pv._parse_episode_response("sorry, I can't do that")


if __name__ == "__main__":
    unittest.main()
