"""Family Game Night's "Guess the Connection" (FAMILY_GAME_NIGHT_SPEC.md
Game Type B). Fully algorithmic, zero LLM calls -- a curated static pool
of {clues, connection, explanation}, same pattern as odd_one_out.py.
The spec's own validation worry for this type ("the connection must not
be vague enough that multiple unrelated answers are equally plausible")
is exactly what a curated, hand-checked pool sidesteps -- every entry
here was picked because the connection is real and clear, not generated
and then hoped to be valid.
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

GAME_TYPE = "guess_the_connection"

ROUND_POOL = (
    {
        "clues": ("Apple", "Amazon", "Orange", "BlackBerry"),
        "connection": "Tech companies named after fruit",
        "explanation": "Apple, Amazon (originally), Orange, and BlackBerry are all tech/telecom brands sharing a fruit name.",
    },
    {
        "clues": ("Mercury", "Pluto", "Mars", "Venus"),
        "connection": "Roman gods",
        "explanation": "Mercury, Pluto, Mars, and Venus are all named after Roman gods, not just planets.",
    },
    {
        "clues": ("Paris", "Athens", "Los Angeles", "Tokyo"),
        "connection": "Summer Olympics host cities",
        "explanation": "Paris, Athens, Los Angeles, and Tokyo have all hosted the Summer Olympics.",
    },
    {
        "clues": ("Egypt", "Peru", "Mexico", "Sudan"),
        "connection": "Countries with pyramids",
        "explanation": "Egypt, Peru, Mexico, and Sudan all have real ancient pyramids within their borders.",
    },
    {
        "clues": ("Penguin", "Ostrich", "Kiwi", "Emu"),
        "connection": "Flightless birds",
        "explanation": "Penguin, Ostrich, Kiwi, and Emu are all real flightless bird species.",
    },
)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    available = [r for r in ROUND_POOL if r["connection"] not in avoid_topics] or list(ROUND_POOL)
    picked = random.choice(available)
    clues, connection, explanation = picked["clues"], picked["connection"], picked["explanation"]

    presentation_data = {"clues": clues, "phase": "question"}
    reveal_data = {"clues": clues, "connection": connection, "phase": "reveal"}

    think_time = estimate_thinking_time("connection", item_count=len(clues), difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title=connection,
        instructions="Figure out what connects these clues.",
        presentation_data=presentation_data,
        answer=connection,
        explanation=explanation,
        thinking_time=think_time,
        reveal_data=reveal_data,
    )

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", "Guess the Connection round -- what links these four?"),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", "Here are your four clues. What's the connection?", round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=think_time, round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "countdown", "", duration_seconds=3.0),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "reveal", f"It's {connection} -- {explanation}", round_data=reveal_data),
    ]

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.guess_the_connection produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']} -- answer: {r['answer']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
