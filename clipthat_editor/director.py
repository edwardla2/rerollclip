"""Creative decisions: turns a clip's kills and a song's beat map into a Timeline in the style
of a reference velocity edit. No rendering here (see compositor.py).

The "velocity montage" style, taken from the reference breakdown:
  * Calm intro on the walk-up (real speed, slow camera push and sway) with big chrome-red
    words dropping in on the beat; opens with a luma reveal out of black.
  * Anticipation on the last beat before the drop: colour split and bloom creep up, the
    camera accelerates in, the last word strobes out.
  * Each kill: accelerate into it, the shot lands exactly on its beat and snaps into slow
    motion with one coordinated hit (punch-in, shake, flash, colour split, bloom pulse), the
    camera keeps pushing and rolls a few degrees while it hangs, then a speed ramp whips out
    into the next shot through a zoom-through (radial blur, the next shot settling in).
  * The first and final kills get the purple edge glow and longer slow motion; the build to
    the final kill raises the colour split and bloom.
  * After the final kill: a calm hold with a white "ACE" slam (contrast), then a replay
    flurry on half beats with quarter-beat glitch pulses, then the aftermath sinks back into
    black through a luma fade.
Effects are attached to kills, cuts and the drop, not to every beat.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .timeline import Clip, Curve, Sfx, Shake, TextLayer, TimeKey, Timeline


def exp_ramp(s0: float, s1: float, length: float) -> float:
    """Source seconds covered by a speed ramp from s0 to s1 (exponential in output time)."""
    if abs(s1 - s0) < 1e-6:
        return s0 * length
    return length * (s1 - s0) / math.log(s1 / s0)


def fit_ramp_end(s0: float, length: float, budget: float, top: float = 5.5) -> float:
    """End speed of a ramp from s0 over `length` output seconds that covers `budget` source."""
    if exp_ramp(s0, top, length) <= budget:
        return top
    lo, hi = s0 * 0.5, top
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if exp_ramp(s0, mid, length) < budget else (lo, mid)
    return max(0.2, (lo + hi) / 2)


class KeyBuilder:
    """Builds a clip's time keys stage by stage (speed ramps split into short pieces so the
    curve stays smooth and monotone)."""

    def __init__(self, speed: float):
        self.keys = [TimeKey(0.0, 0.0, speed, speed)]

    @property
    def src(self) -> float:
        return self.keys[-1].src

    @property
    def out(self) -> float:
        return self.keys[-1].out

    def ramp(self, s0: float, s1: float, length: float, pieces: int = 4) -> "KeyBuilder":
        last = self.keys[-1]
        last.speed_out = s0
        src0, out0 = last.src, last.out
        for j in range(1, pieces + 1):
            tau = length * j / pieces
            s = s0 * (s1 / s0) ** (tau / length) if abs(s1 - s0) > 1e-6 else s0
            self.keys.append(TimeKey(round(src0 + exp_ramp(s0, s, tau), 6), round(out0 + tau, 6), s, s))
        return self

    def snap(self, speed: float) -> "KeyBuilder":
        self.keys[-1].speed_out = speed
        return self


def _beat_time(music: dict[str, Any]):
    period = 60.0 / music["bpm"]
    b0 = music["beats"][0]
    return period, (lambda n: b0 + n * period), int(round((music["drop"] - b0) / period))


def kill_word(count: int | None) -> str | None:
    if not count or count < 2:
        return None
    return "ACE" if count >= 5 else f"{count}K"


def velocity_montage(source: str, duration: float, kills: list[float], music: dict[str, Any], *,
                     count: int | None = None, words: list[str] | None = None,
                     width: int = 1920, height: int = 1080, fps: int = 60) -> Timeline:
    P, beat, nd = _beat_time(music)
    kills = sorted(kills)
    n = len(kills)
    if n == 0:
        raise ValueError("no kills to edit around")
    # Where each kill lands (beat numbers): the first on the drop; a bar for the first kill;
    # two beats for the middle ones; the build to the final kill gets a bar; the final kill
    # lands on a downbeat.
    slots = [nd]
    for i in range(1, n):
        step = 4 if i == 1 else 2
        if i == n - 1 and n >= 3:
            step = 4
        nxt = slots[-1] + step
        if i == n - 1:
            nxt = int(math.ceil((nxt - nd) / 4)) * 4 + nd      # final kill on a downbeat
        slots.append(nxt)
    targets = [beat(s) for s in slots]
    A = 0.5 * P                       # approach (output seconds) before each shot
    S_SLOW, S_APPROACH = 0.28, 2.6
    approach_src = exp_ramp(1.4, S_APPROACH, A)
    first_approach_src = exp_ramp(1.0, S_APPROACH, A)
    # The song starts so the intro (walk-up before kill 1) fits the footage.
    intro_out = targets[0] - A
    available = kills[0] - first_approach_src
    start = max(0.0, intro_out - available)       # song time of output 0
    if start > 0:
        intro_out = targets[0] - A - start
    T = [t - start for t in targets]               # master times of the shots
    clips: list[Clip] = []
    master = {k: Curve() for k in ("ca", "glow", "flash", "radial", "edge", "exposure")}
    for c in master.values():
        c.add(0.0, 0.0)
    texts: list[TextLayer] = []
    sfx: list[Sfx] = []
    cuts: list[float] = []

    # ---- intro: the walk-up, calm, slow push and sway
    intro_src_end = kills[0] - first_approach_src
    if intro_out > 0.3:
        kb = KeyBuilder(1.0)
        src_len = min(intro_src_end, intro_out)
        kb.keys.append(TimeKey(src_len, intro_out, src_len / intro_out, src_len / intro_out))
        intro = Clip("intro", intro_src_end - src_len, intro_src_end, 0.0, kb.keys,
                     zoom=Curve().add(0, 1.035).add(intro_out - P, 1.08, "smooth").add(intro_out, 1.13, "in"),
                     rot=Curve().add(0, 0.0).add(intro_out * 0.45, 0.9, "smooth").add(intro_out - P, -0.6, "smooth")
                     .add(intro_out, 0.0, "smooth"),
                     interpolate=True, game_gain=1.0)
        clips.append(intro)
        # Anticipation on the last beat: colour split and bloom creep up, radial blur swells.
        a0 = intro_out - P
        master["ca"].add(a0, 0.0).add(intro_out, 9.0, "in")
        master["glow"].add(0.6, 0.12).add(a0, 0.15).add(intro_out, 0.45, "in")
        master["radial"].add(intro_out - 0.1, 0.0).add(intro_out, 0.75, "in")
        cuts.append(intro_out)
    # Title words on the beat through the intro; the last strobes out into the drop.
    words = [w.upper() for w in (words or []) if w.strip()]
    if words and intro_out > 2.5:
        # From the first beat after the reveal settles.
        first_beat = math.ceil((0.9 + start - beat(0)) / P)
        w_start = beat(first_beat) - start
        span = (intro_out - P * 0.5) - w_start
        per = span / len(words)
        for j, word in enumerate(words):
            t0 = w_start + j * per
            last = j == len(words) - 1
            texts.append(TextLayer(word, round(t0, 4), round(per + (0.45 * P if last else -0.02), 4), "chrome_red",
                                   x=0.46 if j % 2 == 0 else 0.53, y=0.42 if j % 2 == 0 else 0.46,
                                   size=0.2 if len(word) <= 6 else 0.16, tilt=-3.0 if j % 2 == 0 else 2.5,
                                   yaw=0.35 if j % 2 == 0 else -0.3, enter="letters",
                                   exit="flicker" if last else "fade", track=0.85))
    master["edge"].add(max(0.0, T[0] - 0.02), 0.0)

    # ---- kills
    for i, k in enumerate(kills):
        final = i == n - 1
        big = i == 0 or final
        entry = 1.0 if i == 0 else 1.4
        a_src = first_approach_src if i == 0 else approach_src
        out_start = T[i] - A
        kb = KeyBuilder(entry).ramp(entry, S_APPROACH, A, pieces=2).snap(S_SLOW)
        if final:
            hold = 4 * P                     # the calm hold after the final kill
            kb.ramp(0.22, 0.36, hold, pieces=3)
            clip_out = A + hold
            src_end = k + (kb.src - a_src)
        else:
            hold = (1.5 if i == 0 else 0.75) * P
            nxt_start_master = T[i + 1] - A
            ramp_len = nxt_start_master - (T[i] + hold)
            kb.ramp(S_SLOW, 0.42, hold, pieces=2)
            next_a = approach_src
            budget = (kills[i + 1] - next_a) - (k + (kb.src - a_src)) - 0.05
            s_end = fit_ramp_end(0.42, ramp_len, max(0.05, budget))
            kb.ramp(0.42, s_end, ramp_len, pieces=5)
            clip_out = A + hold + ramp_len
            src_end = k + (kb.src - a_src)
        src_in = k - a_src
        roll = (-3.5 if i % 2 == 0 else 3.0) * (1.6 if big else 1.0)
        zoom = Curve().add(0, 1.22 if clips else 1.13).add(0.16, 1.02, "out3").add(A - 0.02, 1.05, "in")
        # Punch in toward the crosshair (the target); harder on the final kill, which hangs longest.
        punch = 1.28 if final else (1.2 if i == n - 2 else 1.16)
        zoom.add(A + 0.08, punch, "out3").add(A + hold, 1.42 if final else punch + 0.06, "smooth")
        rot = Curve().add(0, 0.0).add(A, 0.0).add(A + hold, roll, "smooth")
        if not final:
            zoom.add(clip_out, 1.36, "in")
            rot.add(clip_out, 0.0, "in")
        clip = Clip(f"kill {i + 1}", round(src_in, 4), round(src_end, 4), round(out_start, 4), kb.keys,
                    zoom=zoom, rot=rot, shakes=[Shake(A, 0.014 if big else 0.01, 0.3)],
                    motion_blur=3 if not final else 0, interpolate=True, game_gain=0.9)
        clip.pan_y = Curve().add(A, 0.0).add(A + hold, -0.012, "smooth")
        clips.append(clip)
        t = T[i]
        # The hit: one coordinated package on the beat.
        master["flash"].add(t - 0.001, 0.0).add(t, 0.26 if big else 0.2).add(t + 0.13, 0.0, "out")
        base_ca = 3.0
        master["ca"].add(t - 0.001, master["ca"].at(t - 0.001)).add(t, 17.0 if big else 13.0).add(t + 0.35, base_ca, "out")
        master["glow"].add(t - 0.001, master["glow"].at(t - 0.001)).add(t, 0.75).add(t + 0.55, 0.3, "out")
        sfx.append(Sfx("hit", round(t, 4), 0.6 if big else 0.5))
        if big:
            master["edge"].add(t, 0.0).add(t + 0.08, 0.9, "out").add(t + hold, 0.75)
            master["edge"].add(t + hold + 0.25, 0.0, "smooth")
        if not final:
            cut = round(out_start + clip_out, 4)
            cuts.append(cut)
            # Whip out: the ramp's last stretch gathers colour split and radial blur.
            master["ca"].add(cut - 0.25, base_ca).add(cut, 11.0, "in")
            master["radial"].add(cut - 0.12, 0.0).add(cut, 0.85, "in")
            if i == n - 2:
                # Build to the final kill: bloom and colour split climb across the bar.
                master["glow"].add(t + hold, 0.3).add(cut, 0.6, "in")
    # Radial blur releases after every cut as the next shot settles.
    for c in cuts:
        master["radial"].add(c + 0.11, 0.0, "out")
    # Sound effects: a whoosh rushing into every cut.
    for c in cuts:
        sfx.append(Sfx("whoosh", round(max(0.0, c - 0.4), 4), 0.4))

    # ---- after the final kill: calm hold with the word, then a replay flurry, then the fade
    hold_end = T[-1] + 4 * P
    word = kill_word(count)
    if word:
        # Below the game's own round banner (top centre), over the spot where the last enemy fell.
        texts.append(TextLayer(word, round(T[-1] + P, 4), round(3 * P, 4), "impact_white", x=0.5, y=0.52,
                               size=0.27, tilt=-2.0, yaw=0.0, enter="slam", exit="through", track=0.6))
        master["flash"].add(T[-1] + P - 0.001, 0.0).add(T[-1] + P, 0.12).add(T[-1] + P + 0.1, 0.0, "out")
        sfx.append(Sfx("hit", round(T[-1] + P, 4), 0.35))
    master["glow"].add(T[-1] + 2 * P, 0.25).add(hold_end, 0.55, "in")
    master["ca"].add(hold_end - 0.3, 3.0).add(hold_end, 12.0, "in")
    master["radial"].add(hold_end - 0.1, 0.0).add(hold_end, 0.8, "in").add(hold_end + 0.1, 0.0, "out")
    sfx.append(Sfx("whoosh", round(hold_end - 0.4, 4), 0.4))
    t = hold_end
    half = P / 2
    order = list(range(n))
    for j, i in enumerate(order):
        k = kills[i]
        speed = 0.75
        kb = KeyBuilder(1.6).ramp(1.6, speed, half * 0.35, pieces=2)
        kb.ramp(speed, 0.5, half * 0.65, pieces=2)
        lead = kb.keys[2].src
        clip = Clip(f"replay {i + 1}", round(k - lead, 4), round(k - lead + kb.src, 4), round(t, 4), kb.keys,
                    zoom=Curve().add(0, 1.3).add(half * 0.35, 1.1, "out3").add(half, 1.16 + 0.03 * j, "smooth"),
                    rot=Curve().add(0, (2.5 if j % 2 else -2.5)).add(half, (1.0 if j % 2 else -1.0), "out"),
                    shakes=[Shake(half * 0.35, 0.009, 0.15, 14.0)], interpolate=True, game_gain=0.7)
        clips.append(clip)
        hit = t + half * 0.35
        master["flash"].add(hit - 0.001, 0.0).add(hit, 0.16).add(hit + 0.08, 0.0, "out")
        master["ca"].add(t, 12.0).add(t + 0.12, 5.0, "out")
        master["radial"].add(t, 0.6).add(t + 0.08, 0.0, "out")
        sfx.append(Sfx("hit", round(hit, 4), 0.32))
        t += half
    # Quarter-beat glitch pulses through the flurry (colour split and exposure flicker).
    q = hold_end
    while q < t - 1e-6:
        if all(abs(q - (hold_end + j * half)) > 1e-3 for j in range(n)):
            master["ca"].add(q - 0.001, 5.0).add(q, 10.0).add(q + 0.07, 5.0, "out")
            master["exposure"].add(q - 0.001, 0.0).add(q, 0.12).add(q + 0.07, 0.0, "out")
        q += P / 4
    master["glow"].add(t, 0.5)
    # Aftermath of the final kill (what comes after the hold), sinking into black.
    final_clip = next(c for c in clips if c.label == f"kill {n}")
    tail_start = final_clip.src_out
    tail_out = max(P * 2.0, 0.8)
    tail_src = min(duration - tail_start - 0.05, tail_out * 0.8)
    if tail_src > 0.3:
        kb = KeyBuilder(0.8)
        kb.keys.append(TimeKey(round(tail_src, 4), round(tail_out, 4), tail_src / tail_out, tail_src / tail_out))
        clips.append(Clip("aftermath", round(tail_start, 4), round(tail_start + tail_src, 4), round(t, 4), kb.keys,
                          zoom=Curve().add(0, 1.25).add(0.2, 1.06, "out3").add(tail_out, 1.12, "smooth"),
                          interpolate=True, game_gain=0.8))
        master["ca"].add(t, 9.0).add(t + 0.3, 2.0, "out")
        master["radial"].add(t, 0.5).add(t + 0.1, 0.0, "out")
        master["glow"].add(t + tail_out, 0.2, "smooth")
        sfx.append(Sfx("hit", round(t, 4), 0.3))
        end = t + tail_out
    else:
        end = t
    for c in master.values():
        c.add(end, c.at(end))
    reveals = [{"t": 0.0, "dur": 0.6, "mode": "in"}, {"t": round(end - P, 4), "dur": round(P, 4), "mode": "out"}]
    tl = Timeline(width, height, fps, source, clips, master, reveals, texts, sorted(sfx, key=lambda s: s.t),
                  music={"file": music.get("file"), "start": round(start, 4), "bpm": music["bpm"],
                         "drop": music["drop"], "kills_at": [round(x, 4) for x in T]},
                  notes=[f"kill {i + 1}: source {k:.3f}s lands on beat {slots[i]} (master {T[i]:.3f}s)"
                         for i, k in enumerate(kills)])
    return tl


# =====================================================================================
# Gameplay-first (the default; taste profile v0.2): the play is the star, effects are accents.
# =====================================================================================

def rank_events(kills: list[float], count: int | None) -> list[dict[str, Any]]:
    """Each kill with an importance: the final elimination is the top event (more so if it
    completes an ace); kills close behind another (a multi-kill burst) rank above singles."""
    out = []
    for i, k in enumerate(kills):
        burst = i > 0 and k - kills[i - 1] <= 2.0
        score = 0.5 + (0.2 if burst else 0.0) + 0.05 * i
        out.append({"t": k, "index": i, "burst": burst, "score": round(score, 3), "top": False})
    if out:
        out[-1]["top"] = True
        out[-1]["score"] = 1.0 if (count or 0) >= 5 else 0.9
    return out


def recipes_for(events: list[dict[str, Any]], taste: dict[str, Any]) -> list[str]:
    """A treatment per kill: the top event gets the profile's top recipe; the rest rotate
    through the others so no two neighbours look the same."""
    cycle = list(taste["accents"]["rotate_recipes"])
    out, j = [], 0
    for e in events:
        if e["top"]:
            out.append(taste["accents"]["top_event_recipe"])
            continue
        pick = cycle[j % len(cycle)]
        if out and pick == out[-1]:
            j += 1
            pick = cycle[j % len(cycle)]
        out.append(pick)
        j += 1
    return out


def hud_corner(source: str, width: int, height: int, corners: list[str], box_w: float = 0.3,
               box_h: float = 0.06, margin: float = 0.035) -> tuple[str, dict[str, float]]:
    """The corner of the framed output with the least HUD: HUD is detailed and doesn't move,
    so score each corner box by edge density weighted by stillness over the clip; the first
    preferred corner within reach of the best wins. Also returns how far below the top HUD
    band (or above the bottom one) the mark should sit."""
    import numpy as np
    import subprocess as sp
    w, h = 108, 192
    raw = sp.run(["ffmpeg", "-v", "error", "-i", source, "-vf",
                  f"fps=2,crop='min(iw\\,ih*{width}/{height})':'min(ih\\,iw*{height}/{width})',scale={w}:{h},format=gray",
                  "-f", "rawvideo", "-"], capture_output=True).stdout
    n = len(raw) // (w * h)
    if n < 2:
        return corners[0], {}
    frames = np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    edges = np.abs(np.diff(frames, axis=2)).mean(axis=0)
    edges = np.pad(edges, ((0, 0), (0, 1)))
    still = 1.0 / (1.0 + frames.std(axis=0) / 8.0)
    hud = edges * still
    # HUD bands: rows near the top/bottom whose HUD score stays high (score bar, ability bar).
    rows = hud.mean(axis=1)
    strong = rows > 2.0 * float(np.median(rows))
    top_rows = [y for y in range(h // 6) if strong[y]]
    bottom_rows = [y for y in range(h - h // 5, h) if strong[y]]
    top_band = (max(top_rows) + 1) if top_rows else 0
    bottom_band = (h - min(bottom_rows)) if bottom_rows else 0
    bw, bh, m = int(box_w * w), int(box_h * h), int(margin * w)
    scores = {}
    for c in corners:
        x0 = m if "left" in c else w - bw - m
        y0 = top_band + m if "top" in c else h - bottom_band - bh - m
        scores[c] = float(hud[y0:y0 + bh, x0:x0 + bw].mean())
    best = min(scores.values())
    pick = next(c for c in corners if scores[c] <= best * 1.25 + 0.05)
    return pick, {"top": round(top_band / h, 4), "bottom": round(bottom_band / h, 4), "scores": scores}


def first_detailed(source: str, a: float, b: float, step: float = 0.1) -> float:
    """The first moment in [a, b] where the picture has real detail. A smoke cloud, a flash or
    a wall in the face is flat and makes a weak opening, so the edit starts after it."""
    import numpy as np
    import subprocess as sp
    if b <= a:
        return a
    w, h = 96, 54
    raw = sp.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, a - 2):.3f}", "-t", f"{b - a + 4:.3f}", "-i", source,
                  "-vf", f"fps={1 / step:g},scale={w}:{h},format=gray", "-f", "rawvideo", "-"],
                 capture_output=True).stdout
    n = len(raw) // (w * h)
    if n < 3:
        return a
    f = np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    detail = np.abs(np.diff(f, axis=2)).mean(axis=(1, 2))
    t0 = max(0.0, a - 2)
    times = t0 + np.arange(n) * step
    after = detail[times >= b]           # the footage around the kill sets what "detailed" means
    ref = float(np.median(after if len(after) else detail))
    # The earliest start from which the picture *stays* detailed through to b (a one-frame
    # flicker inside smoke doesn't count).
    ok = detail >= 0.55 * ref
    best = b
    for i in range(n - 1, -1, -1):
        t = times[i]
        if t > b:
            continue
        if not ok[i]:
            break
        if t >= a - 1e-6:
            best = round(float(t), 3)
    return best


def gameplay_first(source: str, duration: float, kills: list[float], music: dict[str, Any] | None,
                   taste: dict[str, Any], *, count: int | None = None, words: list[str] | None = None) -> Timeline:
    from .taste import tier
    fmt, pace, prot = taste["format"], taste["pacing"], taste["protect"]
    width, height, fps = fmt["width"], fmt["height"], fmt["fps"]
    tz = tier(taste)
    kills = sorted(k for k in kills if 0.3 < k < duration - 0.05)
    if not kills:
        raise ValueError("no kills to edit around")
    events = rank_events(kills, count)
    recipes = recipes_for(events, taste)
    zmax = prot["zoom_max"]
    synced = bool(music) and pace.get("sync_to_music", True)
    P = 60.0 / music["bpm"] if synced else 0.5
    beats = list(music["beats"]) if synced else []

    def next_beat(song_t: float) -> float:
        for b in beats:
            if b >= song_t - 1e-6:
                return b
        return song_t

    LEAD, AFTER = pace["lead_in"], pace["aftermath"]
    OPEN = max(LEAD, 2.0)                     # the first play gets more setup
    clips: list[Clip] = []
    master = {k: Curve().add(0.0, 0.0) for k in ("ca", "glow", "flash", "radial", "edge", "exposure", "mono")}
    sfx: list[Sfx] = []
    notes: list[str] = []
    # Song time of kill 1: the drop if the setup fits before it, else the first beat after the setup.
    first_lead = min(OPEN, kills[0])
    # Open on something worth looking at: skip a flat stretch (smoke, a flash) at the start,
    # keeping at least the usual lead-in.
    if source and Path(source).exists():
        start_at = first_detailed(source, kills[0] - first_lead, kills[0] - 0.45)
        first_lead = kills[0] - start_at
    if synced:
        t1_song = music["drop"] if music["drop"] >= first_lead else next_beat(first_lead)
        start = t1_song - first_lead
    else:
        start = 0.0
    out_t = 0.0                                # running master time
    src_cursor = kills[0] - first_lead         # where the story is in the source
    lead = first_lead
    for i, (ev, recipe) in enumerate(zip(events, recipes)):
        k = ev["t"]
        top = ev["top"]
        nxt = kills[i + 1] if i + 1 < len(kills) else None
        # ---- build this kill's clip: lead-in -> impact (recipe) -> aftermath
        kb = KeyBuilder(1.0)
        zoom = Curve().add(0, 1.0)
        shakes: list[Shake] = []
        kill_local = None
        if recipe == "ramp":
            # Accelerate gently into the shot, snap to slow motion, ease back to real time.
            r_out = min(0.3, lead * 0.5)
            r_src = exp_ramp(1.0, 1.7, r_out)
            calm_src, calm_out = max(0.02, lead - r_src), max(0.02, lead - r_out)
            kb.keys.append(TimeKey(round(calm_src, 6), round(calm_out, 6), calm_src / calm_out, 1.0))
            kb.ramp(1.0, 1.7, r_out, pieces=2)
            kb.keys[-1].src = round(lead, 6)            # the shot, exactly at `lead`
            kb.keys[-1].out = round(lead, 6)
            kill_local = lead
            kb.snap(tz["slow"]).ramp(tz["slow"], tz["slow"] * 1.2, 0.35, pieces=2).ramp(tz["slow"] * 1.2, 1.0, 0.3, pieces=2)
            zoom.add(kill_local, 1.0).add(kill_local + 0.15, min(zmax, tz["punch"]), "out3").add(kill_local + 0.95, 1.02, "smooth")
        else:
            kb.keys.append(TimeKey(round(lead, 6), round(lead, 6), 1.0, 1.0))
            kill_local = lead
            if recipe == "hang":
                hang = max(0.6, tz["hang_beats"] * P * 1.6)
                kb.snap(tz["slow"]).ramp(tz["slow"], tz["slow"] * 0.9, hang, pieces=3).ramp(tz["slow"] * 0.9, 1.0, 0.4, pieces=2)
                zoom.add(kill_local, 1.0).add(kill_local + hang, min(zmax, tz["punch"] + 0.06), "smooth")
                zoom.add(kill_local + hang + 0.6, 1.02, "smooth")
            elif recipe == "snap":
                zoom.add(kill_local, 1.0).add(kill_local + 0.06, min(zmax, tz["punch"] + 0.03), "out3")
                zoom.add(kill_local + 0.5, 1.0, "smooth")
                shakes.append(Shake(kill_local, tz["shake"], 0.22, 13.0))
            else:  # punch
                zoom.add(kill_local, 1.0).add(kill_local + 0.12, min(zmax, tz["punch"]), "out3")
                zoom.add(kill_local + 0.7, 1.0, "smooth")
        # Aftermath at real speed (the top event plays out its payoff).
        after = AFTER if not top else max(AFTER, 1.4)
        if nxt is not None:
            after = min(after, max(0.2, (nxt - k) - 0.3 - (kb.src - lead)))
        after = min(after, duration - k - (kb.src - lead) - 0.02)
        kb.keys.append(TimeKey(round(kb.src + after, 6), round(kb.out + after, 6), 1.0, 1.0))
        clip_src_end = (k - lead) + kb.src
        # ---- where does the next kill land? (on a beat when synced) and how do we get there
        T_kill = out_t + kill_local
        if top:
            # End on the beat after the payoff: hold the last frame-accurate moment, then cut.
            end_out = out_t + kb.out
            if synced:
                end_out = next_beat(end_out + start) - start
                extra = end_out - (out_t + kb.out)
                avail = duration - clip_src_end - 0.02
                if extra > 1e-3:
                    hold = min(extra, avail)
                    if hold > 0.02:
                        kb.keys.append(TimeKey(round(kb.src + hold * 0.6, 6), round(kb.out + extra, 6), 0.6, 0.6))
                    else:
                        kb.keys[-1].out = round(kb.keys[-1].out + extra, 6)
                    clip_src_end = (k - lead) + kb.src
        clip = Clip(f"kill {i + 1} ({recipe})", round(k - lead, 4), round(clip_src_end, 4), round(out_t, 4), kb.keys,
                    zoom=zoom, shakes=shakes, interpolate=True, game_gain=1.0)
        clips.append(clip)
        # ---- accents (event-motivated, by recipe; nothing continuous)
        t = T_kill
        if recipe == "punch":
            master["flash"].add(t - 0.001, 0.0).add(t, tz["flash"]).add(t + 0.12, 0.0, "out")
        elif recipe == "snap":
            master["ca"].add(t - 0.001, 0.0).add(t, tz["split"]).add(t + 0.16, 0.0, "out")
        elif recipe == "ramp":
            master["glow"].add(t - 0.001, 0.0).add(t, tz["bloom"] * 0.6).add(t + 0.45, 0.0, "out")
        elif recipe == "hang":
            if taste["accents"]["mono"]["max_per_edit"] > 0 and tz.get("mono"):
                # Black and white while it hangs; colour returns with the payoff.
                back = t + max(0.6, tz["hang_beats"] * P * 1.6)
                master["mono"].add(t - 0.001, 0.0).add(t + 0.05, 1.0, "out").add(back - 0.05, 1.0).add(back + 0.2, 0.0, "smooth")
                master["flash"].add(back - 0.001, 0.0).add(back, tz["flash"] * 0.7).add(back + 0.18, 0.0, "out")
            master["glow"].add(t - 0.001, 0.0).add(t, tz["bloom"]).add(t + 1.2, 0.0, "smooth")
            if tz.get("edge_glow"):
                master["edge"].add(t - 0.001, 0.0).add(t + 0.1, 0.6, "out").add(t + 1.4, 0.0, "smooth")
            sfx.append(Sfx("hit", round(t, 4), 0.35))
        notes.append(f"kill {i + 1}: source {k:.3f}s -> {recipe}, at {t:.3f}s"
                     + (f" (song {t + start:.3f}s)" if synced else ""))
        out_t = clip.out_end
        if nxt is None:
            break
        # ---- downtime to the next kill's lead-in
        gap_src = (nxt - LEAD) - clip_src_end            # source between this aftermath and the next lead-in
        lead_next = LEAD
        if gap_src <= 0:
            lead_next = max(0.3, nxt - clip_src_end)
            gap_src = 0.0
        rampable = 0 < gap_src <= pace["ramp_downtime_under"]
        avg_max = pace["downtime_max_speed"] * 0.75     # leaves headroom for the curve's peak
        earliest = out_t + (gap_src / avg_max if rampable else 0.0) + lead_next
        if synced:
            target = next_beat(earliest + start) - start
        else:
            target = earliest
        room = target - out_t - lead_next                # output time available for downtime
        use_ramp = rampable and room > 0.12
        if use_ramp:
            # Speed through it smoothly: up from real time and back down, averaging gap/room.
            avg = gap_src / room
            if avg < 1.0:          # more time than footage: give the extra to the lead-in
                lead_next = min(nxt - clip_src_end, lead_next + (room - gap_src))
                room = target - out_t - lead_next
                gap_src = (nxt - lead_next) - clip_src_end
                avg = gap_src / room if room > 0.05 else 1.0
            if room > 0.05 and gap_src > 0.05:
                peak = min(pace["downtime_max_speed"] * 1.5, max(1.05, 2 * avg - 1.0))
                dkb = KeyBuilder(1.0)
                half = room / 2
                dkb.ramp(1.0, peak, half, pieces=3).ramp(peak, 1.0, half, pieces=3)
                # scale to cover exactly gap_src
                f = gap_src / dkb.src
                for key in dkb.keys:
                    key.src = round(key.src * f, 6)
                    key.speed_in *= f
                    key.speed_out *= f
                dclip = Clip(f"downtime {i + 1}", round(clip_src_end, 4), round(clip_src_end + gap_src, 4), round(out_t, 4),
                             dkb.keys, motion_blur=3 if peak > 2.2 else 0, interpolate=False, game_gain=0.7)
                clips.append(dclip)
                if tz.get("radial", 0) > 0 and peak > 2.5:
                    mid = out_t + half
                    master["radial"].add(mid - 0.12, 0.0).add(mid, tz["radial"], "in").add(mid + 0.12, 0.0, "out")
                sfx.append(Sfx("whoosh", round(out_t + half - 0.3, 4), 0.22))
                out_t = dclip.out_end
            lead = target - out_t
        else:
            # Hard cut over the downtime (on the beat); the lead-in absorbs the beat slack.
            lead = min(target - out_t, nxt - clip_src_end - 0.01) if nxt - clip_src_end > 0 else lead_next
            if target - out_t > lead + 1e-3:
                # not enough footage before the next kill: let this aftermath run longer
                extra = target - out_t - lead
                last = clips[-1]
                last.keys[-1].out = round(last.keys[-1].out + extra, 6)
                last.keys[-1].src = round(min(last.keys[-1].src + extra, duration - last.src_in - 0.02), 6)
                last.src_out = round(last.src_in + last.keys[-1].src, 4)
                out_t = last.out_end
            if gap_src > 0:
                notes.append(f"cut over {gap_src:.2f}s of downtime before kill {i + 2}")
        lead = max(0.2, lead)
    end = clips[-1].out_end
    for c in master.values():
        c.add(end, c.at(end))
    texts: list[TextLayer] = []
    branding = None
    if taste["branding"].get("enabled"):
        corner, bands = hud_corner(source, width, height, taste["branding"]["corners"])
        branding = {k: taste["branding"][k] for k in ("sub", "word", "height", "margin")}
        branding.update(corner=corner, top=bands.get("top", 0.0), bottom=bands.get("bottom", 0.0))
    t = taste.get("look", {})
    look = {"contrast": t.get("contrast", 1.06), "saturation": t.get("saturation", 1.12), "gamma": t.get("gamma", 0.99),
            "warmth": t.get("warmth", 0.015), "sharpen": t.get("sharpen", 0.45)}
    tl = Timeline(width, height, fps, source, clips, master, [], texts, sorted(sfx, key=lambda s: s.t),
                  music={"file": (music or {}).get("file"), "start": round(start, 4), "bpm": (music or {}).get("bpm"),
                         "drop": (music or {}).get("drop"),
                         "kills_at": [round(c.out_start + c.out_at(e["t"] - c.src_in), 4)
                                      for e, c in zip(events, [c for c in clips if c.label.startswith("kill")])]},
                  notes=notes, look=look, branding=branding)
    return tl
