"""Family Game Night's "Who / What Am I?" (FAMILY_GAME_NIGHT_SPEC.md
Game Type H). Fully algorithmic, zero LLM calls -- a curated static pool
of {answer, clues} with clues already ordered hardest-to-easiest, same
pattern as the other procedural game types. The spec's own requirement
("the system must ensure each clue is accurate... the answer should
become progressively easier") is exactly what a curated, hand-ordered
pool guarantees by construction, rather than needing a live check of
whether a generated clue sequence actually gets easier.

Real player time after EVERY clue, not just the last one -- section 30
Game Type H's own example shows "PLAYER TIME" between each clue,
specifically so a viewer can guess early rather than only at the very
end.
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

GAME_TYPE = "who_what_am_i"

ROUND_POOL = (
    {
        "answer": "a door",
        "clues": (
            "I can be found in many homes.",
            "I am usually opened and closed.",
            "I help separate one room from another.",
        ),
    },
    {
        "answer": "an umbrella",
        "clues": (
            "I'm often forgotten somewhere.",
            "I only come out when it's wet.",
            "I open up to keep you dry.",
        ),
    },
    {
        "answer": "a candle",
        "clues": (
            "I get shorter the longer I'm used.",
            "I need a flame to do my job.",
            "I melt as I burn, and I give off light.",
        ),
    },
    {
        "answer": "the Eiffel Tower",
        "clues": (
            "I was only meant to stand temporarily.",
            "I'm made almost entirely of iron.",
            "I'm the most-visited paid monument in the world, in Paris.",
        ),
    },
    {
        "answer": "a mirror",
        "clues": (
            "I show you something every time you look at me.",
            "I never change what I show, only reflect it.",
            "I can be found above most bathroom sinks.",
        ),
    },
)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    available = [r for r in ROUND_POOL if r["answer"] not in avoid_topics] or list(ROUND_POOL)
    picked = random.choice(available)
    answer, clues = picked["answer"], picked["clues"]

    presentation_data = {"clues_shown": [clues[0]], "phase": "clues"}
    reveal_data = {"clues_shown": list(clues), "answer": answer, "phase": "reveal"}
    think_time = estimate_thinking_time("moderate_deduction", item_count=1, difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title="Who / What Am I?",
        instructions="Guess what's being described before the final clue.",
        presentation_data=presentation_data,
        answer=answer,
        explanation=f"It's {answer}.",
        thinking_time=think_time * len(clues),
        reveal_data=reveal_data,
    )

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", "Who or What Am I -- guess before I run out of clues."),
    ]
    for i, clue in enumerate(clues, start=1):
        ordinal = {1: "one", 2: "two", 3: "three"}.get(i, str(i))
        segments.append(
            make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", f"Clue {ordinal}: {clue}", round_data={"clues_shown": list(clues[:i]), "phase": "clues"})
        )
        segments.append(make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=think_time))
    segments.append(make_segment(GAME_TYPE, round_index, PLAYER_TIME, "countdown", "", duration_seconds=3.0))
    segments.append(make_segment(GAME_TYPE, round_index, HOST_TIME, "reveal", f"It's {answer}.", round_data=reveal_data))

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.who_what_am_i produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']} -- answer: {r['answer']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
