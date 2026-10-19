"""LLM-picked doodles: one call per video chooses, per spoken beat, a caption plus 1-2 objects from the hand-drawn kit (mm/lib/doodle_art.js) and a pose."""
from __future__ import annotations

import json
import re
from pathlib import Path

_ART = (Path(__file__).resolve().parent.parent / "mm" / "lib" / "doodle_art.js").read_text(encoding="utf-8")
KIT = tuple(re.findall(r"^    (\w+): '", _ART[:_ART.index("const HEAD")], re.M))
POSES = ("stand", "point", "think", "cheer", "run")

PROMPT = """You pick pictures for a faceless short-video channel in the style of a kid's whiteboard doodle.
Video title: {title}
For EACH numbered line below (one spoken sentence) choose:
- "icons": usually 1 object, 2 only when the sentence names two different things; from this kit that best show what the sentence is ABOUT, main subject first. Use ONLY these exact names: {kit}
  Every icon must literally appear in or clearly illustrate the sentence; never fill with unrelated objects. Prefer the literal subject (candy -> candy, pumpkin -> pumpkin, money/price -> coin or money). Avoid repeating the same first icon on consecutive lines.
- "pose": how the stick figure beside it acts, one of: stand, point, think, cheer, run. Use "none" when the objects alone tell the story (then no figure is drawn).
- "caption": 2 to 5 plain words that sum up the point of the sentence (not a copy of its first words). Spell numbers as words; no digits.
Reply with ONLY a JSON list, one item per line number, in order: [{{"i":1,"icons":["pumpkin"],"pose":"point","caption":"..."}}, ...]

Lines:
{lines}"""


def clean_caption(text: object) -> str:
    words = [w for w in str(text or "").split() if not re.search(r"\d", w)]  # digits trip lint C3
    return re.sub(r"\s+", " ", re.sub(r"[^A-Za-z' ,!?-]", "", " ".join(words))).strip()[:40]


def plan_drawings(sentences: list[str], title: str) -> list[dict | None]:
    """[{icons, pose, caption}|None] aligned to sentences; None where the model gave nothing usable (caller falls back)."""
    from pipeline.plan import call_llm
    lines = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
    try:
        raw = call_llm(PROMPT.format(title=title, kit=" ".join(KIT), lines=lines))
        items, _ = json.JSONDecoder().raw_decode(raw[raw.index("["):])
    except Exception as exc:  # fail soft: the template draws its keyword scene instead
        print(f"[doodle_plan] LLM planning failed: {exc}")
        return [None] * len(sentences)
    by_i = {it.get("i"): it for it in items if isinstance(it, dict)}
    out: list[dict | None] = []
    for i in range(len(sentences)):
        it = by_i.get(i + 1) or {}
        raw_icons = it.get("icons")
        icons = [n for n in (raw_icons if isinstance(raw_icons, list) else []) if n in KIT][:2]
        cap = clean_caption(it.get("caption"))
        if icons and out and out[-1] and len(icons) > 1 and icons[0] == out[-1]["icons"][0]:
            icons.reverse()  # same lead icon twice in a row looks stuck
        out.append({"icons": icons, "pose": it.get("pose") if it.get("pose") in POSES else "none", "caption": cap} if icons and cap else None)
    return out
