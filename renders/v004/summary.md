# Reroll render v004

- Length: 16.38 s, 1080x1920 @ 60 fps
- Measured: {'streams': 'stream|width=1080|height=1920|r_frame_rate=60/1; stream|r_frame_rate=0/0; format|duration=16.384000', 'loudness_lufs': '-14.0', 'true_peak_dbfs': '-2.9'}
- Song (preview only): -, None BPM, starts at 0.0 s of the sound; no drop used (candidate None s, n/a)
- Speed: real speed except play 1 skim 1 (4.00-5.64 s) 1.16x-4.62x; play 1 skim 2 (8.64-10.28 s) 1.16x-4.62x; play 1 window 3 (10.28-16.38 s) 0.40x-1.00x
- Taste: mode story, intensity medium

## Changes in this version

- New one-clip flow (what the app runs per Medal clip): clip 4 (ace) alone -> 16.4 s edit, game audio only
- No song, so no beat timing: short gaps between fights (about 4 s each here) are sped through smoothly (up to ~4.6x for an instant) instead of cut; the final kill keeps the black-and-white accent
- Speed-up: this render took 2 min 43 s on the 2-core cloud machine
- Unchanged: whole frame + blurred fill, game colours, watermark

## Shots

| # | Output | Source | Clip | Speeds | Framing |
|---|---|---|---|---|---|
| 1 | 0.00-4.00 | 11.15-15.15 | c4.mp4 | [1.0] | full |
| 2 | 4.00-5.64 | 15.15-19.25 | c4.mp4 | [1.16, 1.83, 2.91, 4.62] | full |
| 3 | 5.64-8.64 | 19.25-22.25 | c4.mp4 | [1.0] | full |
| 4 | 8.64-10.28 | 22.25-26.35 | c4.mp4 | [1.16, 1.83, 2.91, 4.62] | full |
| 5 | 10.28-16.38 | 26.35-31.95 | c4.mp4 | [0.4, 0.42, 0.44, 0.66, 1.0] | full |

## Effects (master keyframes, output time)

- flash: [(13.48, 0.1)]
- mono: [(13.53, 1.0), (14.13, 1.0)]

## Planner notes

- play 1: c4.mp4, 3 kills, framing full
- accent: final kill of play 1 at 13.480s

Kills land at (output s): [3.0, 7.64, 13.48]
