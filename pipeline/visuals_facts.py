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
    doesn't just trust the search tier a candidate came from.

    REAL BUG this fixes, caught on a live test run: a query like "Slinky
    toy walking down stairs" shares generic scene words ("down",
    "stairs") with a completely unrelated "person walking down stairs"
    clip that has nothing to do with a Slinky. Checking overlap against
    the whole query let that pass as exact_subject. The subject
    ("Slinky spring toy") is the actual named thing that must appear --
    checking against the FULL query lets incidental scene-setting words
    manufacture false overlap. Trust/demotion now requires overlap with
    the SUBJECT specifically (falls back to query overlap only when no
    subject is known -- legacy flat-keyword videos with no subject
    field). Query overlap still contributes to the score itself, just
    not to whether the tier label is trusted.
    """
    description = _describe_clip(video)
    desc_tokens = _significant_tokens(description)
    subject_tokens = _significant_tokens(subject)
    query_tokens = _significant_tokens(query)

    subject_overlap = len(subject_tokens & desc_tokens)
    query_overlap = len(query_tokens & desc_tokens)
    # No subject known (legacy data) -- query overlap is the only signal available.
    trust_overlap = subject_overlap if subject_tokens else query_overlap

    match_type = tier
    if trust_overlap == 0 and tier in _TIER_DEMOTION:
        match_type = _TIER_DEMOTION[tier]
        score = _TIER_BASE_SCORE[match_type] - _ZERO_OVERLAP_PENALTY
    else:
        bonus = min(15, subject_overlap * 7 + query_overlap * 3)
        score = _TIER_BASE_SCORE[tier] + bonus
    return max(0, score), match_type


def _search_tier(query: str, tier: str, subject: str, api_key: str, seen_ids: set[int]) -> list[dict]:
    """One tier's worth of scored, deduped candidates for one query.
    per_page=10 (not 5) -- same single API call, just asks Pexels for
    more results per query, at zero extra API cost -- so the diversity
    selector below actually has spare candidates to pick a varied SET
    from instead of being forced to take everything found.
    """
    scored = []
    for video in _search_pexels_videos(query, api_key, per_page=10):
        if video["id"] in seen_ids:
            continue
        seen_ids.add(video["id"])
        score, match_type = _score_candidate(video, query, tier, subject)
        scored.append({"video": video, "query": query, "tier": tier, "match_type": match_type, "score": score})
    return scored


# Visual diversity selection (real failure this fixes: a beat selected 3
# technically-distinct Pexels clips -- 6928978, 32893132, 6177769 -- that
# were all near-identical "hand placing a sticky note on a plain wall"
# shots. Different IDs is not the same thing as different footage.
MAX_DIVERSITY_PENALTY = 30  # capped so a much stronger, similar candidate can still beat a much weaker, diverse one (see tests)
_FUZZY_PREFIX_LEN = 4  # catches word-form variants a literal set intersection misses: "sticky"/"sticking", "note"/"notes"


def _fuzzy_token_overlap(tokens_a: set[str], tokens_b: set[str]) -> int:
    """Counts tokens that match exactly OR share a >= _FUZZY_PREFIX_LEN
    character prefix, each token in b used at most once. Plain set
    intersection missed the real sticky-note case: "hand getting a
    sticky note" vs "hand sticking notes on white wall" share only
    "hand" by exact match, even though "sticky"/"sticking" and
    "note"/"notes" are obviously the same real-world thing.
    """
    remaining_b = set(tokens_b)
    matched = 0
    for ta in tokens_a:
        hit = None
        for tb in remaining_b:
            if ta == tb or (len(ta) >= _FUZZY_PREFIX_LEN and len(tb) >= _FUZZY_PREFIX_LEN and ta[:_FUZZY_PREFIX_LEN] == tb[:_FUZZY_PREFIX_LEN]):
                hit = tb
                break
        if hit is not None:
            matched += 1
            remaining_b.discard(hit)
    return matched


def _text_similarity(description_a: str, description_b: str) -> float:
    """0.0 (nothing in common) to 1.0 (same real-world shot) -- fuzzy
    Jaccard over each description's significant tokens. Cheap,
    deterministic, no LLM call, reuses the same tokenizer already built
    for relevance scoring."""
    tokens_a = _significant_tokens(description_a)
    tokens_b = _significant_tokens(description_b)
    if not tokens_a or not tokens_b:
        return 0.0
    matched = _fuzzy_token_overlap(tokens_a, tokens_b)
    union_size = len(tokens_a) + len(tokens_b) - matched
    return matched / union_size if union_size else 0.0


def _diversity_penalty(video: dict, selected: list[dict]) -> tuple[int, int | None]:
    """Penalty against the MOST similar already-selected candidate (the
    worst case, not a sum across all of them -- one close match is what
    makes a set feel repetitive, penalizing against every selected clip
    cumulatively would over-punish a large, otherwise-fine selection)."""
    if not selected:
        return 0, None
    description = _describe_clip(video)
    best_similarity = 0.0
    most_similar_id = None
    for s in selected:
        similarity = _text_similarity(description, _describe_clip(s["video"]))
        if similarity > best_similarity:
            best_similarity = similarity
            most_similar_id = s["video"]["id"]
    penalty = round(best_similarity * MAX_DIVERSITY_PENALTY)
    return penalty, (most_similar_id if penalty > 0 else None)


def _select_diverse_set(candidates: list[dict], min_count: int, beat_label: str = "") -> tuple[list[dict], list[dict]]:
    """Greedy diversity-aware selection: select the best SET, not the
    top-N scored independently. Each round, every remaining candidate's
    diversity-adjusted score (base relevance - similarity penalty
    against everything already selected) is recomputed, and the best one
    wins -- so a candidate that looked strong before anything was
    selected can still lose out once something too similar is already
    in the set. See MAX_DIVERSITY_PENALTY for why relevance still wins
    over "different at any cost" (a much weaker, merely-diverse
    candidate can't out-score a much stronger, moderately-similar one).

    Deduplicates by video id itself (doesn't just trust the caller's own
    seen_ids bookkeeping) -- defense in depth, same real ID can never be
    selected twice regardless of how many times it appears in `candidates`.
    """
    seen_ids: set = set()
    remaining: list[dict] = []
    for c in candidates:
        vid = c["video"]["id"]
        if vid in seen_ids:
            continue
        seen_ids.add(vid)
        remaining.append(c)
    selected: list[dict] = []
    log: list[dict] = []

    while remaining and len(selected) < min_count:
        scored_round = []
        for c in remaining:
            penalty, similar_to = _diversity_penalty(c["video"], selected)
            scored_round.append((c["score"] - penalty, penalty, similar_to, c))
        scored_round.sort(key=lambda t: t[0], reverse=True)
        final_score, penalty, similar_to, winner = scored_round[0]

        remaining.remove(winner)
        selected.append(winner)
        reason = "highest relevance" if not selected[:-1] else (
            "too similar to already-selected clip(s), but still the best available" if penalty >= MAX_DIVERSITY_PENALTY
            else "diversity-adjusted top pick"
        )
        log.append({
            "clip_id": winner["video"]["id"], "query": winner["query"], "tier": winner["tier"],
            "match_type": winner["match_type"], "clip_description": _describe_clip(winner["video"]),
            "clip_url": winner["video"].get("url"), "base_score": winner["score"],
            "diversity_penalty": penalty, "relevance_score": final_score,
            "similar_to": [similar_to] if similar_to else [], "selection_reason": reason,
        })
        print(
            f"[visual diversity] {beat_label}candidate {winner['video']['id']}: "
            f"base={winner['score']} penalty=-{penalty} final={final_score} "
            f"SELECTED ({reason}{f', similar to {similar_to}' if similar_to else ''})"
        )
    return selected, log


def _build_clip_pool(
    visual_plan: dict, api_key: str, min_count: int, beat_label: str = ""
) -> tuple[list[dict], list[dict]]:
    """Searches the beat's visual plan tier by tier -- exact_subject
    first, then accurate_representation, then concept_explanation,
    falling back to a generic search built from the subject alone only
    if nothing scored acceptably. Stops early once there's real SLACK
    beyond min_count (not just barely enough) -- diversity selection
    needs genuine alternatives to choose between, or it can only pick
    the order of an unchanged set, not the set itself. Returns the
    diversity-aware selection (see _select_diverse_set) plus a log entry
    per SELECTED candidate for {video_id}_visual_log.json.
    """
    subject = visual_plan.get("subject") or ""
    tiers = [
        ("exact_subject", visual_plan.get("exact") or []),
        ("accurate_representation", visual_plan.get("representation") or []),
        ("concept_explanation", visual_plan.get("concept") or []),
    ]

    all_scored: list[dict] = []
    seen_ids: set[int] = set()
    slack_target = min_count * 2  # room for diversity to actually reject near-duplicates
    for tier, queries in tiers:
        for query in queries:
            all_scored.extend(_search_tier(query, tier, subject, api_key, seen_ids))
        good_enough = [c for c in all_scored if c["score"] >= MIN_ACCEPTABLE_SCORE]
        if len(good_enough) >= slack_target:
            break

    if not all_scored and subject:
        # Nothing at all from the tiered queries (e.g. LLM left a tier
        # empty and the others returned zero results) -- last-resort
        # generic search off the subject itself, explicitly logged as
        # generic_fallback rather than silently reusing a higher label.
        all_scored.extend(_search_tier(subject, "generic_fallback", subject, api_key, seen_ids))

    if not all_scored:
        raise RuntimeError(f"no Pexels results for visual plan: {visual_plan}")

    selected, selection_log = _select_diverse_set(all_scored, min_count, beat_label)
    pool = [c["video"] for c in selected]
    return pool, selection_log


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
            pool, pool_log = _build_clip_pool(visual_plan, api_key, min_count=len(beat_frames), beat_label=f"beat {beat['step_index']}: ")
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
