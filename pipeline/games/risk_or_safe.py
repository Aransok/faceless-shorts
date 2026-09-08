"""Risk or Safe round: fully algorithmic, no LLM content and no
verification needed -- this module's "claim" is its own stated odds,
which the code both states AND resolves, so there's nothing external to
fact-check. Presents two real options with real stated odds, then
reveals which outcome a real weighted draw actually produced -- the
draw uses the SAME probability the narration states, so the resolution
is never dressed up to match a script. No win/loss judgment of a
simulated "player": this just shows a real random event playing out, the
same way a dice roll or wheel spin would. See base.py for the shared
beat contract.
"""

from __future__ import annotations

import random

from pipeline.games.base import make_beat

ROUND_TYPE = "risk_or_safe"

# (safe_points, risk_win_probability, risk_win_points) -- "points" here
# are flavor text for the stakes shown on screen, not a tracked score.
RISK_PROFILES = (
    {"safe_points": 10, "risk_win_probability": 0.5, "risk_win_points": 25},
    {"safe_points": 10, "risk_win_probability": 0.35, "risk_win_points": 35},
    {"safe_points": 15, "risk_win_probability": 0.65, "risk_win_points": 25},
)


def generate_round(avoid_topics: list[str], round_index: int) -> list[dict]:
    profile = random.choice(RISK_PROFILES)
    # The RNG draw IS the stated probability -- not a separate number
    # dressed up to match the narration.
    risk_hits = random.random() < profile["risk_win_probability"]
    win_pct = round(profile["risk_win_probability"] * 100)

    round_data = {
        "safe_points": profile["safe_points"],
        "risk_win_probability": profile["risk_win_probability"],
        "risk_win_points": profile["risk_win_points"],
        "risk_hits": risk_hits,
    }

    return [
        make_beat(ROUND_TYPE, round_index, "intro", "Risk or Safe round. Two ways this could go."),
        make_beat(
            ROUND_TYPE, round_index, "rule",
            f"Safe is a guaranteed {profile['safe_points']} points. "
            f"Risky is a {win_pct}% shot at {profile['risk_win_points']} -- and a real chance of nothing.",
            round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "countdown", "Here's the odds."),
        make_beat(
            ROUND_TYPE, round_index, "gameplay",
            f"A {win_pct}% chance at {profile['risk_win_points']} points, versus a safe {profile['safe_points']}.",
            round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's see how it lands..."),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            f"The {win_pct}% shot {'hits' if risk_hits else 'misses'} this time.",
            round_data,
        ),
    ]
