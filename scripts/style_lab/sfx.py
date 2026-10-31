"""Synthesized sound effects for the style lab (numpy only, no samples,
no licenses). Every function returns mono float32 at SR, peak <= ~0.9.
"""
from __future__ import annotations

import numpy as np

SR = 48000


def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def _noise(n: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _band(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Soft FFT band-pass (cosine edges) -- good enough for short SFX."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    lo_edge = np.clip((f - lo * 0.7) / (lo * 0.3 + 1e-9), 0, 1)
    hi_edge = np.clip((hi * 1.3 - f) / (hi * 0.3 + 1e-9), 0, 1)
    return np.fft.irfft(spec * lo_edge * hi_edge, n=len(x)).astype(np.float32)


def _norm(x: np.ndarray, peak: float = 0.9) -> np.ndarray:
    m = float(np.abs(x).max()) or 1.0
    return (x / m * peak).astype(np.float32)


def _sweep_noise(dur: float, f_start: float, f_end: float, seed: int, width: float = 0.8) -> np.ndarray:
    """Noise whose pass-band center glides from f_start to f_end
    (overlap-added hann frames, each band-passed at its own center)."""
    n = int(dur * SR)
    hop, size = 512, 2048
    src = _noise(n + size, seed)
    out = np.zeros(n + size, dtype=np.float32)
    win = np.hanning(size).astype(np.float32)
    frames = max(1, (n - size) // hop + 1)
    for i in range(frames):
        k = i / max(1, frames - 1)
        fc = f_start * (f_end / f_start) ** k
        seg = _band(src[i * hop: i * hop + size] * win, fc * (1 - width / 2), fc * (1 + width / 2))
        out[i * hop: i * hop + size] += seg * win
    return out[:n]


def whoosh(dur: float = 0.45, seed: int = 1) -> np.ndarray:
    t = _t(dur)
    up = _sweep_noise(dur, 350, 2600, seed)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.6
    return _norm(up * env, 0.75)


def boom(dur: float = 1.6) -> np.ndarray:
    t = _t(dur)
    freq = 32 + 46 * np.exp(-t * 3.5)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 2.6)
    click = _band(_noise(len(t), 7), 60, 900) * np.exp(-t * 28) * 0.6
    return _norm(np.tanh((body + click) * 1.8), 0.95)


def pop(dur: float = 0.09) -> np.ndarray:
    t = _t(dur)
    freq = 520 + 900 * np.exp(-t * 60)
    return _norm(np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 45), 0.5)


def riser(dur: float = 1.2, seed: int = 3) -> np.ndarray:
    t = _t(dur)
    sweep = _sweep_noise(dur, 300, 5000, seed, 0.5)
    tone = np.sin(2 * np.pi * np.cumsum(180 + 900 * (t / dur) ** 2) / SR) * 0.25
    env = (t / dur) ** 2.2
    return _norm((sweep + tone) * env, 0.6)


def shutter(seed: int = 5) -> np.ndarray:
    a = _band(_noise(int(0.012 * SR), seed), 1800, 9000) * np.exp(-_t(0.012) * 300)
    b = _band(_noise(int(0.018 * SR), seed + 1), 900, 7000) * np.exp(-_t(0.018) * 220)
    out = np.zeros(int(0.09 * SR), dtype=np.float32)
    out[: len(a)] += a
    out[int(0.055 * SR): int(0.055 * SR) + len(b)] += b * 0.8
    return _norm(out, 0.55)


def type_key(seed: int = 9) -> np.ndarray:
    t = _t(0.035)
    click = _band(_noise(len(t), seed), 1500, 7000) * np.exp(-t * 260)
    knock = np.sin(2 * np.pi * 180 * t) * np.exp(-t * 120) * 0.5
    return _norm(click + knock, 0.35)


def stamp(dur: float = 0.35) -> np.ndarray:
    t = _t(dur)
    thump = np.sin(2 * np.pi * np.cumsum(70 + 80 * np.exp(-t * 40)) / SR) * np.exp(-t * 16)
    slap = _band(_noise(len(t), 11), 250, 2500) * np.exp(-t * 55) * 0.7
    return _norm(np.tanh((thump + slap) * 1.5), 0.9)


def swell(dur: float = 1.3, seed: int = 13) -> np.ndarray:
    t = _t(dur)
    air = _band(_noise(len(t), seed), 120, 1600)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 2
    return _norm(air * env, 0.35)


def place(track: np.ndarray, clip: np.ndarray, at: float, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(track):
        return
    j = min(len(track), i + len(clip))
    track[i:j] += clip[: j - i] * gain
