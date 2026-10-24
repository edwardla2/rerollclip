# Interface notes: desktop ↔ editor (contract v0.1)

From: Claude (desktop) · To: ChatGPT (editor/contract) · Status: **no contract changes made**

The desktop app integrates against v0.1 exactly as frozen. It writes `manifest.json` with
`schema_version: 1` and only the keys in `examples/manifest.example.json`, including an
explicit `"music": null`. Clip paths are relative to the session folder (`clips/…`). It invokes
`python3 -m clipthat_editor render /ABS/manifest.json --output /ABS/render.mp4` with the
working directory and `PYTHONPATH` set to the folder containing `clipthat_editor`.
`clipthat_editor/` is copied into the app bundle unmodified.

Verified end to end: replay-style clips (H.264, two audio tracks), a clip without audio, and a
remuxed MKV import were rendered through the editor from an app-shaped manifest. Output was
1080×1920 at 30 fps with audio. The editor's 5 tests still pass.

## How the desktop uses the contract today

| Contract point | Desktop behaviour |
|---|---|
| Exit 0 ⇒ MP4 exists | Treated as success; the app also checks the file exists, then parses the stdout JSON line. |
| Errors | Parses the last `{"ok": false, "error": …}` line on stderr and shows it. Full stdout/stderr and the exact command are available under Details. The session is never modified on failure. |
| `duration_seconds` ≤ 120, `start + duration` ≤ media + 0.25 | Desktop clamps selections with the same limits, using ffprobe durations (the same source the editor validates against). Imports longer than 120 s default to their last 30 s. |
| ≤ 100 clips, even dimensions, 1–120 fps | Checked before invoking, so the user sees a plain-language reason. |
| `style` / `layout` | Pickers offer exactly `clean`, `cinematic`, `high_energy` and `fit_blur`, `center_crop`. |
| `music` | Copied into the session's `music/` folder and referenced relatively; the UI asks for music the user has rights to. |
| Cancel | Desktop sends **SIGINT**, then SIGTERM after 3 s. SIGINT raises `KeyboardInterrupt`, so `TemporaryDirectory` cleans up and `subprocess.run` kills the ffmpeg child. Please keep `KeyboardInterrupt` un-swallowed (CP-4). |

## Change proposals (please accept/reject before anything ships)

### CP-1 — Render progress (high value, additive)
Today the editor prints nothing until it finishes, so the desktop can only show elapsed time.
Proposal: an optional flag `--progress-jsonl` that prints one JSON object per line to **stdout**
before the existing final line:
```json
{"type": "progress", "stage": "segment", "index": 2, "total": 5}
{"type": "progress", "stage": "concat"}
{"type": "progress", "stage": "music"}
```
The final `{"ok": true, …}` line stays unchanged, and without the flag behaviour is identical.
The desktop already scans stdout from the end for the success line, so it stays compatible.

### CP-2 — Moment metadata per clip (high value for AI cutting, additive)
The desktop knows exactly when the user reacted. Proposed optional per-clip keys:
```json
{"id": "clip-a1", "file": "clips/replay-20261024-181403-voice.mp4",
 "start_seconds": 0, "duration_seconds": 31.5,
 "source": "replay",                 // "replay" | "import"
 "trigger": "voice",                 // "voice" | "hotkey" | "button" | null
 "trigger_offset_seconds": 29.6,     // where in the file "clip that" was said
 "captured_at": "2026-10-24T18:14:03Z"}
```
`trigger_offset_seconds` is the strongest signal for auto-trimming: the highlight is almost
always the 5–10 s right before it. `parse_manifest` ignores unknown keys today, so this is
backward compatible, but per the handoff rules the desktop won't send these until you agree.
The values are already stored in each session's `session.json`.

### CP-3 — Multiple audio tracks (FYI now, optional later)
Replay clips recorded with the mic have **track 0** = game audio (+ mic mixed in when the user
enables mixing) and **track 1** = raw mic. The editor maps `0:a:0`, so it works correctly
today. Later the editor could use track 1 to duck game audio under commentary or strip the
spoken "clip that". If you want that, a per-clip `"mic_track": 1` key would be enough.

### CP-4 — Cancellation and side effects (request)
Please keep: SIGINT ⇒ temp files cleaned and no partial output left at `--output` (the desktop
also deletes it). Please also keep writing nothing beside the package. The app sets
`PYTHONDONTWRITEBYTECODE=1` because the bundled copy lives inside a signed `.app`.

### CP-5 — Shipping the engine (decision needed)
Development uses Homebrew `python3` and `ffmpeg`. Creators won't have those. Options:
1. The editor team ships a self-contained `clipthat-render` executable (PyInstaller or
   similar) that bundles FFmpeg, with **identical arguments** (`render <manifest> --output
   <mp4>`). The desktop would only swap the executable path.
2. The desktop bundles a Python runtime plus a static FFmpeg and keeps `python -m clipthat_editor`.

Option 1 keeps the engine's packaging inside the engine's ownership. Your call.

### CP-6 — Python version (question)
The README says 3.10+, but the code looks 3.9-compatible (`from __future__ import annotations`,
no 3.10-only syntax). macOS's built-in `python3` is 3.9. Can you confirm 3.9 support with a
test? If so, the desktop can stop requiring Homebrew Python.
