"""Style lab: synthesize one script per voice style with word timings.

Writes <out>/voice_<style>.wav and <out>/words_<style>.json
(list of {"word","start","end"} in seconds). Each sentence is a separate
edge_tts call (its WordBoundary events give exact word times); sentences
are trimmed to their last word and joined with a style-specific gap.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts
import numpy as np

SR = 48000

SCRIPT = [
    "This lake killed 1,746 people in a single night, and not one of them drowned.",
    "Its deep water was loaded with volcanic carbon dioxide.",
    "In 1986, it burst out like a shaken soda, and the gas, heavier than air, rolled downhill into sleeping villages.",
    "Creepiest part? It's still seeping in.",
    "So pipes now blast it out in a nonstop fountain, and every local knows exactly why",
]

STYLES = {
    # voice, rate, pitch, gap after each sentence (s)
    "A": ("en-US-AndrewMultilingualNeural", "+14%", "+0Hz", 0.06),
    "B": ("en-US-AvaMultilingualNeural", "-4%", "+0Hz", 0.38),
    "C": ("en-US-ChristopherNeural", "+5%", "-2Hz", 0.20),
}


async def _synth(text: str, voice: str, rate: str, pitch: str, mp3: Path) -> list[dict]:
    words: list[dict] = []
    com = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
    with mp3.open("wb") as fh:
        async for chunk in com.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                s = chunk["offset"] / 1e7
                words.append({"word": chunk["text"], "start": s, "end": s + chunk["duration"] / 1e7})
    return words


def _decode(mp3: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(mp3), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32).copy()


def build(style: str, out: Path) -> None:
    voice, rate, pitch, gap = STYLES[style]
    pieces: list[np.ndarray] = []
    all_words: list[dict] = []
    t = 0.0
    for i, sentence in enumerate(SCRIPT):
        mp3 = out / f"_s{style}{i}.mp3"
        words = asyncio.run(_synth(sentence, voice, rate, pitch, mp3))
        audio = _decode(mp3)
        lead = words[0]["start"]
        end = words[-1]["end"] + 0.12
        seg = audio[int(max(0.0, lead - 0.04) * SR): int(end * SR)]
        shift = t - max(0.0, lead - 0.04)
        for w in words:
            all_words.append({"word": w["word"], "start": round(w["start"] + shift, 3), "end": round(w["end"] + shift, 3), "sentence": i})
        pieces.append(seg)
        t += len(seg) / SR
        g = gap * (1.6 if sentence.endswith("?") or "?" in sentence else 1.0)
        if i < len(SCRIPT) - 1:
            pieces.append(np.zeros(int(g * SR), dtype=np.float32))
            t += g
    audio = np.concatenate(pieces)
    audio = audio / max(1e-6, float(np.abs(audio).max())) * 0.89
    with wave.open(str(out / f"voice_{style}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype(np.int16).tobytes())
    (out / f"words_{style}.json").write_text(json.dumps(all_words, indent=1))
    print(style, voice, f"{len(audio) / SR:.2f}s", len(all_words), "words")


if __name__ == "__main__":
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for s in sys.argv[2:] or list(STYLES):
        build(s, out)
