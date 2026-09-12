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
from pipeline.review_script import review_script
from pipeline.state import (
    create_video,
    create_video_steps,
    get_video,
    get_video_steps,
    recent_beats,
    recent_cta_types,
    recent_topics,
    update_video,
)

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

# Phase 17: authenticity review pass (pipeline/review_script.py). Up to
# this many rewrite attempts after the first draft before giving up and
# raising -- caught by orchestrator.run_daily()'s existing try/except
# around plan(), same as any other plan() failure (this template's slot
# is skipped for this run, others continue).
#
# Phase 19, real cost problem (2026-09-09): this was raised 2 -> 4 in
# Phase 17 to fix a convergence problem, but the real cost of a full
# review/rewrite round trip is TWO LLM calls (a review call + a rewrite
# generation call), so budget=4 means up to 5 generation + 5 review = 10
# real calls for a single video -- and when a video fails outright
# (exhausts the budget without ever passing), every one of those calls
# was wasted, zero video produced. The very first real daily run after
# shipping budget=4 hit exactly this: 2 of 5 videos in one run exhausted
# all 4 rewrites and failed completely, and the owner reported hitting
# ~98% of the day's Claude usage limit from this run alone. Cut back to
# 1 -- worst case now 2 generation + 2 review = 4 calls, 60% less than
# budget=4's worst case, and a bounded failure costs far less. This
# trades some convergence rate for cost -- real data so far suggests a
# script that's still rejected after one real rewrite attempt (using the
# reviewer's own specific feedback) is not obviously about to converge
# on a second or third attempt either, so the extra budget was mostly
# buying failed videos at 2-3x the cost, not more successful ones.
REVIEW_MAX_REWRITES = 1

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


class ClaudeUsageLimitError(RuntimeError):
    """The claude CLI call failed specifically because the account's
    usage limit was reached — distinct from any other CLI failure (bad
    prompt, CLI not installed, transient crash) so call_llm() can fall
    back to a free backend ONLY for this one specific, recoverable
    condition instead of masking a real bug behind a lower-quality
    fallback response."""


# Matched against combined stdout+stderr of a failed claude CLI call.
# Confirmed wording (2026-09) is "Claude AI usage limit reached" / "usage
# limit reached", but matching the broader "usage limit" substring (and
# "rate limit" for the API-key auth path, which phrases it differently)
# is deliberately looser so a minor wording change upstream doesn't
# silently stop the fallback from ever triggering.
_USAGE_LIMIT_PATTERN = re.compile(r"usage limit|rate.?limit exceeded", re.IGNORECASE)


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
        # 240s, not 120 -- the Phase 17 review/rewrite loop
        # (_build_rewrite_prompt) concatenates the original prompt +
        # previous draft + reviewer feedback into one call, real and
        # meaningfully bigger than a bare generation prompt. Confirmed
        # for real: a rewrite call hit the old 120s ceiling and raised
        # subprocess.TimeoutExpired, killing plan() entirely.
        timeout=240,
        shell=(os.name == "nt"),
    )
    if result.returncode != 0:
        combined_output = f"{result.stdout}\n{result.stderr}"
        if _USAGE_LIMIT_PATTERN.search(combined_output):
            raise ClaudeUsageLimitError(f"claude CLI usage limit reached: {combined_output.strip()[:500]}")
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


def _call_groq(prompt: str) -> str:
    """Groq's free-tier API (no credit card, rate-limited but genuinely
    free — see CLAUDE.md's "no paid APIs by default" rule) serving open
    Llama models. Used as the automatic fallback when LLM_FALLBACK_BACKEND
    is set and the primary backend hits ClaudeUsageLimitError, since
    ollama needs a locally-running model server this project's CI runner
    doesn't have, but Groq is a plain hosted HTTPS API."""
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set — required for LLM_BACKEND/LLM_FALLBACK_BACKEND=groq")
    model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    response = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "messages": [{"role": "user", "content": prompt}]},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def _dispatch_llm(backend: str, prompt: str) -> str:
    if backend == "claude_code":
        return _call_claude_code(prompt)
    if backend == "ollama":
        return _call_ollama(prompt)
    if backend == "groq":
        return _call_groq(prompt)
    raise ValueError(f"unknown LLM backend: {backend!r} (expected 'claude_code', 'ollama', or 'groq')")


def call_llm(prompt: str) -> str:
    """Dispatches to LLM_BACKEND (default claude_code). When the primary
    backend is claude_code and it fails specifically because the account's
    usage limit was hit, and LLM_FALLBACK_BACKEND names a different
    backend, retries this one call on the fallback instead of failing the
    whole video — a usage-limit day shouldn't mean zero videos produced
    when a free backend could still generate them. Any other failure
    (bad prompt, CLI missing, transient crash) is NOT treated as
    fallback-eligible: only the usage-limit condition is a "this backend
    is exhausted for today" signal, not "this backend is broken"."""
    backend = os.environ.get("LLM_BACKEND", "claude_code")
    try:
        return _dispatch_llm(backend, prompt)
    except ClaudeUsageLimitError as exc:
        fallback = os.environ.get("LLM_FALLBACK_BACKEND", "").strip()
        if not fallback or fallback == backend:
            raise
        print(f"warning: {exc} -- falling back to LLM_FALLBACK_BACKEND={fallback!r} for this call")
        return _dispatch_llm(fallback, prompt)


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


def _parse_response(template: str, raw: str) -> dict:
    if template == "programming":
        return _parse_programming_response(raw)
    return _parse_facts_response(raw)


def _extract_narration(template: str, parsed: dict) -> str:
    """Plain spoken-narration text for the review pass -- hook + each
    beat's script_text only, no field labels/code/keywords, since those
    would just confuse a reviewer checking whether narration sounds
    authentic."""
    if template == "programming":
        lines = [parsed["hook"]] + [step["script_text"] for step in parsed["steps"]]
    else:
        lines = [parsed["hook"]] + [fact["script_text"] for fact in parsed["facts"]]
    return "\n".join(lines)


def _build_rewrite_prompt(original_prompt: str, previous_raw: str, feedback: str) -> str:
    return (
        f"{original_prompt}\n\n"
        "--- PREVIOUS DRAFT (REJECTED ON AUTHENTICITY REVIEW) ---\n"
        f"{previous_raw}\n\n"
        "--- REVIEWER FEEDBACK ---\n"
        f"{feedback}\n\n"
        "Rewrite the script from scratch, fixing every problem listed above. "
        "Output ONLY the corrected script in the exact same field format "
        "given in the instructions above -- no extra commentary before or after."
    )


def _generate_reviewed(template: str, prompt: str) -> dict:
    """Generates a script, runs it through the authenticity review pass
    (pipeline/review_script.py), and rewrites (feeding the reviewer's own
    feedback back to the LLM) up to REVIEW_MAX_REWRITES times until it's
    approved. Raises if it's still rejected after the last attempt --
    caught by the caller's normal fail-soft handling, same as a
    malformed-output ValueError from the parser."""
    raw = call_llm(prompt)
    parsed = _parse_response(template, raw)
    attempts = 0
    while True:
        review = review_script(_extract_narration(template, parsed), call_llm)
        if review["approved"]:
            return parsed
        attempts += 1
        if attempts > REVIEW_MAX_REWRITES:
            raise RuntimeError(
                f"script for template {template!r} failed authenticity review "
                f"after {REVIEW_MAX_REWRITES} rewrite attempt(s):\n{review['feedback']}"
            )
        raw = call_llm(_build_rewrite_prompt(prompt, raw, review["feedback"]))
        parsed = _parse_response(template, raw)


def _topic_hint_block(topic_hint: str) -> str:
    """Appended when a caller (run_daily(), ultimately a manual
    workflow_dispatch input) wants to steer today's video onto a specific
    real subject -- e.g. a genuinely verified trending topic researched
    ahead of time. Deliberately a DIRECTION, not text to insert verbatim:
    the same "never hand the LLM a literal copyable phrase" lesson this
    project has re-learned several times (cta.py, approaches.yaml) --
    the model still writes its own narration in its own voice, and it
    still goes through the full authenticity review pass below (this
    function runs before _generate_reviewed(), not instead of it).
    """
    return (
        "\n\nREQUIRED TOPIC FOR THIS VIDEO -- do not pick a different "
        "subject; this is today's real subject and angle, researched and "
        "verified ahead of time:\n"
        f"{topic_hint}\n\n"
        "Write it in your own voice, per the persona/style rules below -- "
        "this is the real subject to cover, not a script to copy. Only "
        "state facts you can actually stand behind; if any specific "
        "number/stat mentioned above isn't something you're confident is "
        "accurate, leave it out rather than repeating it unverified.\n"
    )


def plan(template: str, topic_hint: str | None = None) -> str:
    if template not in TEMPLATES:
        raise ValueError(f"unknown template: {template!r} (expected {sorted(TEMPLATES)})")

    prompt_body = TEMPLATES[template].read_text(encoding="utf-8")
    avoid = recent_topics(template, limit=RECENT_TOPICS_LIMIT)
    prompt = prompt_body.replace("{avoid_topics}", ", ".join(avoid) if avoid else "(none yet)")
    # facts/sauce_recipe are both 3-item-per-video templates -- see
    # recent_beats()'s docstring for the real overlap bug (two
    # consecutive sauce_recipe videos both independently picking
    # chimichurri) this closes.
    _AVOID_BEATS_PLACEHOLDER = {"facts": "{avoid_facts}", "sauce_recipe": "{avoid_sauces}"}
    if template in _AVOID_BEATS_PLACEHOLDER:
        avoid_beats = recent_beats(template, limit_videos=RECENT_TOPICS_LIMIT)
        prompt = prompt.replace(
            _AVOID_BEATS_PLACEHOLDER[template],
            "; ".join(avoid_beats) if avoid_beats else "(none yet)",
        )

    if topic_hint:
        prompt += _topic_hint_block(topic_hint)

    style = pick_style()
    prompt += style_guidance_block(style)
    prompt += persona_guidance_block(template)

    pending = get_pending_announcement()
    milestone_line = format_milestone_line(*pending) if pending else None
    last_cta_type = next(iter(recent_cta_types(limit=1)), None)
    cta_angle = pick_cta_angle(milestone_line, last_cta_type=last_cta_type)
    prompt += cta_guidance_block(cta_angle, template, milestone_line)

    parsed = _generate_reviewed(template, prompt)

    if template == "programming":
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
