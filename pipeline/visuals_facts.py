"""Stage 2 (visuals, facts template): each fact beat -> its own
keyword-matched background footage, cut together and sized exactly to
that beat's real narration duration. See SPEC.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv

from pipeline.state import get_video, get_video_steps, list_by_status, update_video
from pipeline.voice import voice

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"

load_dotenv(PROJECT_ROOT / ".env")

WIDTH, HEIGHT = 1080, 1920
FPS = 30
SEGMENT_TARGET_SECONDS = 5.0  # cut to a new clip roughly every 4-6s, within each beat
PEXELS_SEARCH_URL = "https://api.pexels.com/videos/search"


def _search_pexels_videos(query: str, api_key: str, per_page: int = 5) -> list[dict]:
    response = requests.get(
        PEXELS_SEARCH_URL,
        headers={"Authorization": api_key},
        params={"query": query, "per_page": per_page, "orientation": "portrait"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json().get("videos", [])


def _pick_video_file(video: dict) -> str:
    files = video.get("video_files", [])
    mp4_files = [f for f in files if f.get("file_type") == "video/mp4" and f.get("width")]
    if not mp4_files:
        raise ValueError(f"no usable video files in Pexels result: {video.get('id')}")

    # Prefer the closest match to our target resolution — an exact
    # 1080x1920 file needs no upscaling; otherwise pick the smallest file
    # that's still >= target, falling back to the largest available.
    exact = [f for f in mp4_files if f["width"] == WIDTH and f["height"] == HEIGHT]
    if exact:
        return exact[0]["link"]
    at_least = sorted(
        (f for f in mp4_files if f["width"] >= WIDTH), key=lambda f: f["width"]
    )
    if at_least:
        return at_least[0]["link"]
    return max(mp4_files, key=lambda f: f["width"])["link"]


def _describe_clip(video: dict) -> str:
    """Pexels doesn't return tags on video search results, but the page
    URL is a human-written slug (e.g. .../close-up-of-dictionary-pages-
    1234567/) — the cheapest real signal available for a human reviewing
    the query log to sanity-check the match without opening every clip,
    and (see _score_candidate) the only free signal available to check
    whether a candidate actually has anything to do with its query
    before trusting the search tier it came from.
    """
    url = video.get("url", "")
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    slug = "-".join(slug.split("-")[:-1]) if slug and slug.split("-")[-1].isdigit() else slug
    return slug.replace("-", " ") or "(no description available)"


# Visual Director upgrade (see HANDOFF.md / real viewer feedback: "more
# of these neat things that exist and yet you show none of them"). The
# LLM already tiers each beat's queries by how directly they'd show the
# real subject (see plan.py/_parse_facts_response and the
# facts_template.txt prompt) -- this is where that tiering actually
# changes which footage gets selected, instead of collapsing everything
# into one flat keyword list and taking whatever Pexels returns first.
MATCH_TYPES = ("exact_subject", "accurate_representation", "concept_explanation", "generic_fallback")
_TIER_BASE_SCORE = {"exact_subject": 40, "accurate_representation": 30, "concept_explanation": 20, "generic_fallback": 5}
# A candidate whose description shares zero real words with its own
# query/subject is a "the search tier lied" case -- e.g. an "exact"
# query for "Oxford electric bell" that actually returned an unrelated
# clip Pexels judged loosely similar. Rather than trust the tier label
# blindly, demote it one level and apply a mismatch penalty (cheap,
# deterministic, no per-candidate LLM call needed for this).
_TIER_DEMOTION = {"exact_subject": "accurate_representation", "accurate_representation": "concept_explanation", "concept_explanation": "generic_fallback"}
_ZERO_OVERLAP_PENALTY = 10
_STOPWORDS = {"the", "a", "an", "of", "in", "on", "at", "and", "or", "with", "for", "to", "is", "close", "up", "video"}
MIN_ACCEPTABLE_SCORE = 35  # roughly "accurate_representation with some real overlap" or better


def _significant_tokens(text: str) -> set[str]:
    return {w for w in text.lower().replace("-", " ").split() if w and w not in _STOPWORDS}


def _score_candidate(video: dict, query: str, tier: str, subject: str) -> tuple[int, str]:
    """Deterministic, free (no LLM) relevance score + a possibly-demoted
    match type -- see MATCH_TYPES/_TIER_DEMOTION above for why this
    doesn't just trust the search tier a candidate came from."""
    description = _describe_clip(video)
    desc_tokens = _significant_tokens(description)
    query_tokens = _significant_tokens(query) | _significant_tokens(subject)
    overlap = len(query_tokens & desc_tokens)

    match_type = tier
    if overlap == 0 and tier in _TIER_DEMOTION:
        match_type = _TIER_DEMOTION[tier]
        score = _TIER_BASE_SCORE[match_type] - _ZERO_OVERLAP_PENALTY
    else:
        score = _TIER_BASE_SCORE[tier] + min(15, overlap * 5)
    return max(0, score), match_type


def _search_tier(query: str, tier: str, subject: str, api_key: str, seen_ids: set[int]) -> list[dict]:
    """One tier's worth of scored, deduped candidates for one query."""
    scored = []
    for video in _search_pexels_videos(query, api_key, per_page=5):
        if video["id"] in seen_ids:
            continue
        seen_ids.add(video["id"])
        score, match_type = _score_candidate(video, query, tier, subject)
        scored.append({"video": video, "query": query, "tier": tier, "match_type": match_type, "score": score})
    return scored


def _build_clip_pool(visual_plan: dict, api_key: str, min_count: int) -> tuple[list[dict], list[dict]]:
    """Searches the beat's visual plan tier by tier -- exact_subject
    first, then accurate_representation, then concept_explanation,
    falling back to a generic search built from the subject alone only
    if nothing scored acceptably. Stops early once enough
    MIN_ACCEPTABLE_SCORE-or-better candidates exist, rather than always
    exhausting every tier. Returns the top-scoring `min_count` candidates
    (not first-found) plus a log entry per candidate actually searched,
    for {video_id}_visual_log.json.
    """
    subject = visual_plan.get("subject") or ""
    tiers = [
        ("exact_subject", visual_plan.get("exact") or []),
        ("accurate_representation", visual_plan.get("representation") or []),
        ("concept_explanation", visual_plan.get("concept") or []),
    ]

    all_scored: list[dict] = []
    seen_ids: set[int] = set()
    for tier, queries in tiers:
        for query in queries:
            all_scored.extend(_search_tier(query, tier, subject, api_key, seen_ids))
        good_enough = [c for c in all_scored if c["score"] >= MIN_ACCEPTABLE_SCORE]
        if len(good_enough) >= min_count:
            break

    if not all_scored and subject:
        # Nothing at all from the tiered queries (e.g. LLM left a tier
        # empty and the others returned zero results) -- last-resort
        # generic search off the subject itself, explicitly logged as
        # generic_fallback rather than silently reusing a higher label.
        all_scored.extend(_search_tier(subject, "generic_fallback", subject, api_key, seen_ids))

    if not all_scored:
        raise RuntimeError(f"no Pexels results for visual plan: {visual_plan}")

    all_scored.sort(key=lambda c: c["score"], reverse=True)
    selected = all_scored[:min_count]
    pool = [c["video"] for c in selected]
    log = [
        {
            "query": c["query"],
            "clip_id": c["video"]["id"],
            "clip_description": _describe_clip(c["video"]),
            "clip_url": c["video"].get("url"),
            "match_type": c["match_type"],
            "relevance_score": c["score"],
        }
        for c in selected
    ]
    return pool, log


def _download_clip(video: dict, out_path: Path) -> None:
    file_url = _pick_video_file(video)
    response = requests.get(file_url, timeout=60)
    response.raise_for_status()
    out_path.write_bytes(response.content)


def _plan_segment_frames(target_duration: float) -> list[int]:
    """Split a duration's frame count into ~SEGMENT_TARGET_SECONDS chunks,
    exact to the frame — remainder frames go to the earliest segments so
    the sum always equals the real target exactly, same discipline as
    visuals_code.py's per-step frame accounting.
    """
    total_frames = round(target_duration * FPS)
    num_segments = max(1, round(target_duration / SEGMENT_TARGET_SECONDS))
    base = total_frames // num_segments
    remainder = total_frames % num_segments
    return [base + (1 if i < remainder else 0) for i in range(num_segments)]


def _build_segment_clip(source_path: Path, frame_count: int, output_path: Path) -> None:
    """Scale/crop the source clip to exactly 1080x1920 and loop it to an
    exact frame count. Cutting by -frames:v at a forced output fps, not by
    -t at the source's native fps — -t against a looped non-30fps source
    drifted noticeably (multi-loop rounding), which is exact-duration
    wrong for something a narration audio track gets muxed against.
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")

    vf = (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},fps={FPS}"
    )
    result = subprocess.run(
        [
            ffmpeg_path, "-y",
            "-stream_loop", "-1", "-i", str(source_path),
            "-vf", vf,
            "-an",
            "-frames:v", str(frame_count),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")


def _concat_segments(segment_paths: list[Path], output_path: Path) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in segment_paths:
            escaped = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        filelist_path = f.name

    try:
        # All segments share identical codec/resolution/fps (our own
        # encode above), so a stream-copy concat is safe and exact.
        result = subprocess.run(
            [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", filelist_path,
             "-c", "copy", str(output_path)],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed (exit {result.returncode}): {result.stderr}")
    finally:
        os.unlink(filelist_path)


_STOCK_FOOTAGE_TEMPLATES = ("facts", "sauce_recipe")


def _parse_beat_visual_plan(raw_keywords: str) -> dict:
    """beat["keywords"] holds the tiered visual plan as JSON (see
    plan.py/_parse_facts_response) -- {"subject", "exact",
    "representation", "concept"}. Falls back to treating it as the old
    flat comma-separated keyword list (all in the exact_subject tier) for
    any video planned before this change and still resumable.
    """
    try:
        plan = json.loads(raw_keywords)
        if isinstance(plan, dict) and "exact" in plan:
            return plan
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "subject": None,
        "exact": [k.strip() for k in raw_keywords.split(",") if k.strip()],
        "representation": [],
        "concept": [],
    }


def visuals_facts(video_id: str) -> str:
    """Despite the name, this renders any template whose video_steps are
    just script_text + keywords per beat, with B-roll matched per beat —
    "facts" originally, "sauce_recipe" too (a sauce's ingredients/method
    beat needs the exact same keyword -> stock-clip -> trim-to-narration
    pipeline a trivia beat does, just with cooking-action keywords instead
    of trivia-subject ones). Not renamed to something more generic since
    every real call site already imports it as `visuals_facts`.
    """
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if video["template"] not in _STOCK_FOOTAGE_TEMPLATES:
        raise ValueError(
            f"visuals_facts only applies to {_STOCK_FOOTAGE_TEMPLATES}, got {video['template']!r}"
        )

    beats = get_video_steps(video_id)
    if not beats:
        raise ValueError(
            f"video {video_id} has no video_steps — regenerate it with the current plan.py "
            "(older rows predate the per-fact beat format)"
        )
    missing_duration = [b["step_index"] for b in beats if not b["duration"]]
    if missing_duration:
        raise ValueError(
            f"video {video_id} beats {missing_duration} have no duration — run voice() first; "
            "each beat's visual timing comes from its own synthesized audio"
        )
    missing_keywords = [b["step_index"] for b in beats if not b["keywords"]]
    if missing_keywords:
        raise ValueError(f"video {video_id} beats {missing_keywords} have no keywords")

    backend = os.environ.get("FACTS_VISUAL_SOURCE", "stock")
    if backend != "stock":
        raise NotImplementedError(f"FACTS_VISUAL_SOURCE={backend!r} not implemented yet (only 'stock')")

    api_key = os.environ.get("PEXELS_API_KEY")
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY not set — required for FACTS_VISUAL_SOURCE=stock")

    visual_log: list[dict] = []

    with tempfile.TemporaryDirectory(prefix="visuals_facts_") as tmp:
        tmp_dir = Path(tmp)
        beat_clip_paths: list[Path] = []

        for bi, beat in enumerate(beats):
            # beat["duration"] already includes BEAT_PAUSE_SECONDS of real
            # trailing silence for every non-final beat (voice.py bakes it
            # into the step's own audio file) -- no extra tail footage
            # needed here since there's no crossfade consuming one anymore.
            clip_duration = beat["duration"]

            visual_plan = _parse_beat_visual_plan(beat["keywords"])
            beat_frames = _plan_segment_frames(clip_duration)
            pool, pool_log = _build_clip_pool(visual_plan, api_key, min_count=len(beat_frames))
            for entry in pool_log:
                visual_log.append({"beat": beat["step_index"], "subject": visual_plan.get("subject"), **entry})

            source_paths = []
            for i, clip in enumerate(pool):
                source_path = tmp_dir / f"beat{beat['step_index']}_source_{i:02d}.mp4"
                _download_clip(clip, source_path)
                source_paths.append(source_path)

            sub_segment_paths = []
            for i, frame_count in enumerate(beat_frames):
                source = source_paths[i % len(source_paths)]
                seg_path = tmp_dir / f"beat{beat['step_index']}_seg_{i:03d}.mp4"
                _build_segment_clip(source, frame_count, seg_path)
                sub_segment_paths.append(seg_path)

            beat_clip_path = tmp_dir / f"beat{beat['step_index']}_full.mp4"
            _concat_segments(sub_segment_paths, beat_clip_path)
            beat_clip_paths.append(beat_clip_path)

        output_path = OUTPUT_DIR / f"{video_id}_facts.mp4"
        _concat_segments(beat_clip_paths, output_path)

    log_path = OUTPUT_DIR / f"{video_id}_visual_log.json"
    log_path.write_text(json.dumps(visual_log, indent=2), encoding="utf-8")

    update_video(video_id, status="visuals_ready", video_path=str(output_path))
    return str(output_path)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        voiced = [v for v in list_by_status("voiced") if v["template"] in _STOCK_FOOTAGE_TEMPLATES]
        if voiced:
            video_id_arg = voiced[0]["id"]
        else:
            scripted = [v for v in list_by_status("scripted") if v["template"] in _STOCK_FOOTAGE_TEMPLATES]
            if not scripted:
                raise SystemExit(f"no {_STOCK_FOOTAGE_TEMPLATES} videos in state.db — run plan.py first")
            video_id_arg = scripted[0]["id"]
            print(f"video {video_id_arg} has no audio yet — running voice() first")
            voice(video_id_arg)

    path = visuals_facts(video_id_arg)
    print(f"video_id:  {video_id_arg}")
    print(f"output:    {path}")
    print(f"visual log: {OUTPUT_DIR / (video_id_arg + '_visual_log.json')}")
