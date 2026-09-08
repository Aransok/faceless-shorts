"""Risk or Safe round: fully algorithmic, no LLM content and no
verification needed -- unlike higher_or_lower/prediction, this module's
"claim" is its own stated odds, which the code both states AND resolves,
so there's nothing external to fact-check. The one thing that matters is
that the resolution RNG actually matches the odds the narration states --
enforced here by drawing the risk outcome from the same probability the
script text names, not a separate number. See base.py for the shared
session/beat contract.
"""

from __future__ import annotations

import random

from pipeline.games.base import GameSession, make_beat

ROUND_TYPE = "risk_or_safe"

# (safe_points, risk_win_probability, risk_win_points, risk_loss_costs_life)
RISK_PROFILES = (
    {"safe_points": 10, "risk_win_probability": 0.5, "risk_win_points": 25},
    {"safe_points": 10, "risk_win_probability": 0.35, "risk_win_points": 35},
    {"safe_points": 15, "risk_win_probability": 0.65, "risk_win_points": 25},
)


def generate_round(session: GameSession, avoid_topics: list[str], round_index: int) -> tuple[list[dict], GameSession]:
    profile = random.choice(RISK_PROFILES)
    took_risk = random.random() < 0.5  # the "contestant"'s real choice, decided once, honestly

    if took_risk:
        # The RNG draw IS the stated probability -- not a separate number
        # dressed up to match the narration.
        won_risk = random.random() < profile["risk_win_probability"]
        passed = won_risk
        points_delta = profile["risk_win_points"] if won_risk else 0
    else:
        passed = True  # safe choice always "passes" -- guaranteed points, no life risk
        points_delta = profile["safe_points"]

    win_pct = round(profile["risk_win_probability"] * 100)
    round_data = {
        "safe_points": profile["safe_points"],
        "risk_win_probability": profile["risk_win_probability"],
        "risk_win_points": profile["risk_win_points"],
        "took_risk": took_risk,
        "passed": passed,
    }

    beats = [
        make_beat(ROUND_TYPE, round_index, "intro", "Risk or Safe round. Play it safe, or go for it.", session),
        make_beat(
            ROUND_TYPE, round_index, "rule",
            f"Safe is a guaranteed {profile['safe_points']} points. "
            f"Risky is a {win_pct}% shot at {profile['risk_win_points']} -- "
            f"miss it and you lose a life.",
            session, round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "countdown", "Decision time.", session),
        make_beat(
            ROUND_TYPE, round_index, "gameplay",
            f"Going {'risky' if took_risk else 'safe'} this time.",
            session, round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's see how it lands..." if took_risk else "Locking it in...", session),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            (
                f"{'It hits!' if passed else 'It misses.'}"
                if took_risk
                else "Safe points, banked."
            ),
            session, round_data,
        ),
    ]

    session.apply_round_result(passed, points_delta)
    session.round_types_used.append(ROUND_TYPE)
    beats.append(
        make_beat(
            ROUND_TYPE, round_index, "score",
            f"{'+' + str(points_delta) + ' points' if passed else 'Lost a life'}.",
            session, round_data,
        )
    )
    return beats, session
