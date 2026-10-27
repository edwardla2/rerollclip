"""External creative review: every iteration is packaged in renders/vNNN/ for the reviewer,
and reviews come back as feedback/vNNN.md. Previous versions are never overwritten.

renders/vNNN/
  edit.mp4         the postable export (no music)
  preview.mp4      the same with the sound mixed in, for judging sync (never posted)
  timeline.json    every cut, speed key, camera and effect keyframe the render used
  taste.json       the effective taste profile (editorial parameters)
  summary.md       what the edit is, per-shot list, effect parameters, and the changes made
  sheet.png        frames at every kill and cut, for a quick look
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from .timeline import Timeline

ROOT = Path(__file__).resolve().parent.parent
RENDERS = ROOT / "renders"
FEEDBACK = ROOT / "feedback"


def next_version() -> str:
    RENDERS.mkdir(exist_ok=True)
    nums = [int(m.group(1)) for p in RENDERS.iterdir() if (m := re.fullmatch(r"v(\d{3})", p.name))]
    return f"v{(max(nums) + 1) if nums else 1:03d}"


def latest_feedback() -> tuple[str, str] | None:
    """(name, text) of the newest review in feedback/, if any."""
    if not FEEDBACK.exists():
        return None
    files = sorted(p for p in FEEDBACK.glob("v*.md"))
    return (files[-1].name, files[-1].read_text()) if files else None


def _sheet(video: Path, times: list[float], out: Path) -> None:
    font = Path(__file__).parent / "assets" / "SpaceGrotesk-Bold.ttf"
    tmp = out.parent / "_frames"
    tmp.mkdir(exist_ok=True)
    for i, t in enumerate(times):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}", "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale=360:-2,drawtext=fontfile={font}:text='{t:.2f}s':fontcolor=yellow:fontsize=22"
                               f":borderw=2:x=8:y=8", str(tmp / f"{i:03d}.png")], check=True)
    cols = min(6, len(times))
    rows = (len(times) + cols - 1) // cols
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", "1", "-i", str(tmp / "%03d.png"),
                    "-vf", f"tile={cols}x{rows}", "-frames:v", "1", str(out)], check=True)
    shutil.rmtree(tmp)


def _speed_summary(tl: Timeline) -> str:
    """Stated from the keys, so the summary can't claim "no ramps" when there are."""
    changed = [c for c in tl.clips if any(abs(k.speed_in - 1) > 0.01 or abs(k.speed_out - 1) > 0.01 for k in c.keys)]
    if not changed:
        return "real speed (1.0x) throughout"
    parts = []
    for c in changed:
        speeds = [s for k in c.keys for s in (k.speed_in, k.speed_out)]
        parts.append(f"{c.label} ({c.out_start:.2f}-{c.out_end:.2f} s) {min(speeds):.2f}x-{max(speeds):.2f}x")
    return "real speed except " + "; ".join(parts)


def _summary(tl: Timeline, version: str, changes: list[str], taste: dict[str, Any], probe: dict[str, Any]) -> str:
    lines = [f"# Reroll render {version}", "",
             f"- Length: {tl.duration:.2f} s, {tl.width}x{tl.height} @ {tl.fps} fps",
             f"- Measured: {probe}",
             f"- Song (preview only): {tl.music.get('title') or Path(tl.music.get('file') or '-').name}, "
             f"{tl.music.get('bpm')} BPM, starts at {tl.music.get('start')} s of the sound; "
             + (f"drop at {tl.music['drop']} s" if tl.music.get('drop') is not None else
                f"no drop used (candidate {tl.music.get('drop_candidate_s')} s, {tl.music.get('drop_confidence', 'n/a')})"),
             "- Speed: " + _speed_summary(tl),
             f"- Taste: mode {taste.get('mode')}, intensity {taste.get('intensity')}", "",
             "## Changes in this version", ""] + [f"- {c}" for c in changes] + ["", "## Shots", "",
             "| # | Output | Source | Clip | Speeds | Framing |", "|---|---|---|---|---|---|"]
    for i, c in enumerate(sorted(tl.clips, key=lambda c: c.out_start), 1):
        speeds = sorted({round(k.speed_out, 2) for k in c.keys})
        lines.append(f"| {i} | {c.out_start:.2f}-{c.out_end:.2f} | {c.src_in:.2f}-{c.src_out:.2f} | "
                     f"{Path(c.source or tl.source).name} | {speeds} | {c.framing}{' + feed' if c.feed_inset else ''} |")
    lines += ["", "## Effects (master keyframes, output time)", ""]
    for name, curve in tl.master.items():
        if not curve.is_const(0.0):
            peaks = [(round(k[0], 2), round(k[1], 2)) for k in curve.keys if k[1] > 0]
            lines.append(f"- {name}: {peaks}")
    lines += ["", "## Planner notes", ""] + [f"- {n}" for n in tl.notes]
    lines += ["", f"Kills land at (output s): {tl.music.get('kills_at')}", ""]
    return "\n".join(lines)


def package(output: Path, timeline: Path, changes: list[str], taste: dict[str, Any],
            preview: Path | None = None) -> Path:
    version = next_version()
    folder = RENDERS / version
    folder.mkdir(parents=True)
    shutil.copy2(output, folder / "edit.mp4")
    if preview and Path(preview).exists():
        shutil.copy2(preview, folder / "preview.mp4")
    shutil.copy2(timeline, folder / "timeline.json")
    (folder / "taste.json").write_text(json.dumps(taste, indent=2))
    tl = Timeline.load(timeline)
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,r_frame_rate",
                          "-of", "compact", str(output)], capture_output=True, text=True).stdout.strip().replace("\n", "; ")
    loud = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(output), "-af", "ebur128=peak=true",
                           "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.findall(r"I:\s+(-?[\d.]+) LUFS", loud)
    p = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", loud)
    probe = {"streams": out, "loudness_lufs": m[-1] if m else None, "true_peak_dbfs": p[-1] if p else None}
    (folder / "summary.md").write_text(_summary(tl, version, changes, taste, probe))
    times = sorted(set([0.2] + [round(t, 2) for t in tl.music.get("kills_at", [])] +
                       [round(c.out_start + 0.05, 2) for c in tl.clips] + [round(tl.duration - 0.1, 2)]))
    _sheet(folder / "edit.mp4", times, folder / "sheet.png")
    return folder
