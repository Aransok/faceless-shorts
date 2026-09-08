"""Higher or Lower round: LLM proposes a real numeric comparison pair,
verify_claim() confirms it independently before it's allowed to ship.
The LLM never decides who's "right" -- once the pair is verified, the
higher/lower answer is a plain numeric comparison in code, and the
"contestant" guess is a real weighted-random draw seeded by how close the
two values are (closer values = harder call = lower real pass odds).
See base.py for the shared session/beat contract and verify_claim().
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from pipeline.games.base import GameSession, RoundVerificationFailed, VERIFY_MAX_ATTEMPTS, make_beat, verify_claim
from pipeline.persona import persona_guidance_block
from pipeline.plan import call_llm

ROUND_TYPE = "higher_or_lower"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "game_higher_or_lower.txt"

POINTS = 20

_FIELD_NAMES = (
    "CATEGORY", "ITEM_A_NAME", "ITEM_A_VALUE", "ITEM_B_NAME", "ITEM_B_VALUE", "UNIT",
    "INTRO_SCRIPT", "RULE_SCRIPT", "GAMEPLAY_SCRIPT", "REVEAL_SCRIPT",
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
    prompt += persona_guidance_block("game_night")
    raw = call_llm(prompt)
    return _parse_response(raw)


def generate_round(session: GameSession, avoid_topics: list[str], round_index: int) -> tuple[list[dict], GameSession]:
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
        print(f"[higher_or_lower] verify attempt {attempt}/{VERIFY_MAX_ATTEMPTS} REJECTED: {claim!r} -- {result.get('raw', '')[:200]}")
    if content is None:
        raise RoundVerificationFailed(f"higher_or_lower: no verified content after {VERIFY_MAX_ATTEMPTS} attempts")

    item_a_value, item_b_value = content["item_a_value"], content["item_b_value"]
    correct_answer = "higher" if item_b_value > item_a_value else "lower"

    # Real difficulty from the real values -- closer together (relative to
    # the larger of the two) is a harder call, so lower pass odds.
    spread = abs(item_b_value - item_a_value) / max(abs(item_a_value), abs(item_b_value), 1e-9)
    pass_probability = min(0.85, max(0.3, spread))
    passed = random.random() < pass_probability

    round_data = {
        "category": content["CATEGORY"],
        "item_a_name": content["ITEM_A_NAME"],
        "item_a_value": item_a_value,
        "item_b_name": content["ITEM_B_NAME"],
        "item_b_value": item_b_value,
        "unit": content["UNIT"],
        "correct_answer": correct_answer,
        "passed": passed,
    }

    beats = [
        make_beat(ROUND_TYPE, round_index, "intro", content["INTRO_SCRIPT"], session),
        make_beat(ROUND_TYPE, round_index, "rule", content["RULE_SCRIPT"], session, round_data),
        make_beat(ROUND_TYPE, round_index, "countdown", "Higher, or lower?", session),
        make_beat(ROUND_TYPE, round_index, "gameplay", content["GAMEPLAY_SCRIPT"], session, round_data),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's find out...", session),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            content["REVEAL_SCRIPT"] + (" Correct call." if passed else " Wrong call."),
            session, round_data,
        ),
    ]

    session.apply_round_result(passed, POINTS)
    session.round_types_used.append(ROUND_TYPE)
    beats.append(
        make_beat(
            ROUND_TYPE, round_index, "score",
            f"{'+' + str(POINTS) + ' points' if passed else 'Lost a life'}.",
            session, round_data,
        )
    )
    return beats, session
