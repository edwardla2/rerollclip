"""The taste profile: Reroll's editorial preferences as data, kept apart from the editing
timeline and the renderer. The planner (director.py) reads it to choose framing, pacing and
effect recipes; the compositor only executes what the timeline says.

Load with `load()` (the bundled default, or a user's JSON); `tier()` returns the effect
strengths for the chosen intensity.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

DEFAULT = Path(__file__).parent / "taste" / "default.json"
INTENSITIES = ("restrained", "medium", "aggressive")


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load(path: Path | None = None, **overrides: Any) -> dict[str, Any]:
    """The default profile, with a user profile (partial is fine) and keyword overrides on top,
    e.g. load(intensity="aggressive", text={"mode": "stylized"})."""
    taste = json.loads(DEFAULT.read_text())
    if path:
        taste = _merge(taste, json.loads(Path(path).read_text()))
    taste = _merge(taste, {k: v for k, v in overrides.items() if v is not None})
    problems = check(taste)
    if problems:
        raise ValueError("Taste profile: " + "; ".join(problems))
    return taste


def check(taste: dict[str, Any]) -> list[str]:
    issues = []
    if taste.get("intensity") not in INTENSITIES:
        issues.append(f"intensity must be one of {', '.join(INTENSITIES)}")
    for name in INTENSITIES:
        if name not in taste.get("tiers", {}):
            issues.append(f"missing tier {name}")
    if taste.get("format", {}).get("aspect") not in ("9:16", "16:9"):
        issues.append("format.aspect must be 9:16 or 16:9")
    if taste.get("text", {}).get("mode") not in ("off", "stylized"):
        issues.append("text.mode must be off or stylized")
    if taste.get("protect", {}).get("zoom_max", 2) < 1:
        issues.append("protect.zoom_max must be at least 1")
    return issues


def tier(taste: dict[str, Any], intensity: str | None = None) -> dict[str, Any]:
    return dict(taste["tiers"][intensity or taste["intensity"]])
