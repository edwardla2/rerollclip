"""Highlight: Reroll's automatic edit for one gameplay clip.

analyze -> decide -> render, one background job, no user input:

1. Analyze: the per-frame interest score from `analysis.score_clip` (audio loudness +
   visual change). For a clip saved by voice or hotkey the moment sits shortly before
   the trigger, so the trigger offset (when known) limits the search.
2. Decide: an edit decision list (EDL).
   - a window around the peak (peak ~70% in, setup before it, reaction after);
   - jump cuts: long low-energy stretches inside the window shrink to a short sliver,
     except right around the peak;
   - the peak itself plays at half speed with a slight punch-in zoom.
3. Render: one FFmpeg pass. 9:16 centre crop by default (the crosshair is the centre in a
   shooter), blur fill as an option; loudness normalised for short-form platforms;
   hardware H.264 encoder when the machine has one, x264 otherwise.

Every number here is a starting point to be tuned on real Medal clips. Nothing here is
machine learning; the per-game kill-feed signal comes later, only if it beats this.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import json
import re
from pathlib import Path
import subprocess
import time
from typing import Any

from .analysis import STEP, AnalysisError, score_clip, suggest_window
from .engine import EditorError, require_tool

MIN_RESULT = 5.0          # never cut the edit shorter than this
KEEP_EDGE = 0.3           # seconds kept either side of a cut, so cuts read as jump cuts
PROTECT_BEFORE = 2.0      # never cut this close before the peak...
PROTECT_AFTER = 1.0       # ...or after it
SLOW_MIN_STRENGTH = 0.45  # slow motion only for a peak this strong...
SLOW_MIN_PROMINENCE = 2.0 # ...that stands this many times above the window's typical level
TARGET_LUFS = -14.0       # short-form platform loudness
TARGET_PEAK = -1.0        # dBFS ceiling
CUT_FADE = 0.01           # 10 ms fades at every cut so the game audio never clicks

HW_ENCODERS = ["h264_nvenc", "h264_amf", "h264_qsv", "h264_videotoolbox"]


@dataclass(frozen=True)
class Profile:
    """Per-game starting points. Hypotheses to test on real clips, not tuned values."""
    name: str
    length: float               # seconds of source the window covers before cuts
    slow_motion: bool           # allowed at all; still needs a peak that stands out
    slow_half: float = 0.5      # slow motion covers peak +/- this
    slow_factor: float = 0.5    # playback speed during slow motion
    zoom: float = 1.0           # punch-in during slow motion
    layout: str = "center_crop"
    dead_fraction: float = 0.25 # a frame is "dead" below this share of the peak's score
    dead_min_run: float = 1.5   # only stretches at least this long get cut


PROFILES = {
    # A brief emphasis on the deciding elimination; keep the kill feed and the audio.
    "valorant": Profile("valorant", length=13.0, slow_motion=True, slow_half=0.4, slow_factor=0.6, zoom=1.1,
                        layout="focus"),
    # Sprays and rapid multi-kills keep their rhythm: no slow motion.
    "cs2": Profile("cs2", length=12.0, slow_motion=False, dead_min_run=2.0),
    # Build-up matters and building happens off-centre: longer window, whole frame.
    "fortnite": Profile("fortnite", length=16.0, slow_motion=False, layout="fit_blur", dead_min_run=2.0),
    # Quick setup and payoff; experiences vary, so keep the whole frame.
    "roblox": Profile("roblox", length=10.0, slow_motion=False, layout="fit_blur"),
    "generic": Profile("generic", length=14.0, slow_motion=True, zoom=1.15),
}


@dataclass
class Segment:
    start: float          # seconds into the source
    end: float
    speed: float = 1.0    # 0.5 = half speed
    zoom: float = 1.0
    fade_out: float = 0.0  # seconds of fade to black at the segment's end (picture and sound)
    impact: bool = False   # a kill cut: punch-in zoom and a quick flash as it lands

    @property
    def output_length(self) -> float:
        return (self.end - self.start) / self.speed


# ---------- decide ----------

def decide(score: list[float], duration: float, *, profile: Profile | str = "generic",
           length: float | None = None, trigger_offset: float | None = None,
           slow_motion: str = "auto") -> dict[str, Any]:
    """Turns a score curve into the edit: a window, jump cuts and, when earned, a slow-motion peak.

    slow_motion: "auto" (the profile decides, and only for a peak that stands out), "on", "off".
    """
    if isinstance(profile, str):
        if profile not in PROFILES:
            raise EditorError(f"Unknown profile {profile}; choose from {', '.join(PROFILES)}")
        profile = PROFILES[profile]
    if slow_motion not in ("auto", "on", "off"):
        raise EditorError("slow_motion must be auto, on or off")
    window = suggest_window(score, duration, length or profile.length, trigger_offset)
    w0, w1, peak = window["start"], window["start"] + window["duration"], window["peak"]
    strength = window["strength"]
    threshold = profile.dead_fraction * strength

    # Find dead stretches inside the window, away from the peak.
    cuts: list[tuple[float, float]] = []
    run_start = None
    first, last = int(w0 / STEP), min(len(score), int(w1 / STEP))
    for i in range(first, last + 1):
        t = i * STEP
        dead = (i < last and score[i] < threshold
                and not (peak - PROTECT_BEFORE <= t <= peak + PROTECT_AFTER))
        if dead and run_start is None:
            run_start = t
        elif not dead and run_start is not None:
            if t - run_start >= profile.dead_min_run:
                # Dead air at the window's edges is trimmed off; inside, it becomes a jump cut.
                a = w0 if run_start <= w0 + STEP else run_start + KEEP_EDGE
                b = w1 if i >= last else t - KEEP_EDGE
                cuts.append((a, b))
            run_start = None

    # Don't cut below the minimum length: drop the smallest cuts first.
    def kept_after(c: list[tuple[float, float]]) -> float:
        return (w1 - w0) - sum(b - a for a, b in c)
    cuts.sort(key=lambda c: c[1] - c[0], reverse=True)
    while cuts and kept_after(cuts) < MIN_RESULT:
        cuts.pop()
    cuts.sort()

    # Kept spans, then split the one holding the peak into normal / slow / normal.
    spans, cursor = [], w0
    for a, b in cuts:
        spans.append((cursor, a))
        cursor = b
    spans.append((cursor, w1))
    # Slow motion is earned, not automatic: the profile must allow it and the peak must stand out.
    inside = sorted(score[first:last]) or [0.0]
    typical = inside[len(inside) // 2]
    prominence = strength / max(typical, 0.02)
    if slow_motion == "on":
        slow, reason = True, "requested"
    elif slow_motion == "off":
        slow, reason = False, "turned off"
    elif not profile.slow_motion:
        slow, reason = False, f"off for {profile.name}"
    elif strength < SLOW_MIN_STRENGTH or prominence < SLOW_MIN_PROMINENCE:
        slow, reason = False, "peak doesn't stand out enough"
    else:
        slow, reason = True, "peak stands out"
    s0, s1 = max(w0, peak - profile.slow_half), min(w1, peak + profile.slow_half)
    segments: list[Segment] = []
    for a, b in spans:
        if b - a < 0.05:
            continue
        if slow and (a <= s0 < b or a < s1 <= b):
            lo, hi = max(a, s0), min(b, s1)
            if lo - a >= 0.05:
                segments.append(Segment(a, lo))
            segments.append(Segment(lo, hi, profile.slow_factor, profile.zoom))
            if b - hi >= 0.05:
                segments.append(Segment(hi, b))
        else:
            segments.append(Segment(a, b))
    segments = [Segment(round(s.start, 3), round(s.end, 3), s.speed, s.zoom) for s in segments]
    return {
        "profile": profile.name,
        "slow_motion": {"applied": slow, "reason": reason, "prominence": round(prominence, 2)},
        "window": {"start": round(w0, 3), "end": round(w1, 3)},
        "peak": peak,
        "strength": strength,
        "cuts": [{"start": round(a, 3), "end": round(b, 3)} for a, b in cuts],
        "segments": [asdict(s) for s in segments],
        "output_seconds": round(sum(s.output_length for s in segments), 3),
    }


# ---------- render ----------

_encoder_cache: dict[str, bool] = {}


def encoder_works(name: str) -> bool:
    """True if this FFmpeg build can actually open the encoder on this machine."""
    if name not in _encoder_cache:
        probe = subprocess.run(
            [require_tool("ffmpeg"), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "color=c=black:s=256x256:r=30:d=0.2", "-c:v", name, "-f", "null", "-"],
            capture_output=True, text=True)
        _encoder_cache[name] = probe.returncode == 0
    return _encoder_cache[name]


def pick_encoder(prefer: str = "auto") -> str:
    if prefer not in ("auto", "libx264") and prefer not in HW_ENCODERS:
        raise EditorError(f"Unknown encoder {prefer}")
    if prefer == "libx264":
        return "libx264"
    candidates = HW_ENCODERS if prefer == "auto" else [prefer]
    for name in candidates:
        if encoder_works(name):
            return name
    return "libx264"


def encoder_args(name: str) -> list[str]:
    if name == "libx264":
        return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-profile:v", "high", "-threads", "4"]
    if name == "h264_nvenc":
        return ["-c:v", name, "-preset", "p4", "-rc", "vbr", "-cq", "21", "-b:v", "0", "-profile:v", "high"]
    if name == "h264_amf":
        return ["-c:v", name, "-quality", "balanced", "-rc", "cqp", "-qp_i", "21", "-qp_p", "23"]
    if name == "h264_qsv":
        return ["-c:v", name, "-preset", "medium", "-global_quality", "22"]
    return ["-c:v", name, "-b:v", "12M"]  # videotoolbox


def _probe_stream(path: Path) -> dict[str, Any]:
    out = subprocess.run([require_tool("ffprobe"), "-v", "error", "-show_streams", "-show_format",
                          "-of", "json", str(path)], capture_output=True, text=True)
    if out.returncode:
        raise EditorError(f"Can't read media {path.name}")
    data = json.loads(out.stdout)
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not video:
        raise EditorError(f"No video stream in {path.name}")
    num, _, den = (video.get("avg_frame_rate") or "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) else 30.0
    return {"width": int(video["width"]), "height": int(video["height"]), "fps": fps,
            "has_audio": any(s.get("codec_type") == "audio" for s in data["streams"])}


def _measure(ffmpeg: str, path: Path) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBFS) of a file's audio."""
    out = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-map", "0:a:0",
                          "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    summary = out[out.rfind("Summary:"):] if "Summary:" in out else out
    lufs = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return (float(lufs.group(1)) if lufs else TARGET_LUFS,
            float(peak.group(1)) if peak else TARGET_PEAK)


def _set_loudness(ffmpeg: str, rendered: Path, output: Path) -> None:
    """Static gain to the platform target, capped so peaks stay under the ceiling. Video is copied."""
    lufs, peak = _measure(ffmpeg, rendered)
    gain = min(TARGET_LUFS - lufs, TARGET_PEAK - peak) if lufs > -70 else 0.0
    final = output.with_name(output.stem + ".level" + output.suffix)
    done = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(rendered), "-map", "0:v",
                           "-map", "0:a", "-c:v", "copy", "-af", f"volume={gain:.2f}dB", "-c:a", "aac", "-b:a", "160k",
                           "-movflags", "+faststart", str(final)], capture_output=True, text=True)
    rendered.unlink(missing_ok=True)
    if done.returncode:
        final.unlink(missing_ok=True)
        raise EditorError(f"Setting the volume failed: {done.stderr[-800:]}")
    final.replace(output)  # watchers never see a half-written edit


IMPACT_ZOOM = 0.12        # a kill cut lands 12 % zoomed in...
IMPACT_SETTLE = 0.25      # ...and settles back over this long
FLASH = 0.3               # brightness added on the cut, fading out over...
FLASH_TIME = 0.12         # ...this long
GRADE = "eq=contrast=1.12:saturation=1.12:gamma=0.96,vignette=angle=PI/6"
FEED_BOX = (0.30, 0.18, 0.70, 0.05)   # Valorant kill feed: w, h, x, y as shares of the frame


def _impact(s: Segment, width: int, height: int) -> str:
    """Punch-in zoom that settles, plus a white flash, at the start of a kill cut."""
    if not s.impact:
        return ""
    k = f"(1+{IMPACT_ZOOM}*max(0\\,1-t/{IMPACT_SETTLE}))"
    return (f",scale=w='trunc({width}*{k}/2)*2':h='trunc({height}*{k}/2)*2':eval=frame,crop={width}:{height}"
            f",eq=brightness='{FLASH}*max(0\\,1-t/{FLASH_TIME})':eval=frame,setsar=1")


def _dip(s: Segment) -> str:
    """Fade the segment's picture to black over its last fade_out seconds (the dip before a drop)."""
    if not s.fade_out:
        return ""
    out_len = s.output_length
    return f",fade=t=out:st={max(0.0, out_len - s.fade_out):.4f}:d={s.fade_out:.4f}:color=black"


def build_filtergraph(segments: list[Segment], *, src_w: int, src_h: int, width: int, height: int,
                      fps: int, layout: str, audio_input: str) -> str:
    """One filtergraph: trim each segment, retime it, frame it 9:16, concatenate, normalise loudness."""
    n = len(segments)
    parts = [f"[0:v]split={n}" + "".join(f"[vs{i}]" for i in range(n)),
             f"[{audio_input}]asplit={n}" + "".join(f"[as{i}]" for i in range(n))]
    aspect = width / height
    for i, s in enumerate(segments):
        retime = f",setpts={1 / s.speed:.4f}*PTS" if s.speed != 1 else ""
        if layout == "center_crop":
            # Crop the 9:16 slice (narrower when zoomed) straight from the source, then scale once.
            cw = f"trunc(min(iw\\,ih*{aspect:.6f})/{s.zoom:.4f}/2)*2"
            ch = f"trunc(min(ih\\,iw/{aspect:.6f})/{s.zoom:.4f}/2)*2"
            frame = f"crop={cw}:{ch},scale={width}:{height}:flags=bicubic,setsar=1"
            parts.append(f"[vs{i}]trim={s.start}:{s.end},setpts=PTS-STARTPTS{retime},{frame},fps={fps}{_dip(s)}[v{i}]")
        elif layout == "focus":
            # The action big: a centred square of the shot fills the width; the kill feed is cut
            # out and set above it; a blurred copy fills the rest. Graded, with impact on kills.
            zoom = (f",crop=trunc(iw/{s.zoom:.4f}/2)*2:trunc(ih/{s.zoom:.4f}/2)*2" if s.zoom != 1 else "")
            main = width                              # square side
            main_y = (height - main) // 2 + height // 48
            fw, fh, fx, fy = FEED_BOX
            feed_w = int(width * 0.6) // 2 * 2
            parts.append(
                f"[vs{i}]trim={s.start}:{s.end},setpts=PTS-STARTPTS{retime},split=3[f{i}][b{i}][k{i}];"
                f"[b{i}]scale={width // 8}:{height // 8}:force_original_aspect_ratio=increase,"
                f"crop={width // 8}:{height // 8},boxblur=4:2,scale={width}:{height},eq=brightness=-0.12[bb{i}];"
                f"[f{i}]crop=min(iw\\,ih):min(iw\\,ih){zoom},scale={main}:{main}:flags=bicubic[ff{i}];"
                f"[k{i}]crop=iw*{fw}:ih*{fh}:iw*{fx}:ih*{fy},scale={feed_w}:-2[kk{i}];"
                f"[bb{i}][ff{i}]overlay=0:{main_y}[m{i}];"
                f"[m{i}][kk{i}]overlay=(W-w)/2:{main_y}-h-{height // 64},setsar=1,fps={fps},{GRADE}"
                f"{_impact(s, width, height)}{_dip(s)}[v{i}]")
        else:
            zoom = (f",crop=trunc(iw/{s.zoom:.4f}/2)*2:trunc(ih/{s.zoom:.4f}/2)*2" if s.zoom != 1 else "")
            # Cheap blur fill: blur a small copy, then scale it up behind the shot.
            parts.append(
                f"[vs{i}]trim={s.start}:{s.end},setpts=PTS-STARTPTS{retime}{zoom},split=2[f{i}][b{i}];"
                f"[b{i}]scale={width // 8}:{height // 8}:force_original_aspect_ratio=increase,"
                f"crop={width // 8}:{height // 8},boxblur=4:2,scale={width}:{height}[bb{i}];"
                f"[f{i}]scale={width}:{height}:force_original_aspect_ratio=decrease[ff{i}];"
                f"[bb{i}][ff{i}]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={fps}{_impact(s, width, height)}{_dip(s)}[v{i}]")
        if s.speed < 1:
            # Pitch drops with the speed: the familiar heavy slow-motion sound.
            atime = f",asetrate=48000*{s.speed},aresample=48000"
        elif s.speed > 1:
            atime = f",atempo={s.speed:.4f}"   # sped-up stretches keep their pitch
        else:
            atime = ""
        out_len = (s.end - s.start) / s.speed
        tail = max(CUT_FADE, s.fade_out)
        fade = f",afade=t=in:d={CUT_FADE},afade=t=out:st={max(0.0, out_len - tail):.4f}:d={tail:.4f}" if out_len > 4 * CUT_FADE else ""
        parts.append(f"[as{i}]atrim={s.start}:{s.end},asetpts=PTS-STARTPTS,aresample=48000{atime}{fade}[a{i}]")
    parts.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    parts.append("[vc]format=yuv420p[v]")
    # One steady level for the whole edit is set after the render (see _set_loudness): a
    # dynamic normaliser here would pump the volume at every cut.
    parts.append("[ac]aresample=48000[a]")
    return ";".join(parts)


def auto_edit(source: Path, output: Path, *, profile: str = "generic", trigger_offset: float | None = None,
              length: float | None = None, width: int = 1080, height: int = 1920, fps: int | None = None,
              layout: str | None = None, slow_motion: str = "auto", encoder: str = "auto",
              music: Path | str | None = None, music_preview: Path | None = None,
              sounds_list: Path | None = None, sync: str = "auto") -> dict[str, Any]:
    """Edits one clip end to end. Returns the decisions and timings; writes `output`.

    With `music`, the edit is paced to that sound (see sync.py) and exported without it;
    `music="auto"` lets the engine pick the best-fitting sound from Reroll's sound list.
    `music_preview` additionally writes a private copy with the sound mixed in, for checking
    the timing only (not for posting)."""
    source, output = Path(source).resolve(), Path(output).resolve()
    if profile not in PROFILES:
        raise EditorError(f"Unknown profile {profile}; choose from {', '.join(PROFILES)}")
    layout = layout or PROFILES[profile].layout
    if layout not in ("center_crop", "fit_blur", "focus"):
        raise EditorError("layout must be center_crop, fit_blur or focus")
    began = time.monotonic()
    info = _probe_stream(source)
    scored = score_clip(source)
    analyzed = time.monotonic()
    if trigger_offset is not None:
        trigger_offset = min(max(0.0, trigger_offset), scored["duration"])
    if music is not None:
        from .events import find_events
        from .sync import plan_to_music
        events = find_events(source, profile)
        kills = events["times"] or [suggest_window(scored["score"], scored["duration"], 8.0)["peak"]]
        if str(music) == "auto":
            # The engine chooses: test-fit every sound on Reroll's list against these kills.
            from .sounds import pick
            choice = pick(kills, scored["duration"], game=profile, path=sounds_list, sync=sync)
            if not choice:
                from .sounds import load
                listed = load(sounds_list)
                raise EditorError(f"None of the {len(listed)} songs on the list has a beat map yet; "
                                  "map one with 'sounds add <audio> --id <song id>'" if listed else
                                  "The sound list is empty; add a sound with 'sounds add'")
            plan = choice["plan"]
            sound = choice["sound"]
            plan.update(music={"file": sound["title"], "bpm": sound["bpm"], "drop": sound["drop"],
                               "duration": sound["duration"]},
                        sound={"title": sound["title"], "artist": sound["artist"], "tiktok_url": sound["tiktok_url"],
                               "start_at": plan["sound_start"], "score": choice["score"]},
                        alternatives=choice["alternatives"])
            music_preview = None  # nothing to mix: the list holds beat maps, not audio
        else:
            from .beats import analyze_beats
            from .sync import plan_for
            rhythm = analyze_beats(Path(music))
            plan = plan_for(kills, scored["duration"], rhythm, sync)
            if plan is None:
                raise EditorError("This sound has no run of standout hits long enough for the kills; try sync=beats")
            plan.update(music={k: rhythm[k] for k in ("file", "bpm", "drop", "duration")})
        plan.update(events=events)
        first, last = plan["segments"][0]["start"], plan["segments"][-1]["end"]
        plan["window"] = {"start": first, "end": last}
        plan.setdefault("cuts", [])
        plan["peak"] = kills[-1]
        plan["strength"] = 0.0
        plan["slow_motion"] = {"applied": True, "reason": "final kill on the drop", "prominence": 0.0}
    else:
        plan = decide(scored["score"], scored["duration"], profile=profile, length=length,
                      trigger_offset=trigger_offset, slow_motion=slow_motion)
    segments = [Segment(**s) for s in plan["segments"]]
    out_fps = fps or (60 if info["fps"] >= 50 else 30)
    chosen = pick_encoder(encoder)

    ffmpeg = require_tool("ffmpeg")
    # Decode only the window: seek the input, and shift segment times to match.
    offset = plan["window"]["start"]
    span = plan["window"]["end"] - offset
    segments = [Segment(round(s.start - offset, 3), round(s.end - offset, 3), s.speed, s.zoom, s.fade_out, s.impact) for s in segments]
    args = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{offset:.3f}", "-t", f"{span:.3f}",
            "-i", str(source)]
    audio_input = "0:a:0"
    if not info["has_audio"]:
        args += ["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo:d={span:.3f}"]
        audio_input = "1:a:0"
    graph = build_filtergraph(segments, src_w=info["width"], src_h=info["height"], width=width,
                              height=height, fps=out_fps, layout=layout, audio_input=audio_input)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(output.stem + ".partial" + output.suffix)
    tail = ["-filter_complex", graph, "-map", "[v]", "-map", "[a]", "-r", str(out_fps), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(partial)]
    done = subprocess.run(args + encoder_args(chosen) + tail, capture_output=True, text=True)
    if done.returncode and chosen != "libx264":
        # A hardware encoder can fail mid-job (driver, session limit): fall back rather than fail.
        chosen = "libx264"
        done = subprocess.run(args + encoder_args(chosen) + tail, capture_output=True, text=True)
    if done.returncode:
        partial.unlink(missing_ok=True)
        raise EditorError(f"Render failed: {done.stderr[-2000:]}")
    _set_loudness(ffmpeg, partial, output)  # also moves the finished file into place
    finished = time.monotonic()
    if music is not None and music_preview is not None:
        start = plan["sound_start"]
        mix = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(output),
                              "-ss", f"{start:.3f}", "-i", str(music), "-filter_complex",
                              "[0:a]volume=0.35[g];[1:a]aresample=48000,volume=0.85[m];[g][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false[a]",
                              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k",
                              "-movflags", "+faststart", str(Path(music_preview).resolve())], capture_output=True, text=True)
        if mix.returncode:
            raise EditorError(f"Preview mix failed: {mix.stderr[-1000:]}")
    return {
        "ok": True, "style": "highlight", "source": source.name, "output": str(output),
        "width": width, "height": height, "fps": out_fps, "layout": layout, "encoder": chosen,
        "signals": scored["signals"], "source_seconds": round(scored["duration"], 3), **plan,
        "timings": {"analyze_s": round(analyzed - began, 2), "render_s": round(finished - analyzed, 2),
                    "total_s": round(finished - began, 2)},
    }


__all__ = ["auto_edit", "decide", "pick_encoder", "Profile", "PROFILES", "Segment", "AnalysisError"]
