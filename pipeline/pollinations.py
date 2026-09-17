"""Pollinations.ai image generation (2026-09-17 design decision, see
HANDOFF.md): free, no API key, no signup, URL-based image generation
(Flux model) -- used for the Veylorn fantasy-story visuals, where a real
photo/stock clip can't show an invented world the way it can for a real
historical subject (see pipeline/wikimedia.py's equivalent role for the
facts/sauce_recipe templates).
"""

from __future__ import annotations

import time
import urllib.parse
from pathlib import Path

import requests

POLLINATIONS_BASE_URL = "https://image.pollinations.ai/prompt/"

# Anonymous-use rate limit is roughly 1 request/15s per Pollinations' own
# docs -- fine at this pipeline's per-video image volume (well under one
# image per 15s of real generation time), so no explicit throttling here.
REQUEST_TIMEOUT_SECONDS = 60

# Real, observed failure (2026-09-17 veylorn_story test run): a plain
# HTTP 500 from Pollinations on beat 8 of 10, after 8 real narration+
# image beats had already rendered successfully -- killed the whole
# video over one transient server error. Same "known transient failure
# of a free endpoint, retry with backoff" lesson as voice.py's own
# EDGE_TTS_RETRY_DELAYS, just for a 5xx HTTP status instead of a
# specific exception type -- a real 4xx (bad prompt encoding, etc.)
# still fails immediately, since retrying that would just fail the same
# way three more times.
RETRY_DELAYS_SECONDS = (2, 5, 10)


def build_image_url(prompt: str, width: int, height: int, seed: int | None = None) -> str:
    """A plain GET to this URL returns the generated image directly --
    Pollinations' entire API surface for image generation. `seed` pins a
    specific generation (same prompt+seed -> same image) -- passed
    explicitly rather than left to Pollinations' own default so a retry
    of the same beat doesn't silently generate a different image."""
    encoded_prompt = urllib.parse.quote(prompt, safe="")
    params = {"width": str(width), "height": str(height), "nologo": "true"}
    if seed is not None:
        params["seed"] = str(seed)
    return f"{POLLINATIONS_BASE_URL}{encoded_prompt}?{urllib.parse.urlencode(params)}"


def download_image(prompt: str, out_path: Path, width: int, height: int, seed: int | None = None) -> None:
    url = build_image_url(prompt, width, height, seed=seed)
    last_exc: requests.HTTPError | None = None
    for delay in (0,) + RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        response = requests.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        if response.status_code < 500:
            response.raise_for_status()
            out_path.write_bytes(response.content)
            return
        last_exc = requests.HTTPError(f"{response.status_code} Server Error for url: {url}", response=response)
    raise last_exc


if __name__ == "__main__":
    sample_path = Path("/tmp/pollinations_sample.jpg")
    download_image(
        "a lone traveler at a crossroads under a stormy sky, epic fantasy digital painting",
        sample_path, width=1920, height=1080, seed=1,
    )
    print(f"saved: {sample_path}")
