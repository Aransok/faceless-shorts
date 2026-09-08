"""Prediction round: LLM proposes a real stat plus a nearby threshold,
verify_claim() confirms the real value independently before it ships.
Above/below the threshold is a plain numeric comparison in code, and the
"contestant" guess is a real weighted-random draw seeded by how close the
actual value is to the threshold (closer = harder call = lower real pass
odds). Shares verify_claim() with higher_or_lower.py -- see base.py.
"""

from __future__ import annotations

import random
import re
from pathlib import Path

from pipeline.games.base import GameSession, RoundVerificationFailed, VERIFY_MAX_ATTEMPTS, make_beat, verify_claim
from pipeline.persona import persona_guidance_block
from pipeline.plan import call_llm

ROUND_TYPE = "prediction"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "game_prediction.txt"

POINTS = 20

_FIELD_NAMES = (
    "SUBJECT_NAME", "ACTUAL_VALUE", "THRESHOLD_VALUE", "UNIT",
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
        actual_value = float(fields["ACTUAL_VALUE"])
        threshold_value = float(fields["THRESHOLD_VALUE"])
    except ValueError as exc:
        raise ValueError(f"ACTUAL_VALUE/THRESHOLD_VALUE must be plain numbers:\n{text}") from exc

    return {**fields, "actual_value": actual_value, "threshold_value": threshold_value}


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
        claim = f"{candidate['SUBJECT_NAME']} is approximately {candidate['actual_value']} {candidate['UNIT']}."
        result = verify_claim(claim)
        if result["verdict"] == "CONFIRMED":
            content = candidate
            break
        print(f"[prediction] verify attempt {attempt}/{VERIFY_MAX_ATTEMPTS} REJECTED: {claim!r} -- {result.get('raw', '')[:200]}")
    if content is None:
        raise RoundVerificationFailed(f"prediction: no verified content after {VERIFY_MAX_ATTEMPTS} attempts")

    actual_value, threshold_value = content["actual_value"], content["threshold_value"]
    correct_answer = "above" if actual_value > threshold_value else "below"

    spread = abs(actual_value - threshold_value) / max(abs(actual_value), abs(threshold_value), 1e-9)
    pass_probability = min(0.85, max(0.3, spread))
    passed = random.random() < pass_probability

    round_data = {
        "subject_name": content["SUBJECT_NAME"],
        "actual_value": actual_value,
        "threshold_value": threshold_value,
        "unit": content["UNIT"],
        "correct_answer": correct_answer,
        "passed": passed,
    }

    beats = [
        make_beat(ROUND_TYPE, round_index, "intro", content["INTRO_SCRIPT"], session),
        make_beat(ROUND_TYPE, round_index, "rule", content["RULE_SCRIPT"], session, round_data),
        make_beat(ROUND_TYPE, round_index, "countdown", "Above, or below?", session),
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
