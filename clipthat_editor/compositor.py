"""Renders a Timeline (timeline.py) to video. Rendering only: no creative decisions here.

Two passes:
  1. Picture and game sound per clip: frame-accurate trim, shutter (motion blur), the
     nonlinear time remap, synthesized in-between frames, then the camera (rotation, zoom,
     pan, shake) with per-frame keyframed expressions. Clips are concatenated into a
     high-quality intermediate.
  2. Master layers in output time: grade, typography (rendered by typography.py, positioned
     with the footage's measured motion), bloom, radial blur, colour split, exposure flashes,
     edge glow, luma reveals; sound effects mixed over the game audio. Keyframed master
     values are driven frame by frame through a command stream (FFmpeg sendcmd).
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from .timeline import Clip, Curve, Timeline

ASSETS = Path(__file__).parent / "assets"


class RenderError(RuntimeError):
    pass


def _run(args: list[str], what: str) -> None:
    done = subprocess.run(args, capture_output=True, text=True)
    if done.returncode:
        raise RenderError(f"{what} failed ({done.returncode}): {done.stderr[-3000:]}")


def _probe(path: Path) -> dict[str, Any]:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                         capture_output=True, text=True, check=True).stdout
    data = json.loads(out)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    return {"width": int(video["width"]), "height": int(video["height"]),
            "fps": float(num) / float(den or 1),
            "has_audio": any(s["codec_type"] == "audio" for s in data["streams"])}


# ---------------------------------------------------------------- pass 1: clips

def _shake_expr(clip: Clip, axis: str, width: int, t: str = "t") -> str:
    terms = []
    for i, s in enumerate(clip.shakes):
        phase = 0.0 if axis == "x" else 1.3
        f = s.freq if axis == "x" else s.freq * 0.83
        amp = s.amp * width * (1.0 if axis == "x" else 0.6)
        terms.append(f"gte({t}\\,{s.t:.4f})*{amp:.2f}*exp(-({t}-{s.t:.4f})/{s.decay:.4f})"
                     f"*sin(2*PI*{f:.2f}*({t}-{s.t:.4f})+{phase + i:.2f})")
    return "+".join(terms) if terms else "0"


INTERPOLATE = "minterpolate=fps={fps}:mi_mode=mci:mc_mode=obmc:me=epzs:search_param=24"


TEAL = "255*gt(g(X\\,Y)\\,140)*gt(g(X\\,Y)-r(X\\,Y)\\,50)*gt(b(X\\,Y)-r(X\\,Y)\\,20)"
RED = "255*gt(r(X\\,Y)\\,170)*gt(r(X\\,Y)-g(X\\,Y)\\,70)*gt(r(X\\,Y)-b(X\\,Y)\\,60)"


def feed_rows_chain(label: str, width: int) -> str:
    """Valorant's kill feed, rows only: a pixel line counts as a row when it carries both the
    teal and the red of a feed row; each row is kept across its own extent (names, weapon,
    portraits), everything else is transparent, so no scenery comes along with it."""
    def thr(v: int) -> str:
        return f"lut=y='if(gt(val\\,{v})\\,255\\,0)'"
    return (f"[{label}]crop=iw*0.30:ih*0.20:iw*0.70:ih*0.065,split[fc][fm];"
            f"[fm]format=gbrp,split[t0][r0];"
            f"[t0]geq=r='{TEAL}':g='{TEAL}':b='{TEAL}',format=gray,split[ta][tb];"
            f"[r0]geq=r='{RED}':g='{RED}':b='{RED}',format=gray,split[ra][rb];"
            f"[ta]avgblur=sizeX=600:sizeY=1,{thr(8)}[tl];[ra]avgblur=sizeX=600:sizeY=1,{thr(8)}[rl];"
            f"[tb][rb]blend=all_mode=lighten,avgblur=sizeX=50:sizeY=1,{thr(70)},avgblur=sizeX=45:sizeY=1,{thr(8)}[loc];"
            f"[tl][rl]blend=all_mode=multiply[both];[both][loc]blend=all_mode=multiply,dilation,"
            f"avgblur=sizeX=2:sizeY=2[mask];[fc][mask]alphamerge,format=rgba,scale={width}:-2:flags=lanczos")


def chunk_video_chain(clip: Clip, k0: int, k1: int, slow: bool, tl: Timeline, src_fps: float) -> str:
    """Picture for one run of a clip's keys (input already seeked to its first key)."""
    w, h, fps = tl.width, tl.height, tl.fps
    a, b = clip.keys[k0], clip.keys[k1]
    src_len, out_a = b.src - a.src, a.out
    tv = f"(t+{out_a:.6f})"                       # clip-local output time inside this chunk
    parts = [f"[0:v]trim=duration={src_len + 1 / src_fps:.4f},setpts=PTS-STARTPTS"]
    if clip.motion_blur > 1 and not slow:
        n = clip.motion_blur
        weights = " ".join(str(min(i + 1, n - i)) for i in range(n))     # centre-weighted shutter
        parts.append(f"tmix=frames={n}:weights='{weights}'")
    parts.append(f"setpts='(({clip.setpts_expr(f'(T+{a.src:.6f})')})-{out_a:.6f})/TB'")
    if clip.interpolate and slow:
        parts.append(INTERPOLATE.format(fps=fps))
    else:
        parts.append(f"fps={fps}")
    if clip.feed_inset:
        parts.append("split[cam][feedsrc];[cam]null")
    if clip.framing == "full":
        # The whole game screen, full width, centred; a soft, darkened blurred copy fills the rest.
        parts.append(f"split[fg][bg];[bg]scale={w // 8}:{h // 8}:force_original_aspect_ratio=increase,"
                     f"crop={w // 8}:{h // 8},boxblur=4:2,scale={w}:{h},eq=brightness=-0.12[bgb];"
                     f"[fg]scale={w}:-2:flags=lanczos[fgs];"
                     f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    elif clip.framing == "fit":
        # The whole frame, centred, over a soft blurred fill (for sources too small to crop).
        # A centre square fills the width (big enough to read on a phone, keeps the crosshair
        # and the top banner); a dark blurred copy fills the rest.
        side = min(w, h)
        parts.append(f"split[fg][bg];[bg]scale={w // 8}:{h // 8}:force_original_aspect_ratio=increase,"
                     f"crop={w // 8}:{h // 8},boxblur=4:2,scale={w}:{h},eq=brightness=-0.12[bgb];"
                     f"[fg]crop='min(iw\\,ih)':'min(iw\\,ih)',scale={side}:{side}:flags=lanczos[fgs];"
                     f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1")
    else:
        # Fill the output frame: centre crop to its aspect (9:16 from 16:9 keeps the crosshair,
        # the top banner and the ability bar), then scale.
        parts.append(f"crop='min(iw\\,ih*{w}/{h})':'min(ih\\,iw*{h}/{w})',scale={w}:{h}:flags=lanczos,setsar=1")
    moving = not (clip.zoom.is_const(1.0) and clip.rot.is_const(0.0) and clip.pan_x.is_const(0.0)
                  and clip.pan_y.is_const(0.0) and not clip.shakes)
    if moving:
        if not clip.rot.is_const(0.0):
            parts.append(f"rotate=a='({clip.rot.expr(tv)})*PI/180':ow={w}:oh={h}:c=black:bilinear=1")
        z = clip.zoom.expr(tv)
        parts.append(f"scale=w='trunc({w}*({z})/2)*2+2':h='trunc({h}*({z})/2)*2+2':eval=frame:flags=bicubic")
        x = f"clip((iw-{w})/2+({clip.pan_x.expr(tv)})*{w}+{_shake_expr(clip, 'x', w, tv)}\\,0\\,iw-{w})"
        y = f"clip((ih-{h})/2+({clip.pan_y.expr(tv)})*{w}+{_shake_expr(clip, 'y', w, tv)}\\,0\\,ih-{h})"
        parts.append(f"crop={w}:{h}:x='{x}':y='{y}'")
    start, end = clip.out_start + a.out, clip.out_start + b.out
    frames = round(end * fps) - round(start * fps)       # boundaries on whole frames
    if clip.feed_inset:
        # The kill feed (who killed whom: the story of the round) as a crisp inset, top centre,
        # under the game's score bar. Not affected by the camera moves.
        fw = int(w * 0.86) // 2 * 2       # big enough to read the names on a phone
        parts.append(f"null[camv];{feed_rows_chain('feedsrc', fw)}[feed];[camv][feed]overlay=(W-w)/2:H*0.275")     # below the round banners (spike planted, won, ace)
    parts.append(f"setsar=1,format=yuv420p,tpad=stop_mode=clone:stop_duration=0.3,"
                 f"trim=end_frame={frames},setpts=N/({fps}*TB)[v0]")      # exactly on the frame grid
    return ",".join(parts)


def chunk_audio_chain(clip: Clip, k0: int, k1: int, has_audio: bool, fps: int) -> str:
    a, b = clip.keys[k0], clip.keys[k1]
    src_len = b.src - a.src
    frames = round((clip.out_start + b.out) * fps) - round((clip.out_start + a.out) * fps)
    samples = frames * 48000 // fps            # exactly the picture's length
    if not has_audio:
        return f"anullsrc=r=48000:cl=stereo,atrim=end_sample={samples}[a0]"
    ratio = src_len / (samples / 48000)          # > 1: faster than real time
    if ratio < 0.85:
        tempo = f",asetrate={48000 * ratio:.1f},aresample=48000"     # slow motion: pitch drops
    elif abs(ratio - 1) < 0.01:
        tempo = ""
    else:
        stages, r = [], ratio
        while r > 2.0:
            stages.append("atempo=2.0")
            r /= 2.0
        stages.append(f"atempo={r:.5f}")
        tempo = "," + ",".join(stages)
    fade = min(0.008, samples / 48000 / 4)
    return (f"[0:a]atrim=duration={src_len:.5f},asetpts=PTS-STARTPTS,aresample=48000,"
            f"aformat=channel_layouts=stereo{tempo},volume={clip.game_gain:.3f},apad,"
            f"atrim=end_sample={samples},afade=t=in:d={fade:.4f},"
            f"afade=t=out:st={samples / 48000 - fade:.5f}:d={fade:.4f}[a0]")


def render_clips(tl: Timeline, base: Path, encoder_args: list[str], workers: int = 2) -> None:
    """Each clip is split where it goes in or out of slow motion; every piece is one FFmpeg run
    (decoding everything at once would hold it all in memory; in-between frames are only
    synthesized where the footage plays slow), two at a time, then joined without
    re-encoding. Boundaries sit on whole frames and samples, so picture and sound stay in
    step with the timeline to the frame. Unchanged pieces are reused from the last render."""
    from concurrent.futures import ThreadPoolExecutor
    infos: dict[str, dict[str, Any]] = {}
    jobs = []
    for c in sorted(tl.clips, key=lambda c: c.out_start):
        for k0, k1, slow in c.chunks():
            jobs.append((c, k0, k1, slow, base.with_name(f"part{len(jobs):03d}.mkv")))

    def run(job):
        c, k0, k1, slow, part = job
        src = c.source or tl.source
        info = infos.setdefault(src, _probe(Path(src)))
        graph = (chunk_video_chain(c, k0, k1, slow, tl, info["fps"]) + ";\n"
                 + chunk_audio_chain(c, k0, k1, info["has_audio"], tl.fps))
        script = part.with_suffix(".graph.txt")
        key = f"# {src}|{c.src_in}|{tl.fps}|{encoder_args}\n{graph}"
        if part.exists() and script.exists() and script.read_text() == key:
            return part
        script.write_text(graph)
        src_a, src_b = c.src_in + c.keys[k0].src, c.src_in + c.keys[k1].src
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{src_a:.4f}",
              "-t", f"{src_b - src_a + 0.5:.4f}", "-i", src, "-filter_complex_script", str(script),
              "-map", "[v0]", "-map", "[a0]", "-fps_mode", "passthrough"] + encoder_args
             + ["-threads", "2", "-c:a", "pcm_s16le", str(part)], f"Rendering {c.label}")
        script.write_text(key)
        return part

    with ThreadPoolExecutor(max_workers=workers) as pool:
        parts = list(pool.map(run, jobs))
    listing = base.with_name("clips.txt")
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
          "-c", "copy", str(base)], "Joining the clips")


# ---------------------------------------------------------------- motion, for text tracking

def measure_motion(video: Path, start: float, dur: float, fps: int, width: int) -> list[tuple[float, float]]:
    """Cumulative screen motion (pixels at full width) per frame over a window, by phase
    correlation of small greyscale frames: where a point of the scene has moved to."""
    import numpy as np
    w, h = 192, 108
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.4f}", "-t", f"{dur:.4f}", "-i", str(video),
                          "-vf", f"fps={fps},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    n = len(raw) // (w * h)
    frames = np.frombuffer(raw[: n * w * h], dtype=np.uint8).reshape(n, h, w).astype(np.float32)
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    acc, out = np.zeros(2), [(0.0, 0.0)]
    scale = width / w
    for i in range(1, n):
        a = np.fft.fft2((frames[i - 1] - frames[i - 1].mean()) * win)
        b = np.fft.fft2((frames[i] - frames[i].mean()) * win)
        r = a.conj() * b
        r /= np.abs(r) + 1e-6
        c = np.fft.ifft2(r).real
        y, x = np.unravel_index(np.argmax(c), c.shape)
        if y > h // 2:
            y -= h
        if x > w // 2:
            x -= w
        # A cut or whip (no clear peak) shouldn't throw the text across the screen.
        if c.max() > 0.08 and abs(x) < w / 6 and abs(y) < h / 6:
            acc += (x, y)
        out.append((float(acc[0] * scale), float(acc[1] * scale)))
    # Smooth it (the virtual camera's own roll and zoom read as jittery shifts) and keep it
    # small: text should ride along with the scene, not wander across the frame.
    k = 9
    smooth = []
    for i in range(len(out)):
        win = out[max(0, i - k):i + k + 1]
        smooth.append((sum(p[0] for p in win) / len(win), sum(p[1] for p in win) / len(win)))
    lim_x, lim_y = 0.04 * width, 0.03 * width
    return [(max(-lim_x, min(lim_x, x)), max(-lim_y, min(lim_y, y))) for x, y in smooth]


# ---------------------------------------------------------------- assets

def edge_glow(path: Path, width: int, height: int, color: tuple[int, int, int] = (205, 40, 255)) -> Path:
    """A ragged glow creeping in from the frame edges (the reference's purple ink on kills)."""
    import numpy as np
    from PIL import Image
    if path.exists():
        return path
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    d = np.minimum.reduce([xx / width, (width - 1 - xx) / width, yy / width, (height - 1 - yy) / width])
    noise = np.zeros((height, width), np.float32)
    for octave, amp in ((6, 1.0), (14, 0.5), (32, 0.25), (70, 0.12)):
        small = rng.random((max(2, octave * height // width), octave)).astype(np.float32)
        img = Image.fromarray((small * 255).astype(np.uint8)).resize((width, height), Image.BICUBIC)
        noise += amp * (np.asarray(img, np.float32) / 255)
    noise /= 1.87
    reach = 0.035 + 0.11 * noise ** 2
    alpha = np.clip(1 - d / reach, 0, 1) ** 1.6
    alpha *= 0.55 + 0.45 * noise
    rgba = np.zeros((height, width, 4), np.uint8)
    hot = np.clip(alpha * 1.4, 0, 1)
    for i, c in enumerate(color):
        rgba[..., i] = np.clip(c + (255 - c) * (hot ** 3) * 0.6, 0, 255).astype(np.uint8)
    rgba[..., 3] = (np.clip(alpha, 0, 1) * 255).astype(np.uint8)
    Image.fromarray(rgba, "RGBA").save(path)
    return path


# ---------------------------------------------------------------- pass 2: master

def master_commands(tl: Timeline, path: Path) -> None:
    """Per-frame values of the keyframed master effects, as an FFmpeg sendcmd script."""
    m = tl.master
    ca, glow, radial, edge = (m.get(k, Curve.const(0.0)) for k in ("ca", "glow", "radial", "edge"))
    lines = []
    scale = tl.width / 1920
    for i in range(int(math.ceil(tl.duration * tl.fps)) + 1):
        t = i / tl.fps
        shift = int(round(ca.at(t) * scale))
        lines.append(f"{t:.4f} rgbashift@ca rh {-shift}, rgbashift@ca bh {shift}, "
                     f"rgbashift@ca rv {shift // 3}, rgbashift@ca bv {-(shift // 3)}, "
                     f"blend@gl all_opacity {min(1.0, glow.at(t)):.3f}, "
                     f"blend@rb all_opacity {min(1.0, radial.at(t)):.3f}, "
                     f"colorchannelmixer@eg aa {min(1.0, edge.at(t)):.3f};")
    path.write_text("\n".join(lines))


def _reveal_filters(tl: Timeline) -> str:
    """Luma reveals: brights come out of (or sink into) black first."""
    out = []
    for r in tl.reveals:
        t0, d = r["t"], r["dur"]
        p = f"clip((T-{t0:.4f})/{d:.4f}\\,0\\,1)"
        if r["mode"] == "out":
            p = f"(1-{p})"
        th = f"(275-310*{p})"          # threshold sweeps from above white to below black
        k = f"clip((lum(X\\,Y)-{th})/45\\,0\\,1)"
        out.append(f"geq=lum='lum(X\\,Y)*{k}':cb='128+(cb(X\\,Y)-128)*{k}':cr='128+(cr(X\\,Y)-128)*{k}'"
                   f":enable='between(t\\,{t0 - 0.02:.4f}\\,{t0 + d + 0.02:.4f})'")
    return ("," + ",".join(out)) if out else ""


def _grade(look: dict[str, float]) -> str:
    warm = look.get("warmth", 0.0)
    return (f"eq=contrast={look.get('contrast', 1.0):.3f}:saturation={look.get('saturation', 1.0):.3f}"
            f":gamma={look.get('gamma', 1.0):.3f},"
            f"colorbalance=rs={-warm * 0.75:.3f}:bs={warm * 1.25:.3f}:rh={warm * 1.25:.3f}:bh={-warm:.3f},"
            f"unsharp=5:5:{look.get('sharpen', 0.0):.2f}")


def brand_mark(path: Path, branding: dict[str, Any], width: int, height: int) -> tuple[Path, int, int]:
    """The "made with reroll" lockup: a small die mark, a light "made with" line and a heavier
    wordmark, white with a soft shadow (no panel). Returns (png, x, y) for its corner."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    lock_h = max(24, int(branding.get("height", 0.032) * height))
    bold = ImageFont.truetype(str(ASSETS / "SpaceGrotesk-Bold.ttf"), int(lock_h * 0.62))
    small = ImageFont.truetype(str(ASSETS / "SpaceGrotesk-Bold.ttf"), int(lock_h * 0.3))
    word, sub = branding.get("word", "reroll"), branding.get("sub", "made with")
    mark = int(lock_h * 0.78)
    gap = int(lock_h * 0.22)
    text_w = int(max(bold.getlength(word), small.getlength(sub))) + 2
    pad = int(lock_h * 0.3)
    w, h = pad * 2 + mark + gap + text_w, pad * 2 + lock_h
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    my = pad + (lock_h - mark) // 2
    d.rounded_rectangle([pad, my, pad + mark, my + mark], radius=mark // 4, fill=(233, 185, 73, 255))
    r = max(2, mark // 9)
    for cx, cy in ((0.32, 0.32), (0.68, 0.68)):          # a die showing two: reroll
        x0, y0 = pad + int(mark * cx), my + int(mark * cy)
        d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=(24, 24, 28, 255))
    tx = pad + mark + gap
    d.text((tx, pad - int(lock_h * 0.04)), sub, font=small, fill=(255, 255, 255, 200))
    d.text((tx, pad + int(lock_h * 0.28)), word, font=bold, fill=(255, 255, 255, 255))
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow.putalpha(img.getchannel("A").filter(ImageFilter.GaussianBlur(lock_h * 0.12)).point(lambda v: int(v * 0.55)))
    out = Image.alpha_composite(shadow, img)
    out.save(path)
    m = int(branding.get("margin", 0.035) * width)
    corner = branding.get("corner", "top-left")
    x = m if "left" in corner else width - w - m
    y = int(branding.get("top", 0.0) * height) + m if "top" in corner else height - h - m - int(branding.get("bottom", 0.0) * height)
    return path, x, y


def _count_inputs(args: list[str]) -> int:
    return sum(1 for a in args if a == "-i")


def render_master(tl: Timeline, base: Path, output: Path, work: Path, encoder_args: list[str]) -> None:
    from .typography import render_layer
    w, h, fps = tl.width, tl.height, tl.fps
    inputs = ["-i", str(base)]
    graph = []
    cmd = work / "master.cmd"
    master_commands(tl, cmd)
    flash = tl.master.get("flash", Curve.const(0.0))
    exposure = tl.master.get("exposure", Curve.const(0.0))
    mono = tl.master.get("mono", Curve.const(0.0))
    hue = "" if mono.is_const(0.0) else f",hue=s='max(0\\,1-({mono.expr()}))'"
    graph.append(f"[0:v]sendcmd=f='{cmd}',{_grade(tl.look)}{hue},format=rgba[g0]")
    # Typography, positioned with the footage's motion.
    cur = "g0"
    for j, layer in enumerate(tl.texts):
        offsets = measure_motion(base, layer.start, layer.dur, fps, w) if layer.track else None
        folder = work / f"text{j:02d}"
        if folder.exists():
            shutil.rmtree(folder)
        render_layer(layer, folder, fps, w, h, offsets)
        # Offset at the input (not with setpts), so FFmpeg reads the layer only when it's due
        # instead of buffering its frames from the start.
        inputs += ["-itsoffset", f"{layer.start:.4f}", "-framerate", str(fps), "-i", str(folder / "%05d.png")]
        k = _count_inputs(inputs) - 1
        graph.append(f"[{k}:v]format=rgba[t{j}]")
        graph.append(f"[{cur}][t{j}]overlay=eof_action=pass:format=auto[g{j + 1}]")
        cur = f"g{j + 1}"
    # Bloom: highlights blurred and screened back on (computed small, it's soft anyway).
    graph.append(f"[{cur}]format=gbrp,split[gb][gs]")
    graph.append(f"[gs]lutrgb=r='clip((val-150)*2.4\\,0\\,255)':g='clip((val-150)*2.4\\,0\\,255)'"
                 f":b='clip((val-150)*2.4\\,0\\,255)',scale={w // 4}:{h // 4},gblur=sigma=9,"
                 f"scale={w}:{h}:flags=bicubic[glow]")
    graph.append("[gb][glow]blend@gl=all_mode=screen:all_opacity=0[bl]")
    # Radial (zoom) blur: zoomed copies averaged, blended in by keyframe.
    hw, hh = w // 2, h // 2
    graph.append(f"[bl]split=2[rs][rz]")
    graph.append(f"[rz]scale={hw}:{hh},split=4[z0][z1][z2][z3]")
    for i, s in enumerate((1.04, 1.085, 1.135)):
        zw, zh = int(hw * s) // 2 * 2, int(hh * s) // 2 * 2
        graph.append(f"[z{i + 1}]scale={zw}:{zh},crop={hw}:{hh}[zz{i + 1}]")
    graph.append(f"[z0][zz1][zz2][zz3]mix=inputs=4:weights='1 1 1 1',scale={w}:{h}:flags=bicubic[rb]")
    # In FFmpeg's "normal" blend, opacity weights the first input; at 0 the second shows.
    graph.append("[rb][rs]blend@rb=all_mode=normal:all_opacity=0[rbo]")
    # Colour split, then exposure (flashes) and the edge glow.
    graph.append(f"[rbo]rgbashift@ca=rh=0:bh=0:edge=smear,format=yuv444p,"
                 f"eq=brightness='{flash.expr()}':contrast='1+{exposure.expr()}':eval=frame[ex]")
    edge = edge_glow(work / "edge.png", w, h)
    inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{tl.duration + 0.5:.3f}", "-i", str(edge)]
    k = _count_inputs(inputs) - 1
    graph.append(f"[{k}:v]format=rgba,colorchannelmixer@eg=aa=0[edge]")
    tail = "[vf]" if tl.branding else "[v]"
    graph.append(f"[ex][edge]overlay=format=auto:shortest=1{_reveal_filters(tl)},"
                 f"trim=duration={tl.duration:.4f},format=yuv420p{tail}")
    if tl.branding:
        png, bx, by = brand_mark(work / "brand.png", tl.branding, w, h)
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{tl.duration + 0.5:.3f}", "-i", str(png)]
        k = _count_inputs(inputs) - 1
        graph.append(f"[{k}:v]format=rgba,fade=t=in:st=0.15:d=0.35:alpha=1[brand]")
        graph.append(f"[vf][brand]overlay={bx}:{by}:format=auto:shortest=1,format=yuv420p[v]")
    # Sound: game audio from pass 1, sound effects on top.
    audio_in = _count_inputs(inputs)
    names = sorted({s.name for s in tl.sfx})
    for name in names:
        inputs += ["-i", str(ASSETS / f"{name}.wav")]
    graph.append("[0:a]aresample=48000[game]")
    mix = ["[game]"]
    for n_i, name in enumerate(names):
        events = [s for s in tl.sfx if s.name == name]
        idx = audio_in + n_i
        graph.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,asplit={len(events)}"
                     + "".join(f"[s{n_i}_{e}]" for e in range(len(events))))
        for e, s in enumerate(events):
            ms = max(0, int(round(s.t * 1000)))
            graph.append(f"[s{n_i}_{e}]volume={s.gain:.3f},adelay={ms}|{ms}[d{n_i}_{e}]")
            mix.append(f"[d{n_i}_{e}]")
    graph.append("".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
                 f"atrim=duration={tl.duration:.4f}[a]")
    script = work / "master.graph.txt"
    script.write_text(";\n".join(graph))
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"] + inputs
         + ["-filter_complex_script", str(script), "-map", "[v]", "-map", "[a]", "-r", str(fps)]
         + encoder_args + ["-c:a", "pcm_s16le", str(output)], "Rendering the master")


def export(master: Path, output: Path, work: Path) -> None:
    """Final delivery encode: H.264 High, AAC; impact peaks limited so the whole edit can be
    brought to the platform loudness target without clipping."""
    from .highlight import _set_loudness
    final = work / "final.mp4"
    _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(master), "-c:v", "libx264",
          "-preset", "slow", "-crf", "16", "-profile:v", "high", "-pix_fmt", "yuv420p",
          "-af", "alimiter=limit=0.2:attack=2:release=120:level=false", "-c:a", "aac",
          "-b:a", "192k", "-movflags", "+faststart", str(final)], "Encoding the export")
    _set_loudness("ffmpeg", final, Path(output))


def render(tl: Timeline, output: Path, work: Path, preview_music: Path | None = None) -> dict[str, Any]:
    """Renders the timeline to `output` (H.264 + AAC, loudness-matched). With preview_music,
    also writes a private copy with the music mixed in at its sync offset (never the export)."""
    from .highlight import _set_loudness
    problems = tl.check()
    if problems:
        raise RenderError("Timeline problems: " + "; ".join(problems))
    work.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    base = work / "base.mkv"
    render_clips(tl, base, ["-c:v", "libx264", "-preset", "fast", "-crf", "10", "-pix_fmt", "yuv420p"])
    t1 = time.monotonic()
    master = work / "master.mkv"
    render_master(tl, base, master, work, ["-c:v", "libx264", "-preset", "fast", "-crf", "8", "-pix_fmt", "yuv420p"])
    t2 = time.monotonic()
    output = Path(output)
    export(master, output, work)
    result = {"output": str(output), "seconds": round(tl.duration, 3),
              "timings": {"clips_s": round(t1 - t0, 1), "master_s": round(t2 - t1, 1),
                          "total_s": round(time.monotonic() - t0, 1)}}
    if preview_music:
        preview = output.with_name(output.stem + " PREVIEW" + output.suffix)
        offset = tl.music.get("start", 0.0)
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(output), "-ss", f"{offset:.3f}",
              "-i", str(preview_music), "-filter_complex",
              "[0:a]volume=0.55[g];[1:a]aresample=48000,volume=0.9[m];"
              "[g][m]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.89:level=false[a]",
              "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
              "-movflags", "+faststart", str(preview)], "Mixing the preview")
        result["preview"] = str(preview)
    return result
