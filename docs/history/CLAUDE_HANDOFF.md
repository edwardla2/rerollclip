**LATEST DECISION (2026-10-24): Read `SWIFT_STACK_DECISION.md` first. Desktop is now native SwiftUI/AppKit on macOS 15+, NOT Tauri/React. Existing Tauri work should be used as a functional reference and ported carefully. Claude retains desktop/capture/voice/packaging ownership. The older details below are historical.**

# CLAUDE HANDOFF — Clip That desktop MVP

You are the desktop-app lead for **Clip That**, a creator tool for instantly capturing moments and turning them into ready-to-post edits. The user is the product owner. ChatGPT owns the editing engine, manifest contract, QA/test plans, and business/growth planning. **You own the macOS desktop client**: UI, recording, voice activation, clip intake, and editor integration. Do not rebuild the render engine; use the supplied Python CLI and jointly specified JSON manifest instead.

## Product vision (preserve these details)
- Spoken **"Clip that"** saves the **preceding** ~30 seconds, not footage starting after the command.
- Works with existing clipping software **where technically supported**, initially by importing locally exported MP4 files from user-selected folders. Do NOT claim to control third-party recorders that lack an API.
- Has its **own opt-in screen recording / rolling replay buffer** for workflows without an existing clipping tool.
- Users collect multiple highlights in a **session**. The key value is automatic generation of an editable, ready-to-post 9:16 MP4 montage; one-off edits are also useful.
- Future categories: gaming, chess, trading and other desktop workflows. For MVP, focus on **gaming clips**, keep architecture generalized.
- User values distinctive edit quality and creator-led distribution more than building an all-in-one general video editor.

## Ownership / nonoverlap
**Claude develops:** a Tauri 2 desktop client (React + TypeScript UI and Rust command bridge) plus a native Swift 5 macOS ScreenCaptureKit capture helper; transparent microphone permissions, voice phrase detection, opt-in rolling recording buffer, clip folder watcher/import, local session library, rendering job UX, error handling, onboarding, wiring to CLI, packaging. This stack is CONFIRMED by the product owner coordination decision: do not use a pure SwiftUI desktop shell.

**ChatGPT develops:** `clipthat_editor/` Python/FFmpeg CLI + presets and post-processing iterations, shared manifest format (contract below), editing-specific test cases, acceptance fixtures, product requirements, growth/pitch assets.

## Interfaces (frozen v0.1)
- The desktop app writes `manifest.json` with the shape in `examples/manifest.example.json`, using `schema_version: 1` and clip file paths that resolve relative to manifest location or as absolute paths.
- It invokes: `python -m clipthat_editor render /ABS/PATH/manifest.json --output /ABS/PATH/render.mp4` from a process with the editor module available. No hard-coded user-specific paths.
- `style`: `clean`, `cinematic`, or `high_energy`. `layout`: `fit_blur` or `center_crop`.
- When render exits 0, MP4 exists at requested output. On error, surface log clearly and leave session intact.
- Voice trigger and recording should work without a remote account, recording only when user has explicitly enabled it, with visible enabled status, mute/stop control, and no upload by default.
- Label third-party imports as **import**, not direct recorder control. Don't claim publisher APIs support capturing highlights unless verified.

## Desktop acceptance tests
1. User explicitly enables replay capture and microphone, and visible indicators show active state.
2. User says "Clip that"; the app preserves video immediately *before* the command, including audio where allowed; follow-on triggers produce additional clips, with sensible naming and timestamps.
3. User can import a clip from an existing recorder's exported folder without installing that software's SDK.
4. Three valid MP4s in a session produce one valid 9:16 MP4 after invoking renderer; video/audio playback is verified.
5. User can preview, delete, reorder, and export clips without signing in.
6. Denied screen/microphone permission leads to clear, non-destructive recovery UI.
7. A window containing sensitive financial/account details can be excluded or recording paused; never auto-upload recordings or publish outputs.

## Important implementation realities
- Validate macOS ScreenCaptureKit and permissions on the target macOS version; do not assume integration with system clip recording software.
- Hotword detection should be low-resource, local where feasible, and privacy-aware. Provide a keyboard hotkey fallback.
- Don't silently record a whole desktop session without consent; make replay buffer size and retention explicit.
- Optimize for fast local preview and reliability before AI effect complexity. The supplied editor is a **functional deterministic v0**, not a trained AI model.
- Communicate progress by reporting the app architecture, files created, command to run, integration demo, blockers, and exact changes to the JSON contract (propose changes; don't silently modify).

## First deliverable
Create a Tauri 2 + React/TypeScript macOS desktop skeleton with a session UI, folder import, render button wired to the manifest+CLI through Rust process invocation, and placeholder hotkey-based "Clip that" action. Then implement real replay buffer + opt-in voice trigger, preserving the API. Ensure these pieces work before adding custom UI polish.

## Confirmed technology decision (October 24, 2026)
Use **Tauri 2 + React/TypeScript + Rust desktop bridge**, with a **separate native Swift ScreenCaptureKit helper** for opt-in macOS rolling capture. Windows is a future target, not part of the first demo. Keep capture behind a platform interface so a later Windows helper can be added. Start with folder imports and the rendering integration; don't block the demo on voice recognition or capture permissions.

Developer note: the supplied editor uses Python and FFmpeg and is **not yet packaged as a macOS app sidecar**. In development, run the CLI with Python 3.10+ and FFmpeg/FFprobe on PATH; for release, coordinate bundling, codesigning, permissions and distribution. The desktop must not assume Python or FFmpeg will be preinstalled on end-user machines.

## ADDENDUM 2026-10-24 — Product owner requests a CapCut-style website

Clip That is now a **website + browser editor + optional desktop companion**, not only a macOS/Windows app. ChatGPT has implemented an early local working website in `web/` and owns all website work. Read `WEBSITE_PRODUCT_BRIEF.md` and `web/README.md`.

### Your scope is unchanged:
- Build Tauri 2 desktop client and the opt-in replay-buffer/voice capture system in `desktop/`.
- Integrate only with the existing manifest v1 and CLI. Do not rebuild the renderer or independently build the web editor.
- Keep project/clip naming compatible, and propose schema changes rather than silently modifying the contract.
- The browser editor works with uploaded media; the desktop captures moments before the command. Sync between them is **phase 2** and not required for desktop acceptance.
- The website is not public production SaaS; avoid claiming it has accounts, cloud sync, automatic AI effects or deployed hosting.
