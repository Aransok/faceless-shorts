"""Free, deterministic AI-writing linter (2026-10-18).

Owner ask: scripts and auto-comments should not read like template AI
output, and comments kept repeating. The LLM authenticity reviewer
(review_script.py) already catches the subtle stuff, but it costs a call
every time. This module catches the mechanical tells for free, in plain
regex, BEFORE that call -- same "free check first" order plan.py already
uses for _duplicate_item_feedback().

Pattern groups are our own, informed by the categories in
blader/humanizer (MIT) and Wikipedia's "Signs of AI writing" guide:
dashes, negative parallelism ("not X, but Y"), stock AI vocabulary,
staged reveal openers, dramatic one-line closers, chat leftovers.
Deliberately high-precision: every pattern here is something this
channel's persona.md would reject anyway, so a hit is worth a rewrite.
Subtle judgment calls stay with the LLM reviewer.

English only for now. A Bulgarian set (calques, stiff formal register,
stock phrases) can be added as a second list when a template needs it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Tell:
    name: str
    pattern: re.Pattern
    hint: str
    # Fixed in code by fix_dashes() instead of costing an LLM rewrite.
    # Measured on the last 200 real scripts: dashes appeared in 170 of
    # them, the wording tells below in about 13. Triggering a Claude
    # rewrite on every dash would roughly double script cost for a
    # character TTS doesn't even pronounce.
    auto_fix: bool = False


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


TELLS: tuple[Tell, ...] = (
    Tell(
        "dash",
        re.compile(r"—|–|\s--\s"),
        "uses an em/en dash or double hyphen; use a period, comma or colon instead",
        auto_fix=True,
    ),
    Tell(
        "not_x_but_y",
        _rx(
            r"\b(?:it'?s|this is|that'?s|isn'?t|is)\s+not\s+(?:just|only|merely|about)\b"
            r"|\bnot\s+(?:just|only|merely)\s+[^.?!]{1,60}?,?\s+but\b"
            r"|\bisn'?t\s+(?:just|only|merely)\b"
        ),
        "'not X, but Y' / 'it's not just X' framing; state the point directly",
    ),
    Tell(
        "stock_words",
        _rx(
            r"\b(?:delve[sd]?|delving|tapestry|testament to|intricate|pivotal|realm|embark(?:s|ed)?|"
            r"unleash(?:es|ed)?|game[- ]?changer|seamless(?:ly)?|elevate[sd]?|"
            r"navigat(?:e|ing) the (?:world|landscape|complexities)|"
            r"in today'?s (?:fast[- ]paced|digital|modern) world|ever[- ]evolving|"
            r"it'?s worth noting|buckle up|let'?s dive in|dive deep(?:er)? into|"
            r"mind[- ]blowing|unlock(?:s|ing)? the (?:secret|power|full potential))\b"
        ),
        "stock AI vocabulary; use the plain word a person would say",
    ),
    Tell(
        "staged_reveal",
        _rx(r"\bhere'?s the (?:thing|kicker|catch|twist)\b|\bthe best part\?|\bspoiler alert\b|\bplot twist\b"),
        "staged reveal phrase; just say the thing",
    ),
    Tell(
        "dramatic_closer",
        _rx(r"\b(?:and )?(?:that|this) changes everything\b|\bthe rest is history\b|\bmind\.\s*blown\b"),
        "dramatic one-line closer; end on the concrete point instead",
    ),
    Tell(
        "chat_leftover",
        _rx(r"\b(?:i hope this helps|great question|certainly!|as an ai\b|in conclusion)\b"),
        "chat/essay leftover that doesn't belong in narration or a comment",
    ),
)


_NUMBER_RANGE = re.compile(r"(?<=\d)\s*\u2013\s*(?=\d)")
_UNICODE_DASH = re.compile(r"\s*[\u2014\u2013]\s*")
_SPACED_DOUBLE = re.compile(r"\s+--\s+")


def fix_dashes(text: str) -> str:
    """Dashes to commas, in code, no LLM call. Spoken narration keeps the
    same pause; written comments lose the AI-looking em dash. Only
    touches unicode dashes and space-padded double hyphens, never a
    plain hyphen or a code-like `--flag`."""
    if not text:
        return text
    text = _NUMBER_RANGE.sub(" to ", text)
    text = _UNICODE_DASH.sub(", ", text)
    text = _SPACED_DOUBLE.sub(", ", text)
    return re.sub(r",\s*([,.!?])", r"\1", text)


def lint(text: str, include_fixable: bool = False) -> list[tuple[str, str, str]]:
    """Every tell found, as (name, matched_text, hint). Empty list = clean.
    Auto-fixable tells (dashes) are skipped unless include_fixable."""
    found: list[tuple[str, str, str]] = []
    for tell in TELLS:
        if tell.auto_fix and not include_fixable:
            continue
        for match in tell.pattern.finditer(text or ""):
            found.append((tell.name, match.group(0).strip() or match.group(0), tell.hint))
    return found


def feedback(text: str) -> str | None:
    """Rewrite feedback in the same shape plan.py feeds back to the LLM,
    or None when the text is clean."""
    found = lint(text)
    if not found:
        return None
    lines = [f'- "{matched}": {hint}' for _name, matched, hint in found]
    return "These phrases read as AI-written. Rewrite without them:\n" + "\n".join(lines)


_WORD = re.compile(r"[a-z0-9']+")


def opener(text: str, n: int = 5) -> tuple[str, ...]:
    """First n words, lowercased, function words kept on purpose: the
    repetition viewers notice in short comments IS the stock frame
    ("did this one get you too?"), not the topic words after it."""
    return tuple(_WORD.findall((text or "").lower())[:n])


def repeats_recent(text: str, recent: list[str], min_overlap: int = 4) -> str | None:
    """The recent comment this one opens too much like, or None."""
    mine = opener(text)
    if len(mine) < min_overlap:
        return None
    for old in recent:
        if len(set(mine) & set(opener(old))) >= min_overlap:
            return old
    return None


def same_start(text: str, recent: list[str], words: int = 2, window: int = 6) -> str | None:
    """Recent comment (last `window`) sharing the first `words` words.

    repeats_recent() needs 4 of 5 opener words, so "Did anyone try adding"
    and "Did anyone try slicing" both passed, and a whole week of comments
    read as one template. Two shared first words is already the pattern a
    viewer scrolling the channel notices."""
    mine = opener(text, words)
    if len(mine) < words:
        return None
    for old in recent[-window:]:
        if opener(old, words) == mine:
            return old
    return None


def overused_word(text: str, recent: list[str], word: str = "anyone", window: int = 3) -> bool:
    """True if `word` is in this comment and in any of the last `window`."""
    if word not in _WORD.findall((text or "").lower()):
        return False
    return any(word in _WORD.findall(o.lower()) for o in recent[-window:])


if __name__ == "__main__":
    sample = (
        "Here's the thing: this isn't just a bug -- it's a testament to how "
        "Python handles defaults. And that changes everything."
    )
    print(feedback(sample))
    print(fix_dashes(sample))
