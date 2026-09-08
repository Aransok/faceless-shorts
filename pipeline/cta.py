"""Rotating spoken subscribe CTA angles. Folded into the narration
script itself (not just the visual badge overlay from Phase 4) so the CTA
line is never the same copy-pasted sentence video after video — part of
the same authenticity fix as persona.py/approaches.py. Keep it low-key,
never urgency-based ("subscribe now!!"), which reads as manipulative
rather than authentic.
"""

from __future__ import annotations

import random

CTA_ANGLES = [
    {
        "name": "direct_ask",
        "instruction": (
            "Include one brief, low-key subscribe mention somewhere "
            "in the script — plain and direct (e.g. \"subscribe for more "
            "of this\"), not an urgency-based push and not a vague "
            "conditional tail like \"if you like this stuff\" or \"if "
            "that bugs you too\" standing in for an actual reason."
        ),
    },
    {
        "name": "tied_to_topic",
        "instruction": (
            "Include one brief, low-key subscribe mention, phrased "
            "so it connects to THIS video's specific topic (e.g. \"if "
            "stuff like this catches you off guard, that's basically the "
            "whole channel\") rather than a generic tacked-on line."
        ),
    },
    {
        "name": "mid_script_aside",
        "instruction": (
            "Include one brief, low-key subscribe mention as a "
            "casual mid-script aside — dropped naturally in the middle of "
            "the narration, not saved for the very end. It still needs a "
            "real reason to be there (tie it to what you just said), not "
            "a vague conditional like \"if you're into this\" bolted on."
        ),
    },
]

_MILESTONE_ANGLE = {
    "name": "milestone",
    "instruction": (
        "Include one brief, low-key subscribe mention that "
        "naturally references the real milestone stated below — say the "
        "number plainly, don't round it or invent context around it."
    ),
}


def pick_cta_angle(milestone_line: str | None = None) -> dict:
    """A milestone mention takes priority over the regular rotation when
    one is genuinely pending — see pipeline/milestones.py."""
    if milestone_line:
        return _MILESTONE_ANGLE
    return random.choice(CTA_ANGLES)


def cta_guidance_block(angle: dict, milestone_line: str | None = None) -> str:
    """Formatted for appending directly to an LLM prompt."""
    block = (
        "\n\nSPOKEN CTA FOR THIS VIDEO (fold this into the script text "
        "itself, not just a visual overlay — it counts toward the "
        "existing word budget, don't add extra length for it):\n"
        f"- {angle['instruction']}\n"
        "- Keep it to one sentence at most, low-key — never urgency "
        "language like \"subscribe now!!\", that reads as manipulative "
        "rather than authentic.\n"
        "- Always say \"subscribe\", never \"follow\" — this is YouTube, "
        "not Instagram/TikTok, and \"follow\" reads as a platform "
        "mismatch to anyone who notices.\n"
        "- This line follows the exact same authenticity bar as the rest "
        "of the script (see the channel persona above) — it is not "
        "exempt. No generic filler, no vague conditional (\"if you like "
        "this stuff\", \"if that bugs you too\") standing in for a real "
        "connection to THIS video's actual content.\n"
    )
    if milestone_line:
        block += f"- Real milestone to mention: {milestone_line}\n"
    return block
