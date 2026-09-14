"""Content-approach rotation: which hook/structure/phrasing style pool new
videos draw from, set via config.yaml's current_approach. Exists so a
week of videos doesn't all read as the same rigid template with only the
topic swapped — both for A/B testing which approach performs better and
to stay clear of YouTube's inauthentic-content policy, which flags videos
that look like clones.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pipeline.rotation import pick_rotating

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
APPROACHES_PATH = PROJECT_ROOT / "config" / "approaches.yaml"

# How many of each slot's most-recently-used phrases to avoid repeating.
# Global across approaches (not per-approach) — simpler, and a phrase
# from one approach's pool never collides with another's anyway since
# the strings themselves are distinct. Sized against an 18-item pool —
# see pipeline/rotation.py's docstring for why this number can't just be
# reused for a much smaller pool (it bit the theme rotation during design).
RECENT_PHRASES_LIMIT = 15


def get_current_approach() -> str:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    approach = config.get("current_approach")
    if not approach:
        raise ValueError(f"{CONFIG_PATH} has no current_approach set")
    return approach


# Below this many eligible same-approach samples, a comparison is too
# noisy to trust -- same reasoning as winner_analyzer.py's own
# MIN_TEMPLATE_SAMPLE, just applied to approaches instead of templates.
MIN_APPROACH_SAMPLE = 5


def choose_next_approach() -> str:
    """The real feedback loop this config file's own comment described
    but nothing ever implemented (2026-09-14): current_approach had been
    manually fixed to storytelling_hook since launch -- no other
    approach had ever actually been tried, so there was no comparative
    data for anything to learn from. Picks the real best-performing
    approach once enough eligible samples exist for at least 2 of them
    (see MIN_APPROACH_SAMPLE); until then, rotates to whichever approach
    hasn't been used recently (pick_rotating(), the same "not immediately
    repeat" mechanism every other rotation in this project already
    uses) so real comparative data actually starts accumulating instead
    of staying frozen on one approach forever.
    """
    from pipeline.winner_analyzer import approach_performance, classified_rows

    pools = yaml.safe_load(APPROACHES_PATH.read_text(encoding="utf-8"))
    all_approaches = list(pools)

    performance = approach_performance(classified_rows())
    eligible = {a: p for a, p in performance.items() if a in pools and p["count"] >= MIN_APPROACH_SAMPLE}
    if len(eligible) >= 2:
        return max(eligible.items(), key=lambda kv: kv[1]["avg_ratio"])[0]
    # limit=1 (not the size of all_approaches) -- with only 3 approaches
    # total, a larger window would exclude too much of the pool at once;
    # 1 just guarantees no back-to-back repeat, same reasoning as this
    # project's other small-pool rotations (e.g. the CTA variant pool).
    return pick_rotating("current_approach", all_approaches, 1)


def pick_style(approach: str | None = None) -> dict:
    """A hook_opener/script_structure/phrasing_style combination from the
    given (or current) approach's pool, preferring phrases not used in
    the last RECENT_PHRASES_LIMIT videos so the model can't repeat what
    it just used — the actual pick is logged to data/phrase_usage.json
    (via pipeline.rotation) for the next call to read back.
    """
    approach = approach or get_current_approach()
    pools = yaml.safe_load(APPROACHES_PATH.read_text(encoding="utf-8"))
    if approach not in pools:
        raise ValueError(f"unknown approach {approach!r} — expected one of {sorted(pools)}")
    pool = pools[approach]

    return {
        "approach": approach,
        "hook_opener": pick_rotating("hook_openers", pool["hook_openers"], RECENT_PHRASES_LIMIT),
        "script_structure": pick_rotating("script_structures", pool["script_structures"], RECENT_PHRASES_LIMIT),
        "phrasing_style": pick_rotating("phrasing_styles", pool["phrasing_styles"], RECENT_PHRASES_LIMIT),
    }


def style_guidance_block(style: dict) -> str:
    """Formatted for appending directly to an LLM prompt.

    Real, repeated bug this guards against (Phase 17/19, 4 confirmed
    real instances across 2 separate real daily runs, not a one-off):
    hook_openers entries get picked up and inserted near-verbatim, and
    several -- even ones already reviewed and judged "safe" once --
    later failed the authenticity review pass for being generic/
    topic-swappable. A pool of reusable phrases is generic by
    construction; no amount of individually rewording pool entries fully
    fixes that. The real fix is telling the model explicitly not to copy
    one in, every time -- covers the two pools (fast_cuts, deadpan_facts)
    that were never individually audited for this, too.
    """
    return (
        "\n\nSTYLE GUIDANCE FOR THIS VIDEO (vary your writing to actually "
        "match this, not your default pattern):\n"
        f"- Opening line TONE/RHYTHM to match: {style['hook_opener']}\n"
        "  This is a reference for tone and rhythm ONLY -- do not insert "
        "it, or anything close to it, as your actual opening line. Write "
        "an original opening sentence, specific to THIS video's actual "
        "topic, that has a similar feel. Copying it (even lightly "
        "reworded) reads as a generic template line, not something "
        "written for this topic.\n"
        f"- Script structure: {style['script_structure']}\n"
        f"- Phrasing: {style['phrasing_style']}\n"
    )
