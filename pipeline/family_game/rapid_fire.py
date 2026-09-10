"""Family Game Night's "Rapid Fire Final Round" (FAMILY_GAME_NIGHT_SPEC.md
Game Type I). Fully algorithmic, zero LLM calls -- a curated static pool
of true/false statements, all real, checkable facts (no invented
numbers, per this project's standing anti-hallucination rule). Unlike
every other game type here, this one is a SEQUENCE of several quick
challenges inside one round, not a single question -- section 30's own
framing ("5 questions, 5 seconds each... this should be the energetic
ending") is about pace, not depth, so think time per item is short and
there's no per-item countdown beat -- a real countdown for every one of
5 rapid-fire questions would work against the "fast, energetic" feel
the spec explicitly asks for.
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

GAME_TYPE = "rapid_fire"
QUESTIONS_PER_ROUND = 5

STATEMENT_POOL = (
    {"statement": "An octopus has three hearts.", "answer": "true"},
    {"statement": "A group of crows is called a murder.", "answer": "true"},
    {"statement": "Goldfish have a memory span of only a few seconds.", "answer": "false"},
    {"statement": "Bananas are berries, but strawberries aren't.", "answer": "true"},
    {"statement": "The Great Wall of China is visible from space with the naked eye.", "answer": "false"},
    {"statement": "Honey never spoils.", "answer": "true"},
    {"statement": "A bolt of lightning is hotter than the surface of the sun.", "answer": "true"},
    {"statement": "Humans only use 10 percent of their brains.", "answer": "false"},
    {"statement": "Sharks existed before trees did.", "answer": "true"},
    {"statement": "Mount Everest is the tallest mountain measured base to peak.", "answer": "false"},
)


def generate_round(avoid_topics: list[str], round_index: int, difficulty: str = "medium") -> tuple[dict, list[dict]]:
    available = [s for s in STATEMENT_POOL if s["statement"] not in avoid_topics] or list(STATEMENT_POOL)
    count = min(QUESTIONS_PER_ROUND, len(available))
    picked = random.sample(available, count)
    think_time = estimate_thinking_time("rapid_fire", item_count=1, difficulty=difficulty)

    round_ = make_round(
        game_type=GAME_TYPE,
        difficulty=difficulty,
        title=f"Rapid Fire -- {count} questions",
        instructions="True or false, as fast as you can.",
        presentation_data={"statements": [p["statement"] for p in picked], "phase": "question"},
        answer="; ".join(f"{p['statement']} -> {p['answer']}" for p in picked),
        explanation="Each statement's real answer is stated right after it.",
        thinking_time=think_time * count,
        reveal_data={"statements": picked, "phase": "reveal"},
    )

    segments = [
        make_segment(GAME_TYPE, round_index, HOST_TIME, "intro", f"Rapid Fire -- {count} questions, {think_time:.0f} seconds each. Ready?"),
    ]
    for item in picked:
        segments.append(make_segment(GAME_TYPE, round_index, HOST_TIME, "prompt", f"True or false: {item['statement']}"))
        segments.append(make_segment(GAME_TYPE, round_index, PLAYER_TIME, "think", "", duration_seconds=think_time))
        segments.append(make_segment(GAME_TYPE, round_index, HOST_TIME, "reveal", f"{item['answer'].capitalize()}."))

    ok, reason = validate_round(round_, segments)
    if not ok:
        raise ValueError(f"family_game.rapid_fire produced an invalid round: {reason}")

    return round_, segments


if __name__ == "__main__":
    r, segs = generate_round(avoid_topics=[], round_index=0)
    print(f"ROUND: {r['title']}")
    for seg in segs:
        label = f"[{seg['kind']}:{seg['beat']}]"
        duration = f" ({seg['duration_seconds']}s)" if seg["duration_seconds"] else ""
        print(f"{label}{duration} {seg['script_text']}")
