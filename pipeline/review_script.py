"""Phase 17: post-generation authenticity/anti-hallucination review pass.
See config/persona.md and ROADMAP.md. Runs after plan() generates a
script, before it's accepted -- catches generic AI phrasing, fabricated
personal experience, unsupported factual claims, and padding that
persona.md's generation-time rules didn't prevent. Never invents
replacement facts -- only flags problems for the generation call to fix.

Takes the LLM-calling function as a parameter rather than importing
pipeline.plan.call_llm directly -- plan.py is this module's caller, and
importing back from here would create a circular import.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REVIEWER_PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "script_reviewer_template.txt"

# Same lesson learned the hard way in games/base.py's verify_claim(): a
# model asked for "respond in EXACTLY this format" sometimes still
# reasons out loud first, emitting a draft verdict its own follow-up
# text then reverses. Taking the LAST match is the model's settled
# answer; taking the first risks silently keeping an abandoned draft.
_VERDICT_PATTERN = re.compile(r"\b(APPROVED|REWRITE_REQUIRED)\b")


def _parse_review_response(text: str) -> dict:
    text = text.strip()
    matches = list(_VERDICT_PATTERN.finditer(text))
    if not matches:
        raise ValueError(f"reviewer output missing APPROVED/REWRITE_REQUIRED verdict:\n{text}")
    verdict = matches[-1].group(1)
    return {"approved": verdict == "APPROVED", "feedback": text}


def review_script(narration: str, call_llm_fn: Callable[[str], str]) -> dict:
    """Sends `narration` (plain spoken-narration text, not the raw
    field-tagged LLM output -- code/keywords/labels would just confuse a
    reviewer checking for authentic-sounding narration) to the reviewer
    prompt. Returns {"approved": bool, "feedback": str} -- feedback is
    the reviewer's full response, useful as-is to feed back into a
    rewrite prompt whether approved or not.
    """
    prompt_body = REVIEWER_PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_body.replace("{script}", narration)
    raw = call_llm_fn(prompt)
    return _parse_review_response(raw)


if __name__ == "__main__":
    def _fake_llm(prompt: str) -> str:
        # Sample narration deliberately full of the problems this pass
        # should catch, so running this file standalone demonstrates a
        # real REWRITE_REQUIRED verdict without a real LLM call.
        return (
            "REWRITE_REQUIRED\n"
            "1. \"Pretty cool, right?\" -- generic AI filler, adds no information.\n"
            "2. \"I tried this myself and it changed everything.\" -- fabricated "
            "personal experience on a fully automated channel.\n"
        )

    sample_narration = (
        "This is a cool fact about octopuses. Pretty cool, right? "
        "I tried this myself and it changed everything."
    )
    result = review_script(sample_narration, _fake_llm)
    print(f"approved: {result['approved']}")
    print(f"feedback:\n{result['feedback']}")
    sys.exit(0)
