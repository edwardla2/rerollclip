# Reroll edit engine: taste → planner → timeline → renderer

```
kills (events.py) ─┐
song beats (beats.py) ─┼─> director (creative decisions) ──> Timeline JSON ──> compositor (rendering only) ──> MP4
taste profile (taste/) ─┘          gameplay_first | velocity_montage        timeline.py         compositor.py
```

* **Taste profile** (`clipthat_editor/taste/default.json`, loaded by `taste.py`): editorial
  preferences as data: format, intensity tiers, pacing, which recipes rotate, the top-event
  recipe, the monochrome accent budget, text mode, protected regions and zoom limit, branding.
  A user profile can override any part (`--taste my.json`, `--intensity aggressive`).
* **Planner** (`director.py`): reads events, beats and taste; writes a Timeline. Two styles:
  * `gameplay_first` (default): ranks kills (the final elimination / ace is the top event),
    gives each a different treatment (`punch`, `ramp`, `snap`; `hang` for the top event),
    keeps real-speed lead-ins and aftermaths, compresses downtime with a smooth speed curve
    (short gaps) or a cut on the beat (long gaps), lands every kill on a beat, skips flat
    footage (smoke) at the start of a lead-in, allows one black-and-white accent, no words,
    and picks a HUD-free corner for the "made with reroll" mark by measuring where the HUD is.
  * `velocity_montage` (`--style stylized`): the heavy reference look (typography, colour
    split, radial whips, replay flurry); see `reference-breakdown.md`.
* **Timeline** (`timeline.py`): clips with a monotone Hermite time remap (speed keys, so ramps
  are smooth and kills land exactly), keyframed camera (zoom, roll, pan, shake), master effect
  curves in output time (flash, colour split, bloom, radial blur, edge glow, exposure, mono),
  text layers, sound effects, look (grade) and branding. Round-trips through JSON.
* **Compositor** (`compositor.py`): pass 1 renders each clip piece (split where it enters or
  leaves slow motion; in-between frames synthesized only there), frame- and sample-exact,
  two at a time, cached; pass 2 applies master effects driven per frame by a command stream,
  overlays typography and the brand mark, mixes sound effects; export limits peaks and sets
  −14 LUFS. `--preview` adds a private copy with the song mixed in; the export never contains it.

Run: `python -m clipthat_editor montage clip.mp4 --music song.mp3 --output edit.mp4 [--preview]`
(the timeline is written next to the output as `edit.timeline.json`; `--timeline` re-renders one).
