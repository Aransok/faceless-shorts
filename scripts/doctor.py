"""Pre-flight environment check (2026-10-18).

Runs as the first real step of a pipeline workflow, so a missing tool or
secret fails loudly in seconds instead of after a long render (idea from
the `doctor` commands in SenseNova-Skills, Agent Reach and awwwards-mcp).
Reads the same env vars the pipeline reads and checks only what that
configuration actually needs. No network calls, no LLM calls.

Usage:
    python scripts/doctor.py            # check, exit 1 on any hard failure
    python scripts/doctor.py --youtube  # also require YouTube secrets
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# requirements.txt name -> import name
_MODULES = {
    "ffmpeg-python": "ffmpeg",
    "faster-whisper": "faster_whisper",
    "edge-tts": "edge_tts",
    "mutagen": "mutagen",
    "google-api-python-client": "googleapiclient",
    "google-auth-oauthlib": "google_auth_oauthlib",
    "pygments": "pygments",
    "Pillow": "PIL",
    "python-dotenv": "dotenv",
    "requests": "requests",
}

MIN_FREE_GB = 2.0


def check(env: dict[str, str], youtube: bool) -> list[tuple[str, str, str]]:
    """(level, name, detail) rows. level is ok / warn / fail."""
    rows: list[tuple[str, str, str]] = []

    def need(ok: bool, name: str, detail: str, level: str = "fail") -> None:
        rows.append(("ok" if ok else level, name, detail))

    for tool in ("ffmpeg", "ffprobe"):
        need(shutil.which(tool) is not None, tool, "on PATH")

    for pkg, module in _MODULES.items():
        need(importlib.util.find_spec(module) is not None, f"python: {pkg}", f"import {module}")

    llm = env.get("LLM_BACKEND", "claude_code")
    if llm == "claude_code":
        need(shutil.which("claude") is not None, "claude CLI", "LLM_BACKEND=claude_code")
        need(bool(env.get("CLAUDE_CODE_OAUTH_TOKEN")), "CLAUDE_CODE_OAUTH_TOKEN", "LLM_BACKEND=claude_code")
    elif llm == "groq":
        need(bool(env.get("GROQ_API_KEY")), "GROQ_API_KEY", "LLM_BACKEND=groq")

    uses_groq = "groq" in (env.get("BULK_LLM_BACKEND", ""), env.get("LLM_FALLBACK_BACKEND", ""))
    if uses_groq:
        need(bool(env.get("GROQ_API_KEY")), "GROQ_API_KEY", "bulk/fallback backend is groq", level="warn")

    for name, key in (("gemini", "GEMINI_API_KEY"), ("cerebras", "CEREBRAS_API_KEY"), ("openrouter", "OPENROUTER_API_KEY")):
        if name in (env.get("LLM_BACKEND", ""), *env.get("LLM_FALLBACK_BACKEND", "").split(",")):
            need(bool(env.get(key)), key, f"{name} LLM backend", level="warn")

    if env.get("FACTS_VISUAL_SOURCE") == "stock":
        need(bool(env.get("PEXELS_API_KEY")), "PEXELS_API_KEY", "FACTS_VISUAL_SOURCE=stock")

    if youtube:
        for key in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"):
            need(bool(env.get(key)), key, "upload")

    free_gb = shutil.disk_usage(PROJECT_ROOT).free / 1e9
    need(free_gb >= MIN_FREE_GB, "disk", f"{free_gb:.1f} GB free (min {MIN_FREE_GB})")
    return rows


def report(rows: list[tuple[str, str, str]]) -> str:
    icon = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    lines = ["| status | check | detail |", "|---|---|---|"]
    lines += [f"| {icon[level]} | {name} | {detail} |" for level, name, detail in rows]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--youtube", action="store_true", help="also require YouTube upload secrets")
    args = parser.parse_args(argv)

    rows = check(dict(os.environ), youtube=args.youtube)
    table = report(rows)
    print(table)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("## Doctor\n\n" + table + "\n")
    failed = [name for level, name, _ in rows if level == "fail"]
    if failed:
        print(f"\ndoctor: {len(failed)} hard failure(s): {', '.join(failed)}")
        return 1
    print("\ndoctor: all required checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
