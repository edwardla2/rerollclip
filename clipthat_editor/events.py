"""Gameplay events (kills) found in a clip, so edits can be paced around them.

Valorant: after every kill the game shows the player's kill banner just above the ability
bar, at the same spot, for about 1.5-2 s. Banners differ by skin, so this doesn't match
any one image: it watches that spot for a sudden jump in local contrast (a crisp badge
appearing over the scene) and reports each rise as a kill.

Fallback for other games: sharp rises in loudness (shots, impacts), at least 0.8 s apart.
Every number here is a starting point to check on more real clips.
"""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import shutil
import subprocess
from statistics import median
from typing import Any

FPS = 10
BOX = 40


def _ffmpeg() -> str:
    tool = shutil.which("ffmpeg")
    if not tool:
        raise RuntimeError("FFmpeg is required")
    return tool


def _region_contrast(path: Path, crop: str) -> list[float]:
    """Mean horizontal luminance gradient of a screen region, FPS times a second."""
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                           "-vf", f"fps={FPS},crop={crop},scale={BOX}:{BOX},format=gray",
                           "-f", "rawvideo", "-"], capture_output=True)
    raw = proc.stdout
    size = BOX * BOX
    out = []
    for f in range(len(raw) // size):
        px = raw[f * size:(f + 1) * size]
        total = 0
        for row in range(BOX):
            base = row * BOX
            for col in range(BOX - 1):
                total += abs(px[base + col] - px[base + col + 1])
        out.append(total / size)
    return out


SHOT_LOOKBACK = 0.9        # the shot comes before the banner (and any post-kill animation)
SHOT_FPS = 30


def _frame_change(path: Path) -> list[float]:
    """Mean absolute change between consecutive small greyscale frames, SHOT_FPS a second."""
    w, h = 64, 36
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                           "-vf", f"fps={SHOT_FPS},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                          capture_output=True)
    raw, size = proc.stdout, w * h
    frames = len(raw) // size
    out = [0.0]
    for f in range(1, frames):
        a, b = raw[(f - 1) * size:f * size], raw[f * size:(f + 1) * size]
        out.append(sum(abs(x - y) for x, y in zip(a, b)) / size)
    return out


def _shot_before(change: list[float], banner: float) -> float | None:
    """The sharpest whole-screen change (muzzle flash, recoil, unscope) shortly before a banner."""
    lo, hi = max(1, int((banner - SHOT_LOOKBACK) * SHOT_FPS)), int(banner * SHOT_FPS)
    window = change[lo:hi]
    if not window:
        return None
    j = max(range(len(window)), key=lambda i: window[i])
    typical = sorted(window)[len(window) // 2]
    return (lo + j) / SHOT_FPS if window[j] >= max(8.0, 2.5 * typical) else None


def valorant_kills(path: Path) -> list[float]:
    banners = _banner_onsets(path)
    if not banners:
        return []
    # Banners (and post-kill ability animations near them) trail the shot; for tight cuts
    # the kill needs to be the shot itself.
    change = _frame_change(path)
    kills = []
    for banner in banners:
        shot = _shot_before(change, banner)
        kills.append(round(shot if shot is not None else max(0.0, banner - 0.45), 2))
    return kills


def _banner_onsets(path: Path) -> list[float]:
    signal = _region_contrast(path, "iw*0.10:ih*0.14:iw*0.45:ih*0.71")
    if not signal:
        return []
    base = median(signal)
    high = max(8.0, base * 3.0, 0.45 * max(signal))
    low = max(4.0, high * 0.45)
    kills, armed, quiet = [], True, 0
    for i, v in enumerate(signal):
        if v < low:
            quiet += 1
            if quiet >= 2:        # banner gone (or restarting): ready for the next kill
                armed = True
        else:
            quiet = 0
        if armed and v >= high:
            kills.append(round(i / FPS, 2))
            armed = False
    return kills


def audio_hits(path: Path, limit: int = 8) -> list[float]:
    """Loud, sudden moments: the biggest rises in short-time loudness."""
    rate, hop = 8000, 0.05
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                           "-ar", str(rate), "-f", "s16le", "-"], capture_output=True)
    if proc.returncode or not proc.stdout:
        return []
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    per = int(rate * hop)
    db = []
    for i in range(0, len(samples) - per + 1, per):
        chunk = samples[i:i + per]
        rms = math.sqrt(sum(s * s for s in chunk) / per) / 32768.0
        db.append(20 * math.log10(rms) if rms > 1e-5 else -100.0)
    rises = [(db[i] - min(db[max(0, i - 6):i] or [db[i]]), i) for i in range(1, len(db))]
    floor = max(9.0, sorted(r for r, _ in rises)[int(len(rises) * 0.9)] if rises else 9.0)
    picked: list[float] = []
    for rise, i in sorted(rises, reverse=True):
        t = i * hop
        if rise < floor or len(picked) >= limit:
            break
        if all(abs(t - p) >= 0.8 for p in picked):
            picked.append(t)
    return sorted(round(t, 2) for t in picked)


DETECTORS = {"valorant": valorant_kills}


def find_events(path: Path, profile: str) -> dict[str, Any]:
    detector = DETECTORS.get(profile)
    if detector:
        found = detector(Path(path))
        if found:
            return {"source": f"{profile}-kill-banner", "times": found}
    return {"source": "audio-hits", "times": audio_hits(Path(path))}
