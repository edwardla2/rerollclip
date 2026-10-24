# Clip That

Say **“Clip that”** and keep the moment you just had: the previous 30 seconds of your screen
plus about 1.5 s after. Collect clips into a session and turn them into a vertical,
ready-to-post edit, on a Mac or in the browser.

> One repository, one engineering owner (Claude). The active brief is
> [`docs/SINGLE_OWNER_HANDOFF.md`](docs/SINGLE_OWNER_HANDOFF.md). Live status, test evidence and
> blockers are in [`docs/STATUS.md`](docs/STATUS.md). Everything in `docs/history/` is superseded
> context from the earlier two-team phase.

## Repository layout

| Path | What it is | Stack |
|---|---|---|
| `desktop/` | macOS app: replay buffer, “Clip that” voice + hotkey, folder imports, sessions, render/export | SwiftUI · ScreenCaptureKit · Speech (macOS 15+) |
| `desktop/Core/` | Platform-independent app logic (sessions, imports, manifest, renderer bridge, replay bookkeeping) | Swift package |
| `swift-shared/` | **ClipThatContracts**: the schema-v1 manifest, the single definition used by the desktop app and the website | Swift package |
| `clipthat_editor/` | Renderer: trims, orders, frames to 9:16 (blur-fill or crop), mixes music, writes MP4 | Python + FFmpeg |
| `examples/manifest.example.json` | Reference schema-v1 manifest | JSON |
| `web/static/` | Landing page + studio (shared by both backends) | HTML/CSS/JS |
| `web-swift/` | Website backend (replaces `web/server.py`; compile pending) | Swift · Vapor 4 |
| `web/server.py` | Prototype backend, kept as the reference until Vapor passes in CI | FastAPI |
| `tests/` | Renderer tests | Python |
| `docs/` | Handoff, status, history | Markdown |

## What works today (and what doesn't)

**Working and tested in this repo:**
- Renderer: schema-v1 manifest → portrait MP4, with or without source audio, optional music.
- Website + studio: landing page, browser editor (timeline trim/split/reorder, live 9:16 preview, export), beta-interest form.
- Suggested trims: finds the loudest, visually busiest moment and trims around it (trigger-aware for replay clips). Verified on synthetic footage; real-footage evaluation pending.
- Desktop pipelines run through the real renderer: replay-segment assembly, MKV remux import, manifest generation.

**Written, awaiting first compile and test on macOS:**
- The SwiftUI desktop app: replay buffer, voice and hotkey triggers, permissions, watched folders, library, export.

**Not built yet, so it isn't advertised anywhere:** AI highlight detection, beat sync, captions,
Windows, social posting, cloud sync, and a signed desktop download.

## Run it

```bash
# Renderer tests
python3 -m unittest discover -s tests

# Website prototype (local only, binds to localhost)
python3 -m pip install -r web/requirements-dev.txt
python3 -m pytest -q
python3 -m uvicorn web.server:app --host 127.0.0.1 --port 8765

# Shared contracts and desktop core (needs Swift 6 / Xcode 16+)
(cd swift-shared && swift test)
(cd desktop/Core && swift test)

# macOS app
desktop/scripts/bootstrap.sh && open desktop/ClipThat.xcodeproj
```

Requirements: Python 3.10+, FFmpeg/FFprobe on PATH; for Swift parts, macOS 15 + Xcode 16+.

## Principles

- **Private by default.** Nothing records until you turn it on, speech is recognized
  on-device, the replay buffer is deleted when it stops, and nothing is uploaded unless you
  upload it yourself.
- **Honest claims.** Marketing copy only describes what ships; tests enforce key claims on the landing page.
- **One schema.** Every client builds its manifests through `ClipThatContracts`.
