"""Pure-logic builders: video_steps rows -> JSON spec for the motionmaxxing
templates (chef / facts / code). No network, no rendering, so it is unit-testable.

Step rows are dicts with: script_text, duration, code_snippet, output_text and
optionally `words` (list of {word,start,end} relative to the step start).
"""
from __future__ import annotations

import html as _html
import re

ACCENTS = {"facts": "#e8542e", "code": "#ffb454", "chef": "#e8542e"}
PAUSE = 3.5  # mirrors voice.BEAT_PAUSE_SECONDS for paused templates

# ---------------------------------------------------------------- chef
# name -> (color, kind) ; kind: liquid -> pour, oil -> drizzle, dry -> sprinkle
INGREDIENTS: dict[str, tuple[str, str]] = {
    "olive oil": ("#c9a227", "oil"), "oil": ("#c9a227", "oil"), "butter": ("#f2d36b", "liquid"),
    "cream": ("#f4ead2", "liquid"), "milk": ("#f8f6f0", "liquid"), "vinegar": ("#d9b25f", "liquid"),
    "wine": ("#8a2a3b", "liquid"), "water": ("#cfe7f2", "liquid"), "stock": ("#c98a3c", "liquid"),
    "broth": ("#c98a3c", "liquid"), "soy": ("#3b2418", "liquid"), "honey": ("#e0a21b", "oil"),
    "lime": ("#a8c93a", "liquid"), "lemon": ("#f2e04a", "liquid"), "mustard": ("#d8b92a", "liquid"),
    "mayo": ("#f3ead0", "liquid"), "yogurt": ("#f6f3ea", "liquid"), "tomato": ("#d9402b", "liquid"),
    "salt": ("#f4f4f0", "dry"), "sugar": ("#fbfaf5", "dry"), "pepper": ("#3a3330", "dry"),
    "garlic": ("#f3e3b0", "dry"), "onion": ("#e8d3e0", "dry"), "cilantro": ("#4f8f3a", "dry"),
    "thyme": ("#6b8f4a", "dry"), "basil": ("#3f7f3a", "dry"), "parsley": ("#4f9a3a", "dry"),
    "chili": ("#c92d1f", "dry"), "paprika": ("#c0451f", "dry"), "cheese": ("#f0c64a", "dry"),
    "ginger": ("#e6c47a", "dry"), "cumin": ("#a9772f", "dry"), "oregano": ("#5f8a3a", "dry"),
    "flour": ("#f7f1e3", "dry"), "herbs": ("#5f9a3a", "dry"),
}
_SINGLE = [k for k in INGREDIENTS if " " not in k]
DEFAULT_COLOR = "#c9a227"
_ACTION_FOR = {"oil": "drizzle", "liquid": "pour", "dry": "sprinkle"}


def _norm(w: str) -> str:
    return re.sub(r"[^a-z]", "", w.lower())


def _vessel(text: str, default: str = "bowl") -> str:
    t = text.lower()
    if re.search(r"\b(pan|skillet|sear|fry|saute)\b", t):
        return "pan"
    if re.search(r"\b(pot|simmer|boil|saucepan)\b", t):
        return "pot"
    return default


def chef_events(text: str, words: list[dict] | None, speech: float) -> list[dict]:
    """Heuristic action extraction from one beat: [{t, action, ingredient, color}] in time order (seconds, step-relative)."""
    toks = text.split()
    if words and len(words) >= len(toks) * 0.7:
        times = [float(w.get("start", 0.0)) for w in words]
        norm = [_norm(w.get("word", "")) for w in words]
    else:
        n = max(1, len(toks))
        times = [speech * i / n for i in range(n)]
        norm = [_norm(w) for w in toks]
    events: list[dict] = []
    seen: set[str] = set()
    for i, w in enumerate(norm):
        if not w:
            continue
        nxt = norm[i + 1] if i + 1 < len(norm) else ""
        if w == "olive" and nxt == "oil":
            name = "olive oil"
        else:
            name = next((k for k in _SINGLE if w == k or w == k + "s"), None)
            if name == "oil" and i > 0 and norm[i - 1] == "olive":
                name = None  # already caught at "olive"
        if name and name not in seen:
            seen.add(name)
            color, kind = INGREDIENTS[name]
            events.append({"t": times[i], "action": _ACTION_FOR[kind], "ingredient": name, "color": color})
        elif w in ("stir", "stirring", "mix", "fold", "toss") and "stir" not in seen:
            seen.add("stir")
            events.append({"t": times[i], "action": "stir", "ingredient": "", "color": ""})
        elif w in ("whisk", "whisked", "whisking", "emulsify", "blend") and "whisk" not in seen:
            seen.add("whisk")
            events.append({"t": times[i], "action": "whisk", "ingredient": "", "color": ""})
    return events


def _label(ev: dict) -> str:
    a, ing = ev["action"], ev["ingredient"]
    if a == "stir":
        return "Stir it gently"
    if a == "whisk":
        return "Whisk it well"
    if a == "plate":
        return "Serve it up"
    return ("Drizzle " if a == "drizzle" else "Add ") + ing


def chef_spec(steps: list[dict], accent: str | None = None, pause: float = PAUSE) -> dict:
    """steps: per-beat dicts (script_text, duration, optional words). Returns the JSON spec the chef template renders."""
    out: list[dict] = []
    cursor = 0.0
    total = sum(float(s["duration"]) for s in steps)
    for bi, s in enumerate(steps):
        dur = float(s["duration"])
        last = bi == len(steps) - 1
        speech = max(2.0, dur - (0.0 if last else pause))
        evs = chef_events(s["script_text"], s.get("words"), speech)
        vessel = _vessel(s["script_text"])
        cap = max(1, int(speech // 1.8))
        kept: list[dict] = []
        for ev in evs:
            if not kept or ev["t"] - kept[-1]["t"] >= 1.8:
                kept.append(ev)
        kept = kept[:cap]
        if not kept:
            kept = [{"t": speech * 0.3, "action": "stir", "ingredient": "", "color": ""}]
        if last:
            if len(kept) >= cap and cap > 1:
                kept = kept[:-1]
            kept.append({"t": max(kept[-1]["t"] + 1.8, speech - 2.4), "action": "plate", "ingredient": "", "color": ""})
        for i, ev in enumerate(kept):
            t0 = cursor + max(0.0, ev["t"] - 0.5)
            t1 = cursor + (kept[i + 1]["t"] - 0.5 if i + 1 < len(kept) else dur)
            if i == 0:
                t0 = cursor + (0.2 if bi == 0 else 0.0)
            out.append({"action": ev["action"], "ingredient": ev["ingredient"], "into": "plate" if ev["action"] == "plate" else vessel,
                        "color": ev["color"] or DEFAULT_COLOR, "label": _label(ev), "t0": round(t0, 2), "t1": round(max(t1, t0 + 1.5), 2)})
        cursor += dur
    # photo=False: use the vector chef rig (chef.js); the AI-photo chef is parked (see chef_photo.js)
    return {"duration": round(total, 2), "accent": accent or ACCENTS["chef"], "steps": out, "photo": False}


# ---------------------------------------------------------------- facts
_STAT = re.compile(r"(\$)?(\d[\d,]*(?:\.\d+)?)\s*(%|percent|million|billion|thousand|times|years?|days?|hours?|minutes?|seconds?|miles?|feet|degrees|km|kg)?", re.I)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s.strip()]


_DANGLING = {"a", "an", "the", "of", "to", "for", "and", "but", "or", "that", "in", "on", "with", "from", "is", "are", "was", "were", "they'll", "it's", "because", "so", "by", "as", "at", "their", "our", "its", "your"}


def _clip_words(s: str, n: int) -> str:
    """At most n words, cut at a clause boundary when there is one, never ending on a dangling function word."""
    w = s.replace(" — ", ", ").replace("—", ", ").replace(" ,", ",").split()
    if len(w) <= n:
        return " ".join(w).rstrip(".,;:")
    cut = None
    for i in range(min(n, len(w)) - 1, 3, -1):
        if w[i].endswith((",", ";", ":")):
            cut = i + 1
            break
    out = w[:cut] if cut else w[:n]
    while len(out) > 3 and out[-1].lower().strip(",;:") in _DANGLING:
        out.pop()
    return " ".join(out).rstrip(".,;:")


def find_stat(text: str) -> dict | None:
    """First whole number worth a big reveal (2+ digits or with a unit, not a year); None if absent."""
    for m in _STAT.finditer(text):
        raw = m.group(2).replace(",", "")
        unit = (m.group(3) or "").lower()
        if len(raw) < 2 and not unit:
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        if val != int(val) or val > 10**9:
            continue
        if re.fullmatch(r"(19|20)\d\d", raw) and not unit:
            continue
        suffix = "%" if unit in ("%", "percent") else ""
        return {"prefix": m.group(1) or "", "value": int(val), "suffix": suffix, "unit": "" if suffix else unit, "span": m.span()}
    return None


def facts_spec(steps: list[dict], accent: str | None = None, dark: bool = False) -> dict:
    beats: list[dict] = []
    cursor = 0.0
    total = sum(float(s["duration"]) for s in steps)
    for s in steps:
        dur = float(s["duration"])
        sents = _sentences(s["script_text"])
        if not sents:
            cursor += dur
            continue
        stat = find_stat(s["script_text"])
        mid = cursor + dur * 0.5
        if stat:
            host = next((x for x in sents if find_stat(x) and find_stat(x)["value"] == stat["value"]), sents[0])
            hs = find_stat(host)
            rest = (host[:hs["span"][0]] + " " + host[hs["span"][1]:]) if hs else host
            cap = ((stat["unit"] + " ") if stat["unit"] else "") + _clip_words(rest.strip(), 7)
            beats.append({"kind": "stat", "t0": round(cursor, 2), "t1": round(mid + 1.0, 2), "prefix": stat["prefix"], "value": stat["value"],
                          "suffix": stat["suffix"], "caption": cap.strip()})
            others = [x for x in sents if x != host]
            beats.append({"kind": "words", "t0": round(mid + 1.0, 2), "t1": round(cursor + dur, 2), "text": _clip_words(others[-1] if others else host, 10)})
        else:
            beats.append({"kind": "words", "t0": round(cursor, 2), "t1": round(mid, 2), "text": _clip_words(sents[0], 11)})
            beats.append({"kind": "words", "t0": round(mid, 2), "t1": round(cursor + dur, 2), "text": _clip_words(sents[-1] if len(sents) > 1 else sents[0], 10)})
        cursor += dur
    return {"duration": round(total, 2), "accent": accent or ACCENTS["facts"], "theme": "dark" if dark else "light", "beats": beats}


# ---------------------------------------------------------------- code
def highlight_lines(code: str, language: str | None) -> list[dict]:
    """[{text, html}] with inline-colored spans (pygments monokai) so the template needs no stylesheet."""
    from pygments import lex
    from pygments.lexers import PythonLexer, get_lexer_by_name
    from pygments.styles import get_style_by_name
    from pygments.util import ClassNotFound

    try:
        lexer = get_lexer_by_name((language or "python").lower())
    except ClassNotFound:
        lexer = PythonLexer()
    style = get_style_by_name("monokai")
    lines: list[list[str]] = [[]]
    for tok, val in lex(code.rstrip("\n"), lexer):
        color = style.style_for_token(tok)["color"]
        for j, piece in enumerate(val.split("\n")):
            if j > 0:
                lines.append([])
            if piece:
                esc = _html.escape(piece)
                lines[-1].append(f'<span style="color:#{color}">{esc}</span>' if color else esc)
    texts = code.rstrip("\n").split("\n")
    return [{"text": texts[i] if i < len(texts) else "", "html": "".join(parts)} for i, parts in enumerate(lines)]


def code_spec(steps: list[dict], language: str | None, accent: str | None = None) -> dict:
    parts: list[dict] = []
    cursor = 0.0
    total = sum(float(s["duration"]) for s in steps)
    for s in steps:
        dur = float(s["duration"])
        parts.append({"t0": round(cursor, 2), "t1": round(cursor + dur, 2), "lines": highlight_lines(s["code_snippet"] or "", language),
                      "output": (s.get("output_text") or "").strip() or None})
        cursor += dur
    return {"duration": round(total, 2), "accent": accent or ACCENTS["code"], "parts": parts}


if __name__ == "__main__":
    import json
    print(json.dumps(chef_spec([{"script_text": "Pour cream into a hot pan, add fresh thyme, then salt right away.", "duration": 12.0}]), indent=1)[:900])
    print(json.dumps(facts_spec([{"script_text": "Octopuses have 3 hearts. Two pump blood to the gills.", "duration": 10}]), indent=1)[:600])
