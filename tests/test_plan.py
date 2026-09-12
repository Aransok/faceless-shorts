"""Pure-logic tests for pipeline/plan.py's authenticity-review wiring
(pipeline/review_script.py integration) -- no real LLM calls, no DB
writes, per CLAUDE.md's testing rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.plan import (
    ClaudeUsageLimitError,
    _build_rewrite_prompt,
    _extract_narration,
    _topic_hint_block,
    call_bulk_llm,
    call_llm,
)


class ExtractNarrationTest(unittest.TestCase):
    def test_programming_joins_hook_and_step_scripts_only(self):
        parsed = {
            "hook": "This default argument bug is sneaky.",
            "steps": [
                {"script_text": "Define a function with a list default.", "code_snippet": "def f(x=[]):"},
                {"script_text": "Every call shares the same list.", "code_snippet": "def f(x=[]): ..."},
            ],
        }
        narration = _extract_narration("programming", parsed)
        self.assertIn("This default argument bug is sneaky.", narration)
        self.assertIn("Define a function with a list default.", narration)
        self.assertIn("Every call shares the same list.", narration)
        self.assertNotIn("def f", narration)  # code must not leak into the reviewed text

    def test_facts_joins_hook_and_fact_scripts_only(self):
        parsed = {
            "hook": "Bananas are berries, strawberries aren't.",
            "facts": [
                {"script_text": "Octopuses have three hearts.", "keywords": "octopus swimming"},
                {"script_text": "Honey never spoils.", "keywords": "honey jar"},
            ],
        }
        narration = _extract_narration("facts", parsed)
        self.assertIn("Bananas are berries, strawberries aren't.", narration)
        self.assertIn("Octopuses have three hearts.", narration)
        self.assertIn("Honey never spoils.", narration)
        self.assertNotIn("octopus swimming", narration)  # keywords must not leak in


class BuildRewritePromptTest(unittest.TestCase):
    def test_includes_original_prompt_previous_draft_and_feedback(self):
        prompt = _build_rewrite_prompt(
            "original prompt instructions",
            "TOPIC: x\nHOOK: y",
            "REWRITE_REQUIRED\n1. generic filler",
        )
        self.assertIn("original prompt instructions", prompt)
        self.assertIn("TOPIC: x\nHOOK: y", prompt)
        self.assertIn("REWRITE_REQUIRED", prompt)
        self.assertIn("generic filler", prompt)


class TopicHintBlockTest(unittest.TestCase):
    def test_includes_the_hint_text(self):
        block = _topic_hint_block("the bone collector caterpillar (Hawaii, 2025 discovery)")
        self.assertIn("the bone collector caterpillar (Hawaii, 2025 discovery)", block)

    def test_frames_it_as_a_direction_not_verbatim_text(self):
        # Same "never hand the LLM a literal copyable phrase" lesson this
        # project has re-learned several times (cta.py, approaches.yaml)
        # -- the hint must read as guidance, not insertable script text.
        block = _topic_hint_block("some hint")
        self.assertIn("not a script to copy", block)

    def test_warns_against_repeating_unverified_stats(self):
        block = _topic_hint_block("some hint")
        self.assertIn("unverified", block)


class CallLlmFallbackTest(unittest.TestCase):
    """call_llm()'s usage-limit fallback: only a genuine claude CLI
    usage-limit hit (not any other failure) should ever divert to
    LLM_FALLBACK_BACKEND, and only when one is actually configured and
    differs from the primary backend. No real subprocess/network calls —
    subprocess.run and requests.post are both mocked."""

    def setUp(self):
        patcher = mock.patch.dict(
            "os.environ",
            {"LLM_BACKEND": "claude_code", "LLM_FALLBACK_BACKEND": "", "GROQ_API_KEY": ""},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude")
    @mock.patch("pipeline.plan.subprocess.run")
    def test_claude_success_never_touches_fallback(self, mock_run, mock_which):
        mock_run.return_value = mock.Mock(returncode=0, stdout="a real script", stderr="")
        self.assertEqual(call_llm("prompt"), "a real script")

    @mock.patch("pipeline.plan.requests.post")
    @mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude")
    @mock.patch("pipeline.plan.subprocess.run")
    def test_session_limit_wording_also_triggers_fallback(self, mock_run, mock_which, mock_post):
        # Real bug (2026-09-12): a real production failure said "You've
        # hit your session limit · resets 4:40pm (UTC)" -- "session
        # limit", not "usage limit" -- and the old pattern missed it
        # entirely, so the fallback silently never fired on a wording
        # variant that actually happens in production.
        mock_run.return_value = mock.Mock(
            returncode=1, stdout="", stderr="You've hit your session limit · resets 4:40pm (UTC)"
        )
        mock_post.return_value = mock.Mock()
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json = lambda: {"choices": [{"message": {"content": "fallback script"}}]}
        with mock.patch.dict("os.environ", {"LLM_FALLBACK_BACKEND": "groq", "GROQ_API_KEY": "fake-key"}):
            result = call_llm("prompt")
        self.assertEqual(result, "fallback script")

    @mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude")
    @mock.patch("pipeline.plan.subprocess.run")
    def test_usage_limit_without_fallback_configured_raises(self, mock_run, mock_which):
        mock_run.return_value = mock.Mock(
            returncode=1, stdout="", stderr="Claude AI usage limit reached, please try again after 2pm"
        )
        with self.assertRaises(ClaudeUsageLimitError):
            call_llm("prompt")

    @mock.patch("pipeline.plan.requests.post")
    @mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude")
    @mock.patch("pipeline.plan.subprocess.run")
    def test_usage_limit_falls_back_to_configured_backend(self, mock_run, mock_which, mock_post):
        mock_run.return_value = mock.Mock(
            returncode=1, stdout="", stderr="Claude AI usage limit reached, please try again after 2pm"
        )
        mock_post.return_value = mock.Mock()
        mock_post.return_value.raise_for_status = lambda: None
        mock_post.return_value.json = lambda: {"choices": [{"message": {"content": "fallback script"}}]}
        with mock.patch.dict("os.environ", {"LLM_FALLBACK_BACKEND": "groq", "GROQ_API_KEY": "fake-key"}):
            result = call_llm("prompt")
        self.assertEqual(result, "fallback script")
        mock_post.assert_called_once()

    @mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude")
    @mock.patch("pipeline.plan.subprocess.run")
    def test_non_usage_limit_failure_never_falls_back(self, mock_run, mock_which):
        # A real CLI bug/crash must fail loudly, not silently degrade to a
        # lower-quality backend -- only a genuine usage-limit hit is
        # fallback-eligible (see call_llm()'s docstring).
        mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="some unrelated crash")
        with mock.patch.dict("os.environ", {"LLM_FALLBACK_BACKEND": "groq", "GROQ_API_KEY": "fake-key"}):
            with self.assertRaises(RuntimeError) as ctx:
                call_llm("prompt")
        self.assertNotIsInstance(ctx.exception, ClaudeUsageLimitError)

    @mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude")
    @mock.patch("pipeline.plan.subprocess.run")
    def test_fallback_same_as_primary_backend_is_a_noop(self, mock_run, mock_which):
        # LLM_FALLBACK_BACKEND=claude_code (same as the primary) would
        # just retry the exact call that already hit the limit -- treat
        # it as no fallback configured instead of looping.
        mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="usage limit reached")
        with mock.patch.dict("os.environ", {"LLM_FALLBACK_BACKEND": "claude_code"}):
            with self.assertRaises(ClaudeUsageLimitError):
                call_llm("prompt")


class CallBulkLlmTest(unittest.TestCase):
    """call_bulk_llm() is a pure dispatcher for the cheap-backend split
    (metadata/CTA generation) -- see pipeline/metadata.py and
    pipeline/upload.py for the retry/fallback logic that wraps it. No
    real network calls -- requests.post is mocked."""

    def test_defaults_to_groq(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch("pipeline.plan.requests.post") as mock_post:
                mock_post.return_value = mock.Mock()
                mock_post.return_value.raise_for_status = lambda: None
                mock_post.return_value.json = lambda: {"choices": [{"message": {"content": "hi"}}]}
                with mock.patch.dict("os.environ", {"GROQ_API_KEY": "fake-key"}):
                    result = call_bulk_llm("prompt")
        self.assertEqual(result, "hi")
        mock_post.assert_called_once()
        self.assertIn("api.groq.com", mock_post.call_args[0][0])

    def test_honors_bulk_backend_override(self):
        with mock.patch.dict("os.environ", {"BULK_LLM_BACKEND": "claude_code"}):
            with mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude"):
                with mock.patch("pipeline.plan.subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=0, stdout="claude output", stderr="")
                    result = call_bulk_llm("prompt")
        self.assertEqual(result, "claude output")

    def test_never_applies_usage_limit_fallback(self):
        # call_bulk_llm is a plain dispatcher -- it doesn't carry
        # call_llm()'s claude_code-usage-limit-fallback behavior. If a
        # caller points BULK_LLM_BACKEND at claude_code and it hits a
        # usage limit, that's just an error for the caller to handle,
        # not something this function retries on its own.
        with mock.patch.dict("os.environ", {"BULK_LLM_BACKEND": "claude_code", "LLM_FALLBACK_BACKEND": "groq"}):
            with mock.patch("pipeline.plan.shutil.which", return_value="/usr/bin/claude"):
                with mock.patch("pipeline.plan.subprocess.run") as mock_run:
                    mock_run.return_value = mock.Mock(returncode=1, stdout="", stderr="usage limit reached")
                    with self.assertRaises(ClaudeUsageLimitError):
                        call_bulk_llm("prompt")


class GenerateReviewedTest(unittest.TestCase):
    def test_approves_first_draft_without_rewriting(self):
        import pipeline.plan as plan_module

        llm_calls = []
        review_calls = []
        raw_response = (
            "TOPIC: t\nHOOK: h\n"
            "FACT_1_SCRIPT: a\nFACT_1_SUBJECT: s1\nFACT_1_EXACT_QUERIES: q1\nFACT_1_REPRESENTATION_QUERIES: q1\nFACT_1_CONCEPT_QUERIES: none\n"
            "FACT_2_SCRIPT: b\nFACT_2_SUBJECT: s2\nFACT_2_EXACT_QUERIES: q2\nFACT_2_REPRESENTATION_QUERIES: q2\nFACT_2_CONCEPT_QUERIES: none\n"
            "FACT_3_SCRIPT: c\nFACT_3_SUBJECT: s3\nFACT_3_EXACT_QUERIES: q3\nFACT_3_REPRESENTATION_QUERIES: q3\nFACT_3_CONCEPT_QUERIES: none"
        )

        def fake_llm(prompt: str) -> str:
            llm_calls.append(prompt)
            return raw_response

        def fake_review(narration: str, fn) -> dict:
            review_calls.append(narration)
            return {"approved": True, "feedback": "APPROVED"}

        original_llm = plan_module.call_llm
        original_review = plan_module.review_script
        plan_module.call_llm = fake_llm
        plan_module.review_script = fake_review
        try:
            parsed = plan_module._generate_reviewed("facts", "prompt")
        finally:
            plan_module.call_llm = original_llm
            plan_module.review_script = original_review

        self.assertEqual(parsed["topic"], "t")
        self.assertEqual(len(llm_calls), 1)  # no rewrite needed
        self.assertEqual(len(review_calls), 1)

    def test_rewrites_until_approved_then_raises_after_max_attempts(self):
        import pipeline.plan as plan_module

        raw_response = (
            "TOPIC: t\nHOOK: h\n"
            "FACT_1_SCRIPT: a\nFACT_1_SUBJECT: s1\nFACT_1_EXACT_QUERIES: q1\nFACT_1_REPRESENTATION_QUERIES: q1\nFACT_1_CONCEPT_QUERIES: none\n"
            "FACT_2_SCRIPT: b\nFACT_2_SUBJECT: s2\nFACT_2_EXACT_QUERIES: q2\nFACT_2_REPRESENTATION_QUERIES: q2\nFACT_2_CONCEPT_QUERIES: none\n"
            "FACT_3_SCRIPT: c\nFACT_3_SUBJECT: s3\nFACT_3_EXACT_QUERIES: q3\nFACT_3_REPRESENTATION_QUERIES: q3\nFACT_3_CONCEPT_QUERIES: none"
        )

        def fake_llm(prompt: str) -> str:
            return raw_response

        original_llm = plan_module.call_llm
        original_review = plan_module.review_script
        plan_module.call_llm = fake_llm
        # Every review comes back rejected -- should raise once attempts exceed REVIEW_MAX_REWRITES.
        plan_module.review_script = lambda narration, fn: {"approved": False, "feedback": "REWRITE_REQUIRED\nstill generic"}
        try:
            with self.assertRaises(RuntimeError):
                plan_module._generate_reviewed("facts", "prompt")
        finally:
            plan_module.call_llm = original_llm
            plan_module.review_script = original_review


if __name__ == "__main__":
    unittest.main()
