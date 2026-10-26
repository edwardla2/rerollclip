"""Kinetic typography: big extruded 3D-style words, lit and animated, rendered by Reroll frame by
frame as transparent layers the compositor lays over the footage.

Styles (from the reference edit):
  chrome_red    glossy red face with inner tube lines, deep dark-red extrusion, red glow
  impact_white  bright white-to-grey face, grey extrusion, soft cool glow

Animations: letters (each letter drops in, sharpening, staggered), slam (the word punches in
from big with motion blur); exits flicker (strobing out, as the reference does on the beat
before a cut), fade, through (flies past the camera, for a zoom-through transition).
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from .timeline import TextLayer, ease

FONT = Path(__file__).parent / "assets" / "Anton-Regular.ttf"


@dataclass(frozen=True)
class Look:
    top: tuple[int, int, int]
    mid: tuple[int, int, int]
    bottom: tuple[int, int, int]
    side_front: tuple[int, int, int]
    side_back: tuple[int, int, int]
    rim: tuple[int, int, int]
    glow: tuple[int, int, int]
    glow_alpha: float
    lines: float            # strength of the inner tube lines


LOOKS = {
    "chrome_red": Look((255, 92, 84), (214, 10, 18), (105, 0, 4), (120, 0, 6), (38, 0, 2),
                       (255, 150, 140), (255, 20, 30), 0.55, 0.38),
    "impact_white": Look((255, 255, 255), (232, 232, 236), (160, 162, 170), (120, 122, 130), (40, 42, 48),
                         (255, 255, 255), (220, 235, 255), 0.35, 0.0),
}


def _gradient(size: tuple[int, int], look: Look) -> Image.Image:
    w, h = size
    col = Image.new("RGB", (1, h))
    px = col.load()
    for y in range(h):
        u = y / max(1, h - 1)
        a, b, k = (look.top, look.mid, u / 0.45) if u < 0.45 else (look.mid, look.bottom, (u - 0.45) / 0.55)
        px[0, y] = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
    return col.resize((w, h))


@lru_cache(maxsize=256)
def letter_sprite(ch: str, cap: int, style: str) -> tuple[Image.Image, int, int]:
    """One extruded, lit letter. Returns (RGBA sprite, x of the glyph's origin in it, advance)."""
    look = LOOKS[style]
    font = ImageFont.truetype(str(FONT), int(cap * 1.36))
    left, top, right, bottom = font.getbbox(ch)
    depth = max(2, int(cap * 0.11))
    pad = int(cap * 0.22) + depth
    w, h = right - left + 2 * pad, bottom - top + 2 * pad
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).text((pad - left, pad - top), ch, font=font, fill=255)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    # Glow behind everything.
    glow = mask.filter(ImageFilter.GaussianBlur(cap * 0.13))
    glow = glow.point(lambda v: int(v * look.glow_alpha))
    out.paste(Image.new("RGBA", (w, h), look.glow + (255,)), (0, 0), glow)
    # Extrusion: the glyph stacked back and down, darker the deeper it goes.
    dx, dy = 0.55, 0.85
    for i in range(depth, 0, -1):
        k = i / depth
        c = tuple(int(look.side_front[j] + (look.side_back[j] - look.side_front[j]) * k) for j in range(3))
        out.paste(Image.new("RGBA", (w, h), c + (255,)), (int(i * dx), int(i * dy)), mask)
    # Face: vertical gradient, inner tube lines, a lit rim.
    face = _gradient((w, h), look)
    if look.lines:
        lines = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(lines)
        step = max(3, cap // 7)
        for y in range(pad, h - pad, step):
            d.rectangle([0, y, w, y + max(1, step // 3)], fill=int(255 * look.lines))
        inner = mask.filter(ImageFilter.MinFilter(max(3, (cap // 18) | 1)))
        lines = ImageChops.multiply(lines, inner)
        face = Image.composite(Image.new("RGB", (w, h), (40, 0, 0)), face, lines)
    eroded = mask.filter(ImageFilter.MinFilter(max(3, (cap // 30) | 1)))
    rim = ImageChops.subtract(mask, eroded)
    face = Image.composite(Image.new("RGB", (w, h), look.rim), face, rim)
    # Specular sweep across the upper third.
    shine = Image.new("L", (w, h), 0)
    ImageDraw.Draw(shine).rectangle([0, pad, w, pad + int(cap * 0.28)], fill=70)
    shine = ImageChops.multiply(shine.filter(ImageFilter.GaussianBlur(cap * 0.05)), mask)
    face = Image.composite(Image.new("RGB", (w, h), (255, 255, 255)), face, shine)
    out.paste(face.convert("RGBA"), (0, 0), mask)
    advance = int(font.getlength(ch))
    return out, pad - left, advance


def _over(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    """Alpha-composite src onto dst at (x, y), clipped to dst."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(dst.width, x + src.width), min(dst.height, y + src.height)
    if x1 <= x0 or y1 <= y0:
        return
    dst.alpha_composite(src.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def _word_layout(text: str, cap: int, style: str) -> list[tuple[Image.Image, int]]:
    """Letters with their x offsets (kerned by the font's advances, tightened a touch)."""
    x, placed = 0, []
    for ch in text:
        if ch == " ":
            x += int(cap * 0.32)
            continue
        sprite, origin, adv = letter_sprite(ch, cap, style)
        placed.append((sprite, x - origin))
        x += int(adv * 0.97)
    return placed


def render_frame(layer: TextLayer, tau: float, width: int, height: int,
                 offset: tuple[float, float] = (0.0, 0.0)) -> Image.Image | None:
    """The layer at local time tau (seconds since it started), on a transparent canvas."""
    if tau < 0 or tau > layer.dur:
        return None
    cap = max(8, int(layer.size * height))
    letters = _word_layout(layer.text, cap, layer.style)
    if not letters:
        return None
    left = min(x for _, x in letters)
    right = max(x + s.width for s, x in letters)
    top = 0
    tall = max(s.height for s, _ in letters)
    word = Image.new("RGBA", (right - left, tall), (0, 0, 0, 0))
    n = len(letters)
    stagger = min(0.07, 0.45 / max(1, n))
    for i, (sprite, x) in enumerate(letters):
        if layer.enter == "letters":
            p = ease("out3", (tau - i * stagger) / 0.14)
            if p <= 0:
                continue
            s = 1.35 - 0.35 * p
            sp = sprite.resize((max(1, int(sprite.width * s)), max(1, int(sprite.height * s))), Image.BICUBIC)
            if p < 1:
                sp = sp.filter(ImageFilter.GaussianBlur((1 - p) * cap * 0.08))
                a = sp.getchannel("A").point(lambda v, p=p: int(v * p))
                sp.putalpha(a)
            ox = x - left - (sp.width - sprite.width) // 2
            oy = top - (sp.height - sprite.height) // 2 - int((1 - p) * cap * 0.15)
            _over(word, sp, ox, oy)
        else:
            _over(word, sprite, x - left, top)
    # Whole-word motion: entrance, slow push over its life, exit.
    scale, alpha, blur = 1.0 + 0.05 * (tau / max(layer.dur, 1e-6)), 1.0, 0.0
    if layer.enter == "slam":
        p = ease("out3", tau / 0.13)
        scale *= 1.8 - 0.8 * p
        alpha *= min(1.0, tau / 0.05)
        blur = (1 - p) * cap * 0.12
    remaining = layer.dur - tau
    if layer.exit == "flicker" and remaining < 0.32:
        pattern = (1.0, 0.25, 1.0, 0.0, 0.75, 0.0, 0.45, 0.0, 0.2, 0.0)
        k = int((0.32 - remaining) / 0.032)
        alpha *= pattern[min(k, len(pattern) - 1)]
        scale *= 1 + 0.03 * (0.32 - remaining) / 0.32
    elif layer.exit == "fade" and remaining < 0.2:
        alpha *= remaining / 0.2
        blur += (1 - remaining / 0.2) * cap * 0.05
    elif layer.exit == "through" and remaining < 0.18:
        q = ease("in", 1 - remaining / 0.18)
        scale *= 1 + 1.4 * q
        alpha *= 1 - q
        blur += q * cap * 0.15
    if alpha <= 0.01:
        return None
    w, h = word.size
    if layer.yaw:
        # Perspective turn: the far side shrinks.
        k = min(0.45, abs(layer.yaw) * 0.3)
        near, far = (0, h), (int(h * k / 2), int(h * (1 - k / 2)))
        quad = ((0, far[0]), (0, far[1]), (w, near[1]), (w, near[0])) if layer.yaw > 0 else \
            ((0, near[0]), (0, near[1]), (w, far[1]), (w, far[0]))
        word = word.transform((w, h), Image.QUAD, sum(quad, ()), Image.BICUBIC)
    sw, sh = max(1, int(w * scale)), max(1, int(h * scale))
    word = word.resize((sw, sh), Image.BICUBIC)
    if layer.tilt:
        word = word.rotate(layer.tilt, resample=Image.BICUBIC, expand=True)
    if blur > 0.5:
        word = word.filter(ImageFilter.GaussianBlur(blur))
    if alpha < 1:
        word.putalpha(word.getchannel("A").point(lambda v: int(v * alpha)))
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    cx = layer.x * width + offset[0] * layer.track
    cy = layer.y * height + offset[1] * layer.track
    _over(canvas, word, int(cx - word.width / 2), int(cy - word.height / 2))
    return canvas


def render_layer(layer: TextLayer, folder: Path, fps: int, width: int, height: int,
                 offsets: list[tuple[float, float]] | None = None) -> int:
    """Writes the layer's frames as folder/00000.png ...; returns how many."""
    folder.mkdir(parents=True, exist_ok=True)
    frames = int(math.ceil(layer.dur * fps))
    blank = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for i in range(frames):
        off = offsets[i] if offsets and i < len(offsets) else (0.0, 0.0)
        img = render_frame(layer, i / fps, width, height, off) or blank
        img.save(folder / f"{i:05d}.png", compress_level=1)
    return frames
