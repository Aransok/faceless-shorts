"""Rotating spoken CTA system (Phase 18). Folded into the narration
script itself (not just the visual badge overlay from Phase 4) so the
CTA line is never the same copy-pasted sentence video after video — part
of the same authenticity fix as persona.py/approaches.py.

Owner-provided spec: one CTA goal per video (never stack multiple asks),
weighted toward comment/subscribe over share/save, 10% of videos get no
spoken CTA at all, and every CTA must pass the same topic-specificity bar
as the rest of the script (never copy-paste onto an unrelated video).

Deliberately gives the LLM an ABSTRACT instruction per type, never a
literal example phrase to insert — Phase 17's real verification found
that literal example phrases get copied near-verbatim (both a cta.py
example and several config/approaches.yaml hook_openers were picked up
word-for-word and then rejected by the authenticity review pass for
being generic). Not repeating that mistake here.
"""

from __future__ import annotations

import random

# Each type maps to one of the spec's five CTA goals with the owner's
# requested relative frequency (comment 40 / subscribe 25 / save 15 /
# share 10 / none 10 -- see the owner's CTA-frequency table). "Like" and
# "watch another episode" from the spec's goal list aren't separate
# top-level buckets: a next-episode tease is folded into subscribe_series
# (same "there's more of this coming" promise), and Like CTAs are
# deliberately not in the main weighted rotation at all, per the spec's
# own "use sparingly, not every video" rule for likes.
CTA_TYPES = {
    "comment_question": {
        "goal": "comment",
        "weight": 40,
        "instruction": (
            "Include one brief, genuine question or challenge tied to a "
            "SPECIFIC decision, choice, surprising moment, or result in "
            "THIS video -- something a viewer would actually have a real "
            "opinion or answer for, not a generic engagement prompt. Only "
            "ask something the video itself actually raised or revealed."
        ),
    },
    "subscribe_series": {
        "goal": "subscribe",
        "weight": 25,
        "instruction": (
            "Include one brief, low-key subscribe mention that tells the "
            "viewer WHAT they'll get by subscribing -- a concrete promise "
            "tied to THIS video's specific format or topic (more of "
            "exactly this kind of thing), not a vague 'more great "
            "content'. This may also work as a tease that there's another "
            "one coming, if that fits the video better than a direct ask. "
            "Do not claim a specific upload day/schedule unless one is "
            "given below."
        ),
    },
    "save": {
        "goal": "save",
        "weight": 15,
        "instruction": (
            "Include one brief mention encouraging the viewer to save or "
            "remember this for a SPECIFIC future situation genuinely "
            "implied by this video's content -- a real practical reason "
            "to come back to it, not a generic 'save this for later'."
        ),
    },
    "share": {
        "goal": "share",
        "weight": 10,
        "instruction": (
            "Include one brief mention encouraging the viewer to send "
            "this to a SPECIFIC kind of person this content is genuinely "
            "relevant to (the person who'd actually relate to this exact "
            "topic), not a generic 'share this with someone'."
        ),
    },
    "none": {
        "goal": "none",
        "weight": 10,
        "instruction": None,
    },
}

_MILESTONE_TYPE = {
    "goal": "milestone",
    "weight": 0,
    "instruction": (
        "Include one brief, low-key subscribe mention that naturally "
        "references the real milestone stated below -- say the number "
        "plainly, don't round it or invent context around it."
    ),
}

# Per-template hints (spec's "Template-Specific CTA Ideas") -- a short
# nudge toward what a comment/save/share CTA naturally looks like for
# THIS content type, still abstract (no literal phrase), just narrowing
# what "specific" means for this template.
_TEMPLATE_HINTS = {
    "programming": {
        "comment_question": "e.g. whether the viewer spotted the bug before the reveal, or would have made the same mistake.",
        "save": "e.g. the specific situation where this gotcha would actually bite someone.",
        "share": "e.g. a developer who'd recognize this exact mistake from their own code.",
    },
    "facts": {
        "comment_question": "e.g. which of the facts in this video was the most surprising, or which one they'd already heard.",
        "save": "e.g. a real situation where this specific fact would come up again.",
        "share": "e.g. someone who'd specifically care about this exact topic.",
    },
    "sauce_recipe": {
        "comment_question": "e.g. which of the three sauces they'd actually make first.",
        "save": "e.g. the next time they have the specific ingredients/situation this sauce calls for.",
        "share": "e.g. someone who cooks, or who'd specifically use one of these sauces.",
    },
    "game_night": {
        "comment_question": "e.g. how many rounds they got right, or whether they'd have guessed the same answer.",
        "save": "e.g. their next actual game night with other people.",
        "share": "e.g. someone they'd want to play this with.",
    },
}


def _weighted_choice(exclude_type: str | None) -> str:
    candidates = {k: v["weight"] for k, v in CTA_TYPES.items() if v["weight"] > 0}
    # "Do not repeat the same CTA type in consecutive videos when
    # alternatives are available" -- drop just the immediately-previous
    # type, not a wider window (5 buckets is too few to exclude more than
    # one and still respect the target frequency distribution).
    if exclude_type in candidates and len(candidates) > 1:
        del candidates[exclude_type]
    types, weights = zip(*candidates.items())
    return random.choices(types, weights=weights, k=1)[0]


def pick_cta_angle(milestone_line: str | None = None, last_cta_type: str | None = None) -> dict:
    """A milestone mention takes priority over the regular rotation when
    one is genuinely pending — see pipeline/milestones.py. Otherwise a
    weighted pick across CTA_TYPES, avoiding an exact repeat of the
    immediately-previous video's type. `last_cta_type` should be the
    most recent video's stored cta_angle (see pipeline/state.py's
    recent_cta_types()) — pass None if there isn't one yet."""
    if milestone_line:
        return {"name": "milestone", **_MILESTONE_TYPE}
    picked = _weighted_choice(last_cta_type)
    return {"name": picked, **CTA_TYPES[picked]}


def cta_guidance_block(angle: dict, template: str, milestone_line: str | None = None) -> str:
    """Formatted for appending directly to an LLM prompt."""
    if angle["name"] == "none":
        return (
            "\n\nNo spoken CTA in this script this time -- end the "
            "narration on its own content, no subscribe/comment/save/"
            "share mention. Not every video needs one.\n"
        )

    hint = _TEMPLATE_HINTS.get(template, {}).get(angle["name"])
    block = (
        "\n\nSPOKEN CTA FOR THIS VIDEO (fold this into the script text "
        "itself, not just a visual overlay — it counts toward the "
        "existing word budget, don't add extra length for it):\n"
        f"- {angle['instruction']}\n"
    )
    if hint:
        block += f"- For this template, that might mean something like {hint}\n"
    block += (
        "- Exactly ONE ask, one sentence at most -- never stack multiple "
        "asks (comment AND subscribe AND share) into the same script.\n"
        "- Place it near the end, after the video's real payoff/"
        "conclusion has already landed -- never during the hook, a mid-"
        "explanation, or a reveal itself. It should read as the natural "
        "next thought after the content, not an interruption.\n"
        "- Keep it low-key -- never urgency language like \"subscribe "
        "now!!\", that reads as manipulative rather than authentic.\n"
        "- Always say \"subscribe\", never \"follow\" — this is YouTube, "
        "not Instagram/TikTok, and \"follow\" reads as a platform "
        "mismatch to anyone who notices.\n"
        "- This line follows the exact same authenticity bar as the rest "
        "of the script (see the channel persona above) — it is not "
        "exempt. No generic filler, and it must NOT work if pasted onto "
        "an unrelated video -- it has to be specific to what THIS video "
        "actually covered.\n"
    )
    if milestone_line:
        block += f"- Real milestone to mention: {milestone_line}\n"
    return block
