**SUPERSEDED 2026-10-24: See `SWIFT_STACK_DECISION.md`. Product owner selected SwiftUI desktop + Swift/Vapor website. This document is historical.**

# Architecture decision: Tauri 2 + native capture helper

Date: 2026-10-24
Decision: Tauri v2 + React/TypeScript for the desktop UI; Rust commands for native filesystem/process operations; Swift ScreenCaptureKit helper for opt-in capture on macOS. Windows support is future scope, but shared UI makes expansion easier.

## Integration sequence
1. Extract this kit to a local folder. In the same project root, add `desktop/` for Tauri. Keep `clipthat_editor/` unmodified.
2. Build the React session UI: imports, reorder/remove clips, style/layout selector, render progress and export results.
3. Implement a Rust command to write a version-1 manifest and spawn the existing Python CLI with absolute paths in **development mode**. Surface JSON stdout on success and JSON stderr on failures. Do not interpolate user file paths through a shell string.
4. Verify import-three-clips > manifest > FFmpeg render > preview/export locally.
5. Add an opt-in native macOS capture helper behind an interface, with explicit status, pause/stop, sensible rolling-buffer retention and controls to avoid recording sensitive windows. Start with a keyboard trigger; then add local voice trigger.
6. Before distributing to users, plan a packaged editor/runtime/FFmpeg sidecar, macOS entitlements, notarization and permissions. A working development CLI does **not** equal a distributable `.app`.

## Fixed editor contract
`python -m clipthat_editor render /ABS/PATH/manifest.json --output /ABS/PATH/output.mp4`

The manifest is `schema_version: 1`; see `examples/manifest.example.json` for exact fields. Paths are relative to manifest or absolute. Clip entries have `file`, `start_seconds`, `duration_seconds`; use `style` (`clean`, `cinematic`, `high_energy`), `layout` (`fit_blur`, `center_crop`), and output `width`, `height`, `fps`. `music` is null or a file/volume object. Current presets are accepted as labels but not yet different AI edit styles.

## Ownership
Claude: everything under `desktop/` plus capture helper and recorder integrations.
ChatGPT: everything under `clipthat_editor/`, `tests/`, schema & end-to-end editor acceptance.
Shared: integration changes proposed before changing schema/CLI.

## Honest technical limitations
The desktop and voice/capture system are not included in this starter. The included video editor is deterministic and does not currently select highlights, sync to beats, or produce complex stylistic effects. Do not market these unfinished features as shipped.
