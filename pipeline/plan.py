"""Stage 1: plan & script generation. See SPEC.md."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

from pipeline.approaches import pick_style, style_guidance_block
from pipeline.cta import cta_guidance_block, pick_cta_angle
from pipeline.milestones import format_milestone_line, get_pending_announcement, mark_milestone_announced
from pipeline.persona import persona_guidance_block
from pipeline.state import create_video, create_video_steps, get_video, get_video_steps, recent_topics, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = PROJECT_ROOT / "config" / "prompts"

load_dotenv(PROJECT_ROOT / ".env")

TEMPLATES = {
    "programming": PROMPTS_DIR / "programming_template.txt",
    "facts": PROMPTS_DIR / "facts_template.txt",
    # Structurally identical to "facts" (3 beats, each script_text +
    # keywords) -- the prompt content is sauces instead of trivia, but it
    # flows through the exact same _parse_facts_response() below and the
    # exact same visuals_facts.py B-roll pipeline. See ROADMAP.md.
    "sauce_recipe": PROMPTS_DIR / "sauce_recipe_template.txt",
}

RECENT_TOPICS_LIMIT = 15
VALID_STEP_COUNTS = (2, 3, 4)

# facts_template.txt output is always exactly 3 fact beats (fixed count,
# unlike programming's variable STEPS). Each beat's visual fields are the
# tiered exact/representation/concept query lists (Visual Director
# upgrade) instead of one flat KEYWORDS list -- see
# visuals_facts.py's _parse_beat_visual_plan().
_FACT_VISUAL_SUFFIXES = ("SUBJECT", "EXACT_QUERIES", "REPRESENTATION_QUERIES", "CONCEPT_QUERIES")
_FACTS_FIELD_NAMES = (
    "TOPIC", "HOOK",
    *(f"FACT_{i}_{suffix}" for i in (1, 2, 3) for suffix in ("SCRIPT", *_FACT_VISUAL_SUFFIXES)),
)
_FACTS_FIELD_PATTERN = re.compile(
    r"(?P<label>{names}):\s*(?P<value>.*?)(?=\n(?:{names}):|\Z)".format(
        names="|".join(_FACTS_FIELD_NAMES)
    ),
    re.DOTALL,
)

_STEPS_COUNT_PATTERN = re.compile(r"STEPS:\s*(\d+)")


def _call_claude_code(prompt: str) -> str:
    claude_path = shutil.which("claude")
    if claude_path is None:
        raise RuntimeError("claude CLI not found on PATH")
    # On Windows the global npm shim is a .cmd, which CreateProcess can't
    # launch directly without a shell — and the prompt goes via stdin
    # rather than argv so shell quoting never touches untrusted text.
    result = subprocess.run(
        [claude_path, "-p"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        shell=(os.name == "nt"),
    )
    if result.returncode != 0:
        raise RuntimeError(f"claude CLI failed (exit {result.returncode}): {result.stderr}")
    return result.stdout


def _call_ollama(prompt: str) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b-instruct")
    response = requests.post(
        f"{host}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["response"]


def call_llm(prompt: str) -> str:
    backend = os.environ.get("LLM_BACKEND", "claude_code")
    if backend == "claude_code":
        return _call_claude_code(prompt)
    if backend == "ollama":
        return _call_ollama(prompt)
    raise ValueError(f"unknown LLM_BACKEND: {backend!r} (expected 'claude_code' or 'ollama')")


def _split_queries(raw: str) -> list[str]:
    """Comma-split a query field, treating a literal "none" (the prompt's
    documented way to say "no concept queries needed") as empty rather
    than a real search term."""
    if raw.strip().lower() == "none":
        return []
    return [q.strip() for q in raw.split(",") if q.strip()]


def _parse_facts_response(text: str) -> dict:
    text = text.strip()
    fields = {
        m.group("label"): m.group("value").strip() for m in _FACTS_FIELD_PATTERN.finditer(text)
    }
    missing = set(_FACTS_FIELD_NAMES) - set(fields)
    if missing:
        raise ValueError(f"LLM output missing required field(s) {sorted(missing)}:\n{text}")

    # keywords stores the tiered visual plan as JSON (same TEXT column as
    # the old flat comma list -- no schema migration needed). See
    # visuals_facts.py's _parse_beat_visual_plan() for the reader side,
    # which also accepts the old flat-comma format for any in-flight
    # video that was planned before this change.
    facts = [
        {
            "script_text": fields[f"FACT_{i}_SCRIPT"],
            "keywords": json.dumps(
                {
                    "subject": fields[f"FACT_{i}_SUBJECT"],
                    "exact": _split_queries(fields[f"FACT_{i}_EXACT_QUERIES"]),
                    "representation": _split_queries(fields[f"FACT_{i}_REPRESENTATION_QUERIES"]),
                    "concept": _split_queries(fields[f"FACT_{i}_CONCEPT_QUERIES"]),
                }
            ),
        }
        for i in (1, 2, 3)
    ]
    return {"topic": fields["TOPIC"], "hook": fields["HOOK"], "facts": facts}


def _parse_programming_response(text: str) -> dict:
    text = text.strip()

    count_match = _STEPS_COUNT_PATTERN.search(text)
    if not count_match:
        raise ValueError(f"LLM output missing STEPS count:\n{text}")
    step_count = int(count_match.group(1))
    if step_count not in VALID_STEP_COUNTS:
        raise ValueError(f"STEPS must be one of {VALID_STEP_COUNTS}, got {step_count}:\n{text}")

    field_names = ["TOPIC", "HOOK", "LANGUAGE", "STEPS"]
    for i in range(1, step_count + 1):
        field_names += [f"STEP_{i}_SCRIPT", f"STEP_{i}_CODE", f"STEP_{i}_OUTPUT"]

    pattern = re.compile(
        r"(?P<label>{names}):\s*(?P<value>.*?)(?=\n(?:{names}):|\Z)".format(
            names="|".join(field_names)
        ),
        re.DOTALL,
    )
    fields = {m.group("label"): m.group("value").strip() for m in pattern.finditer(text)}

    required = {"TOPIC", "HOOK", "LANGUAGE"} | {f"STEP_{i}_SCRIPT" for i in range(1, step_count + 1)}
    missing = required - set(fields)
    if missing:
        raise ValueError(f"LLM output missing required field(s) {sorted(missing)}:\n{text}")

    steps = []
    for i in range(1, step_count + 1):
        code = fields.get(f"STEP_{i}_CODE") or None
        output = fields.get(f"STEP_{i}_OUTPUT") or None
        if output and output.strip().lower() in ("(none)", "none"):
            output = None
        steps.append(
            {
                "script_text": fields[f"STEP_{i}_SCRIPT"],
                "code_snippet": code,
                "output_text": output,
            }
        )

    return {
        "topic": fields["TOPIC"],
        "hook": fields["HOOK"],
        "language": fields["LANGUAGE"],
        "steps": steps,
    }


def plan(template: str) -> str:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template: {template!r} (expected {sorted(TEMPLATES)})")

    prompt_body = TEMPLATES[template].read_text(encoding="utf-8")
    avoid = recent_topics(template, limit=RECENT_TOPICS_LIMIT)
    prompt = prompt_body.replace("{avoid_topics}", ", ".join(avoid) if avoid else "(none yet)")

    style = pick_style()
    prompt += style_guidance_block(style)
    prompt += persona_guidance_block(template)

    pending = get_pending_announcement()
    milestone_line = format_milestone_line(*pending) if pending else None
    cta_angle = pick_cta_angle(milestone_line)
    prompt += cta_guidance_block(cta_angle, milestone_line)

    raw = call_llm(prompt)

    if template == "programming":
        parsed = _parse_programming_response(raw)
        video_id = create_video(template, topic=parsed["topic"])
        full_script = " ".join(step["script_text"] for step in parsed["steps"])
        update_video(
            video_id,
            status="scripted",
            script_text=full_script,
            code_snippet=parsed["steps"][-1]["code_snippet"],
            language=parsed["language"],
            hook=parsed["hook"],
            approach=style["approach"],
            cta_angle=cta_angle["name"],
            hook_opener_used=style["hook_opener"],
        )
        create_video_steps(video_id, parsed["steps"])
    else:
        parsed = _parse_facts_response(raw)
        video_id = create_video(template, topic=parsed["topic"])
        full_script = " ".join(fact["script_text"] for fact in parsed["facts"])
        update_video(
            video_id,
            status="scripted",
            script_text=full_script,
            hook=parsed["hook"],
            approach=style["approach"],
            cta_angle=cta_angle["name"],
            hook_opener_used=style["hook_opener"],
        )
        create_video_steps(video_id, parsed["facts"])

    if pending:
        mark_milestone_announced(*pending)
    return video_id


if __name__ == "__main__":
    template_arg = sys.argv[1] if len(sys.argv) > 1 else "programming"
    new_id = plan(template_arg)
    video = get_video(new_id)
    word_count = len(video["script_text"].split())
    print(f"template: {template_arg}")
    print(f"topic:    {video['topic']}")
    print(f"hook:     {video['hook']}")
    print(f"words:    {word_count}")

    steps = get_video_steps(new_id)
    if steps:
        if video["language"]:
            print(f"language: {video['language']}")
        print(f"({len(steps)} beats)")
        for step in steps:
            print(f"\n--- beat {step['step_index']} ---")
            print(f"script: {step['script_text']}")
            if step["code_snippet"]:
                print(f"code:\n{step['code_snippet']}")
            if step["output_text"]:
                print(f"output: {step['output_text']}")
            if step["keywords"]:
                print(f"keywords: {step['keywords']}")
    else:
        print(f"script:\n{video['script_text']}")
