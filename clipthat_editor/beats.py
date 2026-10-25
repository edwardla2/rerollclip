"""Rhythm of a sound: tempo, beat times and the drop.

Used for beat-synced edits: Reroll reads the sound the player picked, times the edit to
it, and exports *without* the music. The player adds the same sound inside TikTok (where
it's licensed), starting at 0:00, and the cuts land on its beats.

Method (no third-party packages):
- onset envelope: rise in short-time energy, every HOP seconds, from a low-passed copy
  (kicks and bass carry the beat in most edit music);
- tempo: autocorrelation of that envelope over 70-180 BPM, with a mild preference for
  common edit tempos so half/double-time ambiguity resolves sensibly;
- beat phase: the offset whose beat grid collects the most onset energy;
- drop: the beat where loudness over the next 2 s jumps most above the 2 s before it.
"""
from __future__ import annotations

from array import array
import math
from pathlib import Path
import shutil
import subprocess
from typing import Any

RATE = 12000          # 120 samples = exactly one 10 ms frame
HOP = 0.01                # seconds per envelope frame
MIN_BPM, MAX_BPM = 70.0, 180.0


class BeatError(Exception):
    pass


def _decode(path: Path, lowpass: int | None) -> array:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise BeatError("FFmpeg is required")
    af = f"lowpass=f={lowpass}," if lowpass else ""
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                           "-af", f"{af}aresample={RATE}", "-ar", str(RATE), "-f", "s16le", "-"],
                          capture_output=True)
    if proc.returncode or not proc.stdout:
        raise BeatError(f"Can't read audio from {Path(path).name}")
    samples = array("h")
    samples.frombytes(proc.stdout[: len(proc.stdout) // 2 * 2])
    return samples


def _energy(samples: array) -> list[float]:
    per = int(RATE * HOP)
    out = []
    for i in range(0, len(samples) - per + 1, per):
        chunk = samples[i:i + per]
        out.append(math.sqrt(sum(s * s for s in chunk) / per) / 32768.0)
    return out


def _onsets(energy: list[float]) -> list[float]:
    log = [math.log10(e + 1e-4) for e in energy]
    rise = [0.0] + [max(0.0, log[i] - log[i - 1]) for i in range(1, len(log))]
    peak = max(rise) or 1.0
    return [r / peak for r in rise]


def _tempo(env: list[float]) -> float:
    n = len(env)
    mean = sum(env) / max(n, 1)
    centred = [e - mean for e in env]
    best_lag, best_score = None, -math.inf
    for bpm10 in range(int(MIN_BPM * 10), int(MAX_BPM * 10) + 1, 5):
        bpm = bpm10 / 10
        lag = 60.0 / bpm / HOP
        lo, frac = int(lag), lag - int(lag)
        if lo + 1 >= n:
            continue
        acf = 0.0
        for i in range(n - lo - 1):
            shifted = centred[i + lo] * (1 - frac) + centred[i + lo + 1] * frac
            acf += centred[i] * shifted
        acf /= (n - lo)
        # Gentle prior around 125 BPM: picks 140 over 70 for typical edit music.
        weight = math.exp(-0.5 * (math.log2(bpm / 125.0) / 0.9) ** 2)
        if acf * weight > best_score:
            best_score, best_lag = acf * weight, bpm
    if best_lag is None:
        raise BeatError("The sound is too short to find a tempo")
    return best_lag


def _phase(env: list[float], bpm: float) -> tuple[float, float]:
    """Best grid offset for this tempo, and how much onset energy that grid collects."""
    period = 60.0 / bpm
    steps = 40
    best, best_offset = -1.0, 0.0
    for k in range(steps):
        offset = k * period / steps
        total, t = 0.0, offset
        while t / HOP < len(env):
            i = int(round(t / HOP))
            total += max(env[max(0, i - 2):i + 3] or [0.0])
            t += period
        if total > best:
            best, best_offset = total, offset
    beats = max(1, int(len(env) * HOP / period))
    return best_offset, best / beats


def _refine(env: list[float], bpm: float) -> tuple[float, float]:
    """Fine-tunes the tempo (+/- 1 BPM, 0.05 steps): a small tempo error drifts a whole bar late."""
    best = (-1.0, bpm, 0.0)
    for k in range(-20, 21):
        candidate = bpm + k * 0.05
        offset, score = _phase(env, candidate)
        if score > best[0]:
            best = (score, candidate, offset)
    return best[1], best[2]


def _peaks(env: list[float], share: float = 0.35) -> list[float]:
    """Onset peaks, judged against their own neighbourhood (a loud section mustn't hide its
    kicks), timed to a fraction of a frame by fitting a parabola through each peak."""
    radius = int(1.0 / HOP)
    out = []
    for i in range(1, len(env) - 1):
        if not (env[i] >= env[i - 1] and env[i] > env[i + 1]):
            continue
        local = max(env[max(0, i - radius):i + radius + 1])
        if env[i] < share * local or env[i] < 0.02:
            continue
        a, b, c = env[i - 1], env[i], env[i + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom else 0.0
        out.append((i + max(-0.5, min(0.5, shift))) * HOP)
    return out


def _fit_grid(env: list[float], period: float, offset: float) -> tuple[float, float]:
    """Least-squares fit of the beat grid to the onset peaks nearest each predicted beat."""
    peaks = _peaks(env)
    if len(peaks) < 4:
        return period, offset
    for _ in range(3):
        pairs = []
        k_max = int((len(env) * HOP - offset) / period)
        for k in range(k_max + 1):
            want = offset + k * period
            near = min(peaks, key=lambda p: abs(p - want))
            if abs(near - want) <= period / 4:
                pairs.append((k, near))
        if len(pairs) < 4:
            break
        n = len(pairs)
        mk = sum(k for k, _ in pairs) / n
        mt = sum(t for _, t in pairs) / n
        var = sum((k - mk) ** 2 for k, _ in pairs)
        if var == 0:
            break
        period = sum((k - mk) * (t - mt) for k, t in pairs) / var
        offset = mt - period * mk
        while offset - period >= -period * 0.1:
            offset -= period
        offset = max(0.0, offset)
    return period, offset


def _peaks(env: list[float], share: float = 0.35) -> list[float]:
    """Onset peaks, judged against their own neighbourhood (a loud section mustn't hide its
    kicks), timed to a fraction of a frame by fitting a parabola through each peak."""
    radius = int(1.0 / HOP)
    out = []
    for i in range(1, len(env) - 1):
        if not (env[i] >= env[i - 1] and env[i] > env[i + 1]):
            continue
        local = max(env[max(0, i - radius):i + radius + 1])
        if env[i] < share * local or env[i] < 0.02:
            continue
        a, b, c = env[i - 1], env[i], env[i + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom else 0.0
        out.append((i + max(-0.5, min(0.5, shift))) * HOP)
    return out


def _fit_grid(env: list[float], period: float, offset: float) -> tuple[float, float]:
    """Least-squares fit of the beat grid to the onset peaks nearest each predicted beat."""
    peaks = _peaks(env)
    if len(peaks) < 4:
        return period, offset
    for _ in range(3):
        pairs = []
        k_max = int((len(env) * HOP - offset) / period)
        for k in range(k_max + 1):
            want = offset + k * period
            near = min(peaks, key=lambda p: abs(p - want))
            if abs(near - want) <= period / 4:
                pairs.append((k, near))
        if len(pairs) < 4:
            break
        n = len(pairs)
        mk = sum(k for k, _ in pairs) / n
        mt = sum(t for _, t in pairs) / n
        var = sum((k - mk) ** 2 for k, _ in pairs)
        if var == 0:
            break
        period = sum((k - mk) * (t - mt) for k, t in pairs) / var
        offset = mt - period * mk
        while offset - period >= -period * 0.1:
            offset -= period
        offset = max(0.0, offset)
    return period, offset


# ---------- spectral-flux onsets + dynamic-programming beat tracking (needs numpy) ----------
# The standard approach from music research (Ellis 2007, as in common beat trackers): onsets
# from rises across many frequency bands, so hats, snares and 808s all count; tempo from the
# envelope's autocorrelation with a gentle preference around 120 BPM; then the beat sequence
# that best balances "lands on onsets" against "keeps a steady tempo".
SR = 22050
N_FFT = 2048
HOP_NP = 256                       # ~11.6 ms per frame
# A frame's flux peaks when a hit reaches the end of its window, so envelope frames run one
# window ahead of the audio; measured on a generated track with known kicks (92 ms at 2048).
LATENCY = N_FFT / SR


def _decode_np(path: Path):
    import numpy as np
    ffmpeg = shutil.which("ffmpeg")
    proc = subprocess.run([ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
                           "-ar", str(SR), "-f", "f32le", "-"], capture_output=True)
    if proc.returncode or not proc.stdout:
        raise BeatError(f"Can't read audio from {Path(path).name}")
    return np.frombuffer(proc.stdout[: len(proc.stdout) // 4 * 4], dtype=np.float32)


def _onset_envelope_np(y, top_hz: float = 11000.0):
    import numpy as np
    if len(y) < N_FFT:
        y = np.pad(y, (0, N_FFT - len(y)))
    frames = 1 + (len(y) - N_FFT) // HOP_NP
    idx = np.arange(N_FFT)[None, :] + HOP_NP * np.arange(frames)[:, None]
    spec = np.abs(np.fft.rfft(y[idx] * np.hanning(N_FFT)[None, :], axis=1))
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SR)
    edges = np.geomspace(30.0, top_hz, 41)         # 40 log-spaced bands
    bands = np.stack([spec[:, (freqs >= lo) & (freqs < hi)].sum(axis=1) for lo, hi in zip(edges[:-1], edges[1:])], axis=1)
    logb = np.log1p(1000.0 * bands)
    flux = np.maximum(0.0, np.diff(logb, axis=0, prepend=logb[:1])).mean(axis=1)
    # Remove the slowly varying part so sustained loud sections don't swamp the beat.
    k = max(1, int(0.4 * SR / HOP_NP))
    local = np.convolve(flux, np.ones(k) / k, mode="same")
    env = np.maximum(0.0, flux - local)
    return env / (env.max() or 1.0)


def _grid_share(env, bpm: float, phases: int = 32) -> tuple[float, float]:
    """Best share of onset energy within ~3 % of a beat on a steady grid at this tempo, and that phase."""
    import numpy as np
    fps = SR / HOP_NP
    t = np.arange(len(env)) / fps
    period = 60.0 / bpm
    ph = (t / period) % 1.0
    best, best_phase = 0.0, 0.0
    total = env.sum() or 1.0
    for k in range(phases):
        d = np.abs(((ph - k / phases) + 0.5) % 1.0 - 0.5)
        share = env[d < 0.04].sum() / total
        if share > best:
            best, best_phase = share, k / phases
    return float(best), best_phase


def _tempo_np(env) -> float:
    """Candidate tempos from the autocorrelation, plus their 2x, 1/2x, 3/2x and 2/3x relatives
    (the usual confusions), judged by how much rhythmic energy a steady grid at that tempo
    actually catches, with a gentle preference around 120 BPM."""
    import numpy as np
    fps = SR / HOP_NP
    x = env - env.mean()
    ac = np.correlate(x, x, mode="full")[len(x) - 1:]
    ac /= ac[0] or 1.0
    bpms = np.arange(60.0, 200.0, 0.25)
    lags = 60.0 * fps / bpms
    score = np.interp(lags, np.arange(len(ac)), ac, right=0.0)
    order = np.argsort(score)[::-1]
    seeds = []
    for i in order:
        if all(abs(bpms[i] - b) > 3 for b in seeds):
            seeds.append(float(bpms[i]))
        if len(seeds) == 4:
            break
    cands = {round(b * f, 2) for b in seeds for f in (1, 2, 0.5, 1.5, 2 / 3) if 60 <= b * f <= 200}
    def polish(b):
        # A rough tempo drifts off the beat over a long sound, so tune each candidate first.
        fine = np.arange(b * 0.985, b * 1.015, 0.1)
        return max(((float(f), _grid_share(env, f, 24)[0]) for f in fine), key=lambda x: x[1])
    def value(entry):
        b, share = entry
        prior = float(np.exp(-0.5 * (np.log2(b / 120.0) / 1.0) ** 2))
        return share * (0.6 + 0.4 * prior)
    best, share = max((polish(b) for b in cands), key=value)
    # Double time catches the hats between kicks too; take the slower tempo if half the speed
    # still catches most of the rhythm.
    if best / 2 >= 60:
        half, half_share = polish(best / 2)
        if half_share >= 0.62 * share:
            best = half
    fine = np.arange(best - 0.3, best + 0.3, 0.02)
    return float(max(fine, key=lambda b: _grid_share(env, b)[0]))


def _track_np(env, bpm: float, tightness: float = 100.0):
    import numpy as np
    fps = SR / HOP_NP
    period = 60.0 * fps / bpm
    n = len(env)
    score = env.copy()
    back = np.full(n, -1)
    lo, hi = int(round(period / 2)), int(round(2 * period))
    offsets = np.arange(-hi, -lo + 1)
    penalty = -tightness * np.log(-offsets / period) ** 2
    for t in range(n):
        cand = t + offsets
        ok = cand >= 0
        if not ok.any():
            continue
        vals = score[cand[ok]] + penalty[ok]
        j = int(np.argmax(vals))
        if vals[j] > 0:
            score[t] = env[t] + vals[j]
            back[t] = cand[ok][j]
    # Best last beat within the final period, then follow the chain back.
    tail = np.arange(max(0, n - int(period)), n)
    t = int(tail[np.argmax(score[tail])])
    beats = []
    while t >= 0:
        beats.append(t)
        t = int(back[t])
    return np.array(beats[::-1]) / fps + LATENCY


def _grid_from_beats(beats) -> tuple[float, float]:
    """A steady grid (period, first beat) fitted through tracked beats; edit sounds hold tempo."""
    import numpy as np
    k = np.arange(len(beats))
    period, offset = np.polyfit(k, beats, 1)
    while offset - period >= -0.01:
        offset -= period
    return float(period), float(max(0.0, offset))


def _rhythm_np(path: Path) -> tuple[float, float]:
    """Steady grid (period, first beat). Tempo from _tempo_np; the grid's start is the phase
    that puts the most hits on the beat; between beat and half-beat, bass breaks near-ties."""
    import numpy as np
    y = _decode_np(path)
    env = _onset_envelope_np(y)
    bass = _onset_envelope_np(y, top_hz=160.0)
    bpm = _tempo_np(env)
    period = 60.0 / bpm
    t = np.arange(len(env)) * HOP_NP / SR + LATENCY
    def caught(sig, phase):
        d = np.abs((((t - phase) / period) + 0.5) % 1.0 - 0.5)
        return float(sig[d < 0.04].sum() / (sig.sum() or 1.0))
    phases = [k / 64 * period for k in range(64)]
    offset = max(phases, key=lambda ph: caught(env, ph))
    # Beat or half-beat? Near a tie, the bass decides (kicks usually mark the beat).
    other = (offset + period / 2) % period
    if caught(env, other) >= 0.8 * caught(env, offset) and caught(bass, other) > 1.3 * caught(bass, offset):
        offset = other
    if len(t) * HOP_NP / SR < 4 * period:
        raise BeatError("Couldn't find a steady beat in this sound")
    return period, offset


def strong_hits(path: Path) -> list[list[float]]:
    """[time, strength] of every hit clearly above the song's usual onsets: where kills can land."""
    import numpy as np
    y = _decode_np(path)
    comb = 0.5 * _onset_envelope_np(y) + 0.5 * _onset_envelope_np(y, top_hz=160.0)
    t = np.arange(len(comb)) * HOP_NP / SR + LATENCY
    peaks = [i for i in range(2, len(comb) - 2) if comb[i] == comb[i - 2:i + 3].max() and comb[i] > 0.15]
    if not peaks:
        return []
    typical = float(np.median([comb[i] for i in peaks]))
    return [[round(float(t[i]), 3), round(float(comb[i]), 2)] for i in peaks if comb[i] >= max(0.3, 1.1 * typical)]


def accent_runs(path: Path, min_hits: int = 3) -> list[dict[str, Any]]:
    """The song's standout hits ("dun dun dun"): onsets clearly stronger than its usual hits,
    in tight runs (no gap over 0.6 s). Each run lists its hit times and strengths, strongest
    run first. Edits put one kill on each hit of a run."""
    import numpy as np
    y = _decode_np(path)
    full = _onset_envelope_np(y)
    bass = _onset_envelope_np(y, top_hz=160.0)
    comb = 0.5 * full + 0.5 * bass
    t = np.arange(len(comb)) * HOP_NP / SR + LATENCY
    peaks = [i for i in range(2, len(comb) - 2) if comb[i] == comb[i - 2:i + 3].max() and comb[i] > 0.15]
    if not peaks:
        return []
    typical = float(np.median([comb[i] for i in peaks]))
    strong = [i for i in peaks if comb[i] >= max(0.42, 1.35 * typical)]
    runs, current = [], []
    for i in strong:
        if current and t[i] - t[current[-1]] > 0.6:
            runs.append(current)
            current = []
        current.append(i)
    if current:
        runs.append(current)
    out = []
    for run in runs:
        # A burst, not a section: a steady loud stretch (e.g. everything after a drop) isn't
        # a "dun dun dun".
        if len(run) < min_hits or t[run[-1]] - t[run[0]] > 4.0:
            continue
        values = [float(comb[i]) for i in run]
        out.append({"hits": [round(float(t[i]), 3) for i in run], "strength": [round(v, 2) for v in values],
                    "score": round(sum(values) / typical, 2)})
    return sorted(out, key=lambda r: r["score"], reverse=True)


def phase_profile(path: Path, period: float, first: float, bins: int = 16) -> list[float]:
    """How onset energy falls across one beat when folded onto the grid: a correct grid
    piles it up in bin 0 (and often bin bins/2). For checking a beat map."""
    import numpy as np
    env = _onset_envelope_np(_decode_np(path))
    t = np.arange(len(env)) * HOP_NP / SR + LATENCY
    phase = (((t - first) / period) % 1.0 * bins).astype(int) % bins
    prof = np.bincount(phase, weights=env, minlength=bins)
    return (prof / (prof.mean() or 1.0)).round(2).tolist()


def analyze_beats(path: Path) -> dict[str, Any]:
    path = Path(path)
    if not path.is_file():
        raise BeatError(f"File not found: {path}")
    low = _energy(_decode(path, 200))
    full = _energy(_decode(path, None))
    duration = len(full) * HOP
    if duration < 4:
        raise BeatError("The sound needs to be at least 4 seconds long")
    try:
        period, offset = _rhythm_np(path)
    except ImportError:  # no numpy: the simpler tracker, fine for clean drum tracks
        env = _onsets(low)
        bpm, offset = _refine(env, _tempo(env))
        period, offset = _fit_grid(env, 60.0 / bpm, offset)
    bpm = 60.0 / period
    beats = []
    t = offset
    while t < duration - 0.05:
        beats.append(round(t, 3))
        t += period
    # The drop: the beat where the next 2 s are loudest compared with the 2 s before.
    span = int(2.0 / HOP)
    def mean(a: int, b: int) -> float:
        seg = full[max(0, a):max(0, min(len(full), b))]
        return sum(seg) / len(seg) if seg else 0.0
    best, drop = -math.inf, beats[min(len(beats) - 1, 4)] if beats else 0.0
    for b in beats:
        i = int(b / HOP)
        if b < 2.0 or i + span > len(full):
            continue
        before, after = mean(i - span, i), mean(i, i + span)
        jump = math.log10((after + 1e-4) / (before + 1e-4))
        if jump > best:
            best, drop = jump, b
    try:
        accents = accent_runs(path)
        hits = strong_hits(path)
    except ImportError:
        accents, hits = [], []
    return {"ok": True, "file": path.name, "duration": round(duration, 3), "bpm": round(bpm, 1),
            "beat_seconds": round(period, 4), "beats": beats, "drop": drop,
            "drop_strength": round(best, 3) if best > -math.inf else 0.0, "accents": accents, "hits": hits}
