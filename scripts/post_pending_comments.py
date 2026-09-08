"""Cron entrypoint for catching up on CTA comments that couldn't post at
upload time (video was still private/scheduled) but are now public. See
pipeline/upload.py's post_pending_cta_comments() and ROADMAP.md.

Usage:
    python scripts/post_pending_comments.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.upload import post_pending_cta_comments


def main() -> None:
    post_pending_cta_comments()


if __name__ == "__main__":
    main()
