"""Stage 1 for the game-night longform track (Phase 16) -- assembles one
episode from a real, no-adjacent-repeat sequence of the 5 round modules
(pipeline/games/), carrying one GameSession's lives/points across all of
them. Deliberately no LLM call for the episode-level glue narration
(intro/outro) -- only the two content modules that need real facts
(higher_or_lower, prediction) call the LLM; the shared framing text is
plain, rotated via the same pick_rotating() mechanism as everything else
in the pipeline that needs "not always identical" without needing a full
generation call for two sentences of scaffolding.
"""

from __future__ import annotations

import json

from pipeline.games import higher_or_lower, memory, prediction, risk_or_safe, what_changed
from pipeline.games.base import FALLBACK_ROUND_TYPES, GameSession, RoundVerificationFailed, select_rounds
from pipeline.rotation import pick_rotating
from pipeline.state import create_video, create_video_steps, get_video, get_video_steps, update_video

TEMPLATE = "game_night"
DEFAULT_ROUND_COUNT = 5

_MODULES = {
    "higher_or_lower": higher_or_lower,
    "memory": memory,
    "what_changed": what_changed,
    "risk_or_safe": risk_or_safe,
    "prediction": prediction,
}

_INTRO_LINES = (
    "Alright, it's game night. Let's see how this one goes.",
    "Welcome back for another round of game night.",
    "Game night. Let's get into it.",
)
_OUTRO_LINES = (
    "That's the episode. Subscribe if you're into these.",
    "That's a wrap on tonight's rounds. Stick around for more of these.",
    "And that's game night. If you liked this, subscribing helps a lot.",
)


def _round_topic(round_type: str, beats: list[dict]) -> str | None:
    """Pulls the real subject/category out of a round's own generated
    data (not guessed) so the rest of THIS episode avoids repeating it."""
    for beat in beats:
        if beat.get("round_data_json"):
            data = json.loads(beat["round_data_json"])
            topic = data.get("category") or data.get("subject_name")
            if topic:
                return topic
    return None


def _generate_one_round(
    round_type: str, session: GameSession, avoid_topics: list[str], round_index: int, previous_type: str | None
) -> tuple[str, list[dict], GameSession]:
    """Runs round_type's generate_round(). If verify_claim() rejects every
    retry (RoundVerificationFailed -- see base.py), substitutes a
    FALLBACK_ROUND_TYPES module instead of failing the whole episode --
    owner's explicit call, not a guess. Prefers a fallback type that isn't
    the immediately preceding round, same no-adjacent-repeat rule as the
    normal selector.
    """
    module = _MODULES[round_type]
    try:
        beats, session = module.generate_round(session, avoid_topics, round_index)
        return round_type, beats, session
    except RoundVerificationFailed as exc:
        print(f"[plan_game] {round_type} round {round_index} failed verification, substituting: {exc}")
        candidates = [t for t in FALLBACK_ROUND_TYPES if t != previous_type] or list(FALLBACK_ROUND_TYPES)
        fallback_type = candidates[0]
        fallback_module = _MODULES[fallback_type]
        beats, session = fallback_module.generate_round(session, avoid_topics, round_index)
        return fallback_type, beats, session


def plan_game_night(round_count: int = DEFAULT_ROUND_COUNT) -> str:
    round_types = select_rounds(round_count)
    session = GameSession()
    avoid_topics: list[str] = []
    all_beats: list[dict] = []
    actual_round_types: list[str] = []

    previous_type = None
    for i, round_type in enumerate(round_types, start=1):
        actual_type, beats, session = _generate_one_round(round_type, session, avoid_topics, i, previous_type)
        all_beats.extend(beats)
        actual_round_types.append(actual_type)
        topic = _round_topic(actual_type, beats)
        if topic:
            avoid_topics.append(topic)
        previous_type = actual_type

    intro_line = pick_rotating("game_night_intro", list(_INTRO_LINES), limit=1)
    outro_line = pick_rotating("game_night_outro", list(_OUTRO_LINES), limit=1)

    intro_step = {"script_text": intro_line, "round_type": None, "round_index": 0, "beat_type": "intro"}
    outro_step = {
        "script_text": (
            f"Final score: {session.points} points, {max(session.lives, 0)} "
            f"{'life' if session.lives == 1 else 'lives'} left. {outro_line}"
        ),
        "round_type": None,
        "round_index": len(round_types) + 1,
        "beat_type": "score",
        "lives_after": session.lives,
        "points_after": session.points,
    }

    steps = [intro_step, *all_beats, outro_step]
    topic = f"Game Night: {', '.join(actual_round_types)}"

    video_id = create_video(TEMPLATE, topic=topic)
    full_script = " ".join(s["script_text"] for s in steps)
    update_video(video_id, status="scripted", script_text=full_script, hook=intro_line)
    create_video_steps(video_id, steps)
    return video_id


if __name__ == "__main__":
    new_id = plan_game_night()
    video = get_video(new_id)
    steps = get_video_steps(new_id)
    print(f"video_id: {new_id}")
    print(f"topic:    {video['topic']}")
    print(f"steps:    {len(steps)}")
    for s in steps:
        label = f"[{s['round_type'] or 'episode'}/{s['round_index']}/{s['beat_type']}]"
        print(f"  {label:40s} {s['script_text']}")
