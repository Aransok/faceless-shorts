"""Pure-logic tests for pipeline/family_game/episode.py -- the episode
composer. Every GAME_MODULES entry is monkeypatched with a lightweight
fake generate_round() (a SimpleNamespace, not the real module), so these
tests exercise ONLY the composer's own orchestration logic (selection,
ordering, theme rotation, flattening) -- never the real LLM call
higher_or_lower.generate_round() would otherwise make. Each real game
module's own content-generation logic is already covered by its own
test file; this file's job is different (and per CLAUDE.md's testing
rule, this also means zero real network/LLM calls here)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline.family_game.episode as episode_module
from pipeline.family_game.base import HOST_TIME, PLAYER_TIME, make_round, make_segment
from pipeline.rotation import ROTATION_LOG_PATH


def _fake_generate_round(game_type: str):
    def generate_round(avoid_topics, round_index, difficulty="medium"):
        round_ = make_round(
            game_type=game_type,
            difficulty=difficulty,
            title=f"{game_type} title",
            instructions="do the thing",
            presentation_data={"stub": True},
            answer="stub answer",
            explanation="stub explanation",
            thinking_time=5.0,
            reveal_data={"stub": True},
        )
        segments = [
            make_segment(game_type, round_index, HOST_TIME, "intro", f"{game_type} intro"),
            make_segment(game_type, round_index, PLAYER_TIME, "think", "", duration_seconds=5.0),
            make_segment(game_type, round_index, HOST_TIME, "reveal", f"{game_type} reveal"),
        ]
        return round_, segments

    return generate_round


class EpisodeComposerTest(unittest.TestCase):
    def setUp(self):
        self._original_modules = dict(episode_module.GAME_MODULES)
        episode_module.GAME_MODULES = {
            game_type: SimpleNamespace(generate_round=_fake_generate_round(game_type))
            for game_type in self._original_modules
        }
        self.addCleanup(self._restore)
        # The theme rotation touches a real file (data/phrase_usage.json)
        # -- back it up and restore it so a test run never leaves the
        # real project file mutated, same discipline this project
        # already applies to state.db/data/phrase_usage.json elsewhere.
        self._original_rotation_log = ROTATION_LOG_PATH.read_text(encoding="utf-8") if ROTATION_LOG_PATH.exists() else None

    def _restore(self):
        episode_module.GAME_MODULES = self._original_modules
        if self._original_rotation_log is None:
            ROTATION_LOG_PATH.unlink(missing_ok=True)
        else:
            ROTATION_LOG_PATH.write_text(self._original_rotation_log, encoding="utf-8")

    def test_rapid_fire_is_always_the_closing_round(self):
        for _ in range(20):
            episode = episode_module.compose_episode()
            self.assertEqual(episode["games"][-1]["game_type"], "rapid_fire")

    def test_main_rounds_never_repeat_a_game_type(self):
        for _ in range(20):
            episode = episode_module.compose_episode()
            main_round_types = [g["game_type"] for g in episode["games"][:-1]]
            self.assertEqual(len(main_round_types), len(set(main_round_types)))

    def test_episode_has_six_rounds_total(self):
        episode = episode_module.compose_episode()
        self.assertEqual(len(episode["games"]), len(episode_module.MAIN_ROUND_PLAN) + 1)

    def test_theme_comes_from_the_pool(self):
        for _ in range(20):
            episode = episode_module.compose_episode()
            self.assertIn(episode["theme"], episode_module.THEME_POOL)

    def test_intro_mentions_the_theme(self):
        episode = episode_module.compose_episode()
        self.assertIn(episode["theme"].lower(), episode["intro"].lower())

    def test_difficulty_follows_the_configured_curve(self):
        episode = episode_module.compose_episode()
        difficulties = [g["difficulty"] for g in episode["games"]]
        expected = [slot["difficulty"] for slot in episode_module.MAIN_ROUND_PLAN] + [episode_module.CLOSING_DIFFICULTY]
        self.assertEqual(difficulties, expected)

    def test_avoid_topics_by_type_is_passed_to_the_right_module_only(self):
        seen_avoid_topics = {}

        def spy_generate_round(game_type):
            def generate_round(avoid_topics, round_index, difficulty="medium"):
                seen_avoid_topics[game_type] = avoid_topics
                return _fake_generate_round(game_type)(avoid_topics, round_index, difficulty)
            return generate_round

        episode_module.GAME_MODULES = {
            game_type: SimpleNamespace(generate_round=spy_generate_round(game_type))
            for game_type in self._original_modules
        }

        episode_module.compose_episode(avoid_topics_by_type={"memory_challenge": ["already used topic"]})
        self.assertEqual(seen_avoid_topics["memory_challenge"], ["already used topic"])
        self.assertEqual(seen_avoid_topics["rapid_fire"], [])

    def test_flatten_episode_to_segments_starts_with_intro_ends_with_outro(self):
        episode = episode_module.compose_episode()
        segments = episode_module.flatten_episode_to_segments(episode)
        self.assertEqual(segments[0]["script_text"], episode["intro"])
        self.assertEqual(segments[-1]["script_text"], episode["outro"])

    def test_flatten_episode_to_segments_includes_every_round_segment_in_order(self):
        episode = episode_module.compose_episode()
        segments = episode_module.flatten_episode_to_segments(episode)
        expected_game_type_sequence = [g["game_type"] for g in episode["games"] for _ in g["segments"]]
        middle_game_types = [s["game_type"] for s in segments[1:-1]]
        self.assertEqual(middle_game_types, expected_game_type_sequence)

    def test_flatten_includes_real_player_time(self):
        episode = episode_module.compose_episode()
        segments = episode_module.flatten_episode_to_segments(episode)
        player_segments = [s for s in segments if s["kind"] == PLAYER_TIME]
        self.assertGreater(len(player_segments), 0)
        for s in player_segments:
            self.assertGreater(s["duration_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
