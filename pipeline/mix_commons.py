"""Wikimedia Commons search for the mix templates: free, no key.

Unlike pipeline/wikimedia.py (public-domain only, single image), this finds
footage AND photos by free-text query and accepts attribution licenses
(CC BY / CC BY-SA), since mix_render shows the credit on screen and
generate_metadata lists it in the description.
"""

from __future__ import annotations

import html
import re
import sys
import time
from pathlib import Path

import requests

from pipeline.wikimedia import USER_AGENT

API = "https://commons.wikimedia.org/w/api.php"
HEADERS = {"User-Agent": USER_AGENT}
VIDEO_MIMES = ("video/", "application/ogg")


def _get(url: str, params: dict | None = None, method: str = "GET") -> requests.Response:
    for attempt in range(6):  # Commons answers 429 when hit fast; back off and retry
        r = requests.request(method, url, params=params, headers=HEADERS, timeout=120)
        if r.status_code != 429 or attempt == 5:
            r.raise_for_status()
            return r
        time.sleep(int(r.headers.get("Retry-After") or 0) or 5 * 2 ** attempt)
    raise RuntimeError("unreachable")


def _plain(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def license_ok(lic: str) -> bool:
    """Public domain, CC0, CC BY and CC BY-SA. Never NC or ND."""
    low = lic.lower().strip()
    words = low.replace("-", " ").split()
    if "nc" in words or "nd" in words:
        return False
    return low.startswith(("public domain", "cc0", "pd", "cc by"))


def search(query: str, kind: str = "bitmap", n: int = 12, width: int = 1600) -> list[dict]:
    """kind: "bitmap" (photos) or "video". Returns only usable-license hits."""
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
              "gsrsearch": f"{query} filetype:{kind}", "gsrlimit": n, "prop": "imageinfo",
              "iiprop": "url|extmetadata|mime|size", "iiurlwidth": width}
    data = _get(API, params).json()
    pages = sorted(data.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        if "imageinfo" not in p:
            continue
        ii = p["imageinfo"][0]
        md = ii.get("extmetadata", {})
        item = {"title": p["title"], "mime": ii.get("mime", ""), "url": ii["url"],
                "thumb": ii.get("thumburl", ii["url"]), "w": ii.get("width") or 0, "h": ii.get("height") or 0,
                "artist": _plain(md.get("Artist", {}).get("value", "")),
                "license": _plain(md.get("LicenseShortName", {}).get("value", "")),
                "duration": ii.get("duration")}
        if license_ok(item["license"]):
            out.append(item)
    return out


def is_video(item: dict) -> bool:
    return item["mime"].startswith(VIDEO_MIMES)


def video_url(item: dict) -> str:
    """Prefer a 720p/480p transcode over the (often huge) original."""
    name = item["url"].split("/commons/")[1]
    fname = name.split("/")[-1]
    for res in ("720p.vp9.webm", "480p.vp9.webm", "720p.webm", "480p.webm"):
        u = f"https://upload.wikimedia.org/wikipedia/commons/transcoded/{name}/{fname}.{res}"
        try:
            _get(u, method="HEAD")
            return u
        except requests.RequestException:
            continue
    return item["url"]


def download(url: str, dest: Path) -> Path:
    dest.write_bytes(_get(url).content)
    return dest


def credit(item: dict) -> str:
    who = re.sub(r"\s+", " ", item["artist"] or "Wikimedia Commons")[:40]
    return f"{who}, {item['license'] or 'see Commons'}"


if __name__ == "__main__":
    kind = sys.argv[2] if len(sys.argv) > 2 else "bitmap"
    for it in search(sys.argv[1] if len(sys.argv) > 1 else "octopus", kind):
        print(it["title"], "|", it["w"], "x", it["h"], "|", it["license"], "|", it["duration"], "|", credit(it))
