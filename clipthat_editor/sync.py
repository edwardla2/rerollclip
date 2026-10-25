"""Beat-synced Highlight: pace a clip's kills to the rhythm of a chosen sound.

The export carries the game audio only. The player adds the same sound inside TikTok
(licensed there), starting at `sound_start`, and the edit lines up with it:
- the final kill lands exactly on the drop, in brief slow motion with a slight punch-in;
- earlier kills land on beats where the footage allows: the stretches between kills are
  sped up (1-2.4x) by just enough to reach a beat, while each kill itself plays at 1x;
- a short lead-in before the first kill, and the aftermath (e.g. the ACE banner) holds
  until a beat about two seconds after the drop.
"""
from __future__ import annotations

from typing import Any

from .highlight import Segment

KILL_BEFORE = 0.25      # normal speed this long before a kill...
KILL_AFTER = 0.35       # ...and after it
FINAL_BEFORE = 0.35     # slow motion around the final kill
FINAL_AFTER = 0.6
FINAL_SPEED = 0.6
FINAL_ZOOM = 1.1
MIN_SPEED, MAX_SPEED, IDEAL_SPEED = 1.0, 2.4, 1.6
LEAD_IN = 1.6           # output seconds before the first kill
AFTERMATH = 2.0         # output seconds after the final kill, then on to the next beat
CLUSTER = 15.0          # kills more than this long before the final one are left out


def _beat_before(beats: list[float], t: float) -> list[float]:
    return [b for b in beats if b < t - 1e-6]


def plan_to_music(kills: list[float], duration: float, music: dict[str, Any]) -> dict[str, Any]:
    beats, drop = music["beats"], music["drop"]
    if not kills:
        raise ValueError("No kills to sync")
    final = kills[-1]
    kills = [k for k in kills if final - k <= CLUSTER]
    n = len(kills)

    # Output time of each kill, working back from the final kill on the drop.
    out = [0.0] * n
    out[-1] = drop
    speeds = [1.0] * max(0, n - 1)          # speed of the stretch between kill i and i+1
    for i in range(n - 2, -1, -1):
        head = FINAL_BEFORE if i + 1 == n - 1 else KILL_BEFORE
        head_out = head / FINAL_SPEED if i + 1 == n - 1 else head
        mid = (kills[i + 1] - head) - (kills[i] + KILL_AFTER)
        fixed = KILL_AFTER + head_out
        natural = out[i + 1] - (mid + fixed)          # where kill i lands at 1x
        best = None
        if mid > 0.3:
            for b in _beat_before(beats, out[i + 1]):
                room = out[i + 1] - b - fixed
                if room <= 0:
                    continue
                s = mid / room
                if MIN_SPEED <= s <= MAX_SPEED and (best is None or abs(s - IDEAL_SPEED) < abs(best[1] - IDEAL_SPEED)):
                    best = (b, s)
        if best:
            out[i], speeds[i] = best
        else:
            out[i], speeds[i] = natural, 1.0       # too tight to reach a beat: leave it natural

    # Lead-in: the sound starts so the first kill has LEAD_IN of footage before it.
    lead_src = min(LEAD_IN, kills[0])
    sound_start = out[0] - lead_src
    if sound_start < 0:
        sound_start = 0.0
        lead_src = min(kills[0], out[0])
    else:
        # Start the sound on a beat so the first frame isn't mid-beat.
        on_beat = [b for b in beats if b <= sound_start + 1e-6]
        if on_beat:
            lead_src = min(kills[0], lead_src + (sound_start - on_beat[-1]))
            sound_start = out[0] - lead_src
    start_src = kills[0] - lead_src

    # Aftermath: hold until the first beat at least AFTERMATH after the drop (footage permitting).
    tail_src = duration - (final + FINAL_AFTER)
    target_end = next((b for b in beats if b >= drop + AFTERMATH), drop + AFTERMATH)
    hold = max(0.0, min(tail_src, target_end - (drop + FINAL_AFTER / FINAL_SPEED)))

    segments: list[Segment] = []
    def add(a: float, b: float, speed: float = 1.0, zoom: float = 1.0) -> None:
        if b - a >= 0.02:
            segments.append(Segment(round(a, 3), round(b, 3), speed, zoom))

    # Lead-in (and the first kill at 1x, unless the first kill is the final one).
    add(start_src, kills[0] + KILL_AFTER if n > 1 else final - FINAL_BEFORE)
    for i in range(n - 1):
        head = FINAL_BEFORE if i + 1 == n - 1 else KILL_BEFORE
        add(kills[i] + KILL_AFTER, kills[i + 1] - head, speeds[i])
        if i + 1 < n - 1:
            add(kills[i + 1] - head, kills[i + 1] + KILL_AFTER)
    add(final - FINAL_BEFORE, final + FINAL_AFTER, FINAL_SPEED, FINAL_ZOOM)
    add(final + FINAL_AFTER, final + FINAL_AFTER + hold)
    # Merge touching 1x pieces.
    merged: list[Segment] = []
    for s in segments:
        if merged and merged[-1].speed == s.speed == 1.0 and merged[-1].zoom == s.zoom and abs(merged[-1].end - s.start) < 1e-3:
            merged[-1] = Segment(merged[-1].start, s.end, 1.0, 1.0)
        else:
            merged.append(s)
    total = sum(s.output_length for s in merged)
    landed = [round(o - sound_start, 3) for o in out]
    on_beat = [any(abs(o - b) < 0.02 for b in beats) or o == drop for o in out]
    return {
        "segments": [s.__dict__ for s in merged],
        "kills": kills,
        "kills_at_output": landed,
        "kills_on_beat": on_beat,
        "drop_at_output": round(drop - sound_start, 3),
        "sound_start": round(sound_start, 3),
        "bpm": music["bpm"],
        "output_seconds": round(total, 3),
    }


# ---------- hit-sync: one kill on each of the song's standout hits ("dun dun dun") ----------
HIT_PRE_SHARE = 0.6     # of the time between two hits, this share shows the run-up to the next kill
HIT_MIN_PRE = 0.12      # never cut in later than this before a kill...
HIT_MIN_POST = 0.08     # ...or out sooner than this after one
HIT_LEAD_MAX = 3.0      # longest lead-in of real footage before the first kill
HIT_HOLD = 4.0          # after the last kill: play on (slowing for the punch-in) about this long, riding the drop


MIN_KILL_SHOW = 0.45    # a kill needs about this long on screen to read (enemy, shot, drop)
HIT_PRE_MIN = 0.3       # show at least this much before the shot: the enemy and the aim


def best_window(run: dict[str, Any], k: int, min_gap: float = MIN_KILL_SHOW) -> list[float] | None:
    """k hits from a run, in order, at least min_gap apart, with the highest total strength.
    Hits closer than a kill can be read (e.g. every other "dun") are skipped."""
    hits, strength = run["hits"], run["strength"]
    n = len(hits)
    if n < k:
        return None
    # best[j][c] = (total strength, chosen indices) of c hits ending at hit j
    best: list[dict[int, tuple[float, list[int]]]] = [dict() for _ in range(n)]
    for j in range(n):
        best[j][1] = (strength[j], [j])
        for c in range(2, k + 1):
            options = [(best[i][c - 1][0] + strength[j], best[i][c - 1][1] + [j])
                       for i in range(j) if c - 1 in best[i] and hits[j] - hits[i] >= min_gap - 1e-6]
            if options:
                best[j][c] = max(options)
    finals = [best[j][k] for j in range(n) if k in best[j]]
    if not finals:
        return None
    return [hits[i] for i in max(finals)[1]]


def plan_to_hits(kills: list[float], duration: float, music: dict[str, Any]) -> dict[str, Any] | None:
    """Cut kill to kill so each kill lands on one standout hit; None if the sound has no run
    with enough hits for these kills."""
    final = kills[-1]
    kills = [k for k in kills if final - k <= CLUSTER]
    window = None
    for run in music.get("accents", []):
        window = best_window(run, len(kills))
        if window:
            break
    if not window:
        return None
    return cut_to_targets(kills, duration, window, music, "hits")


def drop_targets(n: int, music: dict[str, Any], min_gap: float = MIN_KILL_SHOW) -> list[float]:
    """Where n kills land: the first on the drop, each next on the song's next hit at least
    min_gap later ("dun, dun, dun"). Where the song has no clear hit in time, the beat grid
    (at the shortest of half-beat, beat, two beats that's still readable) fills in."""
    drop = music["drop"]
    hits = [h for h in music.get("hits", []) if h[0] >= drop - 0.12]
    # The drop itself: snap to its hit if one is right there.
    near = [h for h in hits if abs(h[0] - drop) <= 0.12]
    first = max(near, key=lambda h: h[1])[0] if near else drop
    period = 60.0 / music["bpm"]
    step = next((m * period for m in (0.5, 1, 2) if m * period >= min_gap - 1e-6), 2 * period)
    targets = [first]
    while len(targets) < n:
        prev = targets[-1]
        options = [h for h in hits if prev + min_gap - 1e-6 <= h[0] <= prev + step + 0.12]
        if options:
            # The first clear hit in reach; a much stronger one a moment later wins.
            pick_ = options[0]
            for h in options[1:]:
                if h[1] > 1.4 * pick_[1]:
                    pick_ = h
            targets.append(pick_[0])
        else:
            targets.append(round(prev + step, 3))
    return [round(t, 3) for t in targets]


def plan_to_drop(kills: list[float], duration: float, music: dict[str, Any]) -> dict[str, Any] | None:
    """In order: the build-up before the first kill plays out, the first kill's shot lands on
    the drop, and every next kill on the next hit. None if the drop comes too late in the sound."""
    final = kills[-1]
    kills = [k for k in kills if final - k <= CLUSTER]
    targets = drop_targets(len(kills), music)
    if targets[-1] > music.get("duration", float("inf")) - 0.3:
        return None   # the sound ends before the last kill's hit
    return cut_to_targets(kills, duration, targets, music, "drop")


def cut_to_targets(kills: list[float], duration: float, window: list[float], music: dict[str, Any],
                   mode: str) -> dict[str, Any]:
    """Hard cuts kill to kill so kill i's shot lands at song time window[i]."""
    n = len(kills)
    final = kills[-1]
    gaps = [b - a for a, b in zip(window, window[1:])]
    # Lead-in: real footage before the first kill, as much as the clip has (up to HIT_LEAD_MAX).
    pre_first = min(kills[0], HIT_LEAD_MAX)
    sound_start = max(0.0, window[0] - pre_first)
    pre_first = window[0] - sound_start
    segments: list[Segment] = []
    def add(a: float, b: float, speed: float = 1.0, zoom: float = 1.0) -> None:
        if b - a >= 0.02:
            segments.append(Segment(round(a, 3), round(b, 3), speed, zoom))
    start = kills[0] - pre_first
    for i in range(n - 1):
        g = gaps[i]
        pre_next = max(HIT_PRE_MIN, HIT_PRE_SHARE * g)
        post = max(HIT_MIN_POST, g - pre_next)
        pre_next = g - post
        source_gap = kills[i + 1] - kills[i]
        if source_gap <= g:
            # Kills closer together in the clip than the hits: play straight through to the
            # next kill, slowed just enough that it lands on its hit.
            add(start, kills[i])
            add(kills[i], kills[i + 1], max(0.5, source_gap / g))
            start = kills[i + 1]
            continue
        add(start, kills[i] + post)           # hard cut after kill i...
        start = kills[i + 1] - pre_next       # ...into the run-up of kill i+1
    # Last kill: on its hit, then play on and slow into a punch-in for the aftermath.
    tail = duration - final
    normal = min(tail, 0.35)
    add(start, final + normal)
    slow_src = min(max(0.0, tail - normal), 0.6)
    add(final + normal, final + normal + slow_src, FINAL_SPEED, FINAL_ZOOM)
    used = normal + slow_src / FINAL_SPEED
    hold_src = max(0.0, min(duration - (final + normal + slow_src), HIT_HOLD - used))
    add(final + normal + slow_src, final + normal + slow_src + hold_src)
    total = sum(s.output_length for s in segments)
    out = [round(h - sound_start, 3) for h in window]
    return {
        "mode": mode,
        "segments": [s.__dict__ for s in segments],
        "kills": kills,
        "hits": window,
        "kills_at_output": out,
        "kills_on_beat": [True] * n,
        "drop_at_output": round(music["drop"] - sound_start, 3),
        "sound_start": round(sound_start, 3),
        "bpm": music["bpm"],
        "output_seconds": round(total, 3),
    }


def plan_for(kills: list[float], duration: float, music: dict[str, Any], sync: str = "auto") -> dict[str, Any] | None:
    """sync: "drop" (first kill on the drop, each next kill on the next hit), "hits" (kills on a
    burst of standout hits), "beats" (kills on beats, final on the drop) or "auto" (drop when the
    sound has room after its drop for the kills, else beats)."""
    if sync not in ("auto", "drop", "hits", "beats"):
        raise ValueError("sync must be auto, drop, hits or beats")
    if sync in ("auto", "drop"):
        plan = plan_to_drop(kills, duration, music)
        if plan or sync == "drop":
            return plan
    if sync == "hits":
        return plan_to_hits(kills, duration, music)
    plan = plan_to_music(kills, duration, music)
    plan.setdefault("mode", "beats")
    return plan
