"""Shared game-night infrastructure: session/scoring, the round-selector,
the beat schema every module writes into, and the fact-verification
helper used by the two LLM-content modules (higher_or_lower,
prediction). See ROADMAP.md Phase 16.
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass, field

from pipeline.plan import call_llm

ROUND_TYPES = ("higher_or_lower", "memory", "what_changed", "risk_or_safe", "prediction")

# The two modules whose content is an LLM claim, not a fully algorithmic
# generation -- these are the only ones that need verify_claim().
VERIFIED_CONTENT_ROUND_TYPES = ("higher_or_lower", "prediction")

# Owner's call: if verify_claim() rejects every retry for a slot picked as
# one of the above, substitute one of these (fully algorithmic, nothing to
# verify) rather than failing episode generation outright.
FALLBACK_ROUND_TYPES = ("memory", "what_changed")

BEAT_TYPES = ("intro", "rule", "countdown", "gameplay", "suspense", "reveal", "score")

STARTING_LIVES = 3
VERIFY_MAX_ATTEMPTS = 3

_VERDICT_PATTERN = re.compile(r"VERDICT:\s*(CONFIRMED|REJECTED)", re.IGNORECASE)
_CORRECTED_PATTERN = re.compile(r"CORRECTED:\s*(.+)")


class RoundVerificationFailed(Exception):
    """Raised by higher_or_lower/prediction when verify_claim() rejects
    every generation attempt for a slot. plan_game.py catches this and
    substitutes a FALLBACK_ROUND_TYPES module for that slot rather than
    failing episode generation outright -- owner's explicit call.
    """


@dataclass
class GameSession:
    """Real narrative state carried across an episode's rounds -- lives
    and points are computed once at plan time from each round's actual
    algorithmic outcome, then stored on the steps (lives_after/
    points_after), not re-derived at render time.
    """

    lives: int = STARTING_LIVES
    points: int = 0
    round_types_used: list[str] = field(default_factory=list)

    def apply_round_result(self, passed: bool, points_delta: int) -> None:
        if passed:
            self.points += points_delta
        else:
            self.lives -= 1


def select_rounds(count: int, pool: tuple[str, ...] = ROUND_TYPES) -> list[str]:
    """Random sequence of `count` round types from `pool`, guaranteeing no
    two adjacent entries are the same type -- the owner's "no same game
    type twice in a row, reasonable mix" requirement. For count <= len(pool)
    this reduces to a shuffle (all distinct, so adjacency is trivially
    satisfied); for count > len(pool) each pick excludes only the
    immediately preceding type, same mechanism either way.
    """
    if count <= len(pool):
        rounds = list(pool)
        random.shuffle(rounds)
        return rounds[:count]

    rounds = [random.choice(pool)]
    for _ in range(count - 1):
        candidates = [r for r in pool if r != rounds[-1]]
        rounds.append(random.choice(candidates))
    return rounds


def make_beat(
    round_type: str,
    round_index: int,
    beat_type: str,
    script_text: str,
    session: GameSession,
    round_data: dict | None = None,
) -> dict:
    """One video_steps row for the shared render timing contract (intro ->
    rule -> countdown -> gameplay -> suspense -> reveal -> score). Session
    values are snapshotted as of THIS beat -- every beat up through
    "reveal" carries the pre-round lives/points; "score" is the one beat
    whose lives_after/points_after actually differ, since it's the beat
    that exists to display the change.
    """
    if beat_type not in BEAT_TYPES:
        raise ValueError(f"beat_type must be one of {BEAT_TYPES}, got {beat_type!r}")
    return {
        "script_text": script_text,
        "round_type": round_type,
        "round_index": round_index,
        "beat_type": beat_type,
        "round_data_json": json.dumps(round_data) if round_data is not None else None,
        "lives_after": session.lives,
        "points_after": session.points,
    }


def verify_claim(claim: str) -> dict:
    """Independent second LLM call that sees ONLY the claim text -- not the
    prompt/context that generated it -- so it can't just rubber-stamp its
    own reasoning. Forced into a closed VERDICT: CONFIRMED|REJECTED
    contract (see ai-agent-design.md's closed-vocabulary pattern) plus an
    optional CORRECTED value. This is what "don't let an unverified claim
    go out" actually means in code, not just in the prompt.
    """
    prompt = (
        "You are a fact-checker for a casual trivia game show. You will "
        "be given ONE factual claim, with no other context. Your job is "
        "to judge whether it is SUBSTANTIVELY true -- would a viewer be "
        "meaningfully misled by it, for a casual higher/lower or above/"
        "below comparison?\n\n"
        "Treat reasonable rounding and normal source-to-source variation "
        "as CONFIRMED, not REJECTED. If the claim says a value is "
        "\"approximately X\" and the real figure is close to X (a "
        "different commonly-cited source, a rounder or more precise "
        "figure, a recent vs. older survey), that is the SAME claim for "
        "this purpose -- confirm it. Only REJECT if the claim is "
        "actually wrong in a way that would flip a real comparison or "
        "threshold: wrong order of magnitude, wrong direction, a "
        "fabricated or incorrect fact, or a number well outside any "
        "commonly-cited range for that subject.\n\n"
        f"CLAIM: {claim}\n\n"
        "Respond in EXACTLY this format, nothing else:\n"
        "VERDICT: CONFIRMED\n"
        "(if the claim is substantively accurate, even if not exact to "
        "the decimal)\n\n"
        "or:\n"
        "VERDICT: REJECTED\n"
        "CORRECTED: <the accurate version, if you are confident of one -- "
        "omit this line if you are not confident>\n\n"
        "Be reasonable, not pedantic: minor rounding or a commonly-cited "
        "range is fine. Only reject a claim that would actually mislead "
        "someone about the real-world comparison."
    )
    raw = call_llm(prompt)
    # Despite "respond in EXACTLY this format, nothing else", the model
    # sometimes reasons out loud and self-corrects mid-response (observed
    # for real: a REJECTED verdict followed by reasoning that concludes
    # the claim is actually fine, ending in a second, final CONFIRMED).
    # .search() would grab the FIRST verdict and silently get this
    # backwards -- take the LAST one, which is the model's actual settled
    # answer, not the strict-format instruction alone (code enforcing
    # what the prompt only asked for, per this project's own rule for
    # exactly this failure mode).
    verdict_matches = list(_VERDICT_PATTERN.finditer(raw))
    if not verdict_matches:
        # No parseable verdict at all -- treat as REJECTED rather than
        # silently letting an unparseable response count as confirmed.
        return {"verdict": "REJECTED", "corrected": None, "raw": raw}

    verdict = verdict_matches[-1].group(1).upper()
    corrected = None
    if verdict == "REJECTED":
        corrected_matches = list(_CORRECTED_PATTERN.finditer(raw))
        corrected = corrected_matches[-1].group(1).strip() if corrected_matches else None
    return {"verdict": verdict, "corrected": corrected, "raw": raw}
