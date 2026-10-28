"""The player's clip library: what's in the Medal folder, what each clip contains, and which clips
make the next compilation (the product: "your recent plays as one postable video").

Analysis is slow (kill feed, banners, audio), so results are cached in a ledger keyed by path, size
and modification time; a clip is analysed once. The desktop app calls `scan` when Medal saves a
clip and `pick` + `compile_clips` when the player asks for a video.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from typing import Any

VIDEO = {".mp4", ".mkv", ".mov"}
LEDGER_VERSION = 2


def clips_in(folder: Path) -> list[Path]:
    """Video files under the folder, oldest first, leaving out Reroll's own outputs."""
    out = []
    for p in Path(folder).rglob("*"):
        if p.suffix.lower() in VIDEO and p.is_file() and "(Reroll)" not in p.name \
                and "Reroll" not in p.relative_to(folder).parts[:-1]:
            out.append(p)
    return sorted(out, key=lambda p: p.stat().st_mtime)


def _kill_frames(path: Path, times: list[float]) -> list[list[int]]:
    """A tiny greyscale thumbnail at each kill: footage fingerprints for spotting the same play
    saved twice (Medal can auto-clip and manually clip the same moment)."""
    prints = []
    for t in times:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{max(0.0, t + 0.3):.2f}", "-i", str(path),
                              "-frames:v", "1", "-vf", "scale=32:18,format=gray", "-f", "rawvideo", "-"],
                             capture_output=True).stdout
        if len(raw) == 32 * 18:
            prints.append(list(raw))
    return prints


def analyse(path: Path, profile: str = "valorant") -> dict[str, Any]:
    from .compositor import _probe
    from .events import action_times, find_events
    from .montage import _duration
    ev = find_events(path, profile)
    info = _probe(path)
    return {"duration": _duration(path, "v:0"), "height": info["height"], "kills": ev["times"],
            "count": ev.get("count"), "story": ev.get("story", []), "ace_at": ev.get("ace_at"),
            "detector": ev["source"], "confidence": ev.get("confidence", "high"), "game": profile if ev["source"].endswith("-kills") else None,
            "action": action_times(path), "prints": _kill_frames(path, ev["times"]), "analysed_at": time.time()}


class Library:
    def __init__(self, folder: Path, ledger: Path | None = None, profile: str = "valorant"):
        self.folder = Path(folder).resolve()
        self.ledger = Path(ledger) if ledger else self.folder / ".reroll" / "library.json"
        self.profile = profile
        self.entries: dict[str, dict[str, Any]] = {}
        if self.ledger.exists():
            data = json.loads(self.ledger.read_text())
            if data.get("version") == LEDGER_VERSION:
                self.entries = data["clips"]

    def save(self) -> None:
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ledger.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": LEDGER_VERSION, "clips": self.entries}))
        tmp.replace(self.ledger)

    def scan(self, progress=None) -> list[str]:
        """Analyses clips that are new or changed since the last scan. Returns their paths."""
        new = []
        files = clips_in(self.folder)
        for i, p in enumerate(files):
            st = p.stat()
            key = str(p)
            known = self.entries.get(key)
            if known and known["size"] == st.st_size and known["mtime"] == st.st_mtime:
                continue
            if progress:
                progress("analysing", i / max(1, len(files)), p.name)
            try:
                info = analyse(p, self.profile)
            except Exception as exc:          # a broken or still-writing file: try again next scan
                info = {"error": str(exc)[:300]}
            self.entries[key] = {"size": st.st_size, "mtime": st.st_mtime, **info}
            new.append(key)
        for gone in [k for k in self.entries if not Path(k).exists()]:
            del self.entries[gone]
        self.save()
        return new

    def plays(self) -> list[dict[str, Any]]:
        return [{"source": k, **v} for k, v in self.entries.items() if v.get("kills")]


def score(play: dict[str, Any]) -> float:
    """How strong a play is: kills, with an ace on top."""
    kills = play.get("count") or len(play.get("kills", []))
    return kills + (2.0 if (play.get("ace_at") is not None or kills >= 5) else 0.0)


def same_play(a: dict[str, Any], b: dict[str, Any], tolerance: float = 6.0) -> bool:
    """Two clips of the same moment: some kill frame of one matches a kill frame of the other."""
    for pa in a.get("prints", []):
        for pb in b.get("prints", []):
            diff = sum(abs(x - y) for x, y in zip(pa, pb)) / max(1, len(pa))
            if diff < tolerance:
                return True
    return False


def pick(plays: list[dict[str, Any]], *, since: float | None = None, max_plays: int = 5,
         max_seconds: float = 90.0, taste: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The plays for the next compilation: recent ones (saved after `since`), each play once
    (duplicates dropped, keeping the longer clip), strongest first until the clip count or the
    estimated length runs out. Returns (plays, notes); the planner orders them best-last."""
    from .director import play_windows
    from .taste import load
    cfg = (taste or load())["story"]
    notes = []
    pool = [p for p in plays if since is None or p.get("mtime", 0) >= since]
    # Clips whose kills couldn't be confirmed as yours go in only if nothing else is there.
    sure = [p for p in pool if p.get("confidence", "high") == "high"]
    if sure:
        for p in pool:
            if p not in sure:
                notes.append(f"left out {Path(p['source']).name}: couldn't confirm which kills are yours")
        pool = sure
    pool.sort(key=lambda p: (score(p), p.get("duration", 0)), reverse=True)
    chosen: list[dict[str, Any]] = []
    total = 0.0
    for p in pool:
        twin = next((c for c in chosen if same_play(c, p)), None)
        if twin:
            notes.append(f"skipped {Path(p['source']).name}: same play as {Path(twin['source']).name}")
            continue
        wins = play_windows(p["kills"], p.get("story", []), p["duration"], cfg, p.get("action"))
        span = wins[-1][1] - wins[0][0] if wins else 0.0
        if chosen and (len(chosen) >= max_plays or total + span > max_seconds * 1.15):
            notes.append(f"left out {Path(p['source']).name}: over the length budget")
            continue
        chosen.append(p)
        total += span
    return chosen, notes
