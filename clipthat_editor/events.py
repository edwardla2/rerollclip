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


FEED_FPS = 20
FEED_LAG = 0.12            # a kill-feed row appears about this long after the shot


def _feed_teal(path: Path) -> list[int]:
    """Teal pixels in the kill feed (top right), FEED_FPS a second. Every kill row has some."""
    w, h = 96, 40
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                           "-vf", f"fps={FEED_FPS},crop=iw*0.30:ih*0.16:iw*0.70:ih*0.07,scale={w}:{h}",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    raw, size = proc.stdout, w * h * 3
    out = []
    for f in range(len(raw) // size):
        px = raw[f * size:(f + 1) * size]
        out.append(sum(1 for i in range(0, size, 3)
                       if px[i + 1] > 140 and px[i + 1] - px[i] > 50 and px[i + 2] - px[i] > 20))
    return out


def _feed_kills(path: Path) -> list[float]:
    """Kill times from new teal rows in the kill feed: a step up that lasts (a passing teal
    effect doesn't). Rows arriving together (a collateral) count as one kill moment."""
    return feed_steps(_feed_teal(path))


def _feed_band(path: Path) -> list[int]:
    """Kill-feed rows only: per frame, how many pixel lines of the feed area are mostly row
    colour (teal or red) across their width, times 20. A row is a long horizontal band of
    both; teal or red bits of the scene (walls, smoke, abilities) aren't, so they don't count."""
    w, h = 96, 60
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                           "-vf", f"fps={FEED_FPS},crop=iw*0.30:ih*0.24:iw*0.70:ih*0.07,scale={w}:{h}",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    raw, size, need = proc.stdout, w * h * 3, 0.35 * w
    out = []
    for f in range(len(raw) // size):
        px = raw[f * size:(f + 1) * size]
        lines = 0
        for y in range(h):
            row = px[y * w * 3:(y + 1) * w * 3]
            hits = 0
            for i in range(0, w * 3, 3):
                r, g, b = row[i], row[i + 1], row[i + 2]
                if (g > 140 and g - r > 50 and b - r > 20) or (r > 170 and r - g > 70 and r - b > 60):
                    hits += 1
            if hits >= need:
                lines += 1
        out.append(lines * 20)
    return out


def feed_steps(teal: list[int], merge: float = 0.6) -> list[float]:
    """Kill times from a teal-pixel series (see _feed_kills). Rows closer than `merge` seconds
    count once (a collateral is one shot); merge=0 counts every row (every kill)."""
    n = len(teal)
    if not n or max(teal) == 0:
        return []
    hold = int(0.4 * FEED_FPS)
    step = 70                      # a new row is ~100-190 teal pixels at this size
    kills: list[float] = []
    i = 1
    while i < n:
        before = sorted(teal[max(0, i - hold):i])
        level = before[len(before) // 2] if before else 0
        if teal[i] >= level + step:
            # It has to stay: a passing teal effect (an ability) flashes and drops back.
            stays = all(v >= level + 0.6 * step for v in teal[i:i + hold])
            if stays and i + hold <= n:
                t = round(max(0.0, i / FEED_FPS - FEED_LAG), 2)
                if not kills or t - kills[-1] > merge:   # rows arriving together: one shot (a collateral)
                    kills.append(t)
                i += hold
                continue
        i += 1
    return kills


def row_counts(teal: list[int], steps: list[float] | None = None) -> dict[float, int]:
    """Rows that arrived at each feed step: the step's size over a single row's (the typical
    step), so two rows landing together (a collateral) count as two."""
    hold = int(0.4 * FEED_FPS)
    rises = {}
    for t in (feed_steps(teal) if steps is None else steps):
        i = int(round((t + FEED_LAG) * FEED_FPS))
        before = sorted(teal[max(0, i - hold):i]) or [0]
        after = sorted(teal[i + hold:i + 2 * hold]) or sorted(teal[i:i + hold])
        rises[t] = after[len(after) // 2] - before[len(before) // 2]
    positive = [r for r in rises.values() if r > 0]
    if not positive:
        return {}
    unit = sorted(positive)[(len(positive) - 1) // 2]    # lower median: most steps are one row
    return {t: max(1, round(r / unit)) if r > 0 else 1 for t, r in rises.items()}


def feed_rows(teal: list[int]) -> int:
    """How many kill rows arrived in all (see row_counts)."""
    return sum(row_counts(teal).values())


def valorant_kills(path: Path) -> list[float]:
    return valorant_events(path)["times"]


BANNER_BEFORE = 0.9         # a kill's feed row appears up to this long before your banner...
BANNER_AFTER = 0.3          # ...or this long after it


def row_onsets(teal: list[int], rise: int = 40, hold: float = 0.3) -> list[float]:
    """Frames where a kill-feed row starts sliding in: teal jumps over the level just before
    and stays up (the row stays for seconds; a passing effect doesn't). Exact to the frame."""
    n, keep, look = len(teal), int(hold * FEED_FPS), 6
    out: list[float] = []
    i = look
    while i < n - keep:
        level = sorted(teal[i - look:i])[look // 2]
        if teal[i] >= level + rise and all(v >= level + 0.75 * rise for v in teal[i:i + keep]):
            out.append(round(i / FEED_FPS, 3))
            i += keep
            continue
        i += 1
    return out


def own_kills(onsets: list[float], banners: list[float]) -> list[float]:
    """Your kills, to the frame. The feed lists everyone's kills; only yours bring up your
    kill banner. For each banner: the latest feed row that started in the window around it
    (earlier rows there are other players' kills). No row in the window: just before the banner.
    Without readable banners, every row counts."""
    if not banners:
        return onsets
    mine: list[float] = []
    for b in banners:
        near = [t for t in onsets if b - BANNER_BEFORE <= t <= b + BANNER_AFTER and t not in mine]
        mine.append(max(near) if near else round(max(0.0, b - 0.1), 3))
    return sorted(set(mine))


def ace_onset(path: Path) -> float | None:
    """When the ACE banner appears. The round banners share its spot (top centre), so: white
    banner text over a see-through panel (ACE), not over a solid green (WON) or red (LOST) one,
    held for 0.4 s. Measured on four clips: green behind the text 0.0-0.48 for ACE, 0.76-0.79
    for WON."""
    w, h, fps = 48, 24, 10
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:v:0",
                           "-vf", f"fps={fps},crop=iw*0.14:ih*0.09:iw*0.43:ih*0.15,scale={w}:{h}",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True)
    raw, size, n = proc.stdout, w * h * 3, w * h
    on = []
    for f in range(len(raw) // size):
        px = raw[f * size:(f + 1) * size]
        white = green = red = rest = 0
        for i in range(0, size, 3):
            r, g, b = px[i], px[i + 1], px[i + 2]
            if min(r, g, b) > 190 and max(r, g, b) - min(r, g, b) < 35:
                white += 1
            elif min(r, g, b) <= 190:
                rest += 1
                green += g > r + 25 and g > b - 5
                red += r > g + 40 and r > b + 40
        rest = max(1, rest)
        on.append(white / n >= 0.12 and green / rest < 0.62 and red / rest < 0.5)
    hold = int(0.4 * fps)
    for i in range(len(on) - hold):
        if all(on[i:i + hold]):
            return round(i / fps, 2)
    return None


def valorant_events(path: Path) -> dict[str, Any]:
    """Kill moments plus the number of kills (a collateral is one moment but two kills)."""
    teal = _feed_teal(path)
    steps = feed_steps(teal)
    if steps:
        banners = _banner_onsets(path)
        onsets = row_onsets(_feed_band(path))
        mine = own_kills(onsets, banners)
        # The fifth kill of an ace brings up the ACE banner instead of the usual kill banner:
        # the last feed row just before it is that kill.
        ace = ace_onset(path)
        # A real ACE ends the play: it comes after your other kills, not in the middle of them.
        if ace is not None and mine and ace < max(mine) - 0.5:
            ace = None
        if ace is not None:
            final = [t for t in onsets if ace - 1.5 <= t <= ace + 0.1 and (not mine or t > max(mine) + 0.6)]
            if final:
                mine = sorted(mine + [max(final)])
        if mine:
            rows = row_counts(teal, [t for t in steps if any(abs(t - m) <= 0.7 for m in mine)])
            # Five enemies a round: a row landing just after someone else's can read double.
            count = min(5, max(len(mine), sum(rows.values())))
            if ace is not None:
                count = 5
            # Everyone else's kills (teammates', and teammates going down) are the story around yours.
            others = [t for t in onsets if all(abs(t - m) > 0.15 for m in mine)]
            return {"times": mine, "count": count, "feed_rows": len(steps), "banners": banners, "story": others,
                    "ace_at": ace}
    times = _banner_kills(path)
    return {"times": times, "count": len(times)}


def _banner_kills(path: Path) -> list[float]:
    # No teal kill-feed rows (other HUD colours, feed hidden): fall back to the kill banner.
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


def action_times(path: Path, hop: float = 0.05) -> list[float]:
    """Moments of action from the game audio: sharp, bright, loud sounds (gunfire, abilities,
    impacts) well above the clip's typical level. Footsteps, ambience and quiet holding don't
    register. Measured on real clips: these line up with the fights."""
    import numpy as np
    rate = 16000
    proc = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(rate),
                           "-f", "s16le", "-"], capture_output=True)
    if proc.returncode or not proc.stdout:
        return []
    x = np.frombuffer(proc.stdout[: len(proc.stdout) // 2 * 2], np.int16).astype(np.float32) / 32768
    n = int(rate * hop)
    m = len(x) // n
    if m < 10:
        return []
    d = np.diff(x, prepend=0.0)[: m * n].reshape(m, n)        # first difference: favours bright sounds
    db = 20 * np.log10(np.sqrt((d ** 2).mean(1)) + 1e-6)
    base = float(np.median(db))
    floor = np.array([db[max(0, i - 6):i + 1].min() for i in range(m)])
    hits = np.where((db > base + 12) & (db - floor > 8))[0] * hop
    out: list[float] = []
    for t in hits:
        if not out or t - out[-1] > 0.15:
            out.append(round(float(t), 2))
    return out


DETECTORS = {"valorant": valorant_events}


def find_events(path: Path, profile: str) -> dict[str, Any]:
    detector = DETECTORS.get(profile)
    if detector:
        found = detector(Path(path))
        if found["times"]:
            return {"source": f"{profile}-kills", **found}
    return {"source": "audio-hits", "times": audio_hits(Path(path)), "count": None}
