"""Stage 2 (captions): burn in word-level-timed styled captions onto the
assembled video, positioned in the lower/middle safe zone — clear of the
upper-third CTA. See SPEC.md.
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel

from pipeline.brand import CAPTION_MARGIN_V_RATIO_PORTRAIT
from pipeline.state import get_video, get_video_steps, list_by_status, update_video

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "assets" / "output"
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"

CHUNK_SIZE = 4  # words per caption line
# Bold sans-serif, not the code-styled monospace — captions are a
# different UI element from the branded editor chrome, and thin/
# decorative faces lose legibility at small caption sizes. Poppins
# ExtraBold (OFL-licensed, from Google Fonts) is already bold enough
# that no synthetic bolding is needed on top of it (see Bold: 0 below).
FONT_NAME = "Poppins"
# Tuned against the 1080x1920 Shorts frame (58px font, 620px margin) —
# expressed as ratios so other resolutions scale proportionally instead
# of using pixel values tuned for one specific frame. Font size scales
# off the SHORTER dimension (1080 either way — Shorts' width, quiz
# longform's height) so text reads at a consistent relative size
# regardless of orientation, not 1.78x oversized on a 1920-wide landscape
# frame.
#
# Vertical margin can't share one ratio across orientations OR just
# jump straight to a generic "center-to-upper-third" rule: that rule of
# thumb assumes a simple talking-head video, and our vertical layout has
# a code/facts panel occupying roughly the frame's middle — moving
# captions that high would visually collide with it. The real concern
# behind "avoid the bottom ~25%/top ~15%" is the Shorts app's own UI
# chrome (like button, description, channel handle) covering those zones
# on a real device, not our own panel — so this is a moderate margin
# increase to sit more clearly clear of that chrome, not a full
# relocation into the panel's own space.
#
# MARGIN_V_RATIO_PORTRAIT itself lives in pipeline/brand.py, not here —
# visuals_code.py's code panel has to size itself to stay clear of
# whatever zone this defines, so it can't be a captions.py-local value
# the panel code doesn't know about (a real bug this fixed: the panel
# was vertically centered with unbounded height and ran straight into a
# caption zone it had no idea existed).
FONT_SIZE_RATIO = 58 / 1080
ACTIVE_FONT_SIZE_RATIO = 78 / 1080  # the word being spoken right now — bigger + accent color
MARGIN_V_RATIO_PORTRAIT = CAPTION_MARGIN_V_RATIO_PORTRAIT
MARGIN_V_RATIO_LANDSCAPE = 0.09  # thin bottom strip — quiz longform only, no code panel to coordinate with

# Colors in ASS's &HAABBGGRR order.
TEXT_COLOR = "&H00FFFFFF"       # pure white, inactive words
ACTIVE_COLOR = "&H00EFD966"     # project accent cyan (102,217,239), single high-contrast color for the current word

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{size},{text_color},&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _format_ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _normalize_word(word: str) -> str:
    return re.sub(r"[^a-z0-9']", "", word.lower())


def _load_native_word_timestamps(video_id: str, whole_audio_path: str) -> list[dict] | None:
    """Real per-word timestamps captured directly from edge_tts's own
    synthesis (voice.py's WordBoundary capture), if a sidecar exists for
    every step's audio — accurate through pauses in a way re-transcribing
    our own generated audio with Whisper can't be, since Whisper only
    guesses word boundaries after the fact and that guess gets worse
    right around silence. Returns None if anything's missing (e.g. the
    kokoro backend, which doesn't expose word timestamps), so the caller
    falls back to Whisper.
    """
    steps = get_video_steps(video_id)
    if steps:
        words: list[dict] = []
        cumulative = 0.0
        for step in steps:
            if not step["audio_path"]:
                return None
            words_path = Path(step["audio_path"] + ".words.json")
            if not words_path.exists():
                return None
            step_words = json.loads(words_path.read_text(encoding="utf-8"))
            if not step_words:
                return None
            words += [{"word": w["word"], "start": w["start"] + cumulative, "end": w["end"] + cumulative} for w in step_words]
            cumulative += step["duration"] or 0.0
        return words

    words_path = Path(whole_audio_path + ".words.json")
    if not words_path.exists():
        return None
    data = json.loads(words_path.read_text(encoding="utf-8"))
    return data or None


def _align_script_to_timed_words(script_words: list[str], timed_words: list[dict]) -> list[dict]:
    """Whichever source timed the audio (Whisper's transcription, or
    edge_tts's own WordBoundary events) isn't always what should actually
    be displayed: Whisper can mis-hear a word, and edge_tts's WordBoundary
    text has no punctuation on it at all (confirmed directly against the
    library: "warned" / "me" / "about" / "I", not "about." with the
    period attached). Use the timed source for TIMING only, and the
    already-known-correct, fully-punctuated script text for what's
    actually displayed — aligning the two word sequences so neither a
    mis-transcription nor missing punctuation survives into the captions.
    """
    a = [_normalize_word(w) for w in script_words]
    b = [_normalize_word(w["word"]) for w in timed_words]
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)

    aligned: list[dict] = []
    last_end = 0.0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = timed_words[j1 + k]
                aligned.append({"word": script_words[i1 + k], "start": w["start"], "end": w["end"]})
                last_end = w["end"]
        elif tag == "replace":
            real_words = script_words[i1:i2]
            if j1 < j2:
                span_start = timed_words[j1]["start"]
                span_end = timed_words[j2 - 1]["end"]
            else:
                span_start = span_end = last_end
            if real_words:
                dur = (span_end - span_start) / len(real_words) if span_end > span_start else 0.25
                t = span_start
                for w in real_words:
                    aligned.append({"word": w, "start": t, "end": t + dur})
                    t += dur
                last_end = max(span_end, t)
        elif tag == "delete":
            # the timed source missed these real words entirely — give
            # them a short slot right after the last known timestamp
            # rather than dropping them silently.
            for w in script_words[i1:i2]:
                aligned.append({"word": w, "start": last_end, "end": last_end + 0.25})
                last_end += 0.25
        # tag == "insert": the timed source produced words that aren't in the real
        # script at all (hallucination/artifact) — drop them, never
        # caption something that wasn't actually said.
    return aligned


_SENTENCE_END_RE = re.compile(r"[.!?]$")


def _chunk_words(words: list[dict]) -> list[list[dict]]:
    """Groups words into caption cards of at most CHUNK_SIZE, but never
    lets a card cross a sentence boundary — a real observed bug (a fixed
    sliding window with no punctuation awareness) grouped a sentence's
    last word with the next sentence's first word onto the same card
    (script "...warned me about. I write..." rendered as the single card
    "warned me about I", the period silently vanishing and "I" reading as
    part of the prior sentence). Splitting only on ".", "!", "?" — not
    every comma too — is a deliberate choice: there's no observed bug at
    comma boundaries, and hard-splitting every clause would make captions
    far choppier than the actual problem warrants.
    """
    chunks: list[list[dict]] = []
    current: list[dict] = []
    for w in words:
        current.append(w)
        ends_sentence = bool(_SENTENCE_END_RE.search(w["word"].strip()))
        if ends_sentence or len(current) >= CHUNK_SIZE:
            chunks.append(current)
            current = []
    if current:
        chunks.append(current)
    return chunks


def _build_ass(words: list[dict], out_path: Path, width: int, height: int) -> None:
    short_side = min(width, height)
    font_size = round(short_side * FONT_SIZE_RATIO)
    active_font_size = round(short_side * ACTIVE_FONT_SIZE_RATIO)
    is_landscape = width > height
    margin_ratio = MARGIN_V_RATIO_LANDSCAPE if is_landscape else MARGIN_V_RATIO_PORTRAIT
    margin_v = round(height * margin_ratio)

    lines = [
        _ASS_HEADER.format(
            width=width, height=height, font=FONT_NAME, size=font_size,
            text_color=TEXT_COLOR, margin_v=margin_v,
        )
    ]
    for chunk in _chunk_words(words):
        for j, active in enumerate(chunk):
            start = _format_ass_time(active["start"])
            end = _format_ass_time(active["end"])
            parts = []
            for k, w in enumerate(chunk):
                text = w["word"].strip()
                if k == j:
                    parts.append(f"{{\\fs{active_font_size}\\c{ACTIVE_COLOR}}}{text}")
                else:
                    parts.append(f"{{\\fs{font_size}\\c{TEXT_COLOR}}}{text}")
            line_text = " ".join(parts)
            lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{line_text}\n")
    # utf-8-sig: libass needs a BOM to recognize UTF-8, otherwise it reads
    # the file as a legacy codepage — a multi-byte character like an
    # em-dash then renders as mojibake (confirmed: "—" became "â€”").
    out_path.write_text("".join(lines), encoding="utf-8-sig")


def _ffmpeg_filter_path(path: Path) -> str:
    # ffmpeg's filter-graph parser treats ':' as an option separator, so a
    # Windows drive letter colon must be escaped — this is filter syntax,
    # not shell syntax (args are passed as a list, no shell involved).
    return str(path).replace("\\", "/").replace(":", "\\:")


def _probe_dimensions(path: Path) -> tuple[int, int]:
    ffprobe_path = shutil.which("ffprobe")
    if ffprobe_path is None:
        raise RuntimeError("ffprobe not found on PATH")
    result = subprocess.run(
        [
            ffprobe_path, "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=s=x:p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed (exit {result.returncode}): {result.stderr}")
    width_str, height_str = result.stdout.strip().split("x")
    return int(width_str), int(height_str)


def captions(video_id: str) -> str:
    video = get_video(video_id)
    if video is None:
        raise ValueError(f"no video with id {video_id}")
    if not video["audio_path"]:
        raise ValueError(f"video {video_id} has no audio_path — run voice() first")
    if not video["video_path"]:
        raise ValueError(f"video {video_id} has no video_path — run assemble() first")

    if video["template"] in ("quiz_longform", "game_night"):
        # Not needed for these formats — the on-screen question/option
        # (quiz) or round card (game_night) text already carries the
        # content. game_night specifically: owner watched a real rendered
        # episode and didn't want captions on this longform format at all.
        # Still advances through the same "captioned" status name so the
        # rest of the pipeline (metadata's list_by_status("captioned"),
        # the orchestrator) doesn't need a special case for either
        # template.
        output_path = OUTPUT_DIR / f"{video_id}_final.mp4"
        shutil.copy(video["video_path"], output_path)
        update_video(video_id, status="captioned", final_path=str(output_path))
        return str(output_path)

    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg not found on PATH")

    script_words = video["script_text"].split()
    words = _load_native_word_timestamps(video_id, video["audio_path"])
    if words is not None:
        # edge_tts's WordBoundary text carries no punctuation at all
        # (confirmed directly: "about"/"I", never "about."/"I") -- align
        # it back onto the real script text so sentence-ending
        # punctuation survives into the captions and the chunker below
        # can actually see sentence boundaries.
        words = _align_script_to_timed_words(script_words, words)
    else:
        # Fallback: no native timestamps available for this backend
        # (e.g. kokoro) — re-transcribe with Whisper and align its
        # timing to the known-correct script text.
        model = WhisperModel("base.en", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(video["audio_path"], word_timestamps=True)
        whisper_words = [
            {"word": w.word, "start": w.start, "end": w.end} for seg in segments for w in seg.words
        ]
        if not whisper_words:
            raise RuntimeError(f"faster-whisper returned no words for {video['audio_path']}")

        words = _align_script_to_timed_words(script_words, whisper_words)
        if not words:
            raise RuntimeError(f"could not align script text to whisper output for {video_id}")

    ass_path = OUTPUT_DIR / f"{video_id}_captions.ass"
    width, height = _probe_dimensions(Path(video["video_path"]))
    _build_ass(words, ass_path, width, height)

    output_path = OUTPUT_DIR / f"{video_id}_final.mp4"
    vf = f"subtitles='{_ffmpeg_filter_path(ass_path)}':fontsdir='{_ffmpeg_filter_path(FONTS_DIR)}'"

    result = subprocess.run(
        [
            ffmpeg_path, "-y",
            "-i", str(video["video_path"]),
            "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(output_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {result.returncode}): {result.stderr}")

    update_video(video_id, status="captioned", final_path=str(output_path))
    return str(output_path)


if __name__ == "__main__":
    args = sys.argv[1:]
    if args:
        video_id_arg = args[0]
    else:
        candidates = list_by_status("assembled")
        if not candidates:
            raise SystemExit("no assembled videos in state.db — run assemble.py first")
        video_id_arg = candidates[0]["id"]

    path = captions(video_id_arg)
    print(f"video_id: {video_id_arg}")
    print(f"output:   {path}")
