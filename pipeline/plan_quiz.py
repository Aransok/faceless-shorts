"""Stage 1 for the quiz longform track (separate from plan.py's two Short
templates — see ROADMAP.md's quiz track section). Same LLM backend, same
persona/CTA-rotation modules as the Shorts pipeline (reused, not
duplicated) — but its own prompt/parsing since the output shape (many
questions with options) doesn't fit plan.py's two existing parsers.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pipeline.cta import cta_guidance_block, pick_cta_angle
from pipeline.persona import persona_guidance_block
from pipeline.plan import call_llm
from pipeline.state import create_video, create_video_steps, get_video, get_video_steps, recent_topics, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = PROJECT_ROOT / "config" / "prompts" / "quiz_template.txt"

TEMPLATE = "quiz_longform"
RECENT_TOPICS_LIMIT = 15
VALID_QUESTION_COUNTS = (8, 9, 10)
_OPTION_LETTERS = ("A", "B", "C", "D")

_STEPS_COUNT_PATTERN = re.compile(r"\bN:\s*(\d+)")


def _parse_quiz_response(text: str) -> dict:
    text = text.strip()

    count_match = _STEPS_COUNT_PATTERN.search(text)
    if not count_match:
        raise ValueError(f"LLM output missing N (question count):\n{text}")
    n = int(count_match.group(1))
    if n not in VALID_QUESTION_COUNTS:
        raise ValueError(f"N must be one of {VALID_QUESTION_COUNTS}, got {n}:\n{text}")

    field_names = ["TOPIC", "HOOK", "N", "INTRO_SCRIPT"]
    for i in range(1, n + 1):
        field_names += [
            f"Q{i}_SCRIPT", f"Q{i}_OPTION_A", f"Q{i}_OPTION_B", f"Q{i}_OPTION_C", f"Q{i}_OPTION_D",
            f"Q{i}_CORRECT", f"Q{i}_REVEAL_SCRIPT",
        ]
    field_names.append("OUTRO_SCRIPT")

    pattern = re.compile(
        r"(?P<label>{names}):\s*(?P<value>.*?)(?=\n(?:{names}):|\Z)".format(
            names="|".join(field_names)
        ),
        re.DOTALL,
    )
    fields = {m.group("label"): m.group("value").strip() for m in pattern.finditer(text)}

    missing = set(field_names) - set(fields)
    if missing:
        raise ValueError(f"LLM output missing required field(s) {sorted(missing)}:\n{text}")

    questions = []
    for i in range(1, n + 1):
        correct_letter = fields[f"Q{i}_CORRECT"].strip().upper()[:1]
        if correct_letter not in _OPTION_LETTERS:
            raise ValueError(f"Q{i}_CORRECT must be A/B/C/D, got {fields[f'Q{i}_CORRECT']!r}")
        questions.append(
            {
                "script_text": fields[f"Q{i}_SCRIPT"],
                "options": [fields[f"Q{i}_OPTION_{letter}"] for letter in _OPTION_LETTERS],
                "correct_index": _OPTION_LETTERS.index(correct_letter),
                "reveal_script": fields[f"Q{i}_REVEAL_SCRIPT"],
            }
        )

    return {
        "topic": fields["TOPIC"],
        "hook": fields["HOOK"],
        "intro_script": fields["INTRO_SCRIPT"],
        "outro_script": fields["OUTRO_SCRIPT"],
        "questions": questions,
    }


def _build_steps(parsed: dict) -> list[dict]:
    steps = [{"script_text": parsed["intro_script"], "card_type": "intro"}]
    for q in parsed["questions"]:
        options_json = json.dumps(q["options"])
        steps.append(
            {
                "script_text": q["script_text"],
                "card_type": "question",
                "options": options_json,
                "correct_index": q["correct_index"],
            }
        )
        steps.append(
            {
                "script_text": q["reveal_script"],
                "card_type": "reveal",
                "options": options_json,
                "correct_index": q["correct_index"],
            }
        )
    steps.append({"script_text": parsed["outro_script"], "card_type": "outro"})
    return steps


def plan_quiz() -> str:
    prompt_body = PROMPT_PATH.read_text(encoding="utf-8")
    avoid = recent_topics(TEMPLATE, limit=RECENT_TOPICS_LIMIT)
    prompt = prompt_body.replace("{avoid_topics}", ", ".join(avoid) if avoid else "(none yet)")
    prompt += persona_guidance_block(TEMPLATE)

    cta_angle = pick_cta_angle()
    prompt += cta_guidance_block(cta_angle) + (
        "\nFor this quiz format specifically: fold the CTA into OUTRO_SCRIPT, "
        "not any individual question.\n"
    )

    raw = call_llm(prompt)
    parsed = _parse_quiz_response(raw)

    video_id = create_video(TEMPLATE, topic=parsed["topic"])
    full_script = " ".join(
        [parsed["intro_script"]]
        + [q["script_text"] for q in parsed["questions"]]
        + [parsed["outro_script"]]
    )
    update_video(
        video_id,
        status="scripted",
        script_text=full_script,
        hook=parsed["hook"],
        cta_angle=cta_angle["name"],
    )
    create_video_steps(video_id, _build_steps(parsed))
    return video_id


if __name__ == "__main__":
    new_id = plan_quiz()
    video = get_video(new_id)
    steps = get_video_steps(new_id)
    print(f"video_id: {new_id}")
    print(f"topic:    {video['topic']}")
    print(f"hook:     {video['hook']}")
    print(f"steps:    {len(steps)} ({sum(1 for s in steps if s['card_type'] == 'question')} questions)")
    for s in steps:
        print(f"\n--- step {s['step_index']} [{s['card_type']}] ---")
        print(f"script: {s['script_text']}")
        if s["options"]:
            options = json.loads(s["options"])
            for i, opt in enumerate(options):
                marker = " <-- correct" if i == s["correct_index"] else ""
                print(f"  {chr(65 + i)}. {opt}{marker}")
