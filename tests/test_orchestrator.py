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
        self.run_video_patcher = patch.object(orchestrator, "run_video_to_completion")
        self.list_by_status_patcher = patch.object(orchestrator, "list_by_status", return_value=[])
        self.mock_plan = self.plan_patcher.start()
        self.mock_run_video = self.run_video_patcher.start()
        self.list_by_status_patcher.start()
        self.addCleanup(self.plan_patcher.stop)
        self.addCleanup(self.run_video_patcher.stop)
        self.addCleanup(self.list_by_status_patcher.stop)

        self.mock_plan.side_effect = lambda template, topic_hint=None: f"vid-{template}"
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


if __name__ == "__main__":
    unittest.main()
