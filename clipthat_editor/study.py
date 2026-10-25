"""Measure a finished edit (a reference someone liked) so the engine's numbers can be
calibrated against real examples: where it cuts, how long shots last, how many cuts land on
the music's beats, where the first cut sits against the drop, flashes and dips to black.

The edit is read from a local file the user provides; nothing is downloaded."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from statistics import median
from typing import Any

FPS = 30
W, H = 64, 36


def _frames(path: Path) -> tuple[list[float], list[float]]:
    """Per frame: mean brightness and mean absolute change from the previous frame."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required")
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:v:0",
                          "-vf", f"fps={FPS},scale={W}:{H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    size = W * H
    bright, change = [], []
    prev = None
    for f in range(len(raw) // size):
        px = raw[f * size:(f + 1) * size]
        bright.append(sum(px) / size)
        change.append(sum(abs(a - b) for a, b in zip(px, prev)) / size if prev else 0.0)
        prev = px
    return bright, change


def cuts_from_change(change: list[float], fps: int = FPS, min_gap: float = 0.12) -> list[float]:
    """Hard cuts: a frame-to-frame change far above its neighbourhood."""
    out: list[float] = []
    for i in range(1, len(change)):
        around = change[max(0, i - 8):i] + change[i + 1:i + 9]
        typical = median(around) if around else 0.0
        if change[i] >= max(18.0, 3.0 * typical) and change[i] >= max(change[i - 1], change[min(i + 1, len(change) - 1)]):
            t = i / fps
            if not out or t - out[-1] >= min_gap:
                out.append(round(t, 3))
    return out


def events_from_brightness(bright: list[float], fps: int = FPS) -> dict[str, list[float]]:
    """Flashes (a frame much brighter than the second before) and dips (near-black frames)."""
    flashes, dips = [], []
    for i, b in enumerate(bright):
        before = bright[max(0, i - fps):i]
        if before and b >= median(before) + 60 and (not flashes or i / fps - flashes[-1] > 0.2):
            flashes.append(round(i / fps, 3))
        if b < 12 and (not dips or i / fps - dips[-1] > 0.5):
            dips.append(round(i / fps, 3))
    return {"flashes": flashes, "dips": dips}


def on_beat_share(cuts: list[float], beats: list[float], tolerance: float = 0.06) -> float:
    if not cuts or not beats:
        return 0.0
    hit = sum(1 for c in cuts if min(abs(c - b) for b in beats) <= tolerance)
    return round(hit / len(cuts), 3)


def study(path: Path) -> dict[str, Any]:
    path = Path(path)
    bright, change = _frames(path)
    duration = len(bright) / FPS
    cuts = cuts_from_change(change)
    shots = [round(b - a, 3) for a, b in zip([0.0] + cuts, cuts + [duration])]
    result: dict[str, Any] = {
        "file": path.name,
        "seconds": round(duration, 2),
        "cuts": cuts,
        "cuts_per_second": round(len(cuts) / duration, 2) if duration else 0.0,
        "median_shot": round(median(shots), 3) if shots else 0.0,
        "shortest_shot": min(shots) if shots else 0.0,
        "longest_shot": max(shots) if shots else 0.0,
        **events_from_brightness(bright),
    }
    try:
        from .beats import analyze_beats
        music = analyze_beats(path)
    except Exception as exc:  # no audio track, or nothing rhythmic
        result["music"] = {"error": str(exc)}
        return result
    period = 60.0 / music["bpm"]
    beats = music["beats"]
    halves = sorted(beats + [round(b + period / 2, 3) for b in beats])
    drop = music["drop"]
    after = [c for c in cuts if c >= drop - 0.1]
    result["music"] = {"bpm": music["bpm"], "drop": drop}
    result["cuts_on_beat"] = on_beat_share(cuts, beats)
    result["cuts_on_half_beat"] = on_beat_share(cuts, halves)
    result["first_cut_after_drop"] = round(after[0] - drop, 3) if after else None
    if len(after) > 1:
        gaps = [b - a for a, b in zip(after, after[1:])]
        result["beats_per_cut_after_drop"] = round(median(gaps) / period, 2)
    return result
