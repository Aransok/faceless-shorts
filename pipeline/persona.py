"""Channel persona: loads config/persona.md (the shared, template-agnostic
core) plus a template-specific pet-peeves file, and formats the combined
result for injection into script-generation prompts. See config/persona.md
for the actual voice/tone/honesty rules, and config/persona_pet_peeves_*.md
for the per-template recurring opinions — this module just wires them
together. Recurring opinions are template-specific (Python footguns don't
belong in a sauce-recipe script) so they can't live in one shared file;
splitting them out is also what fixed a real bug where a pet-peeves
example phrase leaked verbatim into a script it didn't belong in.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
PERSONA_PATH = CONFIG_DIR / "persona.md"

# Every template not explicitly listed here fails loudly at prompt-build
# time (missing file) instead of silently getting a mismatched persona.
# programming/facts got their own distinct editorial-identity files
# (Phase 17 narrator-authenticity rewrite — each reads and explains its
# subject differently, not just a shared pet-peeves list with a
# different topic swapped in). quiz_longform/game_night keep the
# original shared "dev" file — out of scope for that rewrite (quiz isn't
# built around persona.py's per-beat voice the same way, and game_night
# is explicitly blocked pending owner feedback, see ROADMAP.md Phase 16).
_PET_PEEVES_FILE = {
    "programming": "persona_pet_peeves_programming.md",
    "facts": "persona_pet_peeves_facts.md",
    "quiz_longform": "persona_pet_peeves_dev.md",
    "sauce_recipe": "persona_pet_peeves_sauce_recipe.md",
    "game_night": "persona_pet_peeves_dev.md",
}


def load_persona(template: str) -> str:
    if template not in _PET_PEEVES_FILE:
        raise ValueError(
            f"no persona pet-peeves file mapped for template {template!r} — "
            f"add one to pipeline/persona.py's _PET_PEEVES_FILE (expected one of "
            f"{sorted(_PET_PEEVES_FILE)})"
        )
    core = PERSONA_PATH.read_text(encoding="utf-8")
    pet_peeves_path = CONFIG_DIR / _PET_PEEVES_FILE[template]
    pet_peeves = pet_peeves_path.read_text(encoding="utf-8")
    return f"{core}\n{pet_peeves}"


def persona_guidance_block(template: str) -> str:
    """Formatted for appending directly to an LLM prompt."""
    return (
        "\n\nCHANNEL PERSONA — write in this specific voice, not a neutral "
        "narrator (full definition, follow it, don't just skim it):\n\n"
        f"{load_persona(template)}\n"
    )
