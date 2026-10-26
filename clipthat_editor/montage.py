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


def montage(source: Path, music: Path | None, output: Path, *, profile: str = "valorant",
            words: list[str] | None = None, style: str = "gameplay", taste_path: Path | None = None,
            intensity: str | None = None, aspect: str | None = None, fps: int | None = None,
            timeline: Path | None = None, work: Path | None = None, preview: bool = False) -> dict[str, Any]:
    """style "gameplay" (default, taste profile driven) or "stylized" (the velocity montage)."""
    source, output = Path(source).resolve(), Path(output).resolve()
    work = Path(work) if work else Path(tempfile.mkdtemp(prefix="reroll-"))
    work.mkdir(parents=True, exist_ok=True)
    song = decoded_audio(Path(music), work) if music else None
    if timeline:
        tl = Timeline.load(timeline)
        events = {"source": "timeline"}
    else:
        from .beats import analyze_beats
        from .events import find_events
        events = find_events(source, profile)
        rhythm = analyze_beats(song) if song else None
        if style == "stylized":
            if not rhythm:
                raise ValueError("the stylized montage needs a song to cut to")
            width, height = (1920, 1080) if (aspect or "16:9") == "16:9" else (1080, 1920)
            tl = velocity_montage(str(source), _duration(source, "v:0"), events["times"], rhythm,
                                  count=events.get("count"), words=words, width=width, height=height, fps=fps or 60)
        else:
            from .director import gameplay_first
            from .taste import load
            fmt = {}
            if aspect:
                fmt = {"aspect": aspect, "width": 1920 if aspect == "16:9" else 1080,
                       "height": 1080 if aspect == "16:9" else 1920}
            if fps:
                fmt["fps"] = fps
            taste = load(taste_path, intensity=intensity, format=fmt or None)
            tl = gameplay_first(str(source), _duration(source, "v:0"), events["times"], rhythm, taste,
                                count=events.get("count"), words=words)
    plan = output.with_suffix(".timeline.json")
    tl.save(plan)
    result = render(tl, output, work, preview_music=song if (preview and song) else None)
    result.update(timeline=str(plan), events=events, notes=tl.notes)
    return result


def compile_clips(sources: list[Path], music: Path | None, output: Path, *, profile: str = "valorant",
                  taste_path: Path | None = None, intensity: str | None = None, work: Path | None = None,
                  preview: bool = False) -> dict[str, Any]:
    """Story mode: several clips into one lightly edited video, best play last."""
    from .beats import analyze_beats
    from .compositor import _probe
    from .director import story_compilation
    from .events import find_events
    from .taste import load
    output = Path(output).resolve()
    work = Path(work) if work else Path(tempfile.mkdtemp(prefix="reroll-"))
    work.mkdir(parents=True, exist_ok=True)
    song = decoded_audio(Path(music), work) if music else None
    plays = []
    for src in sources:
        src = Path(src).resolve()
        ev = find_events(src, profile)
        info = _probe(src)
        plays.append({"source": str(src), "duration": _duration(src, "v:0"), "kills": ev["times"],
                      "story": ev.get("story", []), "count": ev.get("count"), "height": info["height"],
                      "game": profile if ev["source"].endswith("-kills") else None})
    taste = load(taste_path, intensity=intensity)
    tl = story_compilation(plays, analyze_beats(song) if song else None, taste)
    plan = output.with_suffix(".timeline.json")
    tl.save(plan)
    result = render(tl, output, work, preview_music=song if (preview and song) else None)
    result.update(timeline=str(plan), plays=[{k: p[k] for k in ("source", "kills", "story", "count")} for p in plays],
                  notes=tl.notes)
    return result
