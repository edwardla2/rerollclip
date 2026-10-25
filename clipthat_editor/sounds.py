"""Reroll's sound list, and picking the best sound for a clip.

The list holds what's needed to time an edit to a trending sound, never the audio:
title, artist, the TikTok sound link, tempo, the first beat, the drop and the length of the
excerpt TikTok plays. Entries are added with `python -m clipthat_editor sounds add <audio>`,
which reads the rhythm once (beats.py); the audio file isn't kept.

For each clip the engine test-fits every sound with the real pacing plan (sync.py) and
picks the one where the most kills land on beats, the speed-ups look natural, the lead-in
isn't abrupt and the edit is a postable length. The player then adds that sound in TikTok.
"""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

from .beats import analyze_beats
from .sync import IDEAL_SPEED, plan_to_music

DEFAULT_LIST = Path(__file__).with_name("sounds.json")


def load(path: Path | None = None) -> list[dict[str, Any]]:
    path = Path(path or DEFAULT_LIST)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("sounds", [])


def save(sounds: list[dict[str, Any]], path: Path | None = None) -> None:
    path = Path(path or DEFAULT_LIST)
    path.write_text(json.dumps({"schema_version": 1, "sounds": sounds}, indent=2) + "\n", encoding="utf-8")


def rhythm(entry: dict[str, Any]) -> dict[str, Any]:
    """The beat grid rebuilt from a list entry, in the shape sync.plan_to_music expects."""
    period = 60.0 / entry["bpm"]
    beats, t = [], entry["first_beat"]
    while t < entry["duration"] - 0.05:
        beats.append(round(t, 3))
        t += period
    return {"bpm": entry["bpm"], "beats": beats, "drop": entry["drop"], "file": entry["title"],
            "duration": entry["duration"]}


def find(query: str, path: Path | None = None) -> list[dict[str, Any]]:
    """Songs whose title or artist contains every word of the query (case-insensitive)."""
    words = query.lower().split()
    return [s for s in load(path) if all(w in f"{s['title']} {s['artist']}".lower() for w in words)]


def add(audio: Path, *, title: str = "", artist: str = "", url: str = "", games: list[str] | None = None,
        song_id: str = "", path: Path | None = None) -> dict[str, Any]:
    """Reads a sound's rhythm and stores its beat map. With `song_id`, fills in an existing
    song on the list (keeping its title, artist and tags); otherwise adds a new one."""
    r = analyze_beats(Path(audio))
    sounds = load(path)
    existing = next((s for s in sounds if s["id"] == song_id), None) if song_id else None
    if song_id and existing is None:
        raise ValueError(f"No song with id {song_id} on the list")
    entry = dict(existing or {
        "id": "-".join(f"{artist} {title}".lower().split())[:60],
        "title": title, "artist": artist, "games": [], "added": date.today().isoformat(),
    })
    entry.update(bpm=r["bpm"], first_beat=r["beats"][0] if r["beats"] else 0.0, drop=r["drop"],
                 duration=r["duration"], mapped=True, mapped_on=date.today().isoformat())
    if url:
        entry["tiktok_url"] = url
    entry.setdefault("tiktok_url", "")
    if games:
        entry["games"] = sorted(set(entry.get("games", [])) | set(games))
    sounds = [s for s in sounds if s["id"] != entry["id"]] + [entry]
    save(sounds, path)
    return entry


def score_plan(plan: dict[str, Any]) -> float:
    """Higher is better. Kills on the beat matter most; then natural speed-ups, a real
    lead-in before the first kill, and a length people finish watching (7-20 s)."""
    on_beat = sum(plan["kills_on_beat"]) / len(plan["kills_on_beat"])
    ramps = [s["speed"] for s in plan["segments"] if s["speed"] > 1]
    speed_cost = sum(abs(s - IDEAL_SPEED) for s in ramps) / len(ramps) if ramps else 0.0
    lead = plan["kills_at_output"][0]
    lead_cost = max(0.0, 0.8 - lead)
    length = plan["output_seconds"]
    length_cost = max(0.0, 7 - length) / 7 + max(0.0, length - 20) / 20
    return round(3.0 * on_beat - 0.8 * speed_cost - 1.2 * lead_cost - 1.5 * length_cost, 4)


def pick(kills: list[float], duration: float, *, game: str = "", path: Path | None = None,
         sounds: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    sounds = sounds if sounds is not None else load(path)
    ranked = []
    for entry in sounds:
        if not entry.get("mapped", "bpm" in entry):
            continue  # on the list, but its beat map hasn't been made yet
        try:
            plan = plan_to_music(kills, duration, rhythm(entry))
        except ValueError:
            continue
        score = score_plan(plan) + (0.3 if game and game in entry.get("games", []) else 0.0)
        ranked.append((score, entry, plan))
    if not ranked:
        return None
    ranked.sort(key=lambda r: r[0], reverse=True)
    score, entry, plan = ranked[0]
    return {"sound": entry, "plan": plan, "score": score,
            "alternatives": [{"id": e["id"], "title": e["title"], "artist": e["artist"], "score": s}
                             for s, e, _ in ranked[1:4]]}
