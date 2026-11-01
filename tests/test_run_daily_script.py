"""scripts/run_daily.py exit behaviour (reliability pass 2026-10-31):
partial failure stays green (fail-soft), a run that made nothing goes red.
run_daily() is mocked; nothing is planned, rendered or uploaded."""

from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import run_daily as script


def _r(status: str, error: str | None = None) -> dict:
    return {"video_id": "v", "template": "facts", "status": status, "error": error}


class RunDailyExitCodeTest(unittest.TestCase):
    def _run(self, results: list[dict]) -> tuple[str, int]:
        buf = io.StringIO()
        code = 0
        with patch.object(script, "run_daily", return_value=results), patch.object(sys, "argv", ["run_daily.py", "--count", "3"]):
            try:
                with redirect_stdout(buf):
                    script.main()
            except SystemExit as exc:
                code = int(exc.code or 0)
        return buf.getvalue(), code

    def test_all_good_exits_zero(self):
        out, code = self._run([_r("uploaded"), _r("uploaded"), _r("uploaded")])
        self.assertEqual(code, 0)
        self.assertIn("[run_daily] RESULT ok=3 failed=0 attempted=3", out)

    def test_partial_failure_stays_green(self):
        out, code = self._run([_r("uploaded"), _r("failed", "NoAudioReceived: x"), _r("uploaded")])
        self.assertEqual(code, 0)
        self.assertIn("ok=2 failed=1 attempted=3", out)

    def test_total_failure_exits_one_after_printing_every_failure(self):
        out, code = self._run([_r("failed", "A: 1"), _r("failed", "B: 2")])
        self.assertEqual(code, 1)
        self.assertIn("ok=0 failed=2 attempted=2", out)
        self.assertIn("(A: 1)", out)

    def test_nothing_attempted_is_not_a_failure(self):
        _, code = self._run([])  # e.g. the daily cap was already reached
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
