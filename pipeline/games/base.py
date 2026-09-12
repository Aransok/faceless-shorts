"""Shared game-night infrastructure: the round-selector, the beat schema
every module writes into, and the fact-verification helper used by the
two LLM-content modules (higher_or_lower, prediction). See ROADMAP.md
Phase 16.

No session/scoring here -- an earlier version simulated a "contestant"
guessing each round and won/lost lives and points against that simulated
outcome. Cut entirely after watching a real rendered test episode: it
read as a fake AI playing the game by itself, disconnected from the
actual viewer. Every round now just presents its real content, holds for
suspense, and reveals the real answer/outcome -- no invented judgment of
whether anyone "won."
"""

from __future__ import annotations

import heapq
import json
import random
import re
from collections import Counter

from pipeline.plan import call_llm

ROUND_TYPES = ("higher_or_lower", "memory", "what_changed", "risk_or_safe", "prediction")

# The two modules whose content is an LLM claim, not a fully algorithmic
# generation -- these are the only ones that need verify_claim().
VERIFIED_CONTENT_ROUND_TYPES = ("higher_or_lower", "prediction")

# Owner's call: if verify_claim() rejects every retry for a slot picked as
# one of the above, substitute one of these (fully algorithmic, nothing to
# verify) rather than failing episode generation outright.
FALLBACK_ROUND_TYPES = ("memory", "what_changed")

BEAT_TYPES = ("intro", "rule", "countdown", "gameplay", "suspense", "reveal")

VERIFY_MAX_ATTEMPTS = 3

_VERDICT_PATTERN = re.compile(r"VERDICT:\s*(CONFIRMED|REJECTED)", re.IGNORECASE)
_CORRECTED_PATTERN = re.compile(r"CORRECTED:\s*(.+)")


class RoundVerificationFailed(Exception):
    """Raised by higher_or_lower/prediction when verify_claim() rejects
    every generation attempt for a slot. plan_game.py catches this and
    substitutes a FALLBACK_ROUND_TYPES module for that slot rather than
    failing episode generation outright -- owner's explicit call.
    """


def _arrange_no_adjacent_repeats(items: list[str]) -> list[str]:
    """Classic greedy rearrangement (a max-heap keyed by how many of each
    type remain, always placing the most plentiful type that isn't the
    one just placed, then "cooling it down" for exactly one step before
    it's eligible again) -- the standard, guaranteed-correct algorithm
    for this problem. Succeeds whenever no single type is more than half
    of `items`; raises otherwise, since no valid ordering exists at all
    in that case, not just an unlucky attempt. A random per-type
    tiebreaker (not alphabetical/insertion order) keeps two equally-
    plentiful types from always landing in the same relative order every
    time this runs -- real variety across episodes, not a fixed pattern.
    """
    counts = Counter(items)
    max_type, max_count = max(counts.items(), key=lambda kv: kv[1])
    if max_count > (len(items) + 1) // 2:
        raise RuntimeError(
            f"no no-adjacent-repeat ordering exists: {max_type!r} is {max_count} of {len(items)} entries"
        )

    heap = [(-c, random.random(), t) for t, c in counts.items()]
    heapq.heapify(heap)
    result: list[str] = []
    cooldown: tuple[int, float, str] | None = None
    while heap:
        neg_count, tiebreak, type_name = heapq.heappop(heap)
        result.append(type_name)
        if cooldown is not None:
            heapq.heappush(heap, cooldown)
            cooldown = None
        neg_count += 1  # one fewer remaining (neg_count is negative)
        if neg_count < 0:
            cooldown = (neg_count, tiebreak, type_name)
    return result


def select_rounds(count: int, pool: tuple[str, ...] = ROUND_TYPES) -> list[str]:
    """Random sequence of `count` round types from `pool`, guaranteeing no
    two adjacent entries are the same type -- the owner's "no same game
    type twice in a row, reasonable mix" requirement. `pool` may contain
    repeated entries to weight some types more heavily than others (see
    plan_game.py's LONGFORM_ROUND_POOL, which repeats the free/algorithmic
    types far more than the LLM-touching ones) -- the no-adjacent-repeat
    guarantee is enforced either way, not just for a pool of all-distinct
    types.

    Real bug fixed here (2026-09-12): the old count<=len(pool) branch was
    a bare shuffle with no adjacency check at all, silently relying on
    every caller only ever passing an all-distinct pool (true at the
    time -- the only pool that existed was the 5 distinct ROUND_TYPES).
    A first attempt at a fix (retry-shuffling up to 200 times and
    checking) turned out to still fail in practice for a real production
    pool (three types each ~27% of a 30-entry pool) -- random retries
    just aren't reliable odds against multiple large, similarly-sized
    groups. Replaced with a real, guaranteed-correct rearrangement
    algorithm instead of hoping a random shuffle gets lucky.
    """
    if count <= len(pool):
        subset = list(pool) if count == len(pool) else random.sample(pool, count)
        return _arrange_no_adjacent_repeats(subset)

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
    round_data: dict | None = None,
) -> dict:
    """One video_steps row for the shared render timing contract (intro ->
    rule -> countdown -> gameplay -> suspense -> reveal)."""
    if beat_type not in BEAT_TYPES:
        raise ValueError(f"beat_type must be one of {BEAT_TYPES}, got {beat_type!r}")
    return {
        "script_text": script_text,
        "round_type": round_type,
        "round_index": round_index,
        "beat_type": beat_type,
        "round_data_json": json.dumps(round_data) if round_data is not None else None,
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
