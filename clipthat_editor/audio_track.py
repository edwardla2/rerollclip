"""Which audio track of a clip is the game.

Medal can record several tracks: the first is everything mixed (game plus voice chat and mic),
the second is the game alone, the rest are voice chat, mic or other apps, some silent. Measured
on a real Medal clip (2026-10-28): track 1 = track 2 + track 5 (voice chat), tracks 3-4 silent.
Reroll exports game audio only, and its sound analysis is about the game, so it reads track 2
when a clip has one with sound in it, else the first track.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
import subprocess

SILENT_DB = -60.0


def _audio_streams(path: Path) -> int:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                          "-of", "json", str(path)], capture_output=True, text=True).stdout
    try:
        return len(json.loads(out).get("streams", []))
    except json.JSONDecodeError:
        return 0


def _peak_db(path: Path, track: int, seconds: float = 60.0) -> float:
    err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-t", str(seconds), "-i", str(path),
                          "-map", f"0:a:{track}", "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"max_volume:\s*(-?[\d.]+|-inf) dB", err)
    return float(m.group(1)) if m and m.group(1) != "-inf" else -200.0


@lru_cache(maxsize=256)
def _game_track(path: str, size: int, mtime: float) -> int:
    p = Path(path)
    if _audio_streams(p) < 2:
        return 0
    return 1 if _peak_db(p, 1) > SILENT_DB else 0


def game_track(path: Path | str) -> int:
    """Index among the clip's audio streams (for -map 0:a:N and [0:a:N])."""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return 0
    return _game_track(str(p.resolve()), st.st_size, st.st_mtime)
