"""Family Game Night's Memory Challenge (FAMILY_GAME_NIGHT_SPEC.md
section 30 Phase 5). Fully algorithmic, zero LLM calls -- adapted from
pipeline/games/memory.py's icon-sequence mechanic (show a sequence, ask
whether a specific icon was really in it, decided for real from the
generated sequence, never simulated), reshaped into a genuine two-phase
recall challenge instead of that module's single narration-driven
beat list: memorize the sequence while it's visible (real player time),
then decide from memory once it's hidden and only the question remains
on screen (a second, real player-time decision window) -- the actual
memory test the game type's name promises, not "look at the sequence and
the question at the same time."
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

GAME_TYPE = "memory_challenge"

# Named, narratable icon pool -- kept small and concrete so narration
# lines ("was the rocket in it?") read naturally, not like a raw enum.
ICON_POOL = (
    "rocket", "star", "heart", "lightning bolt", "fire", "diamond",
    "skull", "crown", "moon", "sun", "snowflake", "leaf",
)
SEQUENCE_LENGTH_CHOICES = (4, 5, 6, 7)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    length = random.choice(SEQUENCE_LENGTH_CHOICES)
    sequence = random.sample(ICON_POOL, length)

    # The recall challenge: either a real member of the sequence (asked
    # as "was X in it" -> yes) or a real non-member (-> no) -- decided
    # for real from the actual generated sequence, never simulated.
    asks_present = random.random() < 0.5
    if asks_present:
        target = random.choice(sequence)
        correct_answer = "yes"
    else:
        target = random.choice([icon for icon in ICON_POOL if icon not in sequence])
        correct_answer = "no"

    presentation_data = {"sequence": sequence, "phase": "sequence"}
    # No correct_answer here -- this is the view shown during real player
    # time while the viewer is still deciding, and the answer must never
    # enter a PLAYER_TIME segment's data at all (same discipline as
    # higher_or_lower's presentation_data / reveal_data split).
    question_data = {"target": target, "phase": "question"}
    reveal_data = {"sequence": sequence, "target": target, "correct_answer": correct_answer, "phase": "reveal"}

    memorize_time = estimate_thinking_time(GAME_TYPE, item_count=length, difficulty=difficulty)
    decide_time = estimate_thinking_time("simple_question", item_count=1, difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title=f"{length}-icon sequence",
        instructions=f"Was the {target} one of the {length} icons shown?",
        presentation_data=presentation_data,
        answer=correct_answer,
        explanation=f"The {target} was {'' if asks_present else 'not '}in the sequence -- {correct_answer}.",
        thinking_time=memorize_time + decide_time,
        reveal_data=reveal_data,
    )

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", "Memory Challenge -- watch closely, you'll only see it once."),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", f"Here's a sequence of {length} icons. Take it in.", round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=memorize_time, round_data=presentation_data),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "transition", f"Was the {target} one of them?", round_data=question_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=decide_time, round_data=question_data),
        make_segment(GAME_TYPE, round_index, PLAYER_TIME, "countdown", "", duration_seconds=3.0),
        make_segment(GAME_TYPE, round_index, HOST_TIME, "reveal", f"The answer is {correct_answer}.", round_data=reveal_data),
    ]

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.memory_challenge produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']} -- answer: {r['answer']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
