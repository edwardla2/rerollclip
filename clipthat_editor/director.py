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
from typing import Any

from .timeline import Clip, Curve, Sfx, Shake, TextLayer, TimeKey, Timeline


def exp_ramp(s0: float, s1: float, length: float) -> float:
    """Source seconds covered by a speed ramp from s0 to s1 (exponential in output time)."""
    if abs(s1 - s0) < 1e-6:
        return s0 * length
    return length * (s1 - s0) / math.log(s1 / s0)


def fit_ramp_end(s0: float, length: float, budget: float, top: float = 8.0) -> float:
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
        zoom.add(A + 0.08, 1.16, "out3").add(A + hold, 1.22 if not final else 1.3, "smooth")
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
        texts.append(TextLayer(word, round(T[-1] + P, 4), round(3 * P, 4), "impact_white", x=0.5, y=0.33,
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
