"""Pure-logic tests for pipeline/ai_tells.py, scripts/doctor.py and the
comment checks in pipeline/upload.py. No network or LLM calls."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import ai_tells


class FixDashesTest(unittest.TestCase):
    def test_em_dash_becomes_comma(self):
        self.assertEqual(ai_tells.fix_dashes("It works — mostly."), "It works, mostly.")

    def test_tight_em_dash(self):
        self.assertEqual(ai_tells.fix_dashes("fast—really fast"), "fast, really fast")

    def test_spaced_double_hyphen(self):
        self.assertEqual(ai_tells.fix_dashes("Wait -- what?"), "Wait, what?")

    def test_leaves_hyphens_and_flags_alone(self):
        text = "Run pip install --upgrade and a well-known x--; done"
        self.assertEqual(ai_tells.fix_dashes(text), text)

    def test_no_comma_before_punctuation(self):
        self.assertEqual(ai_tells.fix_dashes("Done —."), "Done.")

    def test_number_range(self):
        self.assertEqual(ai_tells.fix_dashes("from 1990\u20132000"), "from 1990 to 2000")

    def test_empty(self):
        self.assertEqual(ai_tells.fix_dashes(""), "")


class LintTest(unittest.TestCase):
    def test_clean_text(self):
        self.assertEqual(ai_tells.lint("Python evaluates default arguments once, at def time."), [])
        self.assertIsNone(ai_tells.feedback("Mustard seeds were used as currency in some markets."))

    def test_dash_skipped_unless_asked(self):
        self.assertEqual(ai_tells.lint("a — b"), [])
        self.assertEqual(ai_tells.lint("a — b", include_fixable=True)[0][0], "dash")

    def test_real_production_tells(self):
        # Phrases found in this channel's real stored scripts.
        for text, name in (
            ("That's not just a typo.", "not_x_but_y"),
            ("This isn't just slow.", "not_x_but_y"),
            ("Here's the catch.", "staged_reveal"),
            ("Here's the twist:", "staged_reveal"),
            ("Buckle up.", "stock_words"),
            ("And that changes everything.", "dramatic_closer"),
        ):
            names = [n for n, _m, _h in ai_tells.lint(text)]
            self.assertIn(name, names, text)

    def test_feedback_lists_each_hit(self):
        fb = ai_tells.feedback("Let's dive in. Here's the kicker.")
        self.assertIn("dive in", fb)
        self.assertIn("kicker", fb)


class RepeatsRecentTest(unittest.TestCase):
    def test_same_opener_caught(self):
        recent = ["Did this one get you too? Mutable defaults are sneaky."]
        self.assertEqual(
            ai_tells.repeats_recent("Did this one get you too? Integer caching strikes again.", recent),
            recent[0],
        )

    def test_different_opener_passes(self):
        recent = ["Did this one get you too? Mutable defaults are sneaky."]
        self.assertIsNone(ai_tells.repeats_recent("Bechamel without a roux sounds wrong but works.", recent))

    def test_short_comment_never_matches(self):
        self.assertIsNone(ai_tells.repeats_recent("Wild.", ["Wild."]))


class GenerateCommentTest(unittest.TestCase):
    VIDEO = {"id": "v1", "topic": "mutable defaults", "hook": "h", "script_text": "s"}

    def _run(self, replies: list[str], recent: list[str] | None = None) -> str:
        from pipeline import upload

        with mock.patch.object(upload, "call_bulk_llm", side_effect=replies), mock.patch.object(
            upload, "_recent_comments", return_value=recent or []
        ):
            return upload._generate_cta_comment(self.VIDEO)

    def test_clean_first_try(self):
        self.assertEqual(self._run(["COMMENT: Default lists outliving the call is so cursed."]),
                         "Default lists outliving the call is so cursed.")

    def test_dash_fixed_without_retry(self):
        self.assertEqual(self._run(["COMMENT: Default lists — so cursed."]), "Default lists, so cursed.")

    def test_tell_triggers_one_retry(self):
        out = self._run(["COMMENT: Here's the thing about defaults.", "COMMENT: Defaults bite everyone once."])
        self.assertEqual(out, "Defaults bite everyone once.")

    def test_repeat_of_recent_triggers_retry_then_raises(self):
        recent = ["Did this one get you too? Mutable defaults are sneaky."]
        same = "COMMENT: Did this one get you too? Defaults again."
        with self.assertRaises(ValueError):
            self._run([same, same], recent)


class DoctorTest(unittest.TestCase):
    def test_missing_secret_fails(self):
        from scripts import doctor

        rows = doctor.check({"LLM_BACKEND": "groq", "FACTS_VISUAL_SOURCE": "stock"}, youtube=True)
        failed = {name for level, name, _ in rows if level == "fail"}
        self.assertIn("GROQ_API_KEY", failed)
        self.assertIn("PEXELS_API_KEY", failed)
        self.assertIn("YT_REFRESH_TOKEN", failed)

    def test_groq_bulk_only_warns(self):
        from scripts import doctor

        rows = doctor.check({"LLM_BACKEND": "ollama", "BULK_LLM_BACKEND": "groq"}, youtube=False)
        levels = {name: level for level, name, _ in rows}
        self.assertEqual(levels["GROQ_API_KEY"], "warn")


if __name__ == "__main__":
    unittest.main()
