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
    """Formatted for appending directly to an LLM prompt."""
    return (
        "\n\nSTYLE GUIDANCE FOR THIS VIDEO (vary your writing to actually "
        "match this, not your default pattern):\n"
        f"- Opening line style: {style['hook_opener']}\n"
        f"- Script structure: {style['script_structure']}\n"
        f"- Phrasing: {style['phrasing_style']}\n"
    )
