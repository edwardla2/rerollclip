"""Reroll's own beat: an original, synthesized phonk-style track composed around an edit.

Everything is generated here (no samples, no copyrighted audio), so the track can be baked into
the export. Structure follows Edward's edit rule: a muffled build-up over the setup, the drop
exactly on the first kill, accent hits on later kills, a fade at the end. The tempo grid is
known exactly (it's ours), so the edit can be planned against it before the audio exists.
"""
from pathlib import Path
import sys
from typing import Any

import numpy as np
from scipy.signal import butter, sosfilt
from scipy.io import wavfile

SR = 44100
BPM = 130.0
BEAT = 60 / BPM
S16 = BEAT / 4
rng = np.random.default_rng(3)


def env(n, attack, decay):
    t = np.arange(n) / SR
    a = np.minimum(1, t / max(attack, 1e-4))
    return a * np.exp(-t / decay)


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "bandpass", fs=SR, output="sos"), x)


def hp(x, f):
    return sosfilt(butter(2, f, "highpass", fs=SR, output="sos"), x)


def lp(x, f):
    return sosfilt(butter(2, f, "lowpass", fs=SR, output="sos"), x)


def cowbell(freq, dur=0.22):
    n = int(dur * SR)
    t = np.arange(n) / SR
    k = freq / 587.0
    sq = np.sign(np.sin(2 * np.pi * 587 * k * t)) + np.sign(np.sin(2 * np.pi * 845 * k * t))
    return bp(sq, 400 * k, 3000 * k) * env(n, 0.001, 0.07) * 0.5


def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 130 * np.exp(-t * 35)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.tanh(2.5 * np.sin(ph) * env(n, 0.001, 0.12)) * 0.9


def bass808(freq, dur):
    n = int(dur * SR)
    t = np.arange(n) / SR
    f = freq * (1 + 1.2 * np.exp(-t * 40))
    ph = 2 * np.pi * np.cumsum(f) / SR
    x = np.sin(ph) * env(n, 0.002, 0.9)
    return np.tanh(3.5 * x) * 0.7


def snare():
    n = int(0.25 * SR)
    noise = rng.uniform(-1, 1, n)
    body = np.sin(2 * np.pi * 190 * np.arange(n) / SR) * env(n, 0.001, 0.04)
    return (bp(noise, 1200, 8000) * env(n, 0.001, 0.07) + 0.5 * body) * 0.6


def hat(open_=False):
    n = int((0.12 if open_ else 0.04) * SR)
    return hp(rng.uniform(-1, 1, n), 7000) * env(n, 0.0005, 0.05 if open_ else 0.012) * 0.25


def place(buf, sample, t, gain=1.0):
    i = int(t * SR)
    j = min(len(buf), i + len(sample))
    if i < len(buf):
        buf[i:j] += gain * sample[: j - i]


def note(n):  # MIDI to Hz
    return 440 * 2 ** ((n - 69) / 12)


def grid(drop: float = 8.0, length: float = 600.0, bpm: float = BPM) -> dict[str, Any]:
    """The beat map of a Reroll beat whose drop is at the given time (seconds, song time): what the
    planner needs, known before any audio exists."""
    p = 60.0 / bpm
    first = drop - int(drop / p) * p
    beats = [round(first + i * p, 4) for i in range(int((length - first) / p))]
    return {"file": "Reroll beat", "title": "Reroll beat (original, generated)", "bpm": bpm,
            "beat_seconds": p, "beats": beats, "drop": drop, "drop_strength": 1.0,
            "duration": length, "hits": []}


def render(drop_at: float, total: float, kills: list[float], out: str) -> None:
    buf = np.zeros(int(total * SR) + SR)
    cow_lead = np.zeros_like(buf)
    # D minor phonk cowbell riff, 2 bars of 16ths (None = rest)
    riff = [74, None, 74, 77, 74, None, 72, None, 74, None, 74, 77, 79, None, 77, 72,
            74, None, 74, 77, 74, None, 72, None, 70, None, 70, 72, 69, None, 72, None]
    riff_b = [77, None, 77, 79, 77, None, 74, None, 77, None, 77, 79, 81, None, 79, 74,
              74, None, 74, 77, 74, None, 72, None, 70, None, 69, 70, 72, None, 74, None]
    bass_line = [38, 38, 38, 36, 34, 34, 33, 36]          # 808 roots, one per half-bar
    bass_b = [41, 41, 41, 40, 38, 38, 36, 33]
    # Grid: the drop is a downbeat; everything is placed relative to it.
    first_step = -int(drop_at / S16) - 1
    last_step = int((total - drop_at) / S16) + 1
    for step in range(first_step, last_step):
        t = drop_at + step * S16
        if t < 0 or t >= total:
            continue
        in_drop = step >= 0
        phrase_b = in_drop and (step // 64) % 2 == 1        # every other 4-bar phrase
        r = (riff_b if phrase_b else riff)[step % 32]
        if r is not None:
            place(cow_lead, cowbell(note(r + 12)), t, 0.9 if in_drop else 0.6)
        if in_drop:
            if step % 8 == 0 or step % 16 == 10:
                place(buf, kick(), t, 1.0)
            if step % 8 == 4:
                place(buf, snare(), t, 1.0)
            place(buf, hat(step % 4 == 2), t, 0.8 if step % 2 == 0 else 0.5)
            if step % 8 == 0:
                line = bass_b if phrase_b else bass_line
                place(buf, bass808(note(line[(step // 8) % 8]), BEAT * 2), t, 1.0)
            if step > 0 and step % 64 == 63:              # fill into each new phrase
                for f in range(4):
                    place(buf, snare(), t - (3 - f) * S16 / 2, 0.4 + 0.1 * f)
        else:
            # Build-up: hats only in the last bar, snare roll speeding up into the drop
            beats_left = -step / 4
            if beats_left <= 4 and step % 2 == 0:
                place(buf, hat(), t, 0.4)
            if beats_left <= 2:
                if step % 1 == 0:
                    place(buf, snare(), t, 0.35 + 0.3 * (1 - beats_left / 2))
            elif beats_left <= 4 and step % 2 == 0:
                place(buf, snare(), t, 0.3)
    # Build-up cowbell is filtered (muffled), opening up at the drop
    di = int(drop_at * SR)
    muffled = lp(cow_lead[:di], 900)
    cow_lead[:di] = muffled
    buf += cow_lead
    # Riser: noise swept up over the last 2 bars before the drop, then cut
    rs = max(0, drop_at - 8 * BEAT)
    n = di - int(rs * SR)
    if n > 0:
        noise = rng.uniform(-1, 1, n)
        sweep = np.zeros(n)
        chunk = 2048
        for i in range(0, n, chunk):
            frac = i / n
            f = 300 + 7000 * frac ** 2
            seg = bp(noise[i:i + chunk], f * 0.7, min(f * 1.4, 18000))
            sweep[i:i + chunk] = seg * (0.05 + 0.3 * frac)
        buf[int(rs * SR):di] += sweep
    # The drop: a heavy hit on the first kill
    place(buf, kick(), drop_at, 1.3)
    place(buf, bass808(note(38), BEAT * 2), drop_at, 1.2)
    # Accent hits on later kills
    for k in kills[1:]:
        place(buf, kick(), k, 0.6)
    # Balance: the build-up sits ~8 dB under the drop (not 18), the drop isn't brick-walled.
    ramp = np.clip((np.arange(len(buf)) / SR - (drop_at - 0.05)) / 0.05, 0, 1)
    buf *= 2.6 * (1 - ramp) + 0.6 * ramp
    buf = np.tanh(buf * 0.9)
    buf = buf[: int(total * SR)]
    buf /= np.max(np.abs(buf)) + 1e-9
    fade = int(min(1.0, total / 8) * SR)                      # ease out at the very end
    buf[-fade:] *= np.linspace(1, 0, fade) ** 1.5
    stereo = np.stack([buf, buf], axis=1) * 0.89
    wavfile.write(out, SR, (stereo * 32767).astype(np.int16))


def make(drop_at: float, total: float, kills: list[float], out: Path) -> Path:
    render(drop_at, total, kills, str(out))
    return Path(out)


if __name__ == "__main__":
    render(float(sys.argv[1]), float(sys.argv[2]), [float(x) for x in sys.argv[4:]], sys.argv[3])
