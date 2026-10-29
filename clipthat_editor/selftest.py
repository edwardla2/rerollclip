"""`reroll-engine selftest`: proves a machine can run the whole engine without any real clips.

It makes two synthetic clips with FFmpeg, runs the kill detector over one (expects nothing found,
but exercises the decoding and numpy/scipy code), then plans and renders a short story compilation
from hand-written plays, and checks the result. The Windows build runs it on every push; on a
tester's PC it's the first thing to try.
"""
from __future__ import annotations

import json
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def _clip(path: Path, color: str, seconds: float) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=s=1280x720:r=30:d={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=330:duration={seconds}:sample_rate=48000",
                    "-filter_complex", f"[0:v]drawbox=x=0:y=0:w=iw:h=ih:color={color}@0.25:t=fill[v]",
                    "-map", "[v]", "-map", "1:a", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)


def run(work: Path | None = None, keep: bool = False) -> dict[str, Any]:
    started = time.time()
    steps: dict[str, Any] = {}
    work = Path(work) if work else Path(tempfile.mkdtemp(prefix="reroll-selftest-"))
    work.mkdir(parents=True, exist_ok=True)
    try:
        for tool in ("ffmpeg", "ffprobe"):
            found = shutil.which(tool)
            if not found:
                return {"ok": False, "failed": f"{tool} not found"}
            steps[tool] = found
        version = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout.splitlines()[0]
        steps["ffmpeg_version"] = version
        if "--enable-libx264" not in subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True).stdout:
            return {"ok": False, "failed": "this ffmpeg has no libx264 (H.264 encoder)", **steps}

        a, b = work / "clip-a.mp4", work / "clip-b.mp4"
        _clip(a, "red", 8)
        _clip(b, "blue", 10)
        steps["clips"] = "ok"

        from .events import find_events
        ev = find_events(a, "valorant")
        steps["detector"] = {"source": ev.get("source"), "kills": len(ev.get("times", []))}

        from .events import action_times
        steps["audio_analysis"] = len(action_times(a))

        from .montage import compile_plays
        plays = [
            {"source": str(a), "duration": 8.0, "kills": [3.0, 5.5], "story": [], "count": 2,
             "height": 720, "game": "valorant", "action": [2.8, 3.0, 5.4]},
            {"source": str(b), "duration": 10.0, "kills": [4.0, 6.0, 8.0], "story": [], "count": 3,
             "height": 720, "game": "valorant", "action": [3.9, 6.0, 7.9]},
        ]
        out = work / "selftest-compilation.mp4"
        result = compile_plays(plays, out, work=work / "render")
        probe = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
             "-of", "json", str(out)], capture_output=True, text=True).stdout)
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        has_audio = any(s["codec_type"] == "audio" for s in probe["streams"])
        duration = float(probe["format"]["duration"])
        steps["render"] = {"width": video["width"], "height": video["height"], "seconds": round(duration, 2),
                           "audio": has_audio}
        ok = video["width"] == 1080 and video["height"] == 1920 and has_audio and duration > 3
        return {"ok": ok, "seconds_taken": round(time.time() - started, 1),
                "machine": f"{platform.system()} {platform.release()} {platform.machine()}",
                "output": str(out) if keep else None, **steps,
                **({} if ok else {"failed": "rendered video has the wrong shape", "render_result": result})}
    finally:
        if not keep:
            shutil.rmtree(work, ignore_errors=True)
