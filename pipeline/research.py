"""Fresh topic research (2026-09-24): real, current sources -> a short
list of candidate topics plan() can build a video around, instead of the
LLM drawing on its own memory of the same few dozen famous examples.

Owner ask: "we have sometimes the same topics ... we should be able to
make a quick research or something and post new cool things." Real data
backed it up -- programming re-uploaded five textbook gotchas within
~9 days of the first time, and sauce_recipe kept circling back to pan
sauces. See ROADMAP.md.

Sources are free, keyless, public APIs (CLAUDE.md's "no paid APIs" rule):
- facts: Wikipedia's "Did you know" hooks (Wikipedia:Recent additions) --
  editor-verified surprising facts about brand-new articles, dozens of
  new ones every week, i.e. things nobody has already made 50 Shorts
  about.
- sauce_recipe: Wikipedia's Category:Sauces, minus every sauce this
  channel's past scripts already mention.
- food: Wikipedia's Category:Cooking techniques, same "not already
  covered" filter.
programming and weird have no source here -- nothing free maps cleanly
onto "a real gotcha" or "an everyday thing with a hidden reason"; both
rely on plan.py's full-history topic avoid-list instead.

Fail-soft end to end: any network/parse problem returns None and the
video is planned exactly as before (CLAUDE.md's "fail soft" rule).
"""

from __future__ import annotations

import os
import random
import re
import sys
from html.parser import HTMLParser

import requests

from pipeline.rotation import mark_used, used_values
from pipeline.state import all_script_text
from pipeline.wikimedia import USER_AGENT

WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"
DYK_PAGE = "Wikipedia:Recent additions"
DYK_FALLBACK_PAGE = "Template:Did you know"
# Templates seeded from a Wikipedia category's article titles.
CATEGORY_SOURCE = {
    "sauce_recipe": "Category:Sauces",
    "food": "Category:Cooking techniques",
}

CANDIDATES_PER_SEED = 6
_USED_SLOT = {
    "facts": "research_used_facts",
    "sauce_recipe": "research_used_sauces",
    "food": "research_used_food",
}
# Effectively "remember forever" -- DYK hooks and sauce names are never
# worth re-offering, and each entry is one short line.
_USED_HISTORY_LIMIT = 3000

# "... that", "…that" (Unicode ellipsis) or ". . . that" -- the first real
# run (2026-09-24) parsed 0 hooks from the live page, so accept every
# ellipsis spelling rather than only three ASCII periods.
_HOOK_PREFIX = re.compile(r"^(?:\.\s?\.\s?\.|\u2026)\s*that\s+", re.IGNORECASE)
_PICTURED = re.compile(r"\s*\((?:[\w ]+ )?(?:pictured|illustrated|shown)\)", re.IGNORECASE)
_MIN_HOOK_CHARS = 40
_MAX_HOOK_CHARS = 300


class _ListItemTextParser(HTMLParser):
    """Collects the visible text of every <li>. DYK hooks are plain <li>
    items; the stdlib parser avoids adding an HTML dependency for this."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[str] = []
        self._stack: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "li":
            self._stack.append([])

    def handle_endtag(self, tag: str) -> None:
        if tag == "li" and self._stack:
            self.items.append("".join(self._stack.pop()))

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1].append(data)


def parse_dyk_hooks(html: str) -> list[str]:
    """Clean "that X" fact sentences from a DYK page's rendered HTML,
    minus the "... that" lead-in, image notes, and trailing "?"."""
    parser = _ListItemTextParser()
    parser.feed(html)
    hooks = []
    for raw in parser.items:
        text = " ".join(raw.split())
        if not _HOOK_PREFIX.match(text):
            continue
        text = _PICTURED.sub("", _HOOK_PREFIX.sub("", text)).rstrip("? ").strip()
        if _MIN_HOOK_CHARS <= len(text) <= _MAX_HOOK_CHARS and text not in hooks:
            hooks.append(text)
    return hooks


def clean_category_titles(titles: list[str]) -> list[str]:
    names = []
    for title in titles:
        if title.lower().startswith("list of"):
            continue
        name = re.sub(r"\s*\([^)]*\)$", "", title).strip()
        if name and name not in names:
            names.append(name)
    return names


def _wikipedia_get(params: dict) -> dict:
    response = requests.get(
        WIKIPEDIA_API_URL,
        params={**params, "format": "json", "formatversion": 2},
        headers={"User-Agent": USER_AGENT},
        timeout=20,
    )
    response.raise_for_status()
    return response.json()


def fetch_dyk_hooks() -> list[str]:
    # redirects=1: the real 2026-09-26 run showed "Recent additions" is a
    # redirect page -- without following it the API returns the 5KB
    # redirect stub (0 hooks). Template:Did you know (the current set on
    # the Main Page) is the fallback if the redirect target has none.
    hooks: list[str] = []
    html = ""
    for page in (DYK_PAGE, DYK_FALLBACK_PAGE):
        data = _wikipedia_get({"action": "parse", "page": page, "prop": "text", "redirects": 1})
        html = data["parse"]["text"]
        hooks = parse_dyk_hooks(html)
        if hooks:
            break
    if not hooks:
        # Diagnostic only: shows the live page's real <li> format in the
        # run log, since Wikipedia isn't reachable from dev sandboxes.
        parser = _ListItemTextParser()
        parser.feed(html)
        samples = [" ".join(i.split())[:80] for i in parser.items[:3]]
        print(f"[research] facts: 0 hooks parsed from {len(html)} chars / {len(parser.items)} <li>; first items: {samples!r}")
    return hooks


def fetch_category_names(category: str) -> list[str]:
    data = _wikipedia_get(
        {"action": "query", "list": "categorymembers", "cmtitle": category, "cmtype": "page", "cmlimit": 500}
    )
    return clean_category_titles([m["title"] for m in data["query"]["categorymembers"]])


def _format_seed(template: str, picks: list[str]) -> str:
    lines = "\n".join(f"- {p}" for p in picks)
    if template == "facts":
        return (
            "Real facts from Wikipedia's 'Did you know' section (each is about "
            "a newly written, editor-reviewed article). Build today's one fact "
            f"on the strongest of these:\n{lines}"
        )
    if template == "food":
        return (
            "Real cooking techniques from Wikipedia this channel has never "
            "covered. Build today's video around one you can explain "
            f"accurately (the real why + what to do):\n{lines}"
        )
    return (
        "Real sauces from Wikipedia's list of sauces that this channel has "
        "never made. Build today's video around one you know a real, "
        f"accurate recipe for:\n{lines}"
    )


def suggest_research_seed(template: str) -> str | None:
    """A formatted candidate list for plan()'s research_seed, or None
    (unsupported template, research disabled, nothing fresh, or any
    failure). Offered candidates are marked used right away -- which one
    the model picks isn't known here, and re-offering an ignored one
    tomorrow would just recreate the looping this exists to fix."""
    if template not in _USED_SLOT:
        return None
    if os.environ.get("ENABLE_RESEARCH_TOPICS", "1") == "0":
        return None
    try:
        if template == "facts":
            pool = fetch_dyk_hooks()
        else:
            covered = all_script_text(template)
            pool = [name for name in fetch_category_names(CATEGORY_SOURCE[template]) if name.lower() not in covered]
        used = set(used_values(_USED_SLOT[template]))
        fresh = [p for p in pool if p not in used]
        if not fresh:
            print(f"[research] {template}: no fresh candidates (pool={len(pool)}, all used/covered)")
            return None
        picks = random.sample(fresh, min(CANDIDATES_PER_SEED, len(fresh)))
        mark_used(_USED_SLOT[template], picks, _USED_HISTORY_LIMIT)
        print(f"[research] {template}: offering {len(picks)} of {len(fresh)} fresh candidates: {picks}")
        return _format_seed(template, picks)
    except Exception as exc:
        print(f"[research] {template}: research failed ({type(exc).__name__}: {exc}) -- planning without it")
        return None


if __name__ == "__main__":
    template_arg = sys.argv[1] if len(sys.argv) > 1 else "facts"
    if template_arg == "facts":
        found = fetch_dyk_hooks()
    else:
        found = fetch_category_names(CATEGORY_SOURCE[template_arg])
    print(f"{len(found)} candidates for {template_arg}:")
    for item in found[:40]:
        print(f"  - {item}")
