"""Rhythm of a sound: tempo, beat times and the drop.

Used for beat-synced edits: Reroll reads the sound the player picked, times the edit to
it, and exports *without* the music. The player adds the same sound inside TikTok (where
it's licensed), starting at 0:00, and the cuts land on its beats.

Method (no third-party packages):
- onset envelope: rise in short-time energy, every HOP seconds, from a low-passed copy
  (kicks and bass carry the beat in most edit music);
- tempo: autocorrelation of that envelope over 70-180 BPM, with a mild preference for
  common edit tempos so half/double-time ambiguity resolves sensibly;
- beat phase: the offset whose beat grid collects the most onset energy;
- drop: the beat where loudness over the next 2 s jumps most above the 2 s before it.
"""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

RATE = 12000          # 120 samples = exactly one 10 ms frame
HOP = 0.01                # seconds per envelope frame
MIN_BPM, MAX_BPM = 70.0, 180.0


class BeatError(Exception):
    pass


def _decode(path: Path, lowpass: int | None) -> array:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise BeatError("FFmpeg is required")
    af = f"lowpass=f={lowpass}," if lowpass else ""
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                           "-af", f"{af}aresample={RATE}", "-ar", str(RATE), "-f", "s16le", "-"],
                          capture_output=True)
    if proc.returncode or not proc.stdout:
        raise BeatError(f"Can't read audio from {Path(path).name}")
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    return samples


def _energy(samples: array) -> list[float]:
    per = int(RATE * HOP)
    out = []
    for i in range(0, len(samples) - per + 1, per):
        chunk = samples[i:i + per]
        out.append(math.sqrt(sum(s * s for s in chunk) / per) / 32768.0)
    return out


def _onsets(energy: list[float]) -> list[float]:
    log = [math.log10(e + 1e-4) for e in energy]
    rise = [0.0] + [max(0.0, log[i] - log[i - 1]) for i in range(1, len(log))]
    peak = max(rise) or 1.0
    return [r / peak for r in rise]


def _tempo(env: list[float]) -> float:
    n = len(env)
    mean = sum(env) / max(n, 1)
    centred = [e - mean for e in env]
    best_lag, best_score = None, -math.inf
    for bpm10 in range(int(MIN_BPM * 10), int(MAX_BPM * 10) + 1, 5):
        bpm = bpm10 / 10
        lag = 60.0 / bpm / HOP
        lo, frac = int(lag), lag - int(lag)
        if lo + 1 >= n:
            continue
        acf = 0.0
        for i in range(n - lo - 1):
            shifted = centred[i + lo] * (1 - frac) + centred[i + lo + 1] * frac
            acf += centred[i] * shifted
        acf /= (n - lo)
        # Gentle prior around 125 BPM: picks 140 over 70 for typical edit music.
        weight = math.exp(-0.5 * (math.log2(bpm / 125.0) / 0.9) ** 2)
        if acf * weight > best_score:
            best_score, best_lag = acf * weight, bpm
    if best_lag is None:
        raise BeatError("The sound is too short to find a tempo")
    return best_lag


def _phase(env: list[float], bpm: float) -> tuple[float, float]:
    """Best grid offset for this tempo, and how much onset energy that grid collects."""
    period = 60.0 / bpm
    steps = 40
    best, best_offset = -1.0, 0.0
    for k in range(steps):
        offset = k * period / steps
        total, t = 0.0, offset
        while t / HOP < len(env):
            i = int(round(t / HOP))
            total += max(env[max(0, i - 2):i + 3] or [0.0])
            t += period
        if total > best:
            best, best_offset = total, offset
    beats = max(1, int(len(env) * HOP / period))
    return best_offset, best / beats


def _refine(env: list[float], bpm: float) -> tuple[float, float]:
    """Fine-tunes the tempo (+/- 1 BPM, 0.05 steps): a small tempo error drifts a whole bar late."""
    best = (-1.0, bpm, 0.0)
    for k in range(-20, 21):
        candidate = bpm + k * 0.05
        offset, score = _phase(env, candidate)
        if score > best[0]:
            best = (score, candidate, offset)
    return best[1], best[2]


def _peaks(env: list[float], share: float = 0.35) -> list[float]:
    """Onset peaks, judged against their own neighbourhood (a loud section mustn't hide its
    kicks), timed to a fraction of a frame by fitting a parabola through each peak."""
    radius = int(1.0 / HOP)
    out = []
    for i in range(1, len(env) - 1):
        if not (env[i] >= env[i - 1] and env[i] > env[i + 1]):
            continue
        local = max(env[max(0, i - radius):i + radius + 1])
        if env[i] < share * local or env[i] < 0.02:
            continue
        a, b, c = env[i - 1], env[i], env[i + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom else 0.0
        out.append((i + max(-0.5, min(0.5, shift))) * HOP)
    return out


def _fit_grid(env: list[float], period: float, offset: float) -> tuple[float, float]:
    """Least-squares fit of the beat grid to the onset peaks nearest each predicted beat."""
    peaks = _peaks(env)
    if len(peaks) < 4:
        return period, offset
    for _ in range(3):
        pairs = []
        k_max = int((len(env) * HOP - offset) / period)
        for k in range(k_max + 1):
            want = offset + k * period
            near = min(peaks, key=lambda p: abs(p - want))
            if abs(near - want) <= period / 4:
                pairs.append((k, near))
        if len(pairs) < 4:
            break
        n = len(pairs)
        mk = sum(k for k, _ in pairs) / n
        mt = sum(t for _, t in pairs) / n
        var = sum((k - mk) ** 2 for k, _ in pairs)
        if var == 0:
            break
        period = sum((k - mk) * (t - mt) for k, t in pairs) / var
        offset = mt - period * mk
        while offset - period >= -period * 0.1:
            offset -= period
        offset = max(0.0, offset)
    return period, offset


def _peaks(env: list[float], share: float = 0.35) -> list[float]:
    """Onset peaks, judged against their own neighbourhood (a loud section mustn't hide its
    kicks), timed to a fraction of a frame by fitting a parabola through each peak."""
    radius = int(1.0 / HOP)
    out = []
    for i in range(1, len(env) - 1):
        if not (env[i] >= env[i - 1] and env[i] > env[i + 1]):
            continue
        local = max(env[max(0, i - radius):i + radius + 1])
        if env[i] < share * local or env[i] < 0.02:
            continue
        a, b, c = env[i - 1], env[i], env[i + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom else 0.0
        out.append((i + max(-0.5, min(0.5, shift))) * HOP)
    return out


def _fit_grid(env: list[float], period: float, offset: float) -> tuple[float, float]:
    """Least-squares fit of the beat grid to the onset peaks nearest each predicted beat."""
    peaks = _peaks(env)
    if len(peaks) < 4:
        return period, offset
    for _ in range(3):
        pairs = []
        k_max = int((len(env) * HOP - offset) / period)
        for k in range(k_max + 1):
            want = offset + k * period
            near = min(peaks, key=lambda p: abs(p - want))
            if abs(near - want) <= period / 4:
                pairs.append((k, near))
        if len(pairs) < 4:
            break
        n = len(pairs)
        mk = sum(k for k, _ in pairs) / n
        mt = sum(t for _, t in pairs) / n
        var = sum((k - mk) ** 2 for k, _ in pairs)
        if var == 0:
            break
        period = sum((k - mk) * (t - mt) for k, t in pairs) / var
        offset = mt - period * mk
        while offset - period >= -period * 0.1:
            offset -= period
        offset = max(0.0, offset)
    return period, offset


def analyze_beats(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise BeatError(f"File not found: {path}")
    low = _energy(_decode(path, 200))
    full = _energy(_decode(path, None))
    duration = len(full) * HOP
    if duration < 4:
        raise BeatError("The sound needs to be at least 4 seconds long")
    env = _onsets(low)
    bpm, offset = _refine(env, _tempo(env))
    period, offset = _fit_grid(env, 60.0 / bpm, offset)
    bpm = 60.0 / period
    beats = []
    t = offset
    while t < duration - 0.05:
        beats.append(round(t, 3))
        t += period
    # The drop: the beat where the next 2 s are loudest compared with the 2 s before.
    span = int(2.0 / HOP)
    def mean(a: int, b: int) -> float:
        seg = full[max(0, a):max(0, min(len(full), b))]
        return sum(seg) / len(seg) if seg else 0.0
    best, drop = -math.inf, beats[min(len(beats) - 1, 4)] if beats else 0.0
    for b in beats:
        i = int(b / HOP)
        if b < 2.0 or i + span > len(full):
            continue
        before, after = mean(i - span, i), mean(i, i + span)
        jump = math.log10((after + 1e-4) / (before + 1e-4))
        if jump > best:
            best, drop = jump, b
    return {"ok": True, "file": path.name, "duration": round(duration, 3), "bpm": round(bpm, 1),
            "beat_seconds": round(period, 4), "beats": beats, "drop": drop,
            "drop_strength": round(best, 3) if best > -math.inf else 0.0}
