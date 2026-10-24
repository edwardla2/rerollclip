# Clip That: engineering status

Owner: Claude · Updated: 2026-10-24

## Milestones

| Phase | Item | Status | Evidence |
|---|---|---|---|
| P0 | One canonical repo, single README, archived history | ✅ Done | this tree |
| P0 | One schema: desktop core builds manifests via `ClipThatContracts` | ✅ Done (code) | compile pending |
| P0 | Swift build route (CI or Mac) | ⛔ Blocked | no Swift toolchain reachable here, see Blockers |
| P1 | Desktop app compiles and runs on macOS 15 | ⏳ Waiting on build route | — |
| P1 | Replay timing verified (previous N s + ~1.5 s) on a real Mac | ⏳ | needs a Mac session |
| P1 | Packaging: bundled renderer + FFmpeg, signed and notarized DMG | ⏳ | needs signing credentials |
| P2 | Polished website + browser studio | ✅ Done (on prototype backend) | pytest + Chromium end-to-end run |
| P2 | Vapor backend with API parity | ⏳ | needs build route |
| P3 | First smart-edit feature, measured on footage | ⏳ | — |

## Test evidence

| Suite | Where | Result |
|---|---|---|
| Renderer (`tests/`) | Linux workspace, Python 3.13, FFmpeg 6.1 | 5/5 pass |
| Website (`web/tests`): claims guardrails, security, upload → render → download | same | 7/7 pass |
| Studio in Chromium (`web/tests/e2e/drive_studio.py`): upload 3, split, drag-trim, drag-reorder, play, export | same | pass: 720×1280, 34.02 s = timeline length, audio, 0 console errors |
| Desktop ffmpeg pipelines (replay assembly, MKV remux, app-shaped manifest → renderer) | same, run by hand | pass: 1080×1920, 30 fps, audio |
| `swift-shared` tests | — | **not run** (no Swift toolchain) |
| `desktop/Core` tests | — | **not run** (no Swift toolchain) |
| Desktop app on macOS | — | **not run** |

## Blockers

1. **No Swift compiler in this workspace.** download.swift.org is blocked by the network
   policy, Ubuntu has no Swift package, and the GitHub CLI token is invalid. Plan: GitHub
   Actions (macOS 15 + Linux runners) on a repo the owner provides. Requested 2026-10-24.
2. **Real-Mac verification** of capture, permissions, voice and hotkey. Needs the owner to run
   builds, or a linked Mac session.
3. **Signing/notarization** needs the owner's Apple Developer credentials. No DMG link will be
   published until it exists.

## Decisions log

- 2026-10-24: Swift on both sides (owner). Desktop stays the SwiftUI v0.1 codebase (no Tauri).
  Web backend moves to Vapor 4; the browser UI stays HTML/CSS/JS served by Vapor.
- 2026-10-24: `ClipThatContracts` is the single manifest schema. Its validation now mirrors
  the renderer's real limits (≤100 clips, ≤120 s per clip, even 240–3840 px, 1–120 fps) and it
  writes an explicit `"music": null`. Clip `id` is required.
- The Python renderer remains the reference/oracle until a Swift-orchestrated renderer
  matches it on fixtures.

## Backlog carried from the two-team phase

- Renderer progress output (opt-in JSON lines) so the UIs can show real progress.
- Per-clip moment metadata (`trigger`, `trigger_offset_seconds`, `source`, `captured_at`):
  the main input for smart trimming.
- Use the raw-mic track (track 1) for ducking and for removing the spoken trigger.
- Packaging: bundle FFmpeg and the renderer runtime (or a Swift renderer) inside the app.
