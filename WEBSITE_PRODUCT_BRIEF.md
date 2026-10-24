# Clip That — CapCut-style web platform (scope addition)

Date: 2026-10-24
Status: Product-owner request accepted, local MVP implemented. **This is not yet a hosted SaaS.**

## Product direction
Clip That is no longer desktop-only. It has two primary interfaces that share the same creative engine:

- **Website / web studio** — public product site, upload/import video, basic timeline, clip ordering and trimming, preview, montage generation, and MP4 export. After MVP: accounts, saved cloud projects, payments, reusable edit templates, smart editing, and collaborative features.
- **Desktop companion** — Tauri 2 app with native capture helper. Enables hands-free, opt-in rolling capture, voice/keyboard command, import from existing recorders, local library and offline use. After MVP: optional sync to signed-in web account.

**Important:** saying “Clip that” refers to capturing the *previous* 30 seconds from an already-running, explicitly enabled replay buffer. A normal website cannot retroactively recover video of a screen it wasn't recording. Voice + replay remains desktop scope; web editing begins from user-provided files.

## Positioning
CapCut is a UX reference, not a template to clone. Clip That emphasizes transforming personally captured moments into edited montages with as little manual editing as possible, rather than replicating an entire general-purpose editing suite.

- Main initial user: gaming clip creators.
- Later categories: chess, educational demonstrations and other screen-recording scenarios.
- Homepage statement: “Clip the moment. Post the magic.”
- Differentiation hypothesis: voice-first capture + import workflow + creator-quality edits. This still requires real user validation.

## Website MVP — implemented locally in `web/`
- Responsive public marketing homepage.
- Browser studio UI including media library, basic clip timeline, reorder, trim controls, style/layout selection and format selection.
- File upload to local-only FastAPI backend; validates file extension and caps size at 250 MB.
- Uses the same **schema_version 1** clip manifest and the existing Python/FFmpeg renderer; no duplicated editing implementation.
- Download final portrait MP4.
- No login, payment, cloud hosting, account synchronization, voice recording, automated highlight selection, or actual preset transitions yet. Edit-style selections are labels, not implemented visual effects.

## Future website production architecture (proposal, not built)
- Frontend: React + TypeScript; evolve current demo into a structured application (e.g. Next.js) when production requirements justify it. Align shared React design tokens with Tauri client.
- Backend/API: authorized project and media endpoints, job-based render queue (FFmpeg workers), object storage with signed URLs, database and retention controls.
- Security: per-user authorization, uploads scanned and probed, request limits, media lifecycle management, server-side path isolation, rate limiting and quotas.
- Async rendering status/job cancellation, cost-aware billing and render limits.
- Privacy-first: don't auto-upload recorded desktop footage; explicit opt-in for cloud sync, visible capture status and ability to exclude sensitive windows.
- Full product review before public deployment: legal music licensing, brand/trademark checks for “Clip That,” account age/payment requirements, and terms.

## Folder ownership and collision prevention
- **ChatGPT owns** `web/`, `clipthat_editor/`, editing tests, landing page and future cloud API architecture.
- **Claude owns** `desktop/` including Tauri/Rust application, native recording/voice helper and desktop session UX.
- **Shared and frozen**: `examples/manifest.example.json` and render CLI, unless a proposal is reviewed and versioned.

Use sibling components; do not create a second render engine inside `desktop/` or `web/`.

## First integration milestone
1. Desktop can capture/import three clips locally.
2. Desktop saves `schema_version: 1` manifest and renders an MP4 with shared CLI.
3. Website can upload three files, modify simple trim/order and render with the same CLI.
4. Both outputs are compatible 9:16 MP4s.
5. Cross-device project sync is **phase 2** and is not implied by sharing the edit engine.
