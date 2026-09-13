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

Round count/mix (2026-09-13): the owner's real, explicit requirement
("good and working video at least 10 mins") was met on the OLDER
pipeline/games/ track by scaling round COUNT via a weighted pool
(plan_game.py's LONGFORM_ROUND_POOL) rather than by padding pacing --
same fix applied here now that this engine is the one actually shipping
(see ROADMAP.md). LONGFORM_GAME_POOL below is that same trick: a big
pool with repeated entries so `select_rounds()` (reused as-is from
pipeline/games/base.py, not reimplemented -- it already solves "no two
adjacent entries the same type" for a weighted pool with duplicates,
including the max-heap rearrangement fix for pools where a few types
each cover a large share of the entries) picks a long, varied,
no-adjacent-repeat sequence. higher_or_lower is the only LLM-touching
game type in this whole package (grep confirms it -- every other
module is a curated pool or procedural scene diff, zero LLM calls), so
capping it low in the pool keeps a much longer episode's real Claude
cost close to what the *old* 5-round format used to spend on ONE
higher_or_lower round, not scaled up with everything else.
"""

from __future__ import annotations

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
from pipeline.games.base import select_rounds
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

# Weighted so the free/algorithmic types (spot_the_difference, memory_
# challenge, odd_one_out, guess_the_connection, who_what_am_i) carry
# almost all of the episode's length, while higher_or_lower -- the one
# type that costs a real Claude call (plus verify_claim()'s own call) --
# stays capped at 2 regardless of how long the episode grows. Counts
# tuned against a real measured run (generating actual rounds and timing
# their real narration word counts + PLAYER_TIME durations, not a guess)
# to land at ~13 minutes total including the fixed Rapid Fire closer --
# inside section 15's 10-15 minute target without an even split forcing
# 5x today's LLM cost per episode.
LONGFORM_GAME_POOL = (
    ("spot_the_difference",) * 4
    + ("memory_challenge",) * 5
    + ("odd_one_out",) * 3
    + ("guess_the_connection",) * 4
    + ("who_what_am_i",) * 2
    + ("higher_or_lower",) * 2
)
MAIN_ROUND_COUNT = len(LONGFORM_GAME_POOL)

# Section 63/64's escalating-difficulty pacing made concrete: the first
# fifth of the episode is a confidence-building easy stretch, the last
# fifth is the hardest stretch right before the energetic Rapid Fire
# close, everything in between is medium. Bucketed by POSITION in the
# episode rather than by game type, so which slots land "easy" vs "hard"
# still varies round to round with whatever select_rounds() happens to
# order there -- the curve is about the shape of the episode, not about
# any one game type always being the hard one.
EASY_FRACTION = 0.2
HARD_FRACTION = 0.8


def _difficulty_for_position(index: int, total: int) -> str:
    fraction = index / total
    if fraction < EASY_FRACTION:
        return "easy"
    if fraction >= HARD_FRACTION:
        return "hard"
    return "medium"


# Rapid Fire always closes the episode -- section 30's own framing
# ("this should be the energetic ending", echoed by the new spec's
# section 65 "FINAL ROUND") makes it a fixed slot, not part of the
# rotating pool above. Its own generate_round() already packs 5
# sub-questions into that one round.
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
    """(game_type, difficulty) per round, in order -- MAIN_ROUND_COUNT
    picks from LONGFORM_GAME_POOL via select_rounds() (guaranteed no two
    adjacent rounds share a game type, even against this pool's heavily
    weighted duplicates), each paired with the difficulty its POSITION
    in the episode calls for, plus the fixed Rapid Fire closer."""
    game_types = select_rounds(MAIN_ROUND_COUNT, LONGFORM_GAME_POOL)
    plan = [(t, _difficulty_for_position(i, MAIN_ROUND_COUNT)) for i, t in enumerate(game_types)]
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

    Also tracks WITHIN-episode repeats (2026-09-13): LONGFORM_GAME_POOL
    can pick the same game type several times in one episode, and
    `avoid_topics_by_type` alone only ever carries cross-episode history
    a caller fed in up front -- it has no way to know what THIS episode
    already used earlier in the same loop. Each round's own title/answer
    (whichever a given module actually filters on -- see each module's
    own `avoid_topics` check) gets folded into that type's avoid list for
    every later round of the same type in this episode.
    """
    avoid_topics_by_type = avoid_topics_by_type or {}
    theme = pick_rotating(THEME_ROTATION_SLOT, list(THEME_POOL), THEME_ROTATION_WINDOW)
    rounds_plan = _select_rounds_plan()

    used_by_type: dict[str, list[str]] = {}
    games = []
    for round_index, (game_type, difficulty) in enumerate(rounds_plan):
        module = GAME_MODULES[game_type]
        avoid_topics = avoid_topics_by_type.get(game_type, []) + used_by_type.get(game_type, [])
        round_, segments = module.generate_round(avoid_topics, round_index, difficulty)
        used_by_type.setdefault(game_type, []).extend([round_["title"], str(round_["answer"])])
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
