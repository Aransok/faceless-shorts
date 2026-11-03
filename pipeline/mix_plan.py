"""Stage 1 for the mix templates (mix_food, mix_facts), 2026-11-02 owner
decision: replace the daily voiced shorts with the "mix" style approved
from the openmontage trial -- big text over real Commons footage/photos,
counters and icon grids, synthesized score, no voiceover.

One call_llm() writes a scene spec (JSON); this module validates and
cleans it, adds a per-video palette/tempo picked from the video_id, and
stores it in videos.mix_spec. pipeline/mix_render.py turns it into the
final mp4.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from pipeline.mix_render import ICONS
from pipeline.plan import _research_seed_block, _topic_hint_block, call_llm
from pipeline.state import create_video, get_video, recent_topics, update_video

PROMPT_PATH = Path(__file__).resolve().parent.parent / "config" / "prompts" / "mix_template.txt"

LANES = {
    "mix_food": "Kitchen science and food: why food does what it does, where foods come from, "
                "surprising cooking tricks that really work.",
    "mix_facts": "Amazing true facts about animals, nature, space, the human body and history.",
}
# research.py keeps a separate used-candidate slot per old template
RESEARCH_SLOT = {"mix_food": "food", "mix_facts": "facts"}

END_HEADLINE = "Follow for<br>one more <b>a day.</b>"

# (bg, ink, mute, acc, acc2). Light and dark grounds; acc must read on bg.
PALETTES = (
    ("#f4efe6", "#1d1b19", "#8a8378", "#e8572a", "#ffb38f"),
    ("#f4efe6", "#1d1b19", "#8a8378", "#2a6fe8", "#9fc2ff"),
    ("#e8f3ee", "#14211b", "#6f8579", "#0f9a63", "#8fe0bd"),
    ("#fbf3d5", "#221d10", "#8c8466", "#d9480f", "#ffc078"),
    ("#fbeae6", "#2a1715", "#8f7470", "#d6336c", "#ffa8c5"),
    ("#141414", "#f5f1e8", "#8d877c", "#ffc93c", "#fff0b3"),
    ("#0f1b2d", "#eef2f7", "#8393a8", "#ff6b5a", "#ffc2b8"),
    ("#11231b", "#eef5ea", "#86a091", "#b7e34a", "#e3f7b0"),
    ("#1e1430", "#f4effa", "#9a8fb0", "#2ed3b7", "#a8f0e3"),
)
BPMS = (92, 100, 108, 116)
CHORD_SETS = (
    [(261.6, 329.6, 392.0, 523.3), (220.0, 261.6, 329.6, 440.0), (174.6, 220.0, 261.6, 349.2), (196.0, 246.9, 293.7, 392.0)],
    [(220.0, 261.6, 329.6, 440.0), (174.6, 220.0, 261.6, 349.2), (261.6, 329.6, 392.0, 523.3), (196.0, 246.9, 293.7, 392.0)],
    [(293.7, 349.2, 440.0, 587.3), (233.1, 293.7, 349.2, 466.2), (261.6, 329.6, 392.0, 523.3), (220.0, 277.2, 329.6, 440.0)],
    [(196.0, 246.9, 293.7, 392.0), (164.8, 196.0, 246.9, 329.6), (261.6, 329.6, 392.0, 523.3), (293.7, 370.0, 440.0, 587.3)],
)

DUR_RANGE = {"card": (3.5, 5.0), "counter": (4.0, 4.5), "grid": (4.5, 5.0), "end": (2.5, 3.0)}
TOTAL_RANGE = (18.0, 32.0)
_ALLOWED_TAG = re.compile(r"<(?!/?(?:b|i)>|br\s*/?>)[^>]*>")


def style_for(video_id: str) -> dict:
    """Deterministic look per video: same id, same palette/tempo/chords."""
    h = int(hashlib.sha256(video_id.encode()).hexdigest(), 16)
    bg, ink, mute, acc, acc2 = PALETTES[h % len(PALETTES)]
    return {"bg": bg, "ink": ink, "mute": mute, "acc": acc, "acc2": acc2,
            "bpm": BPMS[(h >> 8) % len(BPMS)], "chords": CHORD_SETS[(h >> 16) % len(CHORD_SETS)],
            "seed": (h >> 24) % 10_000}


def clean_text(s: object, limit: int = 120) -> str:
    """Keep only <b>, <i>, <br>; force ASCII; cap length."""
    text = _ALLOWED_TAG.sub("", str(s or "")).replace("—", ", ").replace("–", "-")
    text = text.encode("ascii", "ignore").decode().strip()
    return text[:limit]


def plain(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<br\s*/?>", " ", re.sub(r"</?[bi]>", "", s))).strip()


def _clamp(v: object, lo: float, hi: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        x = lo
    return round(min(hi, max(lo, x)), 2)


def validate_spec(raw: dict) -> dict:
    """LLM spec -> clean spec, or ValueError. Pure logic, tested."""
    scenes_in = raw.get("scenes")
    if not isinstance(scenes_in, list) or not 4 <= len(scenes_in) <= 8:
        raise ValueError(f"need 4-8 scenes, got {scenes_in!r:.200}")
    if scenes_in[0].get("type") != "card":
        raise ValueError("first scene must be a card")
    scenes = []
    for i, s in enumerate(scenes_in):
        typ = s.get("type")
        if typ not in DUR_RANGE:
            raise ValueError(f"scene {i}: unknown type {typ!r}")
        if typ == "end" and i != len(scenes_in) - 1:
            raise ValueError("end scene must be last")
        out = {"type": typ, "dur": _clamp(s.get("dur"), *DUR_RANGE[typ])}
        if typ != "end":
            out["h"] = clean_text(s.get("h"))
            if not out["h"]:
                raise ValueError(f"scene {i}: empty headline")
        if s.get("body"):
            out["body"] = clean_text(s["body"])
        if s.get("say"):
            out["say"] = plain(clean_text(s["say"], 200))
        if typ == "card":
            m = s.get("media") or {}
            query = clean_text(m.get("query"), 60)
            query = re.sub(r"<[^>]*>", "", query)
            if not query:
                raise ValueError(f"scene {i}: card has no media query")
            out["media"] = {"query": query, "kind": "video" if m.get("kind") == "video" else "image",
                            "start": _clamp(m.get("start", 0), 0, 600)}
            if s.get("chip"):
                out["chip"] = clean_text(s["chip"], 60)
            stats = s.get("stats")
            if isinstance(stats, list) and stats:
                out["stats"] = [[clean_text(v, 6), clean_text(lab, 40)] for v, lab in stats[:2]]
                out.pop("body", None)
        elif typ == "counter":
            out["icon"] = s.get("icon") if s.get("icon") in ICONS else "star"
            try:
                out["to"] = float(s["to"])
            except (KeyError, TypeError, ValueError):
                raise ValueError(f"scene {i}: counter needs a number 'to'")
            out["decimals"] = int(s.get("decimals") or 0) if 0 <= int(s.get("decimals") or 0) <= 2 else 0
            out["unit"] = clean_text(s.get("unit"), 24)
        elif typ == "grid":
            n = int(s.get("count") or 0)
            if not 2 <= n <= 120:
                raise ValueError(f"scene {i}: grid count {n} out of 2-120")
            out["count"] = n
            out["shape"] = s.get("shape") if s.get("shape") in ICONS else "star"
            if n <= 12:
                labels = [clean_text(x, 16) for x in (s.get("labels") or [])][:n]
                out["labels"] = labels + [""] * (n - len(labels))
            flip = s.get("flip")
            if isinstance(flip, list):
                out["flip"] = sorted({int(j) for j in flip if isinstance(j, int) and 0 <= j < n})
        else:
            out["h"] = END_HEADLINE
            out["icon"] = s.get("icon") if s.get("icon") in ICONS else "heart"
        scenes.append(out)
    if scenes[-1]["type"] != "end":
        scenes.append({"type": "end", "dur": 2.5, "h": END_HEADLINE, "icon": "heart"})
    total = sum(s["dur"] for s in scenes)
    if not TOTAL_RANGE[0] <= total <= TOTAL_RANGE[1]:
        raise ValueError(f"total {total:.1f}s outside {TOTAL_RANGE}")
    kicker = plain(clean_text(raw.get("kicker"), 30)).upper() or "DID YOU KNOW"
    return {"topic": plain(clean_text(raw.get("topic"), 80)), "hook": plain(clean_text(raw.get("hook"), 200)),
            "kicker": kicker, "scenes": scenes}


def script_text(spec: dict) -> str:
    """Plain on-screen text in order -- feeds metadata like a narration would."""
    parts = []
    for s in spec["scenes"]:
        if s["type"] == "end":
            continue
        line = plain(s["h"])
        if s["type"] == "counter":
            line += f" {s['to']:.{s['decimals']}f} {plain(s['unit'])}"
        if s.get("body"):
            line += ". " + plain(s["body"])
        for v, lab in s.get("stats", []):
            line += f". {plain(v)} {plain(lab)}"
        parts.append(line.rstrip(".") + ".")
    return " ".join(parts)


def build_prompt(template: str, topic_hint: str | None, research_seed: str | None) -> str:
    recent = recent_topics(template) or ["(none yet)"]
    return (PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{lane}", LANES[template])
            .replace("{topic_hint}", _topic_hint_block(topic_hint) if topic_hint else "")
            .replace("{research_seed}", _research_seed_block(research_seed) if research_seed else "")
            .replace("{recent_topics}", "\n".join(f"- {t}" for t in recent))
            .replace("{icons}", ", ".join(sorted(ICONS))))


def _parse(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in mix response:\n{raw[:500]}")
    return json.loads(m.group(0))


def plan_mix(template: str, topic_hint: str | None = None, research_seed: str | None = None) -> str:
    if template not in LANES:
        raise ValueError(f"unknown mix template {template!r}")
    prompt = build_prompt(template, topic_hint, research_seed)
    try:
        spec = validate_spec(_parse(call_llm(prompt)))
    except (ValueError, json.JSONDecodeError) as exc:  # one retry: LLM JSON slips are usually one-offs
        print(f"mix spec rejected ({exc}); retrying once")
        spec = validate_spec(_parse(call_llm(prompt + f"\n\nYour last reply was rejected: {exc}. Follow the rules exactly.")))
    video_id = create_video(template, topic=spec["topic"] or None)
    spec["id"] = video_id
    spec["style"] = style_for(video_id)
    update_video(video_id, status="scripted", hook=spec["hook"], script_text=script_text(spec),
                 mix_spec=json.dumps(spec))
    return video_id


if __name__ == "__main__":
    tpl = sys.argv[1] if len(sys.argv) > 1 else "mix_facts"
    vid = plan_mix(tpl)
    v = get_video(vid)
    print(f"video_id: {vid}\ntopic: {v['topic']}\nscript: {v['script_text']}")
    print(json.dumps(json.loads(v["mix_spec"]), indent=2))
