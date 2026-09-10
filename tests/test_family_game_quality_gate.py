"""Pure-logic tests for pipeline/family_game/quality_gate.py. Every
GAME_MODULES entry used by compose_episode_with_quality_gate() is
monkeypatched with a lightweight fake (same pattern as
test_family_game_episode.py) so these tests never exercise a real
module's content generation -- including never hitting
higher_or_lower's real LLM call."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pipeline.family_game.quality_gate as qg
from pipeline.family_game.base import HOST_TIME, PLAYER_TIME, make_round, make_segment
from pipeline.rotation import ROTATION_LOG_PATH


def _valid_round_and_segments(game_type="higher_or_lower", answer="stub answer", title="stub title", narration="short line"):
    round_ = make_round(
        game_type=game_type, difficulty="medium", title=title, instructions="do the thing",
        presentation_data={"stub": True}, answer=answer, explanation="stub explanation",
        thinking_time=5.0, reveal_data={"stub": True},
    )
    segments = [
        make_segment(game_type, 0, HOST_TIME, "intro", narration),
        make_segment(game_type, 0, PLAYER_TIME, "think", "", duration_seconds=5.0),
        make_segment(game_type, 0, HOST_TIME, "reveal", "the reveal line"),
    ]
    return round_, segments


class CheckRoundTest(unittest.TestCase):
    def test_well_formed_round_passes(self):
        round_, segments = _valid_round_and_segments()
        ok, reason = qg.check_round(round_, segments)
        self.assertTrue(ok, reason)

    def test_delegates_to_validate_round_for_structural_checks(self):
        round_, segments = _valid_round_and_segments()
        del round_["explanation"]
        ok, reason = qg.check_round(round_, segments)
        self.assertFalse(ok)
        self.assertIn("missing", reason)

    def test_thinking_time_below_floor_fails(self):
        round_, segments = _valid_round_and_segments()
        segments[1] = {**segments[1], "duration_seconds": 1.0}
        ok, reason = qg.check_round(round_, segments)
        self.assertFalse(ok)
        self.assertIn("floor", reason)

    def test_thinking_time_at_floor_passes(self):
        round_, segments = _valid_round_and_segments()
        segments[1] = {**segments[1], "duration_seconds": qg.MIN_THINKING_SECONDS}
        ok, reason = qg.check_round(round_, segments)
        self.assertTrue(ok, reason)

    def test_overly_long_narration_fails(self):
        round_, segments = _valid_round_and_segments(narration=" ".join(["word"] * (qg.MAX_HOST_NARRATION_WORDS + 1)))
        ok, reason = qg.check_round(round_, segments)
        self.assertFalse(ok)
        self.assertIn("word", reason)

    def test_narration_at_the_cap_passes(self):
        round_, segments = _valid_round_and_segments(narration=" ".join(["word"] * qg.MAX_HOST_NARRATION_WORDS))
        ok, reason = qg.check_round(round_, segments)
        self.assertTrue(ok, reason)


class GenerateRoundWithQualityGateTest(unittest.TestCase):
    def test_succeeds_on_first_valid_attempt(self):
        round_, segments = _valid_round_and_segments()
        module = SimpleNamespace(generate_round=lambda avoid_topics, round_index, difficulty="medium": (round_, segments))
        result_round, result_segments = qg.generate_round_with_quality_gate(module, [], 0)
        self.assertIs(result_round, round_)

    def test_retries_then_succeeds(self):
        bad_round, bad_segments = _valid_round_and_segments(narration=" ".join(["word"] * (qg.MAX_HOST_NARRATION_WORDS + 1)))
        good_round, good_segments = _valid_round_and_segments()
        attempts = {"n": 0}

        def fake_generate(avoid_topics, round_index, difficulty="medium"):
            attempts["n"] += 1
            return (bad_round, bad_segments) if attempts["n"] == 1 else (good_round, good_segments)

        module = SimpleNamespace(generate_round=fake_generate)
        result_round, _ = qg.generate_round_with_quality_gate(module, [], 0)
        self.assertIs(result_round, good_round)
        self.assertEqual(attempts["n"], 2)

    def test_raises_after_max_attempts_exhausted(self):
        bad_round, bad_segments = _valid_round_and_segments(narration=" ".join(["word"] * (qg.MAX_HOST_NARRATION_WORDS + 1)))
        module = SimpleNamespace(generate_round=lambda avoid_topics, round_index, difficulty="medium": (bad_round, bad_segments))
        with self.assertRaises(qg.QualityGateFailure):
            qg.generate_round_with_quality_gate(module, [], 0)


class CheckEpisodeTest(unittest.TestCase):
    def _episode(self, *rounds_and_types):
        games = [{"game_type": gt, "difficulty": "medium", "round": r, "segments": s} for gt, r, s in rounds_and_types]
        return {"games": games}

    def test_no_duplicates_passes(self):
        r1, s1 = _valid_round_and_segments(game_type="a", answer="answer one", title="title one")
        r2, s2 = _valid_round_and_segments(game_type="b", answer="answer two", title="title two")
        ok, problems = qg.check_episode(self._episode(("a", r1, s1), ("b", r2, s2)))
        self.assertTrue(ok, problems)
        self.assertEqual(problems, [])

    def test_duplicate_answer_flagged(self):
        r1, s1 = _valid_round_and_segments(game_type="a", answer="same answer", title="title one")
        r2, s2 = _valid_round_and_segments(game_type="b", answer="same answer", title="title two")
        ok, problems = qg.check_episode(self._episode(("a", r1, s1), ("b", r2, s2)))
        self.assertFalse(ok)
        self.assertTrue(any("duplicate answer" in p for p in problems))

    def test_duplicate_title_flagged(self):
        r1, s1 = _valid_round_and_segments(game_type="a", answer="answer one", title="same title")
        r2, s2 = _valid_round_and_segments(game_type="b", answer="answer two", title="same title")
        ok, problems = qg.check_episode(self._episode(("a", r1, s1), ("b", r2, s2)))
        self.assertFalse(ok)
        self.assertTrue(any("duplicate title" in p for p in problems))

    def test_answer_comparison_is_case_insensitive(self):
        r1, s1 = _valid_round_and_segments(game_type="a", answer="Same Answer", title="title one")
        r2, s2 = _valid_round_and_segments(game_type="b", answer="same answer", title="title two")
        ok, problems = qg.check_episode(self._episode(("a", r1, s1), ("b", r2, s2)))
        self.assertFalse(ok)


def _fake_module(game_type: str):
    def generate_round(avoid_topics, round_index, difficulty="medium"):
        return _valid_round_and_segments(game_type=game_type, answer=f"{game_type} answer", title=f"{game_type} title")
    return SimpleNamespace(generate_round=generate_round)


class ComposeEpisodeWithQualityGateTest(unittest.TestCase):
    def setUp(self):
        self._original_modules = dict(qg.GAME_MODULES)
        qg.GAME_MODULES = {game_type: _fake_module(game_type) for game_type in self._original_modules}
        self.addCleanup(self._restore)
        self._original_rotation_log = ROTATION_LOG_PATH.read_text(encoding="utf-8") if ROTATION_LOG_PATH.exists() else None

    def _restore(self):
        qg.GAME_MODULES = self._original_modules
        if self._original_rotation_log is None:
            ROTATION_LOG_PATH.unlink(missing_ok=True)
        else:
            ROTATION_LOG_PATH.write_text(self._original_rotation_log, encoding="utf-8")

    def test_produces_a_complete_episode_with_no_quality_warnings(self):
        episode = qg.compose_episode_with_quality_gate()
        self.assertEqual(episode["quality_warnings"], [])
        self.assertEqual(len(episode["games"]), len(qg.MAIN_ROUND_PLAN) + 1)

    def test_flags_a_real_cross_round_duplicate(self):
        # Force every game type's fake module to return the SAME answer,
        # so whichever types get picked this run are guaranteed to
        # collide -- a real, not synthetic, exercise of check_episode()
        # wired through the full compose path.
        qg.GAME_MODULES = {
            game_type: SimpleNamespace(
                generate_round=lambda avoid_topics, round_index, difficulty="medium", gt=game_type: _valid_round_and_segments(
                    game_type=gt, answer="always the same answer", title=f"{gt} title",
                )
            )
            for game_type in self._original_modules
        }
        episode = qg.compose_episode_with_quality_gate()
        self.assertGreater(len(episode["quality_warnings"]), 0)


if __name__ == "__main__":
    unittest.main()
