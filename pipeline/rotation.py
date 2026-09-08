"""Generic rolling-recent-exclusion rotation, shared by every "pick one
of a small pool, avoid repeating what just ran" decision in the
pipeline: hook/structure/phrasing (pipeline/approaches.py), code editor
theme (pipeline/visuals_code.py), CTA overlay variant and music track
(pipeline/assemble.py). One mechanism, not a copy per use site.

Storage is data/phrase_usage.json -- named for its original single use
(hook phrasing) before other rotating dimensions were added onto the
same mechanism. Keeping the existing filename rather than doing a
purely-cosmetic rename/migration of real accumulated history.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ROTATION_LOG_PATH = PROJECT_ROOT / "data" / "phrase_usage.json"


def _load_recent(slot: str) -> list[str]:
    if not ROTATION_LOG_PATH.exists():
        return []
    data = json.loads(ROTATION_LOG_PATH.read_text(encoding="utf-8"))
    return data.get(slot, [])


def _record_recent(slot: str, value: str, limit: int) -> None:
    data = json.loads(ROTATION_LOG_PATH.read_text(encoding="utf-8")) if ROTATION_LOG_PATH.exists() else {}
    data[slot] = (data.get(slot, []) + [value])[-limit:]
    ROTATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROTATION_LOG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def pick_rotating(slot: str, pool: list[str], limit: int) -> str:
    """Random pick from pool, preferring items not used in the slot's last
    `limit` picks. Falls back to the full pool if every candidate has been
    used recently (a small pool, or a burst of picks) rather than ever
    failing to pick something. `limit` must be sized to the pool -- a
    window >= pool size makes the exclusion a permanent no-op (this
    already bit the theme pool during design: the 15-video window used
    for the 18-item hook pool would have excluded this 5-item theme pool
    almost every time).
    """
    recent = _load_recent(slot)
    candidates = [p for p in pool if p not in recent]
    picked = random.choice(candidates or pool)
    _record_recent(slot, picked, limit)
    return picked
