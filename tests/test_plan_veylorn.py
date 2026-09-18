"""Pure-logic tests for pipeline/plan_veylorn.py's episode-JSON parsing
-- no real LLM calls, per CLAUDE.md's testing rules.
"""

from __future__ import annotations

import json
import unittest

from pipeline import plan_veylorn as pv


def _episode(beats: list[dict], title: str = "Test Episode") -> str:
    return json.dumps({"title": title, "beats": beats})


def _beat(round_index: int, beat_type: str = "main", narration: str = "Something happens.", image_prompt: str = "a scene", on_screen_prompt: str = "") -> dict:
    return {
        "round_index": round_index, "beat_type": beat_type, "narration": narration,
        "image_prompt": image_prompt, "on_screen_prompt": on_screen_prompt,
    }


def _valid_beats() -> list[dict]:
    beats = []
    for i in range(10):
        if i in (3, 4):
            beat_type = "choice"
        elif i >= 7:
            beat_type = "bonus"
        else:
            beat_type = "main"
        on_screen_prompt = "PRESS 3: ...\nPRESS 4: ..." if i == 2 else ("PRESS 7: ...\nPRESS 8: ...\nPRESS 9: ..." if i == 6 else "")
        beats.append(_beat(i, beat_type, on_screen_prompt=on_screen_prompt))
    return beats


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

    def test_missing_on_screen_prompt_at_beat_2_rejected(self):
        """Real owner feedback (2026-09-18): pressing 7/8/9 didn't feel
        like a real choice without visible on-screen text announcing
        it -- a missing prompt at either choice beat must fail loudly,
        not silently ship an unannounced choice."""
        beats = _valid_beats()
        beats[2]["on_screen_prompt"] = ""
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(beats))

    def test_missing_on_screen_prompt_at_beat_6_rejected(self):
        beats = _valid_beats()
        beats[6]["on_screen_prompt"] = ""
        with self.assertRaises(ValueError):
            pv._parse_episode_response(_episode(beats))

    def test_on_screen_prompt_not_required_on_non_choice_beats(self):
        beats = _valid_beats()  # beats other than 2/6 already have on_screen_prompt=""
        episode = pv._parse_episode_response(_episode(beats))
        self.assertEqual(len(episode["beats"]), 10)


if __name__ == "__main__":
    unittest.main()
