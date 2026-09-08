"""What Changed round: fully algorithmic, no LLM content. A scene is
defined as a small set of attributes; exactly one attribute is mutated
for the "after" version. Difficulty (and real pass odds) is driven by
the actual total attribute count -- more attributes to scan, harder to
spot the one that moved. See base.py for the shared session/beat
contract.
"""

from __future__ import annotations

import random

from pipeline.games.base import GameSession, make_beat

ROUND_TYPE = "what_changed"

# Each scene template names its attributes and each attribute's possible
# values -- narratable ("the awning went from blue to red"), not raw enum
# diffs.
SCENE_TEMPLATES = (
    {
        "subject": "a fruit stand",
        "attributes": {
            "apple_count": (3, 5, 7),
            "banana_count": (2, 4, 6),
            "awning_color": ("blue", "red", "green", "yellow"),
            "sign_text": ("FRESH", "SALE", "OPEN"),
        },
    },
    {
        "subject": "a desk setup",
        "attributes": {
            "monitor_count": (1, 2, 3),
            "mug_color": ("white", "black", "red"),
            "plant_present": ("yes", "no"),
            "chair_color": ("black", "gray", "blue"),
        },
    },
    {
        "subject": "a street corner",
        "attributes": {
            "car_count": (1, 2, 3),
            "traffic_light": ("red", "yellow", "green"),
            "umbrella_present": ("yes", "no"),
            "sign_count": (1, 2, 3),
        },
    },
)

_ATTRIBUTE_COUNT_CHOICES = (4,)  # every template above has 4 -- kept explicit for the difficulty table below
POINTS_BY_ATTRIBUTE_COUNT = {4: 15}
_PASS_PROBABILITY_BY_ATTRIBUTE_COUNT = {4: 0.55}


def _label(attr_name: str) -> str:
    return attr_name.replace("_", " ")


def generate_round(session: GameSession, avoid_topics: list[str], round_index: int) -> tuple[list[dict], GameSession]:
    template = random.choice(SCENE_TEMPLATES)
    attribute_names = list(template["attributes"])
    attribute_count = len(attribute_names)

    before = {name: random.choice(values) for name, values in template["attributes"].items()}
    changed_attr = random.choice(attribute_names)
    other_values = [v for v in template["attributes"][changed_attr] if v != before[changed_attr]]
    after = dict(before)
    after[changed_attr] = random.choice(other_values)

    passed = random.random() < _PASS_PROBABILITY_BY_ATTRIBUTE_COUNT[attribute_count]
    points_delta = POINTS_BY_ATTRIBUTE_COUNT[attribute_count]

    round_data = {
        "subject": template["subject"],
        "before": before,
        "after": after,
        "changed_attribute": changed_attr,
        "passed": passed,
    }

    beats = [
        make_beat(ROUND_TYPE, round_index, "intro", "What Changed round. Two scenes, one difference.", session),
        make_beat(
            ROUND_TYPE, round_index, "rule",
            f"Here's {template['subject']}. Look carefully.",
            session, round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "countdown", "Study it...", session),
        make_beat(
            ROUND_TYPE, round_index, "gameplay",
            "Now here's the second version. What changed?",
            session, round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's compare...", session),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            f"It was the {_label(changed_attr)} -- {before[changed_attr]} became {after[changed_attr]}. "
            + ("Spotted it." if passed else "Missed that one."),
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
