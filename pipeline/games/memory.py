"""Memory round: fully algorithmic, no LLM content at all. A sequence of
icons is shown, then the viewer is asked whether a specific icon was in
it. Difficulty (and thus real pass/fail odds) is driven by the actual
generated sequence length -- longer sequence, harder recall, lower real
pass probability. See base.py for the shared session/beat contract.
"""

from __future__ import annotations

import random

from pipeline.games.base import GameSession, make_beat

ROUND_TYPE = "memory"

# Named, narratable icon pool -- kept small and concrete so narration
# lines ("watch for the rocket") read naturally, not like a raw enum.
ICON_POOL = (
    "rocket", "star", "heart", "lightning bolt", "fire", "diamond",
    "skull", "crown", "moon", "sun", "snowflake", "leaf",
)

SEQUENCE_LENGTH_CHOICES = (4, 5, 6, 7)
POINTS_BY_LENGTH = {4: 10, 5: 15, 6: 20, 7: 25}

# Longer sequence => lower pass probability -- a real, stated relationship
# between generated difficulty and outcome, not an arbitrary coinflip.
_PASS_PROBABILITY_BY_LENGTH = {4: 0.75, 5: 0.65, 6: 0.5, 7: 0.35}


def generate_round(session: GameSession, avoid_topics: list[str], round_index: int) -> tuple[list[dict], GameSession]:
    length = random.choice(SEQUENCE_LENGTH_CHOICES)
    sequence = random.sample(ICON_POOL, length)

    # The recall challenge: either a real member of the sequence (asked as
    # "was X in it" -> yes) or a real non-member (-> no), decided for real
    # before the pass/fail roll so the reveal beat can state the correct
    # answer honestly regardless of whether the roll passes or fails.
    asks_present = random.random() < 0.5
    if asks_present:
        target = random.choice(sequence)
        correct_answer = "yes"
    else:
        target = random.choice([icon for icon in ICON_POOL if icon not in sequence])
        correct_answer = "no"

    passed = random.random() < _PASS_PROBABILITY_BY_LENGTH[length]
    points_delta = POINTS_BY_LENGTH[length]

    round_data = {
        "sequence": sequence,
        "target": target,
        "correct_answer": correct_answer,
        "passed": passed,
    }

    beats = [
        make_beat(ROUND_TYPE, round_index, "intro", "Memory round. Watch closely.", session),
        make_beat(
            ROUND_TYPE, round_index, "rule",
            f"You'll see {length} icons flash by. Remember them.",
            session, round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "countdown", "Here they come.", session),
        make_beat(
            ROUND_TYPE, round_index, "gameplay",
            f"Was the {target} one of them?",
            session, round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's check...", session),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            f"The answer is {correct_answer}. " + ("Nailed it." if passed else "Missed that one."),
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
