# Clip That — coordination and roadmap

## Project goal
Turn any interesting on-screen moment into a creator-quality ready-to-post video with as little work as possible. First target: macOS gaming workflows. Expansion: chess, trading/education, other desktop activities.

## Roles
| Area | Owner | Deliverable |
|---|---|---|
| Product scope, MVP acceptance, asset contracts | ChatGPT | This starter kit, schema and QA |
| Local video-editing/rendering engine, iterative edit quality | ChatGPT | Python/FFmpeg CLI, presets, tests |
| Tauri 2 cross-platform shell, macOS onboarding and React/TypeScript UI | Claude | macOS desktop executable/app |
| Native Swift ScreenCaptureKit helper, explicit opt-in screen/audio replay recorder | Claude | Working last-30-sec buffer |
| Keyword/keyboard trigger, folder watch/import | Claude | Local clip event pipeline |
| Local session library + preview/export UX | Claude | Usable MVP |
| Landing page, creator pilot assets, pricing experiments | ChatGPT | Later pilot package |
| End-to-end user acceptance | Shared; user signs off | Demo videos and recordings |

## Phases and gates
1. **Integration gate:** Import three existing MP4 files into desktop UI; render and export via supplied manifest and editor CLI. No AI claims.
2. **Capture gate:** Local 30-second replay capture and keyboard shortcut; screen/mic permissions and privacy controls.
3. **Voice gate:** Local spoken keyword; reliable while gaming; reasonable false-trigger behavior.
4. **Quality gate:** User judges edits against CapCut/manual benchmarks using their own raw clips; iterate timing, framing, transitions, captions and (licensed) music.
5. **Pilot gate:** Invite 10 gaming creators to use it; measure export completion, actual posts, repeat usage, and willingness to pay.

## What isn't in MVP
- Fully autonomous posting to TikTok, Instagram or YouTube.
- Unverified official capture integrations for Medal, Outplayed, etc.
- Universal support for all desktop games or apps.
- Guaranteed AI highlight understanding or guaranteed viral clips.
- Continuous cloud upload or recording without consent.

## Handoff rules
- Keep desktop and editor in separate directories/packages in one repository.
- Changes to manifest version or CLI flags require agreement before merging.
- Exchange: 1) working files or PR, 2) exact run command, 3) fixture videos, 4) known limitations.
- User owns scope, branding, and final acceptance decisions.

## First measurable milestone
User imports their own gameplay moments, chooses a preset and generates an MP4 in under a minute of interaction (excluding device-dependent processing time). The video must play, be portrait-formatted, and keep usable audio.

## Website addition — 2026-10-24

**ChatGPT additionally owns `web/`**: public marketing page, local browser-based workspace, future authenticated cloud jobs, and integration with the same shared CLI. The existing website is a local MVP, not a deployment-ready cloud editor. Read `WEBSITE_PRODUCT_BRIEF.md`.

**Claude continues to own `desktop/`**: Tauri app, capture helper, local voice command, watched folders, and desktop import/editor integration. Do not duplicate `web/` or `clipthat_editor/`.

**Shared design principle:** Browser edits files the user uploads; desktop companion provides opted-in retrospective capture. Optional cloud sync is a separately designed later milestone.
