"""Download the style-lab test assets into <lab_dir>: Wikimedia Commons
photos, Google Fonts (OFL) and Incompetech music (CC BY 4.0).

    python scripts/style_lab/fetch_assets.py <lab_dir>

Commons answers 429 to bursts from shared IPs, so requests are spaced
out and retried with backoff; thumbnails use an allowed width (1280).
"""
from __future__ import annotations

import hashlib
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

UA = "faceless-shorts-style-lab/1.0 (https://github.com/Aransok/faceless-shorts)"

# key -> (Commons file name, thumbnail width or None for the original)
IMAGES = {
    "lake1986": ("Lake Nyos 1986 001.jpg", None),  # USGS, public domain
    "lake1992": ("Lake Nyos 1992 001.jpg", None),  # USGS, public domain
    "lake2001": ("Lake Nyos 2001.jpg", None),  # USGS, public domain
    "landsat": ("Lake Nyos from Landsat, 2014.jpg", None),  # NASA, public domain
    "vent": ("Lake nyos co2 vent.jpg", None),  # USGS, public domain
    "nyoslake": ("Nyos Lake correct.jpg", None),  # CC0
    "cow": ("Cow killed by Lake Nyos gasses.jpg", None),  # USGS, public domain
    "timeline": ("Tml15-16 Nc.jpg", None),  # public domain
    "hills": ("Hills and farm land, Njap.jpg", 1280),  # CC BY-SA 4.0 (credit the author)
}
FONTS = "family=Montserrat:wght@800;900&family=Anton&family=Inter:wght@500;600;700&family=Instrument+Serif:ital@0;1&family=Special+Elite"
MUSIC = ["Volatile Reaction", "Echoes of Time", "Darkest Child"]  # Kevin MacLeod, CC BY 4.0


def _get(url: str, tries: int = 8, ua: str = UA) -> bytes:
    for attempt in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=60).read()
        except Exception as exc:  # 429/5xx from shared egress: back off
            if attempt == tries - 1:
                raise
            print(f"  retry {attempt + 1} ({exc})")
            time.sleep(min(60, 8 * 2 ** attempt))
    raise AssertionError("unreachable")


def commons_url(name: str, width: int | None) -> str:
    n = name.replace(" ", "_")
    h = hashlib.md5(n.encode()).hexdigest()
    q = urllib.parse.quote(n)
    if width:
        return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/{width}px-{q}"
    return f"https://upload.wikimedia.org/wikipedia/commons/{h[0]}/{h[:2]}/{q}"


def main(lab: Path) -> None:
    for sub in ("img", "fonts", "music"):
        (lab / sub).mkdir(parents=True, exist_ok=True)
    for key, (name, width) in IMAGES.items():
        out = lab / "img" / f"{key}.jpg"
        if not out.exists():
            out.write_bytes(_get(commons_url(name, width)))
            time.sleep(3)
        print("img", key, out.stat().st_size)
    css = _get(f"https://fonts.googleapis.com/css2?{FONTS}", ua="Wget/1.21").decode()
    for fam, style, weight, url in re.findall(r"font-family: '([^']+)';\s*font-style: (\w+);\s*font-weight: (\d+);.*?src: url\((\S+?)\)", css, re.DOTALL):
        out = lab / "fonts" / f"{fam.replace(' ', '')}-{weight}{'i' if style == 'italic' else ''}.ttf"
        if not out.exists():
            out.write_bytes(_get(url))
        print("font", out.name)
    for title in MUSIC:
        out = lab / "music" / f"{title.replace(' ', '_')}.mp3"
        if not out.exists():
            out.write_bytes(_get(f"https://incompetech.com/music/royalty-free/mp3-royaltyfree/{urllib.parse.quote(title)}.mp3"))
        print("music", out.name, out.stat().st_size)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
