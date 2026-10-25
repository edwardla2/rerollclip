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
