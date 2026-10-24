# Clip That — Single-owner handoff to Claude

**Date:** 2026-10-24  
**Authority:** This document supersedes all earlier ChatGPT/Claude ownership divisions, roadmaps, and stack descriptions wherever they conflict. Claude is the **sole engineering and product implementation owner** from now on. ChatGPT will not maintain an independent branch or deliver separate components.

## Product vision

**Clip That** is a privacy-first, voice-triggered clipping and editing platform with a native macOS desktop app plus a CapCut-inspired website/editor. Users capture moments as they happen by saying **“Clip that”** or using a hotkey, collect clips into a session, then create finished vertical short-form videos. Capture should extend beyond games to any expressly selected desktop workflow, including chess, demonstrations, or market-chart commentary, provided sensitive information is protected.

The desktop app also provides optional **opt-in recording**, a rolling buffer, and **read-only folder watching** to import files created by other recording applications. Website users can manually upload their own footage and edit/export videos without installing the desktop app. A future goal is genuinely useful automated montage editing, not merely capture.

## Existing code in this archive — verified locally vs reported elsewhere

- `clipthat_editor/`: Python/FFmpeg **deterministic** renderer supporting trimming, ordering, vertical `fit_blur`/`center_crop`, optional local soundtrack, MP4 export. This is a **working compatibility reference**, not an AI montage engine and not yet Swift.
- `examples/manifest.example.json`: current `schema_version: 1` manifest reference.
- `tests/`: existing renderer validation and render tests. Prior local run reported 5 passing tests; rerun in your environment.
- `web/`: experimental FastAPI + HTML/CSS/JS landing page and browser editor with local upload/render/download. **Not a deployed production website**; not Swift/Vapor yet.
- `swift-shared/`: initial Swift Codable manifest contracts. Prior local run reported 4 passing Swift contract tests; rerun.
- `WEBSITE_PRODUCT_BRIEF.md`, `SWIFT_STACK_DECISION.md`, `CLAUDE_SWIFT_MIGRATION_BRIEF.md`, etc.: historical context. Use this file when instructions differ.
- **Claude desktop v0.1:** user reports Claude already built desktop code with working capture, voice and imports, but **that desktop source may be in Claude's workspace and is not part of this archive**. Inspect actual desktop files and verify on macOS before making shipping claims.

## Latest desktop product facts (reported by Claude, not independently verified by ChatGPT)

**Current reported features:**
- “Clip that” voice trigger or hotkey saves previous 30 seconds and ~1.5 seconds afterward; selectable preceding 15, 45, or 60 seconds.
- Works over full-screen games.
- Read-only watches selected export folders for MP4/MOV/MKV; works with an OBS export folder or any app saving supported files. This is **not** an official integration/control API.
- Sessions, trim/reorder, 9:16 vertical MP4 export.
- Local, private by default: on-device speech recognition, recording disabled until explicitly enabled, buffer deleted when stopped, per-app exclusions, no uploads or account required.
- macOS 15+ target.

**Not yet shipping, and cannot be advertised as shipping:**
- AI highlight detection, beat synchronization, automatic captions, full AI edit quality.
- Windows support; official Medal/Outplayed/ShadowPlay APIs; direct posting to TikTok/Instagram/YouTube.
- Signed and notarized DMG or stable desktop download URL; packaging awaits bundling decision for Python/FFmpeg (`CP-5` in Claude's `INTERFACE_NOTES.md`). Until available, website CTA must be **beta interest / waitlist**, not a fake executable download.

## Final technology direction

User expressly wants **Swift on both sides**.

- macOS: native **SwiftUI + AppKit as needed**, **ScreenCaptureKit** for opt-in capture, on-device speech recognition / hotkeys.
- Web backend/API: **Swift + Vapor**; browser UI can be conventional HTML/CSS plus the minimum JS needed for rich editor interactions. Don't falsely claim SwiftUI runs in the browser.
- Shared domain schema: **Swift Codable models** via `swift-shared/`, keeping schema v1 compatibility until safely migrated.
- Rendering: use the existing Python/FFmpeg reference as a test oracle initially; migrate orchestration to Swift, with FFmpeg permitted for encoding/composition. Avoid rewriting functional pieces before equivalent tests pass.
- One repo, one owner; choose pragmatic implementations that actually build and pass tests. If native existing Claude desktop code is still Tauri, audit it and migrate incrementally to SwiftUI with behavior parity, rather than discarding working functionality.

## Prioritized delivery plan

**P0 — Inventory & working baseline**
1. Inspect this archive and Claude's desktop workspace; identify actual source paths, git branch, completed features, broken pieces, prerequisites.
2. Run current Swift contract + renderer tests; test current desktop on actual macOS 15+ where available.
3. Establish a single canonical repo tree and update README to this single-owner scope; remove conflicting historical instructions from the active entry point.

**P1 — Integrated native macOS release candidate**
1. Preserve capture, on-device voice/hotkey, permissions, replay buffer, read-only watched folders, session library, trim/reorder, export.
2. Make desktop build, render, and export a playable 9:16 MP4 using a stable shared schema.
3. Keep privacy guarantees verifiable: no recording before opt-in; no silent uploads; clear exclusion controls; no sensitive windows in exports.
4. Decide FFmpeg/Python bundling; package signed/notarized DMG when the signing credentials and real macOS environment are available (never invent signing success).

**P2 — Real website**
1. Port local web prototype to a **Vapor** app and build a polished, CapCut-inspired homepage and studio UI.
2. Allow explicitly uploaded clips, trim/reorder, preview, render, download. No claim of AI editing until implemented and tested.
3. Show beta signup CTA until DMG URL exists. Do not present a local demo form as a working cloud waitlist.
4. Set actual authentication, storage retention, upload limits, secure processing and deletion controls before public deployment; avoid uploading local clips without user's initiation.

**P3 — Editing quality differentiator**
1. Add editing presets, intelligent suggestions/curation (with explicit opt-in where appropriate), quality-controlled transitions, effects and beat-synced assembly.
2. Benchmark output on real user-authorized sample footage against CapCut/Medal/Eklipse, not synthetic screenshots. Provide a manual fallback.
3. Only introduce cloud project sync, paid subscriptions, social publishing, official recorder APIs, Windows support after P1/P2 are sound.

## Acceptance criteria

- From macOS screen capture OR preexisting authorized clip file -> session -> trim/reorder -> 1080x1920 MP4 export with correct audio; replay buffer timing verified (previous N seconds + approx. 1.5s after).
- User controls recording and exclusions; no local clip is uploaded unless they explicitly choose web upload or future sync.
- Web uploader can import and produce downloadable videos; running source and tests supplied; mobile-friendly landing page with accurate claims.
- `swift-shared` decodes schema v1 manifests; migration does not silently break old clip sessions.
- No mocked features advertised as complete. Record tests run, tests not run, platform limitations, and blockers.

## Claude's authority and reporting

Claude owns product architecture, desktop, website, renderer, QA, packaging and deployment moving forward. Make reasonable decisions autonomously; do not bounce routine decisions back to ChatGPT. Ask the user only for choices requiring user authorization, credentials, access, or critical product scope. Prioritize a real working MVP over impressive mockups.

Start by auditing the files, then implement. After each milestone report: code/files changed, commands to run, tests passed/failed, demo path or build instructions, remaining blockers. Do not claim unverified functionality.

## Branding and marketing guardrails

Name is **Clip That** (provisional; investigate conflicts before commercial launch). Positioning: "Capture the moment. Make the edit." Voice clip triggers already exist in other products, so differentiation must come from edit quality and workflow, not a claim of invented voice capture. Use copyright-cleared music/assets and proper licensing for creator footage. Product is accessible to gaming creators first, and extensible to chess / screen-recording creators.

## Project handoff

**No further shared-work contract:** Do not await ChatGPT implementation, prompts, or a joint API review. Claude owns both sides and should adjust the contract as needed, preserving migration tests.
