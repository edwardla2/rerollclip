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
            # Don't cut into flat footage (smoke): start the lead-in where the picture has detail,
            # and let this aftermath run on so the next kill still lands on its beat.
            if source and Path(source).exists() and lead > 0.5:
                begin = first_detailed(source, nxt - lead, nxt - 0.45)
                skip = begin - (nxt - lead)
                last = clips[-1]
                room_src = duration - last.src_in - last.keys[-1].src - 0.02
                if skip > 0.05 and room_src > 0:
                    last.keys[-1].out = round(last.keys[-1].out + skip, 6)
                    last.keys[-1].src = round(last.keys[-1].src + min(skip, room_src), 6)
                    last.src_out = round(last.src_in + last.keys[-1].src, 4)
                    out_t = last.out_end
                    lead -= skip
                    notes.append(f"lead-in to kill {i + 2} starts {skip:.2f}s later (flat footage)")
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


# =====================================================================================
# Story compilation: several plays back to back, lightly edited, the story kept.
# =====================================================================================

def play_windows(kills: list[float], story: list[float], duration: float, cfg: dict[str, Any]) -> list[list[float]]:
    """The parts of one clip that tell the play: around each of your kills, and around the
    other kill-feed events between them (a teammate going down is what makes a clutch).
    Windows closer than `merge_gap` join; what's left between them is dead time."""
    if not kills:
        return []
    first, last = kills[0], kills[-1]
    wins = [[k - (cfg["first_lead"] if k == first else cfg["lead"]), k + cfg["after"]] for k in kills]
    wins[-1][1] = last + cfg["payoff"]
    for t in story:
        # Only events that lead into one of your kills: the teammate who goes down before you
        # trade, the last teammate falling before the 1v1.
        if any(0 <= k - t <= cfg["context_before"] for k in kills):
            wins.append([t - cfg["story_pad"], t + cfg["story_pad"] + 0.2])
    wins = sorted([max(0.0, a), min(duration - 0.02, b)] for a, b in wins)
    merged: list[list[float]] = []
    for a, b in wins:
        if merged and a - merged[-1][1] <= cfg["merge_gap"]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def _kill_on_beat(wins, wi, play, clips, out_t, start, P, next_beat, cfg, notes) -> None:
    """Move window wi's start so its first kill lands on a beat: the smallest of (a) starting
    its lead-in later, (b) starting it earlier (if there's footage), (c) letting the previous
    real-speed window run on. Changes wins[wi][0] or the previous clip in place."""
    a, b = wins[wi]
    k = next((k for k in play["kills"] if a <= k <= b), None)
    if k is None:
        return
    kill_out = out_t + (k - a)
    back = kill_out - (next_beat(kill_out + start) - start - P)     # to the beat before
    fwd = next_beat(kill_out + start) - start - kill_out             # to the beat after
    if fwd < 1e-3 or back < 1e-3:
        return
    floor = wins[wi - 1][1] if wi > 0 else 0.0                       # footage this window may reach back to
    prev = clips[-1] if clips else None
    prev_real = prev is not None and abs(prev.keys[-1].speed_in - 1) < 1e-3 and prev.source == play["source"] \
        and wi > 0 and abs(prev.src_out - wins[wi - 1][1]) < 0.05
    options = []
    if (k - a) - back >= cfg["min_lead"]:
        options.append((back, "later"))
    if a - fwd >= floor - 1e-6:
        options.append((fwd, "earlier"))
    if prev_real and prev.src_out + fwd <= a + 1e-6:
        options.append((fwd, "previous"))
    if not options:
        return
    amount, how = min(options)
    if how == "later":
        wins[wi][0] = round(a + back, 4)
    elif how == "earlier":
        wins[wi][0] = round(a - fwd, 4)
    else:
        key = prev.keys[-1]
        key.out = round(key.out + fwd, 6)
        key.src = round(key.src + fwd, 6)
        prev.src_out = round(prev.src_in + key.src, 4)
    notes.append(f"kill at source {k:.2f}s put on the beat ({how}, {amount * 1000:.0f} ms)")


def story_compilation(plays: list[dict[str, Any]], music: dict[str, Any] | None, taste: dict[str, Any]) -> Timeline:
    """plays: [{"source", "duration", "kills", "story", "count", "height"}]. The best play goes
    last; each keeps its windows in order at real speed; dead time between windows is sped
    through (short) or cut (long); cuts land on beats by letting the footage before them run
    on a moment; one accent on the best moment of the whole video."""
    from .taste import tier
    cfg = dict(taste["story"])
    if cfg.get("gaps") == "real":
        # Review v004: never speed footage up; the gaps between fights play in real time, so
        # each play is one continuous stretch from its build-up to its payoff.
        cfg["merge_gap"] = float("inf")
    fmt = taste["format"]
    width, height, fps = fmt["width"], fmt["height"], fmt["fps"]
    tz = tier(taste)
    plays = [p for p in plays if p["kills"]]
    if not plays:
        raise ValueError("no kills found in any clip")
    # Best last (more kills, then a cleaner finish); otherwise keep the given order.
    order = sorted(range(len(plays)), key=lambda i: ((plays[i].get("count") or len(plays[i]["kills"])),
                                                     plays[i].get("height", 0), i))
    plays = [plays[i] for i in order]
    synced = bool(music)
    P = 60.0 / music["bpm"] if synced else 0.5
    beats = list(music["beats"]) if synced else []

    def next_beat(song_t: float) -> float:
        for b in beats:
            if b >= song_t - 1e-6:
                return b
        return song_t

    # The edit should fit the sound (a TikTok sound loops if the video runs longer): leave out
    # the weakest plays until it does. The best play always stays.
    if synced and music.get("duration"):
        def length(ps):
            return sum(b - a for p_ in ps for a, b in play_windows(p_["kills"], p_.get("story", []), p_["duration"], cfg)) \
                + P * len(ps)
        while len(plays) > 1 and length(plays) > music["duration"]:
            plays = plays[1:]

    # Structure (taste: story.structure = "buildup_drop"): the song's build-up plays over the
    # setup before the first kill, nothing happening yet; the drop lands on the first kill.
    # The song starts wherever that puts it, as long as it lasts the whole edit.
    start = 0.0
    spans = [play_windows(p["kills"], p.get("story", []), p["duration"], cfg) for p in plays]
    if synced:
        first_kill = plays[0]["kills"][0] - spans[0][0][0]
        total = sum(b - a for w in spans for a, b in w) + P * len(spans) * 2   # beat slack
        # A song without a real drop just starts from the top.
        start = music["drop"] - first_kill if music.get("drop_strength", 1.0) >= 0.15 else 0.0
        if music.get("duration"):
            start = min(start, music["duration"] - total)
        start = max(0.0, start)
    clips: list[Clip] = []
    master = {k: Curve().add(0.0, 0.0) for k in ("ca", "glow", "flash", "radial", "edge", "exposure", "mono")}
    sfx: list[Sfx] = []
    notes: list[str] = []
    out_t = 0.0
    top_play = len(plays) - 1
    for pi, play in enumerate(plays):
        src, dur = play["source"], play["duration"]
        crop_scale = (height / play.get("height", 1080)) if width < height else 1.0
        if fmt.get("framing") == "full":
            framing = "full"         # the whole game screen, blurred fill above and below
        else:
            framing = "crop" if crop_scale <= cfg["max_crop_upscale"] else "fit"
        inset = framing == "crop" and cfg.get("feed_inset", True) and play.get("game") == "valorant"
        wins = play_windows(play["kills"], play.get("story", []), dur, cfg)
        # Don't open a window on flat footage (smoke, a wall): start where the picture has detail,
        # keeping at least `min_lead` before the kill that window is for.
        if Path(src).exists():
            for wj, w_ in enumerate(wins):
                k_next = next((k for k in play["kills"] if k >= w_[0]), None)
                if k_next is None:
                    continue
                keep = cfg["min_lead"]
                if pi == 0 and wj == 0:
                    keep = cfg.get("buildup_min", 2.0)      # the build-up needs time to build
                w_[0] = max(w_[0], min(first_detailed(src, w_[0], k_next - keep), k_next - keep))
        notes.append(f"play {pi + 1}: {Path(src).name}, {len(play['kills'])} kills, framing {framing}"
                     + (" + kill feed" if inset else ""))
        for wi in range(len(wins)):
            if synced and not (pi == 0 and wi == 0):
                _kill_on_beat(wins, wi, play, clips, out_t, start, P, next_beat, cfg, notes)
                out_t = clips[-1].out_end if clips else out_t
            a, b = wins[wi]
            last_of_play = wi == len(wins) - 1
            nxt = wins[wi + 1][0] if not last_of_play else None
            gap = (nxt - b) if nxt is not None else 0.0
            ramp = nxt is not None and gap <= cfg["ramp_gap_under"]
            if ramp:
                b2 = b
            else:
                b2 = b      # the next window's kill is put on its beat when that window starts
            b2 = max(a + 0.3, min(b2, dur - 0.02))
            kb = KeyBuilder(1.0)
            kb.keys.append(TimeKey(round(b2 - a, 6), round(b2 - a, 6), 1.0, 1.0))
            zoom = Curve().add(0, 1.0)
            clip = Clip(f"play {pi + 1} window {wi + 1}", round(a, 4), round(b2, 4), round(out_t, 4), kb.keys,
                        zoom=zoom, source=src, framing=framing, feed_inset=inset, interpolate=False)
            # The accent: the final kill of the best play, once.
            if pi == top_play and last_of_play and cfg.get("top_accent") == "mono_hang":
                k = play["kills"][-1]
                if a < k < b2 - 0.3:
                    hang_out = cfg["hang"]
                    s = tz["slow"] if tz["slow"] >= 0.35 else 0.35
                    hk = KeyBuilder(1.0)
                    hk.keys.append(TimeKey(round(k - a, 6), round(k - a, 6), 1.0, 1.0))
                    hk.snap(s).ramp(s, s * 1.1, hang_out, pieces=2).ramp(s * 1.1, 1.0, 0.3, pieces=2)
                    rest = (b2 - a) - hk.src
                    if rest > 0.05:
                        hk.keys.append(TimeKey(round(hk.src + rest, 6), round(hk.out + rest, 6), 1.0, 1.0))
                    clip.keys = hk.keys
                    clip.src_out = round(a + hk.src, 4)
                    clip.interpolate = True
                    t = out_t + (k - a)
                    clip.zoom = Curve().add(0, 1.0).add(k - a, 1.0).add(k - a + 0.12, min(taste["protect"]["zoom_max"], 1.07), "out3") \
                        .add(k - a + hang_out + 0.6, 1.0, "smooth")
                    if tz.get("mono"):
                        back = t + hang_out
                        master["mono"].add(t - 0.001, 0.0).add(t + 0.05, 1.0, "out").add(back - 0.05, 1.0).add(back + 0.25, 0.0, "smooth")
                    master["flash"].add(t - 0.001, 0.0).add(t, tz["flash"] * 0.6).add(t + 0.12, 0.0, "out")
                    sfx.append(Sfx("hit", round(t, 4), 0.3))
                    notes.append(f"accent: final kill of play {pi + 1} at {t:.3f}s")
            clips.append(clip)
            out_t = clip.out_end
            if ramp and gap > 0.05:
                # Speed through short dead time, smoothly, up from real time and back.
                avg = cfg["ramp_avg"]
                room = gap / avg
                if synced:
                    # End the skim so the next kill (after its lead-in) lands on a beat.
                    k_n = next((k for k in play["kills"] if k >= wins[wi + 1][0]), wins[wi + 1][0])
                    lead_n = k_n - wins[wi + 1][0]
                    target = next_beat(out_t + room + lead_n + start) - start - lead_n
                    if target - out_t < gap / 4.0:
                        target = next_beat(target + lead_n + 0.01 + start) - start - lead_n
                    room = target - out_t
                avg = gap / room
                peak = max(1.05, 2 * avg - 1.0)
                dk = KeyBuilder(1.0)
                dk.ramp(1.0, peak, room / 2, pieces=3).ramp(peak, 1.0, room / 2, pieces=3)
                f = gap / dk.src
                for key in dk.keys:
                    key.src = round(key.src * f, 6)
                    key.speed_in *= f
                    key.speed_out *= f
                dclip = Clip(f"play {pi + 1} skim {wi + 1}", round(b2, 4), round(b2 + gap, 4), round(out_t, 4), dk.keys,
                             source=src, framing=framing, feed_inset=inset, interpolate=False,
                             motion_blur=3 if peak > 2.2 else 0, game_gain=0.6)
                clips.append(dclip)
                out_t = dclip.out_end
                wins[wi + 1][0] = b2 + gap
            elif nxt is not None:
                notes.append(f"play {pi + 1}: cut {nxt - b2:.1f}s of dead time at {out_t:.3f}s")
    # End with the song: trim the last hold if it runs past the sound.
    if synced and music.get("duration"):
        excess = out_t - (music["duration"] - start)
        last = clips[-1]
        if excess > 0 and last.keys[-1].out - excess > last.keys[-2].out + 0.2:
            k = last.keys[-1]
            k.out = round(k.out - excess, 6)
            k.src = round(k.src - excess * (k.speed_in if k.speed_in else 1.0), 6)
            last.src_out = round(last.src_in + k.src, 4)
            out_t = last.out_end
            notes.append(f"trimmed {excess:.2f}s off the end to finish with the song")
    end = out_t
    for c in master.values():
        c.add(end, c.at(end))
    branding = None
    if taste["branding"].get("enabled"):
        best = plays[-1]
        corner, bands = hud_corner(best["source"], width, height, taste["branding"]["corners"])
        branding = {k: taste["branding"][k] for k in ("sub", "word", "height", "margin")}
        branding.update(corner=corner, top=bands.get("top", 0.0), bottom=bands.get("bottom", 0.0))
    t = taste.get("look", {})
    look = {"contrast": t.get("contrast", 1.05), "saturation": t.get("saturation", 1.08), "gamma": t.get("gamma", 1.0),
            "warmth": t.get("warmth", 0.01), "sharpen": t.get("sharpen", 0.4)}
    kills_at = []
    for c in clips:
        play = next(p for p in plays if p["source"] == c.source)
        for k in play["kills"]:
            if c.src_in <= k < c.src_out:
                kills_at.append(round(c.out_start + c.out_at(k - c.src_in), 4))
    return Timeline(width, height, fps, plays[0]["source"], clips, master, [], [], sorted(sfx, key=lambda s: s.t),
                    music={"file": (music or {}).get("file"), "start": round(start, 4), "bpm": (music or {}).get("bpm"),
                           "drop": (music or {}).get("drop"), "kills_at": sorted(kills_at)},
                    notes=notes, look=look, branding=branding)
