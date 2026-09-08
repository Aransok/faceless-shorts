"""Stage 3 (Phase 6): metadata generation. See SPEC.md."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.plan import call_llm
from pipeline.state import get_video, get_video_steps, list_by_status, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
METADATA_PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "metadata_template.txt"
METADATA_QUIZ_PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "metadata_quiz_template.txt"
METADATA_SAUCE_RECIPE_PROMPT_PATH = (
    PROJECT_ROOT / "config" / "prompts" / "metadata_sauce_recipe_template.txt"
)

load_dotenv(PROJECT_ROOT / ".env")

# YouTube's real hard limits (Data API videos.update / upload), enforced
# as a backstop after the LLM call — not just requested in the prompt.
TITLE_MAX_CHARS = 100
DESCRIPTION_MAX_CHARS = 5000
TAGS_MAX_CHARS = 500

# Our own target (not a YouTube limit): #Shorts + 2-3 broad + 4-5
# specific tags. Enforced by counting actual hashtags in the LLM output
# and truncating, not by trusting the prompt alone to stay under
# YouTube's real 15-hashtag cap (exceeding THAT silently discards every
# hashtag, not just the extras).
HASHTAG_MAX_COUNT = 8
_HASHTAG_PATTERN = re.compile(r"#\w+")

# Real, observed failure (not hypothetical): a generated description
# said "Follow ByteBits" despite the prompt asking for a "subscribe"
# CTA — a soft instruction alone wasn't enough. Backstop the specific
# phrasings an LLM actually produces, same principle as the hashtag cap.
_FOLLOW_PATTERNS = [
    (re.compile(r"\bFollow\s+ByteBits\b"), "Subscribe to ByteBits"),
    (re.compile(r"\bfollow\s+ByteBits\b"), "subscribe to ByteBits"),
    (re.compile(r"\bFollow\s+along\b"), "Subscribe"),
    (re.compile(r"\bfollow\s+along\b"), "subscribe"),
    (re.compile(r"\bFollow\s+us\b"), "Subscribe"),
    (re.compile(r"\bfollow\s+us\b"), "subscribe"),
    (re.compile(r"\bFollow\s+for\s+more\b"), "Subscribe for more"),
    (re.compile(r"\bfollow\s+for\s+more\b"), "subscribe for more"),
]

_FIELD_NAMES = ("TITLE", "DESCRIPTION", "TAGS")
_FIELD_PATTERN = re.compile(
    r"(?P<label>{names}):\s*(?P<value>.*?)(?=\n(?:{names}):|\Z)".format(
        names="|".join(_FIELD_NAMES)
    ),
    re.DOTALL,
)


def _parse_metadata_response(text: str) -> dict:
    text = text.strip()
    fields = {m.group("label"): m.group("value").strip() for m in _FIELD_PATTERN.finditer(text)}
    missing = set(_FIELD_NAMES) - set(fields)
    if missing:
        raise ValueError(f"LLM output missing required field(s) {sorted(missing)}:\n{text}")
    return fields


def _fix_follow_language(description: str) -> str:
    for pattern, replacement in _FOLLOW_PATTERNS:
        description = pattern.sub(replacement, description)
    return description


# Real, observed failure (not hypothetical): a real CI run's description
# contained a genuine em-dash (U+2014) and YouTube's upload API rejected
# the whole video with reason "invalidDescription" over it. Confirmed
# directly against the real failed row: the stored string round-trips
# cleanly through UTF-8 encode/decode with zero control characters, so
# it's not corrupted at rest -- the em-dash itself, once serialized
# through the upload HTTP request pipeline (google-api-python-client /
# whatever's underneath it on this specific CI environment), is what
# YouTube's API is rejecting. Matches this project's own already-
# documented risk class (see docker-and-deployment.md): smart typography
# breaking generated content that flows through a tool whose encoding
# handling you don't fully control -- a generated PDF and a PowerShell
# script hit the identical failure mode earlier in this project, for
# what's very likely a related underlying cause. Same fix: replace with
# plain ASCII rather than trust every consumer down the line to handle
# U+2014 correctly.
_SMART_DASH_PATTERN = re.compile(r"\s*[–—]\s*")  # en dash, em dash (+ any surrounding whitespace)


def _fix_smart_typography(text: str) -> str:
    return _SMART_DASH_PATTERN.sub(" - ", text)


def _cap_hashtags(description: str) -> str:
    matches = list(_HASHTAG_PATTERN.finditer(description))
    if len(matches) <= HASHTAG_MAX_COUNT:
        return description
    # Keep the first HASHTAG_MAX_COUNT hashtags (per the prompt, #Shorts
    # first, then broad, then specific) and drop everything from the
    # next one onward, rather than trust the prompt alone to stay under
    # YouTube's real 15-tag cap.
    cut_from = matches[HASHTAG_MAX_COUNT].start()
    return description[:cut_from].rstrip(" \t,")


def _enforce_limits(title: str, description: str, tags: str) -> tuple[str, str, str]:
    title = _fix_smart_typography(title)
    description = _fix_smart_typography(description)
    tags = _fix_smart_typography(tags)
    if len(title) > TITLE_MAX_CHARS:
        title = title[:TITLE_MAX_CHARS].rsplit(" ", 1)[0].rstrip()
    description = _fix_follow_language(description)
    description = _cap_hashtags(description)
    if len(description) > DESCRIPTION_MAX_CHARS:
        description = description[:DESCRIPTION_MAX_CHARS].rstrip()
    if len(tags) > TAGS_MAX_CHARS:
        # Drop whole tags from the end rather than truncating mid-tag.
        parts = [t.strip() for t in tags.split(",") if t.strip()]
        kept: list[str] = []
        total = 0
        for part in parts:
            added = len(part) + (2 if kept else 0)  # ", " separator
            if total + added > TAGS_MAX_CHARS:
                break
            kept.append(part)
            total += added
        tags = ", ".join(kept)
    return title, description, tags


def _format_sauce_scripts(video_id: str) -> str:
    steps = get_video_steps(video_id)
    return "\n".join(f"Sauce {step['step_index']}: {step['script_text']}" for step in steps)


def generate_metadata(video_id: str) -> dict:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")

    is_quiz = video["template"] == "quiz_longform"
    is_sauce_recipe = video["template"] == "sauce_recipe"
    if is_quiz:
        prompt_path = METADATA_QUIZ_PROMPT_PATH
    elif is_sauce_recipe:
        prompt_path = METADATA_SAUCE_RECIPE_PROMPT_PATH
    else:
        prompt_path = METADATA_PROMPT_PATH
    prompt_body = prompt_path.read_text(encoding="utf-8")
    prompt = (
        prompt_body.replace("{template}", video["template"])
        .replace("{topic}", video["topic"] or "")
        .replace("{hook}", video["hook"] or "")
        .replace("{script_text}", video["script_text"] or "")
    )
    if is_sauce_recipe:
        prompt = prompt.replace("{sauce_scripts}", _format_sauce_scripts(video_id))

    raw = call_llm(prompt)
    parsed = _parse_metadata_response(raw)
    title, description, tags = _enforce_limits(
        parsed["TITLE"], parsed["DESCRIPTION"], parsed["TAGS"]
    )

    require_review = os.environ.get("REQUIRE_REVIEW", "true").lower() == "true"
    next_status = "awaiting_review" if require_review else "approved"

    # "Genome" tags -- capture only, nothing reads these yet (see
    # ROADMAP.md). Computed here since every step's real duration is
    # already final by this stage. genome_hook_style/concept_type mirror
    # approach/template (the real distinctions that already exist);
    # item_count and visual_density (avg seconds per beat -- lower means
    # faster cuts) are real numbers, not guesses.
    steps = get_video_steps(video_id)
    item_count = len(steps)
    total_duration = sum(s["duration"] or 0.0 for s in steps)
    visual_density = round(total_duration / item_count, 2) if item_count else None

    update_video(
        video_id,
        status=next_status,
        title=title,
        description=description,
        tags=tags,
        genome_hook_style=video["approach"],
        genome_concept_type=video["template"],
        genome_item_count=item_count,
        genome_visual_density=visual_density,
    )
    return {"title": title, "description": description, "tags": tags, "status": next_status}


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        captioned = list_by_status("captioned")
        if not captioned:
            raise SystemExit("no captioned videos in state.db — run captions.py first")
        video_id_arg = captioned[0]["id"]

    result = generate_metadata(video_id_arg)
    video = get_video(video_id_arg)
    print(f"video_id:    {video_id_arg}")
    print(f"approach:    {video['approach']}")
    print(f"status:      {result['status']}")
    print(f"title:       {result['title']}  ({len(result['title'])} chars)")
    print(f"description: {len(result['description'])} chars")
    print(result["description"])
    print(f"tags:        {len(result['tags'])} chars")
    print(result["tags"])
