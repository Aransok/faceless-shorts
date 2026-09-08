"""What Changed round: fully algorithmic, no LLM content. A scene is
defined as a small set of attributes; exactly one attribute is mutated
for the "after" version. The reveal states which attribute actually
changed -- no simulated win/loss, just the real answer. See base.py for
the shared beat contract.
"""

from __future__ import annotations

import random

from pipeline.games.base import make_beat

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


def _label(attr_name: str) -> str:
    return attr_name.replace("_", " ")


def generate_round(avoid_topics: list[str], round_index: int) -> list[dict]:
    template = random.choice(SCENE_TEMPLATES)
    attribute_names = list(template["attributes"])

    before = {name: random.choice(values) for name, values in template["attributes"].items()}
    changed_attr = random.choice(attribute_names)
    other_values = [v for v in template["attributes"][changed_attr] if v != before[changed_attr]]
    after = dict(before)
    after[changed_attr] = random.choice(other_values)

    round_data = {
        "subject": template["subject"], "before": before, "after": after, "changed_attribute": changed_attr,
    }

    return [
        make_beat(ROUND_TYPE, round_index, "intro", "What Changed round. Two scenes, one difference."),
        make_beat(
            ROUND_TYPE, round_index, "rule",
            f"Here's {template['subject']}. Look carefully.",
            round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "countdown", "Study it..."),
        make_beat(
            ROUND_TYPE, round_index, "gameplay",
            "Now here's the second version. What changed?",
            round_data,
        ),
        make_beat(ROUND_TYPE, round_index, "suspense", "Let's compare..."),
        make_beat(
            ROUND_TYPE, round_index, "reveal",
            f"It was the {_label(changed_attr)} -- {before[changed_attr]} became {after[changed_attr]}.",
            round_data,
        ),
    ]
