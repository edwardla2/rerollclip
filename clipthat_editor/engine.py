"""Local MP4 montage renderer. Uses FFmpeg; no third-party Python packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any


class EditorError(Exception):
    pass


def require_tool(name: str) -> str:
    tool = shutil.which(name)
    if not tool:
        raise EditorError(f"Required executable '{name}' is missing from PATH")
    return tool


def run(args: list[str]) -> None:
    completed = subprocess.run(args, capture_output=True, text=True)
    if completed.returncode:
        raise EditorError(f"Command failed ({completed.returncode}): {args[0]}\n{completed.stderr[-5000:]}")


def probe(path: Path) -> tuple[float, bool]:
    command = [require_tool("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)]
    output = subprocess.run(command, capture_output=True, text=True)
    if output.returncode:
        raise EditorError(f"Can't read media {path}: {output.stderr[-500:]}")
    data = json.loads(output.stdout)
    streams = data.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise EditorError(f"File does not contain a video stream: {path}")
    duration = float(data.get("format", {}).get("duration", 0))
    return duration, any(s.get("codec_type") == "audio" for s in streams)


def resolve_file(manifest_path: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    return path.resolve()


def parse_manifest(manifest_path: Path, check_files: bool = True) -> dict[str, Any]:
    if not manifest_path.is_file():
        raise EditorError(f"Manifest not found: {manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise EditorError(f"Invalid manifest JSON: {exc}") from exc
    if data.get("schema_version") != 1:
        raise EditorError("Unsupported manifest schema_version (expected 1)")
    clips = data.get("clips")
    if not isinstance(clips, list) or not clips:
        raise EditorError("Manifest requires at least one clip")
    if data.get("style", "clean") not in {"clean", "cinematic", "high_energy"}:
        raise EditorError("Unknown style")
    if data.get("layout", "fit_blur") not in {"fit_blur", "center_crop"}:
        raise EditorError("Unknown layout")
    out = data.get("output", {})
    width, height, fps = out.get("width", 1080), out.get("height", 1920), out.get("fps", 30)
    if (not all(isinstance(x, int) and not isinstance(x, bool) for x in [width, height, fps])
            or width < 240 or height < 240 or width > 3840 or height > 3840 or fps < 1 or fps > 120
            or width % 2 or height % 2):
        raise EditorError("Output dimensions must be even integers between 240 and 3840; fps 1-120")
    if len(clips) > 100:
        raise EditorError("Limit of 100 clips per render")
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict) or not isinstance(clip.get("file"), str) or not clip["file"]:
            raise EditorError(f"clip #{index} must provide 'file'")
        start, duration = clip.get("start_seconds", 0), clip.get("duration_seconds")
        if (not isinstance(start, (int, float)) or isinstance(start, bool) or start < 0
                or not isinstance(duration, (int, float)) or isinstance(duration, bool)
                or duration <= 0 or duration > 120):
            raise EditorError(f"clip #{index} needs start_seconds >= 0 and duration_seconds > 0 (max 120)")
        path = resolve_file(manifest_path, clip["file"])
        if check_files:
            if not path.is_file():
                raise EditorError(f"Missing clip file: {path}")
            media_duration, _ = probe(path)
            if media_duration and start + duration > media_duration + 0.25:
                raise EditorError(f"Clip selection exceeds media duration: {path}")
    music = data.get("music")
    if music is not None:
        if not isinstance(music, dict) or not isinstance(music.get("file"), str):
            raise EditorError("music must be null or an object with 'file'")
        volume = music.get("volume", 0.15)
        if not isinstance(volume, (int, float)) or isinstance(volume, bool) or not 0 <= volume <= 1:
            raise EditorError("music.volume must be between 0 and 1")
        if check_files and not resolve_file(manifest_path, music["file"]).is_file():
            raise EditorError("Music file does not exist")
    return data


def make_segment(path: Path, output: Path, start: float, duration: float, *, width: int, height: int,
                 fps: int, layout: str) -> None:
    _, has_audio = probe(path)
    ffmpeg = require_tool("ffmpeg")
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", str(start), "-t", str(duration), "-i", str(path)]
    if not has_audio:
        args += ["-f", "lavfi", "-t", str(duration), "-i", "anullsrc=r=48000:cl=stereo"]
    if layout == "center_crop":
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
        args += ["-vf", vf]
    else:
        fc = (f"[0:v]split=2[fg0][bg0];"
              f"[bg0]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=16:1[bg];"
              f"[fg0]scale={width}:{height}:force_original_aspect_ratio=decrease,setsar=1[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps},format=yuv420p[v]")
        args += ["-filter_complex", fc]
    args += ["-map", "[v]" if layout == "fit_blur" else "0:v:0",
             "-map", "0:a:0" if has_audio else "1:a:0",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
             "-r", str(fps), "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2",
             "-t", str(duration), "-movflags", "+faststart", str(output)]
    run(args)


def render(manifest_path: Path, output: Path) -> None:
    manifest_path = manifest_path.resolve()
    data = parse_manifest(manifest_path)
    require_tool("ffmpeg")
    width, height, fps = (data.get("output", {}).get(k, default) for k, default in
                          [("width", 1080), ("height", 1920), ("fps", 30)])
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="clipthat-") as temp:
        tempdir = Path(temp)
        segments = []
        for index, clip in enumerate(data["clips"]):
            dest = tempdir / f"segment-{index:03d}.mp4"
            make_segment(resolve_file(manifest_path, clip["file"]), dest,
                         float(clip.get("start_seconds", 0)), float(clip["duration_seconds"]),
                         width=width, height=height, fps=fps, layout=data.get("layout", "fit_blur"))
            segments.append(dest)
        playlist = tempdir / "segments.txt"
        playlist.write_text("".join(f"file '{p.name}'\n" for p in segments), encoding="utf-8")
        joined = tempdir / "joined.mp4"
        run([require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
             "-i", str(playlist), "-c", "copy", "-movflags", "+faststart", str(joined)])
        music = data.get("music")
        if music:
            track = resolve_file(manifest_path, music["file"])
            volume = float(music.get("volume", 0.15))
            fc = f"[0:a]volume=1.0[a0];[1:a]volume={volume}[a1];[a0][a1]amix=inputs=2:duration=first:normalize=0[a]"
            run([require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-y", "-i", str(joined),
                 "-stream_loop", "-1", "-i", str(track), "-filter_complex", fc,
                 "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                 "-movflags", "+faststart", "-shortest", str(output)])
        else:
            shutil.copy2(joined, output)
    print(json.dumps({"ok": True, "output": str(output), "clips": len(data["clips"]),
                      "width": width, "height": height, "fps": fps}))


def main() -> int:
    from .analysis import AnalysisError
    parser = argparse.ArgumentParser(description="Reroll local editor")
    sub = parser.add_subparsers(dest="command", required=True)
    validate_parser = sub.add_parser("validate", help="Check manifest JSON and input paths")
    validate_parser.add_argument("manifest", type=Path)
    render_parser = sub.add_parser("render", help="Render a montage from the manifest")
    render_parser.add_argument("manifest", type=Path)
    render_parser.add_argument("--output", required=True, type=Path)
    analyze_parser = sub.add_parser("analyze", help="Suggest a trim window around the clip's key moment")
    analyze_parser.add_argument("file", type=Path)
    analyze_parser.add_argument("--length", type=float, default=8.0, help="target window length in seconds")
    analyze_parser.add_argument("--trigger-offset", type=float, default=None,
                                help="seconds into the clip where the user said 'Clip that'")
    auto_parser = sub.add_parser("auto", help="Edit one gameplay clip automatically (Highlight style)")
    auto_parser.add_argument("file", type=Path)
    auto_parser.add_argument("--output", required=True, type=Path)
    auto_parser.add_argument("--trigger-offset", type=float, default=None,
                             help="seconds into the clip where the user asked for the edit, if known")
    auto_parser.add_argument("--profile", choices=["generic", "valorant", "cs2", "fortnite", "roblox"], default="generic",
                             help="per-game starting points for length, slow motion and framing")
    auto_parser.add_argument("--length", type=float, default=None, help="seconds of source around the peak (default: profile)")
    auto_parser.add_argument("--layout", choices=["center_crop", "fit_blur"], default=None, help="default: profile")
    auto_parser.add_argument("--slow-motion", choices=["auto", "on", "off"], default="auto")
    auto_parser.add_argument("--size", choices=["720", "1080"], default="1080")
    auto_parser.add_argument("--fps", type=int, choices=[30, 60], default=None, help="default: 60 for 50+ fps sources")
    auto_parser.add_argument("--encoder", default="auto", help="auto, libx264 or a hardware encoder name")
    auto_parser.add_argument("--music", default=None,
                             help="'auto' to let the engine pick from the sound list, or an audio file to pace the "
                                  "edit to; the export never includes the music (add it in TikTok)")
    auto_parser.add_argument("--sounds", type=Path, default=None, help="sound list to pick from (default: built-in)")
    auto_parser.add_argument("--music-preview", type=Path, default=None,
                             help="also write a private copy with the sound mixed in, to check the timing")
    eval_parser = sub.add_parser("evaluate", help="Edit every clip in a folder and write a side-by-side review report")
    eval_parser.add_argument("clips", type=Path)
    eval_parser.add_argument("out", type=Path)
    eval_parser.add_argument("--profile", choices=["generic", "valorant", "cs2", "fortnite", "roblox"], default="generic")
    eval_parser.add_argument("--slow-motion", choices=["auto", "on", "off"], default="auto")
    eval_parser.add_argument("--size", choices=["720", "1080"], default="1080")
    eval_parser.add_argument("--encoder", default="auto")
    sounds_parser = sub.add_parser("sounds", help="Manage the sound list the engine picks from")
    sounds_sub = sounds_parser.add_subparsers(dest="sounds_command", required=True)
    add_parser = sounds_sub.add_parser("add", help="Read a sound's rhythm and add it to the list (audio isn't kept)")
    add_parser.add_argument("audio", type=Path)
    add_parser.add_argument("--title", required=True)
    add_parser.add_argument("--artist", required=True)
    add_parser.add_argument("--url", default="", help="the sound's TikTok link")
    add_parser.add_argument("--games", default="", help="comma-separated, e.g. valorant,cs2")
    add_parser.add_argument("--list", type=Path, default=None)
    list_parser = sounds_sub.add_parser("list", help="Show the sound list")
    list_parser.add_argument("--list", type=Path, default=None)
    opts = parser.parse_args()
    try:
        if opts.command == "validate":
            data = parse_manifest(opts.manifest.resolve())
            print(json.dumps({"ok": True, "clips": len(data["clips"])}))
        elif opts.command == "analyze":
            from .analysis import analyze
            print(json.dumps(analyze(opts.file, length=opts.length, trigger_offset=opts.trigger_offset)))
        elif opts.command == "sounds":
            from . import sounds
            if opts.sounds_command == "add":
                games = [g.strip() for g in opts.games.split(",") if g.strip()]
                print(json.dumps(sounds.add(opts.audio, title=opts.title, artist=opts.artist, url=opts.url,
                                            games=games, path=opts.list)))
            else:
                print(json.dumps(sounds.load(opts.list), indent=2))
        elif opts.command == "evaluate":
            from .evaluate import evaluate
            print(json.dumps(evaluate(opts.clips, opts.out, profile=opts.profile, slow_motion=opts.slow_motion,
                                      size=opts.size, encoder=opts.encoder)))
        elif opts.command == "auto":
            from .highlight import auto_edit
            width, height = (720, 1280) if opts.size == "720" else (1080, 1920)
            print(json.dumps(auto_edit(opts.file, opts.output, profile=opts.profile, trigger_offset=opts.trigger_offset,
                                       length=opts.length, width=width, height=height, fps=opts.fps,
                                       layout=opts.layout, slow_motion=opts.slow_motion, encoder=opts.encoder,
                                       music=opts.music if opts.music in (None, "auto") else Path(opts.music),
                                       music_preview=opts.music_preview, sounds_list=opts.sounds)))
        else:
            render(opts.manifest, opts.output)
        return 0
    except (EditorError, AnalysisError, OSError, ValueError) as err:
        print(json.dumps({"ok": False, "error": str(err)}), file=sys.stderr)
        return 1
