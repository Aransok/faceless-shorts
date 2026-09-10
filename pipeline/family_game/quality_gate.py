"""Pre-render quality gate (FAMILY_GAME_NIGHT_SPEC.md section 30 Phase 7,
section 18, section 32's failure-handling requirement).

Every round from a game module's own generate_round() already passes
pipeline.family_game.base.validate_round() internally -- missing
answer, answer-visible-too-early, non-positive thinking time, and so on
are already a hard floor no round can skip. This module is the layer on
top section 18 actually asks for beyond that floor:

- A few more per-round checks validate_round() doesn't cover (a real
  minimum thinking-time floor beyond merely positive, an
  overly-long-narration check).
- Cross-round checks that only make sense with the WHOLE episode in
  view (duplicate answers/titles across rounds) -- no single round's
  own validate_round() call could ever catch this.
- The regenerate-only-the-failed-round retry loop section 32 asks for
  ("reject round -> generate replacement -> validate replacement...
  however, prevent infinite regeneration loops"), bounded the same way
  this project already bounds every other retryable generation step
  (REVIEW_MAX_REWRITES in plan.py, VERIFY_MAX_ATTEMPTS in games/base.py)
  -- not a new pattern invented for this format.

Deliberately kept separate from pipeline/family_game/episode.py rather
than folded into compose_episode() -- that module's own docstring
already commits to that separation, and it means a caller who doesn't
need the extra episode-level checks (e.g. a unit test exercising just
the composer) isn't forced through this layer to get a valid episode.
"""

from __future__ import annotations

from pipeline.family_game.base import HOST_TIME, PLAYER_TIME, validate_round
from pipeline.family_game.episode import GAME_MODULES, MAIN_ROUND_PLAN, CLOSING_DIFFICULTY, CLOSING_GAME_TYPE
from pipeline.family_game.episode import INTRO_TEMPLATE, OUTRO_TEMPLATE, THEME_POOL, THEME_ROTATION_SLOT, THEME_ROTATION_WINDOW
from pipeline.family_game.episode import _select_rounds_plan
from pipeline.rotation import pick_rotating

# A hard floor below every game type's own configured thinking-time
# range (rapid_fire's 3-6s bucket has the lowest floor of any category
# in base.py's THINKING_TIME_RANGES) -- no correctly-generated round
# should ever actually hit this; it exists to catch a genuinely broken
# or hand-misconfigured round before it reaches rendering, not to
# second-guess a real game module's own timing choices.
MIN_THINKING_SECONDS = 3.0

# ~20 seconds of spoken narration at this pipeline's own established
# ~2.6-2.8 words/sec pacing (see config/prompts/sauce_recipe_template.txt
# and pipeline/voice.py's EDGE_TTS_RATE) -- a single host beat this long
# has drifted from "a quick host line" into something that should have
# been split across multiple beats, not a hard ceiling on the format
# overall.
MAX_HOST_NARRATION_WORDS = 60

# Matches this project's existing bounded-retry convention exactly
# (REVIEW_MAX_REWRITES, games/base.py's VERIFY_MAX_ATTEMPTS) -- not a
# new number picked without precedent.
MAX_REGENERATE_ATTEMPTS = 3


class QualityGateFailure(Exception):
    """Raised when a round still fails the quality gate after
    MAX_REGENERATE_ATTEMPTS regenerations -- section 32: "if repeated
    failure occurs: mark appropriately, log useful diagnostics, fail
    cleanly" rather than silently shipping broken content."""


def check_round(round_: dict, segments: list[dict]) -> tuple[bool, str]:
    """The per-round layer: validate_round()'s existing structural floor,
    plus the two extra section-18 checks it doesn't already cover."""
    ok, reason = validate_round(round_, segments)
    if not ok:
        return False, reason

    for s in segments:
        if s["kind"] == PLAYER_TIME and s["duration_seconds"] < MIN_THINKING_SECONDS:
            return False, f"PLAYER_TIME segment (beat={s['beat']!r}) duration {s['duration_seconds']:.1f}s is below the {MIN_THINKING_SECONDS}s floor"
        if s["kind"] == HOST_TIME and len(s["script_text"].split()) > MAX_HOST_NARRATION_WORDS:
            return False, f"HOST_TIME segment (beat={s['beat']!r}) narration is {len(s['script_text'].split())} words, over the {MAX_HOST_NARRATION_WORDS}-word cap"

    return True, "ok"


def generate_round_with_quality_gate(
    module, avoid_topics: list[str], round_index: int, difficulty: str = "medium",
) -> tuple[dict, list[dict]]:
    """Section 32's loop: reject a failing round, regenerate (not the
    whole episode), validate the replacement, bounded by
    MAX_REGENERATE_ATTEMPTS. Raises QualityGateFailure with the last
    real failure reason attached (the "log useful diagnostics" part --
    a caller catching this should have enough to actually act on, not
    just "it failed").
    """
    last_reason = None
    for attempt in range(1, MAX_REGENERATE_ATTEMPTS + 1):
        round_, segments = module.generate_round(avoid_topics, round_index, difficulty)
        ok, reason = check_round(round_, segments)
        if ok:
            return round_, segments
        last_reason = reason
        print(f"[quality_gate] round {round_index} attempt {attempt}/{MAX_REGENERATE_ATTEMPTS} rejected: {reason}")
    raise QualityGateFailure(
        f"round {round_index} ({getattr(module, '__name__', module)}) failed the quality gate "
        f"after {MAX_REGENERATE_ATTEMPTS} attempts -- last reason: {last_reason}"
    )


def check_episode(episode: dict) -> tuple[bool, list[str]]:
    """Cross-round checks section 18 names ("duplicate answer patterns",
    "repeated game too similar to recent round") that no single round's
    own validation could ever catch on its own -- these need the whole
    episode in view. Returns (ok, problems) rather than raising: unlike
    a single broken round (which has an obvious fix -- regenerate it),
    a whole-episode-level duplicate is a judgment call about which of
    two otherwise-valid rounds to touch, better surfaced to a caller
    than silently "fixed" here.
    """
    problems: list[str] = []
    answers_seen: dict[str, str] = {}
    titles_seen: dict[str, str] = {}
    for game in episode["games"]:
        answer_key = str(game["round"]["answer"]).strip().lower()
        title_key = str(game["round"]["title"]).strip().lower()
        if answer_key in answers_seen:
            problems.append(f"duplicate answer {game['round']['answer']!r} shared by {answers_seen[answer_key]!r} and {game['game_type']!r} rounds")
        else:
            answers_seen[answer_key] = game["game_type"]
        if title_key in titles_seen:
            problems.append(f"duplicate title {game['round']['title']!r} shared by {titles_seen[title_key]!r} and {game['game_type']!r} rounds")
        else:
            titles_seen[title_key] = game["game_type"]
    return not problems, problems


def compose_episode_with_quality_gate(avoid_topics_by_type: dict[str, list[str]] | None = None) -> dict:
    """The real Phase 7 entry point: same shape as
    episode.compose_episode(), but every round is generated through
    generate_round_with_quality_gate() instead of a bare
    module.generate_round() call, and the finished episode is checked
    with check_episode() before being returned. A cross-round problem
    doesn't raise (see check_episode()'s own docstring) -- it's
    attached to the returned episode as `episode["quality_warnings"]`
    so a caller (eventually Phase 8's full pipeline) can decide what to
    do with it, same "surface it, don't silently swallow it, don't
    silently crash either" spirit as the rest of this project's
    fail-soft convention.
    """
    avoid_topics_by_type = avoid_topics_by_type or {}
    theme = pick_rotating(THEME_ROTATION_SLOT, list(THEME_POOL), THEME_ROTATION_WINDOW)
    rounds_plan = _select_rounds_plan()

    games = []
    for round_index, (game_type, difficulty) in enumerate(rounds_plan):
        module = GAME_MODULES[game_type]
        avoid_topics = avoid_topics_by_type.get(game_type, [])
        round_, segments = generate_round_with_quality_gate(module, avoid_topics, round_index, difficulty)
        games.append({"game_type": game_type, "difficulty": difficulty, "round": round_, "segments": segments})

    theme_lowered = theme[0].lower() + theme[1:]
    episode = {
        "title": theme,
        "theme": theme,
        "intro": INTRO_TEMPLATE.format(theme=theme_lowered),
        "games": games,
        "outro": OUTRO_TEMPLATE,
    }
    ok, problems = check_episode(episode)
    episode["quality_warnings"] = [] if ok else problems
    if not ok:
        for p in problems:
            print(f"[quality_gate] episode-level warning: {p}")
    return episode
