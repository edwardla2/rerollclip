# FOR CLAUDE — Clip That native Swift transition

**Owner's new architecture decision:** use Swift for the desktop and server-side web implementation. `SWIFT_STACK_DECISION.md` overrides the historical Tauri architecture. ChatGPT has created a tested `swift-shared/` Codable manifest package you can depend on.

## Your scope remains desktop only
1. Reassess desktop v0.1: report which features actually work, code paths, and macOS test evidence, then port to SwiftUI + AppKit only as necessary.
2. Target **macOS 15+**, **SwiftUI** front end, **ScreenCaptureKit** rolling buffer, OS-native voice recognition, and hotkey control.
3. Preserve behavior: "Clip that" captures ~30 seconds before + ~1.5 seconds after; alternative lengths 15/45/60 sec; proper buffer lifecycle; opt-in recording; on-device voice; exclusions; local-only storage and no account requirement.
4. Folder watcher can import user-selected OBS or other recorder exports in MP4/MOV/MKV. Do not claim direct APIs or control over these applications.
5. Use `swift-shared/` manifest v1 `ClipThatContracts` for editing sessions. The existing Python/FFmpeg CLI stays available as the initial renderer interface; do not fork or rewrite this engine.
6. Continue packaging CP-5, but the site Download button must remain beta/waitlist until a signed notarized DMG and stable URL actually exist.
7. Do not claim unfinished AI highlight detection, beat sync, captions, Windows, direct publishing, or hosted cloud sync.

## What ChatGPT owns
- `swift-shared/` shared model/validation and renderer contract.
- `web-swift/` planned Swift/Vapor server + web editing integration.
- Existing Python CLI and current browser prototype during migration; eventually refactor FFmpeg orchestration into Swift.
- Website messaging and signup prototype. Browser playback/upload UI can still use HTML/CSS and narrowly scoped JS; native SwiftUI is not directly available in ordinary browsers.

## Request on your next report
Provide exact source files and current branch, SwiftUI migration plan, how to build/test on macOS, status of voice and replay functionality (independently tested versus assumed), and any changes needed to manifest v1. Please don't continue implementing a Tauri UI as the production app after this instruction.
