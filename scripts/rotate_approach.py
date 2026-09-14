"""Cron entrypoint for the approach-rotation feedback loop (2026-09-14):
picks the next current_approach via pipeline.approaches.choose_next_
approach() (real winner-analyzer data once there's enough, otherwise a
not-immediately-repeated rotation so comparative data actually
accumulates) and writes it into config.yaml.

Usage:
    python scripts/rotate_approach.py

A plain regex line-replace, not a yaml.safe_load()+safe_dump() round
trip -- PyYAML's dumper doesn't preserve comments, and config.yaml's own
top-of-file comment block (explaining what current_approach does) is
worth keeping intact, not silently stripped by every automated rotation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.approaches import CONFIG_PATH, choose_next_approach, get_current_approach

_CURRENT_APPROACH_LINE = re.compile(r"^current_approach:\s*\S+\s*$", re.MULTILINE)


def main() -> None:
    old_approach = get_current_approach()
    new_approach = choose_next_approach()

    text = CONFIG_PATH.read_text(encoding="utf-8")
    updated, count = _CURRENT_APPROACH_LINE.subn(f"current_approach: {new_approach}", text)
    if count != 1:
        raise RuntimeError(f"expected exactly 1 current_approach line in {CONFIG_PATH}, found {count}")
    CONFIG_PATH.write_text(updated, encoding="utf-8")

    if new_approach == old_approach:
        print(f"approach unchanged: {old_approach}")
    else:
        print(f"approach rotated: {old_approach} -> {new_approach}")


if __name__ == "__main__":
    main()
