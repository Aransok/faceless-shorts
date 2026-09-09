"""Stage 2 (voice): script text -> audio file. See SPEC.md."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from pipeline.state import get_video, get_video_steps, list_by_status, update_video, update_video_step

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"

load_dotenv(PROJECT_ROOT / ".env")

EDGE_TTS_VOICE = os.environ.get("EDGE_TTS_VOICE", "en-US-AndrewNeural")
# 1.08x -- middle of the requested 1.05-1.1x range. edge_tts's Communicate
# takes a percentage-string rate, not a multiplier.
EDGE_TTS_RATE = "+8%"

# edge_tts's Communicate() always treats `text` as plain text to be
# escaped into its own SSML envelope -- confirmed directly: a literal
# "<break time=...>" tag embedded in `text` gets spoken out loud as words
# ("break", "time", "600ms"), not respected as a pause. There's no raw-SSML
# entry point on the public API (Communicate exposes save/save_sync/
# stream/stream_sync only). Real pauses between sentences are built by
# synthesizing each sentence as its own edge_tts call and concatenating,
# not by asking edge_tts for a pause directly.
#
# SENTENCE_PAUSE_SECONDS is 0.0 -- measured for real (not guessed): simply
# splitting into separate calls and concatenating already produces a
# natural ~0.45s gap at the boundary on its own (each call's own
# lead/trail silence stacking at the seam), comfortably inside the
# "brief, natural, not dead air" target with zero extra padding. Adding
# even a modest explicit pad on top (tested at 0.22s) overshot to ~0.73s,
# noticeably longer than intended. Real per-call silence varies somewhat
# by voice/content, so this is a calibrated starting point, not a
# guarantee -- worth re-measuring if the voice changes.
SENTENCE_PAUSE_SECONDS = 0.0
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")

# facts/sauce_recipe beats used to run straight into each other with only
# a 0.5s visual crossfade and zero audio gap -- real complaint: they blend
# together instead of reading as distinct items. Not applied to
# "programming" (visuals_code.py already has its own deliberate two-stage
# fade-to-blank between steps) or "quiz_longform" (its own
# COUNTDOWN_SECONDS pause system).
BEAT_PAUSE_SECONDS = 3.5
_PAUSED_TEMPLATES = {"facts", "sauce_recipe"}

# game_night: gameplay/reveal/countdown beats show a real on-screen card
# the viewer needs actual time to read (a sequence of icons, a versus
# card, an attribute table) -- but the narration line driving that beat's
# duration is often much shorter (e.g. "It hits!" is well under a
# second). A real watched test episode came out far too fast because of
# exactly this -- the visual was already gone before it could be read.
# Fix: pad each of these beats' own audio up to a floor (only the real
# shortfall, not a flat add-on) so the visual holds long enough
# regardless of how brief the line is.
GAME_NIGHT_MIN_BEAT_SECONDS = {"countdown": 1.5, "gameplay": 3.5, "reveal": 4.0}


def _pad_with_silence(path: Path, seconds: float) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")
    padded_path = path.with_name(path.stem + "_padded" + path.suffix)
    result = subprocess.run(
        [
            ffmpeg_path, "-y", "-i", str(path),
            "-af", f"apad=pad_dur={seconds}",
            str(padded_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg silence-pad failed (exit {result.returncode}): {result.stderr}")
    padded_path.replace(path)


# Real, observed failure (2026-09-09 daily run): edge_tts.exceptions.
# NoAudioReceived, a known transient failure of the free Microsoft
# endpoint edge_tts talks to -- not a parameter/config problem (the
# library's own error message is misleading about that). Retrying with a
# short backoff is the real fix other edge_tts users report working;
# only retries this specific exception, so a real config problem still
# fails fast instead of being masked.
EDGE_TTS_RETRY_DELAYS = (1, 3, 6)


async def _synth_one_edge_tts_call(text: str, out_path: Path) -> list[dict]:
    """One real edge_tts call, one sentence or the whole text — returns its
    word list with start/end in seconds, relative to this call's own audio
    (no cumulative offset applied yet)."""
    import edge_tts

    async def _attempt() -> list[dict]:
        communicate = edge_tts.Communicate(text, EDGE_TTS_VOICE, rate=EDGE_TTS_RATE, boundary="WordBoundary")
        words: list[dict] = []
        with open(out_path, "wb") as audio_file:
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_file.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    start = chunk["offset"] / 1e7
                    words.append({"word": chunk["text"], "start": start, "end": start + chunk["duration"] / 1e7})
        return words

    last_exc: BaseException | None = None
    for delay in (0,) + EDGE_TTS_RETRY_DELAYS:
        if delay:
            await asyncio.sleep(delay)
        try:
            return await _attempt()
        except edge_tts.exceptions.NoAudioReceived as exc:
            last_exc = exc
    raise last_exc


def _synthesize_edge_tts(text: str, out_path: Path) -> None:
    """Captures real word-level timestamps directly from edge_tts's own
    WordBoundary events (a sidecar {out_path}.words.json) alongside the
    audio — accurate through pauses in a way re-transcribing our own
    generated audio with faster-whisper afterward can't be, since Whisper
    has to guess word boundaries after the fact and that guess gets worse
    right around silence. captions.py prefers this when present, falling
    back to Whisper only for backends (e.g. kokoro) that don't expose it.

    Splits multi-sentence text into separate synthesis calls, each padded
    with SENTENCE_PAUSE_SECONDS of real silence (except the last), so
    narration gets an actual brief pause at sentence boundaries instead of
    edge_tts's own uniform pacing straight through. Single-sentence text
    (most steps, most of the time) takes the plain single-call path
    unchanged.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]

    async def _run_single() -> list[dict]:
        return await _synth_one_edge_tts_call(text, out_path)

    async def _run_multi() -> list[dict]:
        all_words: list[dict] = []
        cumulative = 0.0
        with tempfile.TemporaryDirectory(prefix="edge_tts_sentences_") as tmp:
            tmp_dir = Path(tmp)
            sentence_paths = []
            for i, sentence in enumerate(sentences):
                sentence_path = tmp_dir / f"sentence_{i:03d}.mp3"
                words = await _synth_one_edge_tts_call(sentence, sentence_path)
                is_last = i == len(sentences) - 1
                if not is_last and SENTENCE_PAUSE_SECONDS > 0:
                    _pad_with_silence(sentence_path, SENTENCE_PAUSE_SECONDS)
                for w in words:
                    all_words.append({"word": w["word"], "start": w["start"] + cumulative, "end": w["end"] + cumulative})
                cumulative += audio_duration_seconds(sentence_path)
                sentence_paths.append(sentence_path)
            _concat_audio(sentence_paths, out_path)
        return all_words

    if len(sentences) <= 1:
        words = asyncio.run(_run_single())
    else:
        words = asyncio.run(_run_multi())

    words_path = out_path.with_name(out_path.name + ".words.json")
    words_path.write_text(json.dumps(words, indent=2), encoding="utf-8")


def _synthesize_kokoro(text: str, out_path: Path) -> None:
    import soundfile as sf
    from kokoro_onnx import Kokoro

    model_path = os.environ.get("KOKORO_MODEL_PATH", "kokoro-v1.0.onnx")
    voices_path = os.environ.get("KOKORO_VOICES_PATH", "voices-v1.0.bin")
    voice = os.environ.get("KOKORO_VOICE", "am_adam")

    kokoro = Kokoro(model_path, voices_path)
    samples, sample_rate = kokoro.create(text, voice=voice, speed=1.0, lang="en-us")
    sf.write(str(out_path), samples, sample_rate)


_BACKENDS = {
    "edge_tts": (_synthesize_edge_tts, "mp3"),
    "kokoro": (_synthesize_kokoro, "wav"),
}


def synthesize(text: str, out_path: Path, backend: str) -> Path:
    if backend not in _BACKENDS:
        raise ValueError(f"unknown TTS_BACKEND: {backend!r} (expected {sorted(_BACKENDS)})")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    synth_fn, _ = _BACKENDS[backend]
    synth_fn(text, out_path)
    return out_path


def audio_duration_seconds(path: Path) -> float:
    from mutagen import File as MutagenFile

    audio = MutagenFile(path)
    if audio is None or audio.info is None:
        raise ValueError(f"could not read audio metadata from {path}")
    return audio.info.length


def _concat_audio(paths: list[Path], output_path: Path) -> None:
    """Concatenate same-codec audio segments in order via ffmpeg's concat
    demuxer (stream copy, no re-encode — segments come from the same TTS
    backend so codec/sample-rate already match).
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
        for p in paths:
            escaped = str(p.resolve()).replace("\\", "/").replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        filelist_path = f.name

    try:
        result = subprocess.run(
            [ffmpeg_path, "-y", "-f", "concat", "-safe", "0", "-i", filelist_path, "-c", "copy", str(output_path)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed (exit {result.returncode}): {result.stderr}")
    finally:
        os.unlink(filelist_path)


def _voice_steps(video_id: str, backend: str, template: str) -> str:
    """Synthesize each step's narration separately so each gets an exact,
    known duration — that's what lets visuals_code.py switch the on-screen
    code/output exactly when each step's narration starts, instead of
    guessing timing from a single narration pass.

    For facts/sauce_recipe, every non-final step also gets BEAT_PAUSE_SECONDS
    of real trailing silence baked into its own audio file — this is what
    creates an actual gap between beats, not just a longer duration number.
    Padding the step's own file (rather than inserting silence at the
    concat stage) means every downstream consumer of step["duration"]
    (visuals_facts.py's B-roll clip sizing, captions.py's cumulative word-
    timestamp offset) picks up the pause automatically, no separate change
    needed in either.
    """
    steps = get_video_steps(video_id)
    _, ext = _BACKENDS[backend]
    add_pause = template in _PAUSED_TEMPLATES
    is_game_night = template == "game_night"

    step_paths = []
    for i, step in enumerate(steps):
        step_path = OUTPUT_DIR / f"{video_id}_step{step['step_index']}_{backend}.{ext}"
        synthesize(step["script_text"], step_path, backend=backend)
        if add_pause and i < len(steps) - 1:
            _pad_with_silence(step_path, BEAT_PAUSE_SECONDS)
        duration = audio_duration_seconds(step_path)
        if is_game_night:
            floor = GAME_NIGHT_MIN_BEAT_SECONDS.get(step["beat_type"])
            if floor is not None and duration < floor:
                _pad_with_silence(step_path, floor - duration)
                duration = floor
        update_video_step(video_id, step["step_index"], audio_path=str(step_path), duration=duration)
        step_paths.append(step_path)

    final_path = OUTPUT_DIR / f"{video_id}_{backend}.{ext}"
    _concat_audio(step_paths, final_path)
    return str(final_path)


def voice(video_id: str, backend: str | None = None) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")

    backend = backend or os.environ.get("TTS_BACKEND", "edge_tts")

    if get_video_steps(video_id):
        out_path = _voice_steps(video_id, backend, video["template"])
    else:
        _, ext = _BACKENDS[backend]
        out_path = OUTPUT_DIR / f"{video_id}_{backend}.{ext}"
        synthesize(video["script_text"], out_path, backend=backend)
        out_path = str(out_path)

    update_video(video_id, status="voiced", audio_path=out_path)
    return out_path


if __name__ == "__main__":
    args = sys.argv[1:]
    backend_arg = args[1] if len(args) > 1 else os.environ.get("TTS_BACKEND", "edge_tts")

    if args and args[0] != "--latest":
        video_id_arg = args[0]
    else:
        scripted = list_by_status("scripted") or list_by_status("voiced")
        if not scripted:
            raise SystemExit("no scripted videos in state.db — run plan.py first")
        video_id_arg = scripted[0]["id"]

    audio_path = voice(video_id_arg, backend=backend_arg)
    duration = audio_duration_seconds(Path(audio_path))
    print(f"video_id: {video_id_arg}")
    print(f"backend:  {backend_arg}")
    print(f"audio:    {audio_path}")
    print(f"duration: {duration:.1f}s")
