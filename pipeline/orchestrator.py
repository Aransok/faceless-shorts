"""Phase 9: orchestrator — drives videos through every stage in order,
resuming partially-completed ones instead of restarting, and stopping
cleanly at review or a real failure rather than crashing the whole run.
See SPEC.md / ROADMAP.md Phase 9.
"""

from __future__ import annotations

import sys
import time
import traceback

from pipeline.assemble import assemble
from pipeline.captions import captions
from pipeline.metadata import generate_metadata
from pipeline.plan import plan
from pipeline.plan_game import plan_game_night
from pipeline.plan_quiz import plan_quiz
from pipeline.state import get_video, list_by_status, update_video
from pipeline.upload import upload
from pipeline.visuals_code import visuals_code
from pipeline.visuals_facts import visuals_facts
from pipeline.visuals_game import visuals_game
from pipeline.visuals_quiz import visuals_quiz
from pipeline.voice import voice

# The daily Shorts rotation, picked via TEMPLATES[i % len(TEMPLATES)] below
# -- quiz_longform is weekly, separate entrypoint. Real per-video view data
# (see ROADMAP.md's growth-diagnosis session, 2026-09-10) showed facts and
# sauce_recipe running 2.8-4x programming's views on the same channel, same
# review pipeline -- weighted 2:2:1 toward facts/sauce_recipe over
# programming instead of the old even 3-way split. Order deliberately
# avoids two same-template slots back to back.
TEMPLATES = ("facts", "sauce_recipe", "programming", "facts", "sauce_recipe")

# A previous run stopped here (killed, crashed, or just ended) but the
# video isn't done and isn't waiting on a human — safe to keep driving.
RESUMABLE_STATUSES = ("scripted", "voiced", "visuals_ready", "assembled", "captioned", "approved")

# Statuses where the orchestrator must stop touching this video: it's
# finished, a human needs to act (awaiting_review), or it needs manual
# investigation (failed — never auto-retried, to avoid looping on a
# systematically broken stage).
TERMINAL_STATUSES = ("awaiting_review", "uploaded", "failed")


# status -> a real stage name for timing logs, since the status value
# itself ("scripted", "voiced", ...) is the status you're advancing FROM,
# not the stage that runs -- confusing in a log without this mapping.
_STAGE_NAMES = {
    "scripted": "voice",
    "voiced": "visuals",
    "visuals_ready": "assemble",
    "assembled": "captions",
    "captioned": "metadata",
    "approved": "upload",
}


def _advance_one_stage(video_id: str) -> str:
    """Runs exactly the next stage for this video's current status.
    Returns the resulting status. Prints real wall-clock timing for the
    stage -- CI's own per-step timing (visible via `gh run view --json
    jobs`) only sees the single "Run daily pipeline" step as one opaque
    block; this is the only way to see which stage inside it actually
    costs the minutes.
    """
    video = get_video(video_id)
    status = video["status"]
    template = video["template"]
    stage_name = _STAGE_NAMES.get(status, status)

    t0 = time.monotonic()
    if status == "scripted":
        voice(video_id)
    elif status == "voiced":
        if template == "programming":
            visuals_code(video_id)
        elif template == "quiz_longform":
            visuals_quiz(video_id)
        elif template == "game_night":
            visuals_game(video_id)
        else:
            visuals_facts(video_id)
    elif status == "visuals_ready":
        assemble(video_id)
    elif status == "assembled":
        captions(video_id)
    elif status == "captioned":
        generate_metadata(video_id)
    elif status == "approved":
        upload(video_id)
    else:
        raise ValueError(f"no stage to advance from status {status!r}")
    elapsed = time.monotonic() - t0

    new_status = get_video(video_id)["status"]
    print(f"[timing] video={video_id} template={template} stage={stage_name} ({status}->{new_status}) {elapsed:.1f}s")
    return new_status


def run_video_to_completion(video_id: str) -> dict:
    """Drives one video forward stage by stage until it hits a terminal
    status (awaiting_review, uploaded, failed) or a real error, which is
    caught and recorded rather than allowed to crash the whole batch.
    Times from the moment this call starts (not the video's original
    creation time) -- for a resumed video that's the right number: how
    much of THIS run's wall-clock time it actually cost.
    """
    video_start = time.monotonic()
    while True:
        video = get_video(video_id)
        status = video["status"]
        if status in TERMINAL_STATUSES:
            elapsed = time.monotonic() - video_start
            print(f"[timing] video={video_id} template={video['template']} TOTAL {elapsed:.1f}s (final status={status})")
            return {
                "video_id": video_id,
                "template": video["template"],
                "status": status,
                "error": video["error_message"],
            }
        try:
            _advance_one_stage(video_id)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            update_video(video_id, status="failed", error_message=error_message[:2000])
            traceback.print_exc()
            elapsed = time.monotonic() - video_start
            print(f"[timing] video={video_id} template={get_video(video_id)['template']} TOTAL {elapsed:.1f}s (FAILED)")
            return {
                "video_id": video_id,
                "template": get_video(video_id)["template"],
                "status": "failed",
                "error": error_message,
            }


def run_daily(count: int, templates: list[str] | None = None) -> list[dict]:
    """Resumes any in-flight videos first, then starts new ones, driving
    each to a terminal status. Safe to re-run after an interrupted run —
    resumable videos pick up from wherever they stopped instead of
    restarting from plan() (and since a `scripted` video skips straight
    to voice(), resuming one costs no extra plan()/review calls — free
    reuse of work already paid for).

    `templates`, when given, is run as an exact sequence in the order
    given (e.g. `["sauce_recipe", "sauce_recipe"]` for two sauce videos
    specifically) instead of cycling the default TEMPLATES rotation —
    lets a manual trigger ask for a specific mix rather than the daily
    default. `count` is ignored when `templates` is given.
    """
    batch_start = time.monotonic()
    results = []

    resumable_ids = []
    for status in RESUMABLE_STATUSES:
        resumable_ids += [v["id"] for v in list_by_status(status)]

    for video_id in resumable_ids:
        print(f"resuming {video_id}...")
        results.append(run_video_to_completion(video_id))

    sequence = templates if templates else [TEMPLATES[i % len(TEMPLATES)] for i in range(count)]
    for i, template in enumerate(sequence):
        print(f"starting new {template} video ({i + 1}/{len(sequence)})...")
        plan_start = time.monotonic()
        try:
            video_id = plan(template)
        except Exception as exc:
            error_message = f"{type(exc).__name__}: {exc}"
            print(f"plan() failed for {template}: {error_message}")
            traceback.print_exc()
            results.append({"video_id": None, "template": template, "status": "failed", "error": error_message})
            continue
        print(f"[timing] video={video_id} template={template} stage=plan (->scripted) {time.monotonic() - plan_start:.1f}s")
        results.append(run_video_to_completion(video_id))

    print(f"[timing] run_daily TOTAL {time.monotonic() - batch_start:.1f}s for {len(results)} video(s)")
    return results


def run_weekly_quiz() -> dict:
    """The quiz longform track's own entrypoint — separate from
    run_daily() since it's a different, lower-frequency cadence (weekly,
    not daily) with its own script generator (plan_quiz.py). Still
    resumes any in-flight quiz video first, same resumability guarantee
    as run_daily().
    """
    resumable_quiz_ids = [
        v["id"] for status in RESUMABLE_STATUSES for v in list_by_status(status) if v["template"] == "quiz_longform"
    ]
    for video_id in resumable_quiz_ids:
        print(f"resuming {video_id}...")
        result = run_video_to_completion(video_id)
        if result["status"] in ("awaiting_review", "uploaded"):
            return result
        # a resumed video that ended up "failed" doesn't block starting
        # a fresh one below — it's already recorded, move on.

    print("starting new quiz_longform video...")
    plan_start = time.monotonic()
    try:
        video_id = plan_quiz()
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        print(f"plan_quiz() failed: {error_message}")
        traceback.print_exc()
        return {"video_id": None, "template": "quiz_longform", "status": "failed", "error": error_message}
    print(f"[timing] video={video_id} template=quiz_longform stage=plan (->scripted) {time.monotonic() - plan_start:.1f}s")
    return run_video_to_completion(video_id)


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--quiz" in args:
        quiz_result = run_weekly_quiz()
        print()
        print("=== run_weekly_quiz summary ===")
        suffix = f"  ({quiz_result['error']})" if quiz_result["error"] else ""
        print(f"{quiz_result['video_id']}  [{quiz_result['template']}]  {quiz_result['status']}{suffix}")
    else:
        count_arg = 1
        if "--count" in args:
            count_arg = int(args[args.index("--count") + 1])

        run_results = run_daily(count_arg)
        print()
        print("=== run_daily summary ===")
        for r in run_results:
            suffix = f"  ({r['error']})" if r["error"] else ""
            print(f"{r['video_id']}  [{r['template']}]  {r['status']}{suffix}")
