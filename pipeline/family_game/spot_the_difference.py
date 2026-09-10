"""Family Game Night's procedural game type (FAMILY_GAME_NIGHT_SPEC.md
section 30 Phase 4 -- "This is important because it demonstrates
deterministic game generation... The answer must come from deterministic
scene state, not LLM memory."). Fully algorithmic, zero LLM calls --
adapted from pipeline/games/what_changed.py's scene-template mechanic
(mutate one attribute of a small scene; the answer is a plain fact about
the generated data, never something an LLM has to remember correctly),
reshaped into the real two-phase flow section 30's Game Type D actually
describes: show scene 1, give real time to study it, show scene 2 (one
attribute changed), give real time to compare it against memory, then
reveal.

This is NOT the same shape as the blocked Shorts track's own
what_changed.py renderer, which showed both scenes as one side-by-side
table the whole time (and had to hide the changed cell as "?" to keep
any real challenge, since a static two-column table makes the diff
visible at a glance). Showing one scene at a time and asking the viewer
to hold it in memory is a real different game, and it's what the spec
actually asks for -- the two-column table is used here only at the
reveal, where seeing both together is exactly the right way to explain
the answer.
"""

from __future__ import annotations

import random

from pipeline.family_game.base import (
    HOST_TIME,
    PLAYER_TIME,
    estimate_thinking_time,
    make_round,
    make_segment,
    validate_round,
)

GAME_TYPE = "spot_the_difference"

SCENE_TEMPLATES = (
    {
        "subject": "a fruit stand",
        "attributes": {
            "apple count": (3, 5, 7),
            "banana count": (2, 4, 6),
            "awning color": ("blue", "red", "green", "yellow"),
            "sign text": ("FRESH", "SALE", "OPEN"),
        },
    },
    {
        "subject": "a desk setup",
        "attributes": {
            "monitor count": (1, 2, 3),
            "mug color": ("white", "black", "red"),
            "plant present": ("yes", "no"),
            "chair color": ("black", "gray", "blue"),
        },
    },
    {
        "subject": "a street corner",
        "attributes": {
            "car count": (1, 2, 3),
            "traffic light": ("red", "yellow", "green"),
            "umbrella present": ("yes", "no"),
            "sign count": (1, 2, 3),
        },
    },
)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    available = [t for t in SCENE_TEMPLATES if t["subject"] not in avoid_topics] or list(SCENE_TEMPLATES)
    template = random.choice(available)
    attribute_names = list(template["attributes"])
    item_count = len(attribute_names)

    before = {name: random.choice(values) for name, values in template["attributes"].items()}
    changed_attr = random.choice(attribute_names)
    other_values = [v for v in template["attributes"][changed_attr] if v != before[changed_attr]]
    after = dict(before)
    after[changed_attr] = random.choice(other_values)

    subject = template["subject"]
    presentation_data = {"subject": subject, "before": before}
    reveal_data = {"subject": subject, "before": before, "after": after, "changed_attribute": changed_attr}

    # Two distinct real time budgets for two distinct real cognitive
    # tasks, per section 8's "different game types should define their
    # own timing": studying scene 1 is the same "observe, then recall"
    # task as Memory Challenge, so it reuses that category; comparing
    # scene 2 against memory is this game's own named category.
    study_time = estimate_thinking_time("memory_challenge", item_count=item_count, difficulty=difficulty)
    compare_time = estimate_thinking_time("spot_the_difference", item_count=item_count, difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title=subject,
        instructions=f"Spot the one thing that changed about {subject}.",
        presentation_data=presentation_data,
        answer=changed_attr,
        explanation=f"{changed_attr}: {before[changed_attr]} became {after[changed_attr]}.",
        thinking_time=study_time + compare_time,
        reveal_data=reveal_data,
    )

    before_view = {"subject": subject, "scene": before, "phase": "before"}
    after_view = {"subject": subject, "scene": after, "phase": "after"}

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", "What Changed round -- take a good look, you'll only see it once before it changes."),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", f"Here's {subject}. Take a close look.", round_data=before_view),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=study_time, round_data=before_view),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "transition", "Okay -- here's the new version. What changed?", round_data=after_view),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=compare_time, round_data=after_view),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "countdown", "", duration_seconds=3.0),
        make_segment(
            GAME_TYPE, round_index, HOST_TIME, "reveal",
            f"It was the {changed_attr} -- {before[changed_attr]} became {after[changed_attr]}.",
            round_data=reveal_data,
        ),
    ]

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.spot_the_difference produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']} -- answer: {r['answer']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
