"""Wikimedia Commons image search for the "real image, brief supplemental
beat" feature (2026-09-14, per real viewer feedback that all-stock B-roll
never actually shows the real thing a fact/recipe beat is talking about).
Free, no API key, self-hosted-equivalent (Wikimedia's own public API) --
fits CLAUDE.md's "no paid APIs" rule same as every other backend here.
"""

from __future__ import annotations

import re
from pathlib import Path

import requests

COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"
# Wikimedia's API etiquette requires a descriptive User-Agent identifying
# the client -- unauthenticated requests without one get rate-limited/blocked.
USER_AGENT = "faceless-shorts/1.0 (https://github.com/aransok/faceless-shorts; automation pipeline)"

# Only license terms that need no in-video attribution overlay -- a
# CC-BY/CC-BY-SA image is legally usable but needs real per-image credit we
# have no format for weaving into a ~20s vertical Short. Restricting to
# these keeps the feature usable "here and there" without building an
# attribution-card system nothing else in this pipeline has.
ACCEPTED_LICENSES = {"Public domain", "CC0", "CC0 1.0", "Public Domain Mark"}

# Only real photo formats. The old test was `mime.startswith("image/")`,
# which let book scans through: a `.djvu` file has the type
# image/vnd.djvu, and its "thumbnail" is a rendered page. The first real
# Case File run (2026-10-31) put three djvu magazine/book pages on screen
# labelled as evidence photos. TIFF is excluded too: Commons holds a lot of
# multi-page archive scans in it.
PHOTO_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}


# Relevance rule (owner's choice 2026-10-31, after the first real Case File
# run showed unrelated photos labelled as evidence): a Commons file is used
# only if its FILE NAME shares a meaningful word with the beat's subject. The
# search matches full text, so a street photo whose description merely
# mentions "ginger" came back for a ginger recipe. Words this short or this
# generic say nothing about what the picture shows.
_GENERIC_WORDS = frozenset({
    "the", "and", "with", "from", "into", "over", "this", "that", "file", "image", "photo",
    "picture", "jpg", "jpeg", "png", "webp", "sauce", "recipe", "how", "why", "for",
})


def _title_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    # singular/plural: "frogs" and "frog" are the same subject word
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if len(w) >= 4 and w not in _GENERIC_WORDS}


def title_matches_subject(title: str, subject: str) -> bool:
    return bool(_title_words(title) & _title_words(subject))


def search_commons_image(subject: str) -> dict | None:
    """Best licensed real photo of `subject`, or None if nothing qualifies.
    Never raises on a network/parse problem -- callers treat that the same
    as "no image available" (this is a supplemental beat, not something a
    video should fail over; see visuals_facts.py's fail-soft wrapping).
    """
    if not subject:
        return None
    try:
        response = requests.get(
            COMMONS_API_URL,
            headers={"User-Agent": USER_AGENT},
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": subject,
                "gsrnamespace": 6,  # File: namespace
                "gsrlimit": 5,
                "prop": "imageinfo",
                "iiprop": "url|extmetadata|mime",
                "iiurlwidth": 1080,
            },
            timeout=15,
        )
        response.raise_for_status()
        pages = response.json().get("query", {}).get("pages", {})
    except (requests.RequestException, ValueError):
        return None

    return _best_licensed_image(pages, subject)


def _best_licensed_image(pages: dict, subject: str | None = None) -> dict | None:
    """First page that is a real photo, under an accepted license and, when a
    `subject` is given, named for it. No subject means no relevance check."""
    for page in pages.values():
        info_list = page.get("imageinfo") or []
        if not info_list:
            continue
        info = info_list[0]
        if info.get("mime", "") not in PHOTO_MIME_TYPES:
            continue  # SVG icons, djvu/tiff scans and the like aren't photos of "the real thing"
        license_name = info.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        if license_name not in ACCEPTED_LICENSES:
            continue
        if subject and not title_matches_subject(page.get("title", ""), subject):
            continue
        image_url = info.get("thumburl") or info.get("url")
        if not image_url:
            continue
        return {
            "title": page.get("title", ""),
            "url": image_url,
            "license": license_name,
            "source_page": info.get("descriptionurl", ""),
        }
    return None


def download_commons_image(image_url: str, out_path: Path) -> None:
    response = requests.get(image_url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    out_path.write_bytes(response.content)


if __name__ == "__main__":
    result = search_commons_image("Oxford Electric Bell")
    print(result or "no licensed image found")
