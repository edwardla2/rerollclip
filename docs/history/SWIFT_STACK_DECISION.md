# ADR-002 — Swift-first web and desktop (2026-10-24)

**Status: ACCEPTED / supersedes ADR-001 (`ARCHITECTURE_DECISION.md`).**

Product owner specifically requests **Swift on both sides**: desktop and website/server. The existing Tauri and Python prototypes are historical compatibility baselines, **not** the intended production stack. Do not pretend the previously supplied prototype was already migrated.

## Final target architecture

| Subsystem | Target implementation | Owner |
|---|---|---|
| macOS desktop | **SwiftUI** + AppKit as needed | Claude |
| Replay capture | **ScreenCaptureKit** with opt-in, rolling buffer, exclusion controls | Claude |
| Voice/hotkey | On-device speech recognition and native keyboard shortcut | Claude |
| macOS packaging | Xcode project, signing, notarized DMG, update feed | Claude |
| Website backend/API | **Swift + Vapor 4** (stable series) | ChatGPT |
| Browser UI | Server-rendered HTML/CSS + minimal browser JavaScript for file inputs, video playback and drag-and-drop; prefer generated HTML/templates from Swift | ChatGPT |
| Shared data contracts | **Swift Package** `swift-shared/` (Codable schema v1) | ChatGPT; Claude consumes |
| Video rendering | Initially existing Python + FFmpeg process behind a Swift adapter, then migrate orchestration to Swift `Process` + FFmpeg, retaining test fixtures | ChatGPT |
| Optional future browser Swift | Swift/WebAssembly + JavaScriptKit, only if it proves better than standard browser interop | ChatGPT R&D |

**Important web constraint:** Native SwiftUI does not directly render an ordinary production website. A Swift/Vapor site is genuinely written in Swift on its server side, but browsers still use HTML/CSS and some JavaScript for interaction. Swift compiled to WebAssembly exists, but adopting it for the entire video-editing frontend would add risk and isn't necessary for a Swift-first product. We explicitly do **not** promise a 100% Swift browser UI today.

## Compatibility promise
- Keep `/examples/manifest.example.json` and `schema_version: 1` until both apps adopt `ClipThatContracts`.
- Keep the current Python render CLI working during migration. It is **not** a production-ready cloud rendering service.
- Do not change clip semantics: voice or hotkey saves the preceding 30 seconds plus about 1.5 s after; optional 15/45/60 second lengths; on-device recognition; opt-in recording; local-only by default. These are the latest **Claude-reported desktop v0.1** capabilities, not independently verified in this repository.
- Third-party compatibility means watching authorized folders for exports (MP4/MOV/MKV), not controlling OBS, Medal or Outplayed via official APIs.
- Browser upload is explicitly initiated by the user; website should not claim passive screen recording or retroactive captures.
- Do not expose unfinished features as shipping: no AI highlight selection, beat sync, captions, social publishing, Windows build, or signed DMG.

## Desktop transition
Claude's existing Tauri implementation may contain valuable functional logic/fixtures. Port features to SwiftUI incrementally rather than discarding verified code without parity. **Claude must confirm** current code/branch, what works, what changes, and which interfaces are affected. Native macOS 15+ is the first release. Cross-platform UI reuse is intentionally deprioritized.

## Website transition
ChatGPT owns migration of current `web/` FastAPI demo into `web-swift/` Vapor. Existing HTML/CSS and small JS can be temporarily reused, with Swift serving project/upload/render endpoints. The beta signup remains local/demo-only until hosting, disclosure and data-handling are completed. Signed DMG URL/update feed remains blocked on Claude's packaging task (CP-5).

## Production gates
1. Swift contracts decode the old v1 manifest (Swift package tests).
2. SwiftUI desktop preserves capture, on-device voice, permissions, imports, sessions and exports on a **real macOS 15+** device.
3. Vapor endpoints reproduce local upload -> manifest -> render -> MP4 download workflow (upload limits, authorization needed before public hosting).
4. Replace Python orchestration only after Swift rendering parity is tested with sample video/audio. FFmpeg itself may remain a separately bundled dependency.
5. Public website and DMG claims remain accurate to what actually ships.
