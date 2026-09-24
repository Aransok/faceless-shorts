"""Pure-logic test for pipeline/orchestrator.py's run_daily() template-
sequence selection -- no real LLM/render/upload calls, per CLAUDE.md's
testing rules.

orchestrator.py imports pipeline.upload (for the `upload` function) at
the top purely for its name -- upload.py in turn imports google-auth,
and this sandbox's cryptography install is broken in a way unrelated to
this repo's own code (a stale system cffi/cryptography conflict), so a
real import of it fails here even though it's fine in the real CI
environment that runs this workflow. Stub ONLY that one module,
temporarily (via patch.dict, auto-restored after this file's own import
line), so this doesn't leak a fake pipeline.upload into any other test
module's real import of it.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_had_real_pipeline_upload = "pipeline.upload" in sys.modules
if not _had_real_pipeline_upload:
    _stub = types.ModuleType("pipeline.upload")
    _stub.upload = lambda *a, **k: None
    sys.modules["pipeline.upload"] = _stub

import pipeline.orchestrator as orchestrator  # noqa: E402  (needs the stub above if upload.py can't import here)

if not _had_real_pipeline_upload:
    del sys.modules["pipeline.upload"]  # don't leak the stub to any other test module's real import


class RunDailyTemplateSequenceTest(unittest.TestCase):
    def setUp(self):
        self.plan_patcher = patch.object(orchestrator, "plan")
        self.plan_game_night_patcher = patch.object(orchestrator, "plan_game_night")
        self.plan_family_game_night_patcher = patch.object(orchestrator, "plan_family_game_night")
        self.plan_veylorn_story_patcher = patch.object(orchestrator, "plan_veylorn_story")
        self.run_video_patcher = patch.object(orchestrator, "run_video_to_completion")
        self.list_by_status_patcher = patch.object(orchestrator, "list_by_status", return_value=[])
        self.research_patcher = patch.object(orchestrator, "suggest_research_seed", return_value=None)
        self.mock_research = self.research_patcher.start()
        self.addCleanup(self.research_patcher.stop)
        self.mock_plan = self.plan_patcher.start()
        self.mock_plan_game_night = self.plan_game_night_patcher.start()
        self.mock_plan_family_game_night = self.plan_family_game_night_patcher.start()
        self.mock_plan_veylorn_story = self.plan_veylorn_story_patcher.start()
        self.mock_run_video = self.run_video_patcher.start()
        self.list_by_status_patcher.start()
        self.addCleanup(self.plan_patcher.stop)
        self.addCleanup(self.plan_game_night_patcher.stop)
        self.addCleanup(self.plan_family_game_night_patcher.stop)
        self.addCleanup(self.plan_veylorn_story_patcher.stop)
        self.addCleanup(self.run_video_patcher.stop)
        self.addCleanup(self.list_by_status_patcher.stop)

        self.mock_plan.side_effect = lambda template, **kwargs: f"vid-{template}"
        self.mock_plan_game_night.side_effect = lambda: "vid-game_night"
        self.mock_plan_family_game_night.side_effect = lambda: "vid-family_game_night"
        self.mock_plan_veylorn_story.side_effect = lambda: "vid-veylorn_story"
        self.mock_run_video.side_effect = lambda video_id: {
            "video_id": video_id, "template": "x", "status": "uploaded", "error": None,
        }

    def test_explicit_templates_run_as_exact_sequence(self):
        orchestrator.run_daily(count=5, templates=["sauce_recipe", "sauce_recipe"])
        called_templates = [c.args[0] for c in self.mock_plan.call_args_list]
        self.assertEqual(called_templates, ["sauce_recipe", "sauce_recipe"])

    def test_count_ignored_when_templates_given(self):
        # count=99 would run 99 videos under the old behavior -- with an
        # explicit templates list, only that list's length matters.
        orchestrator.run_daily(count=99, templates=["programming"])
        self.assertEqual(self.mock_plan.call_count, 1)

    def test_game_night_template_dispatches_to_its_own_planner(self):
        # Real gap found 2026-09-12: run_daily() had no path to CREATE a
        # new game_night video at all -- plan()'s TEMPLATES dict never
        # included it, so `--templates game_night` failed instantly with
        # "unknown template: 'game_night'" even though _advance_one_stage
        # already knew how to advance an existing one. plan_game_night()
        # takes no topic_hint (game_night has no topic/hint concept).
        orchestrator.run_daily(count=1, templates=["game_night"])
        self.mock_plan_game_night.assert_called_once_with()
        self.mock_plan.assert_not_called()

    def test_family_game_night_template_dispatches_to_its_own_planner(self):
        # Same gap, same fix, for the newer family_game_night track
        # (2026-09-13) -- wired up front this time rather than repeating
        # the game_night gap a second time.
        orchestrator.run_daily(count=1, templates=["family_game_night"])
        self.mock_plan_family_game_night.assert_called_once_with()
        self.mock_plan.assert_not_called()

    def test_veylorn_story_template_dispatches_to_its_own_planner(self):
        # veylorn_story (2026-09-18 standalone test format, see
        # HANDOFF.md) is deliberately absent from TEMPLATES -- it must
        # still be creatable via an explicit templates= override, same
        # dispatch shape as game_night/family_game_night.
        orchestrator.run_daily(count=1, templates=["veylorn_story"])
        self.mock_plan_veylorn_story.assert_called_once_with()
        self.mock_plan.assert_not_called()

    def test_veylorn_story_never_appears_in_the_default_rotation(self):
        self.assertNotIn("veylorn_story", orchestrator.TEMPLATES)

    def test_no_templates_falls_back_to_default_rotation_by_count(self):
        orchestrator.run_daily(count=3)
        called_templates = [c.args[0] for c in self.mock_plan.call_args_list]
        expected = [orchestrator.TEMPLATES[i % len(orchestrator.TEMPLATES)] for i in range(3)]
        self.assertEqual(called_templates, expected)

    def test_resumable_videos_run_before_new_ones_regardless_of_templates(self):
        with patch.object(orchestrator, "list_by_status") as mock_list:
            mock_list.side_effect = lambda status: (
                [{"id": "already-scripted-1"}] if status == "scripted" else []
            )
            orchestrator.run_daily(count=1, templates=["sauce_recipe"])

        resumed_ids = [c.args[0] for c in self.mock_run_video.call_args_list]
        self.assertIn("already-scripted-1", resumed_ids)
        # The resumed video plus the one newly planned video should both
        # have produced a run_video_to_completion call.
        self.assertEqual(self.mock_run_video.call_count, 2)

    def test_topic_hints_passed_to_plan_per_template(self):
        orchestrator.run_daily(
            count=5,
            templates=["facts", "programming"],
            topic_hints={"facts": "the bone collector caterpillar", "programming": "vibecoding bugs"},
        )
        calls = {c.args[0]: c.kwargs.get("topic_hint") for c in self.mock_plan.call_args_list}
        self.assertEqual(calls["facts"], "the bone collector caterpillar")
        self.assertEqual(calls["programming"], "vibecoding bugs")

    def test_research_seed_passed_when_no_manual_hint(self):
        self.mock_research.side_effect = lambda template: f"seed for {template}"
        orchestrator.run_daily(count=1, templates=["facts"])
        call = self.mock_plan.call_args_list[0]
        self.assertEqual(call.kwargs.get("research_seed"), "seed for facts")
        self.assertIsNone(call.kwargs.get("topic_hint"))

    def test_manual_hint_wins_and_research_is_never_called(self):
        self.mock_research.side_effect = lambda template: f"seed for {template}"
        orchestrator.run_daily(count=1, templates=["facts"], topic_hints={"facts": "owner's pick"})
        call = self.mock_plan.call_args_list[0]
        self.assertEqual(call.kwargs.get("topic_hint"), "owner's pick")
        self.assertIsNone(call.kwargs.get("research_seed"))
        self.mock_research.assert_not_called()

    def test_template_with_no_matching_hint_gets_none(self):
        orchestrator.run_daily(count=5, templates=["sauce_recipe"], topic_hints={"facts": "unrelated hint"})
        self.assertIsNone(self.mock_plan.call_args_list[0].kwargs.get("topic_hint"))

    def test_no_topic_hints_given_still_works(self):
        # topic_hints=None (the default) must not blow up run_daily() --
        # this is the ordinary daily-run path, exercised far more often
        # than the hinted one.
        orchestrator.run_daily(count=1, templates=["facts"])
        self.assertIsNone(self.mock_plan.call_args_list[0].kwargs.get("topic_hint"))

    def test_resumed_videos_never_get_a_topic_hint(self):
        # A resumed video's topic was already locked in when it was first
        # planned -- run_video_to_completion() (mocked here) doesn't call
        # plan() at all, so there's nothing to assert on plan() calls for
        # the resumed id, but this pins the actual invariant: topic_hints
        # only ever reaches plan() for a NEW video this call starts.
        with patch.object(orchestrator, "list_by_status") as mock_list:
            mock_list.side_effect = lambda status: (
                [{"id": "already-scripted-1"}] if status == "scripted" else []
            )
            orchestrator.run_daily(count=1, templates=["facts"], topic_hints={"facts": "a hint"})

        self.assertEqual(self.mock_plan.call_count, 1)
        self.assertEqual(self.mock_plan.call_args_list[0].kwargs.get("topic_hint"), "a hint")


class AdvanceOneStageScriptedDispatchTest(unittest.TestCase):
    """family_game_night's "scripted" stage calls render_family_game_night()
    (does narration+render+split in one stage, see that module's own
    docstring) instead of the generic voice() every other template uses
    -- no real render/DB calls, get_video()/voice()/render_family_game_night()
    all mocked."""

    def setUp(self):
        self.get_video_patcher = patch.object(orchestrator, "get_video")
        self.voice_patcher = patch.object(orchestrator, "voice")
        self.render_family_game_patcher = patch.object(orchestrator, "render_family_game_night")
        self.render_veylorn_patcher = patch.object(orchestrator, "render_veylorn_story")
        self.mock_get_video = self.get_video_patcher.start()
        self.mock_voice = self.voice_patcher.start()
        self.mock_render_family_game = self.render_family_game_patcher.start()
        self.mock_render_veylorn = self.render_veylorn_patcher.start()
        self.addCleanup(self.get_video_patcher.stop)
        self.addCleanup(self.voice_patcher.stop)
        self.addCleanup(self.render_family_game_patcher.stop)
        self.addCleanup(self.render_veylorn_patcher.stop)

    def _set_video(self, template: str, status: str = "scripted"):
        video = {"id": "vid-1", "status": status, "template": template}
        self.mock_get_video.side_effect = lambda video_id: {**video, "status": "scripted"}

    def test_family_game_night_scripted_calls_render_family_game_not_voice(self):
        self._set_video("family_game_night")
        orchestrator._advance_one_stage("vid-1")
        self.mock_render_family_game.assert_called_once_with("vid-1")
        self.mock_voice.assert_not_called()

    def test_veylorn_story_scripted_calls_render_veylorn_not_voice(self):
        self._set_video("veylorn_story")
        orchestrator._advance_one_stage("vid-1")
        self.mock_render_veylorn.assert_called_once_with("vid-1")
        self.mock_voice.assert_not_called()

    def test_other_templates_scripted_still_call_voice(self):
        for template in ("facts", "programming", "sauce_recipe", "game_night", "quiz_longform"):
            with self.subTest(template=template):
                self.mock_voice.reset_mock()
                self.mock_render_family_game.reset_mock()
                self.mock_render_veylorn.reset_mock()
                self._set_video(template)
                orchestrator._advance_one_stage("vid-1")
                self.mock_voice.assert_called_once_with("vid-1")
                self.mock_render_family_game.assert_not_called()
                self.mock_render_veylorn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
