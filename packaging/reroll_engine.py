"""Entry point for the packaged Windows engine (reroll-engine.exe).

The build puts ffmpeg.exe and ffprobe.exe in an `ffmpeg` folder next to the exe; they go first on
PATH so the engine never picks up some other FFmpeg the player has installed.
"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    bundled = Path(sys.executable).resolve().parent / "ffmpeg"
    os.environ["PATH"] = str(bundled) + os.pathsep + os.environ.get("PATH", "")

from clipthat_editor.engine import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
