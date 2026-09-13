"""Stage 1 for the family_game_night longform track (2026-09-13):
composes one episode via pipeline/family_game/'s already-built engine
(quality-gated, no-adjacent-repeat, real player thinking time) and
stores it as one JSON blob for render_family_game.py's own render stage
to consume -- see pipeline/state.py's family_game_segments_json column
docstring for why a blob instead of video_steps rows.

A new template name, not a replacement for the older "game_night"
track (pipeline/plan_game.py) -- the owner's own call (see ROADMAP.md):
ship this once it's been watched end to end via a real GitHub Actions
run, rather than silently swap the live rotation's game_night slot out
from under it.
"""

from __future__ import annotations

import json

from pipeline.family_game.episode import flatten_episode_to_segments
from pipeline.family_game.quality_gate import compose_episode_with_quality_gate
from pipeline.state import create_video, get_video, update_video

TEMPLATE = "family_game_night"


def plan_family_game_night() -> str:
    episode = compose_episode_with_quality_gate()
    segments = flatten_episode_to_segments(episode)

    video_id = create_video(TEMPLATE, topic=episode["theme"])
    full_script = " ".join(s["script_text"] for s in segments if s["script_text"])
    update_video(
        video_id,
        status="scripted",
        script_text=full_script,
        hook=episode["intro"],
        family_game_segments_json=json.dumps(segments),
    )
    return video_id


if __name__ == "__main__":
    new_id = plan_family_game_night()
    video = get_video(new_id)
    print(f"video_id: {new_id}")
    print(f"topic:    {video['topic']}")
    print(f"hook:     {video['hook']}")
