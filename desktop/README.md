# Clip That — macOS desktop app

Owner: Claude (desktop). The render engine in `../clipthat_editor` is ChatGPT's and is used
**unmodified** through its v0.1 CLI + manifest contract. The website and browser studio in
`../web` are also ChatGPT's. They share only that engine and contract with this app, not
code. Cross-device sync is phase 2.

**Stack:** native Swift/SwiftUI, by product-owner decision (2026-10-24). Kit documents that
still say Tauri are being corrected; see INTERFACE_NOTES CP-8.

## Quick start

```bash
desktop/scripts/bootstrap.sh        # brew deps, editor tests, core tests, generates the Xcode project
open desktop/ClipThat.xcodeproj     # then ⌘R (scheme ClipThat, destination My Mac)
desktop/scripts/make_test_clips.sh  # optional: 3 synthetic gameplay clips in ~/Movies/Clip That Test Clips
```

Requirements: macOS 15+, Xcode 16+, Homebrew (`ffmpeg`, `python`, `xcodegen`). Signing is
pinned to team `VXYH2JZJT3` in `project.yml` so macOS keeps the Screen Recording and
Microphone grants across rebuilds. After adding or removing Swift files, run `xcodegen generate`.

## First-run walkthrough (covers the integration gate)

1. Launch. The main window opens with an empty session list, and a scissors icon appears in the menu bar.
2. **⌘N** creates a session. **⌘I** (or drag files in) imports clips: MP4, MOV, M4V, or MKV/FLV/WebM (remuxed to MP4).
3. Select a clip to preview it, then set its in/out points. Drag rows to reorder. Delete or right-click → Remove sends the clip file to the Trash.
4. Pick a style and layout, optionally add music, then **Render Montage** (⌘R). When it finishes, use Preview, Export… (save anywhere) or the Finder button.

Capture (the capture and voice gates):

5. Flip **Replay buffer** on. macOS asks for Screen & System Audio Recording permission; it may ask you to reopen the app.
6. Press **⌃⌥C** anywhere, including over a full-screen game, or click **Clip That**. You'll hear a click, and about 2 s later a ~30 s clip appears in the selected session.
7. Flip **“Clip that”** on (Microphone + Speech Recognition prompts), then say *“Clip that”*.
8. Settings → Imports → Add Folder… watches a recorder's export folder (for OBS, its Recording Path). New files auto-import as **Import · ‹folder›**.

## Architecture

```
┌────────────────────────── Clip That.app (SwiftUI, macOS 15+) ──────────────────────────┐
│  Views: Sidebar · Clip list/inspector · Render bar · Capture bar · Menu bar · Settings │
│  AppModel (@MainActor): sessions, selection, render state, capture state, settings    │
│                                                                                        │
│  Triggers                     Capture                         Intake                   │
│  GlobalHotkey (Carbon)  ─┐    ReplayRecorder                  FolderScanner (poll 2s)  │
│  VoiceTrigger            ├─▶  ScreenCaptureKit → 2 s segments ClipImporter (copy/remux)│
│  (on-device SFSpeech +   │    (H.264 + PCM .mov, ring buffer) │                        │
│   PhraseSpotter)  ───────┘    → ClipAssembler (ffmpeg) ──────▶ SessionStore            │
│                                                               ~/Movies/Clip That/      │
│  Renderer ── writes manifest.json (schema v1) ── runs `python3 -m clipthat_editor` ──┐ │
└──────────────────────────────────────────────────────────────────────────────────────┼─┘
                                                                                       ▼
                                              clipthat_editor (ChatGPT, bundled as-is) → 9:16 MP4
```

* **`Core/` (Swift package `ClipThatCore`)** is Foundation-only and builds and tests on macOS
  or Linux. It holds the models, session store, manifest builder, renderer bridge, ffprobe and
  imports, folder scanner, replay segment bookkeeping, ffmpeg clip assembly, and phrase
  matching. `swift test` covers it, including an end-to-end render through the real editor.
* **`App/`** contains the macOS-only parts: SwiftUI, ScreenCaptureKit, AVFoundation, Speech, and Carbon hotkeys.
* **Why native SwiftUI instead of React + Tauri:** every hard part of this client is an Apple
  framework API: ScreenCaptureKit, mic capture, on-device speech, global hotkeys, and TCC
  permissions. A Tauri shell would still need a native Swift helper and a bridge for all of
  them. Portability comes from the editor contract: a future Windows client implements the
  same manifest + CLI against the same engine.

### Replay buffer design

* ScreenCaptureKit captures the main display at ≤1080p (720/1440 selectable), 30/60 fps,
  plus system audio and, optionally, the mic. Clip That's own windows and any user-excluded
  apps are filtered out.
* Samples are written as **2-second `.mov` segments**: H.264 at about 0.1 bit/pixel·frame,
  each segment starting on a keyframe, with PCM audio so joins are sample-accurate. They live
  in `~/Library/Caches/ClipThat/Replay/<run>/`. Old segments are deleted continuously; only
  about `buffer + post-roll + 6 s` stays on disk.
* **"Clip that"** waits a 1.5 s post-roll, so your reaction isn't cut off, closes the open
  segment, pins the segments covering the last 30 s, and runs ffmpeg. Video is stream-copied;
  audio is re-encoded to AAC. Track 0 is game audio (+ mic if mixing is on); track 1 is the
  raw mic. The result moves into the session as `clips/replay-<time>-<trigger>.mp4`.
* The buffer is wiped on stop, on capture errors, on quit and at launch. Nothing is uploaded, ever.

### Voice trigger

`SFSpeechRecognizer` with `requiresOnDeviceRecognition = true`. If on-device recognition
isn't available, the trigger reports **Unavailable** rather than falling back to Apple's
servers. `PhraseSpotter` fires when the count of "clip that" occurrences rises, with a 2.5 s
cooldown. Recognition tasks restart after each trigger and every 50 s. It only listens to the
mic, so a friend saying "clip that" on Discord, which arrives through system audio, won't fire it.

## Acceptance tests (CLAUDE_HANDOFF.md)

| # | Test | Status |
|---|------|--------|
| 1 | Explicit enable + visible indicators | Built: capture-bar switches with status pills, menu-bar icon (red dot while recording), macOS's own recording indicator |
| 2 | "Clip that" preserves the *preceding* video incl. audio; repeat triggers; naming/timestamps | Built: assembly pipeline verified with ffmpeg; live capture needs a run on your Mac |
| 3 | Import from a recorder's export folder without its SDK | Built: watched folders + manual import; MKV remux verified |
| 4 | 3 MP4s → one valid 9:16 MP4 | **Verified** end to end against the real editor (also automated in `EditorIntegrationTests`) |
| 5 | Preview, delete, reorder, export without sign-in | Built |
| 6 | Denied permission → clear, non-destructive recovery | Built: inline banner with Open System Settings / Try Again; Settings → Privacy shows each permission |
| 7 | Exclude sensitive windows / pause; never auto-upload | Built: per-app exclusion list (applies live), Pause/Resume, no network code at all |

## Verified vs. not yet verified

The build environment for this pass was Linux, so:

* **Verified here:** the editor's 5 tests (untouched); the exact ffmpeg commands the app uses
  for replay assembly (H.264 + 2 PCM tracks → MP4 with mixed + raw-mic tracks) and MKV remux;
  and those outputs plus an app-shaped `manifest.json` through `python3 -m clipthat_editor
  render` → 1080×1920, 30 fps, with audio.
* **Not yet compiled:** the Swift code. It was written against the macOS 15 SDK and reviewed by
  hand, but this is its first Xcode build. If Xcode reports errors, paste them back and I'll
  fix them. `swift test` in `desktop/Core` is the fastest first check.
* **Needs a real Mac session:** ScreenCaptureKit capture, permission prompts, the global
  hotkey over full-screen games, and voice accuracy while gaming.

## Known limitations (v0)

* Captures the main display only; no window or display picker yet.
* On a completely static screen, ScreenCaptureKit sends no frames, so a segment can run longer
  than 2 s and a clip may exceed 30 s. Gameplay is never static, so this rarely matters.
* Rendering shows elapsed time only, because the editor doesn't report progress (see INTERFACE_NOTES CP-1).
* Development builds use Homebrew's Python and FFmpeg. Shipping to creators needs those bundled (see CP-5).
* Hotkey presets only (⌃⌥C, ⌃⇧C, ⌥⇧C, F9); no custom recorder yet.
* English (US) voice recognition only.

## Files

```
desktop/
  project.yml                XcodeGen spec (app target + bundled editor copy phase)
  Core/                      ClipThatCore Swift package + tests
  App/ClipThatApp.swift      scenes: main window, menu bar extra, settings
  App/AppModel.swift         app state and actions
  App/Capture/               ReplayRecorder (ScreenCaptureKit + segment writer), Permissions
  App/Voice/                 VoiceTrigger
  App/Hotkey/                GlobalHotkey
  App/Views/                 SwiftUI views
  scripts/                   bootstrap.sh, make_test_clips.sh
  INTERFACE_NOTES.md         contract findings and change proposals for the editor team
```
