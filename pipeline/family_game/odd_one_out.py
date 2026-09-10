"""Family Game Night's "What Doesn't Belong?" (FAMILY_GAME_NIGHT_SPEC.md
Game Type C). Fully algorithmic, zero LLM calls -- a curated static pool
of {items, odd_one, category_label, explanation}, same pattern as
spot_the_difference.py/memory_challenge.py. The spec's own real concern
for this type ("the generator must avoid ambiguous cases... there must
be a clear intended answer") is exactly the risk a curated, hand-checked
pool sidesteps entirely -- there's no live judgment call about whether a
generated grouping is genuinely unambiguous, because every entry here
already was one.
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

GAME_TYPE = "odd_one_out"

ROUND_POOL = (
    {
        "items": ("Dog", "Cat", "Horse", "Car"),
        "odd_one": "Car",
        "category_label": "animals",
        "explanation": "Dog, Cat, and Horse are all animals -- Car is a machine.",
    },
    {
        "items": ("Mercury", "Venus", "Earth", "Moon"),
        "odd_one": "Moon",
        "category_label": "planets",
        "explanation": "Mercury, Venus, and Earth are planets -- the Moon is a natural satellite, not a planet.",
    },
    {
        "items": ("Guitar", "Violin", "Piano", "Drum"),
        "odd_one": "Piano",
        "category_label": "string instruments",
        "explanation": "Guitar, Violin, and Drum can all be played standing and carried around -- a Piano can't.",
    },
    {
        "items": ("Salmon", "Trout", "Dolphin", "Tuna"),
        "odd_one": "Dolphin",
        "category_label": "fish",
        "explanation": "Salmon, Trout, and Tuna are fish -- a Dolphin is a mammal.",
    },
    {
        "items": ("Spider", "Ant", "Bee", "Butterfly"),
        "odd_one": "Spider",
        "category_label": "insects",
        "explanation": "Ant, Bee, and Butterfly are insects (six legs) -- a Spider is an arachnid (eight legs).",
    },
    {
        "items": ("Football", "Basketball", "Tennis", "Chess"),
        "odd_one": "Chess",
        "category_label": "sports with a ball",
        "explanation": "Football, Basketball, and Tennis are all played with a ball -- Chess isn't.",
    },
)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    available = [r for r in ROUND_POOL if r["category_label"] not in avoid_topics] or list(ROUND_POOL)
    picked = random.choice(available)
    items, odd_one, category_label, explanation = (
        picked["items"], picked["odd_one"], picked["category_label"], picked["explanation"],
    )

    presentation_data = {"items": items, "phase": "question"}
    reveal_data = {"items": items, "odd_one": odd_one, "phase": "reveal"}

    # Grouping-by-category is the same cognitive task as Guess the
    # Connection, just inverted (find the outlier instead of the shared
    # thread) -- reusing the "connection" timing category rather than
    # inventing a near-duplicate one.
    think_time = estimate_thinking_time("connection", item_count=len(items), difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title=category_label,
        instructions="Find the one item that doesn't belong with the other three.",
        presentation_data=presentation_data,
        answer=odd_one,
        explanation=explanation,
        thinking_time=think_time,
        reveal_data=reveal_data,
    )

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", "What Doesn't Belong round -- one of these isn't like the others."),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", "Take a look -- which one doesn't belong?", round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=think_time, round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "countdown", "", duration_seconds=3.0),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "reveal", f"It's {odd_one} -- {explanation}", round_data=reveal_data),
    ]

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.odd_one_out produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']} -- answer: {r['answer']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
