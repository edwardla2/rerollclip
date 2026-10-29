"""Suggested trims: find the moment worth keeping in a clip.

Signals (sampled every 0.1 s):
- audio loudness (RMS in dB) - gunshots, explosions, shouting and reactions spike it;
- visual change (FFmpeg scene score) - cuts, flashes, fast camera motion.

Each signal is normalised against the clip's own baseline (median / MAD, with a noise floor)
and soft-capped, so a quiet clip and a loud clip are judged by their own standards and a
moment both signals agree on outranks one only a single signal sees. The combined, smoothed score's peak is
the moment; the suggested window places it about 70% of the way through, keeping some
setup before it and the reaction after it.

For replay clips the caller passes `trigger_offset` (when the user said "Clip that"):
the moment happened shortly before that, so the search is limited to the preceding
`TRIGGER_LOOKBACK` seconds.

Deterministic signal processing, no machine learning. Quality on real footage must be
measured before it's described as anything more than a suggestion.
"""

from __future__ import annotations

from array import array
from .audio_track import game_track
import math
from pathlib import Path
import re
import shutil
import subprocess
from statistics import median
from typing import Any

STEP = 0.1                  # seconds per analysis frame
AUDIO_RATE = 8000           # Hz; enough for loudness, cheap to decode
SMOOTH_SECONDS = 0.8
PEAK_POSITION = 0.7         # where the moment sits inside the suggested window
TRIGGER_LOOKBACK = 15.0     # seconds before "Clip that" to search
AUDIO_WEIGHT = 0.65
MOTION_WEIGHT = 0.35


class AnalysisError(Exception):
    pass


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise AnalysisError(f"Required executable '{name}' is missing from PATH")
    return path


def _probe(path: Path) -> tuple[float, bool]:
    out = subprocess.run([_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration:stream=codec_type",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    if out.returncode:
        raise AnalysisError(f"Can't read media {path.name}")
    lines = [l.strip() for l in out.stdout.splitlines() if l.strip()]
    has_audio = "audio" in lines
    duration = 0.0
    for line in lines:
        try:
            duration = float(line)
        except ValueError:
            continue
    if duration <= 0:
        raise AnalysisError(f"Can't determine the length of {path.name}")
    return duration, has_audio


def audio_loudness(path: Path, frames: int) -> list[float]:
    """RMS level in dBFS for each STEP-long frame (first audio track, mixed to mono)."""
    proc = subprocess.run([_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", f"0:a:{game_track(path)}", "-ac", "1",
                           "-ar", str(AUDIO_RATE), "-f", "s16le", "-"], capture_output=True)
    if proc.returncode:
        return []
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    per = int(AUDIO_RATE * STEP)
    levels = []
    for i in range(frames):
        chunk = samples[i * per:(i + 1) * per]
        if not chunk:
            levels.append(-100.0)
            continue
        rms = math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768.0
        levels.append(20 * math.log10(rms) if rms > 1e-5 else -100.0)
    return levels


_SCENE_RE = re.compile(r"pts_time:([0-9.]+)")
_SCORE_RE = re.compile(r"lavfi\.scene_score=([0-9.]+)")


def visual_change(path: Path, frames: int) -> list[float]:
    """Max scene-change score per STEP-long frame, from a small 10 fps proxy."""
    proc = subprocess.run([_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:v:0", "-an",
                           "-vf", "fps=10,scale=160:-2,select='gte(scene,0)',metadata=print:file=-",
                           "-f", "null", "-"], capture_output=True, text=True)
    values = [0.0] * frames
    if proc.returncode:
        return values
    time = None
    for line in proc.stdout.splitlines():
        m = _SCENE_RE.search(line)
        if m:
            time = float(m.group(1))
            continue
        m = _SCORE_RE.search(line)
        if m and time is not None:
            index = min(frames - 1, max(0, int(time / STEP)))
            values[index] = max(values[index], float(m.group(1)))
    return values


AUDIO_FLOOR_DB = 1.5        # smallest loudness spread treated as meaningful
MOTION_FLOOR = 0.02         # smallest scene-score spread treated as meaningful


def _normalise(values: list[float], floor: float) -> list[float]:
    """Rise above the clip's own baseline, in robust standard deviations, soft-capped to 0..1.

    The floor stops a near-constant signal (steady noise, a static frame) from turning tiny
    wobbles into huge scores; the soft cap keeps one signal from drowning out the other, so
    a moment that is both loud and visually busy beats one that is only loud.
    """
    if not values:
        return []
    mid = median(values)
    mad = median(abs(v - mid) for v in values)
    scale = max(mad * 1.4826, floor)
    return [1.0 - math.exp(-max(0.0, (v - mid) / scale) / 3.0) for v in values]


def _smooth(values: list[float], seconds: float) -> list[float]:
    radius = max(1, int(seconds / STEP / 2))
    out = []
    running = 0.0
    window: list[float] = []
    for i in range(len(values) + radius):
        if i < len(values):
            window.append(values[i])
            running += values[i]
        if len(window) > 2 * radius + 1:
            running -= window.pop(0)
        if i >= radius:
            out.append(running / len(window))
    return out[: len(values)]


def suggest_window(score: list[float], duration: float, length: float,
                   trigger_offset: float | None = None) -> dict[str, float]:
    """Pick the peak (optionally before the trigger) and frame a window around it."""
    length = min(length, duration)
    lo, hi = 0, len(score)
    if trigger_offset is not None:
        hi = max(1, min(len(score), int(trigger_offset / STEP) + 1))
        lo = max(0, int((trigger_offset - TRIGGER_LOOKBACK) / STEP))
        if lo >= hi:
            lo = 0
    region = score[lo:hi] or score
    best = max(range(len(region)), key=lambda i: region[i]) if region else 0
    peak_index = lo + best
    peak = (peak_index + 0.5) * STEP
    start = min(max(0.0, peak - PEAK_POSITION * length), max(0.0, duration - length))
    if trigger_offset is not None:
        # Keep the reaction right after the trigger, but no more than ~1.5 s past it.
        latest_end = min(duration, trigger_offset + 1.5)
        if start + length > latest_end:
            start = max(0.0, latest_end - length)
    return {"start": round(start, 3), "duration": round(min(length, duration - start), 3),
            "peak": round(peak, 3), "strength": round(score[peak_index] if score else 0.0, 3)}


def score_clip(path: Path) -> dict[str, Any]:
    """Per-frame interest score (0..1, one value every STEP seconds) plus what it was built from."""
    path = Path(path)
    if not path.is_file():
        raise AnalysisError(f"File not found: {path}")
    duration, has_audio = _probe(path)
    frames = max(1, math.ceil(duration / STEP))
    loud = _normalise(audio_loudness(path, frames), AUDIO_FLOOR_DB) if has_audio else []
    motion = _normalise(visual_change(path, frames), MOTION_FLOOR)
    if loud and any(loud):
        combined = [AUDIO_WEIGHT * a + MOTION_WEIGHT * m for a, m in zip(loud, motion)]
        signals = ["audio", "motion"]
    else:
        combined = motion
        signals = ["motion"]
    return {"duration": duration, "has_audio": has_audio, "signals": signals,
            "score": _smooth(combined, SMOOTH_SECONDS)}


def analyze(path: Path, length: float = 8.0, trigger_offset: float | None = None) -> dict[str, Any]:
    path = Path(path)
    if not (0.5 <= length <= 120):
        raise AnalysisError("length must be between 0.5 and 120 seconds")
    scored = score_clip(path)
    duration, score = scored["duration"], scored["score"]
    if trigger_offset is not None:
        trigger_offset = min(max(0.0, trigger_offset), duration)
    window = suggest_window(score, duration, length, trigger_offset)
    return {"ok": True, "file": path.name, "duration": round(duration, 3), "signals": scored["signals"],
            "suggested_start": window["start"], "suggested_duration": window["duration"],
            "peak_time": window["peak"], "strength": window["strength"]}
