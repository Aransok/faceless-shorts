"""Fresh topic research (2026-09-24): real, current sources -> a short
list of candidate topics plan() can build a video around, instead of the
LLM drawing on its own memory of the same few dozen famous examples.

Owner ask: "we have sometimes the same topics ... we should be able to
make a quick research or something and post new cool things." Real data
backed it up -- programming re-uploaded five textbook gotchas within
~9 days of the first time, and sauce_recipe kept circling back to pan
sauces. See ROADMAP.md.

Sources are free, keyless, public APIs (CLAUDE.md's "no paid APIs" rule):
- facts, first choice (2026-10-08, owner: "catch the viral trends"):
  what people suddenly started looking up -- English Wikipedia articles
  in yesterday's most-read list that weren't in the most-read list a
  week earlier, from Wikimedia's official pageviews API. Falls back to
  "Did you know" below when there's nothing fresh or the call fails.
  food/sauce_recipe also try trending first, limited to risers whose
  description is about food, before their category lists.
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
from datetime import date, datetime, timedelta, timezone
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

PAGEVIEWS_TOP_URL = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/all-access/{day:%Y/%m/%d}"
)
# Rank cutoff in yesterday's list; the baseline is the full top 1000 a
# week earlier, so "rising" means it wasn't anywhere near the top then.
TRENDING_TOP_N = 200
TRENDING_BASELINE_DAYS = 7
TRENDING_TEMPLATES = ("facts", "food", "sauce_recipe")
# food/sauce_recipe only take risers that are actually about food.
_FOOD_DESCRIPTION = re.compile(
    r"\b(?:dish|food|cuisine|sauce|condiment|dip|dressing|gravy|salsa|dessert|pastry|bread|cake"
    r"|pie|soup|stew|beverage|drink|cocktail|spice|herb|fruit|vegetable|squash|cheese|meat"
    r"|recipe|confectionery|candy|snack|cooking|baking|culinary|ingredient)s?\b",
    re.IGNORECASE,
)
_NON_TOPIC_PREFIXES = ("List of ", "Deaths in ", "Main Page")
_YEAR_PAGE = re.compile(r"^\d{3,4}( in .+)?$")
# Most of what spikes on Wikipedia is the news cycle -- the first real
# run's top risers were celebrities, people who had just died, shootings
# and an election. Wikipedia's short descriptions mark people with life
# years ("American actress (born 1924)", "(1950-2026)") or an occupation.
_PERSON_DESCRIPTION = re.compile(
    r"\((?:born |died |c\. )?\d{3,4}(?:\s*[–-]\s*\d{3,4})?\)"
    r"|\b(?:actor|actress|singer|rapper|musician|songwriter|politician|footballer|player|athlete"
    r"|coach|wrestler|boxer|comedian|businessman|businesswoman|entrepreneur"
    r"|journalist|presenter|personality|influencer|writer|author|novelist|director|producer"
    r"|televangelist|evangelist|scientist|physicist|chemist|biologist|neuroscientist|engineer"
    r"|economist|lawyer|judge|criminal|murderer|activist|advocate|dancer|artist|youtuber"
    r"|astrophysicist|astronomer|mathematician|historian|philosopher|poet|painter|composer"
    r"|architect|inventor|explorer|mountaineer|adventurer|chef|designer|official|diplomat)s?\b",
    re.IGNORECASE,
)
_NEWS_EVENT = re.compile(
    r"\b(?:shooting|attack|bombing|murder|killing|massacre|allegations?|scandal|trial|election"
    r"|referendum|crash|disaster|earthquake|hurricane|war|riot|protests?|assassination"
    r"|kidnapping|rape|abuse|stabbing|death of|disambiguation|same term|investigation"
    r"|indictment|arrest|lawsuit|controversy|incident|hostage|missing)\b",
    re.IGNORECASE,
)


def is_newsy(title: str, description: str) -> bool:
    """True for people and news events -- not this channel's material."""
    return bool(_PERSON_DESCRIPTION.search(description) or _NEWS_EVENT.search(f"{title} {description}"))

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


def rising_titles(recent: list[str], baseline: list[str], top_n: int = TRENDING_TOP_N) -> list[str]:
    """Articles in `recent`'s top_n (raw API titles, rank order) that
    aren't in `baseline` at all, minus non-article pages and lists."""
    before = set(baseline)
    titles = []
    for raw in recent[:top_n]:
        if raw in before or ":" in raw:
            continue
        title = raw.replace("_", " ").strip()
        if len(title) < 2 or title.startswith(_NON_TOPIC_PREFIXES) or _YEAR_PAGE.match(title):
            continue
        titles.append(title)
    return titles


def fetch_top_articles(day: date) -> list[str]:
    response = requests.get(PAGEVIEWS_TOP_URL.format(day=day), headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    return [a["article"] for a in response.json()["items"][0]["articles"]]


def fetch_descriptions(titles: list[str]) -> dict[str, str]:
    """Wikipedia short description per title (max 50 per API call), ""
    when an article has none."""
    data = _wikipedia_get(
        {"action": "query", "prop": "description", "titles": "|".join(titles), "redirects": 1}
    )["query"]
    final = {t: t for t in titles}
    for step in ("normalized", "redirects"):
        moved = {m["from"]: m["to"] for m in data.get(step, [])}
        final = {t: moved.get(f, f) for t, f in final.items()}
    by_title = {p["title"]: p.get("description", "") for p in data.get("pages", [])}
    return {t: by_title.get(f, "") for t, f in final.items()}


_trending_cache: dict[date, list[tuple[str, str]]] = {}


def fetch_trending_topics(today: date | None = None) -> list[tuple[str, str]]:
    """(title, short description) for today's non-newsy risers, rank
    order. Cached per day: a daily run asks once per video, and
    Wikipedia rate-limits bursts."""
    today = today or datetime.now(timezone.utc).date()
    if today not in _trending_cache:
        _trending_cache[today] = _fetch_trending_uncached(today)
    return _trending_cache[today]


def _fetch_trending_uncached(today: date) -> list[tuple[str, str]]:
    # Yesterday's list isn't published until a few hours into the UTC day.
    try:
        recent_day = today - timedelta(days=1)
        recent = fetch_top_articles(recent_day)
    except requests.HTTPError:
        recent_day = today - timedelta(days=2)
        recent = fetch_top_articles(recent_day)
    baseline = fetch_top_articles(recent_day - timedelta(days=TRENDING_BASELINE_DAYS))
    risers = rising_titles(recent, baseline)[:50]
    if not risers:
        return []
    descriptions = fetch_descriptions(risers)
    pairs = [(t, descriptions.get(t, "")) for t in risers]
    # No short description means the article can't be vetted at all.
    return [(t, d) for t, d in pairs if d and not is_newsy(t, d)]


# Titles already offered by THIS process, so the day's videos get
# different candidates. Deliberately not persisted (unlike the other
# sources' used-lists): real 2026-10-08, a run that failed at the LLM
# step burned the day's whole trending list before a single video was
# made. Re-offering tomorrow is fine -- anything actually turned into a
# video is excluded by the covered-text check below.
_offered_this_run: set[str] = set()


def _base_title(title: str) -> str:
    return re.sub(r"\s*\([^)]*\)$", "", title).strip().lower()


def trending_candidates(template: str) -> list[str]:
    """Up to CANDIDATES_PER_SEED trending titles suited to `template`
    (rank order -- the top risers are the strongest signal) that this
    channel hasn't covered and this run hasn't offered yet; [] when
    there are none or anything fails."""
    if template not in TRENDING_TEMPLATES or os.environ.get("ENABLE_TRENDING_TOPICS", "1") == "0":
        return []
    try:
        risers = fetch_trending_topics()
        if template != "facts":
            risers = [(t, d) for t, d in risers if _FOOD_DESCRIPTION.search(d)]
        covered = all_script_text(template)
        picks = [
            t for t, _ in risers if t not in _offered_this_run and _base_title(t) not in covered
        ][:CANDIDATES_PER_SEED]
        _offered_this_run.update(picks)
        print(f"[research] trending for {template}: {picks or 'nothing fresh'} (pool={len(risers)})")
        return picks
    except Exception as exc:
        print(f"[research] trending failed for {template} ({type(exc).__name__}: {exc})")
        return []


def _format_trending_seed(template: str, picks: list[str]) -> str:
    lines = "\n".join(f"- {p}" for p in picks)
    lead = (
        "Subjects people suddenly started looking up this week (Wikipedia "
        "articles whose readership just jumped -- a real signal of what "
        "people are curious about right now). "
    )
    if template == "facts":
        ask = (
            "Build the video around whichever has the most genuinely "
            "surprising, durable facts behind it, and let the connecting "
            "theme grow from it. Skip anyone who just died, disasters, "
            "crimes, elections/politics and ongoing news -- this channel does "
            "surprising facts, not news"
        )
    elif template == "food":
        ask = (
            "Build at least one of today's three items around one of these "
            "-- a real technique for it, with the real why"
        )
    else:
        ask = (
            "Build at least one of today's three sauces around one of these "
            "-- a real sauce from it or that genuinely belongs with it"
        )
    return f"{lead}{ask}:\n{lines}"


def _format_seed(template: str, picks: list[str]) -> str:
    lines = "\n".join(f"- {p}" for p in picks)
    if template == "facts":
        return (
            "Real facts from Wikipedia's 'Did you know' section (each is about "
            "a newly written, editor-reviewed article). Anchor one of the three "
            "facts on the strongest of these, and let the connecting theme grow "
            f"from it:\n{lines}"
        )
    if template == "food":
        return (
            "Real cooking techniques from Wikipedia this channel has never "
            "covered. Build at least one of today's three items around one "
            "you can explain accurately (the real why + what to do), and let "
            f"the connecting theme grow from it:\n{lines}"
        )
    return (
        "Real sauces from Wikipedia's list of sauces that this channel has "
        "never made. Build at least one of today's three sauces around one "
        "you know a real, accurate recipe for, and let the connecting theme "
        f"grow from it:\n{lines}"
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
    trending = trending_candidates(template)
    if trending:
        return _format_trending_seed(template, trending)
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
    if template_arg == "trending":
        found = [f"{t} -- {d}" for t, d in fetch_trending_topics()]
    elif template_arg == "facts":
        found = fetch_dyk_hooks()
    else:
        found = fetch_category_names(CATEGORY_SOURCE[template_arg])
    print(f"{len(found)} candidates for {template_arg}:")
    for item in found[:40]:
        print(f"  - {item}")
