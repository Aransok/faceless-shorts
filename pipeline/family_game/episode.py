"""Episode composer (FAMILY_GAME_NIGHT_SPEC.md section 30 Phase 6):
stitches several rounds from different game-type modules into one
episode. Implements section 7's "fully automated episode generation"
steps 1-2 (theme, game-type selection) and section 16/17's pacing and
difficulty-curve guidance, explicitly avoiding the failure mode section
7 calls out by name -- four Higher or Lower rounds back to back.

Deliberately does NOT re-implement Phase 7's quality gate here (that's
its own phase, not folded into composition) -- every game-type module's
own generate_round() already runs validate_round() internally and
raises on a genuinely broken round, so a round either comes back valid
or the composer call fails loudly. Phase 7's job is the richer stuff
section 18 actually asks for on top of that (regenerate only the failed
round rather than the whole episode, duplicate-answer-pattern checks
across the whole episode, an overly-long-narration check) -- none of
which belongs bolted onto orchestration logic.
"""

from __future__ import annotations

import random

from pipeline.family_game import (
    guess_the_connection,
    higher_or_lower,
    memory_challenge,
    odd_one_out,
    rapid_fire,
    spot_the_difference,
    who_what_am_i,
)
from pipeline.family_game.base import HOST_TIME, make_segment
from pipeline.rotation import pick_rotating

GAME_MODULES = {
    "higher_or_lower": higher_or_lower,
    "spot_the_difference": spot_the_difference,
    "memory_challenge": memory_challenge,
    "odd_one_out": odd_one_out,
    "guess_the_connection": guess_the_connection,
    "who_what_am_i": who_what_am_i,
    "rapid_fire": rapid_fire,
}

# Section 16's pacing curve made concrete -- an easy confidence-builder,
# two moderate rounds pulling from different cognitive categories
# (section 2: "alternate cognitive experiences" -- comparison/deduction,
# then pure visual observation, then memory), one deliberately harder
# challenge before the energetic close. Each slot offers a small POOL,
# not one fixed type, specifically so back-to-back episodes don't all
# open with the same game (section 19: avoid repeated game ordering) --
# _select_rounds_plan() also refuses to repeat a type already used
# earlier in the SAME episode, the exact "four Higher or Lower rounds"
# failure mode section 7 names directly.
#
# Difficulty here is the 3-valued scale every game module already uses
# (easy/medium/hard) -- coarser than section 17's own 7-step example
# curve (easy, easy-medium, medium, medium, medium-hard, hard, rapid),
# collapsed onto the levels that actually exist rather than adding
# granularity nothing reads yet.
MAIN_ROUND_PLAN = (
    {"pool": ("higher_or_lower", "odd_one_out"), "difficulty": "easy"},
    {"pool": ("guess_the_connection", "who_what_am_i"), "difficulty": "medium"},
    {"pool": ("spot_the_difference",), "difficulty": "medium"},
    {"pool": ("memory_challenge",), "difficulty": "medium"},
    {"pool": ("higher_or_lower", "guess_the_connection", "odd_one_out", "who_what_am_i"), "difficulty": "hard"},
)
# Rapid Fire always closes the episode -- section 30's own framing
# ("this should be the energetic ending") makes it a fixed slot, not
# part of the rotating pool above.
CLOSING_GAME_TYPE = "rapid_fire"
CLOSING_DIFFICULTY = "medium"

# Section 7 Step 1's own example themes, verbatim.
THEME_POOL = (
    "Family Game Night: Can You Beat Everyone?",
    "The Ultimate Mixed Challenge",
    "Easy to Hard Family Challenge",
    "Brain vs Memory Game Night",
    "Can Your Family Get a Perfect Score?",
)
THEME_ROTATION_SLOT = "family_game_episode_theme"
# Sized to the pool itself (5 entries) -- pick_rotating()'s own docstring
# warns a window >= pool size makes the exclusion a permanent no-op, the
# exact mistake already caught once before in this project (Phase 14's
# CTA-overlay pool).
THEME_ROTATION_WINDOW = 3

INTRO_TEMPLATE = "Welcome back to Family Game Night. Tonight: {theme}. Let's see how you do."
OUTRO_TEMPLATE = "That's the episode. However you did tonight, there's always next time."


def _select_rounds_plan() -> list[tuple[str, str]]:
    """(game_type, difficulty) per round, in order -- one pick per
    MAIN_ROUND_PLAN slot, each excluding any type already used earlier
    in this same episode, plus the fixed Rapid Fire closer."""
    used: set[str] = set()
    plan: list[tuple[str, str]] = []
    for slot in MAIN_ROUND_PLAN:
        candidates = [t for t in slot["pool"] if t not in used] or list(slot["pool"])
        picked = random.choice(candidates)
        plan.append((picked, slot["difficulty"]))
        used.add(picked)
    plan.append((CLOSING_GAME_TYPE, CLOSING_DIFFICULTY))
    return plan


def compose_episode(avoid_topics_by_type: dict[str, list[str]] | None = None) -> dict:
    """Returns an Episode dict (section 24's recommended shape): title,
    theme, intro, games[] (each {game_type, difficulty, round,
    segments}), outro.

    `avoid_topics_by_type` lets a caller feed in cross-episode
    repeat-avoidance per game type (e.g. "don't reuse this
    guess_the_connection answer again") -- this module has no opinion on
    WHERE that history comes from; wiring it to state.db is real future
    work for whenever this format joins the daily orchestrator (see
    ROADMAP.md), not something to invent here ahead of that need.
    """
    avoid_topics_by_type = avoid_topics_by_type or {}
    theme = pick_rotating(THEME_ROTATION_SLOT, list(THEME_POOL), THEME_ROTATION_WINDOW)
    rounds_plan = _select_rounds_plan()

    games = []
    for round_index, (game_type, difficulty) in enumerate(rounds_plan):
        module = GAME_MODULES[game_type]
        avoid_topics = avoid_topics_by_type.get(game_type, [])
        round_, segments = module.generate_round(avoid_topics, round_index, difficulty)
        games.append({"game_type": game_type, "difficulty": difficulty, "round": round_, "segments": segments})

    theme_lowered = theme[0].lower() + theme[1:]
    return {
        "title": theme,
        "theme": theme,
        "intro": INTRO_TEMPLATE.format(theme=theme_lowered),
        "games": games,
        "outro": OUTRO_TEMPLATE,
    }


def flatten_episode_to_segments(episode: dict) -> list[dict]:
    """The whole episode as one flat segment list, ready for
    render.render_episode() completely unchanged -- intro/outro become
    their own HOST_TIME segments under a synthetic "episode" game_type,
    which isn't in render.py's per-game-type dispatch table, so they
    fall through to the existing plain-text-card path with no new
    rendering code needed.
    """
    segments = [make_segment("episode", -1, HOST_TIME, "intro", episode["intro"])]
    for game in episode["games"]:
        segments.extend(game["segments"])
    segments.append(make_segment("episode", len(episode["games"]), HOST_TIME, "explanation", episode["outro"]))
    return segments


if __name__ == "__main__":
    ep = compose_episode()
    print(f"THEME: {ep['theme']}")
    print(f"INTRO: {ep['intro']}")
    for g in ep["games"]:
        print(f"  round {g['round']['game_type']} (difficulty={g['difficulty']}): {g['round']['title']} -- answer: {g['round']['answer']}")
    print(f"OUTRO: {ep['outro']}")
    total_segments = flatten_episode_to_segments(ep)
    total_player_seconds = sum(s["duration_seconds"] or 0 for s in total_segments if s["kind"] != HOST_TIME)
    print(f"Total segments: {len(total_segments)}, total real player-time seconds: {total_player_seconds:.1f}")
