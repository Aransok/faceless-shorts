"""Foundation for the Family Game Night long-form format: the round/
segment data model and the HOST TIME / PLAYER TIME state machine the
whole format is built around (FAMILY_GAME_NIGHT_SPEC.md section 2 --
"the video must give people time to play", the spec's own single most
important rule).

Deliberately a new package, not an extension of pipeline/games/. That
package drives the blocked Shorts-length game_night track (still
blocked, see ROADMAP.md Phase 16) whose original simulated-contestant/
win-loss mechanic was cut entirely after real owner feedback ("the ai
plays by himself") -- pipeline/games/base.py's make_beat()/BEAT_TYPES
already reflects that fix, but it still has no HOST/PLAYER distinction:
every beat's on-screen duration comes from its own narration audio
(padded up to a small fixed per-beat-type floor via
voice.GAME_NIGHT_MIN_BEAT_SECONDS). That's fine for a Short. It cannot
express this spec's actual requirement -- an explicit, narration-
independent block of real seconds where the viewer thinks and the
narrator stays quiet (section 25: "The countdown and player time must
not depend on narration audio duration. They must be explicit timeline
events."). This module exists to fill exactly that gap.

verify_claim() is reused as-is via import, not copied -- fact-checking a
numeric claim has nothing format-specific about it, and this format's
own "must not hallucinate numerical facts" rule (Game Type A) is the
same requirement Phase 16 already solved.
"""

from __future__ import annotations

import json
from pathlib import Path

from pipeline.games.base import verify_claim  # noqa: F401  (re-exported for game-type modules)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_HOST_PERSONA_PATH = PROJECT_ROOT / "config" / "persona_family_game_host.md"

HOST_TIME = "host"
PLAYER_TIME = "player"
SEGMENT_KINDS = (HOST_TIME, PLAYER_TIME)

# What a segment of each kind is allowed to be. A "reveal" cannot be a
# PLAYER_TIME beat by construction -- the answer must never surface while
# the viewer is still meant to be guessing (section 9).
HOST_BEATS = ("intro", "rule", "prompt", "reveal", "explanation", "transition")
PLAYER_BEATS = ("think", "countdown")

DIFFICULTIES = ("easy", "medium", "hard")

# Section 8's suggested conceptual thinking-time ranges, in seconds, by
# round category -- explicitly "starting points, not fixed requirements"
# per the spec, kept here as named constants (not scattered magic
# numbers in each game-type module) so a later tuning pass -- likely
# once there's a real rendered test episode to watch, same pattern this
# project used for voice.py's GAME_NIGHT_MIN_BEAT_SECONDS and
# visuals_quiz.py's COUNTDOWN_SECONDS -- has one place to look.
THINKING_TIME_RANGES: dict[str, tuple[float, float]] = {
    "simple_question": (5.0, 8.0),
    "moderate_deduction": (8.0, 12.0),
    "memory_challenge": (8.0, 15.0),
    "spot_the_difference": (10.0, 20.0),
    "connection": (10.0, 15.0),
    "rapid_fire": (3.0, 6.0),
}

# Section 8: "A round with 10 words should not receive the same thinking
# time as a round with 2 words" -- made concrete as a small additive
# nudge (not a multiplier, so it can't blow a category's range wide
# open) rather than left as prose with no code behind it.
SECONDS_PER_EXTRA_ITEM = 0.6
ITEMS_INCLUDED_IN_BASE = 2
_MAX_EXTRA_ITEM_STEPS = 3


def estimate_thinking_time(category: str, item_count: int = ITEMS_INCLUDED_IN_BASE, difficulty: str = "medium") -> float:
    """Deterministic PLAYER_TIME duration for a round. Never invented
    per-round by the LLM (section 8: "the generator must not arbitrarily
    invent timing") -- every game-type module calls this instead of
    picking its own number.
    """
    if category not in THINKING_TIME_RANGES:
        raise ValueError(f"unknown thinking-time category {category!r}, must be one of {sorted(THINKING_TIME_RANGES)}")
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}, got {difficulty!r}")

    lo, hi = THINKING_TIME_RANGES[category]
    base = {"easy": lo, "medium": (lo + hi) / 2.0, "hard": hi}[difficulty]
    extra_items = max(0, item_count - ITEMS_INCLUDED_IN_BASE)
    duration = base + extra_items * SECONDS_PER_EXTRA_ITEM
    return min(duration, hi + SECONDS_PER_EXTRA_ITEM * _MAX_EXTRA_ITEM_STEPS)


def make_segment(
    game_type: str,
    round_index: int,
    kind: str,
    beat: str,
    script_text: str = "",
    duration_seconds: float | None = None,
    round_data: dict | None = None,
) -> dict:
    """One row of the family-game render timeline. Shaped like
    pipeline/games/base.py's make_beat() (script_text/round_index/
    round_data_json) so it can eventually ride the same kind of
    video_steps columns once this format is wired into state.py -- but
    adds `kind` (HOST_TIME vs PLAYER_TIME) and an explicit
    `duration_seconds`, neither of which make_beat() has any equivalent
    of, because the format it serves never needed them.

    A PLAYER_TIME segment MUST carry an explicit duration_seconds (from
    estimate_thinking_time(), never improvised) -- see the module
    docstring. A silent PLAYER_TIME segment (script_text="") is expected
    and correct, not a bug: section 2 -- "silence is sometimes part of
    the game."
    """
    if kind not in SEGMENT_KINDS:
        raise ValueError(f"kind must be one of {SEGMENT_KINDS}, got {kind!r}")
    allowed_beats = HOST_BEATS if kind == HOST_TIME else PLAYER_BEATS
    if beat not in allowed_beats:
        raise ValueError(f"beat {beat!r} not valid for kind={kind!r} segments; must be one of {allowed_beats}")
    if kind == PLAYER_TIME and (duration_seconds is None or duration_seconds <= 0):
        raise ValueError(
            "PLAYER_TIME segments must have an explicit positive duration_seconds "
            "(from estimate_thinking_time()) -- never derived from narration audio"
        )

    return {
        "game_type": game_type,
        "round_index": round_index,
        "kind": kind,
        "beat": beat,
        "script_text": script_text,
        "duration_seconds": duration_seconds,
        "round_data_json": json.dumps(round_data) if round_data is not None else None,
    }


ROUND_FIELDS = (
    "game_type", "difficulty", "title", "instructions", "presentation_data",
    "answer", "explanation", "thinking_time", "reveal_data",
)


def make_round(
    game_type: str,
    difficulty: str,
    title: str,
    instructions: str,
    presentation_data: dict,
    answer: str,
    explanation: str,
    thinking_time: float,
    reveal_data: dict,
) -> dict:
    """Section 24's recommended Round data model, adapted to this
    project's plain-dict convention (matches make_beat()/the games/*.py
    modules -- no dataclasses/inheritance where a dict already does the
    job, per section 24's own "do not overengineer" instruction).
    """
    if difficulty not in DIFFICULTIES:
        raise ValueError(f"difficulty must be one of {DIFFICULTIES}, got {difficulty!r}")
    if thinking_time <= 0:
        raise ValueError(f"thinking_time must be positive, got {thinking_time!r}")
    return {
        "game_type": game_type,
        "difficulty": difficulty,
        "title": title,
        "instructions": instructions,
        "presentation_data": presentation_data,
        "answer": answer,
        "explanation": explanation,
        "thinking_time": thinking_time,
        "reveal_data": reveal_data,
    }


def validate_round(round_: dict, segments: list[dict]) -> tuple[bool, str]:
    """The structural, no-LLM-call layer of section 18's quality gate --
    checks that apply to every round regardless of game type, enforcing
    the HOST/PLAYER state machine itself rather than any one game
    type's content. Phase 7 (not built yet) adds an LLM-based layer on
    top of this (e.g. "does this connection actually hold") for game
    types whose validity can't be checked mechanically; this layer
    should never need one, on purpose -- it's the free, always-on floor
    every round passes through first.

    Returns (ok, reason) rather than raising, so a caller building an
    episode can log/skip/regenerate a specific failing round instead of
    crashing the whole run -- matches this project's fail-soft
    convention (CLAUDE.md).
    """
    missing = [f for f in ROUND_FIELDS if round_.get(f) in (None, "", {})]
    if missing:
        return False, f"round missing required field(s): {missing}"

    if not segments:
        return False, "round has no segments"

    player_segments = [s for s in segments if s["kind"] == PLAYER_TIME]
    if not player_segments:
        return False, "round has no PLAYER_TIME segment -- the viewer is never given time to play"

    answer_lower = str(round_["answer"]).strip().lower()
    for s in player_segments:
        if s.get("duration_seconds") is None or s["duration_seconds"] <= 0:
            return False, f"PLAYER_TIME segment (beat={s['beat']!r}) has no positive duration_seconds"
        if answer_lower and s.get("script_text") and answer_lower in s["script_text"].lower():
            return False, f"PLAYER_TIME segment (beat={s['beat']!r}) narration leaks the answer {round_['answer']!r}"

    # No PLAYER_TIME segment may trail after every reveal in the round --
    # that would mean its own decision window never actually gets an
    # answer shown, section 9's rule turned inside-out. This deliberately
    # checks against the LAST reveal, not the first: a multi-cycle round
    # (rapid_fire's several question/think/reveal groups back to back) is
    # fine having player time between an EARLIER cycle's reveal and a
    # LATER cycle's own reveal -- only a player segment with no reveal
    # anywhere after it at all is the real bug (the exact case a reordered
    # round -- reveal moved before its own think/countdown -- produces).
    reveal_indices = [i for i, s in enumerate(segments) if s["beat"] == "reveal"]
    player_indices = [i for i, s in enumerate(segments) if s["kind"] == PLAYER_TIME]
    if not reveal_indices:
        return False, "round has no 'reveal' segment at all"
    if player_indices and max(player_indices) > max(reveal_indices):
        return False, "a PLAYER_TIME segment appears after every reveal -- its own answer never gets shown"

    return True, "ok"


def host_persona_guidance_block() -> str:
    """Formatted for appending directly to a round-generation prompt.
    Deliberately reads ONLY config/persona_family_game_host.md, not
    config/persona.md's shared core the way pipeline/persona.py's
    persona_guidance_block() does for the other templates -- that core
    is written for the Shorts/quiz narrator (its CTA phrasing rules and
    sentence-rhythm-for-a-30-45-second-script guidance don't apply to a
    10-20 minute game-show host), and persona_family_game_host.md
    already explicitly folds in the two rules from it that DO carry over
    (no invented facts, no fabricated personal experience) rather than
    relying on this function to layer the whole file in. Once this
    format is wired into state.py's video/template system (Phase 6, not
    yet done), the natural point to reconsider folding this into
    pipeline/persona.py's own _PET_PEEVES_FILE mapping is then, not now.
    """
    return (
        "\n\nHOST PERSONA -- write in this specific voice, not a neutral "
        "narrator (full definition, follow it, don't just skim it):\n\n"
        f"{_HOST_PERSONA_PATH.read_text(encoding='utf-8')}\n"
    )
