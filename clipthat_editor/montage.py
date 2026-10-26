"""Montage edit end to end: detect kills, read the song's beats, plan (director), render (compositor)."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from .compositor import render
from .director import velocity_montage
from .timeline import Timeline


def _duration(path: Path, stream: str) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
                          "stream=duration:format=duration", "-of", "json", str(path)],
                         capture_output=True, text=True).stdout
    data = json.loads(out or "{}")
    for s in data.get("streams", []):
        if s.get("duration"):
            return float(s["duration"])
    return float(data.get("format", {}).get("duration", 0) or 0)


def decoded_audio(path: Path, work: Path) -> Path:
    """The song as a WAV that runs at the right speed. Some files (HE-AAC v2, common in
    TikTok downloads) decode to half the samples with this FFmpeg; resample those back."""
    out = work / "song.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-ac", "2", "-ar", "44100", str(out)],
                   check=True)
    claimed, got = _duration(path, "a:0"), _duration(out, "a:0")
    if claimed and got and 0.45 < got / claimed < 0.55:
        fixed = work / "song-fixed.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(path), "-vn", "-af",
                        "asetrate=22050,aresample=44100", "-ac", "2", str(fixed)], check=True)
        return fixed
    return out


def montage(source: Path, music: Path, output: Path, *, profile: str = "valorant", words: list[str] | None = None,
            aspect: str = "16:9", fps: int = 60, timeline: Path | None = None, work: Path | None = None,
            preview: bool = False) -> dict[str, Any]:
    source, output = Path(source).resolve(), Path(output).resolve()
    work = Path(work) if work else Path(tempfile.mkdtemp(prefix="reroll-"))
    work.mkdir(parents=True, exist_ok=True)
    song = decoded_audio(Path(music), work)
    if timeline:
        tl = Timeline.load(timeline)
        events = {"source": "timeline"}
    else:
        from .beats import analyze_beats
        from .events import find_events
        events = find_events(source, profile)
        rhythm = analyze_beats(song)
        width, height = (1920, 1080) if aspect == "16:9" else (1080, 1920)
        tl = velocity_montage(str(source), _duration(source, "v:0"), events["times"], rhythm,
                              count=events.get("count"), words=words, width=width, height=height, fps=fps)
    plan = output.with_suffix(".timeline.json")
    tl.save(plan)
    result = render(tl, output, work, preview_music=song if preview else None)
    result.update(timeline=str(plan), events=events, notes=tl.notes)
    return result
