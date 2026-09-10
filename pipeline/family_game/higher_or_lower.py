"""Family Game Night's first vertical slice (FAMILY_GAME_NIGHT_SPEC.md
section 30, Phase 3 -- "start with one relatively straightforward game,
recommended: Higher or Lower"). Mirrors the shape of
pipeline/games/higher_or_lower.py (the blocked Shorts track's own
Higher/Lower module): LLM proposes a real numeric comparison,
verify_claim() confirms it independently before it can ship, and once
verified, higher/lower is a plain numeric comparison in code -- the LLM
never decides the answer. What's different here is the timeline: this
produces the new HOST_TIME/PLAYER_TIME segment sequence
(pipeline/family_game/base.py), with a real, narration-independent
PLAYER_TIME gap between the question and the reveal, instead of a
narration-duration-driven beat sequence.
"""

from __future__ import annotations

import re
from pathlib import Path

from pipeline.family_game.base import (
    HOST_TIME,
    PLAYER_TIME,
    estimate_thinking_time,
    host_persona_guidance_block,
    make_round,
    make_segment,
    validate_round,
    verify_claim,
)
from pipeline.games.base import RoundVerificationFailed, VERIFY_MAX_ATTEMPTS
from pipeline.plan import call_llm

GAME_TYPE = "higher_or_lower"
THINKING_CATEGORY = "simple_question"  # two items, one known value -- section 8's simplest bucket
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "family_game_higher_or_lower.txt"

_FIELD_NAMES = (
    "CATEGORY", "ITEM_A_NAME", "ITEM_A_VALUE", "ITEM_B_NAME", "ITEM_B_VALUE", "UNIT",
    "INTRO_SCRIPT", "PROMPT_SCRIPT", "REVEAL_SCRIPT",
)
_FIELD_PATTERN = re.compile(
    r"(?P<label>{names}):\s*(?P<value>.*?)(?=\n(?:{names}):|\Z)".format(names="|".join(_FIELD_NAMES)),
    re.DOTALL,
)


def _parse_response(text: str) -> dict:
    text = text.strip()
    fields = {m.group("label"): m.group("value").strip() for m in _FIELD_PATTERN.finditer(text)}
    missing = set(_FIELD_NAMES) - set(fields)
    if missing:
        raise ValueError(f"LLM output missing required field(s) {sorted(missing)}:\n{text}")

    try:
        item_a_value = float(fields["ITEM_A_VALUE"])
        item_b_value = float(fields["ITEM_B_VALUE"])
    except ValueError as exc:
        raise ValueError(f"ITEM_A_VALUE/ITEM_B_VALUE must be plain numbers:\n{text}") from exc

    return {**fields, "item_a_value": item_a_value, "item_b_value": item_b_value}


def _generate_content(avoid_topics: list[str]) -> dict:
    prompt_body = PROMPT_PATH.read_text(encoding="utf-8")
    prompt = prompt_body.replace("{avoid_topics}", ", ".join(avoid_topics) if avoid_topics else "(none yet)")
    prompt += host_persona_guidance_block()
    raw = call_llm(prompt)
    return _parse_response(raw)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    """Returns (round, segments) -- round via make_round(), segments via
    make_segment(), both from pipeline/family_game/base.py. Raises
    RoundVerificationFailed (same exception pipeline/games/base.py's
    higher_or_lower.py raises, reused rather than a parallel type) if no
    candidate clears verify_claim() within VERIFY_MAX_ATTEMPTS -- a
    caller building an episode should catch this and either substitute a
    different round or skip the slot, not let it crash the whole run.
    """
    content = None
    for attempt in range(1, VERIFY_MAX_ATTEMPTS + 1):
        candidate = _generate_content(avoid_topics)
        claim = (
            f"{candidate['ITEM_A_NAME']} is approximately {candidate['item_a_value']} {candidate['UNIT']}, "
            f"and {candidate['ITEM_B_NAME']} is approximately {candidate['item_b_value']} {candidate['UNIT']}."
        )
        result = verify_claim(claim)
        if result["verdict"] == "CONFIRMED":
            content = candidate
            break
        print(
            f"[family_game.higher_or_lower] verify attempt {attempt}/{VERIFY_MAX_ATTEMPTS} "
            f"REJECTED: {claim!r} -- {result.get('raw', '')[:200]}"
        )
    if content is None:
        raise RoundVerificationFailed(
            f"family_game.higher_or_lower: no verified content after {VERIFY_MAX_ATTEMPTS} attempts"
        )

    item_a_value, item_b_value = content["item_a_value"], content["item_b_value"]
    correct_answer = "higher" if item_b_value > item_a_value else "lower"

    presentation_data = {
        "category": content["CATEGORY"],
        "item_a_name": content["ITEM_A_NAME"],
        "item_a_value": item_a_value,
        "item_b_name": content["ITEM_B_NAME"],
        "unit": content["UNIT"],
    }
    reveal_data = {
        **presentation_data,
        "item_b_value": item_b_value,
        "correct_answer": correct_answer,
    }

    thinking_time = estimate_thinking_time(THINKING_CATEGORY, item_count=2, difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title=content["CATEGORY"],
        instructions=f"Is {content['ITEM_B_NAME']} higher or lower than {content['ITEM_A_NAME']}?",
        presentation_data=presentation_data,
        answer=correct_answer,
        explanation=content["REVEAL_SCRIPT"],
        thinking_time=thinking_time,
        reveal_data=reveal_data,
    )

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", content["INTRO_SCRIPT"]),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", content["PROMPT_SCRIPT"], round_data=presentation_data),
        # presentation_data only, never reveal_data -- the point is that
        # item B's real value/correct_answer never enter a PLAYER_TIME
        # segment's data at all, not just that the renderer happens not
        # to draw them. This is what lets the renderer show the same
        # "unrevealed" versus card during player time (section 9's
        # "the answer must not accidentally appear during this stage").
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=thinking_time, round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "countdown", "", duration_seconds=3.0),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "reveal", content["REVEAL_SCRIPT"], round_data=reveal_data),
    ]

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.higher_or_lower produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']} -- answer: {r['answer']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
