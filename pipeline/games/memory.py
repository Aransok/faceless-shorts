"""Memory round: fully algorithmic, no LLM content at all. A sequence of
icons is shown, then the viewer is asked whether a specific icon was in
it -- the reveal states the real, deterministic answer (was it actually
in the generated sequence, yes or no). No simulated win/loss: this only
presents the challenge and reveals the truth. See base.py for the shared
beat contract.
"""

from __future__ import annotations

import random

from pipeline.games.base import make_beat

ROUND_TYPE = "memory"

# Named, narratable icon pool -- kept small and concrete so narration
# lines ("watch for the rocket") read naturally, not like a raw enum.
ICON_POOL = (
    "rocket", "star", "heart", "lightning bolt", "fire", "diamond",
    "skull", "crown", "moon", "sun", "snowflake", "leaf",
)

SEQUENCE_LENGTH_CHOICES = (4, 5, 6, 7)


def generate_round(avoid_topics: list[str], round_index: int) -> list[dict]:
    length = random.choice(SEQUENCE_LENGTH_CHOICES)
    sequence = random.sample(ICON_POOL, length)

    # The recall challenge: either a real member of the sequence (asked as
    # "was X in it" -> yes) or a real non-member (-> no) -- decided for
    # real from the actual generated sequence, not simulated.
    asks_present = random.random() < 0.5
    if asks_present:
        target = random.choice(sequence)
        correct_answer = "yes"
    else:
        target = random.choice([icon for icon in ICON_POOL if icon not in sequence])
        correct_answer = "no"

    round_data = {"sequence": sequence, "target": target, "correct_answer": correct_answer}

    return [
        make_beat(ROUND_TYPE, round_index, "intro", "Memory round. Watch closely.", None),
        make_beat(
            ROUND_TYPE, round_index, "rule",
            f"You'll see {length} icons flash by. Remember them.",
            round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "countdown", "Here they come.", None),
        make_beat(
            ROUND_TYPE, round_index, "gameplay",
            f"Was the {target} one of them?",
            round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's check...", None),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            f"The answer is {correct_answer}.",
            round_data,
        ),
    ]
