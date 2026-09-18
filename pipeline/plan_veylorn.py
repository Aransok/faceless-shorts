"""Stage 1 for the veylorn_story format (2026-09-18): the standalone-test
fantasy "keyboard-seek" story, per HANDOFF.md's design log. Generates one
10-beat episode (round_index 0-9, one beat per decile of the final
video's duration -- see pipeline/render_veylorn.py for why the video
must be a fixed total length) via a single LLM call, parses it into
video_steps rows (reusing the same round_index/beat_type columns
game_night's rounds use, keywords for the beat's Pollinations image
prompt, and round_data_json for the two choice beats' on-screen
press-prompt text (2026-09-18 update, real owner feedback that a choice
needs to be visibly announced, not just spoken) -- same "generalized
JSON-ish payload in an existing column" reuse as every other template
here, no schema migration needed).

Not routed through pipeline/review_script.py's authenticity gate -- that
pass exists to catch generic AI phrasing/fabricated PERSONAL experience
in a creator explaining a REAL fact, a different problem from writing
deliberately fictional in-world narration for an original story. Worth
revisiting once this format is more than a one-off test.

Uses call_bulk_llm() (BULK_LLM_BACKEND, default groq), not call_llm() --
a deliberate exception to plan.py's own general rule (every other
template's actual script draft/review/rewrite loop stays on Claude,
since a cheaper model there risks MORE review rejections, i.e. MORE
Claude calls). That rule doesn't apply here: this format has no review/
rewrite loop at all (see above), so there is no retry-cost risk to
guard against -- just a single one-shot generation call, and the
owner's own explicit call (2026-09-18) that this specific format should
run on Groq to keep Claude usage down.
"""

from __future__ import annotations

import json
import re

from pipeline.plan import call_bulk_llm
from pipeline.state import create_video, create_video_steps, get_video, get_video_steps, update_video

TEMPLATE = "veylorn_story"
PROMPT_PATH_NAME = "veylorn_story_template.txt"
EXPECTED_BEAT_COUNT = 10


def _prompt_path():
    from pathlib import Path
    return Path(__file__).resolve().parent.parent / "config" / "prompts" / PROMPT_PATH_NAME


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_episode_response(raw: str) -> dict:
    match = _JSON_BLOCK_RE.search(raw)
    if not match:
        raise ValueError(f"no JSON object found in veylorn_story response:\n{raw}")
    episode = json.loads(match.group(0))

    beats = episode.get("beats")
    if not isinstance(beats, list) or len(beats) != EXPECTED_BEAT_COUNT:
        raise ValueError(f"expected exactly {EXPECTED_BEAT_COUNT} beats, got {len(beats) if isinstance(beats, list) else beats!r}")

    seen_indices = sorted(b.get("round_index") for b in beats)
    if seen_indices != list(range(EXPECTED_BEAT_COUNT)):
        raise ValueError(f"expected round_index 0-{EXPECTED_BEAT_COUNT - 1} exactly once each, got {seen_indices}")

    for beat in beats:
        if not beat.get("narration") or not beat.get("image_prompt"):
            raise ValueError(f"beat {beat.get('round_index')} missing narration or image_prompt: {beat}")

    # Beats 2 and 6 are the two real choice points (see the prompt
    # template's STRUCTURE section) -- their on-screen text is what
    # makes each choice actually visible to a viewer (real owner
    # feedback, 2026-09-18: pressing 7/8/9 didn't feel like a real
    # choice when it was only announced in spoken narration). A missing
    # prompt here means the choice mechanic silently degrades to
    # "unannounced," not a cosmetic gap -- worth failing loudly on.
    by_index = {b["round_index"]: b for b in beats}
    for choice_beat_index in (2, 6):
        if not by_index[choice_beat_index].get("on_screen_prompt"):
            raise ValueError(f"beat {choice_beat_index} (a choice announcement beat) has no on_screen_prompt: {by_index[choice_beat_index]}")

    return episode


def plan_veylorn_story() -> str:
    prompt = _prompt_path().read_text(encoding="utf-8")
    raw = call_bulk_llm(prompt)
    episode = _parse_episode_response(raw)

    beats = sorted(episode["beats"], key=lambda b: b["round_index"])
    steps = [
        {
            "script_text": beat["narration"],
            "keywords": beat["image_prompt"],
            "round_index": beat["round_index"],
            "beat_type": beat["beat_type"],
            "round_data_json": json.dumps({"on_screen_prompt": beat["on_screen_prompt"]}) if beat.get("on_screen_prompt") else None,
        }
        for beat in beats
    ]

    video_id = create_video(TEMPLATE, topic=episode["title"])
    full_script = " ".join(s["script_text"] for s in steps)
    update_video(video_id, status="scripted", script_text=full_script, hook=steps[0]["script_text"])
    create_video_steps(video_id, steps)
    return video_id


if __name__ == "__main__":
    new_id = plan_veylorn_story()
    video = get_video(new_id)
    steps = get_video_steps(new_id)
    print(f"video_id: {new_id}")
    print(f"title:    {video['topic']}")
    for s in steps:
        print(f"  [{s['round_index']}/{s['beat_type']}] {s['script_text']}")
        print(f"      image: {s['keywords']}")
        if s["round_data_json"]:
            print(f"      on_screen_prompt: {json.loads(s['round_data_json'])['on_screen_prompt']!r}")
